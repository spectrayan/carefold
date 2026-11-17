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
    def __init__(self, ws_path: Path, agent_id: str = "heart-care-coordinator"):
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
    ctx = DummyContext(temp_workspace, agent_id="heart-care-coordinator")
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
    assert 'agent_id: "heart-care-coordinator"' in content
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
    from carefold.errors import YarvelleError

    for dot_slug in ("..", ".", "", "   "):
        with pytest.raises((HTTPException, YarvelleError)) as exc_info:
            await get_note_detail(dot_slug)
        assert exc_info.value.status_code == 400
        assert "Invalid note slug" in exc_info.value.detail


ALL_NOTE_CATEGORIES = [
    "visit_prep",
    "medication_notes",
    "insurance_call",
    "symptom_log",
    "after_visit",
    "scratchpad",
    "general",
    "visit",
    "symptom",
    "question",
    "school",
]


@pytest.mark.parametrize("category", ALL_NOTE_CATEGORIES)
def test_notes_creation_all_categories_201(client: TestClient, test_profile_id: str, category: str):
    """Verifies notes creation across all 11 categories succeeds with 201 for both /api/notes and /api/profiles/{id}/notes."""
    # 1. Test POST /api/notes (workspace notes endpoint)
    slug1 = f"note-ws-{category}"
    res1 = client.post(
        "/api/notes",
        json={
            "slug": slug1,
            "title": f"Workspace Note {category}",
            "content": f"# Header\nContent for {category}",
            "type": category,
            "profile_id": test_profile_id,
        },
    )
    assert res1.status_code == 201, f"Failed creating /api/notes with category {category}: {res1.text}"
    data1 = res1.json()
    assert data1["type"] == category
    assert data1["agent"] == category
    assert data1["profile_id"] == test_profile_id

    # Verify retrieval
    get_res1 = client.get(f"/api/notes/{slug1}")
    assert get_res1.status_code == 200
    assert get_res1.json()["type"] == category

    # 2. Test POST /api/profiles/{profile_id}/notes (profile typed notes endpoint)
    slug2 = f"note-prof-{category}"
    res2 = client.post(
        f"/api/profiles/{test_profile_id}/notes",
        json={
            "slug": slug2,
            "title": f"Profile Note {category}",
            "content": f"Detailed content for {category}",
            "type": category,
        },
    )
    assert res2.status_code == 201, f"Failed creating /api/profiles/{{id}}/notes with category {category}: {res2.text}"
    data2 = res2.json()
    assert data2["type"] == category
    assert data2["profile_id"] == test_profile_id

    # Verify retrieval
    get_res2 = client.get(f"/api/profiles/{test_profile_id}/notes/{slug2}")
    assert get_res2.status_code == 200
    assert get_res2.json()["type"] == category


def test_notes_filtering_by_category_and_family_aliases(client: TestClient, test_profile_id: str):
    """Verifies filtering by category and bidirectional alias families (visit <-> visit_prep, symptom <-> symptom_log)."""
    # Create notes in profile
    notes_data = [
        ("filter-vp", "Visit Prep Agenda", "visit_prep"),
        ("filter-v", "Visit Clinical Exam", "visit"),
        ("filter-sl", "Symptom Tracking Log", "symptom_log"),
        ("filter-s", "Symptom Flare", "symptom"),
        ("filter-med", "Medication List Review", "medication_notes"),
        ("filter-ins", "Insurance Denial Call", "insurance_call"),
    ]
    for slug, title, ntype in notes_data:
        res = client.post(
            f"/api/profiles/{test_profile_id}/notes",
            json={"slug": slug, "title": title, "content": f"Content for {title}", "type": ntype},
        )
        assert res.status_code == 201

    # 1. Filter by visit_prep -> returns both visit_prep and visit
    res_vp = client.get(f"/api/profiles/{test_profile_id}/notes?type=visit_prep")
    assert res_vp.status_code == 200
    vp_slugs = {n["slug"] for n in res_vp.json()["notes"]}
    assert "filter-vp" in vp_slugs
    assert "filter-v" in vp_slugs
    assert "filter-sl" not in vp_slugs

    # 2. Filter by visit -> returns both visit and visit_prep
    res_v = client.get(f"/api/profiles/{test_profile_id}/notes?type=visit")
    assert res_v.status_code == 200
    v_slugs = {n["slug"] for n in res_v.json()["notes"]}
    assert "filter-vp" in v_slugs
    assert "filter-v" in v_slugs

    # 3. Filter by symptom_log -> returns both symptom_log and symptom
    res_sl = client.get(f"/api/profiles/{test_profile_id}/notes?type=symptom_log")
    assert res_sl.status_code == 200
    sl_slugs = {n["slug"] for n in res_sl.json()["notes"]}
    assert "filter-sl" in sl_slugs
    assert "filter-s" in sl_slugs
    assert "filter-vp" not in sl_slugs

    # 4. Filter by symptom -> returns both symptom and symptom_log
    res_s = client.get(f"/api/profiles/{test_profile_id}/notes?type=symptom")
    assert res_s.status_code == 200
    s_slugs = {n["slug"] for n in res_s.json()["notes"]}
    assert "filter-sl" in s_slugs
    assert "filter-s" in s_slugs

    # 5. Filter by medication_notes on /api/profiles/{id}/notes
    res_med = client.get(f"/api/profiles/{test_profile_id}/notes?type=medication_notes")
    assert res_med.status_code == 200
    med_slugs = {n["slug"] for n in res_med.json()["notes"]}
    assert "filter-med" in med_slugs
    assert "filter-ins" not in med_slugs

    # 6. Filter by insurance_call on /api/profiles/{id}/notes
    res_ins = client.get(f"/api/profiles/{test_profile_id}/notes?type=insurance_call")
    assert res_ins.status_code == 200
    ins_slugs = {n["slug"] for n in res_ins.json()["notes"]}
    assert "filter-ins" in ins_slugs
    assert "filter-med" not in ins_slugs


