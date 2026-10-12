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

"""Adversarial Empirical Challenge Suite: Resumption Token Security & TOCTOU Protection (AU-18, ADR-0004).

Stress-tests:
1. Replay Attacks: Single-use resumption token enforcement and high-concurrency race conditions.
2. Expired Token Attacks: Time-of-use and time-of-check TTL expiration boundaries.
3. Tampering Attacks (TOCTOU): Cryptographic RFC-8785 canonical JSON payload hash verification.
4. Multi-Tenant Boundary Attacks: Profile scoping, viewer privilege denial, and strict prohibition of admin bypasses.
5. State Machine & Integrity: Invalid transitions, rejected consume attempts, and SQL injection defense.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import uuid
from typing import Any, Dict

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
def adversarial_env(monkeypatch):
    """Provisions an isolated multi-tenant database environment with owners, managers, viewers, admins, and attackers."""

    async def _setup():
        engine = create_db_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = get_session_factory(engine)
        auth_adapter = SqlAuthAdapter(session_factory=session_factory)

        monkeypatch.setattr(settings, "auth_provider", "local")
        set_auth_port(auth_adapter)

        # Tenant 1: Alice (Profile Owner)
        alice = await auth_adapter.register_user(
            email="alice_adv@test.local",
            username="alice_adv",
            password="AliceAdvPassword123!",
            full_name="Alice Adv",
            role="member",
            auth_provider="local",
        )
        alice_session = await auth_adapter.create_session(alice.id)

        # Delegate: Bob (Granted explicit 'manage' access on Alice's profile)
        bob = await auth_adapter.register_user(
            email="bob_adv@test.local",
            username="bob_adv",
            password="BobAdvPassword123!",
            full_name="Bob Adv Manager",
            role="member",
            auth_provider="local",
        )
        bob_session = await auth_adapter.create_session(bob.id)

        # Viewer: Charlie (Granted only 'view_clinical' access on Alice's profile, NOT 'manage')
        charlie = await auth_adapter.register_user(
            email="charlie_adv@test.local",
            username="charlie_adv",
            password="CharlieAdvPassword123!",
            full_name="Charlie Adv Viewer",
            role="member",
            auth_provider="local",
        )
        charlie_session = await auth_adapter.create_session(charlie.id)

        # Tenant 2: Dave (Separate Profile Owner)
        dave = await auth_adapter.register_user(
            email="dave_adv@test.local",
            username="dave_adv",
            password="DaveAdvPassword123!",
            full_name="Dave Adv Owner",
            role="member",
            auth_provider="local",
        )
        dave_session = await auth_adapter.create_session(dave.id)

        # Attacker: Eve (Unrelated external authenticated user with no grants)
        eve = await auth_adapter.register_user(
            email="eve_adv@test.local",
            username="eve_adv",
            password="EveAdvPassword123!",
            full_name="Eve Adv Attacker",
            role="member",
            auth_provider="local",
        )
        eve_session = await auth_adapter.create_session(eve.id)

        # Admin: Superuser with role='admin' but NO explicit profile grants (AU-18 bypass check)
        admin = await auth_adapter.register_user(
            email="admin_adv@test.local",
            username="admin_adv",
            password="AdminAdvPassword123!",
            full_name="System Admin Adv",
            role="admin",
            auth_provider="local",
        )
        await auth_adapter.update_user(admin.id, UserUpdate(role="admin"))
        admin_session = await auth_adapter.create_session(admin.id)

        async with session_factory() as session:
            # Create Alice's primary profile
            alice_profile = Profile(
                id=f"prof-alice-{uuid.uuid4().hex[:6]}",
                user_id=alice.id,
                name="Alice Profile",
                relationship="self",
                role="self",
                is_primary=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(alice_profile)

            # Create Dave's primary profile
            dave_profile = Profile(
                id=f"prof-dave-{uuid.uuid4().hex[:6]}",
                user_id=dave.id,
                name="Dave Profile",
                relationship="self",
                role="self",
                is_primary=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(dave_profile)

            # Bob grant: 'manage' on Alice's profile
            session.add(
                ProfileAccess(
                    id=str(uuid.uuid4()),
                    profile_id=alice_profile.id,
                    user_id=bob.id,
                    access_level="manage",
                    granted_by=alice.id,
                    granted_at=datetime.now(timezone.utc),
                )
            )

            # Charlie grant: 'view_clinical' on Alice's profile
            session.add(
                ProfileAccess(
                    id=str(uuid.uuid4()),
                    profile_id=alice_profile.id,
                    user_id=charlie.id,
                    access_level="view_clinical",
                    granted_by=alice.id,
                    granted_at=datetime.now(timezone.utc),
                )
            )

            await session.commit()

            profile_alice_id = alice_profile.id
            profile_dave_id = dave_profile.id

        return {
            "session_factory": session_factory,
            "engine": engine,
            "profile_alice_id": profile_alice_id,
            "profile_dave_id": profile_dave_id,
            "alice": alice,
            "alice_token": alice_session.token,
            "bob": bob,
            "bob_token": bob_session.token,
            "charlie": charlie,
            "charlie_token": charlie_session.token,
            "dave": dave,
            "dave_token": dave_session.token,
            "eve": eve,
            "eve_token": eve_session.token,
            "admin": admin,
            "admin_token": admin_session.token,
        }

    env_data = run_async(_setup())
    session_factory = env_data["session_factory"]

    # Ensure approvals router is registered on app
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
# Section 1: Replay Attacks & Concurrency Race Stress
# ============================================================================


def test_adversarial_replay_sequential_reconsume_fails_closed(adversarial_env):
    """Adversarial Challenge 1.1: Replay Attack (Sequential Re-consumption).

    Attempting to consume an already-consumed token (status == 'consumed') must fail closed immediately.
    Subsequent attempts with identical or tampered arguments must be rejected without state mutation.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-replay-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    valid_args = {"action": "sync_ehr_records", "patient_id": "P-901", "sync_window_days": 30}

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-replay-1",
                    tool_name="sync_ehr_records",
                    args_redacted=json.dumps(valid_args),
                    payload_hash=compute_payload_hash(valid_args),
                    risk_tier="write_external",
                    status="approved",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                    decided_at=now,
                    decided_by=env["alice"].id,
                )
            )
            await session.commit()

    run_async(_insert())

    async def _probe():
        # First legitimate consumption: succeeds
        async with session_factory() as session:
            consumed = await consume_approval_atomic(session, approval_id, valid_args)
            assert consumed == approval_id

        # Verify DB status transitioned to 'consumed'
        async with session_factory() as session:
            rec = (await session.execute(select(Approval).where(Approval.id == approval_id))).scalar_one()
            assert rec.status == "consumed"

        # Second replay consumption: must fail closed with ValueError
        async with session_factory() as session:
            with pytest.raises(ValueError, match="cannot consume|already been consumed"):
                await consume_approval_atomic(session, approval_id, valid_args)

        # Third replay consumption with modified args: must also fail closed
        async with session_factory() as session:
            with pytest.raises(ValueError, match="cannot consume|already been consumed|mismatch"):
                await consume_approval_atomic(session, approval_id, {"different": "payload"})

        # Verify DB status remains strictly 'consumed'
        async with session_factory() as session:
            rec_after = (await session.execute(select(Approval).where(Approval.id == approval_id))).scalar_one()
            assert rec_after.status == "consumed"

    run_async(_probe())


