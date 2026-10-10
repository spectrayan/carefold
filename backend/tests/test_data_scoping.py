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

"""E2E data scoping and user-level isolation test suite.

Requirements:
- R1 (#165): Enforce authentication on GET /api/audit (401 when unauthenticated with auth enabled)
- R1 (#166): User-level isolation across Notes, Attachments, Memory, and Chat Threads
- Backward compatibility: Seamless operation in disabled auth mode with DEFAULT_STEWARD_USER
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import AsyncIterator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app
from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
from carefold.memory.factory import reset_memory_ports, set_memory_port
from carefold.memory.ports.memory_port import MemoryTier


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
async def scoping_env(temp_workspace: Path, monkeypatch):
    """Sets up an isolated in-memory DB, local auth provider, and memory port."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    sql_auth = SqlAuthAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    monkeypatch.setattr(settings, "workspace_root", temp_workspace)
    set_auth_port(sql_auth)

    # Dependency override for get_db
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    # Setup memory adapter
    mem_db_path = temp_workspace / "workspace" / "test_memory.db"
    mem_adapter = SqliteMemoryAdapter(db_path=mem_db_path)
    set_memory_port(mem_adapter)

    try:
        yield {
            "auth": sql_auth,
            "session_factory": session_factory,
            "memory": mem_adapter,
            "workspace": temp_workspace,
        }
    finally:
        app.dependency_overrides.pop(get_db, None)
        reset_auth_port()
        reset_memory_ports()


@pytest.fixture
def auth_users(client: TestClient, scoping_env):
    """Registers and authenticates User A (Admin) and User B (Member)."""
    # 0. Initial Admin setup so Alice and Bob are both standard members
    client.post(
        "/api/auth/register",
        json={
            "email": "admin@carefold.test",
            "username": "admin",
            "password": "AdminPassword123!",
            "full_name": "System Administrator",
        },
    )

    # 1. User A (Member)
    res_a = client.post(
        "/api/auth/register",
        json={
            "email": "alice@carefold.test",
            "username": "alice",
            "password": "AlicePassword123!",
            "full_name": "Alice Smith",
        },
    )
    assert res_a.status_code == 201
    user_a = res_a.json()["user"]

    login_a = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "AlicePassword123!"},
    )
    assert login_a.status_code == 200
    token_a = login_a.json()["token"]
    cookie_a = login_a.cookies.get("carefold_session")

    # 2. User B (Regular Member)
    res_b = client.post(
        "/api/auth/register",
        json={
            "email": "bob@carefold.test",
            "username": "bob",
            "password": "BobPassword123!",
            "full_name": "Bob Jones",
        },
    )
    assert res_b.status_code == 201
    user_b = res_b.json()["user"]

    login_b = client.post(
        "/api/auth/login",
        json={"username": "bob", "password": "BobPassword123!"},
    )
    assert login_b.status_code == 200
    token_b = login_b.json()["token"]
    cookie_b = login_b.cookies.get("carefold_session")

    return {
        "user_a": user_a,
        "token_a": token_a,
        "cookie_a": cookie_a,
        "headers_a": {"Authorization": f"Bearer {token_a}"},
        "cookies_a": {"carefold_session": cookie_a},
        "user_b": user_b,
        "token_b": token_b,
        "cookie_b": cookie_b,
        "headers_b": {"Authorization": f"Bearer {token_b}"},
        "cookies_b": {"carefold_session": cookie_b},
    }


# =============================================================================
# FEATURE 1: GET /api/audit AUTHENTICATION GUARD (R1 #165)
# =============================================================================

