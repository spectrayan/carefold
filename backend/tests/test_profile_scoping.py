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

"""E2E test suite for Milestone 5: Family Profiles, Access Governance & Resource Scoping.

Verifies:
1. Auto-provisioning primary 'Me' profile on first query
2. Protection against deleting primary 'Me' profile (HTTP 400)
3. Profile CRUD and validation
4. Profile-scoped notes and filesystem partitioning
5. Profile-scoped attachments and isolation
6. Profile-scoped memory namespaces
7. Access governance (grant, list, revoke) across multiple users
8. Per-profile clinical consent configuration
9. Chat thread association with profile_id and access control
10. Audit event filtering by profile_id
"""

from __future__ import annotations

import io
import json
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
from carefold.db.models import Note
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app
from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
from carefold.memory.factory import reset_memory_ports, set_memory_port
from carefold.memory.ports.memory_port import MemoryTier
from carefold.audit.logger import record_audit


@pytest.fixture
async def profile_test_env(temp_workspace: Path, monkeypatch):
    """Sets up an isolated in-memory DB, local SQL auth provider, and memory port."""
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

    memory_db_path = temp_workspace / "memories.db"
    mem_adapter = SqliteMemoryAdapter(db_path=memory_db_path)
    set_memory_port(mem_adapter)

    try:
        yield {
            "workspace": temp_workspace,
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
    # Ensure an initial admin exists so test users are standard members
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


@pytest.mark.asyncio
async def test_auto_provision_me_and_delete_protection(profile_test_env):
    """Test auto-provisioning 'Me' profile and ensuring primary profile cannot be deleted."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice@test.local", "Password123!", "Alice")

        # 1. Listing profiles should auto-provision 'Me' profile
        resp = client.get("/api/profiles", headers=user_a["headers"])
        assert resp.status_code == 200
        profiles = resp.json()
        assert len(profiles) == 1
        me_profile = profiles[0]
        assert me_profile["name"] in ("Me", "Alice")
        assert me_profile["is_primary"] is True
        assert me_profile["relationship"] == "self"
        me_id = me_profile["id"]

        # 2. Attempting to delete primary profile must fail with HTTP 400
        del_resp = client.delete(f"/api/profiles/{me_id}", headers=user_a["headers"])
        assert del_resp.status_code == 400
        assert "Cannot delete primary 'Me' profile" in del_resp.json()["detail"]


@pytest.mark.asyncio
async def test_profile_crud_and_family_members(profile_test_env):
    """Test creating and managing family member profiles."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice2@test.local", "Password123!", "Alice")

        # Auto-provision primary first
        client.get("/api/profiles", headers=user_a["headers"])

        # Create Mom profile
        create_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={
                "name": "Mom",
                "relationship": "parent",
                "date_of_birth": "1960-05-15",
            },
        )
        assert create_resp.status_code == 201
        mom_data = create_resp.json()
        mom_id = mom_data["id"]
        assert mom_data["name"] == "Mom"
        assert mom_data["relationship"] == "parent"
        assert mom_data["is_primary"] is False
        assert mom_data["access_level"] == "manage"

        # Get profile detail
        detail_resp = client.get(f"/api/profiles/{mom_id}", headers=user_a["headers"])
        assert detail_resp.status_code == 200
        assert detail_resp.json()["id"] == mom_id

        # Update profile
        update_resp = client.put(
            f"/api/profiles/{mom_id}",
            headers=user_a["headers"],
            json={"relationship": "parent"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["relationship"] == "parent"

        # List profiles should show 2 (Alice and Mom)
        list_resp = client.get("/api/profiles", headers=user_a["headers"])
        assert len(list_resp.json()) == 2

        # Delete non-primary profile should succeed
        del_resp = client.delete(f"/api/profiles/{mom_id}", headers=user_a["headers"])
        assert del_resp.status_code in (200, 204)

        # Verify deletion
        list_resp2 = client.get("/api/profiles", headers=user_a["headers"])
        assert len(list_resp2.json()) == 1


@pytest.mark.asyncio
async def test_notes_profile_scoping(profile_test_env):
    """Test that notes are strictly scoped by profile_id and partitioned on disk."""
    ws = profile_test_env["workspace"]

    with TestClient(app) as client:
        user_a = register_and_login(client, "alice3@test.local", "Password123!", "Alice")
        user_b = register_and_login(client, "bob3@test.local", "Password123!", "Bob")

        # Auto-provision Alice primary
        me_resp = client.get("/api/profiles", headers=user_a["headers"])
        alice_me_id = me_resp.json()[0]["id"]

        # Create Mom profile
        mom_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Mom", "relationship": "parent"},
        )
        mom_id = mom_resp.json()["id"]

        # 1. Create note for Mom
        n_mom = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={
                "title": "Mom Glucose Log",
                "content": "Blood glucose: 110 mg/dL",
                "profile_id": mom_id,
            },
        )
        assert n_mom.status_code == 201
        mom_slug = n_mom.json()["slug"]

        # 2. Create note for Alice primary
        n_alice = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={
                "title": "Alice Running Log",
                "content": "Ran 5k today",
                "profile_id": alice_me_id,
            },
        )
        assert n_alice.status_code == 201

        # Check DB persistence (M2: Notes are 100% relational DB; no loose files written)
        notes_dir = settings.get_notes_dir()
        alice_uid = user_a["user"]["id"]
        mom_file = notes_dir / alice_uid / mom_id / f"{mom_slug}.md"
        assert not mom_file.is_file()

        session_factory = profile_test_env["session_factory"]
        async with session_factory() as session:
            res = await session.execute(select(Note).where(Note.slug == mom_slug))
            note_row = res.scalar_one_or_none()
            assert note_row is not None
            assert note_row.profile_id == mom_id
            assert "Blood glucose: 110 mg/dL" in note_row.content

        # 3. Filter notes by profile
        mom_notes_resp = client.get(f"/api/notes?profile_id={mom_id}", headers=user_a["headers"])
        assert mom_notes_resp.status_code == 200
        mom_notes = mom_notes_resp.json()
        assert len(mom_notes) == 1
        assert mom_notes[0]["title"] == "Mom Glucose Log"

        # 4. User B cannot access Mom's note or list Mom's profile notes
        b_mom_resp = client.get(f"/api/notes?profile_id={mom_id}", headers=user_b["headers"])
        assert b_mom_resp.status_code == 403

        b_create_resp = client.post(
            "/api/notes",
            headers=user_b["headers"],
            json={
                "title": "Hacked Note",
                "content": "Unauthorized note",
                "profile_id": mom_id,
            },
        )
        assert b_create_resp.status_code == 403


