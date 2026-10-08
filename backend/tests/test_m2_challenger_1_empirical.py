# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Empirical Adversarial Challenge Test Harness for Milestone 2 (AuthPort & SqlAuthAdapter).

Challenger: challenger_m2_1
Target: Hexagonal AuthPort & SqlAuthAdapter

Probes:
1. Registration & Authentication with valid vs invalid passwords.
2. Case-sensitivity in username authentication: probe for uppercase username login failures.
3. Timing attack protection: constant-time dummy verify on user lookup misses.
4. Expired session rejection and physical database purge.
5. Single session revocation vs cascade revocation.
6. User disable cascade session revocation.
7. Single-use password reset token enforcement and used_at invalidation.
8. Cascade session revocation upon password reset.
9. Expired password reset token rejection.
10. Password complexity validation during reset without consuming the token.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import time
from unittest.mock import MagicMock
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from carefold.auth.adapters.sql_adapter import SqlAuthAdapter, _DUMMY_HASH, _hash_token
from carefold.auth.ports import (
    AuthPort,
    RegisterUserRequest,
    SessionToken,
    UserProfile,
    UserUpdate,
    ValidatedSession,
)
from carefold.db.models import PasswordReset, Session, User
from carefold.db.session import create_db_engine, get_session_factory, init_db


