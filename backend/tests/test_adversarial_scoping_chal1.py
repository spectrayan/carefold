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

"""Adversarial challenger test harness for Milestone 1: Deep Entity Scoping (AU-12, AU-13)
and Alembic Migration 0004_autonomy_batch_2.py.

Attacks tested:
1. Bypass attacks against profile_id requirement:
   - Whitespace: "   ", "\t\n  "
   - Null: explicit null in JSON
   - Boolean: true, false
   - Empty JSON payload: {}
   - SQL injection payloads: ' OR 1=1 --, '; DROP TABLE notes; --, etc.
2. Cross-profile reading, writing, updating, and deleting between unprivileged accounts:
   - Unprivileged account cross-profile note access
   - Partial-privilege steward roles (view_paperwork, view_clinical) boundaries
   - Chat thread cross-profile access and thread hijacking attempts
   - Cognitive memory CRUD cross-profile isolation
3. Migration stress cycles & dirty-data resilience:
   - Multi-cycle upgrade/downgrade stress
   - Legacy orphaned records backfill under dirty conditions
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import AsyncIterator
import uuid

import alembic.command
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import StaticPool

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.models import (
    ChatThread,
    Note,
    Profile,
    ProfileAccess,
    User,
)
from carefold.db.session import (
    create_db_engine,
    get_alembic_config,
    get_session_factory,
    init_db,
)
from carefold.main import app
from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
from carefold.memory.factory import reset_memory_ports, set_memory_port


@pytest.fixture
async def chal_test_env(temp_workspace: Path, monkeypatch):
    """Sets up an isolated in-memory DB, local SQL auth provider, and memory port."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    sql_auth = SqlAuthAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    monkeypatch.setattr(settings, "workspace_root", temp_workspace)
    monkeypatch.setattr(settings, "home_dir", temp_workspace / "home")
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

    memory_db_path = temp_workspace / "memories.db"
    mem_adapter = SqliteMemoryAdapter(db_path=memory_db_path)
    set_memory_port(mem_adapter)

    try:
        yield {
            "workspace": temp_workspace,
            "home": settings.home_dir,
            "auth": sql_auth,
            "memory_adapter": mem_adapter,
            "session_factory": session_factory,
        }
    finally:
        app.dependency_overrides.clear()
        reset_auth_port()
        await mem_adapter.close()
        set_memory_port(None)


def register_and_login(client: TestClient, email: str, password: str, name: str) -> dict:
    """Helper to register and authenticate a user against local auth."""
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
    assert resp.status_code in (201, 400), resp.text
    login_resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert login_resp.status_code == 200, login_resp.text
    token = login_resp.json()["token"]
    user_info = login_resp.json()["user"]
    headers = {"Authorization": f"Bearer {token}"}
    client.get("/api/profiles", headers=headers)
    return {"token": token, "user": user_info, "headers": headers}


# ============================================================================
# Section 1: Bypass Attacks against profile_id requirement
# ============================================================================

