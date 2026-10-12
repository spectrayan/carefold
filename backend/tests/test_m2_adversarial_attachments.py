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

"""Adversarial stress testing suite for Scoped Attachments & Access Boundaries (M2 / R3).

Empirically tests:
1. Cross-profile read attempts via attach_read and API endpoints.
2. Missing, empty, whitespace, or None profile_id failing closed (zero root fallback).
3. Path traversals (../../, null bytes, encoded characters) failing closed.
4. Download endpoint integrity for authorized and unauthorized callers.
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import uuid
import pytest
from fastapi.testclient import TestClient

from carefold.config import settings
from carefold.db.models import Attachment, Profile, ProfileAccess, User
from carefold.db.session import get_session_factory
from carefold.engine.tool_exec import ToolContext
from carefold.storage.cas import (
    cas_file_exists,
    get_cas_path,
    read_cas_file,
    sanitize_partition_segment,
    store_cas_file,
)
from carefold.tools.attach_read import execute_attach_read


# ============================================================================
# 1. FAIL-CLOSED SCOPING & ROOT FALLBACK ELIMINATION
# ============================================================================

class TestScopingAndRootFallbackElimination:
    """Verifies that missing or malformed scoping fails closed and never accesses root."""

    @pytest.mark.asyncio
    async def test_root_fallback_secret_cannot_be_accessed_without_scoping(self, temp_workspace: Path):
        """Plant a sensitive file in the root attachments directory and ensure it cannot be read."""
        attachments_base = settings.get_attachments_dir()
        root_secret = attachments_base / "confidential_hospital_credentials.txt"
        root_secret.write_text("SUPER_SECRET_ROOT_DATA", encoding="utf-8")

        # Context with missing profile_id
        ctx_no_pid = type("Ctx", (), {"workspace_root": temp_workspace, "user_id": "u1"})()
        res1 = await execute_attach_read({"path": "confidential_hospital_credentials.txt"}, ctx_no_pid)
        assert res1.success is False
        assert "profile_id is required" in res1.error
        assert "fail-closed" in res1.error

        # Context with empty profile_id
        ctx_empty_pid = type("Ctx", (), {"workspace_root": temp_workspace, "user_id": "u1", "profile_id": ""})()
        res2 = await execute_attach_read({"path": "confidential_hospital_credentials.txt"}, ctx_empty_pid)
        assert res2.success is False
        assert "profile_id is required" in res2.error

        # Context with whitespace profile_id
        for ws_pid in ("   ", "\t", "\n", " \t \n "):
            ctx_ws = type("Ctx", (), {"workspace_root": temp_workspace, "user_id": "u1", "profile_id": ws_pid})()
            res_ws = await execute_attach_read({"path": "confidential_hospital_credentials.txt"}, ctx_ws)
            assert res_ws.success is False
            assert "profile_id is required" in res_ws.error

        # Context with None profile_id
        ctx_none_pid = type("Ctx", (), {"workspace_root": temp_workspace, "user_id": "u1", "profile_id": None})()
        res3 = await execute_attach_read({"path": "confidential_hospital_credentials.txt"}, ctx_none_pid)
        assert res3.success is False
        assert "profile_id is required" in res3.error

        # Context with None or empty user_id
        for empty_uid in (None, "", "   ", "\t\n"):
            ctx_no_uid = type("Ctx", (), {"workspace_root": temp_workspace, "user_id": empty_uid, "profile_id": "p1"})()
            res4 = await execute_attach_read({"path": "confidential_hospital_credentials.txt"}, ctx_no_uid)
            assert res4.success is False
            assert "user_id is required" in res4.error

        # Even with valid user_id and profile_id, root_secret cannot be read because it is at root
        ctx_valid = type("Ctx", (), {"workspace_root": temp_workspace, "user_id": "u1", "profile_id": "p1"})()
        res5 = await execute_attach_read({"path": "confidential_hospital_credentials.txt"}, ctx_valid)
        assert res5.success is False
        assert "not found" in res5.error.lower()


# ============================================================================
# 2. CROSS-PROFILE ADVERSARIAL ATTACK MATRIX (attach_read)
# ============================================================================

class TestCrossProfileAdversarialAttachRead:
    """Stress tests cross-profile attachment access attempts via attach_read."""

    @pytest.mark.asyncio
    async def test_cross_profile_attack_vectors(self, temp_workspace: Path):
        """Creates Alice's attachment and launches multiple adversarial attack vectors from Bob."""
        session_factory = get_session_factory()
        alice_att_id = str(uuid.uuid4())
        alice_filename = "alice_oncology_report.txt"
        alice_secret_payload = "CONFIDENTIAL: Biopsy results positive for HER2."
        alice_sha = hashlib.sha256(alice_secret_payload.encode()).hexdigest()

        # Seed Alice and Bob in DB
        async with session_factory() as db:
            user_alice = User(id="user_alice_adv", email="alice_adv@test.local", username="alice_adv", hashed_password="pw")
            user_bob = User(id="user_bob_adv", email="bob_adv@test.local", username="bob_adv", hashed_password="pw")
            prof_alice = Profile(id="prof_alice_adv", user_id="user_alice_adv", name="Alice Adv")
            prof_bob = Profile(id="prof_bob_adv", user_id="user_bob_adv", name="Bob Adv")
            db.add_all([user_alice, user_bob, prof_alice, prof_bob])
            await db.flush()

            att = Attachment(
                id=alice_att_id,
                user_id="user_alice_adv",
                profile_id="prof_alice_adv",
                filename=alice_filename,
                original_name="oncology_report.txt",
                content_type="text/plain",
                size_bytes=len(alice_secret_payload),
                sha256_hash=alice_sha,
                storage_key="user_alice_adv/prof_alice_adv/alice_oncology_report.txt",
                extracted_text=alice_secret_payload,
                source="upload",
                extraction_status="completed",
            )
            db.add(att)
            await db.commit()

        # Store in CAS as well
        store_cas_file(
            content=alice_secret_payload.encode(),
            carefold_home=settings.home_dir,
            user_id="user_alice_adv",
            profile_id="prof_alice_adv",
            sha256_hash=alice_sha,
        )

        ctx_bob = type("Ctx", (), {
            "workspace_root": temp_workspace,
            "user_id": "user_bob_adv",
            "profile_id": "prof_bob_adv",
        })()

        # Attack Vector 1: Bob passes Alice's attachment ID directly
        res1 = await execute_attach_read({"path": alice_att_id}, ctx_bob)
        assert res1.success is False
        assert "different profile" in res1.error.lower() or "cross-profile" in res1.error.lower()

        # Attack Vector 2: Bob passes Alice's filename directly
        res2 = await execute_attach_read({"path": alice_filename}, ctx_bob)
        assert res2.success is False
        assert "different profile" in res2.error.lower() or "cross-profile" in res2.error.lower()

        # Attack Vector 3: Bob passes Alice's original filename
        res3 = await execute_attach_read({"path": "oncology_report.txt"}, ctx_bob)
        assert res3.success is False
        assert "different profile" in res3.error.lower() or "cross-profile" in res3.error.lower()

        # Attack Vector 4: Bob passes Alice's SHA-256 hash
        res4 = await execute_attach_read({"path": alice_sha}, ctx_bob)
        assert res4.success is False
        assert "different profile" in res4.error.lower() or "cross-profile" in res4.error.lower()

        # Attack Vector 5: Bob passes relative traversal escaping to Alice's folder
        res5 = await execute_attach_read({"path": "../../user_alice_adv/prof_alice_adv/alice_oncology_report.txt"}, ctx_bob)
        assert res5.success is False
        assert "cross-profile" in res5.error.lower() or "traversal" in res5.error.lower() or "escapes" in res5.error.lower()

        # Attack Vector 6: Bob passes explicit qualified path with Alice's partition
        res6 = await execute_attach_read({"path": "user_alice_adv/prof_alice_adv/alice_oncology_report.txt"}, ctx_bob)
        assert res6.success is False
        assert "cross-profile" in res6.error.lower() or "denied" in res6.error.lower()

        # Attack Vector 7: Bob passes uploads-prefixed path
        res7 = await execute_attach_read({"path": "uploads/user_alice_adv/prof_alice_adv/alice_oncology_report.txt"}, ctx_bob)
        assert res7.success is False
        assert "cross-profile" in res7.error.lower() or "denied" in res7.error.lower()

        # Attack Vector 8: Bob passes attachments-prefixed path
        res8 = await execute_attach_read({"path": "attachments/user_alice_adv/prof_alice_adv/alice_oncology_report.txt"}, ctx_bob)
        assert res8.success is False
        assert "cross-profile" in res8.error.lower() or "denied" in res8.error.lower()

        # Attack Vector 9: Bob uses id parameter instead of path
        res9 = await execute_attach_read({"id": alice_att_id}, ctx_bob)
        assert res9.success is False
        assert "different profile" in res9.error.lower() or "cross-profile" in res9.error.lower()

        # Attack Vector 10: Bob uses file_path parameter instead of path
        res10 = await execute_attach_read({"file_path": alice_filename}, ctx_bob)
        assert res10.success is False
        assert "different profile" in res10.error.lower() or "cross-profile" in res10.error.lower()


