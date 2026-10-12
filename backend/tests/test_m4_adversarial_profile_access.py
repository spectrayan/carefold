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

"""Adversarial stress testing suite for Profile Access & Admin Backdoor Removal (AU-06 / #165, Requirement R5).

Empirically challenges:
1. Admin user without explicit ProfileAccess grant CANNOT read foreign profile audit events (403 Forbidden).
2. Admin user without explicit ProfileAccess grant CANNOT delete foreign profile (403 Forbidden).
3. Admin user without explicit ProfileAccess grant CANNOT view foreign pending invites (list_all_viewer_invites does not leak).
4. Cross-tenant isolation when profile_id is omitted: never leaks foreign household audit events to regular users or admins.
5. Role elevation & privilege escalation prevention: admin cannot grant self access or mutate foreign profiles/consents.
6. Viewer role boundaries: users/admins with 'view_clinical' access can read permitted audit events but CANNOT delete or manage.
7. Injection & malformed input attacks on profile_id parameters (SQLi, wildcard, traversal).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, AsyncIterator, Dict
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.audit.logger import record_audit
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.models import AuditEventRecord, Profile, ProfileAccess, User, ViewerInvite
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app


# =============================================================================
# FIXTURES & HELPERS
# =============================================================================

@pytest.fixture
async def adv_audit_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Sets up an isolated database, local SQL auth provider, and FastAPI dependencies."""
    test_home = tmp_path / ".carefold"
    test_home.mkdir(parents=True, exist_ok=True)
    (test_home / "logs").mkdir(parents=True, exist_ok=True)

    db_url = f"sqlite+aiosqlite:///{test_home}/carefold.db"
    engine = create_db_engine(db_url)
    await init_db(engine)
    session_factory = get_session_factory(engine)
    sql_auth = SqlAuthAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    monkeypatch.setattr(settings, "home_dir", test_home)
    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setattr(settings, "audit_log_path", test_home / "logs" / "audit.jsonl")
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
            "home": test_home,
            "session_factory": session_factory,
            "engine": engine,
            "auth": sql_auth,
        }
    finally:
        app.dependency_overrides.clear()
        reset_auth_port()
        await engine.dispose()


async def create_authenticated_user(client: TestClient, email: str, username: str, is_admin: bool = False, session_factory=None) -> Dict[str, Any]:
    """Helper to register and login a user, optionally promoting to admin role."""
    reg_resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "username": username,
            "password": "SecurePassword123!",
            "full_name": f"User {username}",
        },
    )
    assert reg_resp.status_code in (200, 201), f"Registration failed: {reg_resp.text}"
    data = reg_resp.json()
    token = data.get("token")
    user_id = data.get("user", {}).get("id")

    if not token:
        login_resp = client.post(
            "/api/auth/login",
            json={"username": username, "password": "SecurePassword123!"},
        )
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        token = login_resp.json().get("token") or login_resp.json().get("session_token")
        assert token is not None, f"Token missing from login response: {login_resp.text}"
        user_id = login_resp.json().get("user", {}).get("id")

    if is_admin and session_factory:
        async with session_factory() as db:
            stmt = select(User).where(User.id == user_id)
            u = (await db.execute(stmt)).scalar_one()
            u.role = "admin"
            await db.commit()

    headers = {"Authorization": f"Bearer {token}"}
    return {
        "id": user_id,
        "email": email,
        "username": username,
        "token": token,
        "headers": headers,
    }


# =============================================================================
# TEST 1: ADMIN BACKDOOR REMOVAL - AUDIT EVENTS ACCESS
# =============================================================================

