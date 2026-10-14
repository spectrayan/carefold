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

"""Unit and integration test suite for Approvals REST API and Atomic Resumption (AU-18, ADR-0004)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.approvals import (
    ApprovalDecideRequest,
    consume_approval_atomic,
    router as approvals_router,
)
from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.auth.ports import UserProfile, UserUpdate
from carefold.config import settings
from carefold.db.models import Approval, Profile, ProfileAccess
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.engine.tool_exec import canonical_json, compute_payload_hash
from carefold.main import app


def run_async(coro):
    """Runs an asynchronous coroutine synchronously in an isolated event loop."""
    return asyncio.run(coro)


@pytest.fixture
def approvals_test_env(monkeypatch):
    """Sets up an isolated in-memory DB, SQL auth provider, and mounts approvals router."""

    async def _setup():
        engine = create_db_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = get_session_factory(engine)
        auth_adapter = SqlAuthAdapter(session_factory=session_factory)

        monkeypatch.setattr(settings, "auth_provider", "local")
        set_auth_port(auth_adapter)

        # Register test users
        # 1. Alice (Account Owner)
        alice = await auth_adapter.register_user(
            email="alice@test.local",
            username="alice",
            password="AlicePassword123!",
            full_name="Alice Owner",
            role="member",
            auth_provider="local",
        )
        alice_session = await auth_adapter.create_session(alice.id)

        # 2. Bob (Delegate with explicit 'manage' access grant)
        bob = await auth_adapter.register_user(
            email="bob@test.local",
            username="bob",
            password="BobPassword123!",
            full_name="Bob Manager",
            role="member",
            auth_provider="local",
        )
        bob_session = await auth_adapter.create_session(bob.id)

        # 3. Charlie (Viewer with only 'view_clinical' access grant, NOT 'manage')
        charlie = await auth_adapter.register_user(
            email="charlie@test.local",
            username="charlie",
            password="CharliePassword123!",
            full_name="Charlie Viewer",
            role="member",
            auth_provider="local",
        )
        charlie_session = await auth_adapter.create_session(charlie.id)

        # 4. Eve (Unauthorized external user)
        eve = await auth_adapter.register_user(
            email="eve@test.local",
            username="eve",
            password="EvePassword123!",
            full_name="Eve Attacker",
            role="member",
            auth_provider="local",
        )
        eve_session = await auth_adapter.create_session(eve.id)

        # 5. Admin (System administrator with role='admin' but NO explicit profile grant)
        admin = await auth_adapter.register_user(
            email="admin@test.local",
            username="admin_user",
            password="AdminPassword123!",
            full_name="System Admin",
            role="admin",
            auth_provider="local",
        )
        await auth_adapter.update_user(admin.id, UserUpdate(role="admin"))
        admin_session = await auth_adapter.create_session(admin.id)

        # Provision Alice's profile and access grants
        async with session_factory() as session:
            alice_profile = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Alice",
                relationship="self",
                role="self",
                is_primary=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(alice_profile)

            # Grant Bob 'manage' access
            bob_grant = ProfileAccess(
                id=str(uuid.uuid4()),
                profile_id=alice_profile.id,
                user_id=bob.id,
                access_level="manage",
                granted_by=alice.id,
                granted_at=datetime.now(timezone.utc),
            )
            session.add(bob_grant)

            # Grant Charlie 'view_clinical' access (not 'manage')
            charlie_grant = ProfileAccess(
                id=str(uuid.uuid4()),
                profile_id=alice_profile.id,
                user_id=charlie.id,
                access_level="view_clinical",
                granted_by=alice.id,
                granted_at=datetime.now(timezone.utc),
            )
            session.add(charlie_grant)

            await session.commit()
            profile_id = alice_profile.id

        return {
            "session_factory": session_factory,
            "profile_id": profile_id,
            "alice": alice,
            "alice_token": alice_session.token,
            "bob": bob,
            "bob_token": bob_session.token,
            "charlie": charlie,
            "charlie_token": charlie_session.token,
            "eve": eve,
            "eve_token": eve_session.token,
            "admin": admin,
            "admin_token": admin_session.token,
        }

    env_data = run_async(_setup())
    session_factory = env_data["session_factory"]

    # Mount approvals router if not already mounted
    if not getattr(app.state, "approvals_router_mounted", False):
        app.include_router(approvals_router, prefix="/api/approvals", tags=["approvals"])
        app.include_router(
            approvals_router,
            prefix="/api/profiles/{profile_id}/approvals",
            tags=["approvals"],
            include_in_schema=False,
        )
        app.state.approvals_router_mounted = True

    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield env_data
    finally:
        app.dependency_overrides.pop(get_db, None)
        reset_auth_port()


# ============================================================================
# Section 1: GET /api/approvals Tests
# ============================================================================


def test_list_pending_approvals_as_owner(approvals_test_env):
    """Owner with account ownership can list pending approvals."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]

    now = datetime.now(timezone.utc)
    test_args = {"medication": "Amoxicillin", "dose_mg": 500}
    approval_id = f"app-{uuid.uuid4().hex[:8]}"

    async def _insert():
        async with session_factory() as session:
            appr = Approval(
                id=approval_id,
                profile_id=profile_id,
                run_id="run-test-1",
                thread_id="thread-test-1",
                tool_name="schedule_followup",
                args_redacted=json.dumps(test_args),
                payload_hash=compute_payload_hash(test_args),
                destination_hosts=json.dumps(["api.hospital.org"]),
                risk_tier="write_external",
                status="pending",
                expires_at=now + timedelta(minutes=30),
                created_at=now,
            )
            session.add(appr)
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        resp = client.get(
            f"/api/approvals?profile_id={profile_id}",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) == 1
        item = data[0]
        assert item["id"] == approval_id
        assert item["tool_name"] == "schedule_followup"
        assert item["status"] == "pending"
        assert item["risk_tier"] == "write_external"
        assert item["destination_hosts"] == ["api.hospital.org"]
        assert item["args"]["medication"] == "Amoxicillin"