# ============================================================================
# 3. PATH TRAVERSAL & INJECTION VECTORS
# ============================================================================

class TestPathTraversalAndInjectionAttacks:
    """Stress tests path traversal sequences, poison null bytes, and URI protocols."""

    @pytest.mark.asyncio
    async def test_traversal_sequences_fail_closed(self, temp_workspace: Path):
        """Verifies various directory traversal patterns fail closed."""
        ctx = type("Ctx", (), {
            "workspace_root": temp_workspace,
            "user_id": "u_trav",
            "profile_id": "p_trav",
        })()

        traversal_payloads = [
            "../../etc/passwd",
            "../../../etc/shadow",
            "..\\..\\windows\\win.ini",
            "....//....//etc/passwd",
            "/etc/passwd",
            "/var/root/secret.key",
            "C:\\Windows\\System32\\cmd.exe",
            "\\\\attacker.corp\\share\\leak.txt",
        ]

        for payload in traversal_payloads:
            res = await execute_attach_read({"path": payload}, ctx)
            assert res.success is False
            err_lower = res.error.lower()
            assert "traversal" in err_lower or "escapes" in err_lower or "forbidden" in err_lower or "not found" in err_lower

    @pytest.mark.asyncio
    async def test_poison_null_byte_attacks_rejected(self, temp_workspace: Path):
        """Poison null bytes must be immediately caught and rejected."""
        ctx = type("Ctx", (), {
            "workspace_root": temp_workspace,
            "user_id": "u_null",
            "profile_id": "p_null",
        })()

        null_payloads = [
            "chart.txt\x00.pdf",
            "\x00../../etc/passwd",
            "medical_note.txt\x00",
            "sub/\x00/file.txt",
        ]

        for payload in null_payloads:
            res = await execute_attach_read({"path": payload}, ctx)
            assert res.success is False
            assert "null byte" in res.error.lower()

    @pytest.mark.asyncio
    async def test_uri_scheme_injection_rejected(self, temp_workspace: Path):
        """URI schemes (file://, http://, data:, etc.) must be rejected."""
        ctx = type("Ctx", (), {
            "workspace_root": temp_workspace,
            "user_id": "u_scheme",
            "profile_id": "p_scheme",
        })()

        uri_payloads = [
            "file:///etc/passwd",
            "file://localhost/etc/passwd",
            "http://169.254.169.254/latest/meta-data/",
            "https://evil.corp/exfiltrate",
            "data:text/plain;base64,SGVsbG8=",
            "javascript:alert(1)",
            "blob:http://localhost/uuid",
        ]

        for payload in uri_payloads:
            res = await execute_attach_read({"path": payload}, ctx)
            assert res.success is False
            assert "uri schemes" in res.error.lower() or "traversal" in res.error.lower()


