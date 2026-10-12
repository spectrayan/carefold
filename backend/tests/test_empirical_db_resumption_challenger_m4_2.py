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

"""Empirical Challenge Suite: Production SQLite Resumption & Adversarial Lifecycle Testing (AU-18, ADR-0004).

Authored by challenger_m4_iter2_1.
Empirically stress-tests the production database resumption path WITHOUT in-memory test doubles:
1. Initial turn creates pending Approval record with expires_at = now + 15m.
2. Human decision via decide_approval sets status to 'approved' with decided_at and decided_by.
3. Resumption turn consumes token atomically via SqlApprovalStore, setting status to 'consumed'.
4. Replay attack: attempting a second resume with the consumed token fails closed with 0 tool executions.
5. TOCTOU attack: modifying tool arguments post-approval triggers payload hash mismatch and aborts execution.
6. Long thread ID (>36 chars) respects the 36-character column limit without SQL truncation error.
7. Concurrency race stress: multiple simultaneous resumption attempts on the same SQLite token.
8. Expired token attack on real SQLite database fails closed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict, List, Optional
import uuid
import pytest
from starlette.requests import Request
from sqlalchemy import select

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command

from carefold.api.approvals import (
    ApprovalDecideRequest,
    consume_approval_atomic,
    decide_approval,
)
from carefold.auth.ports import UserProfile
from carefold.constants.api import SSE_EVENT_APPROVAL_REQUIRED
from carefold.db.models import Approval, Profile, User
from carefold.db.session import get_session_factory, init_db
from carefold.engine.tool_exec import (
    SqlApprovalStore,
    ToolContext,
    ToolSpec,
    compute_payload_hash,
    execute_tool_call,
)
from carefold.workflows.nodes.tool_node import ToolNode


# ============================================================================
# Helpers & Spies
# ============================================================================

async def create_user_and_profile(
    session: Any,
    user_id: str,
    profile_id: str,
    name: str = "Test Profile",
) -> None:
    """Provisions a User and associated primary Profile in SQLite, satisfying FK constraints."""
    user = User(
        id=user_id,
        email=f"{user_id}@test.local",
        username=user_id,
        hashed_password="hashed_pw_placeholder",
    )
    prof = Profile(id=profile_id, user_id=user_id, name=name)
    session.add_all([user, prof])
    await session.commit()

class NetworkSpyExecutor:
    """Tracks network invocation, transmitted byte count, and argument history."""

    def __init__(self) -> None:
        self.invocations: int = 0
        self.bytes_sent: int = 0
        self.call_history: List[Dict[str, Any]] = []

    async def __call__(self, args: Dict[str, Any]) -> Dict[str, Any]:
        self.invocations += 1
        serialized = json.dumps(args).encode("utf-8")
        self.bytes_sent += len(serialized)
        self.call_history.append(dict(args))
        return {"status": "dispatched", "bytes": len(serialized), "args": args}


def make_authenticated_request(token: str = "test-bearer-token") -> Request:
    """Constructs a mock Starlette Request with an explicit Authorization header to satisfy CSRF."""
    return Request(
        scope={
            "type": "http",
            "method": "POST",
            "headers": [
                (b"authorization", f"Bearer {token}".encode("utf-8")),
            ],
        }
    )


def make_user_profile(user_id: str) -> UserProfile:
    """Constructs a valid UserProfile domain model with required timestamps."""
    now = datetime.now(timezone.utc)
    return UserProfile(
        id=user_id,
        email=f"{user_id}@test.local",
        username=user_id,
        role="member",
        status="active",
        created_at=now,
        updated_at=now,
    )


# ============================================================================
# Section 1: Empirical Production DB Lifecycle (Initial Turn, Decision, Resume)
# ============================================================================

@pytest.mark.asyncio
async def test_empirical_initial_turn_creates_pending_approval_with_15m_ttl():
    """Verify initial turn against real SQLite DB creates pending Approval record with expires_at = now + 15m.

    Strict empirical constraint: ToolNode instantiated without approval_store test double.
    Must use production SqlApprovalStore backed by SQLite database.
    """
    await init_db()
    factory = get_session_factory()

    profile_id = f"prof-ttl-{uuid.uuid4().hex[:6]}"
    user_id = f"user-ttl-{uuid.uuid4().hex[:6]}"
    thread_id = f"thread-ttl-{uuid.uuid4().hex[:6]}"
    call_id = "call_order_1"

    async with factory() as session:
        await create_user_and_profile(session, user_id, profile_id, "Empirical Profile")

    spy = NetworkSpyExecutor()
    spec = ToolSpec(
        name="dispatch_prescription",
        description="Outbound e-prescription submission",
        risk_tier="write_external",
        data_flows=("pharmacy.health.org",),
        executor=spy,
    )

    # ZERO test doubles passed: ToolNode defaults to SqlApprovalStore()
    node = ToolNode(
        allowed_tools=["dispatch_prescription"],
        tools=[spec],
    )

    proposed_args = {
        "pharmacy_url": "https://pharmacy.health.org/rx",
        "medication": "Amoxicillin 500mg",
        "refills": 1,
    }

    state = {
        "messages": [],
        "tool_calls": [{
            "id": call_id,
            "name": "dispatch_prescription",
            "args": proposed_args,
        }],
        "profile_id": profile_id,
        "user_id": user_id,
        "thread_id": thread_id,
    }

    builder = StateGraph(Dict[str, Any])
    builder.add_node("tools", node.execute)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)

    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": thread_id, "autonomy": "A1"}}

    # Turn 1: Execution pauses and emits approval_required SSE event
    events: List[Dict[str, Any]] = []
    async for ev in graph.astream_events(state, config=config, version="v2"):
        if ev.get("event") == "on_custom_event":
            events.append(ev)

    assert len(events) == 1, f"Expected 1 SSE event, got {len(events)}"
    assert events[0]["name"] == SSE_EVENT_APPROVAL_REQUIRED
    app_id = events[0]["data"]["approval_id"]

    # Invariant: Tool executor was NEVER called during interrupt turn
    assert spy.invocations == 0
    assert spy.bytes_sent == 0

    # EMPIRICAL SQLITE DB ASSERTIONS
    async with factory() as session:
        stmt = select(Approval).where(Approval.id == app_id)
        res = await session.execute(stmt)
        record = res.scalar_one_or_none()

        assert record is not None, f"Approval record '{app_id}' was not created in SQLite DB!"
        assert record.status == "pending"
        assert record.profile_id == profile_id
        assert record.tool_name == "dispatch_prescription"
        assert record.payload_hash == compute_payload_hash(proposed_args)

        # Invariant: expires_at must be strictly set to created_at + 15 minutes (900 seconds)
        created_utc = record.created_at.replace(tzinfo=timezone.utc) if record.created_at.tzinfo is None else record.created_at
        expires_utc = record.expires_at.replace(tzinfo=timezone.utc) if record.expires_at.tzinfo is None else record.expires_at
        ttl_seconds = (expires_utc - created_utc).total_seconds()
        assert abs(ttl_seconds - 900.0) < 5.0, (
            f"TTL specification violation: expected 900s (15m), but got {ttl_seconds}s!"
        )


@pytest.mark.asyncio
async def test_empirical_human_decision_via_decide_approval_sets_approved():
    """Verify human decision via decide_approval transitions SQLite record from pending to approved.

    Asserts:
    - Status transitions to 'approved'.
    - decided_at timestamp is populated in UTC.
    - decided_by captures the authenticated steward's user ID.
    """
    await init_db()
    factory = get_session_factory()

    profile_id = f"prof-dec-{uuid.uuid4().hex[:6]}"
    user_id = f"user-dec-{uuid.uuid4().hex[:6]}"
    thread_id = f"thread-dec-{uuid.uuid4().hex[:6]}"
    call_id = "call_dec_1"

    async with factory() as session:
        await create_user_and_profile(session, user_id, profile_id, "Decision Profile")

    spy = NetworkSpyExecutor()
    spec = ToolSpec(
        name="send_external_report",
        risk_tier="write_external",
        data_flows=("registry.clinic.org",),
        executor=spy,
    )

    node = ToolNode(allowed_tools=["send_external_report"], tools=[spec])
    args = {"report_id": "R-100", "destination": "https://registry.clinic.org/ingest"}

    state = {
        "messages": [],
        "tool_calls": [{"id": call_id, "name": "send_external_report", "args": args}],
        "profile_id": profile_id,
        "user_id": user_id,
        "thread_id": thread_id,
    }

    builder = StateGraph(Dict[str, Any])
    builder.add_node("tools", node.execute)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": thread_id, "autonomy": "A1"}}

    # Turn 1: Pause on interrupt
    async for _ in graph.astream_events(state, config=config, version="v2"):
        pass

    app_id = f"app_{thread_id}_{call_id}"

    # Verify initial pending state in SQLite
    async with factory() as session:
        rec = (await session.execute(select(Approval).where(Approval.id == app_id))).scalar_one()
        assert rec.status == "pending"
        assert rec.decided_at is None
        assert rec.decided_by is None

    # Human decision: Steward approves via decide_approval function
    req = make_authenticated_request()
    steward = make_user_profile(user_id)
    decide_payload = ApprovalDecideRequest(decision="approved")

    async with factory() as session:
        resp = await decide_approval(app_id, decide_payload, req, steward, session)
        assert resp.status == "approved"
        assert resp.decided_by == user_id

    # Verify SQLite DB reflects the decision
    async with factory() as session:
        rec_after = (await session.execute(select(Approval).where(Approval.id == app_id))).scalar_one()
        assert rec_after.status == "approved"
        assert rec_after.decided_at is not None
        assert rec_after.decided_by == user_id


@pytest.mark.asyncio
async def test_empirical_resumption_turn_consumes_token_atomically():
    """Verify resumption turn consumes token atomically via SqlApprovalStore, setting status to 'consumed'.

    Asserts:
    - ToolNode re-enters without re-emitting duplicate approval_required SSE events.
    - Tool executor is executed exactly once with expected payload.
    - Approval record in SQLite DB transitions from 'approved' to 'consumed'.
    - LangGraph workflow completes cleanly (next == ()).
    """
    await init_db()
    factory = get_session_factory()

    profile_id = f"prof-res-{uuid.uuid4().hex[:6]}"
    user_id = f"user-res-{uuid.uuid4().hex[:6]}"
    thread_id = f"thread-res-{uuid.uuid4().hex[:6]}"
    call_id = "call_res_1"

    async with factory() as session:
        await create_user_and_profile(session, user_id, profile_id, "Resume Profile")

    spy = NetworkSpyExecutor()
    spec = ToolSpec(
        name="transfer_records",
        risk_tier="write_external",
        data_flows=("health.records.gov",),
        executor=spy,
    )

    node = ToolNode(allowed_tools=["transfer_records"], tools=[spec])
    args = {"target": "https://health.records.gov/transfer", "batch_size": 25}

    state = {
        "messages": [],
        "tool_calls": [{"id": call_id, "name": "transfer_records", "args": args}],
        "profile_id": profile_id,
        "user_id": user_id,
        "thread_id": thread_id,
    }

    builder = StateGraph(Dict[str, Any])
    builder.add_node("tools", node.execute)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": thread_id, "autonomy": "A1"}}

    # Turn 1: Interrupt
    async for _ in graph.astream_events(state, config=config, version="v2"):
        pass

    app_id = f"app_{thread_id}_{call_id}"

    # Steward decision via decide_approval
    req = make_authenticated_request()
    steward = make_user_profile(user_id)
    async with factory() as session:
        await decide_approval(app_id, ApprovalDecideRequest(decision="approved"), req, steward, session)

    # Turn 2: Resumption turn with Command(resume=...)
    turn2_events: List[Dict[str, Any]] = []
    resume_cmd = Command(resume={"approval_id": app_id, "decision": "approved"})
    async for ev in graph.astream_events(resume_cmd, config=config, version="v2"):
        if ev.get("event") == "on_custom_event":
            turn2_events.append(ev)

    # Invariant: Zero duplicate approval_required SSE events on resumption
    assert len(turn2_events) == 0, f"Resumption re-emitted {len(turn2_events)} duplicate SSE events!"

    # Invariant: Tool was executed exactly once
    assert spy.invocations == 1
    assert spy.bytes_sent > 0
    assert spy.call_history[0] == args

    # EMPIRICAL SQLITE DB ASSERTION: status transitioned to 'consumed'
    async with factory() as session:
        rec_final = (await session.execute(select(Approval).where(Approval.id == app_id))).scalar_one()
        assert rec_final.status == "consumed", f"Expected 'consumed', got '{rec_final.status}'!"

    # Graph completed
    final_st = await graph.aget_state(config)
    assert final_st.next == ()


# ============================================================================
# Section 2: Replay Attack Defense (Single-Use Token Enforcement)
# ============================================================================

@pytest.mark.asyncio
async def test_empirical_replay_attack_fails_closed_zero_executions():
    """Verify replay attack: attempting a second resume with consumed token fails closed with 0 tool executions.

    Attacks:
    1. Direct execute_tool_call with the already-consumed approval ID.
    2. Direct SqlApprovalStore.consume_atomic invocation with the consumed token.
    3. REST decide endpoint re-decision on the consumed token.

    Invariants:
    - Tool executor is called 0 additional times.
    - Zero additional network bytes transmitted.
    - SQLite record status remains strictly 'consumed'.
    """
    await init_db()
    factory = get_session_factory()

    profile_id = f"prof-replay-{uuid.uuid4().hex[:6]}"
    user_id = f"user-replay-{uuid.uuid4().hex[:6]}"
    thread_id = f"thread-replay-{uuid.uuid4().hex[:6]}"
    call_id = "call_rep_1"

    async with factory() as session:
        await create_user_and_profile(session, user_id, profile_id, "Replay Profile")

    spy = NetworkSpyExecutor()
    spec = ToolSpec(
        name="charge_copay",
        risk_tier="irreversible",
        data_flows=("payments.health.org",),
        executor=spy,
    )

    node = ToolNode(allowed_tools=["charge_copay"], tools=[spec])
    args = {"amount_cents": 2500, "currency": "USD", "gateway": "https://payments.health.org/charge"}

    state = {
        "messages": [],
        "tool_calls": [{"id": call_id, "name": "charge_copay", "args": args}],
        "profile_id": profile_id,
        "user_id": user_id,
        "thread_id": thread_id,
    }

    builder = StateGraph(Dict[str, Any])
    builder.add_node("tools", node.execute)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": thread_id, "autonomy": "A1"}}

    # Turn 1: Interrupt
    async for _ in graph.astream_events(state, config=config, version="v2"):
        pass

    app_id = f"app_{thread_id}_{call_id}"

    # Steward approves
    req = make_authenticated_request()
    steward = make_user_profile(user_id)
    async with factory() as session:
        await decide_approval(app_id, ApprovalDecideRequest(decision="approved"), req, steward, session)

    # Turn 2: Legitimate first resumption -> consumes token
    resume_cmd = Command(resume={"approval_id": app_id, "decision": "approved"})
    async for _ in graph.astream_events(resume_cmd, config=config, version="v2"):
        pass

    assert spy.invocations == 1
    bytes_after_legit = spy.bytes_sent

    # Verify status is consumed in SQLite
    async with factory() as session:
        rec = (await session.execute(select(Approval).where(Approval.id == app_id))).scalar_one()
        assert rec.status == "consumed"

    # REPLAY ATTACK 1: Attacker attempts to re-execute tool call using consumed approval_id
    ctx = ToolContext(user_id=user_id, profile_id=profile_id, autonomy="A1")
    res_replay = await execute_tool_call(
        ctx, spec, args, approval_id=app_id
    )

    assert res_replay.success is False
    assert "ApprovalResumeFailed" in (res_replay.error or "")
    assert any(
        phrase in (res_replay.error or "").lower()
        for phrase in ("cannot consume", "already been consumed")
    )

    # Invariant: ZERO additional tool executions or network bytes
    assert spy.invocations == 1, f"Security violation: tool executed {spy.invocations} times during replay attack!"
    assert spy.bytes_sent == bytes_after_legit, "Security violation: bytes transmitted during replay attack!"

    # REPLAY ATTACK 2: Direct SqlApprovalStore atomic consumption attempt
    sql_store = SqlApprovalStore()
    with pytest.raises(ValueError, match="cannot consume|already been consumed"):
        await sql_store.consume_atomic(app_id, args)

    assert spy.invocations == 1

    # REPLAY ATTACK 3: Re-decision on consumed record via decide_approval must fail with HTTP 400
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        async with factory() as session:
            await decide_approval(app_id, ApprovalDecideRequest(decision="approved"), req, steward, session)
    assert exc_info.value.status_code == 400
    assert "already in status 'consumed'" in exc_info.value.detail

    # Invariant: Record in SQLite database remains strictly 'consumed'
    async with factory() as session:
        rec_check = (await session.execute(select(Approval).where(Approval.id == app_id))).scalar_one()
        assert rec_check.status == "consumed"


# ============================================================================
# Section 3: TOCTOU & Argument Tampering Defense
# ============================================================================

@pytest.mark.asyncio
async def test_empirical_toctou_attack_argument_tampering_aborts():
    """Verify TOCTOU attack: modifying tool arguments post-approval triggers payload hash mismatch and aborts execution.

    Asserts:
    - Pending record created with original arguments and original RFC-8785 payload hash.
    - Steward approves original arguments.
    - Attacker resumes tool execution with tampered arguments.
    - Verification detects payload hash mismatch and aborts execution immediately.
    - Tool executor is called ZERO times on tampered arguments.
    - Database record remains in 'approved' status (not burnt by attacker).
    - Subsequent legitimate resumption with original approved arguments succeeds cleanly.
    """
    await init_db()
    factory = get_session_factory()

    profile_id = f"prof-toctou-{uuid.uuid4().hex[:6]}"
    user_id = f"user-toctou-{uuid.uuid4().hex[:6]}"
    thread_id = f"thread-toctou-{uuid.uuid4().hex[:6]}"
    call_id = "call_toctou_1"

    async with factory() as session:
        await create_user_and_profile(session, user_id, profile_id, "TOCTOU Profile")

    spy = NetworkSpyExecutor()
    spec = ToolSpec(
        name="export_health_records",
        risk_tier="write_external",
        data_flows=("vault.hospital.org",),
        executor=spy,
    )

    original_args = {
        "destination": "https://vault.hospital.org/ingest",
        "record_ids": ["REC-001", "REC-002"],
        "purpose": "clinical_summary",
    }
    tampered_args = {
        "destination": "https://vault.hospital.org/ingest",
        "record_ids": ["REC-001", "REC-002", "EXFILTRATE_ALL_DATA"],
        "purpose": "clinical_summary",
    }

    # Step 1: Create pending approval using SqlApprovalStore directly
    app_id = f"app_{thread_id}_{call_id}"
    sql_store = SqlApprovalStore()
    await sql_store.create_pending(
        approval_id=app_id,
        profile_id=profile_id,
        run_id="run-toctou-1",
        tool_name="export_health_records",
        args=original_args,
        risk_tier="write_external",
        destination_hosts=["vault.hospital.org"],
        thread_id=thread_id,
    )

    # Step 2: Steward approves original arguments
    req = make_authenticated_request()
    steward = make_user_profile(user_id)
    async with factory() as session:
        await decide_approval(app_id, ApprovalDecideRequest(decision="approved"), req, steward, session)

    # Step 3: TOCTOU ATTACK — execute tool call with tampered arguments
    ctx = ToolContext(user_id=user_id, profile_id=profile_id, autonomy="A1")
    tampered_result = await execute_tool_call(
        ctx, spec, tampered_args, approval_id=app_id
    )

    # Invariant: Tampered call must fail closed
    assert tampered_result.success is False
    assert "ApprovalResumeFailed" in (tampered_result.error or "")
    assert "Payload hash mismatch" in (tampered_result.error or "")

    # Invariant: Executor was NEVER called with tampered arguments
    assert spy.invocations == 0
    assert spy.bytes_sent == 0

    # Invariant: SQLite record status is NOT consumed by the attack; remains 'approved'
    async with factory() as session:
        rec_mid = (await session.execute(select(Approval).where(Approval.id == app_id))).scalar_one()
        assert rec_mid.status == "approved"

    # Step 4: Legitimate resumption with original arguments succeeds
    legit_result = await execute_tool_call(
        ctx, spec, original_args, approval_id=app_id
    )

    assert legit_result.success is True
    assert spy.invocations == 1
    assert spy.bytes_sent > 0
    assert spy.call_history[0] == original_args

    # Invariant: SQLite record is now consumed
    async with factory() as session:
        rec_final = (await session.execute(select(Approval).where(Approval.id == app_id))).scalar_one()
        assert rec_final.status == "consumed"


# ============================================================================
# Section 4: Schema Boundary & ID Length Defense (>36 Chars)
# ============================================================================

@pytest.mark.asyncio
async def test_empirical_long_thread_id_respects_36_char_column_limit():
    """Verify long thread ID (>36 chars) respects the 36-character column limit without SQL truncation error.

    Attack / failure mode:
    If thread_id is a long UUID or composite string, raw_app_id = f"app_{thread_id}_{call_id}"
    exceeds 36 characters. On strict SQL engines (PostgreSQL or SQLite), this would trigger
    a schema truncation error during insertion.
    Hardened behavior:
    ToolNode hashes raw_app_id exceeding 36 chars to f"app_{sha256(raw_app_id)[:30]}", strictly
    satisfying the 36-character column limit (len == 34).
    """
    await init_db()
    factory = get_session_factory()

    # Long thread ID: 70 characters (well over the 36-character column bound)
    long_thread_id = "thread_uuid_v4_style_8a7b6c5d_4e3f_2a1b_c0d9_e8f7a6b5c4d3_very_long"
    profile_id = f"prof-long-{uuid.uuid4().hex[:6]}"
    user_id = f"user-long-{uuid.uuid4().hex[:6]}"
    call_id = "call_schedule_very_long_name_123"

    assert len(long_thread_id) > 36, "Pre-condition: thread_id must exceed 36 characters"
    raw_id = f"app_{long_thread_id}_{call_id}"
    assert len(raw_id) > 36, f"Pre-condition: raw_id must exceed 36 chars, was {len(raw_id)}"

    async with factory() as session:
        await create_user_and_profile(session, user_id, profile_id, "Long Thread Profile")

    spy = NetworkSpyExecutor()
    spec = ToolSpec(
        name="schedule_visit",
        risk_tier="write_external",
        data_flows=("telehealth.clinic.org",),
        executor=spy,
    )

    # Use production ToolNode without test doubles
    node = ToolNode(allowed_tools=["schedule_visit"], tools=[spec])
    args = {"provider": "Dr. Smith", "date": "2026-11-15"}

    state = {
        "messages": [],
        "tool_calls": [{"id": call_id, "name": "schedule_visit", "args": args}],
        "profile_id": profile_id,
        "user_id": user_id,
        "thread_id": long_thread_id,
    }

    builder = StateGraph(Dict[str, Any])
    builder.add_node("tools", node.execute)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": long_thread_id, "autonomy": "A1"}}

    # Turn 1: Initial invocation pauses and creates record in SQLite DB
    events: List[Dict[str, Any]] = []
    async for ev in graph.astream_events(state, config=config, version="v2"):
        if ev.get("event") == "on_custom_event":
            events.append(ev)

    assert len(events) == 1
    generated_app_id = events[0]["data"]["approval_id"]

    # CRITICAL INVARIANT: Generated approval_id must be strictly <= 36 characters
    assert len(generated_app_id) <= 36, (
        f"Column overflow violation: approval_id '{generated_app_id}' has length {len(generated_app_id)} > 36!"
    )
    assert len(generated_app_id) == 34, f"Expected 34 characters (app_ + 30 hex), got {len(generated_app_id)}"
    assert generated_app_id.startswith("app_")

    # Invariant: Record was successfully inserted into SQLite DB without truncation error
    async with factory() as session:
        stmt = select(Approval).where(Approval.id == generated_app_id)
        res = await session.execute(stmt)
        record = res.scalar_one_or_none()
        assert record is not None, f"Record with bounded ID '{generated_app_id}' was not found in SQLite DB!"
        assert record.status == "pending"

    # Step 2: Steward approves via decide_approval
    req = make_authenticated_request()
    steward = make_user_profile(user_id)
    async with factory() as session:
        await decide_approval(generated_app_id, ApprovalDecideRequest(decision="approved"), req, steward, session)

    # Step 3: Resumption turn with bounded approval_id succeeds end-to-end
    resume_cmd = Command(resume={"approval_id": generated_app_id, "decision": "approved"})
    async for _ in graph.astream_events(resume_cmd, config=config, version="v2"):
        pass

    assert spy.invocations == 1
    assert spy.bytes_sent > 0

    # Invariant: SQLite record successfully transitioned to consumed
    async with factory() as session:
        rec_check = (await session.execute(select(Approval).where(Approval.id == generated_app_id))).scalar_one()
        assert rec_check.status == "consumed"


# ============================================================================
# Section 5: High-Concurrency Race Condition & TTL Expiration on SQLite
# ============================================================================

@pytest.mark.asyncio
async def test_empirical_concurrency_race_condition_on_real_sqlite():
    """Verify concurrency race condition directly on real SQLite database.

    10 concurrent asyncio tasks attempt to consume the EXACT SAME approved SQLite token simultaneously.
    Invariant: EXACTLY ONE task succeeds; EXACTLY 9 tasks fail closed with ValueError.
    Final DB status must be 'consumed'.
    """
    await init_db()
    factory = get_session_factory()

    profile_id = f"prof-race-{uuid.uuid4().hex[:6]}"
    app_id = f"app-race-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    args = {"action": "dispatch_concurrent_lab_order", "patient_id": "P-999"}

    async with factory() as session:
        prof = Profile(id=profile_id, name="Race Profile")
        session.add(prof)
        record = Approval(
            id=app_id,
            profile_id=profile_id,
            run_id="run-race-1",
            tool_name="dispatch_concurrent_lab_order",
            args_redacted=json.dumps(args),
            payload_hash=compute_payload_hash(args),
            risk_tier="irreversible",
            status="approved",
            expires_at=now + timedelta(minutes=15),
            created_at=now,
            decided_at=now,
            decided_by="steward-1",
        )
        session.add(record)
        await session.commit()

    num_racers = 10
    sql_store = SqlApprovalStore()

    async def _racer_task():
        return await sql_store.consume_atomic(app_id, args)

    results = await asyncio.gather(
        *[_racer_task() for _ in range(num_racers)],
        return_exceptions=True,
    )

    successes = [r for r in results if isinstance(r, str) and r == app_id]
    failures = [r for r in results if isinstance(r, Exception)]

    assert len(successes) == 1, f"Expected exactly 1 success in race, got {len(successes)}: {results}"
    assert len(failures) == num_racers - 1, f"Expected {num_racers - 1} failures, got {len(failures)}"
    for exc in failures:
        assert isinstance(exc, ValueError), f"Expected ValueError, got {type(exc)}: {exc}"
        assert any(
            phrase in str(exc)
            for phrase in ("cannot consume", "already been consumed", "invalid")
        )

    # Invariant: Record in SQLite is consumed
    async with factory() as session:
        rec = (await session.execute(select(Approval).where(Approval.id == app_id))).scalar_one()
        assert rec.status == "consumed"


@pytest.mark.asyncio
async def test_empirical_expired_token_on_real_sqlite_fails_closed():
    """Verify expired token attack against real SQLite database fails closed.

    Record in SQLite DB was marked 'approved', but expires_at has passed.
    Attempting SqlApprovalStore.consume_atomic must fail closed with ValueError('has expired')
    and transition database status to 'expired'.
    """
    await init_db()
    factory = get_session_factory()

    profile_id = f"prof-exp-{uuid.uuid4().hex[:6]}"
    app_id = f"app-exp-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    past_expiration = now - timedelta(seconds=10)
    args = {"action": "emergency_data_export"}

    async with factory() as session:
        prof = Profile(id=profile_id, name="Expired Profile")
        session.add(prof)
        record = Approval(
            id=app_id,
            profile_id=profile_id,
            run_id="run-exp-1",
            tool_name="emergency_data_export",
            args_redacted=json.dumps(args),
            payload_hash=compute_payload_hash(args),
            risk_tier="write_external",
            status="approved",
            expires_at=past_expiration,
            created_at=now - timedelta(minutes=30),
            decided_at=now - timedelta(minutes=15),
            decided_by="steward-1",
        )
        session.add(record)
        await session.commit()

    sql_store = SqlApprovalStore()
    with pytest.raises(ValueError, match="has expired"):
        await sql_store.consume_atomic(app_id, args)

    # Invariant: Record status in SQLite database updated to 'expired'
    async with factory() as session:
        rec = (await session.execute(select(Approval).where(Approval.id == app_id))).scalar_one()
        assert rec.status == "expired"
