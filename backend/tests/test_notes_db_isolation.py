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

"""Notes Database Isolation & Scoping Test Suite.

Empirically tests:
1. Multi-tenant slug isolation: identical slugs across different users and different profiles.
2. Permission scoping: 'manage' required for updates/deletes; 'view_clinical' vs 'view_paperwork'.
3. Rejection of unassigned or unauthorized profiles (403/404 handling).
4. Path traversal and symlink attack attempts in note slugs and titles.
5. Concurrency: simultaneous creation and updating of notes with identical slugs.
6. Verification that zero .md files are written to disk.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import AsyncIterator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.models import Note, Profile, ProfileAccess
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app


@pytest.fixture
async def notes_challenge_env(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch):
    """Sets up an isolated in-memory DB and local SQL auth provider for adversarial challenge tests."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    sql_auth = SqlAuthAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    monkeypatch.setattr(settings, "workspace_root", temp_workspace)
    set_auth_port(sql_auth)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    try:
        yield {
            "workspace": temp_workspace,
            "auth": sql_auth,
            "session_factory": session_factory,
        }
    finally:
        app.dependency_overrides.clear()
        reset_auth_port()


def _register_user(client: TestClient, email: str, password: str, name: str) -> dict:
    """Helper to register and login a user."""
    client.post(
        "/api/auth/register",
        json={
            "email": "admin@carefold.test",
            "username": "admin",
            "password": "AdminPassword123!",
            "full_name": "System Administrator",
        },
    )
    username = email.split("@")[0].replace(".", "_")
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "username": username, "password": password, "full_name": name},
    )
    assert resp.status_code == 201, resp.text
    login_resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert login_resp.status_code == 200, login_resp.text
    token = login_resp.json()["token"]
    user_info = login_resp.json()["user"]
    return {"token": token, "user": user_info, "headers": {"Authorization": f"Bearer {token}"}}


