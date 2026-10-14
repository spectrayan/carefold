# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

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

EXPECTED_AUTONOMY_BATCH_3_TABLES = {
    "health_resources",
    "appointments",
    "reminders",
}

EXPECTED_AUTONOMY_BATCH_4_TABLES = {
    "preventive_records",
    "import_batches",
    "school_forms",
}

EXPECTED_AUTONOMY_BATCH_5_TABLES = {
    "consent_grants",
    "sync_runs",
}

EXPECTED_AUTONOMY_BATCH_6_TABLES = {
    "routines",
    "mcp_tool_pins",
    "email_drafts",
    "school_ics_feeds",
    "companion_devices",
}

EXPECTED_HEAD_TABLES = (
    EXPECTED_BASELINE_TABLES
    | {
        "alembic_version",
        "audit_events",
        "connections",
        "credentials",
    }
    | EXPECTED_AUTONOMY_BATCH_1_TABLES
    | EXPECTED_AUTONOMY_BATCH_3_TABLES
    | EXPECTED_AUTONOMY_BATCH_4_TABLES
    | EXPECTED_AUTONOMY_BATCH_5_TABLES
    | EXPECTED_AUTONOMY_BATCH_6_TABLES
)

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
            "config_json", "consecutive_failures", "consented_version",
            "autonomy_level", "created_at", "updated_at",
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

        # Assert 34 tables at head
        assert len(EXPECTED_HEAD_TABLES) == 34

        # Assert head revision is 0010_i18n_and_locale_storage
        curr_ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver == "0010_i18n_and_locale_storage"

        # Assert BCP 47 locale columns exist on users, profiles, notes, attachments, health_resources
        user_cols_map = {c["name"]: c for c in insp.get_columns("users")}
        assert "preferred_locale" in user_cols_map
        prof_cols_map = {c["name"]: c for c in insp.get_columns("profiles")}
        assert "preferred_locale" in prof_cols_map

        # Assert notes.profile_id and chat_threads.profile_id are NOT NULL
        notes_cols = {c["name"]: c for c in insp.get_columns("notes")}
        assert notes_cols["profile_id"]["nullable"] is False
        assert "locale" in notes_cols

        thread_cols = {c["name"]: c for c in insp.get_columns("chat_threads")}
        assert thread_cols["profile_id"]["nullable"] is False

        # Assert Autonomy Batch 3 tables and columns
        hr_cols = {c["name"] for c in insp.get_columns("health_resources")}
        expected_hr_cols = {
            "id", "profile_id", "resource_type", "source_type", "source_ref",
            "source_id", "content_hash", "data", "status", "effective_at",
            "recorded_at", "created_at", "updated_at",
        }
        assert expected_hr_cols.issubset(hr_cols)

        apt_cols = {c["name"] for c in insp.get_columns("appointments")}
        expected_apt_cols = {
            "id", "profile_id", "title", "provider_name", "specialty",
            "location", "clinic_phone", "start_time", "end_time", "timezone",
            "status", "reason", "preparation_notes", "created_at", "updated_at",
        }
        assert expected_apt_cols.issubset(apt_cols)

        rem_cols = {c["name"] for c in insp.get_columns("reminders")}
        expected_rem_cols = {
            "id", "profile_id", "title", "description", "category",
            "rrule", "timezone", "next_due_at", "status", "last_triggered_at",
            "snooze_until", "created_at", "updated_at",
        }
        assert expected_rem_cols.issubset(rem_cols)

        # Assert Autonomy Batch 4 tables and columns
        prev_cols = {c["name"] for c in insp.get_columns("preventive_records")}
        expected_prev_cols = {
            "id", "profile_id", "rule_id", "schedule_source", "status",
            "completed_at", "notes", "created_at", "updated_at",
        }
        assert expected_prev_cols.issubset(prev_cols)

        imp_cols = {c["name"] for c in insp.get_columns("import_batches")}
        expected_imp_cols = {
            "id", "profile_id", "attachment_id", "format", "source_name",
            "status", "summary_json", "staged_records_json",
            "committed_resource_ids_json", "created_at", "committed_at",
        }
        assert expected_imp_cols.issubset(imp_cols)

        sf_cols = {c["name"] for c in insp.get_columns("school_forms")}
        expected_sf_cols = {
            "id", "profile_id", "attachment_id", "title", "school_or_camp_name",
            "form_type", "status", "expires_at", "reminder_id",
            "prefill_draft_json", "notes", "created_at", "updated_at",
        }
        assert expected_sf_cols.issubset(sf_cols)

        # Assert Autonomy Batch 5 tables and columns
        cg_cols = {c["name"] for c in insp.get_columns("consent_grants")}
        expected_cg_cols = {
            "id", "profile_id", "connection_id", "connector_id",
            "granted_by_user_id", "categories_json", "scopes_json",
            "allowed_hosts_json", "purpose", "terms_version",
            "connector_version", "status", "granted_at", "revoked_at",
            "created_at", "updated_at",
        }
        assert expected_cg_cols.issubset(cg_cols)

        sr_cols = {c["name"] for c in insp.get_columns("sync_runs")}
        expected_sr_cols = {
            "id", "connection_id", "profile_id", "connector_id", "stream",
            "status", "records_fetched", "records_upserted", "records_quarantined",
            "error_code", "error_message", "started_at", "completed_at",
            "duration_ms", "created_at",
        }
        assert expected_sr_cols.issubset(sr_cols)

        # Assert Autonomy Batch 6 & 7 tables and columns
        routine_cols = {c["name"] for c in insp.get_columns("routines")}
        assert {"id", "profile_id", "connection_id", "tool_name", "rrule", "expires_at", "status"}.issubset(routine_cols)

        pin_cols = {c["name"] for c in insp.get_columns("mcp_tool_pins")}
        assert {"id", "profile_id", "connection_id", "tool_name", "schema_hash", "status"}.issubset(pin_cols)

        draft_cols = {c["name"] for c in insp.get_columns("email_drafts")}
        assert {"id", "profile_id", "subject", "body", "category", "status", "sent_at", "external_message_id"}.issubset(draft_cols)

        ics_cols = {c["name"] for c in insp.get_columns("school_ics_feeds")}
        assert {"id", "profile_id", "label", "feed_url", "status", "events_synced"}.issubset(ics_cols)

        comp_cols = {c["name"] for c in insp.get_columns("companion_devices")}
        assert {"id", "user_id", "profile_id", "device_name", "platform", "cert_fingerprint_sha256", "status"}.issubset(comp_cols)

        access_cols = {c["name"] for c in insp.get_columns("profile_access")}
        assert "allowed_sections_json" in access_cols

        audit_cols = {c["name"] for c in insp.get_columns("audit_events")}
        assert {"prev_hash", "entry_hash"}.issubset(audit_cols)

        # Assert notes.linked_appointment_id column exists and is nullable
        assert "linked_appointment_id" in notes_cols
        assert notes_cols["linked_appointment_id"]["nullable"] is True