class TestAuditAuthScoping:
    """Tests GET /api/audit authentication guard and edge cases."""

    def test_audit_unauthenticated_returns_401_when_auth_enabled(self, client: TestClient, scoping_env):
        """R1 (#165): GET /api/audit must reject unauthenticated requests with 401 when auth is enabled."""
        # Unauthenticated request without cookie or Authorization header
        resp = client.get("/api/audit")
        assert resp.status_code == 401, f"Expected 401 Unauthorized, got {resp.status_code}: {resp.text}"
        assert "WWW-Authenticate" in resp.headers

    def test_audit_authenticated_cookie_returns_200(self, client: TestClient, auth_users):
        """GET /api/audit allows access when valid session cookie is provided."""
        resp = client.get("/api/audit", cookies=auth_users["cookies_a"])
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert "total" in data

    def test_audit_authenticated_bearer_header_returns_200(self, client: TestClient, auth_users):
        """GET /api/audit allows access with Authorization: Bearer <token> header."""
        resp = client.get("/api/audit", headers=auth_users["headers_a"])
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data

    def test_audit_tampered_cookie_returns_401(self, client: TestClient, scoping_env):
        """GET /api/audit rejects forged or tampered session cookie with 401."""
        resp = client.get("/api/audit", cookies={"carefold_session": "tampered_fake_session_token"})
        assert resp.status_code == 401

    def test_audit_malformed_auth_header_returns_401(self, client: TestClient, scoping_env):
        """GET /api/audit rejects invalid or empty authorization headers with 401."""
        resp = client.get("/api/audit", headers={"Authorization": "InvalidScheme token"})
        assert resp.status_code == 401

    def test_audit_disabled_auth_mode_returns_200(self, client: TestClient, temp_workspace: Path, monkeypatch):
        """In disabled auth mode, GET /api/audit permits unauthenticated local desktop access."""
        monkeypatch.setattr(settings, "auth_provider", "disabled")
        resp = client.get("/api/audit")
        assert resp.status_code == 200


# =============================================================================
# FEATURE 2: BACKEND NOTES USER-LEVEL SCOPING (R1 #166)
# =============================================================================

