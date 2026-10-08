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

"""Unit and integration tests for attachments upload and listing REST endpoints."""

import io
from pathlib import Path
from fastapi.testclient import TestClient

from carefold.config import settings


def test_upload_attachment_initial_success(client: TestClient, temp_workspace: Path):
    """Verifies successful upload of a supported attachment."""
    file_bytes = b"Hemoglobin: 14.2 g/dL\nPlatelets: 250,000"
    response = client.post(
        "/api/attachments",
        files={"file": ("lab_results.txt", io.BytesIO(file_bytes), "text/plain")},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["filename"] == "lab_results.txt"
    assert data["size"] == len(file_bytes)
    assert data["renamed"] is False
    assert "timestamp" in data

    attachments_dir = settings.get_attachments_dir()
    saved = attachments_dir / "lab_results.txt"
    assert saved.exists()
    assert saved.read_bytes() == file_bytes


def test_upload_attachment_duplicate_auto_rename_preserves_original(
    client: TestClient, temp_workspace: Path
):
    """Verifies that uploading a duplicate filename does not overwrite silently and auto-renames."""
    initial_content = b"Original Patient Record"
    updated_content = b"Updated Patient Record"

    # First upload
    res1 = client.post(
        "/api/attachments",
        files={"file": ("patient_history.txt", io.BytesIO(initial_content), "text/plain")},
    )
    assert res1.status_code == 201
    assert res1.json()["filename"] == "patient_history.txt"
    assert res1.json()["renamed"] is False

    # Second upload with same filename
    res2 = client.post(
        "/api/attachments",
        files={"file": ("patient_history.txt", io.BytesIO(updated_content), "text/plain")},
    )
    assert res2.status_code == 201
    assert res2.json()["filename"] == "patient_history_1.txt"
    assert res2.json()["renamed"] is True

    # Third upload with same filename
    res3 = client.post(
        "/api/attachments",
        files={"file": ("patient_history.txt", io.BytesIO(b"Third Version"), "text/plain")},
    )
    assert res3.status_code == 201
    assert res3.json()["filename"] == "patient_history_2.txt"
    assert res3.json()["renamed"] is True

    attachments_dir = settings.get_attachments_dir()
    # Verify original is still intact
    assert (attachments_dir / "patient_history.txt").read_bytes() == initial_content
    # Verify second version is intact
    assert (attachments_dir / "patient_history_1.txt").read_bytes() == updated_content
    # Verify third version is intact
    assert (attachments_dir / "patient_history_2.txt").read_bytes() == b"Third Version"


def test_upload_attachment_unsupported_format(client: TestClient, temp_workspace: Path):
    """Verifies rejection of unsupported file extensions."""
    response = client.post(
        "/api/attachments",
        files={"file": ("malicious.exe", io.BytesIO(b"binary"), "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "unsupported file format" in response.json()["detail"].lower()


def test_list_attachments(client: TestClient, temp_workspace: Path):
    """Verifies listing uploaded attachments."""
    attachments_dir = settings.get_attachments_dir()
    for f in attachments_dir.iterdir():
        if f.is_file():
            f.unlink()

    # Upload two files
    client.post(
        "/api/attachments",
        files={"file": ("doc_a.txt", io.BytesIO(b"Document A"), "text/plain")},
    )
    client.post(
        "/api/attachments",
        files={"file": ("doc_b.pdf", io.BytesIO(b"%PDF-1.4 sample"), "application/pdf")},
    )

    resp = client.get("/api/attachments")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    filenames = [i["filename"] for i in items]
    assert "doc_a.txt" in filenames
    assert "doc_b.pdf" in filenames