def test_adversarial_replay_concurrency_race_condition(adversarial_env):
    """Adversarial Challenge 1.2: Concurrency Race Condition.

    Stress-test atomic consumption under concurrent execution: 10 concurrent tasks simultaneously
    attempting to consume the EXACT SAME approved token.
    Invariant: EXACTLY ONE task succeeds; EXACTLY N-1 tasks fail closed with ValueError.
    No double execution or partial update is permitted.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-race-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    args = {"action": "book_appointment", "provider_id": "DR-404", "slot": "2026-10-15T10:00:00Z"}

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-race-1",
                    tool_name="book_appointment",
                    args_redacted=json.dumps(args),
                    payload_hash=compute_payload_hash(args),
                    risk_tier="irreversible",
                    status="approved",
                    expires_at=now + timedelta(minutes=20),
                    created_at=now,
                    decided_at=now,
                    decided_by=env["alice"].id,
                )
            )
            await session.commit()

    run_async(_insert())

    async def _concurrent_attack():
        num_racers = 10

        async def _consume_worker(worker_idx: int):
            async with session_factory() as session:
                return await consume_approval_atomic(session, approval_id, args)

        results = await asyncio.gather(
            *[_consume_worker(i) for i in range(num_racers)],
            return_exceptions=True,
        )

        successes = [r for r in results if isinstance(r, str) and r == approval_id]
        failures = [r for r in results if isinstance(r, Exception)]

        # Strict single-use assertion: exactly 1 winner, 9 losers
        assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}: {results}"
        assert len(failures) == num_racers - 1, f"Expected {num_racers - 1} failures, got {len(failures)}"
        for exc in failures:
            assert isinstance(exc, ValueError), f"Unexpected exception type: {type(exc)}: {exc}"
            assert any(
                phrase in str(exc)
                for phrase in ("cannot consume", "already been consumed", "invalid")
            ), f"Unexpected error message: {exc}"

        # Invariant: Record in database is 'consumed'
        async with session_factory() as session:
            rec = (await session.execute(select(Approval).where(Approval.id == approval_id))).scalar_one()
            assert rec.status == "consumed"

    run_async(_concurrent_attack())


def test_adversarial_replay_decide_endpoint_on_consumed_record_fails(adversarial_env):
    """Adversarial Challenge 1.3: Replay via REST decide endpoint on consumed approval.

    Attempting to re-decide an approval that has already transitioned to 'consumed'
    must fail closed with HTTP 400 Bad Request.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-decide-consumed-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    args = {"cmd": "execute"}

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-dec-cons",
                    tool_name="execute_cmd",
                    args_redacted=json.dumps(args),
                    payload_hash=compute_payload_hash(args),
                    risk_tier="irreversible",
                    status="consumed",  # Already consumed
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                    decided_at=now,
                    decided_by=env["alice"].id,
                )
            )
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        resp = client.post(
            f"/api/approvals/{approval_id}/decide",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
            json={"decision": "approved"},
        )
        assert resp.status_code == 400
        assert "already in status 'consumed' and cannot be decided" in resp.json()["detail"]


