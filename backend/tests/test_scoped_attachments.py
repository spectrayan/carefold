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

"""Comprehensive unit and integration test suite for Milestone 2.

Covers:
- AU-08 / AU-09: Scoped Attachments & Directory Traversal Remediation.
- Requirement R3: Fail-closed attach_read, CAS layout, Attachment model extensions,
  and profile-scoped resolution.
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from carefold.config import settings
from carefold.db.models import Attachment, Profile, ProfileAccess, User, utc_now
from carefold.db.session import get_session_factory
from carefold.engine.tool_exec import ToolContext
from carefold.schemas.manifest import AgentManifest
from carefold.storage.cas import (
    cas_file_exists,
    get_cas_path,
    read_cas_file,
    store_cas_file,
)
from carefold.tools.attach_read import execute_attach_read


# ============================================================================
# 1. FAIL-CLOSED ATTACH-READ TESTS
# ============================================================================

class TestAttachReadFailClosed:
    """Verifies that execute_attach_read fails closed whenever scoping is missing."""

    @pytest.mark.asyncio
    async def test_missing_profile_id_denies_execution(self, temp_workspace: Path):
        """Context without profile_id must be denied immediately (never falls back to root)."""
        ctx = type("Ctx", (), {"workspace_root": temp_workspace, "user_id": "user-123"})()
        result = await execute_attach_read({"path": "sample.txt"}, ctx)

        assert result.success is False
        assert "profile_id is required" in result.error
        assert "fail-closed" in result.error

    @pytest.mark.asyncio
    async def test_empty_or_whitespace_profile_id_denies_execution(self, temp_workspace: Path):
        """Context with empty or whitespace profile_id must fail closed."""
        for empty_pid in ("", "   ", "\t\n"):
            ctx = type("Ctx", (), {
                "workspace_root": temp_workspace,
                "user_id": "user-123",
                "profile_id": empty_pid,
            })()
            result = await execute_attach_read({"path": "sample.txt"}, ctx)
            assert result.success is False
            assert "profile_id is required" in result.error

    @pytest.mark.asyncio
    async def test_missing_user_id_denies_execution(self, temp_workspace: Path):
        """Context without user_id must be denied immediately."""
        ctx = type("Ctx", (), {"workspace_root": temp_workspace, "profile_id": "profile-456"})()
        result = await execute_attach_read({"path": "sample.txt"}, ctx)

        assert result.success is False
        assert "user_id is required" in result.error
        assert "fail-closed" in result.error

    @pytest.mark.asyncio
    async def test_tool_context_protocol_compliance(self, temp_workspace: Path):
        """Passing an immutable ToolContext instance is supported and fails closed if invalid."""
        with pytest.raises(ValueError) as exc_info:
            ToolContext(user_id="u1", profile_id="")
        assert "Fail-closed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_non_existent_file_in_scoped_dir_returns_error(self, temp_workspace: Path):
        """Valid context querying a non-existent file returns a clean not found error."""
        ctx = type("Ctx", (), {
            "workspace_root": temp_workspace,
            "user_id": "user-valid",
            "profile_id": "profile-valid",
        })()
        result = await execute_attach_read({"path": "non_existent.txt"}, ctx)

        assert result.success is False
        assert "not found" in result.error.lower()


# ============================================================================
# 2. CROSS-PROFILE ACCESS BLOCKING TESTS
# ============================================================================

class TestCrossProfileAccessBlocking:
    """Verifies that cross-profile attachment access is strictly blocked."""

    @pytest.mark.asyncio
    async def test_cross_profile_attach_read_blocked(self, temp_workspace: Path):
        """Bob attempting to read Alice's attachment by filename or ID is rejected."""
        session_factory = get_session_factory()
        alice_att_id = str(uuid.uuid4())
        alice_filename = "alice_private_chart.txt"
        alice_sha = hashlib.sha256(b"Alice Private Health Data").hexdigest()

        # Insert Alice's attachment record in the DB
        async with session_factory() as db:
            user_alice = User(id="user_alice", email="alice@test.local", username="alice", hashed_password="dummy")
            user_bob = User(id="user_bob", email="bob@test.local", username="bob", hashed_password="dummy")
            prof_alice = Profile(id="profile_alice", user_id="user_alice", name="Alice Profile")
            prof_bob = Profile(id="profile_bob", user_id="user_bob", name="Bob Profile")
            db.add_all([user_alice, user_bob, prof_alice, prof_bob])
            await db.flush()

            att = Attachment(
                id=alice_att_id,
                user_id="user_alice",
                profile_id="profile_alice",
                filename=alice_filename,
                original_name="private_chart.txt",
                content_type="text/plain",
                size_bytes=24,
                sha256_hash=alice_sha,
                storage_key=f"user_alice/profile_alice/{alice_filename}",
                extracted_text="Alice Private Health Data",
                source="upload",
                extraction_status="completed",
            )
            db.add(att)
            await db.commit()

        # Bob context
        ctx_bob = type("Ctx", (), {
            "workspace_root": temp_workspace,
            "user_id": "user_bob",
            "profile_id": "profile_bob",
        })()

        # 1. Bob queries by Alice's attachment ID
        res_id = await execute_attach_read({"path": alice_att_id}, ctx_bob)
        assert res_id.success is False
        assert "different profile" in res_id.error.lower() or "cross-profile" in res_id.error.lower() or "access denied" in res_id.error.lower()

        # 2. Bob queries by Alice's filename
        res_name = await execute_attach_read({"path": alice_filename}, ctx_bob)
        assert res_name.success is False
        assert "different profile" in res_name.error.lower() or "cross-profile" in res_name.error.lower() or "access denied" in res_name.error.lower()

    @pytest.mark.asyncio
    async def test_cross_profile_path_traversal_blocked(self, temp_workspace: Path):
        """Relative path traversal escaping Bob's partition is blocked by sandbox security."""
        ctx_bob = type("Ctx", (), {
            "workspace_root": temp_workspace,
            "user_id": "user_bob",
            "profile_id": "profile_bob",
        })()

        # Traversal to Alice's profile
        res_trav = await execute_attach_read({"path": "../../user_alice/profile_alice/chart.txt"}, ctx_bob)
        assert res_trav.success is False
        assert "traversal" in res_trav.error.lower() or "escapes" in res_trav.error.lower()

    @pytest.mark.asyncio
    async def test_cross_profile_explicit_prefix_rejected(self, temp_workspace: Path):
        """Direct qualification of Alice's partition prefix is rejected."""
        ctx_bob = type("Ctx", (), {
            "workspace_root": temp_workspace,
            "user_id": "user_bob",
            "profile_id": "profile_bob",
        })()

        res = await execute_attach_read({"path": "user_alice/profile_alice/chart.txt"}, ctx_bob)
        assert res.success is False
        assert "cross-profile" in res.error.lower() or "denied" in res.error.lower() or "forbidden" in res.error.lower()