def test_downgrade_to_0008_routines_mcp_and_drafts():
    """Tests downgrading from 0009_companion_and_handover to 0008_routines_mcp_and_drafts and re-upgrading."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "head")

        curr_ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver == "0010_i18n_and_locale_storage"

        alembic.command.downgrade(cfg, "0008_routines_mcp_and_drafts")
        curr_ver_down = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver_down == "0008_routines_mcp_and_drafts"

        insp = inspect(conn)
        audit_cols_down = {c["name"] for c in insp.get_columns("audit_events")}
        assert "prev_hash" not in audit_cols_down
        assert "entry_hash" not in audit_cols_down

        draft_cols_down = {c["name"] for c in insp.get_columns("email_drafts")}
        assert "sent_at" not in draft_cols_down
        assert "external_message_id" not in draft_cols_down

        alembic.command.upgrade(cfg, "head")
        curr_ver_up = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver_up == "0010_i18n_and_locale_storage"


def test_downgrade_to_0007_connectors_and_consent():
    """Tests downgrading from head to 0007_connectors_and_consent and re-upgrading."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "head")

        curr_ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver == "0010_i18n_and_locale_storage"

        alembic.command.downgrade(cfg, "0007_connectors_and_consent")
        curr_ver_down = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver_down == "0007_connectors_and_consent"

        insp = inspect(conn)
        tables_down = set(insp.get_table_names())
        for tbl in EXPECTED_AUTONOMY_BATCH_6_TABLES:
            assert tbl not in tables_down
        conn_cols_down = {c["name"] for c in insp.get_columns("connections")}
        assert "autonomy_level" not in conn_cols_down
        access_cols_down = {c["name"] for c in insp.get_columns("profile_access")}
        assert "allowed_sections_json" not in access_cols_down
        assert EXPECTED_AUTONOMY_BATCH_5_TABLES.issubset(tables_down)

        alembic.command.upgrade(cfg, "head")
        curr_ver_up = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver_up == "0010_i18n_and_locale_storage"
        insp_up = inspect(conn)
        tables_up = set(insp_up.get_table_names())
        assert EXPECTED_AUTONOMY_BATCH_6_TABLES.issubset(tables_up)


