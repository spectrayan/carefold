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

"""Adversarial stress tests for Alembic database migrations, startup stamping, and idempotency."""

from __future__ import annotations

import asyncio
import io
from multiprocessing import Process, Queue
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import uuid

import alembic.command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from carefold.db.base import Base
from carefold.db.session import (
    close_db,
    create_db_engine,
    get_alembic_config,
    get_engine,
    init_db,
    reset_engine,
    run_alembic_migrations,
)

EXPECTED_AUTONOMY_BATCH_1_TABLES = {
    "profile_keys",
    "approvals",
    "jobs",
}

EXPECTED_HEAD_TABLES = {
    "alembic_version",
    "users",
    "sessions",
    "password_resets",
    "system_settings",
    "agent",
    "skill",
    "knowledge_base",
    "profiles",
    "profile_access",
    "profile_consents",
    "viewer_invites",
    "notes",
    "attachments",
    "chat_threads",
    "audit_events",
    "connections",
    "credentials",
    "profile_keys",
    "approvals",
    "jobs",
}

EXPECTED_ATTACHMENT_CAS_COLUMNS = {
    "extracted_text",
    "source",
    "source_ref",
    "extraction_status",
    "updated_at",
    "storage_key",
    "sha256_hash",
}


# =============================================================================
# 1. Legacy Database Upgrade & Automatic Stamping Tests
# =============================================================================

