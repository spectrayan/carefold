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

EXPECTED_AUTONOMY_BATCH_1_TABLES = {
    "profile_keys",
    "approvals",
    "jobs",
}

EXPECTED_HEAD_TABLES = EXPECTED_BASELINE_TABLES | {
    "alembic_version",
    "audit_events",
    "connections",
    "credentials",
} | EXPECTED_AUTONOMY_BATCH_1_TABLES

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
            "id", "connection_id", "profile_id", "token_version", "dek_version",
            "encrypted_blob", "expires_at", "created_at", "updated_at",
        }
        assert expected_cred_cols.issubset(cred_cols)

        pk_cols = {c["name"] for c in insp.get_columns("profile_keys")}
        expected_pk_cols = {"id", "profile_id", "encrypted_dek", "dek_version", "created_at", "updated_at"}
        assert expected_pk_cols.issubset(pk_cols)

        appr_cols = {c["name"] for c in insp.get_columns("approvals")}
        expected_appr_cols = {
            "id", "profile_id", "run_id", "thread_id", "tool_name",
            "args_redacted", "payload_hash", "destination_hosts",
            "risk_tier", "status", "expires_at", "created_at",
            "decided_at", "decided_by",
        }
        assert expected_appr_cols.issubset(appr_cols)

        job_cols = {c["name"] for c in insp.get_columns("jobs")}
        expected_job_cols = {
            "id", "profile_id", "kind", "routine_id", "connection_id",
            "payload", "timezone", "rrule", "next_run_at", "lease_owner",
            "lease_until", "attempts", "idempotency_key", "status",
            "created_at", "updated_at",
        }
        assert expected_job_cols.issubset(job_cols)

        # Assert head revision is 0004_autonomy_batch_2
        curr_ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver == "0004_autonomy_batch_2"

        # Assert notes.profile_id and chat_threads.profile_id are NOT NULL
        notes_cols = {c["name"]: c for c in insp.get_columns("notes")}
        assert notes_cols["profile_id"]["nullable"] is False

        thread_cols = {c["name"]: c for c in insp.get_columns("chat_threads")}
        assert thread_cols["profile_id"]["nullable"] is False


def test_downgrade_to_0003_autonomy_batch_1():
    """Tests downgrading from 0004_autonomy_batch_2 to 0003_autonomy_batch_1 and re-upgrading.

    Asserts:
    1. At 0004: notes.profile_id and chat_threads.profile_id are NOT NULL.
    2. Downgrade to 0003: profile_id reverts to nullable=True on both tables.
    3. Existing note and chat_thread data survive the batch alter rebuild.
    4. Re-upgrade to head: profile_id is NOT NULL and version is 0004_autonomy_batch_2.
    """
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "head")

        curr_ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver == "0004_autonomy_batch_2"

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Seed profile, note, and chat_thread
        conn.execute(
            text("""
                INSERT INTO profiles (id, name, relationship, role, avatar_color, is_primary, created_at, updated_at)
                VALUES ('prof-m1-test', 'Alice', 'self', 'self', '1', 1, :now, :now)
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO notes (id, type, profile_id, slug, title, content, tags_json, created_at, updated_at)
                VALUES ('note-m1-test', 'scratchpad', 'prof-m1-test', 'test-note', 'Test Note', 'Note content', '[]', :now, :now)
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO chat_threads (id, profile_id, agent_id, title, created_at, updated_at)
                VALUES ('thread-m1-test', 'prof-m1-test', 'visit-steward', 'Consultation', :now, :now)
            """),
            {"now": now},
        )
        conn.commit()

        # Downgrade to 0003_autonomy_batch_1
        alembic.command.downgrade(cfg, "0003_autonomy_batch_1")

        curr_ver_down = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver_down == "0003_autonomy_batch_1"

        insp = inspect(conn)
        notes_cols = {c["name"]: c for c in insp.get_columns("notes")}
        assert notes_cols["profile_id"]["nullable"] is True

        thread_cols = {c["name"]: c for c in insp.get_columns("chat_threads")}
        assert thread_cols["profile_id"]["nullable"] is True

        # Data must be preserved
        n_row = conn.execute(text("SELECT id, profile_id, title FROM notes WHERE id = 'note-m1-test'")).fetchone()
        assert n_row is not None
        assert n_row[1] == "prof-m1-test"

        t_row = conn.execute(text("SELECT id, profile_id, title FROM chat_threads WHERE id = 'thread-m1-test'")).fetchone()
        assert t_row is not None
        assert t_row[1] == "prof-m1-test"

        # Re-upgrade to head
        alembic.command.upgrade(cfg, "head")

        curr_ver_up = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver_up == "0004_autonomy_batch_2"

        insp_head = inspect(conn)
        notes_cols_head = {c["name"]: c for c in insp_head.get_columns("notes")}
        assert notes_cols_head["profile_id"]["nullable"] is False

        thread_cols_head = {c["name"]: c for c in insp_head.get_columns("chat_threads")}
        assert thread_cols_head["profile_id"]["nullable"] is False


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
        assert "profile_keys" not in tables
        assert "approvals" not in tables
        assert "jobs" not in tables

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