# ============================================================================
# Section 2: Expired Token Attacks (Time-of-Use & Time-of-Check)
# ============================================================================


def test_adversarial_expired_token_decide_endpoint_fails_closed(adversarial_env):
    """Adversarial Challenge 2.1: Expired Token Attack on POST /decide.

    Attempting to decide a pending approval whose TTL has elapsed (expires_at in past)
    must fail closed with HTTP 400 Bad Request, and automatically persist status='expired'.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-exp-decide-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    past_expiration = now - timedelta(seconds=15)
    args = {"action": "delete_account"}

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-exp-decide",
                    tool_name="delete_account",
                    args_redacted=json.dumps(args),
                    payload_hash=compute_payload_hash(args),
                    risk_tier="irreversible",
                    status="pending",
                    expires_at=past_expiration,
                    created_at=now - timedelta(minutes=30),
                )
            )
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        # First decision attempt: fails closed with 400
        resp = client.post(
            f"/api/approvals/{approval_id}/decide",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
            json={"decision": "approved"},
        )
        assert resp.status_code == 400
        assert "has expired and cannot be decided" in resp.json()["detail"]

        # Verify DB status transitioned to 'expired'
        async def _check_status():
            async with session_factory() as session:
                rec = (await session.execute(select(Approval).where(Approval.id == approval_id))).scalar_one()
                assert rec.status == "expired"

        run_async(_check_status())

        # Second attempt to decide expired record: also fails closed with 400
        resp2 = client.post(
            f"/api/approvals/{approval_id}/decide",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
            json={"decision": "rejected"},
        )
        assert resp2.status_code == 400
        assert "already in status 'expired'" in resp2.json()["detail"]


def test_adversarial_expired_token_consume_atomic_fails_closed(adversarial_env):
    """Adversarial Challenge 2.2: Expired Token Attack on consume_approval_atomic.

    An approval was marked 'approved' in time, but user delayed resumption until after expires_at.
    Attempting to consume the expired approved token must fail closed immediately with ValueError.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-exp-consume-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    past_expiration = now - timedelta(seconds=5)
    args = {"action": "export_clinical_notes"}

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-exp-consume",
                    tool_name="export_notes",
                    args_redacted=json.dumps(args),
                    payload_hash=compute_payload_hash(args),
                    risk_tier="write_external",
                    status="approved",
                    expires_at=past_expiration,
                    created_at=now - timedelta(minutes=20),
                    decided_at=now - timedelta(minutes=10),
                    decided_by=env["alice"].id,
                )
            )
            await session.commit()

    run_async(_insert())

    async def _probe():
        async with session_factory() as session:
            with pytest.raises(ValueError, match="has expired"):
                await consume_approval_atomic(session, approval_id, args)

        # Invariant: Record in database transitioned to 'expired'
        async with session_factory() as session:
            rec = (await session.execute(select(Approval).where(Approval.id == approval_id))).scalar_one()
            assert rec.status == "expired"

        # Subsequent consume attempt fails closed with 'cannot consume'
        async with session_factory() as session:
            with pytest.raises(ValueError, match="cannot consume"):
                await consume_approval_atomic(session, approval_id, args)

    run_async(_probe())


