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

"""Unit and integration tests for Alembic database migrations and schema lifecycle."""

import datetime
import io
from pathlib import Path
import tempfile
import uuid

import alembic.command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

import carefold.db.models
from carefold.db.base import Base
from carefold.db.session import (
    get_alembic_config,
    init_db,
    run_alembic_migrations,
)

EXPECTED_BASELINE_TABLES = {
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
}

EXPECTED_HEAD_TABLES = EXPECTED_BASELINE_TABLES | {
    "alembic_version",
    "audit_events",
    "connections",
    "credentials",
}

EXPECTED_ATTACHMENT_CAS_COLUMNS = {
    "extracted_text",
    "source",
    "source_ref",
    "extraction_status",
    "updated_at",
}


def test_upgrade_head_fresh_sqlite():
    """Tests upgrading a completely fresh SQLite database directly to head."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "head")

        insp = inspect(conn)
        tables = set(insp.get_table_names())
        assert EXPECTED_HEAD_TABLES.issubset(tables)

        att_cols = {c["name"] for c in insp.get_columns("attachments")}
        assert EXPECTED_ATTACHMENT_CAS_COLUMNS.issubset(att_cols)

        audit_cols = {c["name"] for c in insp.get_columns("audit_events")}
        expected_audit_cols = {
            "id", "ts", "profile_id", "actor_user_id", "principal",
            "run_id", "event", "tool", "risk", "decision", "payload_hash",
            "external_ref", "detail_redacted",
        }
        assert expected_audit_cols.issubset(audit_cols)

        conn_cols = {c["name"] for c in insp.get_columns("connections")}
        expected_conn_cols = {
            "id", "user_id", "profile_id", "connector_id", "status",
            "config_json", "created_at", "updated_at",
        }
        assert expected_conn_cols.issubset(conn_cols)

        cred_cols = {c["name"] for c in insp.get_columns("credentials")}
        expected_cred_cols = {
            "id", "connection_id", "profile_id", "token_version",
            "encrypted_blob", "expires_at", "created_at", "updated_at",
        }
        assert expected_cred_cols.issubset(cred_cols)


def test_downgrade_to_baseline_sqlite_batch_rebuild():
    """Tests downgrading from head to 0001_baseline_schema, verifying SQLite batch rebuild."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "head")

        # Insert test data into attachments with CAS fields
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn.execute(
            text("""
                INSERT INTO attachments (
                    id, filename, original_name, content_type, size_bytes,
                    created_at, extracted_text, source, source_ref, extraction_status, updated_at
                ) VALUES (
                    :id, :filename, :original_name, :content_type, :size_bytes,
                    :created_at, :extracted_text, :source, :source_ref, :extraction_status, :updated_at
                )
            """),
            {
                "id": "att-test-1",
                "filename": "doc.pdf",
                "original_name": "doc.pdf",
                "content_type": "application/pdf",
                "size_bytes": 1024,
                "created_at": now,
                "extracted_text": "Extracted text content",
                "source": "upload",
                "source_ref": "upload-ref-1",
                "extraction_status": "completed",
                "updated_at": now,
            },
        )
        conn.commit()

        # Downgrade to baseline
        alembic.command.downgrade(cfg, "0001_baseline_schema")

        insp = inspect(conn)
        tables = set(insp.get_table_names())

        # Autonomous tables should be removed
        assert "audit_events" not in tables
        assert "connections" not in tables
        assert "credentials" not in tables

        # Baseline tables should still exist
        assert EXPECTED_BASELINE_TABLES.issubset(tables)

        # CAS columns should be removed from attachments via batch rebuild
        att_cols = {c["name"] for c in insp.get_columns("attachments")}
        for cas_col in EXPECTED_ATTACHMENT_CAS_COLUMNS:
            assert cas_col not in att_cols

        # Data in remaining columns must be preserved
        row = conn.execute(
            text("SELECT id, filename, content_type, size_bytes FROM attachments WHERE id = 'att-test-1'")
        ).fetchone()
        assert row is not None
        assert row[0] == "att-test-1"
        assert row[1] == "doc.pdf"
        assert row[2] == "application/pdf"
        assert row[3] == 1024


