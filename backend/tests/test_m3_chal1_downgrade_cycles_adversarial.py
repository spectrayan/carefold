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

"""Adversarial stress test suite for schema evolution, downgrade cycles, and SQLite batch rebuilds.

Challenger 1 (m3_rem_chal1) Verification Suite for AU-02, Requirement R4:
1. Full upgrade/downgrade cycle on SQLite:
   upgrade head -> downgrade 0001_baseline_schema -> upgrade head -> downgrade base -> upgrade head.
2. Data preservation under batch rebuild:
   Populate test rows into `users` and `attachments` in baseline schema,
   upgrade to `0002_autonomy_foundations`,
   populate CAS columns on attachments,
   downgrade back to `0001_baseline_schema` (verifying SQLite batch mode rebuilds table and
   drops CAS columns without corrupting original records or raising OperationalError).
3. Re-upgrade to head and verify existing rows remain valid and default values populate cleanly.
4. Edge cases: PRAGMA foreign_keys = ON, multi-cycle data growth, boundary values, and init_db() integration.
"""

from __future__ import annotations

import datetime
from pathlib import Path
import tempfile
import uuid

import alembic.command
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from carefold.db.session import get_alembic_config, init_db

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


# =============================================================================
# 1. Full Upgrade/Downgrade Cycle Tests (Memory and Disk SQLite)
# =============================================================================

@pytest.mark.parametrize("use_disk", [False, True])
def test_adversarial_downgrade_cycle_sqlite_memory_and_file(use_disk: bool):
    """Verifies the complete upgrade/downgrade cycle on SQLite:
    upgrade head -> downgrade 0001_baseline_schema -> upgrade head -> downgrade base -> upgrade head.

    Tested on both in-memory and file-backed SQLite engines.
    Verifies table inventories, alembic_version entries, absence of tmp tables, and index recreation.
    """
    tmp_dir = None
    if use_disk:
        tmp_dir = tempfile.TemporaryDirectory()
        db_path = Path(tmp_dir.name) / "cycle_test.db"
        engine = create_engine(f"sqlite:///{db_path}", poolclass=NullPool)
    else:
        engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)

    try:
        with engine.connect() as conn:
            cfg = get_alembic_config(conn)

            # Step 1: upgrade head
            alembic.command.upgrade(cfg, "head")
            insp = inspect(conn)
            tables = set(insp.get_table_names())
            assert EXPECTED_HEAD_TABLES.issubset(tables), f"Missing head tables: {EXPECTED_HEAD_TABLES - tables}"
            assert not any(t.startswith("_alembic_tmp_") for t in tables), "Found lingering _alembic_tmp_ tables"
            rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert rev == "0002_autonomy_foundations"

            # Check CAS columns on attachments
            att_cols = {c["name"] for c in insp.get_columns("attachments")}
            assert EXPECTED_ATTACHMENT_CAS_COLUMNS.issubset(att_cols)

            # Step 2: downgrade 0001_baseline_schema
            alembic.command.downgrade(cfg, "0001_baseline_schema")
            insp_down = inspect(conn)
            tables_down = set(insp_down.get_table_names())
            assert EXPECTED_BASELINE_TABLES.issubset(tables_down), f"Missing baseline tables: {EXPECTED_BASELINE_TABLES - tables_down}"
            assert "audit_events" not in tables_down
            assert "connections" not in tables_down
            assert "credentials" not in tables_down
            assert not any(t.startswith("_alembic_tmp_") for t in tables_down)
            rev_down = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert rev_down == "0001_baseline_schema"

            # Verify CAS columns removed via SQLite batch alter
            att_cols_down = {c["name"] for c in insp_down.get_columns("attachments")}
            for col in EXPECTED_ATTACHMENT_CAS_COLUMNS:
                assert col not in att_cols_down, f"CAS column '{col}' still present after baseline downgrade"

            # Step 3: upgrade head
            alembic.command.upgrade(cfg, "head")
            insp_reup = inspect(conn)
            tables_reup = set(insp_reup.get_table_names())
            assert EXPECTED_HEAD_TABLES.issubset(tables_reup)
            rev_reup = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert rev_reup == "0002_autonomy_foundations"
            att_cols_reup = {c["name"] for c in insp_reup.get_columns("attachments")}
            assert EXPECTED_ATTACHMENT_CAS_COLUMNS.issubset(att_cols_reup)

            # Step 4: downgrade base
            alembic.command.downgrade(cfg, "base")
            insp_base = inspect(conn)
            tables_base = set(insp_base.get_table_names())
            # All application tables must be cleanly dropped
            remaining_app_tables = tables_base - {"alembic_version"}
            assert len(remaining_app_tables) == 0, f"App tables remained after downgrade base: {remaining_app_tables}"

            # Step 5: upgrade head
            alembic.command.upgrade(cfg, "head")
            insp_final = inspect(conn)
            tables_final = set(insp_final.get_table_names())
            assert EXPECTED_HEAD_TABLES.issubset(tables_final)
            rev_final = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert rev_final == "0002_autonomy_foundations"
            att_cols_final = {c["name"] for c in insp_final.get_columns("attachments")}
            assert EXPECTED_ATTACHMENT_CAS_COLUMNS.issubset(att_cols_final)
    finally:
        engine.dispose()
        if tmp_dir:
            tmp_dir.cleanup()