@pytest.mark.asyncio
async def test_admin_cannot_read_foreign_profile_audit_events(adv_audit_env):
    """Empirically verifies: Admin user without explicit ProfileAccess grant CANNOT read foreign profile audit events.

    Endpoints tested:
    - GET /api/v1/audit?profile_id=<foreign_id> -> 403 Forbidden
    - GET /api/audit?profile_id=<foreign_id> -> 403 Forbidden (backward compat dual-mount)
    """
    session_factory = adv_audit_env["session_factory"]

    with TestClient(app) as client:
        # Create Owner (Household A)
        owner = await create_authenticated_user(client, "alice_household@carefold.test", "alice_h", is_admin=False)
        # Create Admin (System Administrator)
        admin = await create_authenticated_user(client, "sys_admin@carefold.test", "sys_admin", is_admin=True, session_factory=session_factory)

        # Alice creates profile
        p_resp = client.post(
            "/api/v1/profiles",
            json={"name": "Alice Cardiology Prep", "relationship": "self"},
            headers=owner["headers"],
        )
        assert p_resp.status_code == 201
        alice_profile_id = p_resp.json()["id"]

        # Record clinical audit event for Alice's profile
        await record_audit(
            {
                "agent_id": "cardiology-guide",
                "event": "tool",
                "tool": "attach-read",
                "profile_id": alice_profile_id,
                "actor_user_id": owner["id"],
                "allowed": True,
            },
            payload={"ecg_result": "normal sinus rhythm"},
            session_factory=session_factory,
        )

        # 1. Admin attempts to read Alice's audit events via /api/v1/audit -> 403 Forbidden
        resp_v1 = client.get(
            f"/api/v1/audit?profile_id={alice_profile_id}",
            headers=admin["headers"],
        )
        assert resp_v1.status_code == 403, f"Admin was granted unauthorized audit access! Expected 403, got {resp_v1.status_code}"
        assert "Forbidden" in resp_v1.json().get("detail", "")

        # 2. Admin attempts to read Alice's audit events via /api/audit (dual-mount) -> 403 Forbidden
        resp_legacy = client.get(
            f"/api/audit?profile_id={alice_profile_id}",
            headers=admin["headers"],
        )
        assert resp_legacy.status_code == 403, f"Admin bypassed security via /api/audit! Expected 403, got {resp_legacy.status_code}"

        # 3. Owner CAN read their own audit events
        resp_owner = client.get(
            f"/api/v1/audit?profile_id={alice_profile_id}",
            headers=owner["headers"],
        )
        assert resp_owner.status_code == 200
        assert resp_owner.json()["total"] == 1


# =============================================================================
# TEST 2: ADMIN BACKDOOR REMOVAL - PROFILE DELETION & MUTATION
# =============================================================================

@pytest.mark.asyncio
async def test_admin_cannot_delete_or_mutate_foreign_profile(adv_audit_env):
    """Empirically verifies: Admin user CANNOT delete or mutate foreign profiles without explicit grant.

    Endpoints tested:
    - DELETE /api/v1/profiles/<foreign_secondary_id> -> 403 Forbidden
    - DELETE /api/v1/profiles/<foreign_primary_id> -> 403 Forbidden (not 400, no information leak)
    - PUT /api/v1/profiles/<foreign_secondary_id> -> 403 Forbidden
    - GET /api/v1/profiles/<foreign_secondary_id> -> 403 Forbidden
    """
    session_factory = adv_audit_env["session_factory"]

    with TestClient(app) as client:
        owner = await create_authenticated_user(client, "patient_jane@carefold.test", "patient_jane", is_admin=False)
        admin = await create_authenticated_user(client, "admin_attacker@carefold.test", "admin_attacker", is_admin=True, session_factory=session_factory)

        # Jane creates primary profile (auto-provisioned or created)
        me_resp = client.get("/api/v1/profiles", headers=owner["headers"])
        assert me_resp.status_code == 200
        jane_primary_id = me_resp.json()[0]["id"]

        # Jane creates secondary profile (Child)
        child_resp = client.post(
            "/api/v1/profiles",
            json={"name": "Baby Leo", "relationship": "child"},
            headers=owner["headers"],
        )
        assert child_resp.status_code == 201
        jane_child_id = child_resp.json()["id"]

        # 1. Admin attempts to DELETE secondary profile -> 403 Forbidden
        del_resp = client.delete(
            f"/api/v1/profiles/{jane_child_id}",
            headers=admin["headers"],
        )
        assert del_resp.status_code == 403, f"Admin deleted foreign profile! Expected 403, got {del_resp.status_code}"

        # 2. Admin attempts to DELETE primary profile -> 403 Forbidden (authorization check precedes primary check)
        del_pri_resp = client.delete(
            f"/api/v1/profiles/{jane_primary_id}",
            headers=admin["headers"],
        )
        assert del_pri_resp.status_code == 403, f"Admin received unexpected code deleting primary! Expected 403, got {del_pri_resp.status_code}"

        # 3. Admin attempts to GET foreign profile detail -> 403 Forbidden
        get_resp = client.get(
            f"/api/v1/profiles/{jane_child_id}",
            headers=admin["headers"],
        )
        assert get_resp.status_code == 403

        # 4. Admin attempts to PUT update foreign profile -> 403 Forbidden
        put_resp = client.put(
            f"/api/v1/profiles/{jane_child_id}",
            json={"name": "Compromised Leo"},
            headers=admin["headers"],
        )
        assert put_resp.status_code == 403

        # 5. Verify database integrity: profile was NOT modified or deleted
        async with session_factory() as db:
            p = (await db.execute(select(Profile).where(Profile.id == jane_child_id))).scalar_one_or_none()
            assert p is not None
            assert p.name == "Baby Leo"


