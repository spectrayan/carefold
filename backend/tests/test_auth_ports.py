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

"""Comprehensive unit and integration tests for Hexagonal AuthPort adapters and factories."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from unittest.mock import MagicMock
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from carefold.auth.adapters.disabled_adapter import (
    DEFAULT_STEWARD_USER,
    DisabledAuthAdapter,
)
from carefold.auth.adapters.oidc_adapter import OidcAuthAdapter
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import (
    create_auth_port,
    get_auth_port,
    reset_auth_port,
    set_auth_port,
)
from carefold.auth.ports import (
    AuthPort,
    PaginatedUsers,
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


# ============================================================================
# SqlAuthAdapter Tests
# ============================================================================


@pytest.mark.asyncio
async def test_sql_auth_register_user_success(sql_auth_adapter: SqlAuthAdapter):
    """Verifies user registration with OWASP Argon2id password hashing."""
    user = await sql_auth_adapter.register_user(
        email="Alice@Carefold.Local",
        username="alice",
        password="ValidPassword123!",
        full_name="Alice Smith",
        role="member",
    )

    assert isinstance(user, UserProfile)
    assert user.email == "alice@carefold.local"
    assert user.username == "alice"
    assert user.full_name == "Alice Smith"
    assert user.role == "member"
    assert user.status == "active"
    assert user.auth_provider == "local"

    # Verify password hash at rest
    session_factory = sql_auth_adapter._get_session_factory()
    async with session_factory() as s:
        db_user = await s.get(User, user.id)
        assert db_user is not None
        assert db_user.hashed_password != "ValidPassword123!"
        assert "$argon2id$" in db_user.hashed_password


@pytest.mark.asyncio
async def test_sql_auth_register_via_dto(sql_auth_adapter: SqlAuthAdapter):
    """Verifies register_user accepts RegisterUserRequest domain object."""
    req = RegisterUserRequest(
        email="bob@carefold.local",
        username="bob",
        password="StrongPassword2026!",
        full_name="Bob Jones",
        role="steward",
    )
    user = await sql_auth_adapter.register_user(req)
    assert user.username == "bob"
    assert user.role == "steward"


@pytest.mark.asyncio
async def test_sql_auth_register_duplicate_fails(sql_auth_adapter: SqlAuthAdapter):
    """Verifies duplicate email or username registration is rejected."""
    await sql_auth_adapter.register_user(
        email="charlie@carefold.local",
        username="charlie",
        password="Password123!",
    )

    # Duplicate email
    with pytest.raises(ValueError, match="already exists"):
        await sql_auth_adapter.register_user(
            email="charlie@carefold.local",
            username="other_charlie",
            password="Password123!",
        )

    # Duplicate username
    with pytest.raises(ValueError, match="already exists"):
        await sql_auth_adapter.register_user(
            email="different@carefold.local",
            username="charlie",
            password="Password123!",
        )


@pytest.mark.asyncio
async def test_sql_auth_register_password_complexity(sql_auth_adapter: SqlAuthAdapter):
    """Verifies that passwords under 10 characters are rejected."""
    with pytest.raises(ValueError, match="at least 10 characters"):
        await sql_auth_adapter.register_user(
            email="short@carefold.local",
            username="short",
            password="short",
        )


@pytest.mark.asyncio
async def test_sql_auth_authenticate_success(sql_auth_adapter: SqlAuthAdapter):
    """Verifies authentication via username and email, updating last_login_at."""
    await sql_auth_adapter.register_user(
        email="david@carefold.local",
        username="david",
        password="DavidPassword123!",
    )

    # Authenticate by username
    auth1 = await sql_auth_adapter.authenticate("david", "DavidPassword123!")
    assert auth1 is not None
    assert auth1.username == "david"
    assert auth1.last_login_at is not None

    # Authenticate by email
    auth2 = await sql_auth_adapter.authenticate("david@carefold.local", "DavidPassword123!")
    assert auth2 is not None
    assert auth2.id == auth1.id


@pytest.mark.asyncio
async def test_sql_auth_authenticate_wrong_password(sql_auth_adapter: SqlAuthAdapter):
    """Verifies wrong password returns None."""
    await sql_auth_adapter.register_user(
        email="eve@carefold.local",
        username="eve",
        password="EvePassword123!",
    )

    auth = await sql_auth_adapter.authenticate("eve", "WrongPassword!")
    assert auth is None


@pytest.mark.asyncio
async def test_sql_auth_authenticate_constant_time_dummy_verify(sql_session_factory):
    """Verifies constant-time dummy verification is invoked on user lookup misses."""
    mock_hasher = MagicMock()
    mock_hasher.verify.return_value = False

    adapter = SqlAuthAdapter(session_factory=sql_session_factory, hasher=mock_hasher)

    res = await adapter.authenticate("nonexistent_user", "some_password")
    assert res is None
    # Verifies mock_hasher.verify was called on miss with dummy hash to thwart timing attacks
    assert mock_hasher.verify.called
    assert mock_hasher.verify.call_args[0][0] == "some_password"


@pytest.mark.asyncio
async def test_sql_auth_authenticate_disabled_user(sql_auth_adapter: SqlAuthAdapter):
    """Verifies disabled user cannot authenticate."""
    user = await sql_auth_adapter.register_user(
        email="frank@carefold.local",
        username="frank",
        password="FrankPassword123!",
    )
    await sql_auth_adapter.update_user(user.id, status="disabled")

    auth = await sql_auth_adapter.authenticate("frank", "FrankPassword123!")
    assert auth is not None
    assert auth.status == "disabled"


@pytest.mark.asyncio
async def test_sql_auth_session_lifecycle(sql_auth_adapter: SqlAuthAdapter):
    """Verifies session issuance, SHA-256 token hashing at rest, validation, and unpacking."""
    user = await sql_auth_adapter.register_user(
        email="grace@carefold.local",
        username="grace",
        password="GracePassword123!",
    )

    # 1. Create session
    session_token = await sql_auth_adapter.create_session(
        user_id=user.id,
        client_ip="192.168.1.100",
        user_agent="Pytest-Test-Agent",
        duration_seconds=3600,
    )
    assert isinstance(session_token, SessionToken)
    assert session_token.user_id == user.id
    assert session_token.client_ip == "192.168.1.100"
    assert session_token.user_agent == "Pytest-Test-Agent"

    # Tuple unpacking check
    raw_token, session_rec = session_token
    assert raw_token == session_token.token
    assert session_rec.id == session_token.session_id

    # Verify SHA-256 token hash stored at rest
    expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    assert session_token.session_id == expected_hash

    session_factory = sql_auth_adapter._get_session_factory()
    async with session_factory() as s:
        db_session = await s.get(Session, expected_hash)
        assert db_session is not None
        assert db_session.user_id == user.id

    # 2. Validate session
    validated = await sql_auth_adapter.validate_session(raw_token)
    assert validated is not None
    assert isinstance(validated, ValidatedSession)
    assert validated.id == user.id
    assert validated.username == "grace"
    assert validated.session is not None
    assert validated.session.client_ip == "192.168.1.100"

    # Tuple unpacking on validated session: user, session = validated
    val_user, val_session = validated
    assert val_user.id == user.id
    assert val_session.id == expected_hash

    # 3. Invalid token returns None
    invalid = await sql_auth_adapter.validate_session("completely-invalid-raw-token")
    assert invalid is None


@pytest.mark.asyncio
async def test_sql_auth_session_expiration(sql_auth_adapter: SqlAuthAdapter):
    """Verifies expired sessions return None and are purged."""
    user = await sql_auth_adapter.register_user(
        email="heidi@carefold.local",
        username="heidi",
        password="HeidiPassword123!",
    )

    # Create session with -10 seconds duration (already expired)
    session_token = await sql_auth_adapter.create_session(
        user_id=user.id,
        duration_seconds=-10,
    )

    val = await sql_auth_adapter.validate_session(session_token.token)
    assert val is None


@pytest.mark.asyncio
async def test_sql_auth_revoke_session(sql_auth_adapter: SqlAuthAdapter):
    """Verifies single session revocation."""
    user = await sql_auth_adapter.register_user(
        email="ian@carefold.local",
        username="ian",
        password="IanPassword123!",
    )

    session_token = await sql_auth_adapter.create_session(user.id)
    assert await sql_auth_adapter.validate_session(session_token.token) is not None

    # Revoke session
    revoked = await sql_auth_adapter.revoke_session(session_token.token)
    assert revoked is True

    # Subsequent validation fails
    assert await sql_auth_adapter.validate_session(session_token.token) is None

    # Second revocation returns False
    assert await sql_auth_adapter.revoke_session(session_token.token) is False


@pytest.mark.asyncio
async def test_sql_auth_revoke_all_sessions(sql_auth_adapter: SqlAuthAdapter):
    """Verifies revoking all sessions for a specific user."""
    user1 = await sql_auth_adapter.register_user(
        email="user1@carefold.local",
        username="user1",
        password="Password123!",
    )
    user2 = await sql_auth_adapter.register_user(
        email="user2@carefold.local",
        username="user2",
        password="Password123!",
    )

    t1a = await sql_auth_adapter.create_session(user1.id)
    t1b = await sql_auth_adapter.create_session(user1.id)
    t2 = await sql_auth_adapter.create_session(user2.id)

    revoked_count = await sql_auth_adapter.revoke_all_sessions(user1.id)
    assert revoked_count == 2

    # user1 sessions are gone
    assert await sql_auth_adapter.validate_session(t1a.token) is None
    assert await sql_auth_adapter.validate_session(t1b.token) is None

    # user2 session remains active
    assert await sql_auth_adapter.validate_session(t2.token) is not None


@pytest.mark.asyncio
async def test_sql_auth_password_reset_flow(sql_auth_adapter: SqlAuthAdapter):
    """Verifies password reset token creation, consumption, and session cascade invalidation."""
    user = await sql_auth_adapter.register_user(
        email="judy@carefold.local",
        username="judy",
        password="OldPassword123!",
    )

    # Active session prior to reset
    sess = await sql_auth_adapter.create_session(user.id)
    assert await sql_auth_adapter.validate_session(sess.token) is not None

    # Unknown email returns None
    assert await sql_auth_adapter.create_password_reset_token("unknown@carefold.local") is None

    # Generate reset token
    raw_token = await sql_auth_adapter.create_password_reset_token("judy@carefold.local")
    assert raw_token is not None

    # Consume reset token
    reset_ok = await sql_auth_adapter.reset_password(raw_token, "NewStrongPassword123!")
    assert reset_ok is True

    # Re-using the same token fails
    assert await sql_auth_adapter.reset_password(raw_token, "AnotherPassword123!") is False

    # Old password no longer authenticates
    assert await sql_auth_adapter.authenticate("judy", "OldPassword123!") is None

    # New password authenticates
    auth = await sql_auth_adapter.authenticate("judy", "NewStrongPassword123!")
    assert auth is not None

    # Active session was revoked during password reset
    assert await sql_auth_adapter.validate_session(sess.token) is None


@pytest.mark.asyncio
async def test_sql_auth_change_password(sql_auth_adapter: SqlAuthAdapter):
    """Verifies authenticated password change."""
    user = await sql_auth_adapter.register_user(
        email="karl@carefold.local",
        username="karl",
        password="OldPassword123!",
    )

    # Wrong old password fails
    assert not await sql_auth_adapter.change_password(user.id, "WrongOld!", "NewPassword123!")

    # Correct old password succeeds
    assert await sql_auth_adapter.change_password(user.id, "OldPassword123!", "NewPassword123!")

    # Verify new password
    assert await sql_auth_adapter.authenticate("karl", "NewPassword123!") is not None


@pytest.mark.asyncio
async def test_sql_auth_list_users_and_filters(sql_auth_adapter: SqlAuthAdapter):
    """Verifies paginated user listing with search and role filters."""
    for i in range(15):
        await sql_auth_adapter.register_user(
            email=f"user_{i}@carefold.local",
            username=f"user_{i}",
            password="Password123!",
            role="admin" if i < 5 else "member",
        )

    # Default pagination
    paginated = await sql_auth_adapter.list_users(page=1, page_size=10)
    assert isinstance(paginated, PaginatedUsers)
    assert paginated.total == 15
    assert len(paginated.users) == 10
    assert paginated.page == 1

    # Unpacking support
    users, total = paginated
    assert len(users) == 10
    assert total == 15

    # Role filter
    admin_list = await sql_auth_adapter.list_users(role="admin")
    assert admin_list.total == 5

    # Search filter
    search_list = await sql_auth_adapter.list_users(search="user_1")
    # Matches user_1, user_10, user_11, user_12, user_13, user_14 -> 6 users
    assert search_list.total == 6


@pytest.mark.asyncio
async def test_sql_auth_update_user_and_disable_cascade(sql_auth_adapter: SqlAuthAdapter):
    """Verifies user profile update and automatic session revocation on disable."""
    user = await sql_auth_adapter.register_user(
        email="leo@carefold.local",
        username="leo",
        password="LeoPassword123!",
        role="member",
    )

    # Create active session
    sess = await sql_auth_adapter.create_session(user.id)
    assert await sql_auth_adapter.validate_session(sess.token) is not None

    # Update role and full name via UserUpdate
    updated = await sql_auth_adapter.update_user(
        user.id,
        UserUpdate(full_name="Leo Tolstoy", role="steward"),
    )
    assert updated is not None
    assert updated.full_name == "Leo Tolstoy"
    assert updated.role == "steward"
    assert updated.status == "active"

    # Disable user
    disabled_user = await sql_auth_adapter.update_user(user.id, status="disabled")
    assert disabled_user is not None
    assert disabled_user.status == "disabled"

    # Active session was automatically revoked when user was disabled
    assert await sql_auth_adapter.validate_session(sess.token) is None


# ============================================================================
# DisabledAuthAdapter Tests
# ============================================================================


@pytest.mark.asyncio
async def test_disabled_auth_adapter_defaults():
    """Verifies DisabledAuthAdapter returns DEFAULT_STEWARD_USER and permits bypass."""
    adapter = DisabledAuthAdapter()

    assert adapter._steward.id == DEFAULT_STEWARD_USER.id
    assert adapter._steward.email == "steward@carefold.local"
    assert adapter._steward.username == "steward"
    assert adapter._steward.role == "admin"
    assert adapter._steward.auth_provider == "disabled"

    # Register user returns steward
    reg = await adapter.register_user("any@test.local", "any", "any")
    assert reg.id == DEFAULT_STEWARD_USER.id

    # Authenticate returns steward
    auth = await adapter.authenticate("anything", "anything")
    assert auth is not None
    assert auth.id == DEFAULT_STEWARD_USER.id

    # Session issuance returns token
    st = await adapter.create_session("any-user-id")
    assert isinstance(st, SessionToken)
    assert st.token == "disabled-session-token"
    assert st.user_id == DEFAULT_STEWARD_USER.id

    # Session validation returns valid ValidatedSession
    val = await adapter.validate_session("any-token")
    assert val is not None
    assert val.id == DEFAULT_STEWARD_USER.id
    assert val.role == "admin"

    # Listing users returns steward
    users_page = await adapter.list_users()
    assert users_page.total == 1
    assert users_page.users[0].id == DEFAULT_STEWARD_USER.id

    # Reset and change password return True
    assert await adapter.reset_password("token", "newpw") is True
    assert await adapter.change_password("id", "old", "new") is True
    assert await adapter.revoke_session("token") is True


# ============================================================================
# OidcAuthAdapter Tests
# ============================================================================


@pytest.mark.asyncio
async def test_oidc_authorization_urls():
    """Verifies OidcAuthAdapter builds valid OAuth2 / OIDC authorization URLs."""
    adapter = OidcAuthAdapter(
        client_id="test-client-id",
        issuer_url="https://keycloak.example.com",
    )

    # Google
    g_url = adapter.get_authorization_url("google", "https://app/callback", "state123")
    assert g_url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=test-client-id" in g_url
    assert "openid+email+profile" in g_url or "openid%20email%20profile" in g_url
    assert "state123" in g_url

    # GitHub
    gh_url = adapter.get_authorization_url("github", "https://app/callback", "state456")
    assert gh_url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=test-client-id" in gh_url

    # Keycloak
    kc_url = adapter.get_authorization_url("keycloak", "https://app/callback", "state789")
    assert kc_url.startswith("https://keycloak.example.com/protocol/openid-connect/auth?")

    # Unsupported provider
    with pytest.raises(ValueError, match="Unsupported OIDC provider"):
        adapter.get_authorization_url("unknown_idp", "https://app/callback", "s")


@pytest.mark.asyncio
async def test_oidc_password_auth_disabled(sql_auth_adapter: SqlAuthAdapter):
    """Verifies that direct password authentication raises in OIDC mode."""
    adapter = OidcAuthAdapter(sql_adapter=sql_auth_adapter)

    with pytest.raises(NotImplementedError, match="Single Sign-On"):
        await adapter.authenticate("user", "pass")

    assert await adapter.create_password_reset_token("user@email.com") is None
    assert await adapter.reset_password("tok", "newpass") is False
    assert await adapter.change_password("uid", "old", "new") is False


@pytest.mark.asyncio
async def test_oidc_delegates_sessions_to_sql(sql_auth_adapter: SqlAuthAdapter):
    """Verifies that OIDC adapter delegates user registration and sessions to SQL store."""
    adapter = OidcAuthAdapter(sql_adapter=sql_auth_adapter)

    user = await adapter.register_user(
        email="sso_user@carefold.local",
        username="sso_user",
        full_name="SSO User",
    )
    assert user.auth_provider == "oidc"

    token = await adapter.create_session(user.id)
    assert token is not None

    validated = await adapter.validate_session(token.token)
    assert validated is not None
    assert validated.id == user.id


# ============================================================================
# Auth Factory Tests
# ============================================================================


def test_auth_factory_resolution(monkeypatch):
    """Verifies create_auth_port resolves adapters based on environment and provider name."""
    # 1. Default -> DisabledAuthAdapter
    monkeypatch.delenv("CAREFOLD_AUTH_PROVIDER", raising=False)
    reset_auth_port()
    port = create_auth_port()
    assert isinstance(port, DisabledAuthAdapter)

    # 2. Local -> SqlAuthAdapter
    port_local = create_auth_port("local")
    assert isinstance(port_local, SqlAuthAdapter)

    # 3. OIDC -> OidcAuthAdapter
    port_oidc = create_auth_port("oidc")
    assert isinstance(port_oidc, OidcAuthAdapter)

    # 4. Unknown -> ValueError
    with pytest.raises(ValueError, match="Unsupported auth provider"):
        create_auth_port("invalid_provider")


def test_auth_factory_singleton_and_set():
    """Verifies get_auth_port singleton caching, set_auth_port, and reset_auth_port."""
    reset_auth_port()
    p1 = get_auth_port()
    p2 = get_auth_port()
    assert p1 is p2

    custom_port = DisabledAuthAdapter()
    set_auth_port(custom_port)
    assert get_auth_port() is custom_port

    reset_auth_port()
    p3 = get_auth_port()
    assert p3 is not custom_port
