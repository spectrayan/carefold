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

"""Unit and integration tests for Workspace Notes REST endpoints and tool."""

from datetime import datetime, timezone
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from carefold.config import settings
from carefold.tools.workspace_note import execute_workspace_note


class DummyContext:
    def __init__(self, ws_path: Path, agent_id: str = "cardiology-guide"):
        self.workspace_root = ws_path
        self.agent = type("Agent", (), {"id": agent_id})()


@pytest.fixture
def test_profile_id(client: TestClient) -> str:
    """Provisions a test profile for workspace notes tests."""
    from carefold.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER
    from carefold.db.models import User
    from carefold.db.session import get_session_factory
    import asyncio

    async def _ensure_steward():
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

    asyncio.run(_ensure_steward())
    resp = client.post("/api/profiles", json={"name": "Test Patient", "relationship": "self"})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_workspace_note_preserves_human_readable_title(temp_workspace: Path):
    """Verifies that workspace-note tool preserves human-readable title in frontmatter while slugifying filename."""
    ctx = DummyContext(temp_workspace, agent_id="cardiology-guide")
    import asyncio
    res = asyncio.run(
        execute_workspace_note(
            {
                "title": "Cardiovascular Consultation & Vitals Prep",
                "content": "Check BP daily.\nKeep symptom log.",
            },
            ctx,
        )
    )

    assert res.success is True
    assert res.output["title"] == "cardiovascular-consultation-vitals-prep"
    assert res.output["slug"] == "cardiovascular-consultation-vitals-prep"
    assert res.output["display_title"] == "Cardiovascular Consultation & Vitals Prep"
    assert res.output["filename"] == "cardiovascular-consultation-vitals-prep.md"

    notes_dir = settings.get_notes_dir()
    saved_file = notes_dir / "cardiovascular-consultation-vitals-prep.md"
    assert saved_file.exists()

    content = saved_file.read_text(encoding="utf-8")
    assert 'title: "Cardiovascular Consultation & Vitals Prep"' in content
    assert 'agent_id: "cardiology-guide"' in content
    assert "Check BP daily." in content


def test_workspace_note_escapes_quotes_in_title(temp_workspace: Path):
    """Verifies that special characters and quotes in title are cleanly escaped."""
    ctx = DummyContext(temp_workspace)
    import asyncio
    res = asyncio.run(
        execute_workspace_note(
            {
                "title": 'Dr. O\'Connor\'s "Urgent" Vitals Review',
                "content": "Review immediately.",
            },
            ctx,
        )
    )

    assert res.success is True
    notes_dir = settings.get_notes_dir()
    saved_file = notes_dir / f"{res.output['slug']}.md"
    assert saved_file.exists()

    content = saved_file.read_text(encoding="utf-8")
    assert 'title: "Dr. O\'Connor\'s \\"Urgent\\" Vitals Review"' in content


def test_list_notes_empty_directory(client: TestClient, temp_workspace: Path):
    """Verifies that GET /api/notes returns an empty list when notes directory has no notes."""
    notes_dir = settings.get_notes_dir()
    for f in notes_dir.iterdir():
        if f.is_file():
            f.unlink()

    resp = client.get("/api/notes")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_notes_3_tier_title_resolution(client: TestClient, temp_workspace: Path, test_profile_id: str):
    """Verifies 3-tier title resolution: frontmatter/explicit -> # heading -> title-cased slug."""
    # Note 1: Explicit title (Tier 1)
    res1 = client.post(
        "/api/notes",
        json={
            "slug": "note-one",
            "title": "Preserved Frontmatter Title",
            "content": "# Ignored Heading\nContent 1",
            "type": "visit",
            "profile_id": test_profile_id,
        },
    )
    assert res1.status_code == 201

    # Note 2: Title equals slug -> Body has `# Heading` (Tier 2)
    res2 = client.post(
        "/api/notes",
        json={
            "slug": "note-two",
            "title": "note-two",
            "content": "# First Heading Title\nContent 2",
            "type": "general",
            "profile_id": test_profile_id,
        },
    )
    assert res2.status_code == 201

    # Note 3: Title equals slug -> No heading -> Title-cased slug (Tier 3)
    res3 = client.post(
        "/api/notes",
        json={
            "slug": "sarahs-diabetes-notes",
            "title": "sarahs-diabetes-notes",
            "content": "No headings here. Just advice.",
            "type": "general",
            "profile_id": test_profile_id,
        },
    )
    assert res3.status_code == 201

    resp = client.get("/api/notes")
    assert resp.status_code == 200
    items = resp.json()

    assert len(items) == 3
    slug_map = {item["slug"]: item for item in items}
    assert slug_map["note-one"]["title"] == "Preserved Frontmatter Title"
    assert slug_map["note-one"]["agent"] == "visit"

    assert slug_map["note-two"]["title"] == "First Heading Title"
    assert slug_map["note-two"]["agent"] == "general"

    assert slug_map["sarahs-diabetes-notes"]["title"] == "Sarahs Diabetes Notes"
    assert slug_map["sarahs-diabetes-notes"]["agent"] == "general"


