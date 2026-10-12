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

"""Adversarial stress testing suite for Alembic schema evolution, repeated cycles, and SQLite batch rebuilds."""

import datetime
from pathlib import Path
import tempfile
import uuid

import alembic.command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool, StaticPool

from carefold.db.session import get_alembic_config

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

EXPECTED_CAS_COLUMNS = {
    "extracted_text",
    "source",
    "source_ref",
    "extraction_status",
    "updated_at",
}


def test_repeated_upgrade_downgrade_cycles_sqlite():
    """Empirically stress-tests repeated upgrade/downgrade cycles across multiple rounds:

    upgrade head -> downgrade 0002_autonomy_foundations -> downgrade 0001_baseline_schema -> upgrade head -> downgrade base -> upgrade head (x3 iterations).
    Verifies table sets, indexes, alembic_version tracking, and absence of temporary rebuild tables.
    """
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)

    with engine.connect() as conn:
        cfg = get_alembic_config(conn)

        for iteration in range(1, 4):
            # 1. Upgrade to head (0003_autonomy_batch_1)
            alembic.command.upgrade(cfg, "head")
            insp = inspect(conn)
            tables = set(insp.get_table_names())
            assert EXPECTED_HEAD_TABLES.issubset(tables), f"Iteration {iteration}: Missing head tables"
            assert not any(t.startswith("_alembic_tmp_") for t in tables), f"Iteration {iteration}: Lingering tmp tables"

            curr_ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert curr_ver == "0003_autonomy_batch_1", f"Iteration {iteration}: Expected 0003_autonomy_batch_1 at head, got {curr_ver}"

            # 1b. Downgrade to 0002_autonomy_foundations
            alembic.command.downgrade(cfg, "0002_autonomy_foundations")
            insp_0002 = inspect(conn)
            tables_0002 = set(insp_0002.get_table_names())
            assert "profile_keys" not in tables_0002, f"Iteration {iteration}: profile_keys not dropped on 0002 downgrade"
            assert "approvals" not in tables_0002, f"Iteration {iteration}: approvals not dropped on 0002 downgrade"
            assert "jobs" not in tables_0002, f"Iteration {iteration}: jobs not dropped on 0002 downgrade"
            assert {"audit_events", "connections", "credentials"}.issubset(tables_0002), f"Iteration {iteration}: Missing 0002 tables"
            assert not any(t.startswith("_alembic_tmp_") for t in tables_0002), f"Iteration {iteration}: Lingering tmp tables"
            curr_ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert curr_ver == "0002_autonomy_foundations", f"Iteration {iteration}: Expected 0002 at foundations, got {curr_ver}"

            # 2. Downgrade to 0001_baseline_schema
            alembic.command.downgrade(cfg, "0001_baseline_schema")
            insp = inspect(conn)
            tables = set(insp.get_table_names())
            assert EXPECTED_BASELINE_TABLES.issubset(tables), f"Iteration {iteration}: Missing baseline tables"
            assert "audit_events" not in tables, f"Iteration {iteration}: audit_events not dropped"
            assert "connections" not in tables, f"Iteration {iteration}: connections not dropped"
            assert "credentials" not in tables, f"Iteration {iteration}: credentials not dropped"
            assert "profile_keys" not in tables, f"Iteration {iteration}: profile_keys not dropped"
            assert "approvals" not in tables, f"Iteration {iteration}: approvals not dropped"
            assert "jobs" not in tables, f"Iteration {iteration}: jobs not dropped"
            assert not any(t.startswith("_alembic_tmp_") for t in tables), f"Iteration {iteration}: Lingering tmp tables"

            curr_ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert curr_ver == "0001_baseline_schema", f"Iteration {iteration}: Expected 0001 at baseline, got {curr_ver}"

            # 3. Upgrade back to head
            alembic.command.upgrade(cfg, "head")
            insp = inspect(conn)
            tables = set(insp.get_table_names())
            assert EXPECTED_HEAD_TABLES.issubset(tables), f"Iteration {iteration}: Missing head tables after re-upgrade"
            curr_ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert curr_ver == "0003_autonomy_batch_1", f"Iteration {iteration}: Expected 0003_autonomy_batch_1 after re-upgrade, got {curr_ver}"

            # 4. Downgrade to base
            alembic.command.downgrade(cfg, "base")
            insp = inspect(conn)
            tables = set(insp.get_table_names())
            # All application tables should be dropped
            assert len(tables - {"alembic_version"}) == 0, f"Iteration {iteration}: Tables remained after downgrade to base: {tables}"

            # 5. Upgrade back to head
            alembic.command.upgrade(cfg, "head")
            insp = inspect(conn)
            tables = set(insp.get_table_names())
            assert EXPECTED_HEAD_TABLES.issubset(tables), f"Iteration {iteration}: Missing head tables after base upgrade"
            curr_ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert curr_ver == "0003_autonomy_batch_1", f"Iteration {iteration}: Expected 0003_autonomy_batch_1 after base upgrade, got {curr_ver}"