# ==============================================================================
# Challenge 1: Multi-Tenant Slug Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_challenge_cross_user_identical_slug_isolation(notes_challenge_env):
    """Stress-test: User A and User B create notes with identical slugs in their respective profiles.
    
    Verifies:
    - Both users can have notes with identical slug 'cardio-vitals'.
    - User A's GET /api/notes/cardio-vitals returns User A's note, not User B's.
    - User B's GET /api/notes/cardio-vitals returns User B's note, not User A's.
    - User A's PUT modifies only User A's note; User B's note is unchanged.
    - User A's DELETE removes User A's note; User B's note persists intact.
    - User A subsequently querying the slug cannot read User B's note.
    """
    with TestClient(app) as client:
        user_a = _register_user(client, "alice_slug@test.local", "Password123!", "Alice Slug")
        user_b = _register_user(client, "bob_slug@test.local", "Password123!", "Bob Slug")

        # Create Profile for User A
        pa_resp = client.post("/api/profiles", headers=user_a["headers"], json={"name": "Alice Me", "relationship": "self"})
        assert pa_resp.status_code == 201
        prof_a_id = pa_resp.json()["id"]

        # Create Profile for User B
        pb_resp = client.post("/api/profiles", headers=user_b["headers"], json={"name": "Bob Me", "relationship": "self"})
        assert pb_resp.status_code == 201
        prof_b_id = pb_resp.json()["id"]

        # 1. User A creates note with slug 'cardio-vitals'
        n_a = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={
                "slug": "cardio-vitals",
                "title": "Alice Cardio Vitals",
                "content": "Alice BP: 120/80",
                "profile_id": prof_a_id,
            },
        )
        assert n_a.status_code == 201
        assert n_a.json()["slug"] == "cardio-vitals"
        assert n_a.json()["content"] == "Alice BP: 120/80"

        # 2. User B creates note with IDENTICAL slug 'cardio-vitals'
        n_b = client.post(
            "/api/notes",
            headers=user_b["headers"],
            json={
                "slug": "cardio-vitals",
                "title": "Bob Cardio Vitals",
                "content": "Bob BP: 140/90",
                "profile_id": prof_b_id,
            },
        )
        assert n_b.status_code == 201
        assert n_b.json()["slug"] == "cardio-vitals"
        assert n_b.json()["content"] == "Bob BP: 140/90"

        # 3. Read isolation
        get_a = client.get("/api/notes/cardio-vitals", headers=user_a["headers"])
        assert get_a.status_code == 200
        assert get_a.json()["title"] == "Alice Cardio Vitals"
        assert get_a.json()["content"] == "Alice BP: 120/80"

        get_b = client.get("/api/notes/cardio-vitals", headers=user_b["headers"])
        assert get_b.status_code == 200
        assert get_b.json()["title"] == "Bob Cardio Vitals"
        assert get_b.json()["content"] == "Bob BP: 140/90"

        # 4. Update isolation: Alice updates her note
        put_a = client.put(
            "/api/notes/cardio-vitals",
            headers=user_a["headers"],
            json={"content": "Alice BP Updated: 118/75"},
        )
        assert put_a.status_code == 200
        assert put_a.json()["content"] == "Alice BP Updated: 118/75"

        # Verify Bob's note was NOT touched
        get_b2 = client.get("/api/notes/cardio-vitals", headers=user_b["headers"])
        assert get_b2.status_code == 200
        assert get_b2.json()["content"] == "Bob BP: 140/90"

        # 5. Delete isolation: Alice deletes her note
        del_a = client.delete("/api/notes/cardio-vitals", headers=user_a["headers"])
        assert del_a.status_code == 200
        assert del_a.json()["deleted"] is True

        # Verify Bob's note still exists
        get_b3 = client.get("/api/notes/cardio-vitals", headers=user_b["headers"])
        assert get_b3.status_code == 200
        assert get_b3.json()["content"] == "Bob BP: 140/90"

        # Verify Alice cannot read Bob's note (must return 403 or 404, not Bob's data)
        get_a2 = client.get("/api/notes/cardio-vitals", headers=user_a["headers"])
        assert get_a2.status_code in (403, 404)
        if get_a2.status_code == 200:
            assert False, "CRITICAL: Alice was able to read Bob's note after deleting hers!"


@pytest.mark.asyncio
async def test_challenge_same_user_cross_profile_slug_behavior(notes_challenge_env):
    """Stress-test: Same user creating identical slugs across two different profiles they own.
    
    Verifies how the system resolves or scopes notes when the same user has two profiles.
    """
    with TestClient(app) as client:
        user_a = _register_user(client, "alice_same@test.local", "Password123!", "Alice Same")

        # Create Profile 1 (Child) and Profile 2 (Parent)
        p1 = client.post("/api/profiles", headers=user_a["headers"], json={"name": "Child", "relationship": "child"}).json()["id"]
        p2 = client.post("/api/profiles", headers=user_a["headers"], json={"name": "Parent", "relationship": "parent"}).json()["id"]

        # Note 1 for Child
        n1 = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={"slug": "immunization-history", "title": "Child Vaccines", "content": "MMR received", "profile_id": p1},
        )
        assert n1.status_code == 201

        # Note 2 for Parent with identical requested slug
        n2 = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={"slug": "immunization-history", "title": "Parent Vaccines", "content": "Flu shot received", "profile_id": p2},
        )
        assert n2.status_code == 201

        # Check filtering by profile_id
        list_p1 = client.get(f"/api/notes?profile_id={p1}", headers=user_a["headers"]).json()
        assert len(list_p1) == 1
        assert list_p1[0]["title"] == "Child Vaccines"

        list_p2 = client.get(f"/api/notes?profile_id={p2}", headers=user_a["headers"]).json()
        assert len(list_p2) == 1
        assert list_p2[0]["title"] == "Parent Vaccines"


# ==============================================================================
# Challenge 2: Permission Scoping (manage vs view_clinical vs view_paperwork)
# ==============================================================================