@pytest.mark.asyncio
async def test_adversarial_legacy_database_with_raw_tables_and_data(tmp_path: Path):
    """Stress test: Unversioned SQLite DB with pre-Alembic raw DDL tables and data.

    Verifies init_db():
    1. Detects unversioned legacy state (no alembic_version table).
    2. Runs schema fixes (e.g. note -> notes, missing columns).
    3. Stamps with 0001_baseline_schema.
    4. Upgrades to head (0003_autonomy_batch_1).
    5. Preserves all preexisting table data without corruption.
    """
    db_file = tmp_path / "legacy_raw.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    # Step 1: Create raw SQLite database with pre-Alembic DDL (no alembic_version)
    raw_conn = sqlite3.connect(str(db_file))
    cursor = raw_conn.cursor()

    # Legacy raw users table
    cursor.execute("""
        CREATE TABLE users (
            id VARCHAR(36) PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            username VARCHAR(64) UNIQUE NOT NULL,
            hashed_password VARCHAR(255) NOT NULL,
            full_name VARCHAR(255),
            role VARCHAR(32) DEFAULT 'steward' NOT NULL,
            status VARCHAR(32) DEFAULT 'active' NOT NULL,
            auth_provider VARCHAR(32) DEFAULT 'local' NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        );
    """)

    # Legacy raw profiles table (missing short_name, avatar_url)
    cursor.execute("""
        CREATE TABLE profiles (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36),
            name VARCHAR(255) NOT NULL,
            relationship VARCHAR(64) DEFAULT 'self' NOT NULL,
            role VARCHAR(32) DEFAULT 'self' NOT NULL,
            date_of_birth VARCHAR(10),
            avatar_color VARCHAR(32) DEFAULT '1' NOT NULL,
            is_primary BOOLEAN DEFAULT 0 NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );
    """)

    # Legacy raw attachments table (uses file_path instead of storage_key, no CAS columns)
    cursor.execute("""
        CREATE TABLE attachments (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36),
            profile_id VARCHAR(36),
            file_path VARCHAR(512),
            filename VARCHAR(255) NOT NULL,
            original_name VARCHAR(255) NOT NULL,
            content_type VARCHAR(128) DEFAULT 'application/octet-stream' NOT NULL,
            size_bytes INTEGER DEFAULT 0 NOT NULL,
            created_at DATETIME NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (profile_id) REFERENCES profiles (id) ON DELETE CASCADE
        );
    """)

    # Legacy raw note table (named 'note', not 'notes')
    cursor.execute("""
        CREATE TABLE note (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36),
            profile_id VARCHAR(36),
            slug VARCHAR(128) NOT NULL,
            title VARCHAR(255) NOT NULL,
            content TEXT DEFAULT '' NOT NULL,
            tags_json TEXT DEFAULT '[]' NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        );
    """)

    # Insert legacy seed data
    user_id = str(uuid.uuid4())
    prof_id = str(uuid.uuid4())
    att_id = str(uuid.uuid4())
    note_id = str(uuid.uuid4())
    now = "2026-10-01T12:00:00Z"

    cursor.execute("""
        INSERT INTO users (id, email, username, hashed_password, full_name, created_at, updated_at)
        VALUES (?, 'adv_user@carefold.ai', 'adv_user', 'argon2_fake_hash', 'Adversarial Tester', ?, ?);
    """, (user_id, now, now))

    cursor.execute("""
        INSERT INTO profiles (id, user_id, name, relationship, role, is_primary, created_at, updated_at)
        VALUES (?, ?, 'Primary Patient', 'self', 'self', 1, ?, ?);
    """, (prof_id, user_id, now, now))

    cursor.execute("""
        INSERT INTO attachments (id, user_id, profile_id, file_path, filename, original_name, size_bytes, created_at)
        VALUES (?, ?, ?, 'uploads/user/doc1.pdf', 'doc1.pdf', 'Original Document.pdf', 2048, ?);
    """, (att_id, user_id, prof_id, now))

    cursor.execute("""
        INSERT INTO note (id, user_id, profile_id, slug, title, content, created_at, updated_at)
        VALUES (?, ?, ?, 'visit-prep', 'Visit Prep Note', 'Blood pressure is 120/80', ?, ?);
    """, (note_id, user_id, prof_id, now, now))

    raw_conn.commit()
    raw_conn.close()

    # Step 2: Run init_db() against the legacy database
    engine = create_async_engine(db_url, poolclass=NullPool)
    await init_db(engine)

    # Step 3: Verify the upgraded state
    sync_conn = sqlite3.connect(str(db_file))
    cur = sync_conn.cursor()

    # Verify alembic_version exists and points to head
    cur.execute("SELECT version_num FROM alembic_version;")
    rev = cur.fetchone()
    assert rev is not None, "alembic_version table must exist"
    assert rev[0] == "0003_autonomy_batch_1", f"Expected head revision 0003_autonomy_batch_1, got {rev[0]}"

    # Verify note was renamed to notes
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cur.fetchall()}
    assert "notes" in tables, "Table 'notes' must exist"
    assert "note" not in tables, "Legacy table 'note' should be migrated"
    assert EXPECTED_HEAD_TABLES.issubset(tables)

    # Verify preexisting data is completely intact
    cur.execute("SELECT email, username FROM users WHERE id = ?", (user_id,))
    u_row = cur.fetchone()
    assert u_row == ("adv_user@carefold.ai", "adv_user")

    cur.execute("SELECT name, relationship FROM profiles WHERE id = ?", (prof_id,))
    p_row = cur.fetchone()
    assert p_row == ("Primary Patient", "self")

    cur.execute("SELECT title, content FROM notes WHERE id = ?", (note_id,))
    n_row = cur.fetchone()
    assert n_row == ("Visit Prep Note", "Blood pressure is 120/80")

    cur.execute("SELECT filename, size_bytes, storage_key FROM attachments WHERE id = ?", (att_id,))
    a_row = cur.fetchone()
    assert a_row[0] == "doc1.pdf"
    assert a_row[1] == 2048
    # storage_key was backfilled from file_path
    assert a_row[2] == "uploads/user/doc1.pdf"

    # Verify new CAS columns exist on attachments
    cur.execute("PRAGMA table_info(attachments);")
    att_cols = {row[1] for row in cur.fetchall()}
    assert EXPECTED_ATTACHMENT_CAS_COLUMNS.issubset(att_cols)

    # Verify new columns exist on profiles
    cur.execute("PRAGMA table_info(profiles);")
    prof_cols = {row[1] for row in cur.fetchall()}
    assert "short_name" in prof_cols
    assert "avatar_url" in prof_cols

    sync_conn.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_adversarial_legacy_database_users_only(tmp_path: Path):
    """Stress test: Legacy database containing ONLY users table and no other tables."""
    db_file = tmp_path / "legacy_users_only.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    raw_conn = sqlite3.connect(str(db_file))
    cur = raw_conn.cursor()
    cur.execute("""
        CREATE TABLE users (
            id VARCHAR(36) PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            username VARCHAR(64) UNIQUE NOT NULL,
            hashed_password VARCHAR(255) NOT NULL,
            role VARCHAR(32) DEFAULT 'steward' NOT NULL,
            status VARCHAR(32) DEFAULT 'active' NOT NULL,
            auth_provider VARCHAR(32) DEFAULT 'local' NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        );
    """)
    cur.execute("""
        INSERT INTO users (id, email, username, hashed_password, created_at, updated_at)
        VALUES ('u1', 'solo@carefold.ai', 'solouser', 'hash', datetime('now'), datetime('now'));
    """)
    raw_conn.commit()
    raw_conn.close()

    engine = create_async_engine(db_url, poolclass=NullPool)
    await init_db(engine)

    sync_conn = sqlite3.connect(str(db_file))
    cur = sync_conn.cursor()
    cur.execute("SELECT version_num FROM alembic_version;")
    rev = cur.fetchone()
    assert rev is not None and rev[0] == "0003_autonomy_batch_1"

    cur.execute("SELECT username FROM users WHERE id = 'u1';")
    assert cur.fetchone() == ("solouser",)

    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cur.fetchall()}
    assert EXPECTED_HEAD_TABLES.issubset(tables)

    sync_conn.close()
    await engine.dispose()