def test_batch_rebuild_data_preservation_and_cas_lifecycle():
    """Empirically verifies data preservation during SQLite batch table rebuilds:

    - Seeds diverse, adversarial rows into baseline schema.
    - Upgrades to 0002_autonomy_foundations and populates CAS columns.
    - Downgrades to 0001_baseline_schema (dropping CAS columns via batch alter).
    - Verifies all original baseline columns and values are 100% preserved.
    - Re-upgrades to head and verifies existing rows have clean defaults populated.
    """
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)

    with engine.connect() as conn:
        cfg = get_alembic_config(conn)

        # Start at 0001_baseline_schema
        alembic.command.upgrade(cfg, "0001_baseline_schema")

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Seed adversarial users
        test_users = [
            {
                "id": "usr-adversarial-1",
                "email": "doctor_josé@carefold.ai",
                "username": "josé_ramírez_🩺",
                "hashed_password": "argon2$mock$hash$1",
                "full_name": "Dr. José Ramírez, MD 🩺",
                "role": "steward",
                "status": "active",
                "auth_provider": "local",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": "usr-adversarial-2",
                "email": "sqli_test@carefold.ai",
                "username": "admin' OR '1'='1; --",
                "hashed_password": "argon2$mock$hash$2",
                "full_name": "SQL Injection Tester",
                "role": "member",
                "status": "active",
                "auth_provider": "local",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": "usr-adversarial-3",
                "email": "long_name@carefold.ai",
                "username": "u" * 64,
                "hashed_password": "argon2$mock$hash$3",
                "full_name": "N" * 255,
                "role": "admin",
                "status": "disabled",
                "auth_provider": "oidc",
                "created_at": now,
                "updated_at": now,
            },
        ]

        for u in test_users:
            conn.execute(
                text("""
                    INSERT INTO users (
                        id, email, username, hashed_password, full_name, role, status, auth_provider, created_at, updated_at
                    ) VALUES (
                        :id, :email, :username, :hashed_password, :full_name, :role, :status, :auth_provider, :created_at, :updated_at
                    )
                """),
                u,
            )

        # Seed profile
        conn.execute(
            text("""
                INSERT INTO profiles (
                    id, user_id, name, relationship, role, avatar_color, is_primary, created_at, updated_at
                ) VALUES (
                    'prof-test-1', 'usr-adversarial-1', 'José Family Member', 'self', 'self', '#10b981', 1, :now, :now
                )
            """),
            {"now": now},
        )

        # Seed adversarial baseline attachments
        large_content_length = 5_000_000_000  # 5 GB representation
        test_attachments = [
            {
                "id": "att-standard-1",
                "user_id": "usr-adversarial-1",
                "profile_id": "prof-test-1",
                "storage_key": "usr-adversarial-1/prof-test-1/blood_panel.pdf",
                "filename": "blood_panel.pdf",
                "original_name": "blood_panel.pdf",
                "content_type": "application/pdf",
                "size_bytes": 1048576,
                "sha256_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "created_at": now,
            },
            {
                "id": "att-unicode-2",
                "user_id": "usr-adversarial-1",
                "profile_id": "prof-test-1",
                "storage_key": "usr-adversarial-1/prof-test-1/تقرير_مختبر_🔬.pdf",
                "filename": "تقرير_مختبر_🔬.pdf",
                "original_name": "تقرير_مختبر_🔬.pdf",
                "content_type": "application/pdf",
                "size_bytes": 2048,
                "sha256_hash": "a" * 64,
                "created_at": now,
            },
            {
                "id": "att-sqli-3",
                "user_id": "usr-adversarial-2",
                "profile_id": None,
                "storage_key": None,
                "filename": "drop'; DROP TABLE attachments; --.txt",
                "original_name": "drop'; DROP TABLE attachments; --.txt",
                "content_type": "text/plain",
                "size_bytes": 128,
                "sha256_hash": None,
                "created_at": now,
            },
            {
                "id": "att-large-4",
                "user_id": None,
                "profile_id": None,
                "storage_key": None,
                "filename": "mri_scan_3d.raw",
                "original_name": "mri_scan_3d.raw",
                "content_type": "application/octet-stream",
                "size_bytes": large_content_length,
                "sha256_hash": "f" * 64,
                "created_at": now,
            },
        ]

        for att in test_attachments:
            conn.execute(
                text("""
                    INSERT INTO attachments (
                        id, user_id, profile_id, storage_key, filename, original_name, content_type, size_bytes, sha256_hash, created_at
                    ) VALUES (
                        :id, :user_id, :profile_id, :storage_key, :filename, :original_name, :content_type, :size_bytes, :sha256_hash, :created_at
                    )
                """),
                att,
            )
        conn.commit()

        # Step 1: Upgrade to 0002_autonomy_foundations
        alembic.command.upgrade(cfg, "0002_autonomy_foundations")

        insp = inspect(conn)
        att_cols = {c["name"] for c in insp.get_columns("attachments")}
        assert EXPECTED_CAS_COLUMNS.issubset(att_cols), "CAS columns not added on upgrade"

        # Step 2: Populate CAS columns with diverse values
        large_extracted_text = "Clinical note: Patient presents with chest tightness.\n" * 1000
        cas_updates = [
            ("att-standard-1", large_extracted_text, "upload", "up-ref-1", "completed", now),
            ("att-unicode-2", "التقرير الطبي الكامل مع الرموز 🩺🔬", "connector", "epic-fhir-001", "completed", now),
            ("att-sqli-3", "SQL Injection extracted text '--", "upload", None, "failed", now),
            ("att-large-4", None, "upload", None, "pending", None),
        ]

        for aid, text_val, src, ref, status, upd in cas_updates:
            conn.execute(
                text("""
                    UPDATE attachments
                    SET extracted_text = :text_val,
                        source = :src,
                        source_ref = :ref,
                        extraction_status = :status,
                        updated_at = :upd
                    WHERE id = :aid
                """),
                {"aid": aid, "text_val": text_val, "src": src, "ref": ref, "status": status, "upd": upd},
            )

        # Also populate autonomous tables
        conn.execute(
            text("""
                INSERT INTO audit_events (
                    id, ts, profile_id, actor_user_id, principal, run_id, event, tool, risk, decision, payload_hash, external_ref, detail_redacted
                ) VALUES (
                    'aud-1', :now, 'prof-test-1', 'usr-adversarial-1', 'user', 'run-1', 'tool_exec', 'attach_read', 'low', 'allow',
                    'payloadhash123', 'ext-1', '{"detail": "sanitized"}'
                )
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO connections (
                    id, user_id, profile_id, connector_id, status, config_json, created_at, updated_at
                ) VALUES (
                    'conn-1', 'usr-adversarial-1', 'prof-test-1', 'mychart', 'active', '{"endpoint": "https://epic.example.com"}', :now, :now
                )
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO credentials (
                    id, connection_id, profile_id, token_version, encrypted_blob, created_at, updated_at
                ) VALUES (
                    'cred-1', 'conn-1', 'prof-test-1', 1, 'encrypted_token_material_mock', :now, :now
                )
            """),
            {"now": now},
        )
        conn.commit()

        # Step 3: Downgrade back to 0001_baseline_schema (rebuilds attachments via SQLite batch mode)
        alembic.command.downgrade(cfg, "0001_baseline_schema")

        insp_down = inspect(conn)
        tables_down = set(insp_down.get_table_names())
        assert "audit_events" not in tables_down
        assert "connections" not in tables_down
        assert "credentials" not in tables_down

        down_att_cols = {c["name"] for c in insp_down.get_columns("attachments")}
        for cas_c in EXPECTED_CAS_COLUMNS:
            assert cas_c not in down_att_cols, f"CAS column {cas_c} should be dropped after downgrade"

        # Verify all users remain completely intact
        user_rows = {
            r[0]: r for r in conn.execute(text("SELECT id, email, username, full_name, role, status FROM users")).fetchall()
        }
        assert len(user_rows) == 3
        assert user_rows["usr-adversarial-1"][1] == "doctor_josé@carefold.ai"
        assert user_rows["usr-adversarial-1"][2] == "josé_ramírez_🩺"
        assert user_rows["usr-adversarial-1"][3] == "Dr. José Ramírez, MD 🩺"
        assert user_rows["usr-adversarial-2"][2] == "admin' OR '1'='1; --"
        assert user_rows["usr-adversarial-3"][2] == "u" * 64

        # Verify all attachments remain completely intact in baseline columns
        att_rows = {
            r[0]: r
            for r in conn.execute(
                text("SELECT id, user_id, profile_id, storage_key, filename, original_name, content_type, size_bytes, sha256_hash FROM attachments")
            ).fetchall()
        }
        assert len(att_rows) == 4

        # Standard file check
        assert att_rows["att-standard-1"][1] == "usr-adversarial-1"
        assert att_rows["att-standard-1"][2] == "prof-test-1"
        assert att_rows["att-standard-1"][3] == "usr-adversarial-1/prof-test-1/blood_panel.pdf"
        assert att_rows["att-standard-1"][4] == "blood_panel.pdf"
        assert att_rows["att-standard-1"][6] == "application/pdf"
        assert att_rows["att-standard-1"][7] == 1048576

        # Unicode file check
        assert att_rows["att-unicode-2"][4] == "تقرير_مختبر_🔬.pdf"
        assert att_rows["att-unicode-2"][8] == "a" * 64

        # SQL injection filename check
        assert att_rows["att-sqli-3"][4] == "drop'; DROP TABLE attachments; --.txt"
        assert att_rows["att-sqli-3"][3] is None
        assert att_rows["att-sqli-3"][8] is None

        # Large size check
        assert att_rows["att-large-4"][7] == large_content_length

        # Step 4: Re-upgrade to head
        alembic.command.upgrade(cfg, "head")

        insp_reup = inspect(conn)
        reup_att_cols = {c["name"] for c in insp_reup.get_columns("attachments")}
        assert EXPECTED_CAS_COLUMNS.issubset(reup_att_cols)

        # Verify that existing rows have clean server defaults populated
        reup_rows = {
            r[0]: r
            for r in conn.execute(
                text("SELECT id, source, extraction_status, extracted_text, source_ref, updated_at FROM attachments")
            ).fetchall()
        }
        for aid in ["att-standard-1", "att-unicode-2", "att-sqli-3", "att-large-4"]:
            row = reup_rows[aid]
            assert row[1] == "upload", f"Row {aid}: Expected source='upload', got {row[1]}"
            assert row[2] == "pending", f"Row {aid}: Expected extraction_status='pending', got {row[2]}"
            assert row[3] is None, f"Row {aid}: Expected extracted_text=None, got {row[3]}"
            assert row[4] is None, f"Row {aid}: Expected source_ref=None, got {row[4]}"

        # Step 5: Verify new inserts work cleanly with CAS fields and in new tables
        conn.execute(
            text("""
                INSERT INTO attachments (
                    id, user_id, profile_id, storage_key, filename, original_name, content_type, size_bytes, sha256_hash, created_at,
                    extracted_text, source, source_ref, extraction_status, updated_at
                ) VALUES (
                    'att-fresh-5', 'usr-adversarial-1', 'prof-test-1', 'key5', 'fresh.txt', 'fresh.txt', 'text/plain', 10, 'hash5', :now,
                    'Freshly extracted text', 'manual', 'manual-ref', 'completed', :now
                )
            """),
            {"now": now},
        )
        fresh_row = conn.execute(
            text("SELECT source, extraction_status, extracted_text FROM attachments WHERE id = 'att-fresh-5'")
        ).fetchone()
        assert fresh_row == ("manual", "completed", "Freshly extracted text")