@pytest.mark.asyncio
async def test_challenge_permission_scoping_clinical_vs_paperwork(notes_challenge_env):
    """Stress-test: Comprehensive verification of access levels on clinical notes.
    
    - 'manage': create, read, update, delete
    - 'view_clinical': read, list, but CANNOT create, update, or delete (403)
    - 'view_paperwork': CANNOT read, update, delete, or create (403)
    - Unfiltered GET /api/notes MUST NOT leak notes to 'view_paperwork' user!
    """
    with TestClient(app) as client:
        owner = _register_user(client, "owner_perm@test.local", "Password123!", "Owner Perm")
        manager = _register_user(client, "manager_perm@test.local", "Password123!", "Manager Perm")
        clin_viewer = _register_user(client, "clin_perm@test.local", "Password123!", "Clin Perm")
        paper_viewer = _register_user(client, "paper_perm@test.local", "Password123!", "Paper Perm")

        # Owner creates profile
        prof_resp = client.post("/api/profiles", headers=owner["headers"], json={"name": "Patient X", "relationship": "self"})
        prof_id = prof_resp.json()["id"]

        # Owner grants accesses
        # 1. Manager -> manage
        client.post(
            f"/api/profiles/{prof_id}/access",
            headers=owner["headers"],
            json={"user_id": manager["user"]["id"], "access_level": "manage"},
        )
        # 2. Clin Viewer -> view_clinical
        client.post(
            f"/api/profiles/{prof_id}/access",
            headers=owner["headers"],
            json={"user_id": clin_viewer["user"]["id"], "access_level": "view_clinical"},
        )
        # 3. Paper Viewer -> view_paperwork
        client.post(
            f"/api/profiles/{prof_id}/access",
            headers=owner["headers"],
            json={"user_id": paper_viewer["user"]["id"], "access_level": "view_paperwork"},
        )

        # Owner creates note
        note_resp = client.post(
            "/api/notes",
            headers=owner["headers"],
            json={
                "slug": "chemo-log",
                "title": "Chemotherapy Log",
                "content": "Infusion completed 10am.",
                "type": "clinical_prep",
                "profile_id": prof_id,
            },
        )
        assert note_resp.status_code == 201

        # --- Test 1: Manager permissions ('manage') ---
        # Can read
        assert client.get("/api/notes/chemo-log", headers=manager["headers"]).status_code == 200
        # Can update
        assert client.put(
            "/api/notes/chemo-log",
            headers=manager["headers"],
            json={"content": "Infusion note updated by manager."},
        ).status_code == 200
        # Can create new note
        assert client.post(
            "/api/notes",
            headers=manager["headers"],
            json={"slug": "manager-note", "title": "Manager Note", "content": "Content", "profile_id": prof_id},
        ).status_code == 201
        # Can delete note
        assert client.delete("/api/notes/manager-note", headers=manager["headers"]).status_code == 200

        # --- Test 2: Clinical Viewer permissions ('view_clinical') ---
        # Can read note detail
        assert client.get("/api/notes/chemo-log", headers=clin_viewer["headers"]).status_code == 200
        # Can list notes with profile filter
        assert client.get(f"/api/notes?profile_id={prof_id}", headers=clin_viewer["headers"]).status_code == 200
        # CANNOT update note (403 required)
        up_clin = client.put(
            "/api/notes/chemo-log",
            headers=clin_viewer["headers"],
            json={"content": "Malicious edit by viewer"},
        )
        assert up_clin.status_code == 403, f"Expected 403 for view_clinical update, got {up_clin.status_code}"
        # CANNOT delete note (403 required)
        del_clin = client.delete("/api/notes/chemo-log", headers=clin_viewer["headers"])
        assert del_clin.status_code == 403, f"Expected 403 for view_clinical delete, got {del_clin.status_code}"
        # CANNOT create note (403 required)
        post_clin = client.post(
            "/api/notes",
            headers=clin_viewer["headers"],
            json={"slug": "unauth-clin-note", "title": "Unauth", "content": "Content", "profile_id": prof_id},
        )
        assert post_clin.status_code == 403, f"Expected 403 for view_clinical create, got {post_clin.status_code}"

        # --- Test 3: Paperwork Viewer permissions ('view_paperwork') ---
        # CANNOT read note detail (403 required)
        get_paper = client.get("/api/notes/chemo-log", headers=paper_viewer["headers"])
        assert get_paper.status_code == 403, f"Expected 403 for view_paperwork read, got {get_paper.status_code}"
        # CANNOT list notes with profile filter (403 required)
        list_paper = client.get(f"/api/notes?profile_id={prof_id}", headers=paper_viewer["headers"])
        assert list_paper.status_code == 403, f"Expected 403 for view_paperwork list, got {list_paper.status_code}"
        # CANNOT update note (403 required)
        up_paper = client.put(
            "/api/notes/chemo-log",
            headers=paper_viewer["headers"],
            json={"content": "Malicious edit by paper viewer"},
        )
        assert up_paper.status_code == 403
        # CANNOT delete note (403 required)
        assert client.delete("/api/notes/chemo-log", headers=paper_viewer["headers"]).status_code == 403
        # CANNOT create note (403 required)
        assert client.post(
            "/api/notes",
            headers=paper_viewer["headers"],
            json={"slug": "paper-create", "title": "Paper", "content": "Content", "profile_id": prof_id},
        ).status_code == 403

        # --- Test 4: Unfiltered GET /api/notes scoping check ---
        # Check whether paper_viewer receives Patient X's clinical notes in unfiltered list
        unfiltered_list = client.get("/api/notes", headers=paper_viewer["headers"])
        assert unfiltered_list.status_code == 200
        returned_slugs = [n["slug"] for n in unfiltered_list.json()]
        
        # Scoping assertion: paper_viewer must NOT see chemo-log in unfiltered notes list!
        assert "chemo-log" not in returned_slugs, (
            "SECURITY VULNERABILITY DETECTED: GET /api/notes leaked clinical note "
            "'chemo-log' to a user with only 'view_paperwork' permissions!"
        )