# =============================================================================
# TEST 3: ADMIN BACKDOOR REMOVAL - VIEWER INVITES LEAKAGE
# =============================================================================

@pytest.mark.asyncio
async def test_admin_cannot_view_foreign_pending_invites(adv_audit_env):
    """Empirically verifies: Admin user CANNOT view foreign pending invites.

    `list_all_viewer_invites` (GET /api/v1/profiles/invites) must NOT leak foreign invites.
    """
    session_factory = adv_audit_env["session_factory"]

    with TestClient(app) as client:
        owner = await create_authenticated_user(client, "family_lead@carefold.test", "family_lead", is_admin=False)
        admin = await create_authenticated_user(client, "admin_snooper@carefold.test", "admin_snooper", is_admin=True, session_factory=session_factory)

        # Owner gets primary profile and creates an invite
        me_resp = client.get("/api/v1/profiles", headers=owner["headers"])
        prof_id = me_resp.json()[0]["id"]

        inv_resp = client.post(
            f"/api/v1/profiles/{prof_id}/invites",
            json={
                "invitee_name": "Specialist Dr. House",
                "role": "viewer",
                "view_clinical": True,
                "view_paperwork": True,
            },
            headers=owner["headers"],
        )
        assert inv_resp.status_code == 201
        secret_invite_code = inv_resp.json()["invite_code"]
        invite_id = inv_resp.json()["id"]

        # 1. Admin queries global /api/v1/profiles/invites -> MUST RETURN EMPTY LIST
        admin_invites_resp = client.get(
            "/api/v1/profiles/invites",
            headers=admin["headers"],
        )
        assert admin_invites_resp.status_code == 200
        admin_invites = admin_invites_resp.json()
        assert len(admin_invites) == 0, f"Foreign invite leaked to Admin! Leaked: {admin_invites}"

        # 2. Admin queries legacy alias /api/profiles/invites -> MUST RETURN EMPTY LIST
        admin_legacy_resp = client.get(
            "/api/profiles/invites",
            headers=admin["headers"],
        )
        assert admin_legacy_resp.status_code == 200
        assert len(admin_legacy_resp.json()) == 0

        # 3. Admin attempts to list invites for this specific profile -> 403 Forbidden
        admin_profile_inv_resp = client.get(
            f"/api/v1/profiles/{prof_id}/invites",
            headers=admin["headers"],
        )
        assert admin_profile_inv_resp.status_code == 403

        # 4. Admin attempts to create invite under foreign profile -> 403 Forbidden
        admin_create_inv = client.post(
            f"/api/v1/profiles/{prof_id}/invites",
            json={"invitee_name": "Rogue Viewer"},
            headers=admin["headers"],
        )
        assert admin_create_inv.status_code == 403

        # 5. Admin attempts to revoke foreign invite -> 403 Forbidden
        admin_revoke_inv = client.delete(
            f"/api/v1/profiles/{prof_id}/invites/{invite_id}",
            headers=admin["headers"],
        )
        assert admin_revoke_inv.status_code == 403

        # 6. Owner CAN see their own invite
        owner_invites = client.get("/api/v1/profiles/invites", headers=owner["headers"]).json()
        assert len(owner_invites) == 1
        assert owner_invites[0]["invite_code"] == secret_invite_code


# =============================================================================
# TEST 4: CROSS-TENANT OMITTED PROFILE_ID AUDIT QUERY ISOLATION
# =============================================================================

