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

"""Comprehensive test suite for database-backed audit logging and profile access security.

Verifies:
1. SQL audit event insertion with SHA-256 canonical payload hash calculation.
2. Query by profile_id with valid permission returns matching records.
3. Query by unauthorized user returns 403, non-existent profile returns 404.
4. Admin user without explicit grant cannot read foreign profile audit events or manage profile.
5. Query with omitted profile_id strictly filters to accessible profiles and user actor events.
6. Secondary JSONL sink writes and non-blocking error isolation on DB or disk failures.
7. Tool execution events automatically populate payload_hash.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, AsyncIterator, Dict
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.audit.logger import (
    AuditLogger,
    compute_payload_hash,
    get_recent_audit_events,
    record_audit,
)
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.models import AuditEventRecord, Profile, ProfileAccess, User
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app
from carefold.schemas.audit import AuditEvent


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
async def audit_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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


def register_user(client: TestClient, email: str, username: str) -> Dict[str, Any]:
    """Helper to register and login a user via API."""
    reg_resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "username": username,
            "password": "Password123!",
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
            json={"username": username, "password": "Password123!"},
        )
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        token = login_resp.json().get("session_token")
        user_id = login_resp.json().get("user", {}).get("id")

    cookies = {"carefold_session": token} if token else dict(reg_resp.cookies)
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    return {
        "id": user_id,
        "email": email,
        "username": username,
        "token": token,
        "headers": headers,
        "cookies": cookies,
    }


# =============================================================================
# 1. CANONICAL PAYLOAD HASH CALCULATION TESTS
# =============================================================================

def test_compute_payload_hash_key_order_invariance():
    """Validates that compute_payload_hash produces identical digests regardless of key ordering."""
    p1 = {"b": 2, "a": 1, "nested": {"z": 26, "y": 25}}
    p2 = {"nested": {"y": 25, "z": 26}, "a": 1, "b": 2}

    h1 = compute_payload_hash(p1)
    h2 = compute_payload_hash(p2)

    assert h1 is not None
    assert len(h1) == 64
    assert h1 == h2, f"Hashes must be identical regardless of key order: {h1} vs {h2}"


def test_compute_payload_hash_none_and_empty():
    """Validates that None and empty string return None."""
    assert compute_payload_hash(None) is None
    assert compute_payload_hash("") is None
    assert compute_payload_hash("   ") is None


def test_compute_payload_hash_complex_data():
    """Validates hashing of lists, primitives, and deterministic SHA-256 match."""
    payload = {"tool": "attach-read", "args": {"path": "bloodwork.pdf", "page": 1}}
    expected_canonical = json.dumps(payload, sort_keys=True, default=str)
    expected_hash = hashlib.sha256(expected_canonical.encode("utf-8")).hexdigest()

    actual_hash = compute_payload_hash(payload)
    assert actual_hash == expected_hash
    assert actual_hash == AuditLogger.compute_payload_hash(payload)


# =============================================================================
# 2. SQL AUDIT EVENT INSERTION WITH PAYLOAD HASH
# =============================================================================

@pytest.mark.asyncio
async def test_sql_audit_event_insertion_with_payload_hash(audit_env):
    """Tests recording an audit event to SQL database with SHA-256 payload hash."""
    session_factory = audit_env["session_factory"]

    # Pre-populate parent user and profile to satisfy foreign key constraints
    async with session_factory() as db:
        user = User(
            id="user-789",
            email="user789@carefold.test",
            username="user789",
            hashed_password="hash",
            role="member",
        )
        db.add(user)
        profile = Profile(
            id="prof-123",
            user_id="user-789",
            name="Alice Profile",
            relationship="self",
        )
        db.add(profile)
        await db.commit()

    test_payload = {"tool": "attach-read", "filename": "cardiac_mri.pdf", "options": {"page": 2}}
    expected_hash = compute_payload_hash(test_payload)

    ev = AuditEvent(
        agent_id="cardiology-guide",
        event="tool",
        tool="attach-read",
        allowed=True,
        profile_id="prof-123",
        thread_id="run-456",
    )

    recorded = await record_audit(
        ev,
        payload=test_payload,
        actor_user_id="user-789",
        principal="agent",
        risk="clinical_assist",
        session_factory=session_factory,
    )

    assert recorded is not None

    # Verify directly from database table audit_events
    async with session_factory() as db:
        stmt = select(AuditEventRecord).where(AuditEventRecord.profile_id == "prof-123")
        res = await db.execute(stmt)
        record = res.scalar_one_or_none()

        assert record is not None
        assert record.tool == "attach-read"
        assert record.event == "tool"
        assert record.profile_id == "prof-123"
        assert record.actor_user_id == "user-789"
        assert record.principal == "agent"
        assert record.run_id == "run-456"
        assert record.decision == "allow"
        assert record.risk == "clinical_assist"
        assert record.payload_hash == expected_hash
        assert isinstance(record.ts, datetime)


# =============================================================================
# 3. QUERY BY PROFILE_ID WITH VALID PERMISSION
# =============================================================================

@pytest.mark.asyncio
async def test_query_by_profile_id_with_valid_permission(audit_env):
    """Tests query by profile_id returns matching records when caller owns or has access."""
    session_factory = audit_env["session_factory"]

    with TestClient(app) as client:
        user_a = register_user(client, "alice@carefold.test", "alice")

        # Create Profile A1 for Alice
        p_resp = client.post(
            "/api/v1/profiles",
            json={"name": "Alice Health Profile", "relationship": "self"},
            headers=user_a["headers"],
        )
        assert p_resp.status_code == 201
        profile_id = p_resp.json()["id"]

        # Record audit event for Profile A1
        await record_audit(
            {
                "agent_id": "cardiology-guide",
                "event": "run",
                "profile_id": profile_id,
                "actor_user_id": user_a["id"],
                "tool": "visit-prep",
            },
            payload={"notes": "check heart rate"},
            session_factory=session_factory,
        )

        # Query via /api/v1/audit?profile_id={profile_id}
        resp_v1 = client.get(f"/api/v1/audit?profile_id={profile_id}", headers=user_a["headers"])
        assert resp_v1.status_code == 200
        data_v1 = resp_v1.json()
        assert data_v1["total"] == 1
        assert len(data_v1["events"]) == 1
        event_v1 = data_v1["events"][0]
        assert event_v1["profile_id"] == profile_id
        assert event_v1["payload_hash"] is not None
        assert event_v1["agent_id"] == "cardiology-guide"

        # Also verify backward-compatible dual-mount /api/audit
        resp_compat = client.get(f"/api/audit?profile_id={profile_id}", headers=user_a["headers"])
        assert resp_compat.status_code == 200
        assert resp_compat.json()["total"] == 1


# =============================================================================
# 4. CROSS-PROFILE ISOLATION: UNAUTHORIZED USER (403) & NON-EXISTENT (404)
# =============================================================================

def test_query_by_unauthorized_user_returns_403_and_404(audit_env):
    """Tests cross-profile isolation: unauthorized user receives 403, missing profile 404."""
    with TestClient(app) as client:
        user_a = register_user(client, "user_a@carefold.test", "user_a")
        user_b = register_user(client, "user_b@carefold.test", "user_b")

        # User A creates Profile A1
        p_resp = client.post(
            "/api/v1/profiles",
            json={"name": "User A Profile", "relationship": "self"},
            headers=user_a["headers"],
        )
        profile_a = p_resp.json()["id"]

        # User B queries User A's profile audit events -> 403 Forbidden
        resp_unauth = client.get(f"/api/v1/audit?profile_id={profile_a}", headers=user_b["headers"])
        assert resp_unauth.status_code == 403, f"Expected 403, got: {resp_unauth.status_code}"

        # Query non-existent profile -> 404 Not Found
        resp_404 = client.get("/api/v1/audit?profile_id=nonexistent-000-000", headers=user_a["headers"])
        assert resp_404.status_code == 404, f"Expected 404, got: {resp_404.status_code}"


# =============================================================================
# 5. ADMIN USER WITHOUT EXPLICIT GRANT CANNOT ACCESS FOREIGN PROFILES
# =============================================================================

@pytest.mark.asyncio
async def test_admin_without_explicit_grant_denied_audit_and_management(audit_env):
    """Validates that system administrators cannot read foreign profile audits or manage profiles without explicit grant."""
    session_factory = audit_env["session_factory"]

    with TestClient(app) as client:
        user_owner = register_user(client, "owner@carefold.test", "owner")
        user_admin = register_user(client, "admin@carefold.test", "admin")

        # Elevate user_admin role to 'admin' in database
        async with session_factory() as db:
            stmt = select(User).where(User.id == user_admin["id"])
            u = (await db.execute(stmt)).scalar_one()
            u.role = "admin"
            await db.commit()

        # Owner creates Profile
        p_resp = client.post(
            "/api/v1/profiles",
            json={"name": "Confidential Health Profile", "relationship": "self"},
            headers=user_owner["headers"],
        )
        assert p_resp.status_code == 201
        profile_id = p_resp.json()["id"]

        # Record audit event for Owner's profile
        await record_audit(
            {
                "agent_id": "neurology-guide",
                "event": "run",
                "profile_id": profile_id,
                "actor_user_id": user_owner["id"],
            },
            payload={"symptom": "migraine"},
            session_factory=session_factory,
        )

        # 1. Admin attempts to read Owner's profile audit events -> 403 Forbidden!
        resp_admin_audit = client.get(
            f"/api/v1/audit?profile_id={profile_id}",
            headers=user_admin["headers"],
        )
        assert resp_admin_audit.status_code == 403, (
            f"Admin without explicit grant must receive 403 Forbidden on audit, got {resp_admin_audit.status_code}"
        )

        # 2. Admin attempts to delete Owner's profile -> 403 Forbidden!
        resp_admin_del = client.delete(
            f"/api/v1/profiles/{profile_id}",
            headers=user_admin["headers"],
        )
        assert resp_admin_del.status_code == 403, (
            f"Admin without explicit grant must receive 403 Forbidden on delete, got {resp_admin_del.status_code}"
        )

        # 3. Admin attempts to list viewer invites for Owner's profile -> 403 Forbidden!
        resp_admin_inv = client.get(
            f"/api/v1/profiles/{profile_id}/invites",
            headers=user_admin["headers"],
        )
        assert resp_admin_inv.status_code == 403, (
            f"Admin without explicit grant must receive 403 Forbidden on invites, got {resp_admin_inv.status_code}"
        )

        # 4. Now grant Admin explicit 'manage' access via ProfileAccess
        async with session_factory() as db:
            grant = ProfileAccess(
                profile_id=profile_id,
                user_id=user_admin["id"],
                access_level="manage",
            )
            db.add(grant)
            await db.commit()

        # 5. After explicit grant, Admin CAN access audit events
        resp_granted = client.get(
            f"/api/v1/audit?profile_id={profile_id}",
            headers=user_admin["headers"],
        )
        assert resp_granted.status_code == 200
        assert resp_granted.json()["total"] == 1


# =============================================================================
# 6. OMITTED PROFILE_ID STRICT SCOPING (NO SYSTEM-WIDE AUDIT LEAKAGE)
# =============================================================================

@pytest.mark.asyncio
async def test_omitted_profile_id_strict_user_scoping(audit_env):
    """Validates that omitting profile_id returns only accessible profiles and caller's events, never leaking foreign events."""
    session_factory = audit_env["session_factory"]

    with TestClient(app) as client:
        user_alice = register_user(client, "alice_scope@carefold.test", "alice_scope")
        user_bob = register_user(client, "bob_scope@carefold.test", "bob_scope")

        # Alice creates profile
        p_alice = client.post(
            "/api/v1/profiles",
            json={"name": "Alice Records", "relationship": "self"},
            headers=user_alice["headers"],
        ).json()["id"]

        # Bob creates profile
        p_bob = client.post(
            "/api/v1/profiles",
            json={"name": "Bob Records", "relationship": "self"},
            headers=user_bob["headers"],
        ).json()["id"]

        # Record events for Alice and Bob
        await record_audit(
            {"agent_id": "agent-a", "event": "run", "profile_id": p_alice, "actor_user_id": user_alice["id"]},
            payload={"alice": 1},
            session_factory=session_factory,
        )
        await record_audit(
            {"agent_id": "agent-b", "event": "run", "profile_id": p_bob, "actor_user_id": user_bob["id"]},
            payload={"bob": 2},
            session_factory=session_factory,
        )

        # Alice queries /api/v1/audit without profile_id
        resp = client.get("/api/v1/audit", headers=user_alice["headers"])
        assert resp.status_code == 200
        data = resp.json()

        # Alice should see her own profile event, but NEVER Bob's event
        profile_ids = [e["profile_id"] for e in data["events"]]
        assert p_alice in profile_ids
        assert p_bob not in profile_ids, "Cross-tenant audit leak detected: Bob's profile event leaked to Alice!"


