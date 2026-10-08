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

"""Unit tests for Carefold declarative models, CRUD operations, constraints, and cascades."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.db.base import Base
from carefold.db.models import PasswordReset, Session, SystemSetting, User
from carefold.db.session import create_db_engine, get_session_factory, init_db


@pytest.fixture
async def db_session(tmp_path: Path):
    """Provides an isolated async database session with initialized schemas."""
    db_file = tmp_path / "models_test.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)

    factory = get_session_factory(engine)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_user_creation_defaults_and_normalization(db_session: AsyncSession):
    """Verifies User default fields, UUID generation, and email lowercase normalization."""
    user = User(
        email="Test.Caregiver@Example.COM",
        username="caregiver_jane",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$dummyhash",
        full_name="Jane Doe",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    assert user.id is not None
    assert len(user.id) == 36  # UUID v4 string length
    # Normalized email
    assert user.email == "test.caregiver@example.com"
    assert user.username == "caregiver_jane"
    assert user.role == "steward"
    assert user.status == "active"
    assert user.auth_provider == "local"
    assert user.created_at is not None
    assert user.updated_at is not None
    assert user.last_login_at is None


@pytest.mark.asyncio
async def test_user_unique_constraints(db_session: AsyncSession):
    """Verifies uniqueness constraints on email and username."""
    u1 = User(
        email="unique@example.com",
        username="unique_user",
        hashed_password="hash1",
    )
    db_session.add(u1)
    await db_session.commit()

    # 1. Duplicate email must raise IntegrityError
    u2 = User(
        email="UNIQUE@example.com",  # normalized to same email
        username="other_user",
        hashed_password="hash2",
    )
    db_session.add(u2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # 2. Duplicate username must raise IntegrityError
    u3 = User(
        email="different@example.com",
        username="unique_user",
        hashed_password="hash3",
    )
    db_session.add(u3)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_session_lifecycle_and_cascade_delete(db_session: AsyncSession):
    """Verifies Session creation, user relationship, and cascading deletion on user removal."""
    user = User(
        email="session_user@example.com",
        username="session_user",
        hashed_password="hash",
    )
    db_session.add(user)
    await db_session.commit()

    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=7)
    session_id = "a" * 64  # SHA-256 token hash

    sess = Session(
        id=session_id,
        user_id=user.id,
        client_ip="127.0.0.1",
        user_agent="Mozilla/5.0 Test Agent",
        expires_at=expires,
    )
    db_session.add(sess)
    await db_session.commit()

    # Verify query and relationship
    fetched_sess = await db_session.get(Session, session_id)
    assert fetched_sess is not None
    assert fetched_sess.user_id == user.id
    assert fetched_sess.client_ip == "127.0.0.1"

    # Delete the user; cascade must delete session
    await db_session.delete(user)
    await db_session.commit()
    db_session.expire_all()

    # Check session was deleted
    orphan_sess = await db_session.get(Session, session_id)
    assert orphan_sess is None


@pytest.mark.asyncio
async def test_password_reset_lifecycle_and_cascade_delete(db_session: AsyncSession):
    """Verifies PasswordReset token creation, consumption, and cascading deletion."""
    user = User(
        email="reset_user@example.com",
        username="reset_user",
        hashed_password="hash",
    )
    db_session.add(user)
    await db_session.commit()

    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=1)
    token_hash = "b" * 64

    reset = PasswordReset(
        token_hash=token_hash,
        user_id=user.id,
        expires_at=expires,
    )
    db_session.add(reset)
    await db_session.commit()

    # Mark as used
    fetched_reset = await db_session.get(PasswordReset, token_hash)
    assert fetched_reset is not None
    assert fetched_reset.used_at is None
    fetched_reset.used_at = datetime.now(timezone.utc)
    await db_session.commit()

    re_fetched = await db_session.get(PasswordReset, token_hash)
    assert re_fetched is not None
    assert re_fetched.used_at is not None

    # Delete user; cascade must delete password reset
    await db_session.delete(user)
    await db_session.commit()
    db_session.expire_all()

    orphan_reset = await db_session.get(PasswordReset, token_hash)
    assert orphan_reset is None


@pytest.mark.asyncio
async def test_system_setting_json_helpers_and_crud(db_session: AsyncSession):
    """Verifies SystemSetting key-value storage, JSON serialization helpers, and updates."""
    setting = SystemSetting(
        key="runtime.model_config",
        is_secret=False,
        updated_by="admin_user",
    )
    payload = {
        "provider": "ollama",
        "model": "llama3.2:3b",
        "temperature": 0.2,
        "features": ["attachments", "notes"],
    }
    setting.set_value(payload)
    db_session.add(setting)
    await db_session.commit()

    # Fetch and deserialize
    fetched = await db_session.get(SystemSetting, "runtime.model_config")
    assert fetched is not None
    assert fetched.is_secret is False
    assert fetched.updated_by == "admin_user"
    assert fetched.get_value() == payload

    # Update value
    updated_payload = {"provider": "google", "model": "gemini-1.5-pro"}
    fetched.set_value(updated_payload)
    await db_session.commit()

    refetched = await db_session.get(SystemSetting, "runtime.model_config")
    assert refetched.get_value() == updated_payload

    # Delete setting
    await db_session.delete(refetched)
    await db_session.commit()

    deleted = await db_session.get(SystemSetting, "runtime.model_config")
    assert deleted is None