@pytest.mark.asyncio
async def test_omitted_profile_id_strict_multi_tenant_isolation(adv_audit_env):
    """Empirically verifies: Cross-tenant user cannot read another household's audit events even when profile_id is omitted.

    Creates multiple households and verifies:
    - User A sees only Household A's events.
    - User B sees only Household B's events.
    - Admin sees only Admin's own events, zero from Household A or Household B.
    - Unassociated User C sees zero events.
    """
    session_factory = adv_audit_env["session_factory"]

    with TestClient(app) as client:
        user_alice = await create_authenticated_user(client, "alice_multi@carefold.test", "alice_multi")
        user_bob = await create_authenticated_user(client, "bob_multi@carefold.test", "bob_multi")
        user_carol = await create_authenticated_user(client, "carol_multi@carefold.test", "carol_multi")
        user_admin = await create_authenticated_user(client, "admin_multi@carefold.test", "admin_multi", is_admin=True, session_factory=session_factory)

        # Alice creates 2 profiles: P_A1, P_A2
        p_a1 = client.post("/api/v1/profiles", json={"name": "Alice Self", "relationship": "self"}, headers=user_alice["headers"]).json()["id"]
        p_a2 = client.post("/api/v1/profiles", json={"name": "Alice Mom", "relationship": "parent"}, headers=user_alice["headers"]).json()["id"]

        # Bob creates 2 profiles: P_B1, P_B2
        p_b1 = client.post("/api/v1/profiles", json={"name": "Bob Self", "relationship": "self"}, headers=user_bob["headers"]).json()["id"]
        p_b2 = client.post("/api/v1/profiles", json={"name": "Bob Son", "relationship": "child"}, headers=user_bob["headers"]).json()["id"]

        # Record audit events:
        # Alice P_A1 (2 events)
        await record_audit({"agent_id": "cardiology-guide", "event": "run", "profile_id": p_a1, "actor_user_id": user_alice["id"]}, payload={"a": 1}, session_factory=session_factory)
        await record_audit({"agent_id": "cardiology-guide", "event": "tool", "profile_id": p_a1, "actor_user_id": user_alice["id"]}, payload={"a": 2}, session_factory=session_factory)
        # Alice P_A2 (1 event)
        await record_audit({"agent_id": "oncology-navigator", "event": "run", "profile_id": p_a2, "actor_user_id": user_alice["id"]}, payload={"a": 3}, session_factory=session_factory)
        # Alice un-profiled actor event (1 event)
        await record_audit({"agent_id": "system", "event": "run", "actor_user_id": user_alice["id"]}, payload={"a": 4}, session_factory=session_factory)

        # Bob P_B1 (2 events)
        await record_audit({"agent_id": "pulmonology-guide", "event": "run", "profile_id": p_b1, "actor_user_id": user_bob["id"]}, payload={"b": 1}, session_factory=session_factory)
        await record_audit({"agent_id": "pulmonology-guide", "event": "tool", "profile_id": p_b1, "actor_user_id": user_bob["id"]}, payload={"b": 2}, session_factory=session_factory)
        # Bob P_B2 (1 event)
        await record_audit({"agent_id": "ortho-guide", "event": "run", "profile_id": p_b2, "actor_user_id": user_bob["id"]}, payload={"b": 3}, session_factory=session_factory)
        # Bob un-profiled actor event (1 event)
        await record_audit({"agent_id": "system", "event": "run", "actor_user_id": user_bob["id"]}, payload={"b": 4}, session_factory=session_factory)

        # Admin un-profiled actor event (1 event)
        await record_audit({"agent_id": "admin-panel", "event": "run", "actor_user_id": user_admin["id"]}, payload={"admin": 1}, session_factory=session_factory)

        # Total 9 events in database

        # 1. Alice queries /api/v1/audit (no profile_id)
        resp_alice = client.get("/api/v1/audit", headers=user_alice["headers"])
        assert resp_alice.status_code == 200
        alice_data = resp_alice.json()
        assert alice_data["total"] == 4
        alice_profs = {e["profile_id"] for e in alice_data["events"] if e["profile_id"]}
        assert alice_profs == {p_a1, p_a2}
        # Zero leakage from Bob or Admin
        for e in alice_data["events"]:
            assert e["profile_id"] not in (p_b1, p_b2)
            assert e["actor_user_id"] != user_bob["id"]
            assert e["actor_user_id"] != user_admin["id"]

        # 2. Bob queries /api/v1/audit (no profile_id)
        resp_bob = client.get("/api/v1/audit", headers=user_bob["headers"])
        assert resp_bob.status_code == 200
        bob_data = resp_bob.json()
        assert bob_data["total"] == 4
        bob_profs = {e["profile_id"] for e in bob_data["events"] if e["profile_id"]}
        assert bob_profs == {p_b1, p_b2}
        # Zero leakage from Alice or Admin
        for e in bob_data["events"]:
            assert e["profile_id"] not in (p_a1, p_a2)
            assert e["actor_user_id"] != user_alice["id"]
            assert e["actor_user_id"] != user_admin["id"]

        # 3. Admin queries /api/v1/audit (no profile_id) -> MUST NOT SEE ALICE OR BOB!
        resp_admin = client.get("/api/v1/audit", headers=user_admin["headers"])
        assert resp_admin.status_code == 200
        admin_data = resp_admin.json()
        assert admin_data["total"] == 1
        assert admin_data["events"][0]["actor_user_id"] == user_admin["id"]
        for e in admin_data["events"]:
            assert e["profile_id"] not in (p_a1, p_a2, p_b1, p_b2)

        # 4. Carol (unassociated user with no profiles and no actions)
        resp_carol = client.get("/api/v1/audit", headers=user_carol["headers"])
        assert resp_carol.status_code == 200
        carol_data = resp_carol.json()
        assert carol_data["total"] == 0
        assert len(carol_data["events"]) == 0


