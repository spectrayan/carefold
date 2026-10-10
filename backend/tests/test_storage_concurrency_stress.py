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

"""Storage Concurrency Stress Suite.

Verifies SQLite schema migrations, idempotent migrations, streaming download HTTP headers
and disconnect handling, profile access scoping, and cascading physical deletion.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
from pathlib import Path
import sqlite3
from typing import AsyncIterator, Dict
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.models import Attachment, Profile, ProfileAccess
from carefold.db.session import (
    _run_schema_migrations,
    create_db_engine,
    get_session_factory,
    init_db,
)
from carefold.main import app
from carefold.storage.factory import get_storage_adapter


# ============================================================================
# Helpers & Fixtures
# ============================================================================

def _register_user(client: TestClient, email: str, name: str) -> dict:
    username = email.split("@")[0].replace(".", "_")
    client.post(
        "/api/auth/register",
        json={"email": email, "username": username, "password": "Password123!", "full_name": name},
    )
    res = client.post(
        "/api/auth/login",
        json={"username": username, "password": "Password123!"},
    )
    data = res.json()
    token = data["token"]
    user_info = data["user"]
    return {"token": token, "user": user_info, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
async def multi_user_env(temp_workspace: Path, monkeypatch):
    """Sets up an isolated database and local SQL auth provider for multi-user tests."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    sql_auth = SqlAuthAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    monkeypatch.setattr(settings, "workspace_root", temp_workspace)
    set_auth_port(sql_auth)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    try:
        yield {"session_factory": session_factory, "auth": sql_auth, "engine": engine}
    finally:
        app.dependency_overrides.clear()
        reset_auth_port()
        await engine.dispose()


# ============================================================================
# 1. Schema Migration Evolution Tests
# ============================================================================

