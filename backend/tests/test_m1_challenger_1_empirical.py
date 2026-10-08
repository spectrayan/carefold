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

"""Empirical adversarial test harness for Milestone 1 (R1 SQL Layer & Declarative Schemas).

Tests:
1. Transaction rollback on error and auto-commit in `get_db`.
2. Physical cascade deletions (User -> Session, User -> PasswordReset) via ORM and raw SQL.
3. Email lowercase normalization, whitespace handling, and unique constraint collisions.
4. SystemSetting JSON serialization, round-trip fidelity, mutations, and secret flags.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.db.base import Base
from carefold.db.models import PasswordReset, Session, SystemSetting, User
from carefold.db.session import (
    create_db_engine,
    get_db,
    get_engine,
    get_session_factory,
    init_db,
    reset_engine,
)


# ==============================================================================
# CHALLENGE AREA 1: TRANSACTION COMMIT AND ROLLBACK IN get_db
# ==============================================================================

@pytest.mark.asyncio
async def test_get_db_commits_on_clean_generator_exit(tmp_path: Path, monkeypatch):
    """Empirical probe: verify get_db() auto-commits records upon clean generator exit."""
    db_file = tmp_path / "test_get_db_commit.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    monkeypatch.setenv("CAREFOLD_DATABASE_URL", url)
    reset_engine()

    engine = get_engine()
    await init_db(engine)

    # 1. Execute get_db generator without manual commit
    user_id = "test-user-commit-uuid-1234"
    async for db in get_db():
        user = User(
            id=user_id,
            email="auto.commit@example.com",
            username="autocommit_user",
            hashed_password="argon2_hashed_secret",
        )
        db.add(user)
        # Deliberately DO NOT call db.commit() to test get_db's auto-commit

    # 2. Open an independent session to verify row was committed to physical storage
    factory = get_session_factory(engine)
    async with factory() as verify_session:
        fetched = await verify_session.get(User, user_id)
        assert fetched is not None, "get_db failed to commit row upon clean generator exit"
        assert fetched.email == "auto.commit@example.com"
        assert fetched.username == "autocommit_user"

    await engine.dispose()
    reset_engine()


@pytest.mark.asyncio
async def test_get_db_rolls_back_on_unhandled_exception(tmp_path: Path, monkeypatch):
    """Empirical probe: verify get_db() rolls back dirty transactions when an exception is raised."""
    db_file = tmp_path / "test_get_db_rollback.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    monkeypatch.setenv("CAREFOLD_DATABASE_URL", url)
    reset_engine()

    engine = get_engine()
    await init_db(engine)

    # 1. Insert a baseline user that should NOT be affected
    baseline_id = "baseline-user-uuid-1111"
    async for db in get_db():
        db.add(User(
            id=baseline_id,
            email="baseline@example.com",
            username="baseline_user",
            hashed_password="pw",
        ))

    # 2. Attempt operation in get_db that fails mid-flight
    failing_id = "failing-user-uuid-9999"
    with pytest.raises(RuntimeError, match="Simulated endpoint crash"):
        async for db in get_db():
            db.add(User(
                id=failing_id,
                email="doomed@example.com",
                username="doomed_user",
                hashed_password="pw",
            ))
            await db.flush()  # Flushed to SQLite transaction buffer
            # Raise exception before clean generator exit
            raise RuntimeError("Simulated endpoint crash")

    # 3. Verify in independent session: baseline remains, doomed user was rolled back
    factory = get_session_factory(engine)
    async with factory() as verify_session:
        baseline_user = await verify_session.get(User, baseline_id)
        assert baseline_user is not None, "Baseline user was lost"

        doomed_user = await verify_session.get(User, failing_id)
        assert doomed_user is None, "get_db failed to rollback uncommitted row on exception!"

        count_result = await verify_session.execute(
            text("SELECT count(*) FROM users WHERE id = :uid"),
            {"uid": failing_id},
        )
        assert count_result.scalar() == 0

    await engine.dispose()
    reset_engine()


@pytest.mark.asyncio
async def test_get_db_rolls_back_on_commit_integrity_error(tmp_path: Path, monkeypatch):
    """Empirical probe: verify get_db() properly rolls back when commit() raises an IntegrityError."""
    db_file = tmp_path / "test_get_db_integrity.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    monkeypatch.setenv("CAREFOLD_DATABASE_URL", url)
    reset_engine()

    engine = get_engine()
    await init_db(engine)

    # Seed existing user
    async for db in get_db():
        db.add(User(
            email="existing@example.com",
            username="existing_user",
            hashed_password="pw",
        ))

    # Attempt to insert user with duplicate username in get_db
    with pytest.raises(IntegrityError):
        async for db in get_db():
            db.add(User(
                email="different@example.com",
                username="existing_user",  # Duplicate username!
                hashed_password="pw2",
            ))
            # get_db will attempt await db.commit() upon generator exit and catch IntegrityError

    # Verify session factory is healthy and only 1 user exists
    factory = get_session_factory(engine)
    async with factory() as verify_session:
        result = await verify_session.execute(text("SELECT count(*) FROM users"))
        assert result.scalar() == 1

    await engine.dispose()
    reset_engine()


# ==============================================================================
# CHALLENGE AREA 2: CASCADE DELETES (User -> Session & User -> PasswordReset)
# ==============================================================================

@pytest.mark.asyncio
async def test_cascade_delete_orm_level(tmp_path: Path):
    """Empirical probe: verify ORM session.delete(user) cascades to multiple Sessions and PasswordResets."""
    db_file = tmp_path / "cascade_orm.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)
    factory = get_session_factory(engine)

    async with factory() as session:
        user = User(
            email="cascade_target@example.com",
            username="target_user",
            hashed_password="pw",
        )
        session.add(user)
        await session.flush()

        now = datetime.now(timezone.utc)
        # Create 5 sessions
        session_ids = [f"sess_{i}_{'x'*55}" for i in range(5)]
        for s_id in session_ids:
            session.add(Session(
                id=s_id,
                user_id=user.id,
                expires_at=now + timedelta(days=1),
            ))

        # Create 3 password resets
        token_hashes = [f"reset_{i}_{'y'*55}" for i in range(3)]
        for t_hash in token_hashes:
            session.add(PasswordReset(
                token_hash=t_hash,
                user_id=user.id,
                expires_at=now + timedelta(hours=2),
            ))

        await session.commit()

    # Verify all records created
    async with factory() as session:
        sess_count = await session.execute(
            text("SELECT count(*) FROM sessions WHERE user_id = :uid"),
            {"uid": user.id},
        )
        assert sess_count.scalar() == 5

        reset_count = await session.execute(
            text("SELECT count(*) FROM password_resets WHERE user_id = :uid"),
            {"uid": user.id},
        )
        assert reset_count.scalar() == 3

        # Delete user via ORM
        fetched_user = await session.get(User, user.id)
        assert fetched_user is not None
        await session.delete(fetched_user)
        await session.commit()

    # Verify physical cascade across both child tables
    async with factory() as session:
        for s_id in session_ids:
            assert await session.get(Session, s_id) is None
        for t_hash in token_hashes:
            assert await session.get(PasswordReset, t_hash) is None

        total_sess = await session.execute(text("SELECT count(*) FROM sessions"))
        assert total_sess.scalar() == 0
        total_resets = await session.execute(text("SELECT count(*) FROM password_resets"))
        assert total_resets.scalar() == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_cascade_delete_raw_sql_foreign_key_enforcement(tmp_path: Path):
    """Empirical probe: verify raw SQL DELETE triggers SQLite database-level ON DELETE CASCADE."""
    db_file = tmp_path / "cascade_raw_sql.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)
    factory = get_session_factory(engine)

    u1_id = "user-to-delete-1111"
    u2_id = "user-to-keep-2222"

    async with factory() as session:
        # Insert two users
        session.add(User(id=u1_id, email="u1@test.org", username="u1", hashed_password="pw"))
        session.add(User(id=u2_id, email="u2@test.org", username="u2", hashed_password="pw"))
        await session.flush()

        now = datetime.now(timezone.utc)
        # Child records for User 1
        session.add(Session(id="sess_u1_1" + "a"*55, user_id=u1_id, expires_at=now + timedelta(days=1)))
        session.add(Session(id="sess_u1_2" + "a"*55, user_id=u1_id, expires_at=now + timedelta(days=1)))
        session.add(PasswordReset(token_hash="reset_u1_1" + "b"*54, user_id=u1_id, expires_at=now + timedelta(hours=1)))

        # Child records for User 2 (must remain untouched)
        session.add(Session(id="sess_u2_1" + "c"*55, user_id=u2_id, expires_at=now + timedelta(days=1)))
        session.add(PasswordReset(token_hash="reset_u2_1" + "d"*54, user_id=u2_id, expires_at=now + timedelta(hours=1)))
        await session.commit()

    # Execute RAW SQL delete bypassing SQLAlchemy ORM entity lifecycle
    async with factory() as session:
        await session.execute(
            text("DELETE FROM users WHERE id = :uid"),
            {"uid": u1_id},
        )
        await session.commit()

    # Verify: SQLite's PRAGMA foreign_keys = ON physically cascaded deletions
    async with factory() as session:
        # User 1 child records should be completely gone
        res_s1 = await session.execute(
            text("SELECT count(*) FROM sessions WHERE user_id = :uid"),
            {"uid": u1_id},
        )
        assert res_s1.scalar() == 0, "Raw SQL delete failed to cascade to sessions table in SQLite!"

        res_r1 = await session.execute(
            text("SELECT count(*) FROM password_resets WHERE user_id = :uid"),
            {"uid": u1_id},
        )
        assert res_r1.scalar() == 0, "Raw SQL delete failed to cascade to password_resets table in SQLite!"

        # User 2 child records MUST still exist intact
        res_s2 = await session.execute(
            text("SELECT count(*) FROM sessions WHERE user_id = :uid"),
            {"uid": u2_id},
        )
        assert res_s2.scalar() == 1, "Unrelated user sessions were mistakenly deleted!"

        res_r2 = await session.execute(
            text("SELECT count(*) FROM password_resets WHERE user_id = :uid"),
            {"uid": u2_id},
        )
        assert res_r2.scalar() == 1, "Unrelated user password resets were mistakenly deleted!"

    await engine.dispose()


@pytest.mark.asyncio
async def test_foreign_key_rejects_orphans_on_insert(tmp_path: Path):
    """Empirical probe: verify SQLite rejects inserting Session with non-existent user_id."""
    db_file = tmp_path / "fk_reject.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)
    factory = get_session_factory(engine)

    async with factory() as session:
        now = datetime.now(timezone.utc)
        orphan_session = Session(
            id="orphan_session_" + "z"*49,
            user_id="non-existent-user-id-99999",
            expires_at=now + timedelta(days=1),
        )
        session.add(orphan_session)
        # Because PRAGMA foreign_keys = ON, this must raise IntegrityError
        with pytest.raises(IntegrityError):
            await session.commit()

    await engine.dispose()


# ==============================================================================
# CHALLENGE AREA 3: LOWERCASE EMAIL VALIDATION & UNIQUE CONSTRAINTS
# ==============================================================================

@pytest.mark.asyncio
async def test_email_lowercase_normalization_on_init_and_mutation(tmp_path: Path):
    """Empirical probe: verify email normalization on instantiation, whitespace, and attribute mutation."""
    db_file = tmp_path / "email_norm.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)
    factory = get_session_factory(engine)

    async with factory() as session:
        # 1. Instantiation with mixed case and whitespace
        user = User(
            email="   Dr.John.Doe@HospitalNetwork.ORG   ",
            username="dr_john",
            hashed_password="pw",
        )
        assert user.email == "dr.john.doe@hospitalnetwork.org"

        session.add(user)
        await session.commit()
        await session.refresh(user)
        assert user.email == "dr.john.doe@hospitalnetwork.org"

        # 2. Attribute assignment mutation with mixed case
        user.email = "   UPDATED.CLINICIAN@HEALTHCARE.COM   "
        assert user.email == "updated.clinician@healthcare.com"
        await session.commit()
        await session.refresh(user)
        assert user.email == "updated.clinician@healthcare.com"

        # 3. Unicode lowercase normalization
        user.email = "   MÜLLER.KLINIK@EXAMPLE.DE   "
        assert user.email == "müller.klinik@example.de"
        await session.commit()
        await session.refresh(user)
        assert user.email == "müller.klinik@example.de"

    await engine.dispose()


@pytest.mark.asyncio
async def test_email_duplicate_case_insensitive_collision(tmp_path: Path):
    """Empirical probe: verify uniqueness constraint prevents duplicate emails regardless of casing."""
    db_file = tmp_path / "email_dup.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)
    factory = get_session_factory(engine)

    async with factory() as session:
        u1 = User(
            email="steward@carefold.io",
            username="steward1",
            hashed_password="pw",
        )
        session.add(u1)
        await session.commit()

        # u2 has identical email with different casing and surrounding whitespace
        u2 = User(
            email="   STEWARD@CAREFOLD.IO   ",
            username="steward2",
            hashed_password="pw",
        )
        # Should be normalized to 'steward@carefold.io' immediately
        assert u2.email == "steward@carefold.io"
        session.add(u2)

        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    await engine.dispose()


@pytest.mark.asyncio
async def test_email_query_by_normalized_string(tmp_path: Path):
    """Empirical probe: verify SELECT queries accurately retrieve users via normalized email."""
    db_file = tmp_path / "email_query.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)
    factory = get_session_factory(engine)

    async with factory() as session:
        session.add(User(
            email="Nurse.Joy@PokemonHospital.NET",
            username="nurse_joy",
            hashed_password="pw",
        ))
        await session.commit()

    async with factory() as session:
        query_email = "nurse.joy@pokemonhospital.net"
        stmt = select(User).where(User.email == query_email)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        assert user is not None
        assert user.username == "nurse_joy"

    await engine.dispose()


# ==============================================================================
# CHALLENGE AREA 4: SYSTEM SETTING JSON CRUD & SECRET MASKING
# ==============================================================================

@pytest.mark.asyncio
async def test_system_setting_json_types_and_nested_payloads(tmp_path: Path):
    """Empirical probe: verify SystemSetting handles complex nested structures and various JSON types."""
    db_file = tmp_path / "setting_json.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)
    factory = get_session_factory(engine)

    complex_payload = {
        "providers": {
            "ollama": {
                "enabled": True,
                "endpoints": ["http://localhost:11434", "http://127.0.0.1:11434"],
                "timeout_seconds": 45,
                "retry_config": {
                    "max_attempts": 3,
                    "backoff_multiplier": 1.5,
                },
            },
            "cloud": None,
        },
        "flags": [True, False, None, 42, 3.14159, "healthcare-ai"],
        "metadata": {
            "unicode_test": "Hospital Clínico San Carlos • 🏥",
            "active": False,
        },
    }

    async with factory() as session:
        setting = SystemSetting(
            key="runtime.multi_provider_config",
            is_secret=False,
            updated_by="lead_admin",
        )
        setting.set_value(complex_payload)
        session.add(setting)
        await session.commit()

    # Re-fetch in new session and assert complete structural fidelity
    async with factory() as session:
        fetched = await session.get(SystemSetting, "runtime.multi_provider_config")
        assert fetched is not None
        assert fetched.is_secret is False
        assert fetched.updated_by == "lead_admin"
        recovered = fetched.get_value()
        assert recovered == complex_payload
        assert recovered["providers"]["ollama"]["retry_config"]["max_attempts"] == 3
        assert recovered["flags"][5] == "healthcare-ai"
        assert recovered["metadata"]["unicode_test"] == "Hospital Clínico San Carlos • 🏥"

    await engine.dispose()


@pytest.mark.asyncio
async def test_system_setting_primitive_scalars(tmp_path: Path):
    """Empirical probe: verify SystemSetting can store raw JSON scalars (int, bool, string, null)."""
    db_file = tmp_path / "setting_primitives.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)
    factory = get_session_factory(engine)

    test_cases = [
        ("setting.int", 42),
        ("setting.float", 3.14),
        ("setting.bool_true", True),
        ("setting.bool_false", False),
        ("setting.string", "simple string value"),
        ("setting.null", None),
        ("setting.empty_dict", {}),
        ("setting.empty_list", []),
    ]

    async with factory() as session:
        for k, v in test_cases:
            s = SystemSetting(key=k)
            s.set_value(v)
            session.add(s)
        await session.commit()

    async with factory() as session:
        for k, expected_v in test_cases:
            s = await session.get(SystemSetting, k)
            assert s is not None
            assert s.get_value() == expected_v

    await engine.dispose()


@pytest.mark.asyncio
async def test_system_setting_secret_flag_and_update_lifecycle(tmp_path: Path):
    """Empirical probe: verify is_secret flag preservation, value mutation, and deletion."""
    db_file = tmp_path / "setting_secret.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)
    factory = get_session_factory(engine)

    key = "secrets.google_api_key"

    # 1. Create secret setting
    async with factory() as session:
        secret_setting = SystemSetting(
            key=key,
            is_secret=True,
            updated_by="security_admin",
        )
        secret_setting.set_value({"api_key": "AIzaSyTestKeySecret123"})
        session.add(secret_setting)
        await session.commit()

    # 2. Verify is_secret is True and values persist
    async with factory() as session:
        fetched = await session.get(SystemSetting, key)
        assert fetched is not None
        assert fetched.is_secret is True
        assert fetched.get_value() == {"api_key": "AIzaSyTestKeySecret123"}

        # 3. Update secret value and metadata
        fetched.set_value({"api_key": "AIzaSyUpdatedKey456"})
        fetched.updated_by = "rotated_admin"
        await session.commit()

    # 4. Verify update took effect
    async with factory() as session:
        refetched = await session.get(SystemSetting, key)
        assert refetched is not None
        assert refetched.get_value() == {"api_key": "AIzaSyUpdatedKey456"}
        assert refetched.updated_by == "rotated_admin"
        assert refetched.is_secret is True

        # 5. Delete secret setting
        await session.delete(refetched)
        await session.commit()

    # 6. Verify deletion
    async with factory() as session:
        deleted = await session.get(SystemSetting, key)
        assert deleted is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_system_setting_malformed_json_error_handling(tmp_path: Path):
    """Empirical probe: verify get_value() raises json.JSONDecodeError if value_json is invalid."""
    db_file = tmp_path / "setting_malformed.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)
    factory = get_session_factory(engine)

    async with factory() as session:
        corrupted = SystemSetting(
            key="corrupted.config",
            value_json="NOT_VALID_JSON{abc:",
        )
        session.add(corrupted)
        await session.commit()

    async with factory() as session:
        fetched = await session.get(SystemSetting, "corrupted.config")
        assert fetched is not None
        with pytest.raises(json.JSONDecodeError):
            fetched.get_value()

    await engine.dispose()