# ============================================================================
# 3. CONTENT-ADDRESSED STORAGE (CAS) LAYOUT TESTS
# ============================================================================

class TestContentAddressedStorage:
    """Verifies canonical path resolution, atomic writes, and deduplication in CAS."""

    def test_cas_path_canonical_structure(self, tmp_path: Path):
        """Verifies layout: <home>/data/files/<user_id>/<profile_id>/<sha256>."""
        user_id = "user-abc-123"
        profile_id = "prof-def-456"
        dummy_hash = "a" * 64

        cas_path = get_cas_path(tmp_path, user_id, profile_id, dummy_hash)
        expected = tmp_path / "data" / "files" / user_id / profile_id / dummy_hash

        assert cas_path == expected
        assert cas_path.name == dummy_hash
        assert cas_path.parent.name == profile_id
        assert cas_path.parent.parent.name == user_id

    def test_cas_store_and_deduplicate(self, tmp_path: Path):
        """Identical content stored in the same profile is deduplicated to the same file."""
        content = b"Content Addressed Storage Test Payload"
        user_id = "user-cas-1"
        profile_id = "prof-cas-1"
        expected_sha = hashlib.sha256(content).hexdigest()

        # First store
        path1, sha1, is_dedup1 = store_cas_file(content, tmp_path, user_id, profile_id)
        assert sha1 == expected_sha
        assert path1.is_file()
        assert path1.read_bytes() == content
        assert is_dedup1 is False

        # Second store with identical content
        path2, sha2, is_dedup2 = store_cas_file(content, tmp_path, user_id, profile_id)
        assert sha2 == expected_sha
        assert path1 == path2
        assert is_dedup2 is True
        assert cas_file_exists(tmp_path, user_id, profile_id, expected_sha)

    def test_cas_distinct_partitions_across_profiles(self, tmp_path: Path):
        """Identical content in different profiles creates distinct files in separate partitions."""
        content = b"Shared Clinical Guideline"
        expected_sha = hashlib.sha256(content).hexdigest()

        path_a, sha_a, _ = store_cas_file(content, tmp_path, "user-a", "prof-a")
        path_b, sha_b, _ = store_cas_file(content, tmp_path, "user-b", "prof-b")

        assert sha_a == sha_b == expected_sha
        assert path_a != path_b
        assert path_a.exists() and path_b.exists()
        assert "prof-a" in str(path_a)
        assert "prof-b" in str(path_b)

    def test_cas_partition_validation_blocks_traversal(self, tmp_path: Path):
        """Path traversal characters in user_id or profile_id are strictly rejected."""
        valid_sha = "f" * 64

        with pytest.raises(ValueError):
            get_cas_path(tmp_path, "../evil", "prof", valid_sha)

        with pytest.raises(ValueError):
            get_cas_path(tmp_path, "user", "../../evil", valid_sha)

        with pytest.raises(ValueError):
            get_cas_path(tmp_path, "user", "prof", "invalid_short_hash")

        with pytest.raises(ValueError):
            get_cas_path(tmp_path, "user", "prof", "g" * 64)  # Non-hex

    def test_cas_file_read_and_exists_lifecycle(self, tmp_path: Path):
        """Round-trip verification of store, exists, and read."""
        content = b"Medical History Report: Allergies to Penicillin"
        user_id = "user-lifecycle"
        profile_id = "prof-lifecycle"
        sha = hashlib.sha256(content).hexdigest()

        assert not cas_file_exists(tmp_path, user_id, profile_id, sha)
        with pytest.raises(FileNotFoundError):
            read_cas_file(tmp_path, user_id, profile_id, sha)

        store_cas_file(content, tmp_path, user_id, profile_id, sha)

        assert cas_file_exists(tmp_path, user_id, profile_id, sha)
        read_back = read_cas_file(tmp_path, user_id, profile_id, sha)
        assert read_back == content


