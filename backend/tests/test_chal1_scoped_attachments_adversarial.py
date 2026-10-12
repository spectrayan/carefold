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

"""Adversarial Empirical Stress Testing Suite for Challenger 1 (m2_rem_chal1).

Empirically challenges Milestone 2 Remediation (Scoped Attachments & Access Boundaries, R3):
1. Cross-profile read attempts via attach_read and API endpoints are strictly rejected (cannot read attachments belonging to another profile).
2. Missing, empty "", whitespace, or None profile_id fails closed (never falls back to root directory).
3. Attempted path traversals (../../, null bytes \\x00, encoded slashes, Windows paths) fail closed and cannot escape sandbox.
4. Multiple profiles with the same attachment filename can access their own attachments independently without false cross-profile lockout.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import os
from pathlib import Path
import uuid
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select

from carefold.api.deps import get_current_user
from carefold.auth.ports import UserProfile
from carefold.config import settings
from carefold.db.models import Attachment, Profile, ProfileAccess, User, utc_now
from carefold.db.session import get_session_factory
from carefold.engine.tool_exec import ToolContext
from carefold.main import app
from carefold.storage.cas import (
    cas_file_exists,
    get_cas_path,
    read_cas_file,
    store_cas_file,
)
from carefold.tools.attach_read import execute_attach_read


# ============================================================================
# 1. CROSS-PROFILE READ ATTEMPTS STRICT REJECTION (attach_read & API)
# ============================================================================

class TestAdversarialCrossProfileAccessRejection:
    """Stress tests cross-profile attachment access attempts via attach_read and REST API."""

    @pytest.mark.asyncio
    async def test_cross_profile_attach_read_all_attack_vectors_rejected(self, temp_workspace: Path):
        """Alice owns an attachment. Bob launches a multitude of cross-profile read vectors."""
        session_factory = get_session_factory()
        alice_att_id = str(uuid.uuid4())
        alice_filename = "alice_private_biopsy.txt"
        alice_secret_payload = "BIOPSY_CONFIDENTIAL: Stage 2 Invasive Ductal Carcinoma. Grade 3."
        alice_sha = hashlib.sha256(alice_secret_payload.encode()).hexdigest()

        # Seed Alice and Bob in carefold.db
        async with session_factory() as db:
            user_alice = User(
                id="u_alice_adversary",
                email="alice_adv@test.local",
                username="alice_adv",
                hashed_password="pw",
            )
            user_bob = User(
                id="u_bob_adversary",
                email="bob_adv@test.local",
                username="bob_adv",
                hashed_password="pw",
            )
            prof_alice = Profile(
                id="p_alice_adversary",
                user_id="u_alice_adversary",
                name="Alice Adversary Profile",
            )
            prof_bob = Profile(
                id="p_bob_adversary",
                user_id="u_bob_adversary",
                name="Bob Adversary Profile",
            )
            db.add_all([user_alice, user_bob, prof_alice, prof_bob])
            await db.flush()

            att = Attachment(
                id=alice_att_id,
                user_id="u_alice_adversary",
                profile_id="p_alice_adversary",
                filename=alice_filename,
                original_name="biopsy_results.txt",
                content_type="text/plain",
                size_bytes=len(alice_secret_payload),
                sha256_hash=alice_sha,
                storage_key="u_alice_adversary/p_alice_adversary/alice_private_biopsy.txt",
                extracted_text=alice_secret_payload,
                source="upload",
                extraction_status="completed",
            )
            db.add(att)
            await db.commit()

        # Write physical CAS file for Alice
        store_cas_file(
            content=alice_secret_payload.encode(),
            carefold_home=settings.home_dir,
            user_id="u_alice_adversary",
            profile_id="p_alice_adversary",
            sha256_hash=alice_sha,
        )

        ctx_bob = type("BobContext", (), {
            "workspace_root": temp_workspace,
            "user_id": "u_bob_adversary",
            "profile_id": "p_bob_adversary",
        })()

        # Bob Attempt 1: Read by Alice's attachment UUID
        res1 = await execute_attach_read({"path": alice_att_id}, ctx_bob)
        assert res1.success is False, "Bob unexpectedly read Alice's attachment by UUID!"
        assert "cross-profile" in res1.error.lower() or "different profile" in res1.error.lower()

        # Bob Attempt 2: Read by Alice's stored filename
        res2 = await execute_attach_read({"path": alice_filename}, ctx_bob)
        assert res2.success is False, "Bob unexpectedly read Alice's attachment by filename!"
        assert "cross-profile" in res2.error.lower() or "different profile" in res2.error.lower()

        # Bob Attempt 3: Read by Alice's original filename
        res3 = await execute_attach_read({"path": "biopsy_results.txt"}, ctx_bob)
        assert res3.success is False, "Bob unexpectedly read Alice's attachment by original_name!"
        assert "cross-profile" in res3.error.lower() or "different profile" in res3.error.lower()

        # Bob Attempt 4: Read by Alice's SHA256 content hash
        res4 = await execute_attach_read({"path": alice_sha}, ctx_bob)
        assert res4.success is False, "Bob unexpectedly read Alice's attachment by SHA256 hash!"
        assert "cross-profile" in res4.error.lower() or "different profile" in res4.error.lower()

        # Bob Attempt 5: Read by Alice's storage_key
        res5 = await execute_attach_read(
            {"path": "u_alice_adversary/p_alice_adversary/alice_private_biopsy.txt"},
            ctx_bob,
        )
        assert res5.success is False, "Bob unexpectedly read Alice's attachment by storage_key!"
        assert "cross-profile" in res5.error.lower() or "denied" in res5.error.lower()

        # Bob Attempt 6: Relative traversal escaping Bob's directory into Alice's directory
        res6 = await execute_attach_read(
            {"path": "../../u_alice_adversary/p_alice_adversary/alice_private_biopsy.txt"},
            ctx_bob,
        )
        assert res6.success is False, "Bob escaped directory via ../../ to read Alice's file!"
        assert any(
            term in res6.error.lower()
            for term in ("cross-profile", "traversal", "escapes", "denied")
        )

        # Bob Attempt 7: Explicit uploads-prefixed path
        res7 = await execute_attach_read(
            {"path": "uploads/u_alice_adversary/p_alice_adversary/alice_private_biopsy.txt"},
            ctx_bob,
        )
        assert res7.success is False, "Bob read Alice's file via uploads/ prefix!"

        # Bob Attempt 8: Explicit attachments-prefixed path
        res8 = await execute_attach_read(
            {"path": "attachments/u_alice_adversary/p_alice_adversary/alice_private_biopsy.txt"},
            ctx_bob,
        )
        assert res8.success is False, "Bob read Alice's file via attachments/ prefix!"

        # Bob Attempt 9: Parameter variation "id"
        res9 = await execute_attach_read({"id": alice_att_id}, ctx_bob)
        assert res9.success is False, "Bob read Alice's file via 'id' parameter!"

        # Bob Attempt 10: Parameter variation "file_path"
        res10 = await execute_attach_read({"file_path": alice_filename}, ctx_bob)
        assert res10.success is False, "Bob read Alice's file via 'file_path' parameter!"

    def test_cross_profile_api_endpoints_strictly_rejected(self, client: TestClient, temp_workspace: Path):
        """Tests that unauthorized user cannot access another profile's attachments via REST API."""
        session_factory = get_session_factory()
        now = datetime.now(timezone.utc)
        alice_att_id = str(uuid.uuid4())
        alice_filename = "alice_api_secret.txt"
        secret_bytes = b"SECRET_API_RECORD: HIV Viral Load undetectable."
        sha = hashlib.sha256(secret_bytes).hexdigest()

        # Create Alice and Bob users
        user_alice = UserProfile(
            id="u_alice_api",
            email="alice_api@carefold.test",
            username="alice_api",
            role="member",
            status="active",
            created_at=now,
            updated_at=now,
        )
        user_bob = UserProfile(
            id="u_bob_api",
            email="bob_api@carefold.test",
            username="bob_api",
            role="member",
            status="active",
            created_at=now,
            updated_at=now,
        )

        # Store in CAS and DB
        store_cas_file(
            content=secret_bytes,
            carefold_home=settings.home_dir,
            user_id="u_alice_api",
            profile_id="p_alice_api",
            sha256_hash=sha,
        )

        import asyncio
        async def seed():
            async with session_factory() as db:
                db.add(User(id="u_alice_api", email="alice_api@carefold.test", username="alice_api", hashed_password="pw"))
                db.add(User(id="u_bob_api", email="bob_api@carefold.test", username="bob_api", hashed_password="pw"))
                db.add(Profile(id="p_alice_api", user_id="u_alice_api", name="Alice API Profile"))
                db.add(Profile(id="p_bob_api", user_id="u_bob_api", name="Bob API Profile"))
                await db.flush()

                db.add(Attachment(
                    id=alice_att_id,
                    user_id="u_alice_api",
                    profile_id="p_alice_api",
                    filename=alice_filename,
                    original_name="alice_api_secret.txt",
                    content_type="text/plain",
                    size_bytes=len(secret_bytes),
                    sha256_hash=sha,
                    storage_key="u_alice_api/p_alice_api/alice_api_secret.txt",
                    extracted_text=secret_bytes.decode(),
                    source="upload",
                    extraction_status="completed",
                ))
                await db.commit()
        asyncio.run(seed())

        # Test in multi-user mode
        old_auth = settings.auth_provider
        settings.auth_provider = "local"
        try:
            # Test as Bob (unauthorized caller)
            app.dependency_overrides[get_current_user] = lambda: user_bob
            try:
                # 1. Bob attempts GET /api/attachments?profile_id=p_alice_api
                res_list = client.get("/api/attachments?profile_id=p_alice_api")
                assert res_list.status_code == status.HTTP_403_FORBIDDEN, (
                    f"Expected 403 Forbidden for unauthorized profile list, got {res_list.status_code}"
                )

                # 2. Bob attempts GET /api/attachments/{alice_att_id}/download
                res_dl = client.get(f"/api/attachments/{alice_att_id}/download")
                assert res_dl.status_code == status.HTTP_403_FORBIDDEN, (
                    f"Expected 403 Forbidden for unauthorized download, got {res_dl.status_code}"
                )

                # 3. Bob attempts GET /api/attachments/{alice_att_id}/content
                res_cnt = client.get(f"/api/attachments/{alice_att_id}/content")
                assert res_cnt.status_code == status.HTTP_403_FORBIDDEN, (
                    f"Expected 403 Forbidden for unauthorized content, got {res_cnt.status_code}"
                )

                # 4. Bob attempts DELETE /api/attachments/{alice_att_id}
                res_del = client.delete(f"/api/attachments/{alice_att_id}")
                assert res_del.status_code == status.HTTP_403_FORBIDDEN, (
                    f"Expected 403 Forbidden for unauthorized delete, got {res_del.status_code}"
                )

                # 5. Bob lists unpartitioned /api/attachments in multi-user mode -> Alice's file must NOT appear
                res_all = client.get("/api/attachments")
                assert res_all.status_code == status.HTTP_200_OK
                returned_ids = [item["id"] for item in res_all.json()]
                assert alice_att_id not in returned_ids, "Alice's attachment leaked into Bob's multi-user list!"

            finally:
                app.dependency_overrides.pop(get_current_user, None)

            # Test as Alice (authorized caller)
            app.dependency_overrides[get_current_user] = lambda: user_alice
            try:
                # 1. Alice downloads her own file -> 200 OK
                res_ok = client.get(f"/api/attachments/{alice_att_id}/download")
                assert res_ok.status_code == status.HTTP_200_OK
                assert res_ok.content == secret_bytes
                assert res_ok.headers.get("content-length") == str(len(secret_bytes))
                assert sha in res_ok.headers.get("etag", "")

                # 2. Alice lists her profile -> 200 OK with her attachment
                res_alice_list = client.get("/api/attachments?profile_id=p_alice_api")
                assert res_alice_list.status_code == status.HTTP_200_OK
                ids = [x["id"] for x in res_alice_list.json()]
                assert alice_att_id in ids
            finally:
                app.dependency_overrides.pop(get_current_user, None)
        finally:
            settings.auth_provider = old_auth