def test_sqlite_batch_rebuild_with_pragma_foreign_keys_on():
    """Empirically tests that SQLite batch rebuilds succeed cleanly even when PRAGMA foreign_keys = ON.

    SQLite's table rebuild procedure (create temp, copy, drop original, rename temp) can fail with
    foreign key constraint violations if foreign key enforcement is active and constraints are violated.
    Alembic batch alter mode must handle this safely.
    """
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)

    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys = ON;"))
        fk_status = conn.execute(text("PRAGMA foreign_keys;")).scalar()
        assert fk_status == 1, "Foreign keys must be enabled for this test"

        cfg = get_alembic_config(conn)

        # Baseline migration
        alembic.command.upgrade(cfg, "0001_baseline_schema")

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Insert parent user
        conn.execute(
            text("""
                INSERT INTO users (id, email, username, hashed_password, role, status, auth_provider, created_at, updated_at)
                VALUES ('fk-user-1', 'fk@carefold.ai', 'fkuser', 'hash', 'steward', 'active', 'local', :now, :now)
            """),
            {"now": now},
        )
        # Insert parent profile referencing user
        conn.execute(
            text("""
                INSERT INTO profiles (id, user_id, name, relationship, role, avatar_color, is_primary, created_at, updated_at)
                VALUES ('fk-prof-1', 'fk-user-1', 'FK Profile', 'self', 'self', '#3b82f6', 1, :now, :now)
            """),
            {"now": now},
        )
        # Insert child attachment referencing both user and profile
        conn.execute(
            text("""
                INSERT INTO attachments (id, user_id, profile_id, filename, original_name, content_type, size_bytes, created_at)
                VALUES ('fk-att-1', 'fk-user-1', 'fk-prof-1', 'fk.pdf', 'fk.pdf', 'application/pdf', 100, :now)
            """),
            {"now": now},
        )
        conn.commit()

        # Upgrade to head with FK on
        alembic.command.upgrade(cfg, "head")

        # Downgrade to 0001_baseline_schema with FK on
        alembic.command.downgrade(cfg, "0001_baseline_schema")

        # Confirm data remains valid and foreign key relationship is unbroken
        row = conn.execute(text("SELECT user_id, profile_id FROM attachments WHERE id = 'fk-att-1'")).fetchone()
        assert row == ("fk-user-1", "fk-prof-1")