# ============================================================================
# 4. ATTACHMENT MODEL EXTENSIONS & UNIFIED ALIASES TESTS
# ============================================================================

class TestAttachmentModelExtensions:
    """Verifies CAS fields and unified property aliases on Attachment model."""

    def test_attachment_model_cas_fields(self):
        """Attachment includes extracted_text, source, source_ref, extraction_status, updated_at."""
        att = Attachment(
            user_id="u1",
            profile_id="p1",
            filename="record.pdf",
            original_name="record.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            sha256_hash="e" * 64,
            extracted_text="Extracted text from PDF layer",
            source="connector",
            source_ref="stream_42",
            extraction_status="completed",
        )

        assert att.extracted_text == "Extracted text from PDF layer"
        assert att.source == "connector"
        assert att.source_ref == "stream_42"
        assert att.extraction_status == "completed"
        assert att.created_at is not None
        assert att.updated_at is not None

    def test_attachment_model_unified_aliases(self):
        """Attachment provides standard aliases: mime, size, sha256."""
        att = Attachment(
            user_id="u1",
            profile_id="p1",
            filename="test.txt",
            content_type="text/plain",
            size_bytes=512,
            sha256_hash="b" * 64,
        )

        # Getter aliases
        assert att.mime == "text/plain"
        assert att.size == 512
        assert att.sha256 == "b" * 64

        # Setter aliases
        att.mime = "text/markdown"
        assert att.content_type == "text/markdown"

        att.size = 2048
        assert att.size_bytes == 2048

        att.sha256 = "c" * 64
        assert att.sha256_hash == "c" * 64

    def test_attachment_model_kwargs_normalization(self):
        """Initializing Attachment with mime, size, or sha256 maps to columns properly."""
        att = Attachment(
            user_id="u1",
            profile_id="p1",
            filename="doc.pdf",
            mime="application/pdf",
            size=4096,
            sha256="d" * 64,
        )

        assert att.content_type == "application/pdf"
        assert att.size_bytes == 4096
        assert att.sha256_hash == "d" * 64


