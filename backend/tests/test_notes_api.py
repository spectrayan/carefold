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


def test_list_notes_3_tier_title_resolution(client: TestClient, temp_workspace: Path):
    """Verifies 3-tier title resolution: frontmatter -> # heading -> title-cased slug."""
    notes_dir = settings.get_notes_dir()
    for f in notes_dir.iterdir():
        if f.is_file():
            f.unlink()

    # Note 1: Frontmatter title (Tier 1)
    (notes_dir / "note-one.md").write_text(
        "---\n"
        'title: "Preserved Frontmatter Title"\n'
        'created_at: "2026-10-08T10:00:00+00:00"\n'
        'agent_id: "derma-guide"\n'
        "---\n\n"
        "# Ignored Heading\nContent 1",
        encoding="utf-8",
    )

    # Note 2: Frontmatter title equals slug -> Body has `# Heading` (Tier 2)
    (notes_dir / "note-two.md").write_text(
        "---\n"
        'title: "note-two"\n'
        'created_at: "2026-10-08T09:00:00+00:00"\n'
        'agent_id: "visit-steward"\n'
        "---\n\n"
        "# First Heading Title\nContent 2",
        encoding="utf-8",
    )

    # Note 3: Frontmatter title equals slug -> No heading -> Title-cased slug (Tier 3)
    (notes_dir / "sarahs-diabetes-notes.md").write_text(
        "---\n"
        'title: "sarahs-diabetes-notes"\n'
        'created_at: "2026-10-08T08:00:00+00:00"\n'
        'agent_id: "visit-steward"\n'
        "---\n\n"
        "No headings here. Just advice.",
        encoding="utf-8",
    )

    # Ignored files: dotfiles and non-md files
    (notes_dir / ".hidden-note.md").write_text("hidden", encoding="utf-8")
    (notes_dir / "readme.txt").write_text("text", encoding="utf-8")

    resp = client.get("/api/notes")
    assert resp.status_code == 200
    items = resp.json()

    assert len(items) == 3
    # Check sorting: newest first
    assert items[0]["slug"] == "note-one"
    assert items[0]["title"] == "Preserved Frontmatter Title"
    assert items[0]["agent"] == "derma-guide"

    assert items[1]["slug"] == "note-two"
    assert items[1]["title"] == "First Heading Title"
    assert items[1]["agent"] == "visit-steward"

    assert items[2]["slug"] == "sarahs-diabetes-notes"
    assert items[2]["title"] == "Sarahs Diabetes Notes"
    assert items[2]["agent"] == "visit-steward"


def test_get_note_detail_success(client: TestClient, temp_workspace: Path):
    """Verifies reading note details by slug (with and without .md)."""
    notes_dir = settings.get_notes_dir()
    (notes_dir / "visit-agenda.md").write_text(
        "---\n"
        'title: "Clinic Visit Agenda"\n'
        'created_at: "2026-10-08T12:00:00+00:00"\n'
        'agent_id: "cardiology-guide"\n'
        "---\n\n"
        "# Clinic Visit Agenda\n\n1. Review meds\n2. Discuss lab results\n",
        encoding="utf-8",
    )

    # Without extension
    resp1 = client.get("/api/notes/visit-agenda")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["slug"] == "visit-agenda"
    assert data1["title"] == "Clinic Visit Agenda"
    assert data1["agent"] == "cardiology-guide"
    assert data1["created_at"] == "2026-10-08T12:00:00+00:00"
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