def test_notes_update_and_patch_lifecycle(client: TestClient, test_profile_id: str):
    """Verifies updating and patching notes with new note categories, legacy aliases, and deletion."""
    # Create initial note
    slug = "lifecycle-note"
    res = client.post(
        f"/api/profiles/{test_profile_id}/notes",
        json={"slug": slug, "title": "Lifecycle Note", "content": "Initial content", "type": "visit_prep"},
    )
    assert res.status_code == 201

    # 1. Update via PUT /api/notes/{slug} with medication_notes
    put_res = client.put(
        f"/api/notes/{slug}",
        json={"title": "Updated Lifecycle Note", "content": "New content", "type": "medication_notes"},
    )
    assert put_res.status_code == 200
    assert put_res.json()["type"] == "medication_notes"

    # 2. Update via PUT with legacy alias clinical_prep -> maps to question
    put_legacy = client.put(
        f"/api/notes/{slug}",
        json={"type": "clinical_prep"},
    )
    assert put_legacy.status_code == 200
    assert put_legacy.json()["type"] == "question"

    # 3. Patch via PATCH /api/profiles/{profile_id}/notes/{slug} with insurance_call
    patch_res = client.patch(
        f"/api/profiles/{test_profile_id}/notes/{slug}",
        json={"type": "insurance_call", "content": "Insurance details"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["type"] == "insurance_call"

    # 4. Delete via DELETE /api/profiles/{profile_id}/notes/{slug}
    del_res = client.delete(f"/api/profiles/{test_profile_id}/notes/{slug}")
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True

    # 5. Subsequent GET returns 404
    get_res = client.get(f"/api/profiles/{test_profile_id}/notes/{slug}")
    assert get_res.status_code == 404


def test_notes_profile_scoping_rules_preserved(client: TestClient, test_profile_id: str):
    """Verifies that profile isolation and scoping rules are preserved across new note categories."""
    # Create second profile
    resp2 = client.post("/api/profiles", json={"name": "Second Profile", "relationship": "child"})
    assert resp2.status_code == 201
    profile_b_id = resp2.json()["id"]

    # Create note in Profile A
    slug = "profile-a-secret-note"
    create_res = client.post(
        f"/api/profiles/{test_profile_id}/notes",
        json={"slug": slug, "title": "Profile A Note", "content": "Strictly confidential", "type": "visit_prep"},
    )
    assert create_res.status_code == 201

    # Profile B cannot get Profile A's note
    get_res = client.get(f"/api/profiles/{profile_b_id}/notes/{slug}")
    assert get_res.status_code == 404

    # Profile B cannot patch Profile A's note
    patch_res = client.patch(
        f"/api/profiles/{profile_b_id}/notes/{slug}",
        json={"title": "Hacked Title", "type": "medication_notes"},
    )
    assert patch_res.status_code == 404

    # Profile B cannot delete Profile A's note
    del_res = client.delete(f"/api/profiles/{profile_b_id}/notes/{slug}")
    assert del_res.status_code == 404

    # Listing notes for Profile B does not leak Profile A's note
    list_res = client.get(f"/api/profiles/{profile_b_id}/notes")
    assert list_res.status_code == 200
    b_slugs = [n["slug"] for n in list_res.json()["notes"]]
    assert slug not in b_slugs