# =============================================================================
# TEST 5: PRIVILEGE ESCALATION ATTEMPTS & ACCESS CONTROL MUTATIONS
# =============================================================================

@pytest.mark.asyncio
async def test_admin_privilege_escalation_and_access_mutations_blocked(adv_audit_env):
    """Empirically verifies: Admin CANNOT grant themselves access or tamper with foreign access grants.

    Endpoints tested:
    - POST /api/v1/profiles/<foreign_id>/access -> 403 Forbidden
    - GET /api/v1/profiles/<foreign_id>/access -> 403 Forbidden
    - DELETE /api/v1/profiles/<foreign_id>/access/<user_id> -> 403 Forbidden
    - GET /api/v1/profiles/<foreign_id>/consent -> 403 Forbidden
    - PUT /api/v1/profiles/<foreign_id>/consent -> 403 Forbidden
    """
    session_factory = adv_audit_env["session_factory"]

    with TestClient(app) as client:
        owner = await create_authenticated_user(client, "victim@carefold.test", "victim", is_admin=False)
        admin = await create_authenticated_user(client, "escalator@carefold.test", "escalator", is_admin=True, session_factory=session_factory)

        p_resp = client.post("/api/v1/profiles", json={"name": "Confidential Dossier", "relationship": "self"}, headers=owner["headers"])
        foreign_prof_id = p_resp.json()["id"]

        # 1. Admin attempts to grant themselves 'manage' access -> 403 Forbidden
        escalate_resp = client.post(
            f"/api/v1/profiles/{foreign_prof_id}/access",
            json={"user_id": admin["id"], "access_level": "manage"},
            headers=admin["headers"],
        )
        assert escalate_resp.status_code == 403, f"Admin escalated privileges! Expected 403, got {escalate_resp.status_code}"

        # 2. Admin attempts to list access grants -> 403 Forbidden
        list_acc_resp = client.get(
            f"/api/v1/profiles/{foreign_prof_id}/access",
            headers=admin["headers"],
        )
        assert list_acc_resp.status_code == 403

        # 3. Admin attempts to revoke owner's access -> 403 Forbidden
        rev_resp = client.delete(
            f"/api/v1/profiles/{foreign_prof_id}/access/{owner['id']}",
            headers=admin["headers"],
        )
        assert rev_resp.status_code == 403

        # 4. Admin attempts to view clinical consent -> 403 Forbidden
        get_cons_resp = client.get(
            f"/api/v1/profiles/{foreign_prof_id}/consent",
            headers=admin["headers"],
        )
        assert get_cons_resp.status_code == 403

        # 5. Admin attempts to update clinical consent -> 403 Forbidden
        put_cons_resp = client.put(
            f"/api/v1/profiles/{foreign_prof_id}/consent",
            json={"allow_clinical": True},
            headers=admin["headers"],
        )
        assert put_cons_resp.status_code == 403


