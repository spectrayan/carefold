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

"""Unit and integration tests for Option A branched health pack migrations."""

import datetime
from pathlib import Path
import tempfile
import uuid

import alembic.command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.pool import StaticPool

from carefold.db.session import (
    get_alembic_config,
    get_pack_alembic_config,
    resolve_health_migrations_dir,
    run_alembic_migrations,
    run_all_migrations,
    run_pack_migrations,
)

HEALTH_TABLES = [
    "health_resources",
    "health_resource_versions",
    "health_resource_codings",
    "health_resource_references",
    "appointments",
    "reminders",
    "preventive_records",
    "import_batches",
    "school_forms",
    "school_ics_feeds",
]


def test_health_pack_migration_greenfield_sqlite():
    """Starts with an empty SQLite database, runs run_all_migrations, asserts both version tables."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        run_all_migrations(conn, enabled_packs=["health"])
        conn.commit()

        # Check alembic_version
        core_revs = [r[0] for r in conn.exec_driver_sql("SELECT version_num FROM alembic_version;").fetchall()]
        assert "0014_neutralize_profile_columns" in core_revs

        # Check alembic_version_health
        health_revs = [r[0] for r in conn.exec_driver_sql("SELECT version_num FROM alembic_version_health;").fetchall()]
        assert "health_0002_fhir_ehr_repository" in health_revs

        # Check all health tables exist and have scope column
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        for tbl in HEALTH_TABLES:
            assert tbl in tables, f"Expected table {tbl} to exist in DB"
            cols = {c["name"]: c for c in inspector.get_columns(tbl)}
            assert "scope" in cols, f"Expected column 'scope' in table {tbl}"


def test_health_pack_migration_upgrade_existing_db():
    """Sets up an existing DB at 0013_turn_tasks with pre-inserted health rows, then runs pack migrations."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        # Run core migrations up to 0013_turn_tasks
        run_alembic_migrations(conn)
        conn.commit()

        inspector = inspect(conn)
        assert "alembic_version_health" not in inspector.get_table_names()

        # Insert a user and profile first
        user_id = str(uuid.uuid4())
        profile_id = str(uuid.uuid4())
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn.exec_driver_sql(
            "INSERT INTO users (id, email, username, hashed_password, created_at, updated_at) VALUES (:id, 'u@test.local', 'tester', 'hash', :now, :now);",
            {"id": user_id, "now": now_iso},
        )
        conn.exec_driver_sql(
            "INSERT INTO profiles (id, user_id, name, relationship, role, avatar_color, is_primary, created_at, updated_at) VALUES (:id, :uid, 'Self', 'self', 'self', 'blue', 1, :now, :now);",
            {"id": profile_id, "uid": user_id, "now": now_iso},
        )

        # Pre-insert records into health_resources, appointments, reminders
        hr_id = str(uuid.uuid4())
        conn.exec_driver_sql(
            """INSERT INTO health_resources (
                id, profile_id, resource_type, source_type, data, status, effective_at, recorded_at, created_at, updated_at, scope
            ) VALUES (
                :id, :pid, 'Condition', 'manual', '{"code": "diabetes"}', 'active', :now, :now, :now, :now, 'health'
            );""",
            {"id": hr_id, "pid": profile_id, "now": now_iso},
        )

        apt_id = str(uuid.uuid4())
        conn.exec_driver_sql(
            """INSERT INTO appointments (
                id, profile_id, title, start_time, end_time, created_at, updated_at, scope
            ) VALUES (
                :id, :pid, 'Cardiology Follow-up', :now, :now, :now, :now, 'health'
            );""",
            {"id": apt_id, "pid": profile_id, "now": now_iso},
        )

        rem_id = str(uuid.uuid4())
        conn.exec_driver_sql(
            """INSERT INTO reminders (
                id, profile_id, title, next_due_at, created_at, updated_at, scope
            ) VALUES (
                :id, :pid, 'Check BP', :now, :now, :now, 'health'
            );""",
            {"id": rem_id, "pid": profile_id, "now": now_iso},
        )
        conn.commit()

        # Now run all migrations including health pack
        run_all_migrations(conn, enabled_packs=["health"])
        conn.commit()

        # Check alembic_version_health created
        inspector = inspect(conn)
        assert "alembic_version_health" in inspector.get_table_names()
        health_revs = [r[0] for r in conn.exec_driver_sql("SELECT version_num FROM alembic_version_health;").fetchall()]
        assert "health_0002_fhir_ehr_repository" in health_revs

        # Verify pre-existing data is 100% intact
        hr_row = conn.exec_driver_sql("SELECT data FROM health_resources WHERE id = :id;", {"id": hr_id}).fetchone()
        assert hr_row is not None
        assert "diabetes" in hr_row[0]

        apt_row = conn.exec_driver_sql("SELECT title FROM appointments WHERE id = :id;", {"id": apt_id}).fetchone()
        assert apt_row is not None
        assert apt_row[0] == "Cardiology Follow-up"

        rem_row = conn.exec_driver_sql("SELECT title FROM reminders WHERE id = :id;", {"id": rem_id}).fetchone()
        assert rem_row is not None
        assert rem_row[0] == "Check BP"


