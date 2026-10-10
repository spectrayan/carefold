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

"""Unit and integration tests for Carefold database schema migrations and table evolution."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from carefold.db.base import Base
from carefold.db.models import Note, Profile, User, ViewerInvite
from carefold.db.session import create_db_engine, get_session_factory, init_db


@pytest.mark.asyncio
async def test_fresh_database_creates_all_tables_and_columns(tmp_path: Path):
    """Verifies that init_db() on a fresh database creates 'notes', 'viewer_invites', and new profile columns."""
    db_file = tmp_path / "fresh_carefold.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)

    try:
        await init_db(engine)

        async with engine.connect() as conn:
            # 1. Inspect table names
            tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
            assert "notes" in tables
            assert "note" not in tables
            assert "viewer_invites" in tables
            assert "profiles" in tables
            assert "users" in tables
            assert "profile_access" in tables

            # 2. Inspect profiles columns
            profile_cols = await conn.run_sync(
                lambda sc: [c["name"] for c in inspect(sc).get_columns("profiles")]
            )
            assert "short_name" in profile_cols
            assert "avatar_url" in profile_cols

            # 3. Inspect viewer_invites indexes
            indexes = await conn.run_sync(
                lambda sc: [idx["name"] for idx in inspect(sc).get_indexes("viewer_invites")]
            )
            assert "ix_viewer_invites_invite_code" in indexes
            assert "ix_viewer_invites_profile_id" in indexes
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_database_migration_renames_note_table_and_preserves_data(tmp_path: Path):
    """Verifies that an older database with table 'note' and without profile columns is migrated cleanly."""
    db_file = tmp_path / "legacy_carefold.db"

    # 1. Construct raw SQLite legacy database (pre-M2 schema)
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        # Legacy profiles without short_name or avatar_url
        conn.execute("""
            CREATE TABLE profiles (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36),
                name VARCHAR(255) NOT NULL,
                relationship VARCHAR(64) NOT NULL DEFAULT 'self',
                role VARCHAR(32) NOT NULL DEFAULT 'self',
                date_of_birth VARCHAR(10),
                avatar_color VARCHAR(32) NOT NULL DEFAULT '1',
                is_primary BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
        """)
        # Legacy note table (singular)
        conn.execute("""
            CREATE TABLE note (
                id VARCHAR(36) PRIMARY KEY,
                type VARCHAR(32) NOT NULL DEFAULT 'scratchpad',
                user_id VARCHAR(36),
                profile_id VARCHAR(36),
                slug VARCHAR(128) NOT NULL,
                title VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
        """)
        # Seed legacy rows
        conn.execute("""
            INSERT INTO profiles (id, name, relationship, role, created_at, updated_at)
            VALUES ('prof-001', 'Legacy Leo', 'child', 'self', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """)
        conn.execute("""
            INSERT INTO note (id, slug, title, content, tags_json, created_at, updated_at)
            VALUES ('note-001', 'legacy-slug', 'Legacy Title', 'Legacy Content Body', '["tag1"]', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """)
        conn.commit()

    # 2. Run init_db() on legacy database
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)

    try:
        await init_db(engine)

        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
            # 'note' renamed to 'notes'
            assert "notes" in tables
            assert "note" not in tables
            assert "viewer_invites" in tables

            # Verify existing note data preserved
            res = await conn.execute(text("SELECT id, slug, title, content, tags_json FROM notes;"))
            row = res.fetchone()
            assert row is not None
            assert row[0] == "note-001"
            assert row[1] == "legacy-slug"
            assert row[2] == "Legacy Title"
            assert row[3] == "Legacy Content Body"
            assert row[4] == '["tag1"]'

            # Verify profiles columns added without losing data
            profile_cols = await conn.run_sync(
                lambda sc: [c["name"] for c in inspect(sc).get_columns("profiles")]
            )
            assert "short_name" in profile_cols
            assert "avatar_url" in profile_cols

            prof_res = await conn.execute(text("SELECT id, name, short_name, avatar_url FROM profiles;"))
            prof_row = prof_res.fetchone()
            assert prof_row is not None
            assert prof_row[0] == "prof-001"
            assert prof_row[1] == "Legacy Leo"
            assert prof_row[2] is None  # Defaults to NULL
            assert prof_row[3] is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_schema_migration_idempotency(tmp_path: Path):
    """Verifies that running init_db() multiple times produces no errors and preserves schemas."""
    db_file = tmp_path / "idempotent_test.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)

    try:
        await init_db(engine)
        # Second run on same DB
        await init_db(engine)
        # Third run on same DB
        await init_db(engine)

        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
            assert "notes" in tables
            assert "viewer_invites" in tables
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_schema_migration_collision_note_and_empty_notes(tmp_path: Path):
    """Verifies that if both 'note' (with rows) and 'notes' (empty) exist, data is safely migrated."""
    db_file = tmp_path / "collision_carefold.db"

    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("""
            CREATE TABLE note (
                id VARCHAR(36) PRIMARY KEY,
                type VARCHAR(32) NOT NULL DEFAULT 'scratchpad',
                slug VARCHAR(128) NOT NULL,
                title VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE notes (
                id VARCHAR(36) PRIMARY KEY,
                type VARCHAR(32) NOT NULL DEFAULT 'scratchpad',
                slug VARCHAR(128) NOT NULL,
                title VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
        """)
        conn.execute("""
            INSERT INTO note (id, slug, title, content, created_at, updated_at)
            VALUES ('n-collision', 'collision-slug', 'Collision Title', 'Content', '2026-01-01', '2026-01-01');
        """)
        conn.commit()

    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)

    try:
        await init_db(engine)

        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
            assert "notes" in tables
            assert "note" not in tables

            res = await conn.execute(text("SELECT id, slug FROM notes;"))
            row = res.fetchone()
            assert row is not None
            assert row[0] == "n-collision"
            assert row[1] == "collision-slug"
    finally:
        await engine.dispose()
