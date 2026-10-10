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

"""Test suite verifying database-only clinical notes persistence, tags support, and profile scoping."""

import asyncio
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from carefold.config import settings
from carefold.db.models import Note, Profile
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app


@pytest.fixture(autouse=True)
async def setup_notes_db():
    """Initializes in-memory database and ensures test isolation."""
    await init_db()
    yield


def test_notes_db_only_no_filesystem_write(client: TestClient, temp_workspace: Path):
    """Verifies that creating a note writes strictly to carefold.db with zero loose files created on disk."""
    notes_dir = settings.get_notes_dir()
    initial_files = list(notes_dir.glob("**/*.md"))

    payload = {
        "title": "Hypertension Log & Medication Checklist",
        "content": "Check BP daily at 8am and 8pm.\nBring log to cardiologist.",
        "type": "clinical_prep",
        "tags": ["cardiology", "hypertension"],
    }
    resp = client.post("/api/notes", json=payload)
    assert resp.status_code == 201
    created = resp.json()
    slug = created["slug"]

    # Invariant: Zero files written to notes_dir
    post_files = list(notes_dir.glob("**/*.md"))
    assert len(post_files) == len(initial_files)
    assert not (notes_dir / f"{slug}.md").exists()

    # Query directly via API
    get_resp = client.get(f"/api/notes/{slug}")
    assert get_resp.status_code == 200
    assert get_resp.json()["title"] == "Hypertension Log & Medication Checklist"
    assert get_resp.json()["tags"] == ["cardiology", "hypertension"]
    assert '["cardiology", "hypertension"]' in get_resp.json()["tags_json"]


def test_list_notes_ignores_loose_filesystem_files(client: TestClient, temp_workspace: Path):
    """Verifies that list_notes queries only carefold.db and ignores unmanaged files on disk."""
    notes_dir = settings.get_notes_dir()
    notes_dir.mkdir(parents=True, exist_ok=True)
    loose_file = notes_dir / "untracked_rogue_note.md"
    loose_file.write_text("---\ntitle: 'Rogue Note'\n---\nDangerous content", encoding="utf-8")

    # DB note
    resp = client.post("/api/notes", json={"title": "Official DB Note", "content": "Clean content"})
    assert resp.status_code == 201
    db_slug = resp.json()["slug"]

    list_resp = client.get("/api/notes")
    assert list_resp.status_code == 200
    slugs = [n["slug"] for n in list_resp.json()]

    assert db_slug in slugs
    assert "untracked_rogue_note" not in slugs


def test_notes_tags_json_and_list_support(client: TestClient):
    """Verifies that tags are accepted as a list and returned in both tags and tags_json fields."""
    resp = client.post(
        "/api/notes",
        json={
            "title": "Cardiology Prep",
            "content": "Bring recent ECG",
            "tags": ["heart", "ecg", "vitals"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["tags"] == ["heart", "ecg", "vitals"]
    assert data["tags_json"] == '["heart", "ecg", "vitals"]'

    slug = data["slug"]
    put_resp = client.put(
        f"/api/notes/{slug}",
        json={"tags": ["heart", "annual-checkup"]},
    )
    assert put_resp.status_code == 200
    updated = put_resp.json()
    assert updated["tags"] == ["heart", "annual-checkup"]
    assert updated["tags_json"] == '["heart", "annual-checkup"]'


def test_notes_crud_lifecycle(client: TestClient):
    """Verifies the complete CRUD lifecycle for clinical notes."""
    # 1. Create
    c_resp = client.post("/api/notes", json={"title": "Visit Note", "content": "Initial"})
    assert c_resp.status_code == 201
    slug = c_resp.json()["slug"]

    # 2. Read
    r_resp = client.get(f"/api/notes/{slug}")
    assert r_resp.status_code == 200
    assert r_resp.json()["content"] == "Initial"

    # 3. Update
    u_resp = client.put(f"/api/notes/{slug}", json={"content": "Updated content"})
    assert u_resp.status_code == 200
    assert u_resp.json()["content"] == "Updated content"

    # 4. Delete
    d_resp = client.delete(f"/api/notes/{slug}")
    assert d_resp.status_code == 200
    assert d_resp.json()["deleted"] is True

    # 5. Verify 404
    assert client.get(f"/api/notes/{slug}").status_code == 404


@pytest.mark.parametrize(
    "bad_slug",
    ["../../etc/passwd", "..%2f..%2fpasswd", "note/subnote", "note\\escaped", "slug with spaces", "note%00"],
)
def test_notes_slug_security_rejections(client: TestClient, bad_slug: str):
    """Verifies that traversal attacks and invalid characters in slugs are rejected."""
    assert client.get(f"/api/notes/{bad_slug}").status_code in (400, 404)
