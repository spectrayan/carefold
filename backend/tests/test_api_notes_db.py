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

"""Test suite verifying database-only clinical notes persistence, tags support, and profile scoping."""

import asyncio
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from carefold.config import settings
from carefold.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER
from carefold.db.models import Note, Profile, User
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app


@pytest.fixture(autouse=True)
async def setup_notes_db():
    """Initializes in-memory database and ensures test isolation."""
    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        user = await session.get(User, DEFAULT_STEWARD_USER.id)
        if not user:
            user = User(
                id=DEFAULT_STEWARD_USER.id,
                email="steward@carefold.ai",
                username="steward",
                hashed_password="mock",
                role="steward",
                status="active",
                auth_provider="disabled",
            )
            session.add(user)
            await session.commit()
    yield


@pytest.fixture
def test_profile_id(client: TestClient) -> str:
    """Provisions an isolated care profile for notes persistence tests."""
    resp = client.post("/api/profiles", json={"name": "Primary Patient", "relationship": "self"})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_notes_db_only_no_filesystem_write(client: TestClient, temp_workspace: Path, test_profile_id: str):
    """Verifies that creating a note writes strictly to carefold.db with zero loose files created on disk."""
    notes_dir = settings.get_notes_dir()
    initial_files = list(notes_dir.glob("**/*.md"))

    payload = {
        "title": "Hypertension Log & Medication Checklist",
        "content": "Check BP daily at 8am and 8pm.\nBring log to cardiologist.",
        "type": "clinical_prep",
        "tags": ["cardiology", "hypertension"],
        "profile_id": test_profile_id,
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


def test_list_notes_ignores_loose_filesystem_files(client: TestClient, temp_workspace: Path, test_profile_id: str):
    """Verifies that list_notes queries only carefold.db and ignores unmanaged files on disk."""
    notes_dir = settings.get_notes_dir()
    notes_dir.mkdir(parents=True, exist_ok=True)
    loose_file = notes_dir / "untracked_rogue_note.md"
    loose_file.write_text("---\ntitle: 'Rogue Note'\n---\nDangerous content", encoding="utf-8")

    # DB note
    resp = client.post("/api/notes", json={"title": "Official DB Note", "content": "Clean content", "profile_id": test_profile_id})
    assert resp.status_code == 201
    db_slug = resp.json()["slug"]

    list_resp = client.get("/api/notes")
    assert list_resp.status_code == 200
    slugs = [n["slug"] for n in list_resp.json()]

    assert db_slug in slugs
    assert "untracked_rogue_note" not in slugs


def test_notes_tags_json_and_list_support(client: TestClient, test_profile_id: str):
    """Verifies that tags are accepted as a list and returned in both tags and tags_json fields."""
    resp = client.post(
        "/api/notes",
        json={
            "title": "Cardiology Prep",
            "content": "Bring recent ECG",
            "tags": ["heart", "ecg", "vitals"],
            "profile_id": test_profile_id,
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


def test_notes_crud_lifecycle(client: TestClient, test_profile_id: str):
    """Verifies the complete CRUD lifecycle for clinical notes."""
    # 1. Create
    c_resp = client.post("/api/notes", json={"title": "Visit Note", "content": "Initial", "profile_id": test_profile_id})
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