# ============================================================================
# 2. FAIL-CLOSED SCOPING & ROOT FALLBACK ELIMINATION
# ============================================================================

class TestFailClosedScopingAndRootFallbackElimination:
    """Verifies that missing, empty, whitespace, or None profile_id fails closed and never falls back to root."""

    @pytest.mark.asyncio
    async def test_root_canary_cannot_be_read_under_any_circumstance(self, temp_workspace: Path):
        """Plant a root canary in attachments directory and verify all access forms fail closed."""
        attachments_base = settings.get_attachments_dir()
        root_canary = attachments_base / "canary_hospital_root_credentials.key"
        root_canary.write_text("SENSITIVE_ROOT_KEY_NEVER_LEAK", encoding="utf-8")

        uploads_base = settings.get_uploads_dir()
        uploads_canary = uploads_base / "canary_uploads_root_credentials.key"
        uploads_canary.write_text("SENSITIVE_UPLOADS_KEY_NEVER_LEAK", encoding="utf-8")

        # 1. Missing profile_id attribute
        ctx_no_pid = type("CtxNoPid", (), {"workspace_root": temp_workspace, "user_id": "u_test"})()
        r1 = await execute_attach_read({"path": "canary_hospital_root_credentials.key"}, ctx_no_pid)
        assert r1.success is False
        assert "profile_id is required" in r1.error
        assert "fail-closed" in r1.error

        # 2. Empty string profile_id
        ctx_empty_pid = type("CtxEmptyPid", (), {
            "workspace_root": temp_workspace,
            "user_id": "u_test",
            "profile_id": "",
        })()
        r2 = await execute_attach_read({"path": "canary_hospital_root_credentials.key"}, ctx_empty_pid)
        assert r2.success is False
        assert "profile_id is required" in r2.error

        # 3. Whitespace profile_id variations
        for ws in (" ", "   ", "\t", "\n", "\r\n", " \t \n "):
            ctx_ws = type("CtxWs", (), {
                "workspace_root": temp_workspace,
                "user_id": "u_test",
                "profile_id": ws,
            })()
            r_ws = await execute_attach_read({"path": "canary_hospital_root_credentials.key"}, ctx_ws)
            assert r_ws.success is False
            assert "profile_id is required" in r_ws.error

        # 4. None profile_id
        ctx_none_pid = type("CtxNonePid", (), {
            "workspace_root": temp_workspace,
            "user_id": "u_test",
            "profile_id": None,
        })()
        r3 = await execute_attach_read({"path": "canary_hospital_root_credentials.key"}, ctx_none_pid)
        assert r3.success is False
        assert "profile_id is required" in r3.error

        # 5. Missing user_id attribute
        ctx_no_uid = type("CtxNoUid", (), {
            "workspace_root": temp_workspace,
            "profile_id": "p_test",
        })()
        r4 = await execute_attach_read({"path": "canary_hospital_root_credentials.key"}, ctx_no_uid)
        assert r4.success is False
        assert "user_id is required" in r4.error
        assert "fail-closed" in r4.error

        # 6. Empty / whitespace / None user_id
        for bad_uid in ("", "   ", "\t\n", None):
            ctx_bad_uid = type("CtxBadUid", (), {
                "workspace_root": temp_workspace,
                "user_id": bad_uid,
                "profile_id": "p_test",
            })()
            r_uid = await execute_attach_read({"path": "canary_hospital_root_credentials.key"}, ctx_bad_uid)
            assert r_uid.success is False
            assert "user_id is required" in r_uid.error

        # 7. Valid user_id and profile_id attempting to read the root canaries
        # Must FAIL CLOSED (not found in scoped directory) and NEVER fall back to root
        ctx_valid = type("CtxValid", (), {
            "workspace_root": temp_workspace,
            "user_id": "u_legit_failclosed",
            "profile_id": "p_legit_failclosed",
        })()
        r_att = await execute_attach_read({"path": "canary_hospital_root_credentials.key"}, ctx_valid)
        assert r_att.success is False
        assert "not found" in r_att.error.lower()

        r_up = await execute_attach_read({"path": "canary_uploads_root_credentials.key"}, ctx_valid)
        assert r_up.success is False
        assert "not found" in r_up.error.lower()

    def test_tool_context_dataclass_fail_closed_invariants(self):
        """ToolContext dataclass must enforce non-empty user_id and profile_id upon construction."""
        # Missing or empty profile_id
        for bad_p in ("", "   ", "\t"):
            with pytest.raises(ValueError) as exc:
                ToolContext(user_id="u1", profile_id=bad_p)
            assert "Fail-closed" in str(exc.value)

        # Missing or empty user_id
        for bad_u in ("", "   ", "\t"):
            with pytest.raises(ValueError) as exc:
                ToolContext(user_id=bad_u, profile_id="p1")
            assert "Fail-closed" in str(exc.value)