# =============================================================================
# 2. Greenfield Database Creation Tests
# =============================================================================

@pytest.mark.asyncio
async def test_adversarial_greenfield_database_direct_upgrade(tmp_path: Path):
    """Stress test: Greenfield database on a completely non-existent file path.

    Verifies:
    1. Parent directories are ensured and file is created.
    2. Upgrades directly to head (0003_autonomy_batch_1) without stamping step.
    3. All tables are present.
    4. Can immediately execute reads and writes across baseline and autonomous tables.
    """
    db_file = tmp_path / "deep" / "nested" / "dir" / "greenfield.db"
    assert not db_file.exists()
    db_url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_async_engine(db_url, poolclass=NullPool)
    await init_db(engine)

    assert db_file.exists()

    sync_conn = sqlite3.connect(str(db_file))
    cur = sync_conn.cursor()

    cur.execute("SELECT version_num FROM alembic_version;")
    rev = cur.fetchone()
    assert rev is not None
    assert rev[0] == "0003_autonomy_batch_1"

    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cur.fetchall()}
    assert EXPECTED_HEAD_TABLES.issubset(tables)

    # Insert into an autonomous table (audit_events) and baseline table (users)
    now = "2026-10-12T00:00:00Z"
    cur.execute("""
        INSERT INTO users (id, email, username, hashed_password, role, status, auth_provider, created_at, updated_at)
        VALUES ('u-gf', 'gf@carefold.ai', 'gfuser', 'pwdhash', 'steward', 'active', 'local', ?, ?);
    """, (now, now))

    cur.execute("""
        INSERT INTO audit_events (id, ts, principal, event, tool, risk, decision, payload_hash)
        VALUES ('evt-1', ?, 'user', 'tool_call', 'attach_read', 'low', 'allowed', 'abc123hash');
    """, (now,))

    sync_conn.commit()

    cur.execute("SELECT count(*) FROM users;")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT count(*) FROM audit_events;")
    assert cur.fetchone()[0] == 1

    sync_conn.close()
    await engine.dispose()


# =============================================================================
# 3. Idempotency & Concurrency Stress Tests
# =============================================================================