def test_get_note_detail_success(client: TestClient, temp_workspace: Path, test_profile_id: str):
    """Verifies reading note details by slug (with and without .md)."""
    create_res = client.post(
        "/api/notes",
        json={
            "slug": "visit-agenda",
            "title": "Clinic Visit Agenda",
            "content": "# Clinic Visit Agenda\n\n1. Review meds\n2. Discuss lab results\n",
            "type": "visit",
            "profile_id": test_profile_id,
        },
    )
    assert create_res.status_code == 201

    # Without extension
    resp1 = client.get("/api/notes/visit-agenda")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["slug"] == "visit-agenda"
    assert data1["title"] == "Clinic Visit Agenda"
    assert data1["agent"] == "visit"
    assert "1. Review meds" in data1["content"]
    assert "---" in data1["raw_content"]
    assert data1["metadata"]["title"] == "Clinic Visit Agenda"
    assert data1["size_bytes"] > 0

    # With extension
    resp2 = client.get("/api/notes/visit-agenda.md")
    assert resp2.status_code == 200
    assert resp2.json()["slug"] == "visit-agenda"


def test_get_note_detail_not_found(client: TestClient, temp_workspace: Path):
    """Verifies 404 response for non-existent note."""
    resp = client.get("/api/notes/non-existent-note")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.parametrize(
    "traversal_payload",
    [
        "../../etc/passwd",
        "../../attachments/test.txt",
        "..%2f..%2fetc%2fpasswd",
        "/etc/shadow",
        "file:///etc/passwd",
        "note%00.md",
    ],
)
def test_get_note_detail_rejects_path_traversal(
    client: TestClient, temp_workspace: Path, traversal_payload: str
):
    """Verifies path traversal attempts on GET /api/notes/{slug} return 400 Bad Request or 404."""
    resp = client.get(f"/api/notes/{traversal_payload}")
    assert resp.status_code in (400, 404)
    assert resp.status_code != 200
    assert resp.status_code != 500


def test_get_note_detail_rejects_symlink_escape(client: TestClient, temp_workspace: Path, tmp_path: Path):
    """Verifies that symlinks escaping the notes directory are rejected with 400 Bad Request."""
    notes_dir = settings.get_notes_dir()

    # Create external victim file outside workspace
    external_file = tmp_path / "outside_confidential.txt"
    external_file.write_text("CONFIDENTIAL OUTSIDE DATA", encoding="utf-8")

    # Create symlink inside notes_dir pointing to external_file
    symlink_note = notes_dir / "escaping_symlink.md"
    try:
        os.symlink(external_file, symlink_note)
    except OSError:
        pytest.skip("Symlink creation not permitted in this environment")

    resp = client.get("/api/notes/escaping_symlink")
    assert resp.status_code == 400
    assert "invalid note path" in resp.json()["detail"].lower()


def test_list_notes_ignores_escaping_symlink(client: TestClient, temp_workspace: Path, tmp_path: Path, test_profile_id: str):
    """Verifies that symlinks escaping the notes directory are safely ignored by list_notes."""
    notes_dir = settings.get_notes_dir()
    for f in notes_dir.iterdir():
        if f.is_file():
            f.unlink()

    external_file = tmp_path / "outside_secret.md"
    external_file.write_text("# Secret Note\nOutside content", encoding="utf-8")

    symlink_note = notes_dir / "leaked_symlink.md"
    try:
        os.symlink(external_file, symlink_note)
    except OSError:
        pytest.skip("Symlink creation not permitted in this environment")

    # Also add a valid note
    create_res = client.post(
        "/api/notes",
        json={"slug": "valid_note", "title": "Valid Note", "content": "# Valid Note\nInside content", "profile_id": test_profile_id},
    )
    assert create_res.status_code == 201

    resp = client.get("/api/notes")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["slug"] == "valid_note"


@pytest.mark.parametrize(
    "invalid_slug",
    [
        "invalid slug with spaces",
        "invalid!chars",
        "invalid@note",
        "note%00",
        "note.with.dots",
        "note:colon",
        "invalid^slug",
    ],
)
def test_get_note_detail_invalid_slug_validation(
    client: TestClient, temp_workspace: Path, invalid_slug: str
):
    """Verifies that invalid slug formats are rejected with 400 Bad Request."""
    resp = client.get(f"/api/notes/{invalid_slug}")
    assert resp.status_code == 400
    assert "Invalid note slug" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_note_detail_dot_slugs_raise_400():
    """Verifies that dot slugs raise 400 when processed directly by get_note_detail."""
    from fastapi import HTTPException
    from carefold.api.notes import get_note_detail

    for dot_slug in ("..", ".", "", "   "):
        with pytest.raises(HTTPException) as exc_info:
            await get_note_detail(dot_slug)
        assert exc_info.value.status_code == 400
        assert "Invalid note slug" in exc_info.value.detail