# ============================================================================
# 3. PATH TRAVERSAL DEFENSES FAIL CLOSED
# ============================================================================

class TestAdversarialPathTraversalDefenses:
    """Stress tests path traversal attack strings, null bytes, URI schemes, and OS paths."""

    @pytest.mark.asyncio
    async def test_all_traversal_payloads_blocked(self, temp_workspace: Path):
        """Verifies extensive directory traversal attack matrix fails closed."""
        ctx = type("CtxTrav", (), {
            "workspace_root": temp_workspace,
            "user_id": "u_trav_harness",
            "profile_id": "p_trav_harness",
        })()

        traversal_attack_vectors = [
            # Standard directory traversals
            "../../etc/passwd",
            "../../../etc/shadow",
            "../../../../var/log/syslog",
            "../../../../private/etc/master.passwd",
            # Windows backslash traversals
            "..\\..\\windows\\win.ini",
            "..\\..\\system32\\config\\sam",
            # Mixed slashes
            "..\\../..\\../etc/passwd",
            # Double encoded / multi-dot traversals
            "....//....//etc/passwd",
            "....\\\\....\\\\windows\\win.ini",
            # URL encoded traversal sequences
            "..%2f..%2fetc/passwd",
            "..%2F..%2Fetc%2Fpasswd",
            "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
            "%2e%2e/%2e%2e/etc/passwd",
            # Windows drive letters & absolute paths
            "C:\\Windows\\System32\\drivers\\etc\\hosts",
            "C:/Windows/System32/drivers/etc/hosts",
            "D:\\confidential\\carefold.db",
            "E:/backup/keys.json",
            # Windows UNC network shares
            "\\\\10.0.0.1\\share\\stolen.txt",
            "//10.0.0.1/share/stolen.txt",
            # POSIX absolute paths
            "/etc/passwd",
            "/private/etc/hosts",
            "/var/root/.ssh/id_rsa",
        ]

        for payload in traversal_attack_vectors:
            res = await execute_attach_read({"path": payload}, ctx)
            assert res.success is False, f"Traversal payload unexpectedly succeeded: {payload}"
            err = res.error.lower()
            assert any(term in err for term in (
                "traversal", "escapes", "forbidden", "not found", "denied", "cross-profile", "security violation"
            )), f"Unexpected error response for traversal '{payload}': {res.error}"

    @pytest.mark.asyncio
    async def test_poison_null_byte_attacks_blocked(self, temp_workspace: Path):
        """Null byte injection in file paths must be caught immediately."""
        ctx = type("CtxNull", (), {
            "workspace_root": temp_workspace,
            "user_id": "u_null_harness",
            "profile_id": "p_null_harness",
        })()

        null_payloads = [
            "chart.txt\x00.pdf",
            "\x00../../etc/passwd",
            "safe_note.txt\x00/../../etc/shadow",
            "attachments/\x00/file.txt",
            "file.txt\0",
        ]

        for payload in null_payloads:
            res = await execute_attach_read({"path": payload}, ctx)
            assert res.success is False, f"Null byte payload succeeded: {repr(payload)}"
            assert "null byte" in res.error.lower()

    @pytest.mark.asyncio
    async def test_uri_scheme_attacks_blocked(self, temp_workspace: Path):
        """URI protocol scheme injections must be blocked."""
        ctx = type("CtxUri", (), {
            "workspace_root": temp_workspace,
            "user_id": "u_uri_harness",
            "profile_id": "p_uri_harness",
        })()

        uri_schemes = [
            "file:///etc/passwd",
            "file://localhost/etc/passwd",
            "FILE:///etc/passwd",
            "http://169.254.169.254/latest/meta-data/",
            "https://attacker.site/exfiltrate",
            "ftp://attacker.site/leak",
            "gopher://attacker.site:70/1",
            "data:text/plain;base64,QUJDRA==",
            "javascript:alert('xss')",
            "blob:http://localhost:3000/some-guid",
            "about:blank",
        ]

        for scheme_payload in uri_schemes:
            res = await execute_attach_read({"path": scheme_payload}, ctx)
            assert res.success is False, f"URI scheme payload succeeded: {scheme_payload}"
            assert "uri schemes" in res.error.lower() or "traversal" in res.error.lower()

    def test_api_download_endpoint_path_traversal_rejection(self, client: TestClient, temp_workspace: Path):
        """API download endpoint rejects path traversal sequences in {attachment_id} parameter."""
        traversal_ids = [
            "..%2f..%2fetc%2fpasswd",
            "..%2F..%2Fetc%2Fshadow",
            "..%5c..%5cwindows%5cwin.ini",
            "/etc/passwd",
        ]
        for trav_id in traversal_ids:
            res = client.get(f"/api/attachments/{trav_id}/download")
            assert res.status_code in (
                status.HTTP_404_NOT_FOUND,
                status.HTTP_400_BAD_REQUEST,
                422,
            ), f"API download failed to reject traversal id {trav_id}: code {res.status_code}"