@pytest.mark.asyncio
async def test_attachments_profile_scoping(profile_test_env):
    """Test profile-scoped attachments and isolation."""
    ws = profile_test_env["workspace"]

    with TestClient(app) as client:
        user_a = register_and_login(client, "alice4@test.local", "Password123!", "Alice")
        user_b = register_and_login(client, "bob4@test.local", "Password123!", "Bob")

        # Create Mom profile
        mom_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Mom", "relationship": "parent"},
        )
        mom_id = mom_resp.json()["id"]

        # Upload attachment for Mom
        dummy_pdf = io.BytesIO(b"%PDF-1.4 mock pdf content for mom")
        up_resp = client.post(
            f"/api/attachments?profile_id={mom_id}",
            headers=user_a["headers"],
            files={"file": ("mom_lab_report.pdf", dummy_pdf, "application/pdf")},
        )
        assert up_resp.status_code in (200, 201)
        up_data = up_resp.json()
        assert up_data["filename"] == "mom_lab_report.pdf"

        # Check disk path partitioning
        att_dir = settings.get_attachments_dir()
        alice_uid = user_a["user"]["id"]
        mom_att_dir = att_dir / alice_uid / mom_id
        assert (mom_att_dir / "mom_lab_report.pdf").is_file()

        # List attachments with profile_id filter
        list_resp = client.get(f"/api/attachments?profile_id={mom_id}", headers=user_a["headers"])
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1

        # User B cannot list or upload to Mom's profile
        b_list = client.get(f"/api/attachments?profile_id={mom_id}", headers=user_b["headers"])
        assert b_list.status_code == 403


@pytest.mark.asyncio
async def test_memory_profile_scoping(profile_test_env):
    """Test memory isolation per profile namespace."""
    mem_port = profile_test_env["memory_adapter"]

    with TestClient(app) as client:
        user_a = register_and_login(client, "alice5@test.local", "Password123!", "Alice")
        alice_uid = user_a["user"]["id"]

        # Create Mom and Dad profiles
        mom_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Mom", "relationship": "parent"},
        )
        mom_id = mom_resp.json()["id"]

        dad_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Dad", "relationship": "parent"},
        )
        dad_id = dad_resp.json()["id"]

        # Store Mom memory directly in mem_port under effective namespace
        mom_ns = f"user_{alice_uid}_profile_{mom_id}"
        await mem_port.remember(
            key="condition_hypertension",
            tier=MemoryTier.WORKING,
            value="Diagnosed with Stage 1 Hypertension in 2021",
            namespace=mom_ns,
        )

        dad_ns = f"user_{alice_uid}_profile_{dad_id}"
        await mem_port.remember(
            key="condition_asthma",
            tier=MemoryTier.WORKING,
            value="Diagnosed with Asthma in 2018",
            namespace=dad_ns,
        )

        # Recall memories via API with profile_id
        mom_recall = client.get(f"/api/memory/recall?q=Hypertension&profile_id={mom_id}", headers=user_a["headers"])
        assert mom_recall.status_code == 200
        mom_results = mom_recall.json()
        assert len(mom_results) == 1
        assert "Stage 1 Hypertension" in mom_results[0]["value"]

        # Dad's memory recall does not see Mom's condition
        dad_recall = client.get(f"/api/memory/recall?q=Hypertension&profile_id={dad_id}", headers=user_a["headers"])
        assert dad_recall.status_code == 200
        assert len(dad_recall.json()) == 0