def test_downgrade_to_0006_preventive_and_school_forms():
    """Tests downgrading from head to 0006_preventive_and_school_forms and re-upgrading."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "head")

        curr_ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver == "0010_i18n_and_locale_storage"

        alembic.command.downgrade(cfg, "0006_preventive_and_school_forms")
        curr_ver_down = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver_down == "0006_preventive_and_school_forms"

        insp = inspect(conn)
        tables_down = set(insp.get_table_names())
        assert "consent_grants" not in tables_down
        assert "sync_runs" not in tables_down
        conn_cols_down = {c["name"] for c in insp.get_columns("connections")}
        assert "consecutive_failures" not in conn_cols_down
        assert "consented_version" not in conn_cols_down
        assert EXPECTED_AUTONOMY_BATCH_4_TABLES.issubset(tables_down)

        alembic.command.upgrade(cfg, "head")
        curr_ver_up = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver_up == "0010_i18n_and_locale_storage"
        insp_up = inspect(conn)
        tables_up = set(insp_up.get_table_names())
        assert EXPECTED_AUTONOMY_BATCH_5_TABLES.issubset(tables_up)


def test_downgrade_to_0005_clinical_domain_records():
    """Tests downgrading from head to 0005_clinical_domain_records and re-upgrading."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "head")

        curr_ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver == "0010_i18n_and_locale_storage"

        alembic.command.downgrade(cfg, "0005_clinical_domain_records")
        curr_ver_down = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver_down == "0005_clinical_domain_records"

        insp = inspect(conn)
        tables_down = set(insp.get_table_names())
        assert "preventive_records" not in tables_down
        assert "import_batches" not in tables_down
        assert "school_forms" not in tables_down
        assert "consent_grants" not in tables_down
        assert "sync_runs" not in tables_down
        assert EXPECTED_AUTONOMY_BATCH_3_TABLES.issubset(tables_down)

        alembic.command.upgrade(cfg, "head")
        curr_ver_up = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver_up == "0010_i18n_and_locale_storage"
        insp_up = inspect(conn)
        tables_up = set(insp_up.get_table_names())
        assert EXPECTED_AUTONOMY_BATCH_4_TABLES.issubset(tables_up)
        assert EXPECTED_AUTONOMY_BATCH_5_TABLES.issubset(tables_up)
        assert EXPECTED_AUTONOMY_BATCH_6_TABLES.issubset(tables_up)