# ==============================================================================
# Challenge 3: Rejection of Unassigned or Unauthorized Profiles
# ==============================================================================

@pytest.mark.asyncio
async def test_challenge_unauthorized_and_nonexistent_profiles(notes_challenge_env):
    """Stress-test: 403 and 404 responses for unauthorized and non-existent profiles."""
    with TestClient(app) as client:
        user_a = _register_user(client, "alice_unauth@test.local", "Password123!", "Alice Unauth")
        user_b = _register_user(client, "bob_unauth@test.local", "Password123!", "Bob Unauth")

        # User A's private profile
        prof_a = client.post("/api/profiles", headers=user_a["headers"], json={"name": "Alice Private", "relationship": "self"}).json()["id"]

        # 1. Non-existent profile ID -> 404
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        res_404_create = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={"title": "Note", "content": "Content", "profile_id": fake_uuid},
        )
        assert res_404_create.status_code == 404

        res_404_list = client.get(f"/api/notes?profile_id={fake_uuid}", headers=user_a["headers"])
        assert res_404_list.status_code == 404

        # 2. Unauthorized profile ID -> 403
        res_403_create = client.post(
            "/api/notes",
            headers=user_b["headers"],
            json={"title": "Intruder Note", "content": "Intrusion", "profile_id": prof_a},
        )
        assert res_403_create.status_code == 403

        res_403_list = client.get(f"/api/notes?profile_id={prof_a}", headers=user_b["headers"])
        assert res_403_list.status_code == 403

        # 3. User A creates note in prof_a, User B attempts update/reassign
        note_res = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={"slug": "secret-alice-note", "title": "Secret", "content": "Top Secret", "profile_id": prof_a},
        )
        assert note_res.status_code == 201

        # User B cannot read or update
        assert client.get("/api/notes/secret-alice-note", headers=user_b["headers"]).status_code in (403, 404)
        assert client.put(
            "/api/notes/secret-alice-note",
            headers=user_b["headers"],
            json={"content": "Hacked"},
        ).status_code in (403, 404)

        # 4. User A attempts to reassign note to non-existent profile -> 404
        reassign_404 = client.put(
            "/api/notes/secret-alice-note",
            headers=user_a["headers"],
            json={"profile_id": fake_uuid},
        )
        assert reassign_404.status_code == 404

        # 5. User A creates unassigned note (profile_id=None)
        unassigned_res = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={"slug": "scratchpad-raw", "title": "Raw Scratchpad", "content": "Scratchpad text"},
        )
        assert unassigned_res.status_code == 201

        # User B cannot read or modify User A's unassigned note
        assert client.get("/api/notes/scratchpad-raw", headers=user_b["headers"]).status_code in (403, 404)
        assert client.put("/api/notes/scratchpad-raw", headers=user_b["headers"], json={"content": "Modified"}).status_code in (403, 404)
        assert client.delete("/api/notes/scratchpad-raw", headers=user_b["headers"]).status_code in (403, 404)