# =============================================================================
# 7. SECONDARY JSONL SINK & NON-BLOCKING FAULT ISOLATION
# =============================================================================

@pytest.mark.asyncio
async def test_secondary_jsonl_sink_writes(audit_env):
    """Tests that record_audit writes to secondary JSONL sink with payload_hash."""
    log_file = audit_env["home"] / "logs" / "secondary_audit.jsonl"
    payload = {"tool": "notes-read", "note_id": "note-1"}
    p_hash = compute_payload_hash(payload)

    ev = AuditEvent(
        agent_id="test-agent",
        event="tool",
        tool="notes-read",
        allowed=True,
    )

    await record_audit(
        ev,
        log_path=log_file,
        payload=payload,
        session_factory=audit_env["session_factory"],
    )

    assert log_file.is_file()
    lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]["tool"] == "notes-read"
    assert lines[0]["payload_hash"] == p_hash


@pytest.mark.asyncio
async def test_non_blocking_fault_isolation_on_db_failure(monkeypatch):
    """Tests that database persistence failure logs a warning without crashing agent execution."""
    ev = AuditEvent(
        agent_id="crash-test-agent",
        event="run",
        allowed=True,
    )

    # Supply an invalid session factory that raises RuntimeError
    class BrokenSessionFactory:
        def __call__(self):
            raise RuntimeError("Simulated database disk I/O failure")

    # record_audit must succeed without raising an exception
    result = await record_audit(
        ev,
        session_factory=BrokenSessionFactory(),
    )
    assert result is not None
    assert result.agent_id == "crash-test-agent"