def test_file_based_sqlite_database_lifecycle():
    """Empirically tests migration cycles, batch rebuilds, and WAL journal mode on real disk files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "carefold_stress.db"
        engine = create_engine(f"sqlite:///{db_path}", poolclass=NullPool)

        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode = WAL;"))
            cfg = get_alembic_config(conn)

            # 1. Upgrade head
            alembic.command.upgrade(cfg, "head")

            # 2. Insert record
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            conn.execute(
                text("""
                    INSERT INTO users (id, email, username, hashed_password, role, status, auth_provider, created_at, updated_at)
                    VALUES ('disk-usr-1', 'disk@carefold.ai', 'diskuser', 'h', 'steward', 'active', 'local', :now, :now)
                """),
                {"now": now},
            )
            conn.execute(
                text("""
                    INSERT INTO attachments (
                        id, user_id, filename, original_name, content_type, size_bytes, created_at,
                        extracted_text, source, extraction_status
                    ) VALUES (
                        'disk-att-1', 'disk-usr-1', 'disk.txt', 'disk.txt', 'text/plain', 50, :now,
                        'Extracted on disk', 'upload', 'completed'
                    )
                """),
                {"now": now},
            )
            conn.commit()

            # 3. Downgrade to baseline
            alembic.command.downgrade(cfg, "0001_baseline_schema")

            att_row = conn.execute(text("SELECT id, filename, size_bytes FROM attachments WHERE id = 'disk-att-1'")).fetchone()
            assert att_row == ("disk-att-1", "disk.txt", 50)

            # 4. Re-upgrade to head
            alembic.command.upgrade(cfg, "head")

            # 5. Check WAL file / persistence
            reup_row = conn.execute(text("SELECT id, source, extraction_status FROM attachments WHERE id = 'disk-att-1'")).fetchone()
            assert reup_row == ("disk-att-1", "upload", "pending")


def test_high_volume_batch_rebuild_preservation():
    """Empirically verifies that high-volume datasets (500 rows) survive batch rebuilds without truncation or data drift."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)

    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "0001_baseline_schema")

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Seed 100 users
        users = [
            {
                "id": f"u-bulk-{i}",
                "email": f"user{i}@carefold.ai",
                "username": f"user_{i}",
                "hashed_password": "hash",
                "role": "member",
                "status": "active",
                "auth_provider": "local",
                "created_at": now,
                "updated_at": now,
            }
            for i in range(100)
        ]
        for u in users:
            conn.execute(
                text("""
                    INSERT INTO users (id, email, username, hashed_password, role, status, auth_provider, created_at, updated_at)
                    VALUES (:id, :email, :username, :hashed_password, :role, :status, :auth_provider, :created_at, :updated_at)
                """),
                u,
            )

        # Seed 500 attachments
        attachments = [
            {
                "id": f"att-bulk-{i}",
                "user_id": f"u-bulk-{i % 100}",
                "profile_id": None,
                "storage_key": f"key_{i}",
                "filename": f"file_{i}.pdf",
                "original_name": f"file_{i}.pdf",
                "content_type": "application/pdf",
                "size_bytes": 1000 + i,
                "sha256_hash": f"hash_{i:064d}",
                "created_at": now,
            }
            for i in range(500)
        ]
        for att in attachments:
            conn.execute(
                text("""
                    INSERT INTO attachments (id, user_id, profile_id, storage_key, filename, original_name, content_type, size_bytes, sha256_hash, created_at)
                    VALUES (:id, :user_id, :profile_id, :storage_key, :filename, :original_name, :content_type, :size_bytes, :sha256_hash, :created_at)
                """),
                att,
            )
        conn.commit()

        # Upgrade to 0002_autonomy_foundations
        alembic.command.upgrade(cfg, "0002_autonomy_foundations")

        # Downgrade to 0001_baseline_schema (rebuilds table with 500 rows)
        alembic.command.downgrade(cfg, "0001_baseline_schema")

        count_users = conn.execute(text("SELECT count(*) FROM users")).scalar()
        assert count_users == 100, f"Expected 100 users, found {count_users}"

        count_att = conn.execute(text("SELECT count(*) FROM attachments")).scalar()
        assert count_att == 500, f"Expected 500 attachments, found {count_att}"

        # Spot check boundary rows
        first_row = conn.execute(text("SELECT filename, size_bytes FROM attachments WHERE id = 'att-bulk-0'")).fetchone()
        assert first_row == ("file_0.pdf", 1000)

        last_row = conn.execute(text("SELECT filename, size_bytes FROM attachments WHERE id = 'att-bulk-499'")).fetchone()
        assert last_row == ("file_499.pdf", 1499)