def test_downgrade_to_0004_policy_gate_and_vault():
    """Tests downgrading from 0005_clinical_domain_records to 0004_policy_gate_and_vault and re-upgrading.

    Asserts:
    1. At 0005: Batch 3 tables exist, notes.linked_appointment_id exists.
    2. Seed profile, appointment, note linked to appointment, health resource, reminder.
    3. Downgrade to 0004: health_resources, appointments, reminders tables are dropped;
       notes.linked_appointment_id column is dropped; note content is preserved.
    4. alembic_version is 0004_policy_gate_and_vault.
    5. Re-upgrade to head (0006): Batch 3 and 4 tables and linked_appointment_id re-created,
       existing note data remains intact.
    """
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "0005_clinical_domain_records")

        curr_ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver == "0005_clinical_domain_records"

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Seed profile
        conn.execute(
            text("""
                INSERT INTO profiles (id, name, relationship, role, avatar_color, is_primary, created_at, updated_at)
                VALUES ('prof-b3-test', 'Bob', 'self', 'self', '1', 1, :now, :now)
            """),
            {"now": now},
        )
        # Seed appointment
        conn.execute(
            text("""
                INSERT INTO appointments (id, profile_id, title, start_time, end_time, timezone, status, created_at, updated_at)
                VALUES ('apt-b3-test', 'prof-b3-test', 'Cardiology Checkup', :now, :now, 'UTC', 'scheduled', :now, :now)
            """),
            {"now": now},
        )
        # Seed note linked to appointment
        conn.execute(
            text("""
                INSERT INTO notes (id, type, profile_id, slug, title, content, tags_json, linked_appointment_id, created_at, updated_at)
                VALUES ('note-b3-test', 'visit', 'prof-b3-test', 'cardio-prep', 'Cardio Prep', 'Review BP meds', '[]', 'apt-b3-test', :now, :now)
            """),
            {"now": now},
        )
        # Seed health resource
        conn.execute(
            text("""
                INSERT INTO health_resources (id, profile_id, resource_type, source_type, data, status, effective_at, recorded_at, created_at, updated_at)
                VALUES ('hr-b3-test', 'prof-b3-test', 'observation', 'manual', '{"resourceType": "Observation"}', 'active', :now, :now, :now, :now)
            """),
            {"now": now},
        )
        # Seed reminder
        conn.execute(
            text("""
                INSERT INTO reminders (id, profile_id, title, category, timezone, next_due_at, status, created_at, updated_at)
                VALUES ('rem-b3-test', 'prof-b3-test', 'Take BP meds', 'medication', 'UTC', :now, 'pending', :now, :now)
            """),
            {"now": now},
        )
        conn.commit()

        # Downgrade to 0004_policy_gate_and_vault
        alembic.command.downgrade(cfg, "0004_policy_gate_and_vault")

        curr_ver_down = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver_down == "0004_policy_gate_and_vault"

        insp = inspect(conn)
        tables_down = set(insp.get_table_names())
        assert "health_resources" not in tables_down
        assert "appointments" not in tables_down
        assert "reminders" not in tables_down

        notes_cols = {c["name"] for c in insp.get_columns("notes")}
        assert "linked_appointment_id" not in notes_cols

        # Verify note survived downgrade
        note_row = conn.execute(text("SELECT id, title, content, profile_id FROM notes WHERE id = 'note-b3-test'")).fetchone()
        assert note_row is not None
        assert note_row[1] == "Cardio Prep"
        assert note_row[2] == "Review BP meds"
        assert note_row[3] == "prof-b3-test"

        # Re-upgrade to head (0009_companion_and_handover)
        alembic.command.upgrade(cfg, "head")
        curr_ver_up = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver_up == "0010_i18n_and_locale_storage"

        insp_up = inspect(conn)
        tables_up = set(insp_up.get_table_names())
        assert EXPECTED_AUTONOMY_BATCH_3_TABLES.issubset(tables_up)
        assert EXPECTED_AUTONOMY_BATCH_4_TABLES.issubset(tables_up)
        assert EXPECTED_AUTONOMY_BATCH_5_TABLES.issubset(tables_up)
        assert EXPECTED_AUTONOMY_BATCH_6_TABLES.issubset(tables_up)

        notes_cols_up = {c["name"]: c for c in insp_up.get_columns("notes")}
        assert "linked_appointment_id" in notes_cols_up
        assert notes_cols_up["linked_appointment_id"]["nullable"] is True

        # Note data still preserved with linked_appointment_id as NULL
        note_row_up = conn.execute(text("SELECT id, title, linked_appointment_id FROM notes WHERE id = 'note-b3-test'")).fetchone()
        assert note_row_up is not None
        assert note_row_up[1] == "Cardio Prep"
        assert note_row_up[2] is None


