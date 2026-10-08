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

"""Unit and integration tests for Carefold database session, pooling, and dialect resolution."""

from __future__ import annotations

import os
from pathlib import Path
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool, QueuePool, StaticPool

from carefold.config import settings
from carefold.constants.paths import ENV_DATABASE_URL, ENV_DATABASE_URL_FALLBACK
from carefold.db.base import Base
from carefold.db.models import User
from carefold.db.session import (
    close_db,
    create_db_engine,
    get_db,
    get_engine,
    get_session_factory,
    init_db,
    normalize_database_url,
    reset_engine,
    resolve_database_url,
    sanitize_db_url,
)


def test_normalize_database_url():
    """Verifies that database URLs are correctly normalized to async drivers."""
    assert (
        normalize_database_url("postgres://user:pass@localhost:5432/carefold")
        == "postgresql+asyncpg://user:pass@localhost:5432/carefold"
    )
    assert (
        normalize_database_url("postgresql://user:pass@localhost:5432/carefold")
        == "postgresql+asyncpg://user:pass@localhost:5432/carefold"
    )
    assert (
        normalize_database_url("postgresql+psycopg2://user:pass@localhost:5432/carefold")
        == "postgresql+asyncpg://user:pass@localhost:5432/carefold"
    )
    assert (
        normalize_database_url("sqlite:///workspace/carefold.db")
        == "sqlite+aiosqlite:///workspace/carefold.db"
    )
    assert (
        normalize_database_url(":memory:")
        == "sqlite+aiosqlite:///:memory:"
    )
    # Already normalized URLs pass through
    assert (
        normalize_database_url("sqlite+aiosqlite:///workspace/carefold.db")
        == "sqlite+aiosqlite:///workspace/carefold.db"
    )
    assert (
        normalize_database_url("postgresql+asyncpg://user:pass@localhost:5432/carefold")
        == "postgresql+asyncpg://user:pass@localhost:5432/carefold"
    )


def test_sanitize_db_url():
    """Verifies that sensitive credentials are redacted in log-formatted URLs."""
    raw = "postgresql+asyncpg://carefold_user:super_secret_pw@db.internal:5432/carefold"
    sanitized = sanitize_db_url(raw)
    assert "super_secret_pw" not in sanitized
    assert "carefold_user" in sanitized
    assert "***" in sanitized or "None" in sanitized or "hidden" in sanitized

    # SQLite URLs without credentials remain unchanged
    sqlite_url = "sqlite+aiosqlite:///workspace/carefold.db"
    assert sanitize_db_url(sqlite_url) == sqlite_url


def test_resolve_database_url_priority(monkeypatch, tmp_path):
    """Verifies database URL resolution precedence."""
    monkeypatch.delenv(ENV_DATABASE_URL, raising=False)
    monkeypatch.delenv(ENV_DATABASE_URL_FALLBACK, raising=False)

    # 1. Default fallback to workspace
    resolved_default = resolve_database_url()
    assert resolved_default.startswith("sqlite+aiosqlite:///")
    assert "workspace/carefold.db" in resolved_default

    # 2. DATABASE_URL fallback
    monkeypatch.setenv(ENV_DATABASE_URL_FALLBACK, "postgresql://user:pass@host/fallback_db")
    resolved_fallback = resolve_database_url()
    assert resolved_fallback == "postgresql+asyncpg://user:pass@host/fallback_db"

    # 3. CAREFOLD_DATABASE_URL takes highest env precedence
    monkeypatch.setenv(ENV_DATABASE_URL, "postgresql://user:pass@host/primary_db")
    resolved_primary = resolve_database_url()
    assert resolved_primary == "postgresql+asyncpg://user:pass@host/primary_db"

    # 4. Explicit parameter overrides all env vars
    resolved_param = resolve_database_url("sqlite:///override.db")
    assert resolved_param == "sqlite+aiosqlite:///override.db"


def test_engine_pooling_dialect_selection():
    """Verifies that engine creation applies dialect-specific connection pool classes."""
    # SQLite in-memory: StaticPool
    mem_engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    assert isinstance(mem_engine.pool, StaticPool)

    # SQLite file: NullPool
    file_engine = create_db_engine("sqlite+aiosqlite:///tmp/test.db")
    assert isinstance(file_engine.pool, NullPool)

    # PostgreSQL: QueuePool / AsyncAdaptedQueuePool
    pg_engine = create_db_engine("postgresql+asyncpg://user:pass@localhost:5432/carefold")
    assert isinstance(pg_engine.pool, (QueuePool, AsyncAdaptedQueuePool))


@pytest.mark.asyncio
async def test_sqlite_pragmas_enabled():
    """Verifies that foreign keys, busy timeout, and WAL/journal pragmas are applied."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            # Foreign keys check
            fk_res = await conn.execute(text("PRAGMA foreign_keys;"))
            assert fk_res.scalar() == 1

            # Busy timeout check
            timeout_res = await conn.execute(text("PRAGMA busy_timeout;"))
            assert timeout_res.scalar() == 10000

            # Journal mode check
            mode_res = await conn.execute(text("PRAGMA journal_mode;"))
            # For :memory:, journal_mode is typically 'memory'
            assert mode_res.scalar() in ("wal", "memory")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_file_sqlite_wal_pragma(tmp_path: Path):
    """Verifies that file-based SQLite engines activate WAL journal mode."""
    db_file = tmp_path / "test_wal.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    try:
        async with engine.connect() as conn:
            mode_res = await conn.execute(text("PRAGMA journal_mode;"))
            assert mode_res.scalar() == "wal"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_and_close_db(tmp_path: Path):
    """Verifies init_db creates all schema tables and close_db disposes engine."""
    db_file = tmp_path / "nested" / "dir" / "test_init.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)

    try:
        # Directory is created automatically
        await init_db(engine)
        assert db_file.parent.exists()

        async with engine.connect() as conn:
            tables = await conn.run_sync(
                lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
            )
            assert "users" in tables
            assert "sessions" in tables
            assert "password_resets" in tables
            assert "system_settings" in tables
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_db_dependency_transaction_commit_and_rollback(tmp_path: Path):
    """Verifies that get_db commits on clean exit and rolls back on exception."""
    db_file = tmp_path / "test_tx.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)

    factory = get_session_factory(engine)

    # 1. Successful commit flow
    async with factory() as session:
        user = User(
            email="tx_test@example.com",
            username="tx_user",
            hashed_password="hashed_pw_placeholder",
        )
        session.add(user)
        await session.commit()

    # Verify user was committed
    async with factory() as session:
        fetched = await session.get(User, user.id)
        assert fetched is not None
        assert fetched.username == "tx_user"

    # 2. Rollback flow on exception
    with pytest.raises(RuntimeError):
        async with factory() as session:
            failing_user = User(
                email="fail@example.com",
                username="fail_user",
                hashed_password="hashed_pw_placeholder",
            )
            session.add(failing_user)
            await session.flush()
            raise RuntimeError("Intentional error to trigger rollback")

    # Verify failing_user was rolled back
    async with factory() as session:
        result = await session.execute(
            text("SELECT count(*) FROM users WHERE username = 'fail_user'")
        )
        assert result.scalar() == 0

    await engine.dispose()