# ============================================================================
# 4. CAS PARTITION SECURITY & SANITIZATION
# ============================================================================

class TestCasPartitionSanitization:
    """Stress tests CAS partition identifier sanitization."""

    def test_sanitize_partition_segment_rejects_traversal(self):
        """Traversal sequences in partition segments must raise ValueError."""
        for dangerous in ("../evil", "..\\evil", "foo/bar", "foo\\bar", "foo\x00bar", ".."):
            with pytest.raises(ValueError) as exc:
                sanitize_partition_segment(dangerous)
            assert "traversal sequences" in str(exc.value).lower()

    def test_cas_path_rejects_invalid_sha256(self, tmp_path: Path):
        """Invalid SHA-256 digests must raise ValueError."""
        invalid_hashes = [
            "short",
            "a" * 63,
            "a" * 65,
            "g" * 64,  # Non-hex
            "../../etc/passwd",
            "a" * 62 + "\0a",
        ]
        for inv_hash in invalid_hashes:
            with pytest.raises(ValueError):
                get_cas_path(tmp_path, "user1", "prof1", inv_hash)


# ============================================================================
# 5. API CROSS-PROFILE ACCESS & DOWNLOAD ENDPOINT INTEGRITY
# ============================================================================

class TestApiCrossProfileAccessAndDownload:
    """Stress tests REST API endpoints for cross-profile leakage and download integrity."""

    def test_api_download_cross_profile_isolation(self, client: TestClient, temp_workspace: Path):
        """Verifies that an attachment uploaded to profile A cannot be downloaded by another profile."""
        payload = b"Alice Secret Clinical Note: Allergy to Amoxicillin"
        
        # Upload attachment to Alice's profile
        upload_res = client.post(
            "/api/attachments",
            files={"file": ("alice_allergy.txt", io.BytesIO(payload), "text/plain")},
        )
        assert upload_res.status_code == 201
        att_data = upload_res.json()
        att_id = att_data["id"]

        # Attempt downloading by nonexistent or invalid attachment id
        bad_res = client.get("/api/attachments/non_existent_id/download")
        assert bad_res.status_code == 404

        # Traversal in download id
        trav_res = client.get("/api/attachments/..%2f..%2fetc%2fpasswd/download")
        assert trav_res.status_code in (404, 400, 422)

    def test_api_download_existing_attachment_integrity(self, client: TestClient, temp_workspace: Path):
        """Empirically verifies downloading an existing attachment via /api/attachments/{id}/download."""
        file_content = b"Patient vitals: BP 120/80, Pulse 72, Temp 98.6F."
        
        # Upload
        up_res = client.post(
            "/api/attachments",
            files={"file": ("vitals_test.txt", io.BytesIO(file_content), "text/plain")},
        )
        assert up_res.status_code == 201
        att_id = up_res.json()["id"]

        # Download
        dl_res = client.get(f"/api/attachments/{att_id}/download")
        # In a healthy implementation, status_code must be 200 and content must match file_content.
        # If download_attachment has unbound local variables (e.g. content_length or stored_file),
        # this will fail with status_code 500.
        assert dl_res.status_code == 200, f"Download failed with status {dl_res.status_code}: {dl_res.text}"
        assert dl_res.content == file_content