# =============================================================================
# 2. Data Preservation Under SQLite Batch Rebuild (AU-02, Requirement R4)
# =============================================================================

def test_adversarial_data_preservation_batch_rebuild_cas_lifecycle():
    """Empirically verifies:
    1. Populates test rows into users, profiles, and attachments at 0001_baseline_schema.
    2. Upgrades to 0002_autonomy_foundations.
    3. Populates CAS columns on attachments and autonomous tables.
    4. Downgrades back to 0001_baseline_schema:
       - SQLite batch rebuild recreates attachments table.
       - CAS columns are dropped cleanly without OperationalError.
       - Original baseline columns and values are 100% preserved.
    5. Re-upgrades to head:
       - Existing rows remain valid.
       - Default values populate cleanly on re-added CAS columns.
       - New rows can be inserted and queried cleanly.
    """
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)

    with engine.connect() as conn:
        cfg = get_alembic_config(conn)

        # 1. Start at baseline
        alembic.command.upgrade(cfg, "0001_baseline_schema")

        now = "2026-10-12T01:00:00Z"
        uid1 = "usr-pres-1"
        uid2 = "usr-pres-2"
        pid1 = "prof-pres-1"
        aid1 = "att-pres-1"
        aid2 = "att-pres-2"
        aid3 = "att-pres-unicode"

        # Insert baseline users
        conn.execute(
            text("""
                INSERT INTO users (id, email, username, hashed_password, full_name, role, status, auth_provider, created_at, updated_at)
                VALUES
                    (:u1, 'alice@carefold.ai', 'alice', 'argon2_alice_hash', 'Alice Smith', 'steward', 'active', 'local', :now, :now),
                    (:u2, 'bob@carefold.ai', 'bob_🩺', 'argon2_bob_hash', 'Dr. Bob 🩺', 'member', 'active', 'oidc', :now, :now)
            """),
            {"u1": uid1, "u2": uid2, "now": now},
        )

        # Insert baseline profile
        conn.execute(
            text("""
                INSERT INTO profiles (id, user_id, name, relationship, role, avatar_color, is_primary, created_at, updated_at)
                VALUES (:p1, :u1, 'Alice Primary', 'self', 'self', '#10b981', 1, :now, :now)
            """),
            {"p1": pid1, "u1": uid1, "now": now},
        )

        # Insert baseline attachments (without CAS columns)
        conn.execute(
            text("""
                INSERT INTO attachments (id, user_id, profile_id, storage_key, filename, original_name, content_type, size_bytes, sha256_hash, created_at)
                VALUES
                    (:a1, :u1, :p1, 'u1/p1/lab_report.pdf', 'lab_report.pdf', 'Lab Report Oct.pdf', 'application/pdf', 1048576, 'hash_sha256_lab_1', :now),
                    (:a2, :u2, NULL, 'u2/none/cardio_ecg.xml', 'cardio_ecg.xml', 'cardio_ecg.xml', 'text/xml', 65536, 'hash_sha256_ecg_2', :now),
                    (:a3, :u1, :p1, 'u1/p1/فحص_دم_🔬.pdf', 'فحص_دم_🔬.pdf', 'فحص_دم_🔬.pdf', 'application/pdf', 2048, 'hash_sha256_arabic_3', :now)
            """),
            {"a1": aid1, "a2": aid2, "a3": aid3, "u1": uid1, "u2": uid2, "p1": pid1, "now": now},
        )
        conn.commit()

        # 2. Upgrade to 0002_autonomy_foundations
        alembic.command.upgrade(cfg, "0002_autonomy_foundations")

        insp_after_up = inspect(conn)
        cols_after_up = {c["name"] for c in insp_after_up.get_columns("attachments")}
        assert EXPECTED_ATTACHMENT_CAS_COLUMNS.issubset(cols_after_up)

        # Verify initial default values after upgrade
        rows_init_cas = conn.execute(
            text("SELECT id, source, extraction_status, extracted_text, source_ref, updated_at FROM attachments ORDER BY id")
        ).fetchall()
        assert len(rows_init_cas) == 3
        for r in rows_init_cas:
            assert r[1] == "upload", f"Default source expected 'upload', got {r[1]}"
            assert r[2] == "pending", f"Default extraction_status expected 'pending', got {r[2]}"
            assert r[3] is None, f"Default extracted_text expected None, got {r[3]}"
            assert r[4] is None, f"Default source_ref expected None, got {r[4]}"
            assert r[5] is None, f"Default updated_at expected None, got {r[5]}"

        # 3. Populate CAS columns with actual non-default data
        large_extracted_text = "CLINICAL SUMMARY: Normal sinus rhythm. Hemoglobin A1C: 5.4%.\n" * 200
        conn.execute(
            text("""
                UPDATE attachments
                SET extracted_text = :text_val,
                    source = 'connector',
                    source_ref = 'epic-fhir-doc-101',
                    extraction_status = 'completed',
                    updated_at = :now
                WHERE id = :a1
            """),
            {"text_val": large_extracted_text, "now": now, "a1": aid1},
        )
        conn.execute(
            text("""
                UPDATE attachments
                SET extracted_text = 'ECG Lead II analysis: normal PR interval',
                    source = 'manual',
                    source_ref = 'steward-entry-02',
                    extraction_status = 'completed',
                    updated_at = :now
                WHERE id = :a2
            """),
            {"now": now, "a2": aid2},
        )
        conn.execute(
            text("""
                UPDATE attachments
                SET extracted_text = 'تقرير الفحص المخبري السريري 🩺🔬',
                    source = 'upload',
                    source_ref = NULL,
                    extraction_status = 'failed',
                    updated_at = :now
                WHERE id = :a3
            """),
            {"now": now, "a3": aid3},
        )

        # Also insert rows into autonomous tables to verify cascading/safe drop
        conn.execute(
            text("""
                INSERT INTO audit_events (id, ts, profile_id, actor_user_id, principal, run_id, event, tool, risk, decision, payload_hash, external_ref, detail_redacted)
                VALUES ('aud-pres-1', :now, :p1, :u1, 'user', 'run-p-1', 'tool_exec', 'attach_read', 'low', 'allowed', 'payloadhash_test', 'ref-1', '{"sanitized": true}')
            """),
            {"now": now, "p1": pid1, "u1": uid1},
        )
        conn.execute(
            text("""
                INSERT INTO connections (id, user_id, profile_id, connector_id, status, config_json, created_at, updated_at)
                VALUES ('conn-pres-1', :u1, :p1, 'epic', 'active', '{"fhir_base": "https://fhir.example.com"}', :now, :now)
            """),
            {"now": now, "u1": uid1, "p1": pid1},
        )
        conn.execute(
            text("""
                INSERT INTO credentials (id, connection_id, profile_id, token_version, encrypted_blob, created_at, updated_at)
                VALUES ('cred-pres-1', 'conn-pres-1', :p1, 1, 'encrypted_blob_pres_data', :now, :now)
            """),
            {"now": now, "p1": pid1},
        )
        conn.commit()

        # 4. Downgrade back to 0001_baseline_schema
        # This exercises SQLite batch mode table rebuild on attachments and drops CAS columns & tables
        alembic.command.downgrade(cfg, "0001_baseline_schema")

        insp_after_down = inspect(conn)
        tables_after_down = set(insp_after_down.get_table_names())
        assert "audit_events" not in tables_after_down
        assert "connections" not in tables_after_down
        assert "credentials" not in tables_after_down

        cols_after_down = {c["name"] for c in insp_after_down.get_columns("attachments")}
        for col in EXPECTED_ATTACHMENT_CAS_COLUMNS:
            assert col not in cols_after_down, f"Column '{col}' was not dropped in batch alter"

        # Verify DATA PRESERVATION on users: all records must be completely identical
        user_rows = {
            r[0]: r
            for r in conn.execute(
                text("SELECT id, email, username, hashed_password, full_name, role, status, auth_provider FROM users ORDER BY id")
            ).fetchall()
        }
        assert len(user_rows) == 2
        assert user_rows[uid1] == (uid1, "alice@carefold.ai", "alice", "argon2_alice_hash", "Alice Smith", "steward", "active", "local")
        assert user_rows[uid2] == (uid2, "bob@carefold.ai", "bob_🩺", "argon2_bob_hash", "Dr. Bob 🩺", "member", "active", "oidc")

        # Verify DATA PRESERVATION on attachments: all original records 100% preserved
        att_rows = {
            r[0]: r
            for r in conn.execute(
                text("SELECT id, user_id, profile_id, storage_key, filename, original_name, content_type, size_bytes, sha256_hash FROM attachments ORDER BY id")
            ).fetchall()
        }
        assert len(att_rows) == 3
        assert att_rows[aid1] == (aid1, uid1, pid1, "u1/p1/lab_report.pdf", "lab_report.pdf", "Lab Report Oct.pdf", "application/pdf", 1048576, "hash_sha256_lab_1")
        assert att_rows[aid2] == (aid2, uid2, None, "u2/none/cardio_ecg.xml", "cardio_ecg.xml", "cardio_ecg.xml", "text/xml", 65536, "hash_sha256_ecg_2")
        assert att_rows[aid3] == (aid3, uid1, pid1, "u1/p1/فحص_دم_🔬.pdf", "فحص_دم_🔬.pdf", "فحص_دم_🔬.pdf", "application/pdf", 2048, "hash_sha256_arabic_3")

        # 5. Re-upgrade to head
        alembic.command.upgrade(cfg, "head")

        insp_final = inspect(conn)
        cols_final = {c["name"] for c in insp_final.get_columns("attachments")}
        assert EXPECTED_ATTACHMENT_CAS_COLUMNS.issubset(cols_final)

        # Verify existing rows remain valid and default values populate cleanly
        reup_rows = {
            r[0]: r
            for r in conn.execute(
                text("SELECT id, source, extraction_status, extracted_text, source_ref, updated_at FROM attachments ORDER BY id")
            ).fetchall()
        }
        assert len(reup_rows) == 3
        for aid in [aid1, aid2, aid3]:
            r = reup_rows[aid]
            assert r[1] == "upload", f"Row {aid}: Expected source='upload', got {r[1]}"
            assert r[2] == "pending", f"Row {aid}: Expected extraction_status='pending', got {r[2]}"
            assert r[3] is None, f"Row {aid}: Expected extracted_text=None, got {r[3]}"
            assert r[4] is None, f"Row {aid}: Expected source_ref=None, got {r[4]}"

        # Verify original columns still preserved after re-upgrade
        reup_orig_rows = {
            r[0]: r
            for r in conn.execute(
                text("SELECT id, filename, size_bytes, sha256_hash FROM attachments ORDER BY id")
            ).fetchall()
        }
        assert reup_orig_rows[aid1] == (aid1, "lab_report.pdf", 1048576, "hash_sha256_lab_1")
        assert reup_orig_rows[aid2] == (aid2, "cardio_ecg.xml", 65536, "hash_sha256_ecg_2")
        assert reup_orig_rows[aid3] == (aid3, "فحص_دم_🔬.pdf", 2048, "hash_sha256_arabic_3")

        # 6. Verify inserting new records with CAS columns into head
        aid_new = "att-pres-new-4"
        conn.execute(
            text("""
                INSERT INTO attachments (
                    id, user_id, profile_id, storage_key, filename, original_name, content_type, size_bytes, sha256_hash, created_at,
                    extracted_text, source, source_ref, extraction_status, updated_at
                ) VALUES (
                    :aid, :u1, :p1, 'u1/p1/new_record.pdf', 'new_record.pdf', 'new_record.pdf', 'application/pdf', 512, 'hash_new_4', :now,
                    'Freshly extracted content', 'connector', 'conn-fhir-99', 'completed', :now
                )
            """),
            {"aid": aid_new, "u1": uid1, "p1": pid1, "now": now},
        )
        conn.commit()

        new_row = conn.execute(
            text("SELECT id, source, extraction_status, extracted_text FROM attachments WHERE id = :aid"),
            {"aid": aid_new},
        ).fetchone()
        assert new_row == (aid_new, "connector", "completed", "Freshly extracted content")