# ==============================================================================
# Challenge 4: Path Traversal & Symlink Attacks
# ==============================================================================

@pytest.mark.parametrize(
    "malicious_slug",
    [
        "../../etc/passwd",
        "..\\..\\windows\\win.ini",
        "..%2f..%2fetc%2fpasswd",
        "%2e%2e%2f%2e%2e%2fpasswd",
        "/etc/shadow",
        "file:///etc/passwd",
        "null_byte%00",
        "null_byte\x00note",
        "slug with spaces",
        "slug!@#$%",
        "slug;rm -rf /",
    ],
)
def test_challenge_path_traversal_in_slug(client: TestClient, malicious_slug: str):
    """Stress-test: Reject traversal payloads and invalid slug characters with 400 or 404."""
    # GET
    try:
        get_res = client.get(f"/api/notes/{malicious_slug}")
        assert get_res.status_code in (400, 404), f"GET allowed malicious slug {malicious_slug}: {get_res.status_code}"
    except Exception as exc:
        assert "InvalidURL" in type(exc).__name__ or "invalid" in str(exc).lower()

    # POST
    try:
        post_res = client.post(
            "/api/notes",
            json={"slug": malicious_slug, "title": "Evil Note", "content": "payload"},
        )
        assert post_res.status_code in (400, 404, 422), f"POST allowed malicious slug {malicious_slug}: {post_res.status_code}"
    except Exception as exc:
        assert "InvalidURL" in type(exc).__name__ or "invalid" in str(exc).lower()


def test_challenge_traversal_in_title_and_symlink_defense(client: TestClient, tmp_path: Path):
    """Stress-test: Path traversal in note title and symlink defense on disk."""
    # 1. Traversal attempt in title (auto-generated slug)
    res = client.post(
        "/api/notes",
        json={"title": "../../../etc/passwd", "content": "Test content"},
    )
    assert res.status_code == 201
    created_slug = res.json()["slug"]
    # Verify slug was sanitized and contains no path separators
    assert "/" not in created_slug
    assert "\\" not in created_slug
    assert ".." not in created_slug

    # 2. Symlink defense
    notes_dir = settings.get_notes_dir()
    notes_dir.mkdir(parents=True, exist_ok=True)
    outside_target = tmp_path / "sensitive_host_file.txt"
    outside_target.write_text("SENSITIVE DATA", encoding="utf-8")

    symlink_file = notes_dir / "evil_symlink.md"
    try:
        os.symlink(outside_target, symlink_file)
    except OSError:
        pytest.skip("Symlink creation not supported")

    # Attempt to read via API
    resp = client.get("/api/notes/evil_symlink")
    assert resp.status_code == 400
    assert "symlink escape detected" in resp.json()["detail"].lower()


# ==============================================================================
# Challenge 5: Concurrency / Race Conditions
# ==============================================================================

