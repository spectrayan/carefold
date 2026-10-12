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

"""Empirical adversarial stress test suite for CAS storage layout and reference-counted deletion (R3).

Thoroughly verifies:
1. CAS storage layout <carefold_home>/data/files/<user_id>/<profile_id>/<sha256>.
2. Content deduplication: saving identical content under the same profile deduplicates properly.
3. Reference-counted deletion: when 2 attachments share the same CAS file, deleting attachment 1
   does NOT delete the physical CAS file.
4. Surviving download integrity: verify attachment 2 download still returns 200 OK with correct
   content, Content-Length, ETag, and security headers.
5. Zero-ref unlinking: verify deleting attachment 2 cleanly unlinks the physical CAS file when
   the reference count reaches 0.
6. Streaming download header integrity (Content-Length, ETag, X-Content-Type-Options, Content-Disposition).
7. Multi-reference stress (N=5 attachments lifecycle).
8. Cross-profile reference isolation.
9. Zero-byte and large-payload boundary verification.
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from typing import List
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from carefold.config import settings
from carefold.db.models import Attachment, Profile, User
from carefold.db.session import get_session_factory
from carefold.storage.cas import (
    cas_file_exists,
    get_cas_path,
    read_cas_file,
    store_cas_file,
)

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


# ============================================================================
# HELPER FIXTURES
# ============================================================================

@pytest.fixture
async def sample_profiles(temp_workspace: Path):
    """Creates two distinct profiles under a test user in carefold.db."""
    session_factory = get_session_factory()
    user_id = "test_steward_user"
    prof_a_id = f"prof_a_{uuid.uuid4().hex[:8]}"
    prof_b_id = f"prof_b_{uuid.uuid4().hex[:8]}"

    async with session_factory() as db:
        user = User(
            id=user_id,
            email="steward@test.local",
            username="steward_test",
            hashed_password="hashed_pw_placeholder",
        )
        prof_a = Profile(id=prof_a_id, user_id=user_id, name="Patient Alpha Profile")
        prof_b = Profile(id=prof_b_id, user_id=user_id, name="Patient Beta Profile")
        db.add_all([user, prof_a, prof_b])
        await db.commit()

    return {
        "user_id": user_id,
        "profile_a": prof_a_id,
        "profile_b": prof_b_id,
    }


# ============================================================================
# 1. CAS STORAGE LAYOUT HIERARCHY
# ============================================================================

class TestCasStorageLayoutEmpirical:
    """Empirically verifies canonical CAS layout on physical disk."""

    def test_cas_storage_layout_structure(self, tmp_path: Path):
        """Layout must be strictly <carefold_home>/data/files/<user_id>/<profile_id>/<sha256>."""
        user_id = "user_cardio_101"
        profile_id = "prof_patient_202"
        payload = b"Cardiac Stress Test Protocol: Bruce Stage 4 Nominal"
        sha = hashlib.sha256(payload).hexdigest()

        cas_path, returned_sha, is_dedup = store_cas_file(
            content=payload,
            carefold_home=tmp_path,
            user_id=user_id,
            profile_id=profile_id,
        )

        assert returned_sha == sha
        assert is_dedup is False
        assert cas_path.is_file()

        # Check exact path components
        resolved_home = tmp_path.resolve()
        expected_path = resolved_home / "data" / "files" / user_id / profile_id / sha
        assert cas_path == expected_path

        # Verify disk directory hierarchy
        assert cas_path.name == sha
        assert cas_path.parent.name == profile_id
        assert cas_path.parent.parent.name == user_id
        assert cas_path.parent.parent.parent.name == "files"
        assert cas_path.parent.parent.parent.parent.name == "data"
        assert cas_path.parent.parent.parent.parent.parent == resolved_home

    def test_cas_storage_layout_default_fallbacks(self, tmp_path: Path):
        """None or empty user_id and profile_id default safely to 'default' segments."""
        payload = b"Anonymous System Health Record Payload"
        sha = hashlib.sha256(payload).hexdigest()

        cas_path, _, _ = store_cas_file(
            content=payload,
            carefold_home=tmp_path,
            user_id=None,
            profile_id=None,
        )

        expected = tmp_path.resolve() / "data" / "files" / "default" / "default" / sha
        assert cas_path == expected
        assert cas_path.is_file()


# ============================================================================
# 2. CONTENT DEDUPLICATION UNDER SAME PROFILE
# ============================================================================

class TestCasContentDeduplicationEmpirical:
    """Empirically verifies deduplication mechanics and metadata."""

    def test_deduplication_under_same_profile(self, client: TestClient, sample_profiles):
        """Saving identical content under the same profile deduplicates properly."""
        prof_a = sample_profiles["profile_a"]
        payload = b"ELECTROLYTES PANEL: Na 139, K 4.1, Cl 101, HCO3 25"
        expected_sha = hashlib.sha256(payload).hexdigest()

        # Upload 1st document
        res1 = client.post(
            f"/api/v1/attachments?profile_id={prof_a}",
            files={"file": ("electrolytes_run1.txt", io.BytesIO(payload), "text/plain")},
        )
        assert res1.status_code == 201
        data1 = res1.json()
        assert data1["success"] is True
        assert data1["sha256"] == expected_sha
        assert data1["is_deduplicated"] is False
        att1_id = data1["id"]

        # Check physical CAS path
        cas_file = get_cas_path(settings.home_dir, data1["user_id"], prof_a, expected_sha)
        assert cas_file.is_file()
        mtime_initial = cas_file.stat().st_mtime_ns

        # Upload 2nd document with identical payload under same profile
        res2 = client.post(
            f"/api/v1/attachments?profile_id={prof_a}",
            files={"file": ("electrolytes_run2.txt", io.BytesIO(payload), "text/plain")},
        )
        assert res2.status_code == 201
        data2 = res2.json()
        assert data2["success"] is True
        assert data2["sha256"] == expected_sha
        assert data2["is_deduplicated"] is True
        att2_id = data2["id"]

        # IDs must be unique in DB, but both share the same hash
        assert att1_id != att2_id

        # Physical CAS file was reused (mtime untouched)
        assert cas_file.stat().st_mtime_ns == mtime_initial
        assert cas_file.read_bytes() == payload

    def test_no_deduplication_across_different_profiles(self, client: TestClient, sample_profiles):
        """Identical content uploaded under different profiles creates isolated CAS files."""
        prof_a = sample_profiles["profile_a"]
        prof_b = sample_profiles["profile_b"]
        payload = b"Cross-Profile Diagnostic Report Payload"
        expected_sha = hashlib.sha256(payload).hexdigest()

        res_a = client.post(
            f"/api/v1/attachments?profile_id={prof_a}",
            files={"file": ("report_a.txt", io.BytesIO(payload), "text/plain")},
        )
        assert res_a.status_code == 201
        data_a = res_a.json()
        assert data_a["is_deduplicated"] is False

        res_b = client.post(
            f"/api/v1/attachments?profile_id={prof_b}",
            files={"file": ("report_b.txt", io.BytesIO(payload), "text/plain")},
        )
        assert res_b.status_code == 201
        data_b = res_b.json()
        # Different partition, so NOT deduplicated against prof_a
        assert data_b["is_deduplicated"] is False

        # Two distinct physical files on disk
        path_a = get_cas_path(settings.home_dir, data_a["user_id"], prof_a, expected_sha)
        path_b = get_cas_path(settings.home_dir, data_b["user_id"], prof_b, expected_sha)

        assert path_a != path_b
        assert path_a.is_file() and path_b.is_file()


# ============================================================================
# 3. REFERENCE-COUNTED DELETION & SURVIVING DOWNLOAD INTEGRITY
# ============================================================================

class TestCasReferenceCountedDeletionAndDownload:
    """Verifies that deleting 1 of 2 shared attachments preserves CAS file and allows download."""

    def test_reference_counted_deletion_two_attachments(self, client: TestClient, sample_profiles):
        """When 2 attachments share the same CAS file:
        - Deleting attachment 1 does NOT delete the physical CAS file.
        - Attachment 2 download returns 200 OK with correct content and Content-Length.
        - Deleting attachment 2 cleanly unlinks physical CAS file when refcount reaches 0.
        """
        prof_a = sample_profiles["profile_a"]
        payload = b"MRI BRAIN WITH AND WITHOUT CONTRAST: Unremarkable ventricular system."
        expected_sha = hashlib.sha256(payload).hexdigest()

        # Step 1: Upload Attachment 1
        res1 = client.post(
            f"/api/v1/attachments?profile_id={prof_a}",
            files={"file": ("mri_report_copy1.txt", io.BytesIO(payload), "text/plain")},
        )
        assert res1.status_code == 201
        data1 = res1.json()
        att1_id = data1["id"]
        user_id = data1["user_id"]

        # Step 2: Upload Attachment 2 (identical content)
        res2 = client.post(
            f"/api/v1/attachments?profile_id={prof_a}",
            files={"file": ("mri_report_copy2.txt", io.BytesIO(payload), "text/plain")},
        )
        assert res2.status_code == 201
        data2 = res2.json()
        att2_id = data2["id"]
        assert data2["is_deduplicated"] is True

        # Verify physical CAS file exists on disk
        cas_path = get_cas_path(settings.home_dir, user_id, prof_a, expected_sha)
        assert cas_path.is_file()

        # Step 3: Delete Attachment 1
        del1 = client.delete(f"/api/v1/attachments/{att1_id}")
        assert del1.status_code == 200
        assert del1.json()["success"] is True
        assert del1.json()["deleted"] is True

        # CRITICAL ASSERTION: Physical CAS file must STILL exist because att2 references it!
        assert cas_path.is_file(), "CAS file MUST NOT be unlinked while Attachment 2 still references it"
        assert cas_file_exists(settings.home_dir, user_id, prof_a, expected_sha) is True

        # Step 4: Verify Attachment 1 is gone from API
        dl1 = client.get(f"/api/v1/attachments/{att1_id}/download")
        assert dl1.status_code == 404

        # Step 5: Verify Attachment 2 download still returns 200 OK with correct content and headers
        dl2 = client.get(f"/api/v1/attachments/{att2_id}/download")
        assert dl2.status_code == 200
        assert dl2.content == payload
        assert dl2.headers["content-length"] == str(len(payload))
        assert dl2.headers["etag"] == f'"{expected_sha}"'
        assert dl2.headers["x-content-type-options"] == "nosniff"
        assert 'filename="mri_report_copy2.txt"' in dl2.headers["content-disposition"]

        # Step 6: Verify Content route alias works identically
        content_res = client.get(f"/api/v1/attachments/{att2_id}/content")
        assert content_res.status_code == 200
        assert content_res.content == payload
        assert content_res.headers["content-length"] == str(len(payload))

        # Step 7: Delete Attachment 2 (reference count reaches 0)
        del2 = client.delete(f"/api/v1/attachments/{att2_id}")
        assert del2.status_code == 200
        assert del2.json()["success"] is True
        assert del2.json()["deleted"] is True

        # CRITICAL ASSERTION: Physical CAS file must now be cleanly unlinked!
        assert not cas_path.exists(), "CAS file MUST be unlinked when reference count reaches 0"
        assert cas_file_exists(settings.home_dir, user_id, prof_a, expected_sha) is False

        # Step 8: Subsequent download of Attachment 2 returns 404
        dl2_after = client.get(f"/api/v1/attachments/{att2_id}/download")
        assert dl2_after.status_code == 404


# ============================================================================
# 4. STREAMING DOWNLOAD HEADER INTEGRITY
# ============================================================================

class TestCasStreamingDownloadHeaderIntegrity:
    """Verifies HTTP response headers for downloads from CAS."""

    def test_streaming_headers_integrity(self, client: TestClient, sample_profiles):
        """Header integrity: Content-Length, ETag, X-Content-Type-Options, Content-Disposition."""
        prof_a = sample_profiles["profile_a"]
        payload = b"Comprehensive Metabolic Panel: All analytes within normal reference intervals.\n" * 10
        expected_sha = hashlib.sha256(payload).hexdigest()
        filename = "metabolic_panel_2026.txt"

        up = client.post(
            f"/api/v1/attachments?profile_id={prof_a}",
            files={"file": (filename, io.BytesIO(payload), "text/plain")},
        )
        assert up.status_code == 201
        att_id = up.json()["id"]

        dl = client.get(f"/api/v1/attachments/{att_id}/download")
        assert dl.status_code == 200

        # Exact headers verification
        headers = dl.headers
        assert headers.get("content-length") == str(len(payload))
        assert headers.get("etag") == f'"{expected_sha}"'
        assert headers.get("x-content-type-options") == "nosniff"
        assert f'filename="{filename}"' in headers.get("content-disposition", "")
        assert dl.content == payload

    def test_streaming_headers_zero_byte_file(self, client: TestClient, sample_profiles):
        """Zero-byte file streaming download headers."""
        prof_a = sample_profiles["profile_a"]
        payload = b""
        filename = "empty_record.txt"

        up = client.post(
            f"/api/v1/attachments?profile_id={prof_a}",
            files={"file": (filename, io.BytesIO(payload), "text/plain")},
        )
        assert up.status_code == 201
        att_id = up.json()["id"]

        dl = client.get(f"/api/v1/attachments/{att_id}/download")
        assert dl.status_code == 200
        assert dl.content == b""
        assert dl.headers.get("content-length") == "0"
        assert dl.headers.get("etag") == f'"{EMPTY_SHA256}"'
        assert dl.headers.get("x-content-type-options") == "nosniff"

    def test_streaming_headers_large_payload(self, client: TestClient, sample_profiles):
        """Large payload (~512KB) streaming download headers and integrity."""
        prof_a = sample_profiles["profile_a"]
        chunk = b"CLINICAL_DISCHARGE_SUMMARY_SERIALIZED_RECORD_ROW_INDEX_123456789\n"
        payload = chunk * 8000  # ~512 KB
        expected_sha = hashlib.sha256(payload).hexdigest()
        filename = "large_summary.txt"

        up = client.post(
            f"/api/v1/attachments?profile_id={prof_a}",
            files={"file": (filename, io.BytesIO(payload), "text/plain")},
        )
        assert up.status_code == 201
        att_id = up.json()["id"]

        dl = client.get(f"/api/v1/attachments/{att_id}/download")
        assert dl.status_code == 200
        assert len(dl.content) == len(payload)
        assert dl.headers.get("content-length") == str(len(payload))
        assert dl.headers.get("etag") == f'"{expected_sha}"'
        assert hashlib.sha256(dl.content).hexdigest() == expected_sha


# ============================================================================
# 5. MULTI-REFERENCE STRESS (N=5 ATTACHMENTS LIFECYCLE)
# ============================================================================

class TestCasMultiReferenceStress:
    """Stress tests reference counting across 5 attachments sharing 1 physical CAS file."""

    def test_multi_reference_lifecycle_n5(self, client: TestClient, sample_profiles):
        """Upload 5 documents with identical content:
        - Refcount goes 1 -> 2 -> 3 -> 4 -> 5.
        - Deleting 1 by 1: file retained at refcount 4, 3, 2, 1.
        - File unlinked only at refcount 0.
        """
        prof_a = sample_profiles["profile_a"]
        payload = b"Multi-Reference Clinical Guideline Document: Hyperkalemia Protocol"
        expected_sha = hashlib.sha256(payload).hexdigest()

        att_ids: List[str] = []
        user_id = None

        # Upload 5 identical files
        for i in range(5):
            res = client.post(
                f"/api/v1/attachments?profile_id={prof_a}",
                files={"file": (f"guideline_copy_{i}.txt", io.BytesIO(payload), "text/plain")},
            )
            assert res.status_code == 201
            d = res.json()
            att_ids.append(d["id"])
            user_id = d["user_id"]
            if i == 0:
                assert d["is_deduplicated"] is False
            else:
                assert d["is_deduplicated"] is True

        cas_path = get_cas_path(settings.home_dir, user_id, prof_a, expected_sha)
        assert cas_path.is_file()

        # Delete documents 0, 1, 2, 3 (refcount drops from 5 to 1)
        for i in range(4):
            to_delete_id = att_ids[i]
            del_res = client.delete(f"/api/v1/attachments/{to_delete_id}")
            assert del_res.status_code == 200

            # Physical CAS file must STILL exist
            assert cas_path.is_file(), f"CAS file prematurely unlinked after deleting document index {i}"

            # Surviving document (index 4) download still succeeds
            surviving_id = att_ids[4]
            surv_dl = client.get(f"/api/v1/attachments/{surviving_id}/download")
            assert surv_dl.status_code == 200
            assert surv_dl.content == payload
            assert surv_dl.headers["content-length"] == str(len(payload))

        # Delete document 4 (refcount drops to 0)
        final_id = att_ids[4]
        final_del = client.delete(f"/api/v1/attachments/{final_id}")
        assert final_del.status_code == 200

        # Physical CAS file is now cleanly unlinked
        assert not cas_path.exists(), "CAS file must be unlinked when refcount reaches 0"
        assert cas_file_exists(settings.home_dir, user_id, prof_a, expected_sha) is False

        # Download of document 4 returns 404
        dl_final = client.get(f"/api/v1/attachments/{final_id}/download")
        assert dl_final.status_code == 404


# ============================================================================
# 6. CROSS-PROFILE REFERENCE ISOLATION
# ============================================================================

class TestCasCrossProfileReferenceIsolation:
    """Verifies that unlinking in Profile A never unlinks identical content in Profile B."""

    def test_cross_profile_deletion_isolation(self, client: TestClient, sample_profiles):
        """Profile A has 2 attachments; Profile B has 1 attachment with identical content.
        - Deleting both attachments in Profile A unlinks Profile A's physical CAS file.
        - Profile B's physical CAS file remains intact on disk!
        - Profile B download returns 200 OK.
        """
        prof_a = sample_profiles["profile_a"]
        prof_b = sample_profiles["profile_b"]
        payload = b"Shared Standard Formulary Tier List 2026"
        expected_sha = hashlib.sha256(payload).hexdigest()

        # Upload 2 copies to Profile A
        res_a1 = client.post(
            f"/api/v1/attachments?profile_id={prof_a}",
            files={"file": ("formulary_a1.txt", io.BytesIO(payload), "text/plain")},
        )
        assert res_a1.status_code == 201
        a1_id = res_a1.json()["id"]
        user_id = res_a1.json()["user_id"]

        res_a2 = client.post(
            f"/api/v1/attachments?profile_id={prof_a}",
            files={"file": ("formulary_a2.txt", io.BytesIO(payload), "text/plain")},
        )
        assert res_a2.status_code == 201
        a2_id = res_a2.json()["id"]

        # Upload 1 copy to Profile B
        res_b1 = client.post(
            f"/api/v1/attachments?profile_id={prof_b}",
            files={"file": ("formulary_b1.txt", io.BytesIO(payload), "text/plain")},
        )
        assert res_b1.status_code == 201
        b1_id = res_b1.json()["id"]

        path_a = get_cas_path(settings.home_dir, user_id, prof_a, expected_sha)
        path_b = get_cas_path(settings.home_dir, user_id, prof_b, expected_sha)

        assert path_a.is_file()
        assert path_b.is_file()

        # Delete a1 -> Profile A CAS file retained
        assert client.delete(f"/api/v1/attachments/{a1_id}").status_code == 200
        assert path_a.is_file()
        assert path_b.is_file()

        # Delete a2 -> Profile A CAS file UNLINKED (refcount 0 in profile A)
        assert client.delete(f"/api/v1/attachments/{a2_id}").status_code == 200
        assert not path_a.exists(), "Profile A CAS file must be unlinked"

        # CRITICAL ASSERTION: Profile B's physical CAS file MUST STILL EXIST!
        assert path_b.is_file(), "Profile B CAS file must NOT be affected by Profile A deletion"
        assert path_b.read_bytes() == payload

        # Profile B download returns 200 OK
        dl_b = client.get(f"/api/v1/attachments/{b1_id}/download")
        assert dl_b.status_code == 200
        assert dl_b.content == payload
        assert dl_b.headers["content-length"] == str(len(payload))

        # Delete b1 -> Profile B CAS file now unlinked
        assert client.delete(f"/api/v1/attachments/{b1_id}").status_code == 200
        assert not path_b.exists(), "Profile B CAS file must be unlinked after its last reference is deleted"