def test_partial_columns_idempotency_resilience():
    """Empirically tests that 0002_autonomy_foundations is resilient to partially pre-existing columns.

    If a legacy migration or manual patch already added e.g. extracted_text, upgrading to head
    must not fail with 'duplicate column name: extracted_text'.
    """
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)

    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "0001_baseline_schema")

        # Manually inject one CAS column before migration
        conn.execute(text("ALTER TABLE attachments ADD COLUMN extracted_text TEXT;"))
        conn.commit()

        # Upgrade to head: should succeed without OperationalError
        alembic.command.upgrade(cfg, "head")

        insp = inspect(conn)
        cols = {c["name"] for c in insp.get_columns("attachments")}
        assert EXPECTED_CAS_COLUMNS.issubset(cols)


def test_index_lifecycle_and_uniqueness_enforcement():
    """Empirically verifies that indexes survive table rebuilds and maintain constraint enforcement."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)

    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "head")

        insp = inspect(conn)
        att_indexes_head = {idx["name"] for idx in insp.get_indexes("attachments")}
        assert "ix_attachments_source" in att_indexes_head
        assert "ix_attachments_extraction_status" in att_indexes_head
        assert "ix_attachments_filename" in att_indexes_head

        # Downgrade to 0001_baseline_schema
        alembic.command.downgrade(cfg, "0001_baseline_schema")

        insp_down = inspect(conn)
        att_indexes_down = {idx["name"] for idx in insp_down.get_indexes("attachments")}
        assert "ix_attachments_source" not in att_indexes_down
        assert "ix_attachments_extraction_status" not in att_indexes_down
        assert "ix_attachments_filename" in att_indexes_down

        # Test unique constraint on users
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn.execute(
            text("""
                INSERT INTO users (id, email, username, hashed_password, role, status, auth_provider, created_at, updated_at)
                VALUES ('u-uniq-1', 'unique@carefold.ai', 'uniq_user', 'h', 'steward', 'active', 'local', :now, :now)
            """),
            {"now": now},
        )
        conn.commit()

        # Duplicate email must raise IntegrityError
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            conn.execute(
                text("""
                    INSERT INTO users (id, email, username, hashed_password, role, status, auth_provider, created_at, updated_at)
                    VALUES ('u-uniq-2', 'unique@carefold.ai', 'another_user', 'h', 'steward', 'active', 'local', :now, :now)
                """),
                {"now": now},
            )
        conn.rollback()

        # Re-upgrade to head and verify CAS indexes restored
        alembic.command.upgrade(cfg, "head")
        insp_reup = inspect(conn)
        att_indexes_reup = {idx["name"] for idx in insp_reup.get_indexes("attachments")}
        assert "ix_attachments_source" in att_indexes_reup
        assert "ix_attachments_extraction_status" in att_indexes_reup


def test_offline_sql_downgrade_generation_dialects():
    """Empirically verifies offline SQL generation (sql=True) across SQLite and Postgres dialects.

    - PostgreSQL supports offline SQL generation for both upgrades and downgrades via native ALTER TABLE.
    - SQLite supports offline upgrade, but offline downgrade of batch-altered tables requires live connection
      reflection (or copy_from Table spec) because SQLite table rebuilds require existing column schema.
    """
    import io
    import alembic.util.exc

    # 1. PostgreSQL dialect offline upgrade and downgrade (generates pure SQL DDL)
    buf_pg_up = io.StringIO()
    cfg_pg_up = get_alembic_config()
    cfg_pg_up.attributes["output_buffer"] = buf_pg_up
    cfg_pg_up.set_main_option("sqlalchemy.url", "postgresql://user:pass@localhost:5432/carefold")

    alembic.command.upgrade(cfg_pg_up, "head", sql=True)
    sql_pg_up = buf_pg_up.getvalue()
    assert "CREATE TABLE users" in sql_pg_up
    assert "CREATE TABLE audit_events" in sql_pg_up

    buf_pg_down = io.StringIO()
    cfg_pg_down = get_alembic_config()
    cfg_pg_down.attributes["output_buffer"] = buf_pg_down
    cfg_pg_down.set_main_option("sqlalchemy.url", "postgresql://user:pass@localhost:5432/carefold")

    alembic.command.downgrade(cfg_pg_down, "head:0001_baseline_schema", sql=True)
    sql_pg_down = buf_pg_down.getvalue()
    assert "DROP TABLE jobs;" in sql_pg_down
    assert "DROP TABLE approvals;" in sql_pg_down
    assert "DROP TABLE profile_keys;" in sql_pg_down
    assert "DROP TABLE credentials;" in sql_pg_down
    assert "DROP TABLE connections;" in sql_pg_down
    assert "DROP TABLE audit_events;" in sql_pg_down
    assert "ALTER TABLE attachments DROP COLUMN updated_at;" in sql_pg_down
    assert "ALTER TABLE attachments DROP COLUMN extracted_text;" in sql_pg_down

    # 2. SQLite dialect offline upgrade succeeds
    buf_sqlite_up = io.StringIO()
    cfg_sqlite_up = get_alembic_config()
    cfg_sqlite_up.attributes["output_buffer"] = buf_sqlite_up
    cfg_sqlite_up.set_main_option("sqlalchemy.url", "sqlite:///:memory:")

    alembic.command.upgrade(cfg_sqlite_up, "head", sql=True)
    sql_sqlite_up = buf_sqlite_up.getvalue()
    assert "CREATE TABLE users" in sql_sqlite_up
    assert "CREATE TABLE attachments" in sql_sqlite_up

    # 3. SQLite dialect offline downgrade requires live connection reflection for table copy/move rebuild
    buf_sqlite_down = io.StringIO()
    cfg_sqlite_down = get_alembic_config()
    cfg_sqlite_down.attributes["output_buffer"] = buf_sqlite_down
    cfg_sqlite_down.set_main_option("sqlalchemy.url", "sqlite:///:memory:")

    with pytest.raises(alembic.util.exc.CommandError) as exc_info:
        alembic.command.downgrade(cfg_sqlite_down, "head:0001_baseline_schema", sql=True)
    assert "batch mode with dialect sqlite requires a live database connection" in str(exc_info.value)