def test_list_pending_approvals_as_manager(approvals_test_env):
    """Delegate user with explicit 'manage' access can list pending approvals."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]

    now = datetime.now(timezone.utc)

    async def _insert():
        async with session_factory() as session:
            appr = Approval(
                id=f"app-{uuid.uuid4().hex[:8]}",
                profile_id=profile_id,
                run_id="run-1",
                tool_name="send_records",
                args_redacted="{}",
                payload_hash=compute_payload_hash({}),
                risk_tier="irreversible",
                status="pending",
                expires_at=now + timedelta(minutes=15),
                created_at=now,
            )
            session.add(appr)
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        resp = client.get(
            f"/api/approvals?profile_id={profile_id}",
            headers={"Authorization": f"Bearer {env['bob_token']}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1


def test_list_pending_approvals_viewer_forbidden(approvals_test_env):
    """Viewer with only 'view_clinical' cannot list approvals (requires 'manage')."""
    env = approvals_test_env
    profile_id = env["profile_id"]

    with TestClient(app) as client:
        resp = client.get(
            f"/api/approvals?profile_id={profile_id}",
            headers={"Authorization": f"Bearer {env['charlie_token']}"},
        )
        assert resp.status_code == 403
        assert "management privileges required" in resp.json()["detail"]


def test_list_pending_approvals_unauthorized_user_forbidden(approvals_test_env):
    """External user with no grant on profile receives 403 Forbidden."""
    env = approvals_test_env
    profile_id = env["profile_id"]

    with TestClient(app) as client:
        resp = client.get(
            f"/api/approvals?profile_id={profile_id}",
            headers={"Authorization": f"Bearer {env['eve_token']}"},
        )
        assert resp.status_code == 403


def test_list_approvals_admin_without_manage_denied(approvals_test_env):
    """System administrator without explicit manage grant on profile is DENIED (AU-18 invariant)."""
    env = approvals_test_env
    profile_id = env["profile_id"]

    with TestClient(app) as client:
        resp = client.get(
            f"/api/approvals?profile_id={profile_id}",
            headers={"Authorization": f"Bearer {env['admin_token']}"},
        )
        assert resp.status_code == 403
        assert "management privileges required" in resp.json()["detail"]


# ============================================================================
# Section 2: POST /api/approvals/{id}/decide Tests
# ============================================================================


def test_decide_approval_approve_success(approvals_test_env):
    """Approving a pending request updates status to 'approved' with decided_at and decided_by."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]
    approval_id = f"app-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    args = {"action": "sync_calendar", "event_id": "ev-101"}

    async def _insert():
        async with session_factory() as session:
            appr = Approval(
                id=approval_id,
                profile_id=profile_id,
                run_id="run-1",
                tool_name="sync_calendar",
                args_redacted=json.dumps(args),
                payload_hash=compute_payload_hash(args),
                risk_tier="write_external",
                status="pending",
                expires_at=now + timedelta(minutes=15),
                created_at=now,
            )
            session.add(appr)
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        resp = client.post(
            f"/api/approvals/{approval_id}/decide",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
            json={"decision": "approved"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == approval_id
        assert data["status"] == "approved"
        assert data["decided_by"] == env["alice"].id
        assert data["decided_at"] is not None


def test_decide_approval_with_edited_args_recomputes_payload_hash(approvals_test_env):
    """When edited_args is provided during approval, payload_hash and args_redacted are updated."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]
    approval_id = f"app-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    original_args = {"dose_mg": 100, "refill_count": 3}
    edited_args = {"dose_mg": 50, "refill_count": 1}

    async def _insert():
        async with session_factory() as session:
            appr = Approval(
                id=approval_id,
                profile_id=profile_id,
                run_id="run-1",
                tool_name="order_prescription",
                args_redacted=json.dumps(original_args),
                payload_hash=compute_payload_hash(original_args),
                risk_tier="irreversible",
                status="pending",
                expires_at=now + timedelta(minutes=15),
                created_at=now,
            )
            session.add(appr)
            await session.commit()

    run_async(_insert())

    expected_new_hash = compute_payload_hash(edited_args)
    assert expected_new_hash != compute_payload_hash(original_args)

    with TestClient(app) as client:
        resp = client.post(
            f"/api/approvals/{approval_id}/decide",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
            json={"decision": "approved", "edited_args": edited_args},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["payload_hash"] == expected_new_hash
        assert data["args"]["dose_mg"] == 50
        assert data["args"]["refill_count"] == 1


def test_decide_approval_reject_success(approvals_test_env):
    """Rejecting a pending request updates status to 'rejected'."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]
    approval_id = f"app-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    async def _insert():
        async with session_factory() as session:
            appr = Approval(
                id=approval_id,
                profile_id=profile_id,
                run_id="run-1",
                tool_name="delete_entry",
                args_redacted="{}",
                payload_hash=compute_payload_hash({}),
                risk_tier="irreversible",
                status="pending",
                expires_at=now + timedelta(minutes=15),
                created_at=now,
            )
            session.add(appr)
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        resp = client.post(
            f"/api/approvals/{approval_id}/decide",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
            json={"decision": "rejected"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"


def test_decide_approval_already_decided_fails(approvals_test_env):
    """Attempting to decide an approval that is already decided returns 400 Bad Request."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]
    approval_id = f"app-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    async def _insert():
        async with session_factory() as session:
            appr = Approval(
                id=approval_id,
                profile_id=profile_id,
                run_id="run-1",
                tool_name="test_tool",
                args_redacted="{}",
                payload_hash=compute_payload_hash({}),
                risk_tier="write_local",
                status="approved",  # Already approved
                expires_at=now + timedelta(minutes=15),
                created_at=now,
                decided_at=now,
                decided_by=env["alice"].id,
            )
            session.add(appr)
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        resp = client.post(
            f"/api/approvals/{approval_id}/decide",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
            json={"decision": "rejected"},
        )
        assert resp.status_code == 400
        assert "already in status 'approved'" in resp.json()["detail"]


def test_decide_approval_expired_fails(approvals_test_env):
    """Attempting to decide an expired approval returns 400 Bad Request."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]
    approval_id = f"app-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    async def _insert():
        async with session_factory() as session:
            appr = Approval(
                id=approval_id,
                profile_id=profile_id,
                run_id="run-1",
                tool_name="test_tool",
                args_redacted="{}",
                payload_hash=compute_payload_hash({}),
                risk_tier="write_local",
                status="pending",
                expires_at=now - timedelta(minutes=5),  # Expired 5 mins ago
                created_at=now - timedelta(minutes=20),
            )
            session.add(appr)
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        resp = client.post(
            f"/api/approvals/{approval_id}/decide",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
            json={"decision": "approved"},
        )
        assert resp.status_code == 400
        assert "has expired" in resp.json()["detail"]


def test_decide_approval_admin_without_manage_denied(approvals_test_env):
    """Admin user cannot decide approval on profile without explicit manage grant."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]
    approval_id = f"app-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    async def _insert():
        async with session_factory() as session:
            appr = Approval(
                id=approval_id,
                profile_id=profile_id,
                run_id="run-1",
                tool_name="test_tool",
                args_redacted="{}",
                payload_hash=compute_payload_hash({}),
                risk_tier="write_local",
                status="pending",
                expires_at=now + timedelta(minutes=15),
                created_at=now,
            )
            session.add(appr)
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        resp = client.post(
            f"/api/approvals/{approval_id}/decide",
            headers={"Authorization": f"Bearer {env['admin_token']}"},
            json={"decision": "approved"},
        )
        assert resp.status_code == 403


# ============================================================================
# Section 3: Atomic Resumption Engine Tests (AU-18, ADR-0004)
# ============================================================================


def test_atomic_resumption_query_success(approvals_test_env):
    """consume_approval_atomic atomically executes UPDATE ... RETURNING id."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]
    approval_id = f"app-atomic-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    args = {"action": "dispatch", "target": "server-1"}

    async def _run():
        async with session_factory() as session:
            appr = Approval(
                id=approval_id,
                profile_id=profile_id,
                run_id="run-1",
                tool_name="dispatch_network",
                args_redacted=json.dumps(args),
                payload_hash=compute_payload_hash(args),
                risk_tier="write_external",
                status="approved",
                expires_at=now + timedelta(minutes=15),
                created_at=now,
                decided_at=now,
                decided_by=env["alice"].id,
            )
            session.add(appr)
            await session.commit()

        async with session_factory() as session:
            consumed_id = await consume_approval_atomic(session, approval_id, args)
            assert consumed_id == approval_id

            # Verify DB status is 'consumed'
            stmt = select(Approval).where(Approval.id == approval_id)
            res = await session.execute(stmt)
            record = res.scalar_one()
            assert record.status == "consumed"

    run_async(_run())


def test_atomic_resumption_query_replay_fails_closed(approvals_test_env):
    """Calling consume_approval_atomic twice (replay attack) fails closed on second attempt."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]
    approval_id = f"app-replay-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    args = {"key": "value"}

    async def _run():
        async with session_factory() as session:
            appr = Approval(
                id=approval_id,
                profile_id=profile_id,
                run_id="run-1",
                tool_name="test_tool",
                args_redacted=json.dumps(args),
                payload_hash=compute_payload_hash(args),
                risk_tier="write_local",
                status="approved",
                expires_at=now + timedelta(minutes=15),
                created_at=now,
                decided_at=now,
                decided_by=env["alice"].id,
            )
            session.add(appr)
            await session.commit()

        # First consumption succeeds
        async with session_factory() as session:
            res1 = await consume_approval_atomic(session, approval_id, args)
            assert res1 == approval_id

        # Second consumption fails closed
        async with session_factory() as session:
            with pytest.raises(ValueError, match="cannot consume|already been consumed"):
                await consume_approval_atomic(session, approval_id, args)

    run_async(_run())


def test_atomic_resumption_query_tampered_args_fails_closed(approvals_test_env):
    """Tampering with arguments during resume triggers hash mismatch and fails closed."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]
    approval_id = f"app-tamper-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    original_args = {"amount": 50}
    tampered_args = {"amount": 500}

    async def _run():
        async with session_factory() as session:
            appr = Approval(
                id=approval_id,
                profile_id=profile_id,
                run_id="run-1",
                tool_name="charge_card",
                args_redacted=json.dumps(original_args),
                payload_hash=compute_payload_hash(original_args),
                risk_tier="irreversible",
                status="approved",
                expires_at=now + timedelta(minutes=15),
                created_at=now,
                decided_at=now,
                decided_by=env["alice"].id,
            )
            session.add(appr)
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(ValueError, match="Payload hash mismatch"):
                await consume_approval_atomic(session, approval_id, tampered_args)

    run_async(_run())


def test_profile_nested_route_alias_access(approvals_test_env):
    """Verifies that /api/profiles/{profile_id}/approvals alias works identically."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]
    approval_id = f"app-alias-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)

    async def _insert():
        async with session_factory() as session:
            appr = Approval(
                id=approval_id,
                profile_id=profile_id,
                run_id="run-1",
                tool_name="alias_tool",
                args_redacted="{}",
                payload_hash=compute_payload_hash({}),
                risk_tier="read",
                status="pending",
                expires_at=now + timedelta(minutes=15),
                created_at=now,
            )
            session.add(appr)
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        resp = client.get(
            f"/api/profiles/{profile_id}/approvals",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
        )
        assert resp.status_code == 200
        items = resp.json()
        assert any(it["id"] == approval_id for it in items)


def test_get_single_approval_by_id(approvals_test_env):
    """GET /api/approvals/{id} retrieves approval by ID for authorized manager."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]
    approval_id = f"app-single-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)

    async def _insert():
        async with session_factory() as session:
            appr = Approval(
                id=approval_id,
                profile_id=profile_id,
                run_id="run-1",
                tool_name="get_records",
                args_redacted="{}",
                payload_hash=compute_payload_hash({}),
                risk_tier="read",
                status="pending",
                expires_at=now + timedelta(minutes=15),
                created_at=now,
            )
            session.add(appr)
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        # Success for owner
        resp = client.get(
            f"/api/approvals/{approval_id}",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == approval_id

        # 403 for viewer
        resp_viewer = client.get(
            f"/api/approvals/{approval_id}",
            headers={"Authorization": f"Bearer {env['charlie_token']}"},
        )
        assert resp_viewer.status_code == 403

        # 404 for nonexistent
        resp_404 = client.get(
            "/api/approvals/nonexistent-id",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
        )
        assert resp_404.status_code == 404


def test_list_approvals_status_filter_options(approvals_test_env):
    """Verifies filtering approvals by status ('all', 'approved', 'rejected')."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]
    now = datetime.now(timezone.utc)

    async def _insert():
        async with session_factory() as session:
            # 1 approved
            session.add(
                Approval(
                    id=f"app-st-appr-{uuid.uuid4().hex[:6]}",
                    profile_id=profile_id,
                    run_id="run-1",
                    tool_name="tool_1",
                    args_redacted="{}",
                    payload_hash=compute_payload_hash({}),
                    risk_tier="write_local",
                    status="approved",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                )
            )
            # 1 rejected
            session.add(
                Approval(
                    id=f"app-st-rej-{uuid.uuid4().hex[:6]}",
                    profile_id=profile_id,
                    run_id="run-1",
                    tool_name="tool_2",
                    args_redacted="{}",
                    payload_hash=compute_payload_hash({}),
                    risk_tier="write_local",
                    status="rejected",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                )
            )
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        # status=approved
        resp_appr = client.get(
            f"/api/approvals?profile_id={profile_id}&status=approved",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
        )
        assert resp_appr.status_code == 200
        assert all(it["status"] == "approved" for it in resp_appr.json())

        # status=all
        resp_all = client.get(
            f"/api/approvals?profile_id={profile_id}&status=all",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
        )
        assert resp_all.status_code == 200
        statuses = {it["status"] for it in resp_all.json()}
        assert "approved" in statuses
        assert "rejected" in statuses


def test_decide_approval_csrf_protection_cross_site_blocked(approvals_test_env):
    """Verifies that ambient cookie requests from cross-site origins are blocked by CSRF protection."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]
    approval_id = f"app-csrf-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)

    async def _insert():
        async with session_factory() as session:
            appr = Approval(
                id=approval_id,
                profile_id=profile_id,
                run_id="run-1",
                tool_name="test_tool",
                args_redacted="{}",
                payload_hash=compute_payload_hash({}),
                risk_tier="write_local",
                status="pending",
                expires_at=now + timedelta(minutes=15),
                created_at=now,
            )
            session.add(appr)
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        # Client sends ambient cookie without Authorization header, and Sec-Fetch-Site is cross-site
        client.cookies.set("carefold_session", env["alice_token"])
        resp = client.post(
            f"/api/approvals/{approval_id}/decide",
            headers={"Sec-Fetch-Site": "cross-site"},
            json={"decision": "approved"},
        )
        assert resp.status_code == 403
        assert "CSRF protection" in resp.json()["detail"]


def test_atomic_resumption_query_unapproved_or_expired_fails_closed(approvals_test_env):
    """Verifies that consume_approval_atomic fails closed for pending, rejected, or expired approvals."""
    env = approvals_test_env
    session_factory = env["session_factory"]
    profile_id = env["profile_id"]
    now = datetime.now(timezone.utc)
    app_pending_id = f"app-pen-{uuid.uuid4().hex[:6]}"
    app_expired_id = f"app-exp-{uuid.uuid4().hex[:6]}"
    args = {"test": 1}

    async def _run():
        async with session_factory() as session:
            # Pending approval
            session.add(
                Approval(
                    id=app_pending_id,
                    profile_id=profile_id,
                    run_id="run-1",
                    tool_name="tool_pending",
                    args_redacted=json.dumps(args),
                    payload_hash=compute_payload_hash(args),
                    risk_tier="write_local",
                    status="pending",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                )
            )
            # Expired approved approval
            session.add(
                Approval(
                    id=app_expired_id,
                    profile_id=profile_id,
                    run_id="run-1",
                    tool_name="tool_expired",
                    args_redacted=json.dumps(args),
                    payload_hash=compute_payload_hash(args),
                    risk_tier="write_local",
                    status="approved",
                    expires_at=now - timedelta(minutes=5),
                    created_at=now - timedelta(minutes=20),
                )
            )
            await session.commit()

        # Consuming pending must fail closed
        async with session_factory() as session:
            with pytest.raises(ValueError, match="cannot consume"):
                await consume_approval_atomic(session, app_pending_id, args)

        # Consuming expired must fail closed
        async with session_factory() as session:
            with pytest.raises(ValueError, match="has expired"):
                await consume_approval_atomic(session, app_expired_id, args)

    run_async(_run())