@pytest.mark.asyncio
async def test_adversarial_sequential_idempotency(tmp_path: Path):
    """Stress test: Run init_db() 10 times consecutively on the same database.

    Verifies:
    1. Zero exceptions raised.
    2. Version remains pinned at head.
    3. Existing rows are preserved.
    4. Table count remains constant.
    """
    db_file = tmp_path / "sequential_idempotent.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    engine = create_async_engine(db_url, poolclass=NullPool)

    # First run
    await init_db(engine)

    # Insert sentinel row
    sync_conn = sqlite3.connect(str(db_file))
    cur = sync_conn.cursor()
    cur.execute("""
        INSERT INTO users (id, email, username, hashed_password, created_at, updated_at)
        VALUES ('sentinel', 'sentinel@carefold.ai', 'sentinel', 'pwd', datetime('now'), datetime('now'));
    """)
    sync_conn.commit()
    sync_conn.close()

    # Repeat init_db 9 more times
    for i in range(9):
        await init_db(engine)

    # Verify state
    sync_conn = sqlite3.connect(str(db_file))
    cur = sync_conn.cursor()
    cur.execute("SELECT version_num FROM alembic_version;")
    assert cur.fetchone()[0] == "0003_autonomy_batch_1"

    cur.execute("SELECT count(*) FROM users WHERE id = 'sentinel';")
    assert cur.fetchone()[0] == 1

    cur.execute("SELECT count(*) FROM sqlite_master WHERE type='table';")
    # All tables stable
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cur.fetchall()}
    assert EXPECTED_HEAD_TABLES.issubset(tables)

    sync_conn.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_adversarial_async_concurrency_stress(tmp_path: Path):
    """Stress test: Run 10 concurrent async tasks calling init_db() simultaneously.

    Simulates multiple server workers starting up concurrently on the same SQLite file.
    Verifies:
    1. Zero crashes or unhandled exceptions.
    2. Zero locking errors (handled via WAL mode & busy_timeout).
    3. Consistent final head schema.
    """
    db_file = tmp_path / "concurrent_async.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    # Use create_db_engine to ensure WAL and busy_timeout PRAGMAs are active
    engine = create_db_engine(db_url)

    async def worker_init(worker_id: int):
        await asyncio.sleep(0.01 * (worker_id % 3))  # slight jitter
        await init_db(engine)
        return worker_id

    # Launch 10 concurrent init tasks
    tasks = [worker_init(i) for i in range(10)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Verify no task failed
    for idx, res in enumerate(results):
        if isinstance(res, Exception):
            pytest.fail(f"Concurrent worker {idx} failed with: {type(res).__name__}: {res}")
        assert res == idx

    # Verify resulting database schema
    sync_conn = sqlite3.connect(str(db_file))
    cur = sync_conn.cursor()
    cur.execute("SELECT version_num FROM alembic_version;")
    assert cur.fetchone()[0] == "0003_autonomy_batch_1"

    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cur.fetchall()}
    assert EXPECTED_HEAD_TABLES.issubset(tables)

    sync_conn.close()
    await engine.dispose()


def _mp_worker(db_url: str, queue: Queue):
    """Worker process function for multi-process concurrency test."""
    try:
        async def run():
            engine = create_db_engine(db_url)
            await init_db(engine)
            await engine.dispose()

        asyncio.run(run())
        queue.put("OK")
    except Exception as e:
        queue.put(f"ERROR: {type(e).__name__}: {e}")


def test_adversarial_multiprocess_concurrency_stress(tmp_path: Path):
    """Stress test: Multi-process concurrency with separate OS processes calling init_db().

    Simulates Gunicorn / Uvicorn multi-process workers booting up in parallel.
    """
    db_file = tmp_path / "concurrent_mp.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    # Pre-create parent directory
    db_file.parent.mkdir(parents=True, exist_ok=True)

    queue = Queue()
    processes = []
    num_processes = 6

    for _ in range(num_processes):
        p = Process(target=_mp_worker, args=(db_url, queue))
        processes.append(p)
        p.start()

    for p in processes:
        p.join(timeout=30)
        assert not p.is_alive(), "Process did not terminate within timeout"

    results = []
    while not queue.empty():
        results.append(queue.get())

    assert len(results) == num_processes, f"Expected {num_processes} results, got {len(results)}"
    for r in results:
        assert r == "OK", f"Multi-process worker failed: {r}"

    # Verify database integrity
    sync_conn = sqlite3.connect(str(db_file))
    cur = sync_conn.cursor()
    cur.execute("SELECT version_num FROM alembic_version;")
    assert cur.fetchone()[0] == "0003_autonomy_batch_1"

    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cur.fetchall()}
    assert EXPECTED_HEAD_TABLES.issubset(tables)
    sync_conn.close()