def test_adversarial_expired_token_boundary_precision(adversarial_env):
    """Adversarial Challenge 2.3: Millisecond Expiration Boundary Precision.

    Tests TTL boundaries:
    - Token with expires_at in the immediate past (10ms ago) must fail closed.
    - Token with expires_at in the immediate future (+5s) must consume successfully.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    now = datetime.now(timezone.utc)
    args = {"param": "boundary_test"}

    id_expired = f"app-exp-ms-{uuid.uuid4().hex[:6]}"
    id_valid = f"app-valid-ms-{uuid.uuid4().hex[:6]}"

    async def _insert():
        async with session_factory() as session:
            # 10 milliseconds in past
            session.add(
                Approval(
                    id=id_expired,
                    profile_id=profile_id,
                    run_id="run-b1",
                    tool_name="b_tool",
                    args_redacted=json.dumps(args),
                    payload_hash=compute_payload_hash(args),
                    risk_tier="write_local",
                    status="approved",
                    expires_at=now - timedelta(milliseconds=10),
                    created_at=now - timedelta(seconds=10),
                    decided_at=now,
                    decided_by=env["alice"].id,
                )
            )
            # 5 seconds in future
            session.add(
                Approval(
                    id=id_valid,
                    profile_id=profile_id,
                    run_id="run-b2",
                    tool_name="b_tool",
                    args_redacted=json.dumps(args),
                    payload_hash=compute_payload_hash(args),
                    risk_tier="write_local",
                    status="approved",
                    expires_at=now + timedelta(seconds=5),
                    created_at=now,
                    decided_at=now,
                    decided_by=env["alice"].id,
                )
            )
            await session.commit()

    run_async(_insert())

    async def _verify():
        # Immediate past: fails closed
        async with session_factory() as session:
            with pytest.raises(ValueError, match="has expired"):
                await consume_approval_atomic(session, id_expired, args)

        # Immediate future: succeeds
        async with session_factory() as session:
            consumed = await consume_approval_atomic(session, id_valid, args)
            assert consumed == id_valid

    run_async(_verify())


def test_adversarial_expired_token_filtered_from_pending_list(adversarial_env):
    """Adversarial Challenge 2.4: Pending List Excludes Expired Approvals.

    GET /api/approvals?profile_id={id}&status=pending must filter out expired pending requests,
    preventing stale requests from polluting the steward review dashboard.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    now = datetime.now(timezone.utc)
    id_active = f"app-act-{uuid.uuid4().hex[:6]}"
    id_expired = f"app-exp-list-{uuid.uuid4().hex[:6]}"

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=id_active,
                    profile_id=profile_id,
                    run_id="run-list-act",
                    tool_name="tool_active",
                    args_redacted="{}",
                    payload_hash=compute_payload_hash({}),
                    risk_tier="read",
                    status="pending",
                    expires_at=now + timedelta(minutes=10),
                    created_at=now,
                )
            )
            session.add(
                Approval(
                    id=id_expired,
                    profile_id=profile_id,
                    run_id="run-list-exp",
                    tool_name="tool_expired",
                    args_redacted="{}",
                    payload_hash=compute_payload_hash({}),
                    risk_tier="read",
                    status="pending",
                    expires_at=now - timedelta(minutes=5),  # Expired
                    created_at=now - timedelta(minutes=20),
                )
            )
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        resp = client.get(
            f"/api/approvals?profile_id={profile_id}&status=pending",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
        )
        assert resp.status_code == 200
        items = resp.json()
        ids = [it["id"] for it in items]
        assert id_active in ids
        assert id_expired not in ids, "Expired pending approval was not filtered out from pending list"


# ============================================================================
# Section 3: Tampering Attacks & TOCTOU Cryptographic Hash Mismatch
# ============================================================================


def test_adversarial_tampering_add_malicious_parameter_fails_hash(adversarial_env):
    """Adversarial Challenge 3.1: TOCTOU Parameter Injection Attack.

    Attacker approves legitimate query arguments, but at resumption injects an administrative override parameter.
    Must fail closed with 'Payload hash mismatch' without executing or consuming the token.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-tamper-add-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    approved_args = {"operation": "view_records", "patient_id": "P-101"}
    injected_args = {"operation": "view_records", "patient_id": "P-101", "admin_override": True}

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-tamper-add",
                    tool_name="view_records",
                    args_redacted=json.dumps(approved_args),
                    payload_hash=compute_payload_hash(approved_args),
                    risk_tier="write_local",
                    status="approved",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                    decided_at=now,
                    decided_by=env["alice"].id,
                )
            )
            await session.commit()

    run_async(_insert())

    async def _probe():
        async with session_factory() as session:
            with pytest.raises(ValueError, match="Payload hash mismatch"):
                await consume_approval_atomic(session, approval_id, injected_args)

        # Invariant: Record in database remains 'approved' (token not burnt, not executed)
        async with session_factory() as session:
            rec = (await session.execute(select(Approval).where(Approval.id == approval_id))).scalar_one()
            assert rec.status == "approved"

        # Legitimate args can still be resumed safely
        async with session_factory() as session:
            consumed = await consume_approval_atomic(session, approval_id, approved_args)
            assert consumed == approval_id

    run_async(_probe())


def test_adversarial_tampering_mutate_field_value_fails_hash(adversarial_env):
    """Adversarial Challenge 3.2: Value Mutation Attack (Financial / Clinical Tampering).

    Approved amount: 50. Resumption tampered amount: 500.
    Must fail closed with cryptographic hash mismatch error.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-tamper-val-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    original_args = {"charge_amount_cents": 5000, "currency": "USD", "memo": "copay"}
    tampered_args = {"charge_amount_cents": 50000, "currency": "USD", "memo": "copay"}

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-tamper-val",
                    tool_name="process_copay",
                    args_redacted=json.dumps(original_args),
                    payload_hash=compute_payload_hash(original_args),
                    risk_tier="irreversible",
                    status="approved",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                    decided_at=now,
                    decided_by=env["alice"].id,
                )
            )
            await session.commit()

    run_async(_insert())

    async def _probe():
        async with session_factory() as session:
            with pytest.raises(ValueError, match="Payload hash mismatch"):
                await consume_approval_atomic(session, approval_id, tampered_args)

    run_async(_probe())