def test_downgrade_to_0002_autonomy_foundations():
    """Tests downgrading from 0003_autonomy_batch_1 to 0002_autonomy_foundations.

    Asserts:
    1. Table drops: jobs, approvals, profile_keys are completely dropped.
    2. Batch column drop: dek_version is stripped from credentials.
    3. Data preservation: existing credential columns and data survive the batch alter.
    4. Re-upgrade: upgrade back to head succeeds without errors.
    """
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "head")

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Seed profile, connection, and credential with dek_version = 2
        conn.execute(
            text("""
                INSERT INTO profiles (id, name, relationship, role, avatar_color, is_primary, created_at, updated_at)
                VALUES ('prof-m2-test', 'Alice', 'self', 'self', '1', 1, :now, :now)
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO connections (id, user_id, profile_id, connector_id, status, config_json, created_at, updated_at)
                VALUES ('conn-m2-test', 'user-1', 'prof-m2-test', 'epic-fhir', 'active', '{}', :now, :now)
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO credentials (
                    id, connection_id, profile_id, token_version, dek_version,
                    encrypted_blob, aad_binding, created_at, updated_at
                ) VALUES (
                    'cred-m2-test', 'conn-m2-test', 'prof-m2-test', 1, 2,
                    'encrypted_blob_payload_xyz', 'prof-m2-test|conn-m2-test|2', :now, :now
                )
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO profile_keys (id, profile_id, encrypted_dek, dek_version, created_at, updated_at)
                VALUES ('pk-m2-test', 'prof-m2-test', 'enc_dek_hex_123', 1, :now, :now)
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO approvals (
                    id, profile_id, run_id, tool_name, args_redacted, payload_hash,
                    risk_tier, status, expires_at, created_at
                ) VALUES (
                    'appr-m2-test', 'prof-m2-test', 'run-1', 'test_tool', '{}', 'hash123',
                    'write_external', 'pending', :now, :now
                )
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO jobs (
                    id, profile_id, kind, payload, next_run_at, status, created_at, updated_at
                ) VALUES (
                    'job-m2-test', 'prof-m2-test', 'reminder', '{}', :now, 'pending', :now, :now
                )
            """),
            {"now": now},
        )
        conn.commit()

        # Execute downgrade to 0002_autonomy_foundations
        alembic.command.downgrade(cfg, "0002_autonomy_foundations")

        insp = inspect(conn)
        tables = set(insp.get_table_names())

        # Assert 0003 tables are removed
        assert "profile_keys" not in tables
        assert "approvals" not in tables
        assert "jobs" not in tables

        # Assert 0002 tables remain intact
        assert {"credentials", "connections", "audit_events"}.issubset(tables)

        # Assert dek_version column was dropped from credentials
        cred_cols = {c["name"] for c in insp.get_columns("credentials")}
        assert "dek_version" not in cred_cols

        # Assert credential data was preserved through the SQLite batch table rebuild
        row = conn.execute(
            text("SELECT id, connection_id, profile_id, encrypted_blob FROM credentials WHERE id = 'cred-m2-test'")
        ).fetchone()
        assert row is not None
        assert row[0] == "cred-m2-test"
        assert row[1] == "conn-m2-test"
        assert row[2] == "prof-m2-test"
        assert row[3] == "encrypted_blob_payload_xyz"

        # Re-upgrade back to head
        alembic.command.upgrade(cfg, "head")
        insp_head = inspect(conn)
        tables_head = set(insp_head.get_table_names())
        assert EXPECTED_AUTONOMY_BATCH_1_TABLES.issubset(tables_head)

        cred_cols_head = {c["name"] for c in insp_head.get_columns("credentials")}
        assert "dek_version" in cred_cols_head


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