# ============================================================================
# 5. API INTEGRATION & CAS ENDPOINT TESTS
# ============================================================================

class TestApiScopedAttachmentsAndCas:
    """Verifies attachment endpoints integrate with CAS and enforce profile scoping."""

    def test_api_upload_stores_in_cas_and_extracts_text(self, client: TestClient, temp_workspace: Path):
        """Uploading via API stores file in CAS layout and populates extracted_text."""
        payload = b"CLINICAL NOTE\nPatient presented with acute migraines.\nPrescribed sumatriptan."
        expected_sha = hashlib.sha256(payload).hexdigest()

        response = client.post(
            "/api/attachments",
            files={"file": ("clinical_note.txt", io.BytesIO(payload), "text/plain")},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["sha256"] == expected_sha
        assert data["extracted_text"] == payload.decode("utf-8")

        # Verify physical file exists in CAS layout: <home>/data/files/<uid>/<pid>/<sha256>
        cas_file = get_cas_path(
            settings.home_dir,
            data.get("user_id"),
            data.get("profile_id"),
            expected_sha,
        )
        assert cas_file.is_file()
        assert cas_file.read_bytes() == payload

    @pytest.mark.asyncio
    async def test_attach_read_fast_paths_cached_extracted_text(self, temp_workspace: Path):
        """execute_attach_read returns cached extracted_text directly from DB record."""
        session_factory = get_session_factory()
        user_id = "user_fastpath"
        profile_id = "prof_fastpath"
        sha = hashlib.sha256(b"Cached Text Fastpath Content").hexdigest()
        att_id = str(uuid.uuid4())

        async with session_factory() as db:
            user = User(id=user_id, email="fastpath@test.local", username="fastpath", hashed_password="dummy")
            prof = Profile(id=profile_id, user_id=user_id, name="FastPath Profile")
            db.add_all([user, prof])
            await db.flush()

            att = Attachment(
                id=att_id,
                user_id=user_id,
                profile_id=profile_id,
                filename="fastpath_note.txt",
                original_name="fastpath_note.txt",
                content_type="text/plain",
                size_bytes=28,
                sha256_hash=sha,
                storage_key=f"{user_id}/{profile_id}/fastpath_note.txt",
                extracted_text="Cached Text Fastpath Content",
                source="upload",
                extraction_status="completed",
            )
            db.add(att)
            await db.commit()

        ctx = type("Ctx", (), {
            "workspace_root": temp_workspace,
            "user_id": user_id,
            "profile_id": profile_id,
        })()

        res = await execute_attach_read({"path": "fastpath_note.txt"}, ctx)
        assert res.success is True
        assert res.output["content"] == "Cached Text Fastpath Content"
        assert res.output["format"] == "text"

    def test_api_delete_attachment_cleans_up_cas(self, client: TestClient, temp_workspace: Path):
        """Deleting an attachment unlinks the CAS file and removes the DB record."""
        payload = b"Temporary Diagnostic Image or Note"
        res = client.post(
            "/api/attachments",
            files={"file": ("to_delete.txt", io.BytesIO(payload), "text/plain")},
        )
        assert res.status_code == 201
        data = res.json()
        att_id = data["id"]
        sha = data["sha256"]

        cas_file = get_cas_path(settings.home_dir, data.get("user_id"), data.get("profile_id"), sha)
        assert cas_file.is_file()

        # Delete attachment
        del_res = client.delete(f"/api/attachments/{att_id}")
        assert del_res.status_code == 200

        # Verify CAS file is unlinked and DB query returns 404
        assert not cas_file.is_file()
        get_res = client.get(f"/api/attachments/{att_id}/download")
        assert get_res.status_code == 404

    def test_api_download_existing_attachment_success(self, client: TestClient, temp_workspace: Path):
        """Verifies successful download of an active attachment stored in CAS."""
        import io
        payload = b"Sample diagnostic chart content for download verification"
        up = client.post(
            "/api/attachments",
            files={"file": ("chart.txt", io.BytesIO(payload), "text/plain")},
        )
        assert up.status_code == 201
        att_id = up.json()["id"]

        dl = client.get(f"/api/attachments/{att_id}/download")
        assert dl.status_code == 200
        assert dl.content == payload
        assert dl.headers["content-length"] == str(len(payload))
        assert "etag" in dl.headers