def test_adversarial_tampering_delete_field_fails_hash(adversarial_env):
    """Adversarial Challenge 3.3: Field Stripping Attack.

    Attacker strips a safety constraint (e.g. 'sandbox': True).
    Must fail closed with hash mismatch.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-tamper-del-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    original_args = {"target_host": "api.test.org", "sandbox": True}
    stripped_args = {"target_host": "api.test.org"}

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-tamper-del",
                    tool_name="api_dispatch",
                    args_redacted=json.dumps(original_args),
                    payload_hash=compute_payload_hash(original_args),
                    risk_tier="write_external",
                    status="approved",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                    decided_at=now,
                    decided_by=env["alice"].id,
                )
            )
            await session.commit()

    run_async(_insert())

    async def _probe():
        async with session_factory() as session:
            with pytest.raises(ValueError, match="Payload hash mismatch"):
                await consume_approval_atomic(session, approval_id, stripped_args)

    run_async(_probe())


def test_adversarial_tampering_type_confusion_fails_hash(adversarial_env):
    """Adversarial Challenge 3.4: Type Confusion Attack.

    Approved: integer 100. Resumed: string "100".
    RFC-8785 canonical JSON represents these differently, resulting in different SHA-256 digests.
    Must fail closed.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-tamper-type-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    int_args = {"refill_id": 100}
    str_args = {"refill_id": "100"}

    assert compute_payload_hash(int_args) != compute_payload_hash(str_args)

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-tamper-type",
                    tool_name="refill_order",
                    args_redacted=json.dumps(int_args),
                    payload_hash=compute_payload_hash(int_args),
                    risk_tier="write_external",
                    status="approved",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                    decided_at=now,
                    decided_by=env["alice"].id,
                )
            )
            await session.commit()

    run_async(_insert())

    async def _probe():
        async with session_factory() as session:
            with pytest.raises(ValueError, match="Payload hash mismatch"):
                await consume_approval_atomic(session, approval_id, str_args)

    run_async(_probe())


def test_adversarial_tampering_nested_mutation_fails_hash(adversarial_env):
    """Adversarial Challenge 3.5: Nested Object Tampering.

    Tampering with a deeply nested dictionary property must trigger cryptographic hash mismatch.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-tamper-nest-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    orig_nest = {"profile": {"tier": "free", "flags": {"can_export": False}}}
    tamp_nest = {"profile": {"tier": "free", "flags": {"can_export": True}}}

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-tamper-nest",
                    tool_name="update_flags",
                    args_redacted=json.dumps(orig_nest),
                    payload_hash=compute_payload_hash(orig_nest),
                    risk_tier="write_local",
                    status="approved",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                    decided_at=now,
                    decided_by=env["alice"].id,
                )
            )
            await session.commit()

    run_async(_insert())

    async def _probe():
        async with session_factory() as session:
            with pytest.raises(ValueError, match="Payload hash mismatch"):
                await consume_approval_atomic(session, approval_id, tamp_nest)

    run_async(_probe())


def test_adversarial_canonical_json_key_order_is_invariant(adversarial_env):
    """Adversarial Challenge 3.6: RFC-8785 Canonical JSON Sorting Invariance.

    Verifies that dictionary key insertion order does NOT cause false rejections.
    Arguments with rearranged keys must produce identical hashes and consume successfully.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-key-order-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)

    # Different key ordering
    dict_order_1 = {"z_field": 1, "a_field": 2, "m_field": {"beta": 1, "alpha": 2}}
    dict_order_2 = {"a_field": 2, "m_field": {"alpha": 2, "beta": 1}, "z_field": 1}

    hash_1 = compute_payload_hash(dict_order_1)
    hash_2 = compute_payload_hash(dict_order_2)
    assert hash_1 == hash_2, "RFC-8785 canonical JSON sorting failed to produce identical hashes"

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-key-order",
                    tool_name="order_independent",
                    args_redacted=json.dumps(dict_order_1),
                    payload_hash=hash_1,
                    risk_tier="write_local",
                    status="approved",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                    decided_at=now,
                    decided_by=env["alice"].id,
                )
            )
            await session.commit()

    run_async(_insert())

    async def _probe():
        async with session_factory() as session:
            # Consuming with reversed key order dictionary must succeed without error
            consumed = await consume_approval_atomic(session, approval_id, dict_order_2)
            assert consumed == approval_id

    run_async(_probe())