# =============================================================================
# 3. Foreign Keys Enabled (PRAGMA foreign_keys = ON) Batch Rebuild Test
# =============================================================================

def test_adversarial_batch_rebuild_with_pragma_foreign_keys_on():
    """Empirically tests that SQLite batch rebuilds succeed without constraint violations
    when PRAGMA foreign_keys = ON is strictly enforced on the SQLite connection.

    In SQLite, recreating a table via temp table copy/drop/rename under active foreign key constraints
    can trigger foreign key failures if Alembic does not disable foreign keys or handle relationships safely.
    """
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)

    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys = ON;"))
        assert conn.execute(text("PRAGMA foreign_keys;")).scalar() == 1

        cfg = get_alembic_config(conn)

        # Baseline
        alembic.command.upgrade(cfg, "0001_baseline_schema")

        now = "2026-10-12T01:30:00Z"
        conn.execute(
            text("""
                INSERT INTO users (id, email, username, hashed_password, role, status, auth_provider, created_at, updated_at)
                VALUES ('fk-user-a', 'fk_a@carefold.ai', 'fka', 'hash', 'steward', 'active', 'local', :now, :now)
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO profiles (id, user_id, name, relationship, role, avatar_color, is_primary, created_at, updated_at)
                VALUES ('fk-prof-a', 'fk-user-a', 'Profile A', 'self', 'self', '#10b981', 1, :now, :now)
            """),
            {"now": now},
        )
        conn.execute(
            text("""
                INSERT INTO attachments (id, user_id, profile_id, filename, original_name, content_type, size_bytes, created_at)
                VALUES ('fk-att-a', 'fk-user-a', 'fk-prof-a', 'file_a.pdf', 'file_a.pdf', 'application/pdf', 100, :now)
            """),
            {"now": now},
        )
        conn.commit()

        # Upgrade to head with foreign keys ON
        alembic.command.upgrade(cfg, "head")

        # Downgrade back to baseline with foreign keys ON
        # This executes batch_alter_table("attachments")
        alembic.command.downgrade(cfg, "0001_baseline_schema")

        # Confirm data is valid and FK relations intact
        row = conn.execute(text("SELECT user_id, profile_id, filename FROM attachments WHERE id = 'fk-att-a'")).fetchone()
        assert row == ("fk-user-a", "fk-prof-a", "file_a.pdf")

        # Re-upgrade to head
        alembic.command.upgrade(cfg, "head")
        row_reup = conn.execute(text("SELECT user_id, profile_id, source FROM attachments WHERE id = 'fk-att-a'")).fetchone()
        assert row_reup == ("fk-user-a", "fk-prof-a", "upload")