def test_downgrade_to_base_and_upgrade_back_to_head():
    """Tests downgrading all the way to base, then upgrading back to head."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "head")

        alembic.command.downgrade(cfg, "base")
        insp = inspect(conn)
        tables = set(insp.get_table_names())
        # All Carefold application tables should be dropped
        assert tables == {"alembic_version"} or len(tables) == 0

        # Upgrade back to head
        alembic.command.upgrade(cfg, "head")
        insp_after = inspect(conn)
        tables_after = set(insp_after.get_table_names())
        assert EXPECTED_HEAD_TABLES.issubset(tables_after)


def test_legacy_unversioned_database_stamping_and_upgrade():
    """Tests that an existing database without alembic_version is stamped with baseline and upgraded."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        # Create baseline tables first
        alembic.command.upgrade(cfg, "0001_baseline_schema")

        # Simulate legacy database: drop alembic_version table
        conn.execute(text("DROP TABLE alembic_version"))
        conn.commit()

        insp = inspect(conn)
        tables = set(insp.get_table_names())
        assert "users" in tables
        assert "alembic_version" not in tables

        # Insert user and attachment records
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn.execute(
            text("""
                INSERT INTO users (
                    id, email, username, hashed_password, role, status, auth_provider, created_at, updated_at
                ) VALUES (
                    'user-legacy-1', 'legacy@carefold.ai', 'legacyuser', 'hash123', 'steward', 'active', 'local', :now, :now
                )
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO attachments (
                    id, filename, original_name, content_type, size_bytes, created_at
                ) VALUES (
                    'att-legacy-1', 'legacy.txt', 'legacy.txt', 'text/plain', 512, :now
                )
            """),
            {"now": now},
        )
        conn.commit()

        # Run migration runner as session.py:init_db does
        run_alembic_migrations(conn)

        # Inspect resulting state
        insp_migrated = inspect(conn)
        tables_migrated = set(insp_migrated.get_table_names())
        assert EXPECTED_HEAD_TABLES.issubset(tables_migrated)

        # Existing user and attachment data should be preserved
        user_row = conn.execute(text("SELECT email, username FROM users WHERE id = 'user-legacy-1'")).fetchone()
        assert user_row is not None
        assert user_row[0] == "legacy@carefold.ai"
        assert user_row[1] == "legacyuser"

        att_row = conn.execute(text("SELECT filename, size_bytes FROM attachments WHERE id = 'att-legacy-1'")).fetchone()
        assert att_row is not None
        assert att_row[0] == "legacy.txt"
        assert att_row[1] == 512

        # New columns should exist
        att_cols = {c["name"] for c in insp_migrated.get_columns("attachments")}
        assert EXPECTED_ATTACHMENT_CAS_COLUMNS.issubset(att_cols)


@pytest.mark.asyncio
async def test_init_db_idempotency():
    """Tests that init_db can be called multiple times idempotently without error."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)

    # First call: initializes greenfield database to head
    await init_db(engine)

    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        assert EXPECTED_HEAD_TABLES.issubset(tables)

    # Second call: must be completely idempotent
    await init_db(engine)

    async with engine.connect() as conn:
        tables_second = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        assert EXPECTED_HEAD_TABLES.issubset(tables_second)


def test_offline_sql_generation():
    """Tests generating migration SQL in offline mode without an active DB connection."""
    buf = io.StringIO()
    cfg = get_alembic_config()
    cfg.attributes["output_buffer"] = buf
    cfg.set_main_option("sqlalchemy.url", "sqlite:///:memory:")

    # Offline upgrade head generates valid SQL script
    alembic.command.upgrade(cfg, "head", sql=True)
    sql_text = buf.getvalue()
    assert "CREATE TABLE users" in sql_text
    assert "CREATE TABLE attachments" in sql_text
    assert "CREATE TABLE audit_events" in sql_text