# ============================================================================
# 4. MULTI-PROFILE IDENTICAL FILENAME INDEPENDENCE & ISOLATION
# ============================================================================

class TestMultiProfileIdenticalFilenameIsolation:
    """Stress tests scenarios where multiple profiles share identical attachment filenames.

    Must verify:
    1. Independent access without false cross-profile lockout.
    2. Proper active-profile resolution (getting the caller profile's own version).
    3. Proper cross-profile lockout when a 3rd profile without the file queries the same name.
    4. Proper CAS deduplication handling (shared SHA deletion reference counting).
    """

    @pytest.mark.asyncio
    async def test_identical_filename_different_content_no_false_lockout(self, temp_workspace: Path):
        """Profile Alpha and Profile Beta both have 'lab_vitals.txt' with different content.

        Both must read their own version cleanly; Gamma (who has no file) must be denied.
        """
        session_factory = get_session_factory()
        shared_filename = "lab_vitals.txt"

        alpha_content = "ALPHA_VITALS: Patient 1 - BP 118/75, Pulse 68 bpm, SpO2 99%."
        beta_content = "BETA_VITALS: Patient 2 - BP 165/105, Pulse 110 bpm, SpO2 93% (Hypertensive Crisis)."

        alpha_sha = hashlib.sha256(alpha_content.encode()).hexdigest()
        beta_sha = hashlib.sha256(beta_content.encode()).hexdigest()

        alpha_id = str(uuid.uuid4())
        beta_id = str(uuid.uuid4())

        async with session_factory() as db:
            u_alpha = User(id="u_alpha_dup", email="alpha_dup@test.local", username="alpha_dup", hashed_password="pw")
            u_beta = User(id="u_beta_dup", email="beta_dup@test.local", username="beta_dup", hashed_password="pw")
            u_gamma = User(id="u_gamma_dup", email="gamma_dup@test.local", username="gamma_dup", hashed_password="pw")
            p_alpha = Profile(id="p_alpha_dup", user_id="u_alpha_dup", name="Profile Alpha")
            p_beta = Profile(id="p_beta_dup", user_id="u_beta_dup", name="Profile Beta")
            p_gamma = Profile(id="p_gamma_dup", user_id="u_gamma_dup", name="Profile Gamma")
            db.add_all([u_alpha, u_beta, u_gamma, p_alpha, p_beta, p_gamma])
            await db.flush()

            att_alpha = Attachment(
                id=alpha_id,
                user_id="u_alpha_dup",
                profile_id="p_alpha_dup",
                filename=shared_filename,
                original_name=shared_filename,
                content_type="text/plain",
                size_bytes=len(alpha_content),
                sha256_hash=alpha_sha,
                storage_key=f"u_alpha_dup/p_alpha_dup/{shared_filename}",
                extracted_text=alpha_content,
                source="upload",
                extraction_status="completed",
            )
            att_beta = Attachment(
                id=beta_id,
                user_id="u_beta_dup",
                profile_id="p_beta_dup",
                filename=shared_filename,
                original_name=shared_filename,
                content_type="text/plain",
                size_bytes=len(beta_content),
                sha256_hash=beta_sha,
                storage_key=f"u_beta_dup/p_beta_dup/{shared_filename}",
                extracted_text=beta_content,
                source="upload",
                extraction_status="completed",
            )
            db.add_all([att_alpha, att_beta])
            await db.commit()

        # Store CAS files
        store_cas_file(
            content=alpha_content.encode(),
            carefold_home=settings.home_dir,
            user_id="u_alpha_dup",
            profile_id="p_alpha_dup",
            sha256_hash=alpha_sha,
        )
        store_cas_file(
            content=beta_content.encode(),
            carefold_home=settings.home_dir,
            user_id="u_beta_dup",
            profile_id="p_beta_dup",
            sha256_hash=beta_sha,
        )

        ctx_alpha = type("AlphaCtx", (), {
            "workspace_root": temp_workspace,
            "user_id": "u_alpha_dup",
            "profile_id": "p_alpha_dup",
        })()
        ctx_beta = type("BetaCtx", (), {
            "workspace_root": temp_workspace,
            "user_id": "u_beta_dup",
            "profile_id": "p_beta_dup",
        })()
        ctx_gamma = type("GammaCtx", (), {
            "workspace_root": temp_workspace,
            "user_id": "u_gamma_dup",
            "profile_id": "p_gamma_dup",
        })()

        # 1. Alpha reads 'lab_vitals.txt' -> MUST succeed and return Alpha's content
        res_alpha = await execute_attach_read({"path": shared_filename}, ctx_alpha)
        assert res_alpha.success is True, f"Alpha was locked out from reading own file: {res_alpha.error}"
        assert res_alpha.output is not None
        assert "ALPHA_VITALS" in res_alpha.output["content"]
        assert "BETA_VITALS" not in res_alpha.output["content"]

        # 2. Beta reads 'lab_vitals.txt' -> MUST succeed and return Beta's content
        res_beta = await execute_attach_read({"path": shared_filename}, ctx_beta)
        assert res_beta.success is True, f"Beta was locked out from reading own file: {res_beta.error}"
        assert res_beta.output is not None
        assert "BETA_VITALS" in res_beta.output["content"]
        assert "ALPHA_VITALS" not in res_beta.output["content"]

        # 3. Gamma queries 'lab_vitals.txt' -> MUST fail closed with cross-profile denial
        res_gamma = await execute_attach_read({"path": shared_filename}, ctx_gamma)
        assert res_gamma.success is False, "Gamma was unexpectedly permitted to read another profile's file!"
        assert "cross-profile" in res_gamma.error.lower() or "denied" in res_gamma.error.lower()

    def test_identical_filename_and_content_cas_deduplication_and_deletion(
        self,
        client: TestClient,
        temp_workspace: Path,
    ):
        """Profile Alpha and Profile Beta upload the EXACT same document (identical filename & SHA).

        Both must download independently. Deleting Alpha's attachment must NOT delete
        the shared CAS file, allowing Beta to continue downloading without interruption.
        """
        now = datetime.now(timezone.utc)
        shared_filename = "standard_notice.txt"
        shared_payload = b"NOTICE: Privacy Practices and Consent for Medical Treatment (2026)."
        shared_sha = hashlib.sha256(shared_payload).hexdigest()

        alpha_id = str(uuid.uuid4())
        beta_id = str(uuid.uuid4())

        user_alpha = UserProfile(
            id="u_alpha_cas",
            email="alpha_cas@test.local",
            username="alpha_cas",
            role="member",
            status="active",
            created_at=now,
            updated_at=now,
        )
        user_beta = UserProfile(
            id="u_beta_cas",
            email="beta_cas@test.local",
            username="beta_cas",
            role="member",
            status="active",
            created_at=now,
            updated_at=now,
        )

        session_factory = get_session_factory()
        import asyncio

        async def setup():
            async with session_factory() as db:
                db.add(User(id="u_alpha_cas", email="alpha_cas@test.local", username="alpha_cas", hashed_password="pw"))
                db.add(User(id="u_beta_cas", email="beta_cas@test.local", username="beta_cas", hashed_password="pw"))
                db.add(Profile(id="p_alpha_cas", user_id="u_alpha_cas", name="Alpha CAS Profile"))
                db.add(Profile(id="p_beta_cas", user_id="u_beta_cas", name="Beta CAS Profile"))
                await db.flush()

                db.add(Attachment(
                    id=alpha_id,
                    user_id="u_alpha_cas",
                    profile_id="p_alpha_cas",
                    filename=shared_filename,
                    original_name=shared_filename,
                    content_type="text/plain",
                    size_bytes=len(shared_payload),
                    sha256_hash=shared_sha,
                    storage_key=f"u_alpha_cas/p_alpha_cas/{shared_filename}",
                    extracted_text=shared_payload.decode(),
                    source="upload",
                    extraction_status="completed",
                ))
                db.add(Attachment(
                    id=beta_id,
                    user_id="u_beta_cas",
                    profile_id="p_beta_cas",
                    filename=shared_filename,
                    original_name=shared_filename,
                    content_type="text/plain",
                    size_bytes=len(shared_payload),
                    sha256_hash=shared_sha,
                    storage_key=f"u_beta_cas/p_beta_cas/{shared_filename}",
                    extracted_text=shared_payload.decode(),
                    source="upload",
                    extraction_status="completed",
                ))
                await db.commit()

        asyncio.run(setup())

        # Store in CAS
        store_cas_file(
            content=shared_payload,
            carefold_home=settings.home_dir,
            user_id="u_alpha_cas",
            profile_id="p_alpha_cas",
            sha256_hash=shared_sha,
        )
        store_cas_file(
            content=shared_payload,
            carefold_home=settings.home_dir,
            user_id="u_beta_cas",
            profile_id="p_beta_cas",
            sha256_hash=shared_sha,
        )

        # 1. Alpha downloads Alpha's attachment
        app.dependency_overrides[get_current_user] = lambda: user_alpha
        res_a = client.get(f"/api/attachments/{alpha_id}/download")
        assert res_a.status_code == status.HTTP_200_OK
        assert res_a.content == shared_payload

        # 2. Alpha cannot download Beta's attachment (403 Forbidden)
        res_cross = client.get(f"/api/attachments/{beta_id}/download")
        assert res_cross.status_code == status.HTTP_403_FORBIDDEN

        # 3. Alpha deletes Alpha's attachment
        del_a = client.delete(f"/api/attachments/{alpha_id}")
        assert del_a.status_code == status.HTTP_200_OK
        app.dependency_overrides.pop(get_current_user, None)

        # 4. Beta downloads Beta's attachment -> MUST STILL SUCCEED (CAS file not orphaned!)
        app.dependency_overrides[get_current_user] = lambda: user_beta
        res_b = client.get(f"/api/attachments/{beta_id}/download")
        assert res_b.status_code == status.HTTP_200_OK, f"Beta download failed after Alpha delete: {res_b.text}"
        assert res_b.content == shared_payload

        # 5. Beta deletes Beta's attachment
        del_b = client.delete(f"/api/attachments/{beta_id}")
        assert del_b.status_code == status.HTTP_200_OK
        app.dependency_overrides.pop(get_current_user, None)