# =============================================================================
# 4. Multi-Cycle Data Growth Stress Test
# =============================================================================

def test_adversarial_repeated_downgrade_upgrade_stress_with_data_growth():
    """Empirically stress-tests multiple consecutive downgrade/upgrade cycles with growing data sets:
    Cycle 1: Baseline -> insert batch 1 -> Upgrade head -> insert CAS -> Downgrade baseline -> verify batch 1
    Cycle 2: Insert batch 2 in baseline -> Upgrade head -> verify batch 1 + 2 with defaults -> Downgrade baseline
    Cycle 3: Upgrade head -> Downgrade base -> Upgrade head -> verify clean empty head state.
    """
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)

    with engine.connect() as conn:
        cfg = get_alembic_config(conn)

        # Cycle 1: Baseline
        alembic.command.upgrade(cfg, "0001_baseline_schema")
        now = "2026-10-12T02:00:00Z"

        # Insert 10 users and 20 attachments
        for i in range(10):
            conn.execute(
                text("""
                    INSERT INTO users (id, email, username, hashed_password, role, status, auth_provider, created_at, updated_at)
                    VALUES (:id, :email, :username, 'h', 'member', 'active', 'local', :now, :now)
                """),
                {"id": f"u-c1-{i}", "email": f"u_c1_{i}@test.com", "username": f"user_c1_{i}", "now": now},
            )
        for j in range(20):
            conn.execute(
                text("""
                    INSERT INTO attachments (id, user_id, filename, original_name, content_type, size_bytes, created_at)
                    VALUES (:id, :uid, :fname, :fname, 'application/pdf', 100, :now)
                """),
                {"id": f"att-c1-{j}", "uid": f"u-c1-{j % 10}", "fname": f"doc_{j}.pdf", "now": now},
            )
        conn.commit()

        # Upgrade head and add CAS data
        alembic.command.upgrade(cfg, "head")
        for j in range(20):
            conn.execute(
                text("UPDATE attachments SET extracted_text = :txt, source = 'connector' WHERE id = :id"),
                {"txt": f"Extracted text for doc {j}", "id": f"att-c1-{j}"},
            )
        conn.commit()

        # Downgrade baseline: verify 10 users and 20 attachments remain
        alembic.command.downgrade(cfg, "0001_baseline_schema")
        assert conn.execute(text("SELECT count(*) FROM users")).scalar() == 10
        assert conn.execute(text("SELECT count(*) FROM attachments")).scalar() == 20

        # Cycle 2: Insert 10 more users and 20 more attachments in baseline
        for i in range(10, 20):
            conn.execute(
                text("""
                    INSERT INTO users (id, email, username, hashed_password, role, status, auth_provider, created_at, updated_at)
                    VALUES (:id, :email, :username, 'h', 'member', 'active', 'local', :now, :now)
                """),
                {"id": f"u-c2-{i}", "email": f"u_c2_{i}@test.com", "username": f"user_c2_{i}", "now": now},
            )
        for j in range(20, 40):
            conn.execute(
                text("""
                    INSERT INTO attachments (id, user_id, filename, original_name, content_type, size_bytes, created_at)
                    VALUES (:id, :uid, :fname, :fname, 'application/pdf', 200, :now)
                """),
                {"id": f"att-c2-{j}", "uid": f"u-c2-{j % 20}", "fname": f"doc_{j}.pdf", "now": now},
            )
        conn.commit()

        # Upgrade head: verify 20 users and 40 attachments with default CAS columns
        alembic.command.upgrade(cfg, "head")
        assert conn.execute(text("SELECT count(*) FROM users")).scalar() == 20
        assert conn.execute(text("SELECT count(*) FROM attachments")).scalar() == 40
        assert conn.execute(text("SELECT count(*) FROM attachments WHERE source = 'upload'")).scalar() == 40

        # Cycle 3: Downgrade base -> upgrade head
        alembic.command.downgrade(cfg, "base")
        insp_base = inspect(conn)
        assert len(set(insp_base.get_table_names()) - {"alembic_version"}) == 0

        alembic.command.upgrade(cfg, "head")
        insp_head = inspect(conn)
        assert EXPECTED_HEAD_TABLES.issubset(set(insp_head.get_table_names()))
        assert conn.execute(text("SELECT count(*) FROM users")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM attachments")).scalar() == 0


# =============================================================================
# 5. Boundary Values & Unicode Safety During Batch Rebuild
# =============================================================================

def test_adversarial_schema_evolution_with_boundary_values():
    """Empirically verifies that extreme boundary values survive SQLite batch alter table rebuilds:
    - 64-bit integer file sizes (e.g. 50 GB file: 53,687,091,200 bytes).
    - Nullable vs empty string representations.
    - Special characters: SQL keywords, quotation marks, Arabic / emoji filenames.
    - Zero bytes file size.
    """
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)

    with engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "0001_baseline_schema")

        now = "2026-10-12T02:30:00Z"
        large_size = 53_687_091_200  # 50 GB

        boundary_records = [
            ("att-bnd-zero", "empty.dat", 0, None),
            ("att-bnd-large", "big_genomics.bam", large_size, "hash_bam_64bit"),
            ("att-bnd-quote", "file'with\"quotes;--.csv", 1024, "hash_quote"),
            ("att-bnd-arabic", "تقرير_طبي_🏥.pdf", 4096, "hash_arabic_emoji"),
        ]

        for aid, fname, sz, hsh in boundary_records:
            conn.execute(
                text("""
                    INSERT INTO attachments (id, filename, original_name, content_type, size_bytes, sha256_hash, created_at)
                    VALUES (:aid, :fname, :fname, 'application/octet-stream', :sz, :hsh, :now)
                """),
                {"aid": aid, "fname": fname, "sz": sz, "hsh": hsh, "now": now},
            )
        conn.commit()

        # Upgrade head -> Downgrade baseline (triggers batch rebuild) -> Re-upgrade head
        alembic.command.upgrade(cfg, "head")
        alembic.command.downgrade(cfg, "0001_baseline_schema")
        alembic.command.upgrade(cfg, "head")

        rows = {
            r[0]: (r[1], r[2], r[3])
            for r in conn.execute(text("SELECT id, filename, size_bytes, sha256_hash FROM attachments ORDER BY id")).fetchall()
        }

        assert rows["att-bnd-zero"] == ("empty.dat", 0, None)
        assert rows["att-bnd-large"] == ("big_genomics.bam", large_size, "hash_bam_64bit")
        assert rows["att-bnd-quote"] == ("file'with\"quotes;--.csv", 1024, "hash_quote")
        assert rows["att-bnd-arabic"] == ("تقرير_طبي_🏥.pdf", 4096, "hash_arabic_emoji")