@pytest.fixture
async def sql_session_factory():
    """Sets up an isolated in-memory SQLite database and returns session factory."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest.fixture
def sql_auth_adapter(sql_session_factory: async_sessionmaker[AsyncSession]):
    """Instantiates SqlAuthAdapter backed by the isolated test database."""
    return SqlAuthAdapter(session_factory=sql_session_factory)


# ==============================================================================
# PROBE 1: USER REGISTRATION & AUTHENTICATION
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_1_auth_valid_and_invalid_passwords(sql_auth_adapter: SqlAuthAdapter):
    """Empirical probe: verify authentication with valid vs invalid passwords and email casing."""
    user = await sql_auth_adapter.register_user(
        email="doctor.smith@carefold.local",
        username="drsmith",
        password="SuperSecretPassword123!",
        full_name="Dr. Smith",
        role="steward",
    )

    assert user.id is not None
    assert user.email == "doctor.smith@carefold.local"
    assert user.username == "drsmith"

    # 1. Valid password succeeds and updates last_login_at
    auth_ok = await sql_auth_adapter.authenticate("drsmith", "SuperSecretPassword123!")
    assert auth_ok is not None
    assert auth_ok.id == user.id
    assert auth_ok.last_login_at is not None

    # 2. Invalid password returns None
    auth_bad_pw = await sql_auth_adapter.authenticate("drsmith", "IncorrectPassword123!")
    assert auth_bad_pw is None

    # 3. Case-insensitive email login succeeds
    auth_email_upper = await sql_auth_adapter.authenticate("DOCTOR.SMITH@CAREFOLD.LOCAL", "SuperSecretPassword123!")
    assert auth_email_upper is not None
    assert auth_email_upper.id == user.id

    # 4. Whitespace trimming in login identifier
    auth_whitespace = await sql_auth_adapter.authenticate("   drsmith   ", "SuperSecretPassword123!")
    assert auth_whitespace is not None
    assert auth_whitespace.id == user.id

    # 5. Non-existent user returns None
    auth_nonexistent = await sql_auth_adapter.authenticate("nonexistent_user", "SuperSecretPassword123!")
    assert auth_nonexistent is None


# ==============================================================================
# PROBE 2: CASE-SENSITIVITY IN USERNAME AUTHENTICATION (BUG REPRODUCTION)
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_2_username_case_sensitivity_defect(sql_auth_adapter: SqlAuthAdapter):
    """Empirical probe: verify if user registering with uppercase letters in username can authenticate.
    
    Bug hypothesis:
    In SqlAuthAdapter.register_user:
        norm_username = resolved_username.strip()  # Case is preserved: 'AliceSmith'
    In SqlAuthAdapter.authenticate:
        norm_query = username_or_email.strip().lower()  # Forced to lowercase: 'alicesmith'
        stmt = select(User).where(or_(User.email == norm_query, User.username == norm_query))
    Because User.username is 'AliceSmith' and norm_query is 'alicesmith', SQL comparison fails!
    The user can NEVER authenticate using their username!
    """
    user = await sql_auth_adapter.register_user(
        email="alice.smith@carefold.local",
        username="AliceSmith",
        password="ValidPassword123!",
    )
    assert user.username == "AliceSmith"

    # Attempt 1: Authenticate with the exact username used during registration ("AliceSmith")
    auth_exact = await sql_auth_adapter.authenticate("AliceSmith", "ValidPassword123!")

    # Attempt 2: Authenticate with lowercase version of username ("alicesmith")
    auth_lower = await sql_auth_adapter.authenticate("alicesmith", "ValidPassword123!")

    # Check if either username authentication succeeded
    # If the bug exists, BOTH will be None!
    # User can only authenticate via email:
    auth_email = await sql_auth_adapter.authenticate("alice.smith@carefold.local", "ValidPassword123!")
    assert auth_email is not None, "Email authentication should succeed"

    # We assert that username authentication works as a user would expect:
    # A user who registered as "AliceSmith" expects to log in with "AliceSmith"!
    # If this fails, the bug is empirically confirmed!
    assert auth_exact is not None, (
        "CRITICAL DEFECT DETECTED: User registered with username 'AliceSmith' cannot authenticate "
        "using 'AliceSmith'! SqlAuthAdapter.authenticate lowercases query to 'alicesmith' but "
        "compares against non-lowercased User.username column without func.lower()."
    )


# ==============================================================================
# PROBE 3: TIMING ATTACK PROTECTION (CONSTANT-TIME DUMMY VERIFY)
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_3_timing_attack_protection_dummy_verify(sql_session_factory):
    """Empirical probe: verify constant-time dummy verification is invoked on user lookup misses."""
    mock_hasher = MagicMock()
    mock_hasher.verify.return_value = False

    adapter = SqlAuthAdapter(session_factory=sql_session_factory, hasher=mock_hasher)

    # 1. Non-existent user lookup miss
    result = await adapter.authenticate("missing_user_uuid_9999", "attempted_password")
    assert result is None

    # Verify mock_hasher.verify was called with the dummy hash
    assert mock_hasher.verify.called
    assert mock_hasher.verify.call_args[0][0] == "attempted_password"
    assert mock_hasher.verify.call_args[0][1] == _DUMMY_HASH


@pytest.mark.asyncio
async def test_probe_3b_timing_attack_protection_empirical_measurements(sql_auth_adapter: SqlAuthAdapter):
    """Empirical probe: measure real execution duration of non-existent user vs wrong password.
    
    Both paths must execute OWASP Argon2id password verification, resulting in comparable
    runtimes (typically tens of milliseconds), preventing timing-based user enumeration.
    """
    await sql_auth_adapter.register_user(
        email="existing.probe@carefold.local",
        username="existingprobe",
        password="ValidPassword123!",
    )

    # Warm up hasher / JIT
    await sql_auth_adapter.authenticate("existingprobe", "WarmupWrongPassword123!")

    # Measure non-existent user authentication (runs dummy hash verify)
    t0 = time.perf_counter()
    res_nonexistent = await sql_auth_adapter.authenticate("nonexistent_user_for_timing", "TestPassword123!")
    dur_nonexistent = time.perf_counter() - t0
    assert res_nonexistent is None

    # Measure existing user with wrong password (runs actual hash verify)
    t1 = time.perf_counter()
    res_wrong_pw = await sql_auth_adapter.authenticate("existingprobe", "TestPassword123!")
    dur_wrong_pw = time.perf_counter() - t1
    assert res_wrong_pw is None

    # Both operations should take significant time (> 5ms) due to Argon2id memory-hard hashing
    # In an insecure system without dummy verification, non-existent user would return in < 0.5ms.
    assert dur_nonexistent > 0.005, (
        f"Non-existent user authentication took only {dur_nonexistent*1000:.2f}ms! "
        "Expected Argon2id dummy verification duration (> 5ms)."
    )
    assert dur_wrong_pw > 0.005, (
        f"Wrong password authentication took only {dur_wrong_pw*1000:.2f}ms!"
    )

    # The timing ratio should be within reasonable bounds (order of magnitude)
    ratio = dur_nonexistent / dur_wrong_pw if dur_wrong_pw > 0 else 1.0
    assert 0.2 <= ratio <= 5.0, (
        f"Timing disparity detected between non-existent user ({dur_nonexistent*1000:.2f}ms) "
        f"and wrong password ({dur_wrong_pw*1000:.2f}ms). Ratio: {ratio:.2f}"
    )


# ==============================================================================
# PROBE 4: EXPIRED SESSION REJECTION & PHYSICAL DATABASE PURGE
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_4_session_expiration_and_db_purge(sql_auth_adapter: SqlAuthAdapter):
    """Empirical probe: verify expired sessions return None and are physically deleted from DB."""
    user = await sql_auth_adapter.register_user(
        email="session.expire@carefold.local",
        username="sessionexpire",
        password="ValidPassword123!",
    )

    # 1. Create session expired 10 seconds ago
    token_expired = await sql_auth_adapter.create_session(user.id, duration_seconds=-10)
    raw_token_exp = token_expired.token
    token_hash_exp = token_expired.session_id

    # Verify session was initially recorded in the database
    factory = sql_auth_adapter._get_session_factory()
    async with factory() as s:
        db_s = await s.get(Session, token_hash_exp)
        assert db_s is not None, "Session was not inserted into database"

    # 2. Validate session -> Must return None because it is expired
    validated = await sql_auth_adapter.validate_session(raw_token_exp)
    assert validated is None, "Expired session was incorrectly accepted!"

    # 3. Verify session was physically purged from the database
    async with factory() as s:
        db_s_after = await s.get(Session, token_hash_exp)
        assert db_s_after is None, "Expired session was not purged from the database upon failed validation!"

    # 4. Verify valid session works and updates last_active_at
    token_valid = await sql_auth_adapter.create_session(user.id, duration_seconds=3600)
    validated_valid = await sql_auth_adapter.validate_session(token_valid.token)
    assert validated_valid is not None
    assert validated_valid.id == user.id
    assert validated_valid.session.id == token_valid.session_id


# ==============================================================================
# PROBE 5: SINGLE SESSION REVOCATION VS CASCADE REVOCATION
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_5_single_session_vs_cascade_revocation(sql_auth_adapter: SqlAuthAdapter):
    """Empirical probe: verify revoke_session targets 1 session while revoke_all_sessions clears all."""
    user1 = await sql_auth_adapter.register_user(
        email="user1.sessions@carefold.local",
        username="user1sessions",
        password="ValidPassword123!",
    )
    user2 = await sql_auth_adapter.register_user(
        email="user2.sessions@carefold.local",
        username="user2sessions",
        password="ValidPassword123!",
    )

    # User 1 creates 3 sessions (e.g., mobile, desktop, laptop)
    s1 = await sql_auth_adapter.create_session(user1.id, user_agent="Mobile")
    s2 = await sql_auth_adapter.create_session(user1.id, user_agent="Desktop")
    s3 = await sql_auth_adapter.create_session(user1.id, user_agent="Laptop")

    # User 2 creates 1 session
    s_other = await sql_auth_adapter.create_session(user2.id, user_agent="User2Desktop")

    # 1. Single session revocation on s1
    revoked_s1 = await sql_auth_adapter.revoke_session(s1.token)
    assert revoked_s1 is True

    # s1 is now invalid
    assert await sql_auth_adapter.validate_session(s1.token) is None
    # Subsequent revocation of already-revoked s1 returns False
    assert await sql_auth_adapter.revoke_session(s1.token) is False

    # s2 and s3 of user1 remain active
    assert await sql_auth_adapter.validate_session(s2.token) is not None
    assert await sql_auth_adapter.validate_session(s3.token) is not None

    # s_other of user2 remains active
    assert await sql_auth_adapter.validate_session(s_other.token) is not None

    # 2. Cascade revocation: revoke_all_sessions for user1
    revoked_count = await sql_auth_adapter.revoke_all_sessions(user1.id)
    assert revoked_count == 2, f"Expected 2 remaining sessions revoked, got {revoked_count}"

    # All user1 sessions are now revoked
    assert await sql_auth_adapter.validate_session(s2.token) is None
    assert await sql_auth_adapter.validate_session(s3.token) is None

    # User 2 session is STILL active (unaffected by user1 cascade)
    assert await sql_auth_adapter.validate_session(s_other.token) is not None


# ==============================================================================
# PROBE 6: USER DISABLED CASCADE SESSION REVOCATION
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_6_disabled_user_cascades_session_revocation(sql_auth_adapter: SqlAuthAdapter):
    """Empirical probe: verify disabling a user immediately revokes all their active sessions."""
    user = await sql_auth_adapter.register_user(
        email="disable.target@carefold.local",
        username="disabletarget",
        password="ValidPassword123!",
    )

    sess_a = await sql_auth_adapter.create_session(user.id)
    sess_b = await sql_auth_adapter.create_session(user.id)

    assert await sql_auth_adapter.validate_session(sess_a.token) is not None
    assert await sql_auth_adapter.validate_session(sess_b.token) is not None

    # Update user status to disabled
    updated = await sql_auth_adapter.update_user(user.id, status="disabled")
    assert updated is not None
    assert updated.status == "disabled"

    # Both active sessions must be immediately revoked
    assert await sql_auth_adapter.validate_session(sess_a.token) is None
    assert await sql_auth_adapter.validate_session(sess_b.token) is None

    # Verify sessions are deleted from DB
    factory = sql_auth_adapter._get_session_factory()
    async with factory() as s:
        count = await s.scalar(select(Session).where(Session.user_id == user.id))
        assert count is None, "Sessions were not deleted when user was disabled"


# ==============================================================================
# PROBE 7: PASSWORD RESET STRICT SINGLE-USE & INVALIDATION UPON CONSUMPTION
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_7_password_reset_strict_single_use(sql_auth_adapter: SqlAuthAdapter):
    """Empirical probe: verify reset tokens are strictly single-use and marked used_at."""
    user = await sql_auth_adapter.register_user(
        email="reset.user@carefold.local",
        username="resetuser",
        password="OldInitialPassword123!",
    )

    # 1. Generate reset token
    raw_token = await sql_auth_adapter.create_password_reset_token("reset.user@carefold.local")
    assert raw_token is not None

    # Verify token record in database has used_at == None
    token_hash = _hash_token(raw_token)
    factory = sql_auth_adapter._get_session_factory()
    async with factory() as s:
        entry = await s.get(PasswordReset, token_hash)
        assert entry is not None
        assert entry.used_at is None

    # 2. First consumption: must succeed
    first_attempt = await sql_auth_adapter.reset_password(raw_token, "BrandNewPassword123!")
    assert first_attempt is True

    # Verify used_at was set upon consumption
    async with factory() as s:
        entry_after = await s.get(PasswordReset, token_hash)
        assert entry_after is not None
        assert entry_after.used_at is not None

    # 3. Second consumption: MUST FAIL (strictly single-use)
    second_attempt = await sql_auth_adapter.reset_password(raw_token, "AttemptTwoPassword123!")
    assert second_attempt is False, "Single-use reset token was accepted a second time!"

    # 4. Old password cannot authenticate; new password authenticates
    assert await sql_auth_adapter.authenticate("reset.user@carefold.local", "OldInitialPassword123!") is None
    assert await sql_auth_adapter.authenticate("reset.user@carefold.local", "BrandNewPassword123!") is not None


# ==============================================================================
# PROBE 8: PASSWORD RESET CASCADE REVOKES ALL ACTIVE SESSIONS
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_8_password_reset_cascade_revokes_all_sessions(sql_auth_adapter: SqlAuthAdapter):
    """Empirical probe: verify consuming a reset token revokes all active sessions for that user."""
    user = await sql_auth_adapter.register_user(
        email="compromised.user@carefold.local",
        username="compromiseduser",
        password="CompromisedPassword123!",
    )

    # User has 3 active sessions across different devices
    sess1 = await sql_auth_adapter.create_session(user.id, user_agent="Device1")
    sess2 = await sql_auth_adapter.create_session(user.id, user_agent="Device2")
    sess3 = await sql_auth_adapter.create_session(user.id, user_agent="Device3")

    assert await sql_auth_adapter.validate_session(sess1.token) is not None
    assert await sql_auth_adapter.validate_session(sess2.token) is not None
    assert await sql_auth_adapter.validate_session(sess3.token) is not None

    # User triggers password reset and consumes token
    reset_token = await sql_auth_adapter.create_password_reset_token("compromised.user@carefold.local")
    assert reset_token is not None
    reset_ok = await sql_auth_adapter.reset_password(reset_token, "SecuredPassword2026!")
    assert reset_ok is True

    # ALL 3 previous sessions must be revoked immediately
    assert await sql_auth_adapter.validate_session(sess1.token) is None, "Session 1 survived password reset!"
    assert await sql_auth_adapter.validate_session(sess2.token) is None, "Session 2 survived password reset!"
    assert await sql_auth_adapter.validate_session(sess3.token) is None, "Session 3 survived password reset!"


# ==============================================================================
# PROBE 9: EXPIRED PASSWORD RESET TOKEN REJECTION
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_9_expired_password_reset_token_rejected(sql_auth_adapter: SqlAuthAdapter):
    """Empirical probe: verify expired password reset tokens cannot be consumed."""
    user = await sql_auth_adapter.register_user(
        email="expired.reset@carefold.local",
        username="expiredreset",
        password="OriginalPassword123!",
    )

    # Generate token with negative expiry
    token = await sql_auth_adapter.create_password_reset_token(
        "expired.reset@carefold.local",
        expiry_minutes=-10,
    )
    assert token is not None

    # Consumption must fail
    res = await sql_auth_adapter.reset_password(token, "NewPasswordForExpired123!")
    assert res is False, "Expired password reset token was accepted!"

    # Original password still active
    auth = await sql_auth_adapter.authenticate("expired.reset@carefold.local", "OriginalPassword123!")
    assert auth is not None


# ==============================================================================
# PROBE 10: PASSWORD COMPLEXITY DURING RESET DOES NOT CONSUME TOKEN
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_10_reset_complexity_validation_preserves_token(sql_auth_adapter: SqlAuthAdapter):
    """Empirical probe: verify invalid new password raises ValueError without consuming token."""
    user = await sql_auth_adapter.register_user(
        email="retry.reset@carefold.local",
        username="retryreset",
        password="InitialPassword123!",
    )

    token = await sql_auth_adapter.create_password_reset_token("retry.reset@carefold.local")
    assert token is not None

    # Attempt reset with short password (< 10 chars)
    with pytest.raises(ValueError, match="at least 10 characters"):
        await sql_auth_adapter.reset_password(token, "short")

    # Verify token was NOT consumed
    token_hash = _hash_token(token)
    factory = sql_auth_adapter._get_session_factory()
    async with factory() as s:
        entry = await s.get(PasswordReset, token_hash)
        assert entry is not None
        assert entry.used_at is None, "Token was marked used despite ValueError"

    # Subsequent attempt with valid password must succeed
    retry_ok = await sql_auth_adapter.reset_password(token, "ValidLongNewPassword123!")
    assert retry_ok is True
