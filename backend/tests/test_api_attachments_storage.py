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

"""Test suite for Attachments REST API with Hexagonal StoragePort integration."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from carefold.config import settings
from carefold.storage.factory import get_storage_adapter


class TestAttachmentsUploadStorage:
    """Tests file upload via StoragePort, SHA-256 computation, and DB persistence."""

    def test_upload_attachment_success(self, client: TestClient):
        content = b"Patient lab values: WBC 7.2, RBC 4.8"
        expected_hash = hashlib.sha256(content).hexdigest()

        response = client.post(
            "/api/attachments",
            files={"file": ("lab_report.txt", io.BytesIO(content), "text/plain")},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["filename"] == "lab_report.txt"
        assert data["size"] == len(content)
        assert data["sha256_hash"] == expected_hash
        assert "storage_key" in data

        # Verify StoragePort stores the file
        uploads_dir = settings.get_uploads_dir()
        assert (uploads_dir / data["storage_key"]).exists() or (uploads_dir / data["filename"]).exists()

    def test_upload_attachment_sha256_integrity(self, client: TestClient):
        content = b"Cryptographic integrity check test string"
        true_sha = hashlib.sha256(content).hexdigest()

        response = client.post(
            "/api/attachments",
            files={"file": ("crypto_check.txt", io.BytesIO(content), "text/plain")},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["sha256_hash"] == true_sha

    def test_upload_attachment_duplicate_autorename(self, client: TestClient):
        content_v1 = b"Original Version"
        content_v2 = b"Second Version"

        res1 = client.post(
            "/api/attachments",
            files={"file": ("records.txt", io.BytesIO(content_v1), "text/plain")},
        )
        assert res1.status_code == 201
        assert res1.json()["filename"] == "records.txt"
        assert res1.json()["renamed"] is False

        res2 = client.post(
            "/api/attachments",
            files={"file": ("records.txt", io.BytesIO(content_v2), "text/plain")},
        )
        assert res2.status_code == 201
        assert res2.json()["filename"] == "records_1.txt"
        assert res2.json()["renamed"] is True

    def test_upload_attachment_unsupported_format(self, client: TestClient):
        response = client.post(
            "/api/attachments",
            files={"file": ("exploit.exe", io.BytesIO(b"MZ..."), "application/octet-stream")},
        )
        assert response.status_code == 400
        assert "unsupported file format" in response.json()["detail"].lower()

    def test_upload_attachment_oversized(self, client: TestClient):
        oversized = b"0" * (10 * 1024 * 1024 + 10)
        response = client.post(
            "/api/attachments",
            files={"file": ("huge.txt", io.BytesIO(oversized), "text/plain")},
        )
        assert response.status_code == 413
        assert "exceeds maximum limit" in response.json()["detail"].lower()


class TestAttachmentsDownloadStreaming:
    """Tests file download streaming, headers, and access control."""

    def test_download_attachment_success(self, client: TestClient):
        raw_content = b"Downloaded attachment content verification bytes"
        upload_res = client.post(
            "/api/attachments",
            files={"file": ("download_test.txt", io.BytesIO(raw_content), "text/plain")},
        )
        assert upload_res.status_code == 201
        att_id = upload_res.json()["id"]

        # Stream download
        dl_res = client.get(f"/api/attachments/{att_id}/download")
        assert dl_res.status_code == 200
        assert dl_res.content == raw_content
        assert dl_res.headers.get("content-type", "").startswith("text/plain")
        assert dl_res.headers.get("content-length") == str(len(raw_content))
        assert 'attachment; filename="download_test.txt"' in dl_res.headers.get("content-disposition", "")

    def test_download_attachment_content_alias(self, client: TestClient):
        raw_content = b"Content alias test stream"
        upload_res = client.post(
            "/api/attachments",
            files={"file": ("alias_test.txt", io.BytesIO(raw_content), "text/plain")},
        )
        att_id = upload_res.json()["id"]

        dl_res = client.get(f"/api/attachments/{att_id}/content")
        assert dl_res.status_code == 200
        assert dl_res.content == raw_content

    def test_download_attachment_not_found(self, client: TestClient):
        dl_res = client.get("/api/attachments/non_existent_uuid_12345/download")
        assert dl_res.status_code == 404


class TestAttachmentsDelete:
    """Tests attachment deletion from StoragePort and relational database."""

    def test_delete_attachment_success(self, client: TestClient):
        upload_res = client.post(
            "/api/attachments",
            files={"file": ("to_delete.txt", io.BytesIO(b"Delete me"), "text/plain")},
        )
        att_id = upload_res.json()["id"]

        del_res = client.delete(f"/api/attachments/{att_id}")
        assert del_res.status_code == 200
        assert del_res.json()["deleted"] is True

        # Subsequent download must return 404
        dl_res = client.get(f"/api/attachments/{att_id}/download")
        assert dl_res.status_code == 404