# =============================================================================
# 8. TOOL EXECUTION EVENT AUTOMATIC PAYLOAD HASHING
# =============================================================================

@pytest.mark.asyncio
async def test_tool_execution_event_populates_payload_hash(audit_env):
    """Validates that tool execution events automatically compute and populate payload_hash from args."""
    session_factory = audit_env["session_factory"]

    # Pre-populate profile
    async with session_factory() as db:
        prof = Profile(
            id="prof-tool-test",
            name="Tool Test Profile",
            relationship="self",
        )
        db.add(prof)
        await db.commit()

    tool_args = {"path": "lab_results.pdf", "max_bytes": 1024}
    expected_hash = compute_payload_hash(tool_args)

    # Calling with dictionary carrying args
    event_dict = {
        "agent_id": "visit-steward",
        "event": "tool",
        "tool": "attach-read",
        "args": tool_args,
        "allowed": True,
        "profile_id": "prof-tool-test",
    }

    await record_audit(event_dict, session_factory=session_factory)

    async with session_factory() as db:
        stmt = select(AuditEventRecord).where(AuditEventRecord.profile_id == "prof-tool-test")
        res = await db.execute(stmt)
        record = res.scalar_one_or_none()

        assert record is not None
        assert record.tool == "attach-read"
        assert record.payload_hash == expected_hash