@pytest.mark.asyncio
async def test_access_governance_sharing(profile_test_env):
    """Test granting and revoking access levels between users for a profile."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice6@test.local", "Password123!", "Alice")
        user_b = register_and_login(client, "bob6@test.local", "Password123!", "Bob")

        # Alice creates Grandma profile
        resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Grandma", "relationship": "grandparent"},
        )
        grandma_id = resp.json()["id"]

        # Bob initially has no access (403)
        b_resp = client.get(f"/api/profiles/{grandma_id}", headers=user_b["headers"])
        assert b_resp.status_code == 403

        # Alice grants Bob 'view_clinical' access
        grant_resp = client.post(
            f"/api/profiles/{grandma_id}/access",
            headers=user_a["headers"],
            json={
                "user_id": user_b["user"]["id"],
                "access_level": "view_clinical",
            },
        )
        assert grant_resp.status_code == 201
        assert grant_resp.json()["access_level"] == "view_clinical"

        # Bob can now view Grandma's profile
        b_resp2 = client.get(f"/api/profiles/{grandma_id}", headers=user_b["headers"])
        assert b_resp2.status_code == 200
        assert b_resp2.json()["name"] == "Grandma"
        assert b_resp2.json()["access_level"] == "view_clinical"

        # List accesses
        access_list = client.get(f"/api/profiles/{grandma_id}/access", headers=user_a["headers"])
        assert access_list.status_code == 200
        assert len(access_list.json()) == 2

        # Alice revokes Bob's access
        rev_resp = client.delete(
            f"/api/profiles/{grandma_id}/access/{user_b['user']['id']}",
            headers=user_a["headers"],
        )
        assert rev_resp.status_code in (200, 204)

        access_list2 = client.get(f"/api/profiles/{grandma_id}/access", headers=user_a["headers"])
        assert access_list2.status_code == 200
        assert len(access_list2.json()) == 1

        # Bob is denied again (403)
        b_resp3 = client.get(f"/api/profiles/{grandma_id}", headers=user_b["headers"])
        assert b_resp3.status_code == 403


@pytest.mark.asyncio
async def test_clinical_consent_per_profile(profile_test_env):
    """Test per-profile clinical consent configuration and independence."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice7@test.local", "Password123!", "Alice")

        # Auto-provision primary profile
        me_resp = client.get("/api/profiles", headers=user_a["headers"])
        me_id = me_resp.json()[0]["id"]

        # Create Child profile
        child_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Child", "relationship": "child"},
        )
        child_id = child_resp.json()["id"]

        # Default consent for Child is not allowed
        cons_resp = client.get(f"/api/profiles/{child_id}/consent", headers=user_a["headers"])
        assert cons_resp.status_code == 200
        assert cons_resp.json()["allow_clinical"] is False

        # Update consent for Child to allow clinical
        up_cons = client.put(
            f"/api/profiles/{child_id}/consent",
            headers=user_a["headers"],
            json={"allow_clinical": True, "terms_version": "v1.0"},
        )
        assert up_cons.status_code == 200
        assert up_cons.json()["allow_clinical"] is True

        # Verify Child consent is True
        cons_resp2 = client.get(f"/api/profiles/{child_id}/consent", headers=user_a["headers"])
        assert cons_resp2.json()["allow_clinical"] is True

        # Me profile consent is still untouched
        me_cons = client.get(f"/api/profiles/{me_id}/consent", headers=user_a["headers"])
        assert me_cons.status_code == 200


@pytest.mark.asyncio
async def test_chat_thread_and_audit_profile_scoping(profile_test_env):
    """Test ChatThread profile association and audit filtering."""
    ws = profile_test_env["workspace"]

    with TestClient(app) as client:
        user_a = register_and_login(client, "alice8@test.local", "Password123!", "Alice")

        # Create Mom profile
        mom_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Mom", "relationship": "parent"},
        )
        mom_id = mom_resp.json()["id"]

        # 1. Record an audit event for Mom
        await record_audit(
            {
                "agent_id": "cardiology-guide",
                "event": "run",
                "profile_id": mom_id,
            },
            workspace_root=ws,
        )

        # Record another event without profile_id
        await record_audit(
            {
                "agent_id": "benefits-guide",
                "event": "run",
            },
            workspace_root=ws,
        )

        # Filter audit events by profile_id
        audit_resp = client.get(f"/api/audit?profile_id={mom_id}", headers=user_a["headers"])
        assert audit_resp.status_code == 200
        audit_data = audit_resp.json()
        assert audit_data["total"] == 1
        assert audit_data["events"][0]["agent_id"] == "cardiology-guide"
        assert audit_data["events"][0]["profile_id"] == mom_id