@pytest.mark.asyncio
async def test_challenge_concurrent_note_creation_identical_slugs(notes_challenge_env):
    """Stress-test: Simultaneous creation of notes with identical slugs."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as aclient:
        # Register admin & user
        await aclient.post(
            "/api/auth/register",
            json={
                "email": "admin@carefold.test",
                "username": "admin",
                "password": "AdminPassword123!",
                "full_name": "System Administrator",
            },
        )
        await aclient.post(
            "/api/auth/register",
            json={
                "email": "alice_conc@test.local",
                "username": "alice_conc",
                "password": "Password123!",
                "full_name": "Alice Concurrency",
            },
        )
        login_res = await aclient.post(
            "/api/auth/login",
            json={"username": "alice_conc", "password": "Password123!"},
        )
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Auto-provision primary profile
        p_resp = await aclient.post("/api/profiles", headers=headers, json={"name": "Me", "relationship": "self"})
        prof_id = p_resp.json()["id"]

        async def post_note(i: int):
            return await aclient.post(
                "/api/notes",
                headers=headers,
                json={
                    "slug": "concurrent-race-slug",
                    "title": f"Race Note {i}",
                    "content": f"Content from worker {i}",
                    "profile_id": prof_id,
                },
            )

        responses = await asyncio.gather(*[post_note(i) for i in range(5)])

        # All 5 requests should succeed (201) without crashing (no 500 error)
        status_codes = [r.status_code for r in responses]
        assert all(code == 201 for code in status_codes), f"Expected all 201, got: {status_codes}"

        # Reading the slug should not crash with MultipleResultsFound
        get_res = await aclient.get("/api/notes/concurrent-race-slug", headers=headers)
        assert get_res.status_code == 200

        # Updating the slug should not crash
        put_res = await aclient.put(
            "/api/notes/concurrent-race-slug",
            headers=headers,
            json={"content": "Updated after race"},
        )
        assert put_res.status_code == 200


@pytest.mark.asyncio
async def test_challenge_concurrent_note_updates(notes_challenge_env):
    """Stress-test: Simultaneous updating of the same note."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as aclient:
        await aclient.post(
            "/api/auth/register",
            json={
                "email": "admin@carefold.test",
                "username": "admin",
                "password": "AdminPassword123!",
                "full_name": "System Administrator",
            },
        )
        await aclient.post(
            "/api/auth/register",
            json={
                "email": "alice_upd_conc@test.local",
                "username": "alice_upd_conc",
                "password": "Password123!",
                "full_name": "Alice Upd Concurrency",
            },
        )
        login_res = await aclient.post(
            "/api/auth/login",
            json={"username": "alice_upd_conc", "password": "Password123!"},
        )
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create note
        init_res = await aclient.post(
            "/api/notes",
            headers=headers,
            json={"slug": "update-race", "title": "Update Race Note", "content": "Initial"},
        )
        assert init_res.status_code == 201

        async def put_note(i: int):
            return await aclient.put(
                "/api/notes/update-race",
                headers=headers,
                json={"content": f"Concurrent update {i}"},
            )

        responses = await asyncio.gather(*[put_note(i) for i in range(5)])
        assert all(r.status_code == 200 for r in responses)

        # Final GET succeeds
        final_get = await aclient.get("/api/notes/update-race", headers=headers)
        assert final_get.status_code == 200
        assert "Concurrent update" in final_get.json()["content"]


# ==============================================================================
# Challenge 6: Zero .md files written outside test sandboxes
# ==============================================================================

@pytest.mark.asyncio
async def test_challenge_zero_loose_md_files(notes_challenge_env):
    """Stress-test: Zero .md files created during CRUD operations."""
    notes_dir = settings.get_notes_dir()
    initial_mds = list(notes_dir.glob("**/*.md"))

    with TestClient(app) as client:
        user = _register_user(client, "zero_md@test.local", "Password123!", "Zero MD")

        # 1. Create multiple notes
        for i in range(5):
            client.post(
                "/api/notes",
                headers=user["headers"],
                json={"title": f"Zero MD Note {i}", "content": f"Content {i}"},
            )

        # Invariant check
        post_create_mds = list(notes_dir.glob("**/*.md"))
        assert len(post_create_mds) == len(initial_mds), (
            f"Found new .md files written to disk! {post_create_mds}"
        )