def test_health_pack_migration_missing_core_precondition():
    """Creating a database without 0013_turn_tasks raises RuntimeError when running pack migrations."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    mig_dir = resolve_health_migrations_dir()

    with engine.connect() as conn:
        # Case A: empty database
        with pytest.raises(RuntimeError, match="alembic_version"):
            run_pack_migrations(conn, migrations_dir=mig_dir, depends_on_core="0013_turn_tasks")

        # Case B: database only at 0004
        cfg_core = get_alembic_config(conn)
        alembic.command.upgrade(cfg_core, "0004_policy_gate_and_vault")
        conn.commit()

        with pytest.raises(RuntimeError, match="0013_turn_tasks"):
            run_pack_migrations(conn, migrations_dir=mig_dir, depends_on_core="0013_turn_tasks")


def test_dual_version_isolation_and_rollback():
    """Verifies that downgrading core does not touch alembic_version_health."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        run_all_migrations(conn, enabled_packs=["health"])
        conn.commit()

        assert [r[0] for r in conn.exec_driver_sql("SELECT version_num FROM alembic_version;").fetchall()] == ["0014_neutralize_profile_columns"]
        assert [r[0] for r in conn.exec_driver_sql("SELECT version_num FROM alembic_version_health;").fetchall()] == ["health_0002_fhir_ehr_repository"]

        # Downgrade core to 0010_i18n_and_locale_storage
        cfg_core = get_alembic_config(conn)
        alembic.command.downgrade(cfg_core, "0010_i18n_and_locale_storage")
        conn.commit()

        # Core is downgraded
        assert [r[0] for r in conn.exec_driver_sql("SELECT version_num FROM alembic_version;").fetchall()] == ["0010_i18n_and_locale_storage"]
        # Health version remains untouched
        assert [r[0] for r in conn.exec_driver_sql("SELECT version_num FROM alembic_version_health;").fetchall()] == ["health_0002_fhir_ehr_repository"]

        # Re-upgrade core to head
        alembic.command.upgrade(cfg_core, "head")
        conn.commit()

        assert [r[0] for r in conn.exec_driver_sql("SELECT version_num FROM alembic_version;").fetchall()] == ["0014_neutralize_profile_columns"]
        assert [r[0] for r in conn.exec_driver_sql("SELECT version_num FROM alembic_version_health;").fetchall()] == ["health_0002_fhir_ehr_repository"]

        # Also test downgrading health_0002_fhir_ehr_repository -> health_0001_baseline and re-upgrading
        mig_dir = resolve_health_migrations_dir()
        cfg_health = get_pack_alembic_config(mig_dir, connection=conn, version_table="alembic_version_health")
        alembic.command.downgrade(cfg_health, "health_0001_baseline")
        conn.commit()
        assert [r[0] for r in conn.exec_driver_sql("SELECT version_num FROM alembic_version_health;").fetchall()] == ["health_0001_baseline"]
        tables_after_downgrade = set(inspect(conn).get_table_names())
        assert "health_resource_versions" not in tables_after_downgrade
        assert "health_resource_codings" not in tables_after_downgrade
        assert "health_resource_references" not in tables_after_downgrade

        alembic.command.upgrade(cfg_health, "head")
        conn.commit()
        assert [r[0] for r in conn.exec_driver_sql("SELECT version_num FROM alembic_version_health;").fetchall()] == ["health_0002_fhir_ehr_repository"]
        tables_after_reupgrade = set(inspect(conn).get_table_names())
        assert "health_resource_versions" in tables_after_reupgrade
        assert "health_resource_codings" in tables_after_reupgrade
        assert "health_resource_references" in tables_after_reupgrade