def test_adversarial_tampering_edited_args_enforces_new_hash_rejects_original(adversarial_env):
    """Adversarial Challenge 3.7: Edited Arguments Lifecycle Enforcement.

    When a steward modifies arguments via POST /decide:
    1. The stored payload_hash is updated to the hash of edited_args.
    2. Resuming with the original (pre-edited) args fails closed with hash mismatch.
    3. Resuming with the approved edited_args succeeds cleanly.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-edit-hash-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    orig_args = {"dose_mg": 100, "notes": "original instruction"}
    edited_args = {"dose_mg": 25, "notes": "steward dosage reduction"}

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-edit-hash",
                    tool_name="prescribe_medication",
                    args_redacted=json.dumps(orig_args),
                    payload_hash=compute_payload_hash(orig_args),
                    risk_tier="irreversible",
                    status="pending",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                )
            )
            await session.commit()

    run_async(_insert())

    # Steward approves with edited_args
    with TestClient(app) as client:
        resp = client.post(
            f"/api/approvals/{approval_id}/decide",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
            json={"decision": "approved", "edited_args": edited_args},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["payload_hash"] == compute_payload_hash(edited_args)

    async def _probe():
        # Attempting to resume with ORIGINAL args must fail closed
        async with session_factory() as session:
            with pytest.raises(ValueError, match="Payload hash mismatch"):
                await consume_approval_atomic(session, approval_id, orig_args)

        # Resuming with EDITED args must succeed cleanly
        async with session_factory() as session:
            consumed = await consume_approval_atomic(session, approval_id, edited_args)
            assert consumed == approval_id

    run_async(_probe())


# ============================================================================
# Section 4: Multi-Tenant Boundary Attacks & Strict Admin Bypass Denial (AU-18)
# ============================================================================


def test_adversarial_multitenant_admin_bypass_strictly_denied_au18(adversarial_env):
    """Adversarial Challenge 4.1: Multi-Tenant Admin Bypass Prohibition (AU-18 Invariant).

    A user with role='admin' (system administrator) but without explicit account ownership
    or an explicit 'manage' access grant on the profile MUST be rejected with HTTP 403 Forbidden.
    Verifies list, get, and decide endpoints.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-admin-block-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    args = {"cmd": "clinical_operation"}

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-adm-block",
                    tool_name="clinical_operation",
                    args_redacted=json.dumps(args),
                    payload_hash=compute_payload_hash(args),
                    risk_tier="write_external",
                    status="pending",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                )
            )
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        # 1. Admin GET /api/approvals?profile_id={alice} -> 403 Forbidden
        r_list = client.get(
            f"/api/approvals?profile_id={profile_id}",
            headers={"Authorization": f"Bearer {env['admin_token']}"},
        )
        assert r_list.status_code == 403
        assert "management privileges required" in r_list.json()["detail"]

        # 2. Admin GET /api/approvals/{approval_id} -> 403 Forbidden
        r_get = client.get(
            f"/api/approvals/{approval_id}",
            headers={"Authorization": f"Bearer {env['admin_token']}"},
        )
        assert r_get.status_code == 403
        assert "management privileges required" in r_get.json()["detail"]

        # 3. Admin POST /api/approvals/{approval_id}/decide -> 403 Forbidden
        r_decide = client.post(
            f"/api/approvals/{approval_id}/decide",
            headers={"Authorization": f"Bearer {env['admin_token']}"},
            json={"decision": "approved"},
        )
        assert r_decide.status_code == 403
        assert "management privileges required" in r_decide.json()["detail"]