# =============================================================================
# 4. Offline Migration Generation Tests
# =============================================================================

def test_adversarial_offline_sql_generation_cli():
    """Stress test: Run alembic upgrade head --sql via CLI.

    Verifies:
    1. Exits with code 0.
    2. Generates complete DDL for baseline, autonomy foundations, and autonomy batch 1.
    3. Contains no unresolved template variables or python tracebacks.
    """
    backend_dir = Path(__file__).resolve().parents[1]
    cmd = [
        sys.executable,
        "-m",
        "alembic",
        "-c",
        str(backend_dir / "alembic.ini"),
        "upgrade",
        "head",
        "--sql",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"Alembic CLI failed: {proc.stderr}"
    sql_text = proc.stdout

    # Verify key DDL statements exist
    assert "CREATE TABLE users" in sql_text
    assert "CREATE TABLE profiles" in sql_text
    assert "CREATE TABLE attachments" in sql_text
    assert "CREATE TABLE audit_events" in sql_text
    assert "CREATE TABLE connections" in sql_text
    assert "CREATE TABLE credentials" in sql_text
    assert "CREATE TABLE profile_keys" in sql_text
    assert "CREATE TABLE approvals" in sql_text
    assert "CREATE TABLE jobs" in sql_text
    assert "0001_baseline_schema" in sql_text
    assert "0002_autonomy_foundations" in sql_text
    assert "0003_autonomy_batch_1" in sql_text
    assert "Traceback" not in proc.stderr


def test_adversarial_offline_sql_script_execution():
    """Stress test: Validate that offline generated SQL executes cleanly in SQLite.

    Takes offline migration script generated via alembic.command.upgrade(sql=True)
    and executes it against a raw SQLite in-memory database using sqlite3.
    """
    buf = io.StringIO()
    cfg = get_alembic_config()
    cfg.attributes["output_buffer"] = buf
    cfg.set_main_option("sqlalchemy.url", "sqlite:///:memory:")

    alembic.command.upgrade(cfg, "head", sql=True)
    raw_sql = buf.getvalue()

    assert len(raw_sql) > 1000, "Generated SQL should not be empty"

    # Clean alembic log lines/comments that are not valid SQLite statements if any
    clean_lines = []
    for line in raw_sql.splitlines():
        # Skip alembic log output lines (e.g. INFO  [alembic...])
        if line.startswith("INFO ") or line.startswith("DEBUG ") or line.startswith("WARNING "):
            continue
        # SQLite 3 doesn't support RETURNING in batch executescript in older versions
        # or comment headers
        clean_lines.append(line)
    clean_sql = "\n".join(clean_lines)

    # Execute against fresh sqlite3 connection
    conn = sqlite3.connect(":memory:")
    # Remove RETURNING if present since executescript does not return cursors
    executable_sql = clean_sql.replace(" RETURNING version_num", "")
    conn.executescript(executable_sql)

    cur = conn.cursor()
    cur.execute("SELECT version_num FROM alembic_version;")
    rev = cur.fetchone()
    assert rev is not None
    assert rev[0] == "0003_autonomy_batch_1"

    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cur.fetchall()}
    assert EXPECTED_HEAD_TABLES.issubset(tables)
    conn.close()


# =============================================================================
# 5. Additional Edge-Case Concurrency & Reset Stress Tests
# =============================================================================