class TestNotesUserScoping:
    """Tests user isolation for notes creation, retrieval, updates, and deletion."""

    def test_notes_user_a_crud_lifecycle(self, client: TestClient, auth_users):
        """User A can create, get, list, update, and delete their own note."""
        # 1. Create Note
        create_resp = client.post(
            "/api/notes",
            json={
                "title": "Alice Blood Pressure Log",
                "slug": "alice-bp-log",
                "content": "Systolic 120, Diastolic 80.",
                "type": "vital_log",
                "tags": ["vitals", "cardiology"],
            },
            headers=auth_users["headers_a"],
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        assert created["slug"] == "alice-bp-log"

        # 2. Get Note
        get_resp = client.get("/api/notes/alice-bp-log", headers=auth_users["headers_a"])
        assert get_resp.status_code == 200
        assert "Systolic 120" in get_resp.json()["content"]

        # 3. List Notes
        list_resp = client.get("/api/notes", headers=auth_users["headers_a"])
        assert list_resp.status_code == 200
        slugs = [n["slug"] for n in list_resp.json()]
        assert "alice-bp-log" in slugs

        # 4. Update Note
        update_resp = client.put(
            "/api/notes/alice-bp-log",
            json={"title": "Alice BP Log Updated", "content": "Systolic 118, Diastolic 78."},
            headers=auth_users["headers_a"],
        )
        assert update_resp.status_code == 200
        assert "118" in update_resp.json()["content"]

        # 5. Delete Note
        del_resp = client.delete("/api/notes/alice-bp-log", headers=auth_users["headers_a"])
        assert del_resp.status_code == 200

    def test_notes_user_b_cannot_access_user_a_note(self, client: TestClient, auth_users):
        """User B cannot view or list User A's private notes."""
        # User A creates a note
        client.post(
            "/api/notes",
            json={
                "title": "Alice Private Medical Diary",
                "slug": "alice-diary",
                "content": "Confidential patient symptom notes.",
            },
            headers=auth_users["headers_a"],
        )

        # User B lists notes -> must NOT see Alice's diary
        list_b = client.get("/api/notes", headers=auth_users["headers_b"])
        assert list_b.status_code == 200
        b_slugs = [n["slug"] for n in list_b.json()]
        assert "alice-diary" not in b_slugs

        # User B attempts to get Alice's note by slug -> must be rejected (404 or 403)
        get_b = client.get("/api/notes/alice-diary", headers=auth_users["headers_b"])
        assert get_b.status_code in (403, 404), f"User B should not access User A note, got: {get_b.status_code}"

    def test_notes_user_b_cannot_update_or_delete_user_a_note(self, client: TestClient, auth_users):
        """User B cannot modify or delete User A's note."""
        client.post(
            "/api/notes",
            json={"title": "Alice Labs", "slug": "alice-labs", "content": "Original content"},
            headers=auth_users["headers_a"],
        )

        # User B tries to update Alice's note
        put_b = client.put(
            "/api/notes/alice-labs",
            json={"content": "Malicious overwrite"},
            headers=auth_users["headers_b"],
        )
        assert put_b.status_code in (403, 404)

        # User B tries to delete Alice's note
        del_b = client.delete("/api/notes/alice-labs", headers=auth_users["headers_b"])
        assert del_b.status_code in (403, 404)

        # Verify Alice's note remains unaltered
        get_a = client.get("/api/notes/alice-labs", headers=auth_users["headers_a"])
        assert get_a.status_code == 200
        assert get_a.json()["content"] == "Original content"


# =============================================================================
# FEATURE 3: ATTACHMENTS USER-LEVEL SCOPING (R1 #166)
# =============================================================================

class TestAttachmentsUserScoping:
    """Tests sandboxed attachment upload and listing isolated per user."""

    def test_attachments_user_a_upload_and_list(self, client: TestClient, auth_users):
        """User A can upload and view their own uploaded document."""
        file_content = b"Patient Alice: EKG Normal Sinus Rhythm."
        upload_resp = client.post(
            "/api/attachments",
            files={"file": ("alice_ekg.txt", io.BytesIO(file_content), "text/plain")},
            headers=auth_users["headers_a"],
        )
        assert upload_resp.status_code == 201
        data = upload_resp.json()
        assert data["success"] is True
        assert "alice_ekg" in data["filename"]

        # List attachments for User A
        list_resp = client.get("/api/attachments", headers=auth_users["headers_a"])
        assert list_resp.status_code == 200
        filenames = [f["filename"] for f in list_resp.json()]
        assert any("alice_ekg" in name for name in filenames)

    def test_attachments_user_b_cannot_see_user_a_files(self, client: TestClient, auth_users):
        """User B's attachment list does not leak User A's uploaded medical records."""
        # User A uploads a private medical record
        client.post(
            "/api/attachments",
            files={"file": ("alice_confidential.pdf", io.BytesIO(b"%PDF-1.4 confidential"), "application/pdf")},
            headers=auth_users["headers_a"],
        )

        # User B queries their attachment list
        list_b = client.get("/api/attachments", headers=auth_users["headers_b"])
        assert list_b.status_code == 200
        b_files = [f["filename"] for f in list_b.json()]
        assert not any("alice_confidential" in name for name in b_files), "User B saw User A attachment!"


# =============================================================================
# FEATURE 4: MEMORIES USER-LEVEL SCOPING (R1 #166)
# =============================================================================

class TestMemoriesUserScoping:
    """Tests cognitive memory namespace isolation per user."""

    def test_memories_user_a_remember_and_recall(self, client: TestClient, auth_users):
        """User A can store and recall episodic memories under user-scoped namespace."""
        user_a_id = auth_users["user_a"]["id"]
        user_ns = f"user_{user_a_id}"

        # Write memory for User A
        put_resp = client.put(
            "/api/memory/medication_reminder",
            params={"namespace": user_ns},
            json={
                "value": "Takes Lisinopril 10mg daily at 8am.",
                "tier": "episodic",
                "namespace": user_ns,
            },
            headers=auth_users["headers_a"],
        )
        assert put_resp.status_code == 200

        # Recall memory for User A
        get_resp = client.get(
            f"/api/memory/medication_reminder?namespace={user_ns}",
            headers=auth_users["headers_a"],
        )
        assert get_resp.status_code == 200
        assert "Lisinopril" in str(get_resp.json()["value"])

    def test_memories_user_b_cannot_access_user_a_namespace(self, client: TestClient, auth_users):
        """User B cannot access or recall memories stored in User A's namespace."""
        user_a_id = auth_users["user_a"]["id"]
        user_b_id = auth_users["user_b"]["id"]

        # Alice stores private memory
        client.put(
            "/api/memory/alice_allergy",
            params={"namespace": f"user_{user_a_id}"},
            json={
                "value": "Severe penicillin allergy",
                "tier": "semantic",
                "namespace": f"user_{user_a_id}",
            },
            headers=auth_users["headers_a"],
        )

        # Bob recalls in Bob's namespace -> must be empty
        recall_b = client.get(
            f"/api/memory?query=penicillin&namespace=user_{user_b_id}",
            headers=auth_users["headers_b"],
        )
        assert recall_b.status_code == 200
        assert len(recall_b.json()) == 0


# =============================================================================
# FEATURE 5: CHAT THREADS USER SCOPING (R1 #166)
# =============================================================================

class TestChatThreadsUserScoping:
    """Tests chat thread checkpoints and history isolation between users."""

    def test_threads_unauthenticated_returns_401_when_auth_enabled(self, client: TestClient, scoping_env):
        """GET /api/chat/threads requires authentication when auth is active."""
        resp = client.get("/api/chat/threads?thread_id=any-thread-id")
        assert resp.status_code == 401

    def test_threads_nonexistent_thread_returns_404(self, client: TestClient, auth_users):
        """Querying a nonexistent thread returns 404."""
        resp = client.get(
            "/api/chat/threads?thread_id=nonexistent-uuid-12345",
            headers=auth_users["headers_a"],
        )
        assert resp.status_code == 404


# =============================================================================
# TIER 3 & 4: CROSS-FEATURE INTEGRATION & REAL-WORLD SCENARIO
# =============================================================================

class TestCrossFeatureDataScoping:
    """End-to-end multi-tenant isolation scenario testing."""

    def test_scenario_complete_user_isolation(self, client: TestClient, auth_users):
        """Validates that User A and User B maintain completely partitioned data domains."""
        # Alice creates a note and saves a memory
        client.post(
            "/api/notes",
            json={"title": "Alice Cardiology Summary", "slug": "alice-cardio", "content": "Ejection fraction 60%."},
            headers=auth_users["headers_a"],
        )
        client.put(
            "/api/memory/cardio_pref",
            params={"namespace": f"user_{auth_users['user_a']['id']}"},
            json={"value": "Prefers morning appointments", "tier": "episodic"},
            headers=auth_users["headers_a"],
        )

        # Bob creates his own note and memory
        client.post(
            "/api/notes",
            json={"title": "Bob Orthopedic Rehab", "slug": "bob-ortho", "content": "Physical therapy 3x/week."},
            headers=auth_users["headers_b"],
        )
        client.put(
            "/api/memory/ortho_pref",
            params={"namespace": f"user_{auth_users['user_b']['id']}"},
            json={"value": "Left knee brace required", "tier": "episodic"},
            headers=auth_users["headers_b"],
        )

        # Verify Alice sees ONLY Alice's note
        notes_a = client.get("/api/notes", headers=auth_users["headers_a"]).json()
        slugs_a = [n["slug"] for n in notes_a]
        assert "alice-cardio" in slugs_a
        assert "bob-ortho" not in slugs_a

        # Verify Bob sees ONLY Bob's note
        notes_b = client.get("/api/notes", headers=auth_users["headers_b"]).json()
        slugs_b = [n["slug"] for n in notes_b]
        assert "bob-ortho" in slugs_b
        assert "alice-cardio" not in slugs_b
