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

"""Data Scoping Security Test Suite.

Adversarially probes:
1. Probe GET /api/audit unauthenticated (401, header formats, tampered cookies, disabled mode)
2. Probe cross-tenant notes isolation (CRUD, cross-user slug clash, path traversal)
3. Probe cross-tenant attachments isolation (listing, cross-tenant file download/read)
4. Probe cross-tenant memory isolation (namespace spoofing, recall, update, delete, bulk wipe)
5. Probe cross-tenant chat threads (unauthenticated, cross-tenant read/append, 403/404)
6. Probe backward compatibility in disabled auth mode across all domains
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
from carefold.tools.attach_read import execute_attach_read


class DummyContext:
    def __init__(self, workspace_root: Path, user_id: str | None = None):
        self.workspace_root = workspace_root
        self.user_id = user_id


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

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

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
        await engine.dispose()


@pytest.fixture
def auth_users(client: TestClient, scoping_env):
    """Registers and authenticates User A (Alice, member), User B (Bob, member), and Admin."""
    # 0. Initial Admin
    client.post(
        "/api/auth/register",
        json={
            "email": "admin@carefold.test",
            "username": "admin",
            "password": "AdminPassword123!",
            "full_name": "System Administrator",
        },
    )

    # 1. User A (Alice - Member)
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

    # 2. User B (Bob - Member)
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
# PROBE 1: GET /api/audit UNATHENTICATED 401 & EDGE CASES
# =============================================================================

class TestProbeAuditAuth:
    """Probe 1: Adversarially tests authentication boundaries on GET /api/audit."""

    def test_audit_unauthenticated_without_credentials_yields_401(self, client: TestClient, scoping_env):
        resp = client.get("/api/audit")
        assert resp.status_code == 401
        assert "WWW-Authenticate" in resp.headers
        assert "Bearer" in resp.headers["WWW-Authenticate"]

    def test_audit_tampered_bearer_token_yields_401(self, client: TestClient, scoping_env):
        resp = client.get("/api/audit", headers={"Authorization": "Bearer totally_fabricated_token_12345"})
        assert resp.status_code == 401

    def test_audit_malformed_auth_header_format_yields_401(self, client: TestClient, scoping_env):
        resp = client.get("/api/audit", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 401

    def test_audit_tampered_cookie_yields_401(self, client: TestClient, scoping_env):
        resp = client.get("/api/audit", cookies={"carefold_session": "forged_session_cookie_abc"})
        assert resp.status_code == 401

    def test_audit_authenticated_users_succeed_200(self, client: TestClient, auth_users):
        resp_a = client.get("/api/audit", headers=auth_users["headers_a"])
        assert resp_a.status_code == 200
        resp_b = client.get("/api/audit", cookies=auth_users["cookies_b"])
        assert resp_b.status_code == 200

    def test_audit_disabled_auth_mode_yields_200(self, client: TestClient, monkeypatch, scoping_env):
        monkeypatch.setattr(settings, "auth_provider", "disabled")
        resp = client.get("/api/audit")
        assert resp.status_code == 200


# =============================================================================
# PROBE 2: CROSS-TENANT NOTES READ / UPDATE / DELETE (403/404)
# =============================================================================

class TestProbeNotesCrossTenant:
    """Probe 2: Adversarially tests cross-tenant note boundaries."""

    def test_user_b_cannot_read_user_a_note(self, client: TestClient, auth_users):
        # Alice creates note
        create_resp = client.post(
            "/api/notes",
            json={
                "title": "Alice Confidential Medical Plan",
                "slug": "alice-confidential",
                "content": "Secret oncology medication schedule: 50mg daily.",
            },
            headers=auth_users["headers_a"],
        )
        assert create_resp.status_code == 201

        # Bob attempts to read Alice's note
        read_b = client.get("/api/notes/alice-confidential", headers=auth_users["headers_b"])
        assert read_b.status_code == 403, f"Expected 403 Forbidden, got {read_b.status_code}"
        assert "Access denied" in read_b.json()["detail"] or "Forbidden" in read_b.json()["detail"]

    def test_user_b_cannot_update_user_a_note(self, client: TestClient, auth_users):
        # Alice creates note
        client.post(
            "/api/notes",
            json={"title": "Alice Vitals", "slug": "alice-vitals", "content": "BP 120/80"},
            headers=auth_users["headers_a"],
        )

        # Bob attempts to overwrite Alice's note
        update_b = client.put(
            "/api/notes/alice-vitals",
            json={"title": "Hacked Title", "content": "Hacked content"},
            headers=auth_users["headers_b"],
        )
        assert update_b.status_code == 403

        # Verify Alice's note was unchanged
        read_a = client.get("/api/notes/alice-vitals", headers=auth_users["headers_a"])
        assert read_a.status_code == 200
        assert read_a.json()["content"] == "BP 120/80"

    def test_user_b_cannot_delete_user_a_note(self, client: TestClient, auth_users):
        # Alice creates note
        client.post(
            "/api/notes",
            json={"title": "Alice Labs", "slug": "alice-labs", "content": "Normal fasting glucose"},
            headers=auth_users["headers_a"],
        )

        # Bob attempts to delete Alice's note
        del_b = client.delete("/api/notes/alice-labs", headers=auth_users["headers_b"])
        assert del_b.status_code == 403

        # Verify note still exists for Alice
        read_a = client.get("/api/notes/alice-labs", headers=auth_users["headers_a"])
        assert read_a.status_code == 200

    def test_user_b_list_notes_excludes_user_a_notes(self, client: TestClient, auth_users):
        # Alice creates note
        client.post(
            "/api/notes",
            json={"title": "Alice Only Note", "slug": "alice-only", "content": "Private notes"},
            headers=auth_users["headers_a"],
        )

        # Bob lists notes
        list_b = client.get("/api/notes", headers=auth_users["headers_b"])
        assert list_b.status_code == 200
        slugs = [n["slug"] for n in list_b.json()]
        assert "alice-only" not in slugs

    def test_note_slug_path_traversal_rejection(self, client: TestClient, auth_users):
        # Path traversal attempts must be rejected with 400 or 404
        resp1 = client.get("/api/notes/..%2Falice-only", headers=auth_users["headers_b"])
        assert resp1.status_code in (400, 404)
        resp2 = client.get("/api/notes/alice%2Fsecret", headers=auth_users["headers_b"])
        assert resp2.status_code in (400, 404)

    def test_cross_user_note_slug_clash_isolation(self, client: TestClient, auth_users):
        """Tests that two users can create notes with identical slugs without cross-talk or crash."""
        # Alice creates note with slug 'treatment-plan'
        res_a = client.post(
            "/api/notes",
            json={"title": "Treatment Plan", "slug": "treatment-plan", "content": "Alice Chemo Schedule"},
            headers=auth_users["headers_a"],
        )
        assert res_a.status_code == 201

        # Bob creates note with same slug 'treatment-plan'
        res_b = client.post(
            "/api/notes",
            json={"title": "Treatment Plan", "slug": "treatment-plan", "content": "Bob Physical Therapy"},
            headers=auth_users["headers_b"],
        )
        assert res_b.status_code == 201

        # Alice gets 'treatment-plan'
        get_a = client.get("/api/notes/treatment-plan", headers=auth_users["headers_a"])
        assert get_a.status_code == 200
        assert get_a.json()["content"] == "Alice Chemo Schedule"

        # Bob gets 'treatment-plan'
        get_b = client.get("/api/notes/treatment-plan", headers=auth_users["headers_b"])
        assert get_b.status_code == 200
        assert get_b.json()["content"] == "Bob Physical Therapy"


# =============================================================================
# PROBE 3: CROSS-TENANT ATTACHMENTS ACCESS & SANDBOX ISOLATION
# =============================================================================

class TestProbeAttachmentsCrossTenant:
    """Probe 3: Adversarially tests attachment isolation and attach_read sandbox boundaries."""

    def test_user_b_cannot_see_user_a_attachments_in_list(self, client: TestClient, auth_users):
        # Alice uploads file
        upload_resp = client.post(
            "/api/attachments",
            files={"file": ("alice_ekg.txt", io.BytesIO(b"EKG Data for Alice"), "text/plain")},
            headers=auth_users["headers_a"],
        )
        assert upload_resp.status_code == 201

        # Bob lists attachments
        list_b = client.get("/api/attachments", headers=auth_users["headers_b"])
        assert list_b.status_code == 200
        b_files = [att["filename"] for att in list_b.json()]
        assert not any("alice_ekg" in f for f in b_files)

    @pytest.mark.asyncio
    async def test_attach_read_cross_user_isolation(self, client: TestClient, auth_users, scoping_env):
        """Tests whether attach_read tool enforces user isolation when context carries user_id."""
        user_a_id = auth_users["user_a"]["id"]
        user_b_id = auth_users["user_b"]["id"]

        # Alice uploads file via API
        upload_resp = client.post(
            "/api/attachments",
            files={"file": ("alice_chart.txt", io.BytesIO(b"ALICE CONFIDENTIAL MEDICAL CHART"), "text/plain")},
            headers=auth_users["headers_a"],
        )
        assert upload_resp.status_code == 201
        uploaded_filename = upload_resp.json()["filename"]

        ws_root = scoping_env["workspace"]
        ctx_bob = DummyContext(workspace_root=ws_root, user_id=user_b_id)

        # 1. Bob attempts to read "alice_chart.txt" without user prefix
        res_direct = await execute_attach_read({"path": uploaded_filename}, ctx_bob)
        # In Bob's partition, the file does not exist.
        # It must NOT be read successfully from root either.
        assert res_direct.success is False

        # 2. Bob attempts path traversal with ..
        res_trav = await execute_attach_read({"path": f"../{user_a_id}/{uploaded_filename}"}, ctx_bob)
        assert res_trav.success is False

        # 3. Bob attempts to access Alice's partition directly: "{user_a_id}/{uploaded_filename}"
        res_cross = await execute_attach_read({"path": f"{user_a_id}/{uploaded_filename}"}, ctx_bob)
        # Empirical test: In a secure multi-tenant system, Bob (user_id=user_b_id) MUST NOT be able
        # to read Alice's attachment by passing Alice's partition prefix.
        assert res_cross.success is False, (
            f"VULNERABILITY DETECTED: Cross-tenant attachment leakage in attach_read! "
            f"User B (id={user_b_id}) successfully read User A's file at {user_a_id}/{uploaded_filename}: "
            f"{res_cross.output}"
        )


# =============================================================================
# PROBE 4: CROSS-TENANT MEMORY ISOLATION
# =============================================================================

class TestProbeMemoryCrossTenant:
    """Probe 4: Adversarially tests cognitive memory isolation against spoofing and tampering."""

    def test_memory_namespace_spoofing_prevention(self, client: TestClient, auth_users):
        user_a_id = auth_users["user_a"]["id"]
        user_b_id = auth_users["user_b"]["id"]

        # Alice stores memory under default namespace
        client.put(
            "/api/memory/alice_allergy",
            json={"value": "Anaphylaxis to Sulfa drugs", "tier": "episodic"},
            headers=auth_users["headers_a"],
        )

        # Bob attempts to recall memory specifying Alice's raw namespace f"user_{user_a_id}"
        recall_spoof = client.get(
            f"/api/memory?query=Sulfa&namespace=user_{user_a_id}",
            headers=auth_users["headers_b"],
        )
        assert recall_spoof.status_code == 200
        # The server should have derived namespace f"user_{user_b_id}:user_{user_a_id}", which is empty!
        assert len(recall_spoof.json()) == 0

        # Bob attempts to get Alice's specific key using Alice's namespace
        get_spoof = client.get(
            f"/api/memory/alice_allergy?namespace=user_{user_a_id}",
            headers=auth_users["headers_b"],
        )
        assert get_spoof.status_code == 404

        # Bob attempts to overwrite Alice's memory using Alice's namespace
        put_spoof = client.put(
            f"/api/memory/alice_allergy?namespace=user_{user_a_id}",
            json={"value": "Tampered allergy data", "tier": "episodic"},
            headers=auth_users["headers_b"],
        )
        assert put_spoof.status_code == 200  # Saved into Bob's isolated namespace

        # Verify Alice's original memory is completely uncorrupted
        get_alice = client.get(
            "/api/memory/alice_allergy",
            headers=auth_users["headers_a"],
        )
        assert get_alice.status_code == 200
        assert get_alice.json()["value"] == "Anaphylaxis to Sulfa drugs"

    def test_memory_bulk_delete_cross_tenant_isolation(self, client: TestClient, auth_users):
        user_a_id = auth_users["user_a"]["id"]

        # Alice stores a critical memory
        client.put(
            "/api/memory/alice_insulin_dose",
            json={"value": "20 units Lantus bedtime", "tier": "episodic"},
            headers=auth_users["headers_a"],
        )

        # Bob calls bulk delete targeting Alice's namespace
        del_b = client.delete(
            f"/api/memory?namespace=user_{user_a_id}",
            headers=auth_users["headers_b"],
        )
        assert del_b.status_code == 200

        # Verify Alice's memory was NOT wiped
        get_alice = client.get(
            "/api/memory/alice_insulin_dose",
            headers=auth_users["headers_a"],
        )
        assert get_alice.status_code == 200
        assert get_alice.json()["value"] == "20 units Lantus bedtime"


# =============================================================================
# PROBE 5: CROSS-TENANT CHAT THREADS
# =============================================================================

class TestProbeChatThreadsCrossTenant:
    """Probe 5: Adversarially tests chat thread checkpoints and ownership enforcement."""

    def test_chat_threads_unauthenticated_returns_401(self, client: TestClient, scoping_env):
        resp = client.get("/api/chat/threads?thread_id=thread_123")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_chat_thread_cross_tenant_access_denied(self, client: TestClient, auth_users, scoping_env):
        from carefold.db.models import ChatThread

        session_factory = scoping_env["session_factory"]
        alice_thread_id = "thread_alice_private_cardiocare_999"

        # Record thread owned by Alice in DB
        async with session_factory() as session:
            thread = ChatThread(
                id=alice_thread_id,
                user_id=auth_users["user_a"]["id"],
                agent_id="cardiology-guide",
                title="Alice Cardiology Consultation",
            )
            session.add(thread)
            await session.commit()

        # Bob attempts to get thread history for Alice's thread
        get_b = client.get(
            f"/api/chat/threads?thread_id={alice_thread_id}",
            headers=auth_users["headers_b"],
        )
        assert get_b.status_code == 403, f"Expected 403 Forbidden, got {get_b.status_code}"
        assert "Access denied" in get_b.json()["detail"]

        # Bob attempts to invoke chat streaming using Alice's thread ID
        stream_b = client.post(
            "/api/chat",
            json={
                "agent_id": "cardiology-guide",
                "thread_id": alice_thread_id,
                "prompt": "Tell me what we talked about earlier",
            },
            headers=auth_users["headers_b"],
        )
        assert stream_b.status_code == 403, f"Expected 403 Forbidden, got {stream_b.status_code}"


# =============================================================================
# PROBE 6: BACKWARD COMPATIBILITY IN DISABLED AUTH MODE
# =============================================================================

class TestProbeDisabledAuthBackwardCompatibility:
    """Probe 6: Verifies all backend endpoints remain fully operable in single-user offline mode."""

    def test_disabled_auth_full_suite_flow(self, client: TestClient, monkeypatch, scoping_env):
        monkeypatch.setattr(settings, "auth_provider", "disabled")

        # 1. Audit log
        resp_audit = client.get("/api/audit")
        assert resp_audit.status_code == 200

        # 2. Notes CRUD
        create_note = client.post(
            "/api/notes",
            json={"title": "Offline Note", "slug": "offline-note", "content": "Working offline"},
        )
        assert create_note.status_code == 201

        get_note = client.get("/api/notes/offline-note")
        assert get_note.status_code == 200
        assert get_note.json()["content"] == "Working offline"

        list_notes = client.get("/api/notes")
        assert list_notes.status_code == 200
        assert any(n["slug"] == "offline-note" for n in list_notes.json())

        del_note = client.delete("/api/notes/offline-note")
        assert del_note.status_code == 200

        # 3. Attachments
        upload_att = client.post(
            "/api/attachments",
            files={"file": ("offline_file.txt", io.BytesIO(b"Offline Attachment Content"), "text/plain")},
        )
        assert upload_att.status_code == 201

        list_att = client.get("/api/attachments")
        assert list_att.status_code == 200
        assert any("offline_file" in f["filename"] for f in list_att.json())

        # 4. Memory
        put_mem = client.put(
            "/api/memory/offline_key",
            json={"value": "Offline memory value", "tier": "episodic"},
        )
        assert put_mem.status_code == 200

        get_mem = client.get("/api/memory/offline_key")
        assert get_mem.status_code == 200
        assert get_mem.json()["value"] == "Offline memory value"