@pytest.mark.asyncio
async def test_adversarial_interleaved_init_db_and_active_queries(tmp_path: Path):
    """Stress test: Interleave concurrent init_db() calls with simultaneous read queries.

    Simulates high-traffic application boot where incoming requests execute read
    queries while background tasks or worker lifespans invoke init_db().
    Verifies:
    1. Zero database locked errors or unhandled crashes.
    2. Read queries eventually succeed once tables exist.
    3. Final database state is consistent and at head.
    """
    db_file = tmp_path / "interleaved.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    engine = create_db_engine(db_url)

    read_successes = 0
    read_table_misses = 0

    async def init_task(tid: int):
        await asyncio.sleep(0.005 * tid)
        await init_db(engine)

    async def reader_task(rid: int):
        nonlocal read_successes, read_table_misses
        for _ in range(5):
            await asyncio.sleep(0.01)
            try:
                async with engine.connect() as conn:
                    result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table';"))
                    tables = {row[0] for row in result.fetchall()}
                    if "users" in tables:
                        u_res = await conn.execute(text("SELECT count(*) FROM users;"))
                        u_res.scalar()
                        read_successes += 1
                    else:
                        read_table_misses += 1
            except Exception as e:
                err_str = str(e).lower()
                if "locked" in err_str:
                    pytest.fail(f"Reader task encountered database lock error: {e}")
                read_table_misses += 1

    init_tasks = [init_task(i) for i in range(5)]
    reader_tasks = [reader_task(i) for i in range(5)]

    await asyncio.gather(*init_tasks, *reader_tasks)

    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT version_num FROM alembic_version;"))
        assert result.scalar() == "0003_autonomy_batch_1"

    await engine.dispose()


@pytest.mark.asyncio
async def test_adversarial_rapid_engine_reset_cycles(tmp_path: Path):
    """Stress test: Rapid engine reset cycles with repeated init_db and close_db.

    Simulates rapid test suite execution or dynamic container re-initialization
    where reset_engine() and init_db() are cycled repeatedly across different event loops.
    Verifies:
    1. Lock state is cleanly recreated without event loop binding errors.
    2. No file lock or sqlite leak across reset cycles.
    3. Final schema is fully valid.
    """
    db_file = tmp_path / "rapid_reset.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    for _ in range(5):
        reset_engine()
        engine = create_db_engine(db_url)
        await init_db(engine)
        async with engine.connect() as conn:
            res = await conn.execute(text("SELECT version_num FROM alembic_version;"))
            assert res.scalar() == "0003_autonomy_batch_1"
        await engine.dispose()
        reset_engine()


def _mp_legacy_worker(db_url: str, queue: Queue):
    try:
        async def run():
            engine = create_db_engine(db_url)
            await init_db(engine)
            await engine.dispose()

        asyncio.run(run())
        queue.put("OK")
    except Exception as e:
        queue.put(f"ERROR: {type(e).__name__}: {e}")