def test_downgrade_to_0003_household_profiles_and_audit():
    """Tests downgrading from 0004_policy_gate_and_vault to 0003_household_profiles_and_audit and re-upgrading.

    Asserts:
    1. At 0004: notes.profile_id and chat_threads.profile_id are NOT NULL.
    2. Downgrade to 0003: profile_id reverts to nullable=True on both tables.
    3. Existing note and chat_thread data survive the batch alter rebuild.
    4. Re-upgrade to head: profile_id is NOT NULL and version is 0004_policy_gate_and_vault.
    """
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "0004_policy_gate_and_vault")

        curr_ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver == "0004_policy_gate_and_vault"

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Seed profile, note, and chat_thread
        conn.execute(
            text("""
                INSERT INTO profiles (id, name, relationship, role, avatar_color, is_primary, created_at, updated_at)
                VALUES ('prof-msg_one-test', 'Alice', 'self', 'self', '1', 1, :now, :now)
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO notes (id, type, profile_id, slug, title, content, tags_json, created_at, updated_at)
                VALUES ('note-msg_one-test', 'scratchpad', 'prof-msg_one-test', 'test-note', 'Test Note', 'Note content', '[]', :now, :now)
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO chat_threads (id, profile_id, agent_id, title, created_at, updated_at)
                VALUES ('thread-msg_one-test', 'prof-msg_one-test', 'visit-steward', 'Consultation', :now, :now)
            """),
            {"now": now},
        )
        conn.commit()

        # Downgrade to 0003_household_profiles_and_audit
        alembic.command.downgrade(cfg, "0003_household_profiles_and_audit")

        curr_ver_down = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver_down == "0003_household_profiles_and_audit"

        insp = inspect(conn)
        notes_cols = {c["name"]: c for c in insp.get_columns("notes")}
        assert notes_cols["profile_id"]["nullable"] is True

        thread_cols = {c["name"]: c for c in insp.get_columns("chat_threads")}
        assert thread_cols["profile_id"]["nullable"] is True

        # Data must be preserved
        n_row = conn.execute(text("SELECT id, profile_id, title FROM notes WHERE id = 'note-msg_one-test'")).fetchone()
        assert n_row is not None
        assert n_row[1] == "prof-msg_one-test"

        t_row = conn.execute(text("SELECT id, profile_id, title FROM chat_threads WHERE id = 'thread-msg_one-test'")).fetchone()
        assert t_row is not None
        assert t_row[1] == "prof-msg_one-test"

        # Re-upgrade to 0004
        alembic.command.upgrade(cfg, "0004_policy_gate_and_vault")

        curr_ver_up = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert curr_ver_up == "0004_policy_gate_and_vault"

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
        assert "health_resources" not in tables
        assert "appointments" not in tables
        assert "reminders" not in tables
        assert "preventive_records" not in tables
        assert "import_batches" not in tables
        assert "school_forms" not in tables

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
    """Tests downgrading from 0003_household_profiles_and_audit to 0002_autonomy_foundations.

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
                VALUES ('prof-msg_two-test', 'Alice', 'self', 'self', '1', 1, :now, :now)
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO connections (id, user_id, profile_id, connector_id, status, config_json, created_at, updated_at)
                VALUES ('conn-msg_two-test', 'user-1', 'prof-msg_two-test', 'epic-fhir', 'active', '{}', :now, :now)
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO credentials (
                    id, connection_id, profile_id, token_version, dek_version,
                    encrypted_blob, aad_binding, created_at, updated_at
                ) VALUES (
                    'cred-msg_two-test', 'conn-msg_two-test', 'prof-msg_two-test', 1, 2,
                    'encrypted_blob_payload_xyz', 'prof-msg_two-test|conn-msg_two-test|2', :now, :now
                )
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO profile_keys (id, profile_id, encrypted_dek, dek_version, created_at, updated_at)
                VALUES ('pk-msg_two-test', 'prof-msg_two-test', 'enc_dek_hex_123', 1, :now, :now)
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO approvals (
                    id, profile_id, run_id, tool_name, args_redacted, payload_hash,
                    risk_tier, status, expires_at, created_at
                ) VALUES (
                    'appr-msg_two-test', 'prof-msg_two-test', 'run-1', 'test_tool', '{}', 'hash123',
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
                    'job-msg_two-test', 'prof-msg_two-test', 'reminder', '{}', :now, 'pending', :now, :now
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
            text("SELECT id, connection_id, profile_id, encrypted_blob FROM credentials WHERE id = 'cred-msg_two-test'")
        ).fetchone()
        assert row is not None
        assert row[0] == "cred-msg_two-test"
        assert row[1] == "conn-msg_two-test"
        assert row[2] == "prof-msg_two-test"
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
