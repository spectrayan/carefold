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

"""Empirical stress tests for concurrent SQLite async writes under WAL mode & 10s busy timeout,
URL normalization, and password masking in sanitize_db_url.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import random
import uuid
import pytest
from sqlalchemy import text
from sqlalchemy.engine.url import make_url, URL
from sqlalchemy.exc import OperationalError

from carefold.db.models import Session as DbSession, SystemSetting, User
from carefold.db.session import (
    create_db_engine,
    get_session_factory,
    init_db,
    normalize_database_url,
    sanitize_db_url,
)


# ==============================================================================
# 1. EMPIRICAL CONCURRENCY TESTS (SQLite WAL + 10s busy timeout)
# ==============================================================================

@pytest.mark.asyncio
async def test_concurrent_sqlite_async_writes_wal(tmp_path: Path):
    """Stress test: 20 concurrent async workers writing 10 transactions each (200 total tx)

    verifies WAL mode and 10s busy timeout prevent 'database is locked' errors.
    """
    db_file = tmp_path / "concurrent_wal.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)

    factory = get_session_factory(engine)
    num_workers = 20
    tx_per_worker = 10
    total_expected = num_workers * tx_per_worker

    errors: list[Exception] = []

    async def worker(worker_id: int):
        for tx_idx in range(tx_per_worker):
            try:
                # Add tiny random jitter to maximize lock contention and interleaving
                await asyncio.sleep(random.uniform(0.001, 0.01))
                async with factory() as session:
                    user_id = str(uuid.uuid4())
                    user = User(
                        id=user_id,
                        email=f"user_w{worker_id}_tx{tx_idx}_{uuid.uuid4().hex[:6]}@example.com",
                        username=f"user_w{worker_id}_tx{tx_idx}_{uuid.uuid4().hex[:6]}",
                        hashed_password="hashed_pw_test",
                    )
                    session.add(user)
                    await session.commit()
            except Exception as exc:
                errors.append(exc)

    # Run all workers concurrently
    tasks = [asyncio.create_task(worker(w)) for w in range(num_workers)]
    await asyncio.gather(*tasks)

    # 1. Verify zero lock errors occurred
    assert len(errors) == 0, f"Encountered {len(errors)} errors during concurrent writes: {errors[:3]}"

    # 2. Verify all records were committed and readable
    async with factory() as session:
        result = await session.execute(text("SELECT count(*) FROM users"))
        actual_count = result.scalar()
        assert actual_count == total_expected, f"Expected {total_expected} users, found {actual_count}"

    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_simultaneous_burst_writes(tmp_path: Path):
    """Burst test: 50 concurrent async tasks attempting to commit simultaneously."""
    db_file = tmp_path / "burst_wal.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)

    factory = get_session_factory(engine)
    num_tasks = 50

    barrier = asyncio.Barrier(num_tasks)
    errors: list[Exception] = []

    async def burst_insert(task_id: int):
        await barrier.wait()  # Release all tasks at the exact same moment
        try:
            async with factory() as session:
                setting = SystemSetting(
                    key=f"setting_burst_{task_id}_{uuid.uuid4().hex[:4]}",
                    value_json='{"status": "ok"}',
                )
                session.add(setting)
                await session.commit()
        except Exception as exc:
            errors.append(exc)

    await asyncio.gather(*[burst_insert(i) for i in range(num_tasks)])

    assert len(errors) == 0, f"Encountered errors under burst writes: {errors}"

    async with factory() as session:
        result = await session.execute(text("SELECT count(*) FROM system_settings"))
        assert result.scalar() == num_tasks

    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_readers_and_writers_simultaneous(tmp_path: Path):
    """Interleaved stress test: 15 writers and 15 readers running simultaneously

    under WAL mode, readers do not block writers and writers do not block readers.
    """
    db_file = tmp_path / "readers_writers_wal.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)

    factory = get_session_factory(engine)
    stop_event = asyncio.Event()
    writer_errors: list[Exception] = []
    reader_errors: list[Exception] = []
    reads_completed = 0

    async def writer_task(w_id: int):
        for i in range(15):
            try:
                async with factory() as session:
                    u = User(
                        id=str(uuid.uuid4()),
                        email=f"rw_{w_id}_{i}_{uuid.uuid4().hex[:4]}@example.com",
                        username=f"rw_{w_id}_{i}_{uuid.uuid4().hex[:4]}",
                        hashed_password="pw",
                    )
                    session.add(u)
                    await session.commit()
                await asyncio.sleep(0.005)
            except Exception as exc:
                writer_errors.append(exc)

    async def reader_task():
        nonlocal reads_completed
        while not stop_event.is_set():
            try:
                async with factory() as session:
                    res = await session.execute(text("SELECT count(*) FROM users"))
                    _ = res.scalar()
                    reads_completed += 1
                await asyncio.sleep(0.002)
            except Exception as exc:
                reader_errors.append(exc)

    # Start 15 readers
    readers = [asyncio.create_task(reader_task()) for _ in range(15)]
    # Start 15 writers
    writers = [asyncio.create_task(writer_task(i)) for i in range(15)]

    await asyncio.gather(*writers)
    stop_event.set()
    await asyncio.gather(*readers)

    assert len(writer_errors) == 0, f"Writer errors: {writer_errors}"
    assert len(reader_errors) == 0, f"Reader errors: {reader_errors}"
    assert reads_completed > 50, f"Expected substantial concurrent reads, got {reads_completed}"

    async with factory() as session:
        res = await session.execute(text("SELECT count(*) FROM users"))
        assert res.scalar() == 15 * 15

    await engine.dispose()


@pytest.mark.asyncio
async def test_control_contrast_wal_vs_non_wal(tmp_path: Path):
    """Empirical control experiment: Verify that without WAL / busy_timeout,

    concurrent writes frequently encounter database locking or timeout failures.
    This empirically proves the effectiveness of Carefold's WAL + 10s busy timeout configuration.
    """
    db_file = tmp_path / "control_nowal.db"
    # Connect directly without WAL/busy_timeout pragma and with 0 timeout
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    nowal_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file.resolve()}",
        poolclass=NullPool,
        connect_args={"check_same_thread": False, "timeout": 0.01},  # 10ms timeout, DELETE journal mode
    )
    # create table
    async with nowal_engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode = DELETE;"))
        await conn.execute(text("PRAGMA busy_timeout = 10;"))  # tiny timeout
        await conn.execute(text("CREATE TABLE test_lock (id INT PRIMARY KEY, val TEXT);"))

    factory_nowal = get_session_factory(nowal_engine)

    lock_errors: list[Exception] = []

    async def contentious_writer(i: int):
        try:
            async with factory_nowal() as session:
                await session.execute(text(f"INSERT INTO test_lock VALUES ({i}, 'val')"))
                # hold transaction open briefly
                await asyncio.sleep(0.05)
                await session.commit()
        except Exception as exc:
            lock_errors.append(exc)

    # 10 contentious writers without WAL and tiny timeout
    await asyncio.gather(*[contentious_writer(i) for i in range(10)])

    # Under non-WAL and 10ms timeout, locking errors are expected
    # This proves the control condition reproduces the locking failure
    assert len(lock_errors) > 0, "Control test expected to reproduce database is locked under non-WAL/10ms timeout"

    await nowal_engine.dispose()


# ==============================================================================
# 2. URL NORMALIZATION TESTS
# ==============================================================================

def test_normalize_database_url_comprehensive():
    """Empirical verification of URL normalization across schemes, query params, and paths."""
    # 1. postgres:// -> postgresql+asyncpg://
    assert (
        normalize_database_url("postgres://app:secret@db.service.internal:5432/carefold")
        == "postgresql+asyncpg://app:secret@db.service.internal:5432/carefold"
    )
    # 2. postgresql:// -> postgresql+asyncpg://
    assert (
        normalize_database_url("postgresql://app:secret@db.service.internal:5432/carefold")
        == "postgresql+asyncpg://app:secret@db.service.internal:5432/carefold"
    )
    # 3. postgresql+psycopg2:// -> postgresql+asyncpg://
    assert (
        normalize_database_url("postgresql+psycopg2://app:secret@localhost:5432/carefold")
        == "postgresql+asyncpg://app:secret@localhost:5432/carefold"
    )
    # 4. sqlite:///relative/path -> sqlite+aiosqlite:///relative/path
    assert (
        normalize_database_url("sqlite:///workspace/carefold.db")
        == "sqlite+aiosqlite:///workspace/carefold.db"
    )
    # 5. sqlite:////absolute/path -> sqlite+aiosqlite:////absolute/path
    assert (
        normalize_database_url("sqlite:////var/data/carefold/db.sqlite")
        == "sqlite+aiosqlite:////var/data/carefold/db.sqlite"
    )
    # 6. :memory: -> sqlite+aiosqlite:///:memory:
    assert normalize_database_url(":memory:") == "sqlite+aiosqlite:///:memory:"

    # 7. sqlite:///:memory: -> sqlite+aiosqlite:///:memory:
    assert (
        normalize_database_url("sqlite:///:memory:")
        == "sqlite+aiosqlite:///:memory:"
    )

    # 8. Leading and trailing whitespace handling
    assert (
        normalize_database_url("   postgres://user:pass@host/db   ")
        == "postgresql+asyncpg://user:pass@host/db"
    )
    assert (
        normalize_database_url("\n\tsqlite:///test.db\n")
        == "sqlite+aiosqlite:///test.db"
    )

    # 9. Query parameters preserved
    assert (
        normalize_database_url("postgresql://user:pass@localhost:5432/db?sslmode=require&target_session_attrs=read-write")
        == "postgresql+asyncpg://user:pass@localhost:5432/db?sslmode=require&target_session_attrs=read-write"
    )
    assert (
        normalize_database_url("sqlite:///test.db?uri=true&timeout=10")
        == "sqlite+aiosqlite:///test.db?uri=true&timeout=10"
    )

    # 10. Already normalized passes through idempotently
    already_pg = "postgresql+asyncpg://user:pass@localhost/db"
    assert normalize_database_url(already_pg) == already_pg
    already_sqlite = "sqlite+aiosqlite:///test.db"
    assert normalize_database_url(already_sqlite) == already_sqlite

    # 11. Idempotence property: normalize(normalize(x)) == normalize(x)
    for sample in [
        "postgres://user:pass@host/db",
        "sqlite:///my.db",
        ":memory:",
        "postgresql+psycopg2://user:pass@host/db",
    ]:
        first = normalize_database_url(sample)
        second = normalize_database_url(first)
        assert first == second


# ==============================================================================
# 3. PASSWORD MASKING & CREDENTIAL SANITIZATION TESTS
# ==============================================================================

def test_sanitize_db_url_credential_masking():
    """Empirical verification that passwords and credentials are never exposed in sanitized URLs."""
    # 1. Standard password
    url1 = "postgresql+asyncpg://admin_user:SuperSecretPassword123@db.prod.internal:5432/carefold_prod"
    res1 = sanitize_db_url(url1)
    assert "SuperSecretPassword123" not in res1
    assert "admin_user" in res1
    assert "***" in res1

    # 2. Complex password with special characters (URL encoded)
    url2 = "postgresql+asyncpg://user_db:P%40%24%24w0rd%21%23%25@db.host.com:5432/mydb"
    res2 = sanitize_db_url(url2)
    assert "P%40%24%24w0rd" not in res2
    assert "user_db" in res2

    # 3. Passwords with colons or slashes
    url3 = "postgresql://user:p:a:s:s@localhost:5432/db"
    res3 = sanitize_db_url(url3)
    assert "p:a:s:s" not in res3
    assert "user" in res3

    # 4. SQLAlchemy URL object input
    sqla_url = make_url("postgresql+asyncpg://user:secrettoken@localhost:5432/carefold")
    res4 = sanitize_db_url(sqla_url)
    assert "secrettoken" not in res4
    assert "user" in res4

    # 5. URL without password
    url5 = "postgresql+asyncpg://user_nopass@localhost:5432/carefold"
    res5 = sanitize_db_url(url5)
    assert "user_nopass" in res5

    # 6. URL with empty password (user:)
    url6 = "postgresql+asyncpg://user:@localhost:5432/carefold"
    res6 = sanitize_db_url(url6)
    assert "user" in res6

    # 7. SQLite URL (no credentials) passes through cleanly
    url7 = "sqlite+aiosqlite:///workspace/carefold.db"
    res7 = sanitize_db_url(url7)
    assert res7 == url7

    # 8. Malformed / custom URI triggering regex fallback path
    # e.g. scheme with unusual syntax that might make make_url fail
    malformed = "custom+driver://secretuser:secretpass123@10.0.0.1:9999/database"
    res8 = sanitize_db_url(malformed)
    assert "secretpass123" not in res8
    assert "secretuser" in res8
    assert "***" in res8