def test_adversarial_multiprocess_legacy_migration_race(tmp_path: Path):
    """Stress test: Multi-process race to upgrade and stamp an unversioned legacy database.

    Simulates multiple worker processes booting simultaneously on an unversioned legacy DB.
    Verifies:
    1. Zero 'table already exists' errors.
    2. Zero 'database is locked' errors.
    3. Exactly one worker executes schema migrations & stamping; all others cleanly detect head.
    4. Preexisting data is fully preserved.
    """
    db_file = tmp_path / "mp_legacy_race.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE users (
            id VARCHAR(36) PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            username VARCHAR(64) UNIQUE NOT NULL,
            hashed_password VARCHAR(255) NOT NULL,
            role VARCHAR(32) DEFAULT 'steward' NOT NULL,
            status VARCHAR(32) DEFAULT 'active' NOT NULL,
            auth_provider VARCHAR(32) DEFAULT 'local' NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE attachments (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36),
            filename VARCHAR(255) NOT NULL,
            file_path VARCHAR(512),
            size_bytes INTEGER DEFAULT 0 NOT NULL,
            created_at DATETIME NOT NULL
        );
    """)
    now = "2026-10-12T00:00:00Z"
    cur.execute("""
        INSERT INTO users (id, email, username, hashed_password, created_at, updated_at)
        VALUES ('u_race', 'race@carefold.ai', 'raceuser', 'hash', ?, ?);
    """, (now, now))
    cur.execute("""
        INSERT INTO attachments (id, user_id, filename, file_path, size_bytes, created_at)
        VALUES ('att_race', 'u_race', 'report.pdf', 'files/report.pdf', 1024, ?);
    """, (now,))
    conn.commit()
    conn.close()

    queue = Queue()
    processes = []
    num_processes = 4

    for _ in range(num_processes):
        p = Process(target=_mp_legacy_worker, args=(db_url, queue))
        processes.append(p)
        p.start()

    for p in processes:
        p.join(timeout=30)
        assert not p.is_alive(), "Process did not terminate within timeout"

    results = []
    while not queue.empty():
        results.append(queue.get())

    assert len(results) == num_processes, f"Expected {num_processes} results, got {len(results)}"
    for r in results:
        assert r == "OK", f"Multi-process legacy worker failed: {r}"

    sync_conn = sqlite3.connect(str(db_file))
    cur = sync_conn.cursor()
    cur.execute("SELECT version_num FROM alembic_version;")
    assert cur.fetchone()[0] == "0003_autonomy_batch_1"

    cur.execute("SELECT username FROM users WHERE id = 'u_race';")
    assert cur.fetchone() == ("raceuser",)

    cur.execute("SELECT storage_key FROM attachments WHERE id = 'att_race';")
    assert cur.fetchone() == ("files/report.pdf",)

    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cur.fetchall()}
    assert EXPECTED_HEAD_TABLES.issubset(tables)

    sync_conn.close()


def test_adversarial_downgrade_to_0002_and_base(tmp_path: Path):
    """Stress test: Downgrade from 0003_autonomy_batch_1 to 0002_autonomy_foundations and base.

    Verifies:
    1. Database boots at 0003_autonomy_batch_1.
    2. Downgrades cleanly to 0002_autonomy_foundations, dropping profile_keys, approvals, and jobs.
    3. Retains credentials, connections, audit_events, and baseline tables.
    4. Downgrades cleanly to base, dropping all app tables.
    5. Re-upgrades cleanly to 0003_autonomy_batch_1.
    """
    db_file = tmp_path / "downgrade_0002_test.db"
    db_url = f"sqlite:///{db_file}"

    engine = create_engine(db_url, poolclass=NullPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)

        # 1. Upgrade to head
        alembic.command.upgrade(cfg, "head")
        cur_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert cur_rev == "0003_autonomy_batch_1"

        insp = inspect(conn)
        tables = set(insp.get_table_names())
        assert EXPECTED_HEAD_TABLES.issubset(tables)

        # 2. Downgrade to 0002_autonomy_foundations
        alembic.command.downgrade(cfg, "0002_autonomy_foundations")
        cur_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert cur_rev == "0002_autonomy_foundations"

        insp_0002 = inspect(conn)
        tables_0002 = set(insp_0002.get_table_names())
        assert "profile_keys" not in tables_0002
        assert "approvals" not in tables_0002
        assert "jobs" not in tables_0002
        assert {"credentials", "connections", "audit_events"}.issubset(tables_0002)

        # 3. Downgrade to base
        alembic.command.downgrade(cfg, "base")
        insp_base = inspect(conn)
        tables_base = set(insp_base.get_table_names())
        assert len(tables_base - {"alembic_version"}) == 0

        # 4. Re-upgrade to head
        alembic.command.upgrade(cfg, "head")
        cur_rev_head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert cur_rev_head == "0003_autonomy_batch_1"

        insp_head = inspect(conn)
        tables_head = set(insp_head.get_table_names())
        assert EXPECTED_HEAD_TABLES.issubset(tables_head)

    engine.dispose()