# =============================================================================
# TEST 6: VIEWER ROLE BOUNDARIES (READ-ONLY GRANT DOES NOT GRANT MANAGE)
# =============================================================================

@pytest.mark.asyncio
async def test_viewer_grant_allows_audit_read_but_blocks_deletion_and_invites(adv_audit_env):
    """Empirically verifies: Explicit 'view_clinical' grant permits audit read but BLOCKS management actions.

    Even if an admin (or user) has an explicit 'view_clinical' grant on a profile:
    - Reading audit events -> 200 OK
    - Deleting profile -> 403 Forbidden
    - Creating invites -> 403 Forbidden
    - Granting access -> 403 Forbidden
    """
    session_factory = adv_audit_env["session_factory"]

    with TestClient(app) as client:
        owner = await create_authenticated_user(client, "alice_viewer_test@carefold.test", "alice_vt")
        admin = await create_authenticated_user(client, "admin_viewer_test@carefold.test", "admin_vt", is_admin=True, session_factory=session_factory)

        p_resp = client.post("/api/v1/profiles", json={"name": "Alice Monitored Care", "relationship": "parent"}, headers=owner["headers"])
        prof_id = p_resp.json()["id"]

        # Record audit event for this profile
        await record_audit(
            {"agent_id": "gastro-guide", "event": "run", "profile_id": prof_id, "actor_user_id": owner["id"]},
            payload={"symptom": "gerd"},
            session_factory=session_factory,
        )

        # Owner explicitly grants Admin 'view_clinical' access
        grant_resp = client.post(
            f"/api/v1/profiles/{prof_id}/access",
            json={"user_id": admin["id"], "access_level": "view_clinical"},
            headers=owner["headers"],
        )
        assert grant_resp.status_code == 201

        # 1. Admin CAN now read audit events for this specific profile
        audit_resp = client.get(f"/api/v1/audit?profile_id={prof_id}", headers=admin["headers"])
        assert audit_resp.status_code == 200
        assert audit_resp.json()["total"] == 1

        # 2. But Admin CANNOT delete the profile ('view_clinical' is not 'manage')
        del_resp = client.delete(f"/api/v1/profiles/{prof_id}", headers=admin["headers"])
        assert del_resp.status_code == 403, f"Viewer role was allowed to delete profile! Expected 403, got {del_resp.status_code}"

        # 3. Admin CANNOT create invites on the profile
        inv_resp = client.post(
            f"/api/v1/profiles/{prof_id}/invites",
            json={"invitee_name": "Nurse Kelly"},
            headers=admin["headers"],
        )
        assert inv_resp.status_code == 403

        # 4. Admin CANNOT grant access to others
        acc_resp = client.post(
            f"/api/v1/profiles/{prof_id}/access",
            json={"email": "third_party@test.local", "access_level": "view_clinical"},
            headers=admin["headers"],
        )
        assert acc_resp.status_code == 403


# =============================================================================
# TEST 7: INJECTION & MALFORMED INPUT ATTACKS ON PROFILE_ID
# =============================================================================

@pytest.mark.asyncio
async def test_malformed_and_injection_profile_id_resilience(adv_audit_env):
    """Empirically verifies: Malformed profile_id and injection payloads fail closed safely."""
    with TestClient(app) as client:
        user = await create_authenticated_user(client, "test_sqli@carefold.test", "test_sqli")

        adversarial_payloads = [
            "' OR '1'='1",
            "'; DROP TABLE audit_events; --",
            "../../etc/passwd",
            "%00",
            "*",
            "%",
            "non-existent-uuid-99999",
        ]

        for payload in adversarial_payloads:
            resp = client.get(f"/api/v1/audit?profile_id={payload}", headers=user["headers"])
            # Must return 404 Not Found (or 400/422), NEVER 200 with data, and NEVER 500
            assert resp.status_code in (404, 400, 422), (
                f"Payload '{payload}' yielded unexpected status code: {resp.status_code}"
            )