class TestSchemaMigrationEvolution:
    """Adversarial stress-testing of SQLite schema evolution from legacy schemas."""

    def test_legacy_db_with_only_file_path_column_migration(self, tmp_path: Path):
        """Stress-tests upgrading a legacy SQLite database having only 'file_path' and no 'filename'."""
        db_file = tmp_path / "legacy_filepath_only.db"

        with sqlite3.connect(str(db_file)) as conn:
            conn.execute("""
                CREATE TABLE attachments (
                    id VARCHAR(36) PRIMARY KEY,
                    file_path VARCHAR(255) NOT NULL,
                    user_id VARCHAR(36),
                    profile_id VARCHAR(36),
                    original_name VARCHAR(255),
                    content_type VARCHAR(128),
                    size_bytes INTEGER,
                    created_at DATETIME
                );
            """)
            conn.executemany("""
                INSERT INTO attachments (id, file_path, user_id, profile_id, original_name, content_type, size_bytes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, [
                ("att-1", "user-1/prof-1/doc1.pdf", "user-1", "prof-1", "doc1.pdf", "application/pdf", 1000, "2026-01-01"),
                ("att-2", "user-2/doc2.txt", "user-2", None, "doc2.txt", "text/plain", 200, "2026-01-01"),
                ("att-3", "unscoped_doc.txt", None, None, "unscoped_doc.txt", "text/plain", 50, "2026-01-01"),
            ])
            conn.commit()

        sync_engine = create_engine(f"sqlite:///{db_file.resolve()}")
        # Inspect behavior when _run_schema_migrations runs against this legacy table
        migration_failed = False
        failure_error = None
        with sync_engine.connect() as connection:
            try:
                _run_schema_migrations(connection)
                connection.commit()
            except Exception as exc:
                migration_failed = True
                failure_error = exc

        # Assert that migration succeeded cleanly without error on legacy table missing 'filename'
        assert not migration_failed, f"Migration failed on legacy table missing filename: {failure_error}"
        with sync_engine.connect() as connection:
            cols = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(attachments);").fetchall()]
            assert "storage_key" in cols
            assert "sha256_hash" in cols
            assert "filename" in cols
            rows = dict(connection.exec_driver_sql("SELECT id, storage_key FROM attachments;").fetchall())
            assert rows["att-1"] == "user-1/prof-1/doc1.pdf"
            assert rows["att-2"] == "user-2/doc2.txt"
            assert rows["att-3"] == "unscoped_doc.txt"

    def test_legacy_db_with_both_filename_and_file_path_backfill(self, tmp_path: Path):
        """Verifies schema upgrade and backfill when pre-existing legacy table has filename."""
        db_file = tmp_path / "legacy_both.db"

        with sqlite3.connect(str(db_file)) as conn:
            conn.execute("""
                CREATE TABLE attachments (
                    id VARCHAR(36) PRIMARY KEY,
                    filename VARCHAR(255) NOT NULL,
                    file_path VARCHAR(255),
                    user_id VARCHAR(36),
                    profile_id VARCHAR(36),
                    original_name VARCHAR(255),
                    content_type VARCHAR(128),
                    size_bytes INTEGER,
                    created_at DATETIME
                );
            """)
            conn.executemany("""
                INSERT INTO attachments (id, filename, file_path, user_id, profile_id, original_name, content_type, size_bytes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, [
                ("att-1", "doc1.pdf", "user-1/prof-1/doc1.pdf", "user-1", "prof-1", "doc1.pdf", "application/pdf", 1000, "2026-01-01"),
                ("att-2", "doc2.txt", "user-2/doc2.txt", "user-2", None, "doc2.txt", "text/plain", 200, "2026-01-01"),
                ("att-3", "unscoped.txt", "unscoped.txt", None, None, "unscoped.txt", "text/plain", 50, "2026-01-01"),
                ("att-4", "prof_only.txt", "prof-4/prof_only.txt", None, "prof-4", "prof_only.txt", "text/plain", 80, "2026-01-01"),
            ])
            conn.commit()

        sync_engine = create_engine(f"sqlite:///{db_file.resolve()}")
        with sync_engine.connect() as connection:
            _run_schema_migrations(connection)

            cols = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(attachments);").fetchall()}
            assert "storage_key" in cols
            assert "sha256_hash" in cols

            indices = {row[1] for row in connection.exec_driver_sql("PRAGMA index_list(attachments);").fetchall()}
            assert "ix_attachments_storage_key" in indices
            assert "ix_attachments_sha256_hash" in indices

            rows = dict(connection.exec_driver_sql("SELECT id, storage_key FROM attachments;").fetchall())
            assert rows["att-1"] == "user-1/prof-1/doc1.pdf"
            assert rows["att-2"] == "user-2/doc2.txt"
            assert rows["att-3"] == "unscoped.txt"
            assert rows["att-4"] == "prof-4/prof_only.txt"


# ============================================================================
# 2. Idempotent Migrations Tests
# ============================================================================

class TestIdempotentMigrations:
    """Stress-tests repeated execution of _run_schema_migrations() on the same database."""

    def test_run_schema_migrations_multiple_times_sequentially(self, tmp_path: Path):
        """Runs _run_schema_migrations() 10 consecutive times and verifies stability."""
        db_file = tmp_path / "idempotent_stress.db"
        sync_engine = create_engine(f"sqlite:///{db_file.resolve()}")

        # Initialize base table
        with sync_engine.connect() as connection:
            connection.exec_driver_sql("""
                CREATE TABLE attachments (
                    id VARCHAR(36) PRIMARY KEY,
                    filename VARCHAR(255) NOT NULL,
                    user_id VARCHAR(36),
                    profile_id VARCHAR(36),
                    original_name VARCHAR(255),
                    content_type VARCHAR(128),
                    size_bytes INTEGER,
                    created_at DATETIME
                );
            """)
            connection.commit()

        # Execute migration 10 times consecutively
        for iteration in range(10):
            with sync_engine.connect() as connection:
                _run_schema_migrations(connection)
                connection.commit()

        # Verify columns were added exactly once
        with sync_engine.connect() as connection:
            table_info = connection.exec_driver_sql("PRAGMA table_info(attachments);").fetchall()
            col_names = [row[1] for row in table_info]
            assert col_names.count("storage_key") == 1, "Duplicate storage_key column detected!"
            assert col_names.count("sha256_hash") == 1, "Duplicate sha256_hash column detected!"

            # Verify index list has exactly one of each
            index_list = connection.exec_driver_sql("PRAGMA index_list(attachments);").fetchall()
            idx_names = [row[1] for row in index_list]
            assert idx_names.count("ix_attachments_storage_key") == 1
            assert idx_names.count("ix_attachments_sha256_hash") == 1


# ============================================================================
# 3. Streaming Download HTTP Headers & Disconnect Tests
# ============================================================================

class TestStreamingDownloadHeadersAndDisconnect:
    """Verifies RFC headers, content streaming, and disconnect behavior."""

    def test_streaming_download_http_headers_and_integrity(self, client: TestClient):
        """Verifies Content-Disposition, Content-Length, Content-Type, and ETag headers."""
        raw_payload = b"%PDF-1.4 Clinical Document Header and Payload Test Content 12345"
        expected_sha = hashlib.sha256(raw_payload).hexdigest()
        expected_len = len(raw_payload)

        # Upload
        up_res = client.post(
            "/api/attachments",
            files={"file": ("clinical_summary.pdf", io.BytesIO(raw_payload), "application/pdf")},
        )
        assert up_res.status_code == 201
        att_id = up_res.json()["id"]

        # Download
        dl_res = client.get(f"/api/attachments/{att_id}/download")
        assert dl_res.status_code == 200

        # Verify headers
        cd = dl_res.headers.get("content-disposition", "")
        assert cd == 'attachment; filename="clinical_summary.pdf"'

        cl = dl_res.headers.get("content-length")
        assert cl == str(expected_len)

        ct = dl_res.headers.get("content-type")
        assert ct == "application/pdf"

        etag = dl_res.headers.get("etag")
        assert etag == f'"{expected_sha}"'

        nosniff = dl_res.headers.get("x-content-type-options")
        assert nosniff == "nosniff"

        # Verify content bytes
        assert dl_res.content == raw_payload

    @pytest.mark.asyncio
    async def test_streaming_download_disconnect_clean_handling(self, client: TestClient):
        """Simulates client disconnect during streaming response to verify clean termination."""
        raw_payload = b"X" * 1024 * 1024  # 1 MB payload
        up_res = client.post(
            "/api/attachments",
            files={"file": ("stream_large.txt", io.BytesIO(raw_payload), "text/plain")},
        )
        att_id = up_res.json()["id"]

        # Call with streaming generator and early break (simulating client disconnect)
        with client.stream("GET", f"/api/attachments/{att_id}/download") as response:
            assert response.status_code == 200
            read_bytes = 0
            for chunk in response.iter_bytes(chunk_size=4096):
                read_bytes += len(chunk)
                if read_bytes >= 8192:
                    # Client aborts connection mid-stream
                    break

        # Connection should close cleanly without throwing unhandled server exceptions
        assert read_bytes >= 8192


# ============================================================================
# 4. Profile Access Scoping Tests
# ============================================================================

class TestProfileAccessScoping:
    """Verifies strict profile scoping on download and deletion endpoints."""

    def test_unauthorized_user_cannot_download_or_delete_profile_attachment(self, multi_user_env):
        """User Bob cannot download or delete an attachment belonging to Alice's profile."""
        with TestClient(app) as client:
            alice = _register_user(client, "alice@scope.local", "Alice")
            bob = _register_user(client, "bob@scope.local", "Bob")

            # Alice gets her profile
            alice_profiles = client.get("/api/profiles", headers=alice["headers"]).json()
            alice_prof_id = alice_profiles[0]["id"]

            # Alice uploads an attachment scoped to her profile
            content = b"Alice Confidential Health Data"
            up_res = client.post(
                f"/api/attachments?profile_id={alice_prof_id}",
                headers=alice["headers"],
                files={"file": ("alice_records.pdf", io.BytesIO(content), "application/pdf")},
            )
            assert up_res.status_code == 201
            att_id = up_res.json()["id"]

            # 1. Bob attempts to download Alice's attachment -> 403 Forbidden
            bob_dl_res = client.get(
                f"/api/attachments/{att_id}/download",
                headers=bob["headers"],
            )
            assert bob_dl_res.status_code == 403
            assert "access denied" in bob_dl_res.json()["detail"].lower()

            # 2. Bob attempts to delete Alice's attachment -> 403 Forbidden
            bob_del_res = client.delete(
                f"/api/attachments/{att_id}",
                headers=bob["headers"],
            )
            assert bob_del_res.status_code == 403
            assert "access denied" in bob_del_res.json()["detail"].lower()

            # 3. Bob attempts to list Alice's attachments -> 403 Forbidden
            bob_list_res = client.get(
                f"/api/attachments?profile_id={alice_prof_id}",
                headers=bob["headers"],
            )
            assert bob_list_res.status_code == 403

            # 4. Alice can download her own attachment -> 200 OK
            alice_dl_res = client.get(
                f"/api/attachments/{att_id}/download",
                headers=alice["headers"],
            )
            assert alice_dl_res.status_code == 200
            assert alice_dl_res.content == content

    def test_viewer_access_can_download_but_cannot_delete(self, multi_user_env):
        """User Charlie with 'view_clinical' access can download but cannot delete."""
        with TestClient(app) as client:
            alice = _register_user(client, "alice2@scope.local", "Alice")
            charlie = _register_user(client, "charlie@scope.local", "Charlie")

            alice_prof_id = client.get("/api/profiles", headers=alice["headers"]).json()[0]["id"]

            # Alice invites Charlie with 'viewer' role (view_clinical=True)
            invite_res = client.post(
                f"/api/profiles/{alice_prof_id}/invites",
                headers=alice["headers"],
                json={
                    "invitee_name": "Charlie",
                    "role": "viewer",
                    "view_clinical": True,
                    "view_paperwork": False,
                },
            )
            assert invite_res.status_code == 201
            invite_code = invite_res.json()["invite_code"]

            # Charlie accepts invite
            accept_res = client.post(
                "/api/profiles/invites/accept",
                headers=charlie["headers"],
                json={"invite_code": invite_code},
            )
            assert accept_res.status_code == 200

            # Alice uploads attachment
            content = b"Shared Clinical ECG Chart"
            up_res = client.post(
                f"/api/attachments?profile_id={alice_prof_id}",
                headers=alice["headers"],
                files={"file": ("ecg.pdf", io.BytesIO(content), "application/pdf")},
            )
            att_id = up_res.json()["id"]

            # Charlie downloads -> ALLOWED (200)
            charlie_dl = client.get(
                f"/api/attachments/{att_id}/download",
                headers=charlie["headers"],
            )
            assert charlie_dl.status_code == 200
            assert charlie_dl.content == content

            # Charlie deletes -> FORBIDDEN (403, manage permission required)
            charlie_del = client.delete(
                f"/api/attachments/{att_id}",
                headers=charlie["headers"],
            )
            assert charlie_del.status_code == 403
            assert "manage permissions required" in charlie_del.json()["detail"].lower()


# ============================================================================
# 5. Cascading Physical Deletion Tests
# ============================================================================

class TestCascadingPhysicalDeletion:
    """Verifies that DELETE /attachments/{id} removes both database row and storage files."""

    def test_cascading_physical_deletion_removes_db_and_disk_files(self, multi_user_env):
        """Verifies complete physical cleanup of file, sidecar, and DB row upon deletion."""
        with TestClient(app) as client:
            alice = _register_user(client, "alice3@scope.local", "Alice")
            alice_prof_id = client.get("/api/profiles", headers=alice["headers"]).json()[0]["id"]

            content = b"Physically Deletable Medical Scan Data"
            up_res = client.post(
                f"/api/attachments?profile_id={alice_prof_id}",
                headers=alice["headers"],
                files={"file": ("scan_to_purge.pdf", io.BytesIO(content), "application/pdf")},
            )
            assert up_res.status_code == 201
            data = up_res.json()
            att_id = data["id"]
            storage_key = data["storage_key"]
            filename = data["filename"]

            storage = get_storage_adapter()
            uploads_dir = storage.base_dir

            # Locate physical file
            user_id = alice["user"]["id"]
            phys_file = uploads_dir / user_id / alice_prof_id / filename
            sidecar_file = uploads_dir / user_id / alice_prof_id / f".{filename}.meta.json"

            assert phys_file.exists(), f"Physical file missing at {phys_file}"
            assert sidecar_file.exists(), f"Metadata sidecar missing at {sidecar_file}"

            # Verify DB record exists
            session_factory = multi_user_env["session_factory"]

            async def _check_db_exists():
                async with session_factory() as session:
                    res = await session.execute(select(Attachment).where(Attachment.id == att_id))
                    return res.scalar_one_or_none()

            record = asyncio.run(_check_db_exists())
            assert record is not None
            assert record.id == att_id

            # Call DELETE /api/attachments/{id}
            del_res = client.delete(
                f"/api/attachments/{att_id}",
                headers=alice["headers"],
            )
            assert del_res.status_code == 200
            assert del_res.json()["deleted"] is True

            # 1. Verify DB record was purged
            record_after = asyncio.run(_check_db_exists())
            assert record_after is None, "Database record was NOT purged after deletion!"

            # 2. Verify physical file was purged from disk
            assert not phys_file.exists(), f"Physical file was NOT purged from disk: {phys_file}"

            # 3. Verify sidecar metadata was purged from disk
            assert not sidecar_file.exists(), f"Sidecar file was NOT purged from disk: {sidecar_file}"

            # 4. Subsequent download returns 404
            dl_after = client.get(
                f"/api/attachments/{att_id}/download",
                headers=alice["headers"],
            )
            assert dl_after.status_code == 404