def test_adversarial_multitenant_unauthorized_external_tenant_denied(adversarial_env):
    """Adversarial Challenge 4.2: External Tenant Isolation (Eve Attacker).

    An unrelated authenticated user from another tenant/account (Eve) attempting to
    query or decide Alice's approval requests must receive HTTP 403 Forbidden.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-eve-block-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-eve",
                    tool_name="test_tool",
                    args_redacted="{}",
                    payload_hash=compute_payload_hash({}),
                    risk_tier="read",
                    status="pending",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                )
            )
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        # Eve list -> 403
        assert client.get(
            f"/api/approvals?profile_id={profile_id}",
            headers={"Authorization": f"Bearer {env['eve_token']}"},
        ).status_code == 403

        # Eve get -> 403
        assert client.get(
            f"/api/approvals/{approval_id}",
            headers={"Authorization": f"Bearer {env['eve_token']}"},
        ).status_code == 403

        # Eve decide -> 403
        assert client.post(
            f"/api/approvals/{approval_id}/decide",
            headers={"Authorization": f"Bearer {env['eve_token']}"},
            json={"decision": "approved"},
        ).status_code == 403


def test_adversarial_multitenant_viewer_role_insufficient_privilege(adversarial_env):
    """Adversarial Challenge 4.3: Privilege Escalation Prevention (Viewer != Manager).

    Charlie has an explicit grant on Alice's profile, but only with access_level='view_clinical'.
    Charlie must NOT be permitted to list, view, or decide approval requests (requires 'manage').
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-charlie-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-charlie",
                    tool_name="sync_notes",
                    args_redacted="{}",
                    payload_hash=compute_payload_hash({}),
                    risk_tier="write_local",
                    status="pending",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                )
            )
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        # Viewer list -> 403
        assert client.get(
            f"/api/approvals?profile_id={profile_id}",
            headers={"Authorization": f"Bearer {env['charlie_token']}"},
        ).status_code == 403

        # Viewer get -> 403
        assert client.get(
            f"/api/approvals/{approval_id}",
            headers={"Authorization": f"Bearer {env['charlie_token']}"},
        ).status_code == 403

        # Viewer decide -> 403
        assert client.post(
            f"/api/approvals/{approval_id}/decide",
            headers={"Authorization": f"Bearer {env['charlie_token']}"},
            json={"decision": "approved"},
        ).status_code == 403


def test_adversarial_multitenant_cross_profile_spoofing_denied(adversarial_env):
    """Adversarial Challenge 4.4: Cross-Profile Approval ID Spoofing.

    Bob has 'manage' access on Alice's Profile A, but NO access on Dave's Profile B.
    Dave has an approval record on Profile B.
    Bob attempting to fetch or decide Dave's approval by ID must receive HTTP 403 Forbidden.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    dave_profile_id = env["profile_dave_id"]
    dave_approval_id = f"app-adv-dave-item-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=dave_approval_id,
                    profile_id=dave_profile_id,
                    run_id="run-dave-1",
                    tool_name="dave_private_tool",
                    args_redacted="{}",
                    payload_hash=compute_payload_hash({}),
                    risk_tier="irreversible",
                    status="pending",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                )
            )
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        # Bob tries to read Dave's approval -> 403
        assert client.get(
            f"/api/approvals/{dave_approval_id}",
            headers={"Authorization": f"Bearer {env['bob_token']}"},
        ).status_code == 403

        # Bob tries to decide Dave's approval -> 403
        assert client.post(
            f"/api/approvals/{dave_approval_id}/decide",
            headers={"Authorization": f"Bearer {env['bob_token']}"},
            json={"decision": "approved"},
        ).status_code == 403

        # Dave (legitimate owner) CAN read Dave's approval -> 200
        assert client.get(
            f"/api/approvals/{dave_approval_id}",
            headers={"Authorization": f"Bearer {env['dave_token']}"},
        ).status_code == 200


def test_adversarial_multitenant_unauthenticated_requests_denied(adversarial_env):
    """Adversarial Challenge 4.5: Unauthenticated Request Boundary.

    Requests lacking authentication credentials must receive HTTP 401 Unauthorized.
    """
    env = adversarial_env
    profile_id = env["profile_alice_id"]

    with TestClient(app) as client:
        assert client.get(f"/api/approvals?profile_id={profile_id}").status_code == 401
        assert client.get(f"/api/approvals/some-id").status_code == 401
        assert client.post(f"/api/approvals/some-id/decide", json={"decision": "approved"}).status_code == 401


def test_adversarial_multitenant_csrf_protection_cross_site_blocked(adversarial_env):
    """Adversarial Challenge 4.6: Ambient Browser Session CSRF Protection.

    Requests using ambient cookies with Sec-Fetch-Site: cross-site without Bearer token must be blocked (403).
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    approval_id = f"app-adv-csrf-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=approval_id,
                    profile_id=profile_id,
                    run_id="run-csrf",
                    tool_name="csrf_tool",
                    args_redacted="{}",
                    payload_hash=compute_payload_hash({}),
                    risk_tier="write_local",
                    status="pending",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                )
            )
            await session.commit()

    run_async(_insert())

    with TestClient(app) as client:
        # Cross-site cookie attack
        client.cookies.set("carefold_session", env["alice_token"])
        resp = client.post(
            f"/api/approvals/{approval_id}/decide",
            headers={"Sec-Fetch-Site": "cross-site"},
            json={"decision": "approved"},
        )
        assert resp.status_code == 403
        assert "CSRF protection" in resp.json()["detail"]