SQLI_PAYLOADS = [
    "' OR 1=1 --",
    "\" OR \"\"=\"",
    "admin'--",
    "'; DROP TABLE notes; --",
    "'; DROP TABLE chat_threads; --",
    "1' OR '1'='1",
    "' UNION SELECT id, name, relationship, role, avatar_color, is_primary, created_at, updated_at FROM profiles --",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload_val", ["   ", "\t\r\n  ", None])
async def test_attack_notes_create_whitespace_and_null_bypass(chal_test_env, payload_val):
    """Attacks POST /api/notes with whitespace and null profile_id variations."""
    with TestClient(app) as client:
        user = register_and_login(client, "attacker1@test.local", "Password123!", "Attacker")
        resp = client.post(
            "/api/notes",
            headers=user["headers"],
            json={"title": "Attack Note", "content": "Exploit", "profile_id": payload_val},
        )
        assert resp.status_code == 400
        assert "profile_id is required" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bool_val", [True, False])
async def test_attack_notes_create_boolean_bypass(chal_test_env, bool_val):
    """Attacks POST /api/notes with boolean profile_id."""
    with TestClient(app) as client:
        user = register_and_login(client, "attacker2@test.local", "Password123!", "Attacker")
        resp = client.post(
            "/api/notes",
            headers=user["headers"],
            json={"title": "Bool Note", "content": "Exploit", "profile_id": bool_val},
        )
        # Pydantic validates str type, reject with 422 or 400
        assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_attack_notes_create_empty_json_payload(chal_test_env):
    """Attacks POST /api/notes with empty JSON payload or completely missing profile_id."""
    with TestClient(app) as client:
        user = register_and_login(client, "attacker3@test.local", "Password123!", "Attacker")
        # Empty payload
        resp_empty = client.post("/api/notes", headers=user["headers"], json={})
        assert resp_empty.status_code == 422  # title & content required

        # Missing profile_id
        resp_missing = client.post(
            "/api/notes",
            headers=user["headers"],
            json={"title": "Missing Field", "content": "Content"},
        )
        assert resp_missing.status_code == 400
        assert "profile_id is required" in resp_missing.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("sqli", SQLI_PAYLOADS)
async def test_attack_notes_create_sqli_payload(chal_test_env, sqli):
    """Attacks POST /api/notes with SQL injection strings as profile_id."""
    with TestClient(app) as client:
        user = register_and_login(client, "attacker4@test.local", "Password123!", "Attacker")
        resp = client.post(
            "/api/notes",
            headers=user["headers"],
            json={"title": "SQLi Note", "content": "Content", "profile_id": sqli},
        )
        # Must not cause 500 error, must not bypass scoping, must return 404 (profile not found)
        assert resp.status_code in (400, 404)
        assert resp.status_code != 500


@pytest.mark.asyncio
@pytest.mark.parametrize("sqli", SQLI_PAYLOADS)
async def test_attack_notes_update_sqli_payload(chal_test_env, sqli):
    """Attacks PUT /api/notes/{slug} attempting reassignment with SQL injection payloads."""
    with TestClient(app) as client:
        user = register_and_login(client, "attacker5@test.local", "Password123!", "Attacker")
        p_resp = client.post("/api/profiles", headers=user["headers"], json={"name": "Valid Profile", "relationship": "other"})
        pid = p_resp.json()["id"]

        n_resp = client.post("/api/notes", headers=user["headers"], json={"title": "Note Up", "content": "C", "profile_id": pid})
        slug = n_resp.json()["slug"]

        up_resp = client.put(f"/api/notes/{slug}", headers=user["headers"], json={"profile_id": sqli})
        assert up_resp.status_code in (400, 404)
        assert up_resp.status_code != 500


@pytest.mark.asyncio
@pytest.mark.parametrize("payload_val", ["   ", "\t\r\n  ", None])
async def test_attack_chat_stream_whitespace_and_null_bypass(chal_test_env, payload_val):
    """Attacks POST /api/chat with whitespace and null profile_id variations."""
    with TestClient(app) as client:
        user = register_and_login(client, "attacker6@test.local", "Password123!", "Attacker")
        resp = client.post(
            "/api/chat",
            headers=user["headers"],
            json={"agent_id": "cardiology-guide", "prompt": "Hello", "profile_id": payload_val},
        )
        assert resp.status_code == 400
        assert "profile_id is required" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bool_val", [True, False])
async def test_attack_chat_stream_boolean_bypass(chal_test_env, bool_val):
    """Attacks POST /api/chat with boolean profile_id."""
    with TestClient(app) as client:
        user = register_and_login(client, "attacker7@test.local", "Password123!", "Attacker")
        resp = client.post(
            "/api/chat",
            headers=user["headers"],
            json={"agent_id": "cardiology-guide", "prompt": "Hello", "profile_id": bool_val},
        )
        assert resp.status_code in (400, 422)


@pytest.mark.asyncio
@pytest.mark.parametrize("sqli", SQLI_PAYLOADS)
async def test_attack_chat_stream_sqli_payload(chal_test_env, sqli):
    """Attacks POST /api/chat with SQL injection payloads as profile_id."""
    with TestClient(app) as client:
        user = register_and_login(client, "attacker8@test.local", "Password123!", "Attacker")
        resp = client.post(
            "/api/chat",
            headers=user["headers"],
            json={"agent_id": "cardiology-guide", "prompt": "Hello", "profile_id": sqli},
        )
        assert resp.status_code in (400, 404)
        assert resp.status_code != 500


@pytest.mark.asyncio
@pytest.mark.parametrize("payload_val", ["   ", "\t\n  "])
async def test_attack_memory_whitespace_bypass(chal_test_env, payload_val):
    """Attacks memory endpoints with whitespace profile_id."""
    with TestClient(app) as client:
        user = register_and_login(client, "attacker9@test.local", "Password123!", "Attacker")

        # GET /api/memory
        r1 = client.get("/api/memory", params={"profile_id": payload_val}, headers=user["headers"])
        assert r1.status_code == 400
        assert "profile_id is required" in r1.json()["detail"]

        # DELETE /api/memory
        r2 = client.delete("/api/memory", params={"profile_id": payload_val}, headers=user["headers"])
        assert r2.status_code == 400
        assert "profile_id is required" in r2.json()["detail"]

        # GET /api/memory/{key}
        r3 = client.get("/api/memory/key1", params={"profile_id": payload_val}, headers=user["headers"])
        assert r3.status_code == 400

        # PUT /api/memory/{key}
        r4 = client.put("/api/memory/key1", params={"profile_id": payload_val}, headers=user["headers"], json={"value": {"x": 1}})
        assert r4.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("sqli", SQLI_PAYLOADS)
async def test_attack_memory_sqli_payload(chal_test_env, sqli):
    """Attacks memory endpoints with SQL injection in profile_id."""
    with TestClient(app) as client:
        user = register_and_login(client, "attacker10@test.local", "Password123!", "Attacker")

        r1 = client.get("/api/memory", params={"profile_id": sqli}, headers=user["headers"])
        assert r1.status_code in (400, 404)
        assert r1.status_code != 500


# ============================================================================
# Section 2: Cross-profile reading, writing & partial privilege attacks
# ============================================================================

@pytest.mark.asyncio
async def test_attack_cross_profile_note_manipulation(chal_test_env):
    """Attacks unprivileged user trying to read, modify, or delete victim's note."""
    with TestClient(app) as client:
        alice = register_and_login(client, "alice_vic@test.local", "Password123!", "Alice")
        bob = register_and_login(client, "bob_att@test.local", "Password123!", "Bob")

        # Alice creates profile & note
        p_res = client.post("/api/profiles", headers=alice["headers"], json={"name": "Alice Records", "relationship": "other"})
        pid_alice = p_res.json()["id"]

        n_res = client.post("/api/notes", headers=alice["headers"], json={"title": "Secret", "content": "My secret", "profile_id": pid_alice})
        slug = n_res.json()["slug"]

        # Bob attempts reading note directly
        r_read = client.get(f"/api/notes/{slug}", headers=bob["headers"])
        assert r_read.status_code == 403

        # Bob attempts listing notes for Alice's profile
        r_list = client.get(f"/api/notes?profile_id={pid_alice}", headers=bob["headers"])
        assert r_list.status_code == 403

        # Bob attempts updating Alice's note
        r_up = client.put(f"/api/notes/{slug}", headers=bob["headers"], json={"content": "Defaced!"})
        assert r_up.status_code == 403

        # Bob attempts deleting Alice's note
        r_del = client.delete(f"/api/notes/{slug}", headers=bob["headers"])
        assert r_del.status_code == 403

        # Bob attempts creating a note inside Alice's profile
        r_create = client.post("/api/notes", headers=bob["headers"], json={"title": "Rogue", "content": "Rogue", "profile_id": pid_alice})
        assert r_create.status_code == 403


@pytest.mark.asyncio
async def test_attack_partial_privilege_steward_roles(chal_test_env):
    """Tests partial privilege access enforcement for stewards:
    - view_paperwork: CANNOT read clinical notes, CANNOT chat, CANNOT access memories
    - view_clinical: CAN read clinical notes, but CANNOT write/delete notes or mutate memories
    """
    with TestClient(app) as client:
        alice = register_and_login(client, "alice_owner@test.local", "Password123!", "Alice")
        steward_paperwork = register_and_login(client, "charlie_paper@test.local", "Password123!", "Charlie")
        steward_clinical = register_and_login(client, "dan_clin@test.local", "Password123!", "Dan")

        p_res = client.post("/api/profiles", headers=alice["headers"], json={"name": "Alice Health", "relationship": "other"})
        pid = p_res.json()["id"]

        n_res = client.post("/api/notes", headers=alice["headers"], json={"title": "Diagnosis", "content": "Confidential diagnosis", "profile_id": pid})
        slug = n_res.json()["slug"]

        # Grant charlie view_paperwork
        session_factory = chal_test_env["session_factory"]
        async with session_factory() as session:
            session.add(ProfileAccess(
                id=str(uuid.uuid4()),
                profile_id=pid,
                user_id=steward_paperwork["user"]["id"],
                access_level="view_paperwork",
                granted_at=datetime.datetime.now(datetime.timezone.utc),
            ))
            session.add(ProfileAccess(
                id=str(uuid.uuid4()),
                profile_id=pid,
                user_id=steward_clinical["user"]["id"],
                access_level="view_clinical",
                granted_at=datetime.datetime.now(datetime.timezone.utc),
            ))
            await session.commit()

        # 1. Charlie (view_paperwork):
        # Must be blocked from notes
        assert client.get(f"/api/notes/{slug}", headers=steward_paperwork["headers"]).status_code == 403
        assert client.get(f"/api/notes?profile_id={pid}", headers=steward_paperwork["headers"]).status_code == 403
        # Must be blocked from chat
        assert client.post("/api/chat", headers=steward_paperwork["headers"], json={"agent_id": "cardiology-guide", "prompt": "Hi", "profile_id": pid}).status_code == 403
        # Must be blocked from memory
        assert client.get(f"/api/memory?profile_id={pid}", headers=steward_paperwork["headers"]).status_code == 403

        # 2. Dan (view_clinical):
        # Can read clinical notes
        read_res = client.get(f"/api/notes/{slug}", headers=steward_clinical["headers"])
        assert read_res.status_code == 200
        assert "Confidential diagnosis" in read_res.json()["content"]

        # Cannot create notes (manage required)
        assert client.post("/api/notes", headers=steward_clinical["headers"], json={"title": "T", "content": "C", "profile_id": pid}).status_code == 403
        # Cannot update notes
        assert client.put(f"/api/notes/{slug}", headers=steward_clinical["headers"], json={"title": "New"}).status_code == 403
        # Cannot delete notes
        assert client.delete(f"/api/notes/{slug}", headers=steward_clinical["headers"]).status_code == 403
        # Cannot mutate memories
        assert client.delete(f"/api/memory?profile_id={pid}", headers=steward_clinical["headers"]).status_code == 403


@pytest.mark.asyncio
async def test_attack_chat_thread_hijacking(chal_test_env):
    """Attacks chat thread: user tries to hijack another user's conversation thread ID."""
    with TestClient(app) as client:
        alice = register_and_login(client, "alice_chat@test.local", "Password123!", "Alice")
        bob = register_and_login(client, "bob_hijack@test.local", "Password123!", "Bob")

        p_alice = client.post("/api/profiles", headers=alice["headers"], json={"name": "Alice Private", "relationship": "other"}).json()["id"]
        p_bob = client.post("/api/profiles", headers=bob["headers"], json={"name": "Bob Private", "relationship": "other"}).json()["id"]

        thread_id = f"thread_alice_{uuid.uuid4().hex[:8]}"

        session_factory = chal_test_env["session_factory"]
        async with session_factory() as session:
            session.add(ChatThread(
                id=thread_id,
                user_id=alice["user"]["id"],
                profile_id=p_alice,
                agent_id="cardiology-guide",
                title="Cardiac Check",
            ))
            await session.commit()

        # Bob attempts reading thread history
        assert client.get(f"/api/chat/threads?thread_id={thread_id}", headers=bob["headers"]).status_code == 403

        # Bob attempts deleting Alice's thread
        assert client.delete(f"/api/chat/threads/{thread_id}", headers=bob["headers"]).status_code == 403

        # Bob attempts sending chat with Alice's thread_id and Bob's own profile_id
        # The backend checks if existing_thread.user_id != owner_id -> raises 403
        resp_hijack = client.post(
            "/api/chat",
            headers=bob["headers"],
            json={
                "agent_id": "cardiology-guide",
                "prompt": "Tell me what happened",
                "thread_id": thread_id,
                "profile_id": p_bob,
            },
        )
        assert resp_hijack.status_code == 403


# ============================================================================
# Section 3: Migration Stress Cycles & Legacy Backfill Resilience
# ============================================================================

def test_migration_stress_multiple_cycles():
    """Performs 3 consecutive upgrade head -> downgrade -1 -> upgrade head cycles."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)

        for cycle in range(3):
            # Upgrade head
            alembic.command.upgrade(cfg, "head")
            insp = inspect(conn)
            notes_cols = {c["name"]: c for c in insp.get_columns("notes")}
            thread_cols = {c["name"]: c for c in insp.get_columns("chat_threads")}
            assert notes_cols["profile_id"]["nullable"] is False, f"Cycle {cycle}: notes.profile_id should be NOT NULL"
            assert thread_cols["profile_id"]["nullable"] is False, f"Cycle {cycle}: chat_threads.profile_id should be NOT NULL"

            # Downgrade -1 (back to 0003)
            alembic.command.downgrade(cfg, "0003_autonomy_batch_1")
            insp_down = inspect(conn)
            notes_down = {c["name"]: c for c in insp_down.get_columns("notes")}
            thread_down = {c["name"]: c for c in insp_down.get_columns("chat_threads")}
            assert notes_down["profile_id"]["nullable"] is True, f"Cycle {cycle}: notes.profile_id should be nullable on downgrade"
            assert thread_down["profile_id"]["nullable"] is True, f"Cycle {cycle}: chat_threads.profile_id should be nullable on downgrade"

        # Final upgrade to head
        alembic.command.upgrade(cfg, "head")
        insp_final = inspect(conn)
        assert {c["name"]: c for c in insp_final.get_columns("notes")}["profile_id"]["nullable"] is False


def test_migration_dirty_data_orphans_without_user_id():
    """Tests backfill handling when orphaned notes have NO user_id and NO matching profiles exist yet."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)

        # Upgrade to 0003
        alembic.command.upgrade(cfg, "0003_autonomy_batch_1")

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Insert orphaned note and chat_thread with user_id = NULL and profile_id = NULL
        # Zero profiles exist in profiles table!
        conn.execute(text("""
            INSERT INTO notes (id, slug, title, content, user_id, profile_id, type, tags_json, created_at, updated_at)
            VALUES ('completely-orphaned-note', 'orphan-slug', 'Orphan', 'Content', NULL, NULL, 'scratchpad', '[]', :now, :now)
        """), {"now": now_iso})

        conn.execute(text("""
            INSERT INTO chat_threads (id, agent_id, title, user_id, profile_id, created_at, updated_at)
            VALUES ('completely-orphaned-thread', 'cardiology-guide', 'Orphan Thread', NULL, NULL, :now, :now)
        """), {"now": now_iso})

        conn.commit()

        # Upgrade to 0004 (should auto-provision Default Profile and backfill without failing)
        alembic.command.upgrade(cfg, "head")

        # Verify profile was provisioned and rows are populated
        note_pid = conn.execute(text("SELECT profile_id FROM notes WHERE id = 'completely-orphaned-note'")).scalar()
        thread_pid = conn.execute(text("SELECT profile_id FROM chat_threads WHERE id = 'completely-orphaned-thread'")).scalar()
        assert note_pid is not None
        assert thread_pid is not None
        assert note_pid == thread_pid

        # Verify Default Profile was created
        prof = conn.execute(text("SELECT name FROM profiles WHERE id = :pid"), {"pid": note_pid}).fetchone()
        assert prof is not None
        assert prof[0] == "Default Profile"