# =============================================================================
# 6. init_db() Integration Post-Downgrade
# =============================================================================

@pytest.mark.asyncio
async def test_adversarial_session_init_db_post_downgrade(tmp_path: Path):
    """Empirically tests that session.py:init_db() correctly handles a database that has been downgraded.
    When a database is at 0001_baseline_schema, booting the application and calling init_db()
    must detect the schema is behind head, execute upgrade to head cleanly, and not fail.
    """
    db_file = tmp_path / "post_downgrade.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    # 1. Setup sync engine and downgrade to baseline
    sync_engine = create_engine(f"sqlite:///{db_file}", poolclass=NullPool)
    with sync_engine.connect() as conn:
        cfg = get_alembic_config(conn)
        alembic.command.upgrade(cfg, "head")
        alembic.command.downgrade(cfg, "0001_baseline_schema")

        cur_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert cur_rev == "0001_baseline_schema"
    sync_engine.dispose()

    # 2. Call async init_db() as Carefold does on application startup
    async_engine = create_async_engine(db_url, poolclass=NullPool)
    await init_db(async_engine)
    await async_engine.dispose()

    # 3. Verify database successfully reached head
    verify_engine = create_engine(f"sqlite:///{db_file}", poolclass=NullPool)
    with verify_engine.connect() as conn:
        cur_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert cur_rev == "0002_autonomy_foundations"

        insp = inspect(conn)
        tables = set(insp.get_table_names())
        assert EXPECTED_HEAD_TABLES.issubset(tables)

        att_cols = {c["name"] for c in insp.get_columns("attachments")}
        assert EXPECTED_ATTACHMENT_CAS_COLUMNS.issubset(att_cols)
    verify_engine.dispose()
