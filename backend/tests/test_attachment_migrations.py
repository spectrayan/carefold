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

"""Integration tests for safe SQLite schema evolution and data backfill for attachments."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.db.session import create_db_engine, get_session_factory, init_db


@pytest.mark.asyncio
async def test_fresh_db_has_attachment_storage_columns_and_indices(tmp_path: Path):
    """Verifies that a newly initialized database contains storage_key, sha256_hash, and indices."""
    db_file = tmp_path / "fresh_test.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)

    async with engine.connect() as conn:
        # Check column existence via PRAGMA table_info
        cols_res = await conn.execute(text("PRAGMA table_info(attachments);"))
        cols = {row[1]: row[2] for row in cols_res.fetchall()}
        assert "storage_key" in cols
        assert "sha256_hash" in cols

        # Check index existence via PRAGMA index_list
        idx_res = await conn.execute(text("PRAGMA index_list(attachments);"))
        idx_names = {row[1] for row in idx_res.fetchall()}
        assert "ix_attachments_storage_key" in idx_names
        assert "ix_attachments_sha256_hash" in idx_names

    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_adds_missing_columns_and_backfills_legacy_db(tmp_path: Path):
    """Simulates a legacy pre-M3 database and verifies safe schema evolution and backfill."""
    db_file = tmp_path / "legacy_test.db"

    # 1. Create a legacy SQLite table using raw sqlite3 matching workspace/carefold.db exactly
    with sqlite3.connect(str(db_file)) as raw_conn:
        raw_conn.execute("""
            CREATE TABLE attachments (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                user_id VARCHAR(36),
                profile_id VARCHAR(36),
                filename VARCHAR(255) NOT NULL,
                original_name VARCHAR(255) NOT NULL,
                content_type VARCHAR(128) NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at DATETIME NOT NULL
            );
        """)
        # Insert 4 legacy records (reproducing workspace/carefold.db and multi-tenant cases)
        raw_conn.executemany("""
            INSERT INTO attachments (id, user_id, profile_id, filename, original_name, content_type, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, [
            ("att-1", None, None, "test_upload_summary.txt", "test_upload_summary.txt", "text/plain", 30, "2026-10-09 14:06:29"),
            ("att-2", None, None, "passwd.txt", "passwd.txt", "text/plain", 7, "2026-10-09 14:06:29"),
            ("att-3", "user-alice", "prof-self", "blood_work.pdf", "blood_work.pdf", "application/pdf", 12000, "2026-10-09 14:07:00"),
            ("att-4", "user-bob", None, "generic_note.txt", "generic_note.txt", "text/plain", 100, "2026-10-09 14:08:00"),
        ])
        raw_conn.commit()

    # 2. Run init_db() which executes _run_schema_migrations()
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)

    # 3. Verify columns were safely added without dropping table
    async with engine.connect() as conn:
        cols_res = await conn.execute(text("PRAGMA table_info(attachments);"))
        cols = {row[1]: row[2] for row in cols_res.fetchall()}
        assert "storage_key" in cols
        assert "sha256_hash" in cols

        # Verify indices exist
        idx_res = await conn.execute(text("PRAGMA index_list(attachments);"))
        idx_names = {row[1] for row in idx_res.fetchall()}
        assert "ix_attachments_storage_key" in idx_names
        assert "ix_attachments_sha256_hash" in idx_names

        # 4. Verify backfill of storage_key values
        rows_res = await conn.execute(text("SELECT id, storage_key, filename FROM attachments ORDER BY id;"))
        rows = {row[0]: (row[1], row[2]) for row in rows_res.fetchall()}

        # att-1: unassigned -> storage_key is filename
        assert rows["att-1"][0] == "test_upload_summary.txt"
        # att-2: unassigned -> storage_key is filename
        assert rows["att-2"][0] == "passwd.txt"
        # att-3: user-alice / prof-self -> user_id/profile_id/filename
        assert rows["att-3"][0] == "user-alice/prof-self/blood_work.pdf"
        # att-4: user-bob / None -> user_id/filename
        assert rows["att-4"][0] == "user-bob/generic_note.txt"

    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_idempotency(tmp_path: Path):
    """Verifies that running init_db / _run_schema_migrations twice produces no errors."""
    db_file = tmp_path / "idempotent_test.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)

    # First run
    await init_db(engine)
    # Second run on already migrated schema
    await init_db(engine)

    async with engine.connect() as conn:
        cols_res = await conn.execute(text("PRAGMA table_info(attachments);"))
        cols = [row[1] for row in cols_res.fetchall()]
        assert cols.count("storage_key") == 1
        assert cols.count("sha256_hash") == 1

    await engine.dispose()