def test_adversarial_multitenant_nonexistent_resources_fail_cleanly(adversarial_env):
    """Adversarial Challenge 4.7: Nonexistent Resource Probes.

    Nonexistent profiles return 404; nonexistent approvals return 404; missing profile_id returns 400.
    """
    env = adversarial_env

    with TestClient(app) as client:
        # Missing profile_id parameter
        r_missing = client.get(
            "/api/approvals",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
        )
        assert r_missing.status_code == 400

        # Nonexistent profile
        r_no_prof = client.get(
            "/api/approvals?profile_id=prof-nonexistent-999",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
        )
        assert r_no_prof.status_code == 404

        # Nonexistent approval
        r_no_appr = client.get(
            "/api/approvals/app-nonexistent-999",
            headers={"Authorization": f"Bearer {env['alice_token']}"},
        )
        assert r_no_appr.status_code == 404


# ============================================================================
# Section 5: State Machine Invariants & SQL Injection Defense
# ============================================================================


def test_adversarial_state_machine_invalid_state_consumption_fails_closed(adversarial_env):
    """Adversarial Challenge 5.1: State Machine Invariants on consume_approval_atomic.

    - Consuming a 'pending' approval fails closed (must be approved first).
    - Consuming a 'rejected' approval fails closed.
    - Consuming a nonexistent approval ID fails closed.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    profile_id = env["profile_alice_id"]
    now = datetime.now(timezone.utc)
    id_pend = f"app-adv-st-pend-{uuid.uuid4().hex[:6]}"
    id_rej = f"app-adv-st-rej-{uuid.uuid4().hex[:6]}"
    args = {"dummy": "data"}

    async def _insert():
        async with session_factory() as session:
            session.add(
                Approval(
                    id=id_pend,
                    profile_id=profile_id,
                    run_id="run-pend",
                    tool_name="tool_pending",
                    args_redacted=json.dumps(args),
                    payload_hash=compute_payload_hash(args),
                    risk_tier="write_local",
                    status="pending",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                )
            )
            session.add(
                Approval(
                    id=id_rej,
                    profile_id=profile_id,
                    run_id="run-rej",
                    tool_name="tool_rejected",
                    args_redacted=json.dumps(args),
                    payload_hash=compute_payload_hash(args),
                    risk_tier="write_local",
                    status="rejected",
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                    decided_at=now,
                    decided_by=env["alice"].id,
                )
            )
            await session.commit()

    run_async(_insert())

    async def _probe():
        # Pending consume: fails closed
        async with session_factory() as session:
            with pytest.raises(ValueError, match="cannot consume"):
                await consume_approval_atomic(session, id_pend, args)

        # Rejected consume: fails closed
        async with session_factory() as session:
            with pytest.raises(ValueError, match="cannot consume"):
                await consume_approval_atomic(session, id_rej, args)

        # Nonexistent consume: fails closed
        async with session_factory() as session:
            with pytest.raises(ValueError, match="not found"):
                await consume_approval_atomic(session, "app-ghost-id", args)

    run_async(_probe())


def test_adversarial_sql_injection_defense_in_approval_id(adversarial_env):
    """Adversarial Challenge 5.2: SQL Injection Defense.

    Parameter injection into consume_approval_atomic (e.g. `' OR '1'='1' --`) must fail closed safely.
    Parameterized SQL binds parameters safely, avoiding SQL injection vulnerabilities.
    """
    env = adversarial_env
    session_factory = env["session_factory"]
    sqli_payloads = [
        "' OR '1'='1' --",
        "'; DROP TABLE approvals; --",
        "app-1' UNION SELECT * FROM approvals --",
    ]

    async def _probe():
        for sqli in sqli_payloads:
            async with session_factory() as session:
                with pytest.raises(ValueError, match="not found"):
                    await consume_approval_atomic(session, sqli, {})

        # Verify approvals table is intact and unaffected
        async with session_factory() as session:
            res = await session.execute(select(Approval))
            # Table remains queryable
            assert res is not None

    run_async(_probe())
