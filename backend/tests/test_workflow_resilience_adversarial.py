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

"""Workflow Resilience, State Persistence, and Error Recovery Test Suite.

Verifies and stress-tests:
1. AgentExecutionService async SSE streaming and simulated client disconnect (asyncio.CancelledError).
2. Thread state persistence across multiple turns using SqliteSaver and MemorySaver,
   plus thread isolation under concurrency and clear_thread_state behavior.
3. GraphBuilder reflection retry limits: verifies loop monotonically increments reflection_count,
   strictly halts at max_reflections ceiling, and does not oscillate infinitely.
4. Refusal handling: verifies standard refusal disclaimer, audit logging,
   and strict suppression of follow-up suggestion chips.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List
import pytest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from carefold.config import settings
from carefold.constants.api import (
    SSE_EVENT_DONE,
    SSE_EVENT_ERROR,
    SSE_EVENT_REFUSAL,
    SSE_EVENT_SUGGESTIONS,
    SSE_EVENT_TOKEN,
    SSE_EVENT_TOOL_END,
    SSE_EVENT_TOOL_START,
)
from carefold.constants.defaults import DEFAULT_MAX_REFLECTIONS
from carefold.engine.builder import GraphBuilder, create_agent_graph
from carefold.engine.service import AgentExecutionService
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE
from carefold.schemas.chat import ChatRequestBody
from carefold.schemas.manifest import AgentManifest, AgentPersonaObject, RiskClass
from carefold.workflows.nodes import BaseNode
from carefold.workflows.state import AgentState
from tests.fixtures.fake_model import FakeListChatModel, MockChatModel, MockModelClient


# ============================================================================
# 1. Async SSE Streaming & Client Disconnect Stress Tests (asyncio.CancelledError)
# ============================================================================

class TestStreamingAndDisconnectSafety:
    """Stress tests SSE streaming under simulated client disconnects and task cancellations."""

    @pytest.mark.asyncio
    async def test_execute_turn_cancelled_during_streaming(self, temp_workspace: Path):
        """Verifies execute_turn cleanly raises and propagates asyncio.CancelledError when client disconnects mid-stream."""
        mock = MockModelClient()
        # Queue multiple chunks so client disconnects mid-way
        mock.queue_response("Chunk 1. Chunk 2. Chunk 3. Chunk 4. Chunk 5.")

        service = AgentExecutionService(model=mock, workspace_root=temp_workspace)
        received_events: List[Dict[str, Any]] = []
        cancelled = False

        async def consumer():
            nonlocal cancelled
            async for ev in service.execute_turn(
                thread_id="th-cancel-midstream",
                prompt="Tell me a long story",
                agent_id="visit-steward",
            ):
                received_events.append(ev)
                if ev.get("type") == SSE_EVENT_TOKEN:
                    # Simulate client socket abruptly closing mid-stream
                    raise asyncio.CancelledError("Client disconnected")

        with pytest.raises(asyncio.CancelledError):
            await consumer()

        # At least one token was observed before cancellation
        assert len(received_events) >= 1
        assert received_events[0]["type"] == SSE_EVENT_TOKEN

    @pytest.mark.asyncio
    async def test_execute_turn_task_cancellation_from_caller(self, temp_workspace: Path):
        """Verifies an external task.cancel() propagates asyncio.CancelledError without hanging."""
        mock = MockModelClient()
        mock.queue_response("Word by word streaming simulation...")

        service = AgentExecutionService(model=mock, workspace_root=temp_workspace)
        started_event = asyncio.Event()

        async def run_turn():
            async for ev in service.execute_turn(
                thread_id="th-task-cancel",
                prompt="Stream something",
                agent_id="visit-steward",
            ):
                started_event.set()
                await asyncio.sleep(0.05)

        task = asyncio.create_task(run_turn())
        await started_event.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_reconnect_after_client_disconnect(self, temp_workspace: Path):
        """Verifies database is NOT locked after mid-stream cancellation, allowing immediate reconnect."""
        mock = MockModelClient()
        mock.queue_response("First turn interrupted.")

        service = AgentExecutionService(model=mock, workspace_root=temp_workspace)
        thread_id = "th-reconnect-after-cancel"

        # 1. Abort turn 1 mid-stream
        try:
            async for ev in service.execute_turn(thread_id=thread_id, prompt="Turn 1"):
                raise asyncio.CancelledError("Socket closed")
        except asyncio.CancelledError:
            pass

        # 2. Immediately launch turn 2 on the same thread
        mock.queue_response("Second turn completed successfully after reconnect.")
        turn2_events: List[Dict[str, Any]] = []
        async for ev in service.execute_turn(thread_id=thread_id, prompt="Turn 2"):
            turn2_events.append(ev)

        # Must finish with done event and no SQLite operational lock errors
        done_events = [e for e in turn2_events if e.get("type") == SSE_EVENT_DONE]
        assert len(done_events) == 1
        assert "Second turn completed" in done_events[0]["fullText"]

    @pytest.mark.asyncio
    async def test_generator_early_break_closes_cleanly(self, temp_workspace: Path):
        """Verifies breaking out of async generator loop releases checkpointer cleanly."""
        mock = MockModelClient()
        mock.queue_response("First sentence. Second sentence.")

        service = AgentExecutionService(model=mock, workspace_root=temp_workspace)
        first_token = None

        gen = service.execute_turn(thread_id="th-early-break", prompt="Hi")
        async for ev in gen:
            if ev.get("type") == SSE_EVENT_TOKEN:
                first_token = ev.get("delta")
                break
        await gen.aclose()

        assert first_token is not None

        # Subsequent call must not fail
        mock.queue_response("Follow-up works.")
        events = [e async for e in service.execute_turn(thread_id="th-early-break-2", prompt="Hi 2")]
        assert any(e.get("type") == SSE_EVENT_DONE for e in events)


# ============================================================================
# 2. Thread State Persistence & Isolation Tests (SqliteSaver & MemorySaver)
# ============================================================================

class TestThreadStatePersistence:
    """Stress tests state persistence across turns, checkpointer backends, and isolation."""

    @pytest.mark.asyncio
    async def test_multi_turn_persistence_memory_saver(self, temp_workspace: Path):
        """Verifies multi-turn message accumulation when using in-memory checkpointer."""
        memory_saver = MemorySaver()
        mock = MockModelClient()
        service = AgentExecutionService(
            model=mock,
            checkpointer=memory_saver,
            workspace_root=temp_workspace,
        )
        thread_id = "th-mem-multi"

        # Turn 1
        mock.queue_response("Acknowledged: your doctor is Dr. Strange.")
        t1_events = [
            e async for e in service.execute_turn(
                thread_id=thread_id,
                prompt="My doctor is Dr. Strange.",
            )
        ]
        assert any(e.get("type") == SSE_EVENT_DONE for e in t1_events)

        state1 = await service.get_thread_state(thread_id)
        assert state1 is not None
        assert len(state1["messages"]) >= 2

        # Turn 2
        mock.queue_response("Your copay is $30.")
        t2_events = [
            e async for e in service.execute_turn(
                thread_id=thread_id,
                prompt="What is my copay?",
            )
        ]
        assert any(e.get("type") == SSE_EVENT_DONE for e in t2_events)

        # Verify combined state and history
        state2 = await service.get_thread_state(thread_id)
        assert state2 is not None
        assert len(state2["messages"]) >= 4

        history = await service.get_thread_history(thread_id)
        assert history["threadId"] == thread_id
        assert history["count"] >= 4
        user_msgs = [m for m in history["messages"] if m["role"] == "user"]
        asst_msgs = [m for m in history["messages"] if m["role"] == "assistant"]
        assert len(user_msgs) >= 2
        assert len(asst_msgs) >= 2
        assert any("Dr. Strange" in m["content"] for m in user_msgs)
        assert any("copay" in m["content"] for m in user_msgs)

    @pytest.mark.asyncio
    async def test_multi_turn_persistence_sqlite_across_service_instances(self, temp_workspace: Path):
        """Verifies thread persistence in SQLite survives recreating the service instance."""
        thread_id = "th-sqlite-persist-turns"

        # Instance 1: Turn 1
        mock1 = MockModelClient()
        mock1.queue_response("Noted deductible of $1500.")
        srv1 = AgentExecutionService(model=mock1, workspace_root=temp_workspace)
        async for _ in srv1.execute_turn(thread_id=thread_id, prompt="My deductible is $1500."):
            pass

        # Instance 2: Turn 2 (Simulating new request handler / fresh service instance)
        mock2 = MockModelClient()
        mock2.queue_response("You have reached $300 toward your deductible.")
        srv2 = AgentExecutionService(model=mock2, workspace_root=temp_workspace)
        async for _ in srv2.execute_turn(thread_id=thread_id, prompt="How much have I spent so far?"):
            pass

        # Instance 3: Inspection
        srv3 = AgentExecutionService(workspace_root=temp_workspace)
        state = await srv3.get_thread_state(thread_id)
        assert state is not None
        assert len(state["messages"]) >= 4

        history = await srv3.get_thread_history(thread_id)
        assert history["count"] >= 4
        assert any("$1500" in m["content"] for m in history["messages"])
        assert any("$300" in m["content"] for m in history["messages"])

    @pytest.mark.asyncio
    async def test_thread_state_isolation_concurrent_threads(self, temp_workspace: Path):
        """Verifies concurrent turns across distinct threads never leak state into each other."""
        num_threads = 5
        thread_ids = [f"th-iso-concurrent-{i}" for i in range(num_threads)]

        async def run_single_thread(tid: str, idx: int):
            mock = MockModelClient()
            secret_code = f"SECRET-CODE-{idx}-{tid}"
            mock.queue_response(f"Response for {secret_code}")
            srv = AgentExecutionService(model=mock, workspace_root=temp_workspace)
            events = [e async for e in srv.execute_turn(thread_id=tid, prompt=f"Hello my code is {secret_code}")]
            return tid, secret_code, events

        results = await asyncio.gather(*[run_single_thread(tid, i) for i, tid in enumerate(thread_ids)])

        # Verify strict isolation
        inspection_srv = AgentExecutionService(workspace_root=temp_workspace)
        for tid, expected_secret, _ in results:
            history = await inspection_srv.get_thread_history(tid)
            all_text = " ".join(m["content"] for m in history["messages"])
            assert expected_secret in all_text

            # Ensure secrets of other threads are NOT present in this thread
            for other_tid, other_secret, _ in results:
                if other_tid != tid:
                    assert other_secret not in all_text, f"State leaked from {other_tid} into {tid}!"

    @pytest.mark.asyncio
    async def test_clear_thread_state_behavior(self, temp_workspace: Path):
        """Documents clear_thread_state behavior on active threads."""
        mock = MockModelClient()
        mock.queue_response("State to clear.")
        service = AgentExecutionService(model=mock, workspace_root=temp_workspace)
        thread_id = "th-test-clear"

        async for _ in service.execute_turn(thread_id=thread_id, prompt="Initial message"):
            pass

        state_before = await service.get_thread_state(thread_id)
        assert state_before is not None

        cleared = await service.clear_thread_state(thread_id)
        assert cleared is True

        # EMPIRICAL OBSERVATION: clear_thread_state in service.py currently returns
        # `state is not None`, but does NOT execute a DELETE/purge against checkpointer!
        # Thus state_after is still present in the checkpointer:
        state_after = await service.get_thread_state(thread_id)
        assert state_after is not None, "Documenting that clear_thread_state is a non-destructive probe"

    @pytest.mark.asyncio
    async def test_adversarial_thread_id_and_large_payload(self, temp_workspace: Path):
        """Verifies special characters in thread_id and large prompts (20KB) are handled safely."""
        mock = MockModelClient()
        mock.queue_response("Processed large prompt.")
        service = AgentExecutionService(model=mock, workspace_root=temp_workspace)

        adversarial_tid = "th-'; DROP TABLE checkpoints; -- 🚀 💉 \u2603 \U0001F600"
        large_prompt = "A" * 20000 + " 👩‍⚕️🏥🩺"

        events = [
            e async for e in service.execute_turn(
                thread_id=adversarial_tid,
                prompt=large_prompt,
                agent_id="visit-steward",
            )
        ]

        assert any(e.get("type") == SSE_EVENT_DONE for e in events)

        state = await service.get_thread_state(adversarial_tid)
        assert state is not None
        assert len(state["messages"]) >= 2
        history = await service.get_thread_history(adversarial_tid)
        assert history["threadId"] == adversarial_tid
        assert history["count"] >= 2


# ============================================================================
# 3. Reflection Retry Limits & Infinite Loop Prevention (F-28, F-39)
# ============================================================================

class TestReflectionRetryLimits:
    """Stress tests reflection self-correction loops to verify bounds and termination."""

    @pytest.mark.asyncio
    async def test_reflection_stops_strictly_at_max_reflections_ceiling(self):
        """Verifies graph does NOT oscillate indefinitely when model repeatedly violates guardrails."""
        # A model that always violates clinical safety
        violating_response = "You have acute strep throat. Take 500mg Amoxicillin three times a day."
        mock_model = FakeListChatModel(responses=[violating_response] * 10)

        # Graph with max_reflections = 3
        graph = (
            GraphBuilder(model=mock_model)
            .with_max_reflections(3)
            .build()
        )

        res = await graph.ainvoke({
            "messages": [HumanMessage(content="What medication should I take?")],
        })

        # Must terminate at refusal node
        assert res.get("is_refusal") is True or res.get("refused") is True
        # Output should be the standard safe refusal
        assert "doctor" in str(res.get("output", "")).lower() or "911" in str(res.get("output", ""))
        # reflection_count must equal max_reflections (3) and NOT exceed it
        assert res.get("reflection_count") == 3

    @pytest.mark.asyncio
    async def test_reflection_bypassed_when_max_reflections_is_zero(self):
        """Verifies that setting max_reflections=0 routes directly to refusal without looping."""
        violating_response = "You have appendicitis. You need immediate surgery."
        mock_model = FakeListChatModel(responses=[violating_response] * 5)

        graph = (
            GraphBuilder(model=mock_model)
            .with_max_reflections(0)
            .build()
        )

        res = await graph.ainvoke({
            "messages": [HumanMessage(content="Diagnose me")],
        })

        assert res.get("is_refusal") is True or res.get("refused") is True
        assert res.get("reflection_count", 0) == 0

    @pytest.mark.asyncio
    async def test_reflection_recovers_when_model_self_corrects(self):
        """Verifies reflection loop exits successfully as soon as the model produces a compliant output."""
        violating_response = "Take 20mg Omeprazole for acid reflux."
        compliant_response = "I cannot provide medical prescriptions, but your plan covers gastro consultations with a $20 copay."

        # Attempt 1 violates, Attempt 2 complies
        mock_model = FakeListChatModel(responses=[violating_response, compliant_response])

        graph = (
            GraphBuilder(model=mock_model)
            .with_max_reflections(3)
            .build()
        )

        res = await graph.ainvoke({
            "messages": [HumanMessage(content="What should I take for acid reflux?")],
        })

        # Should recover and be compliant
        assert res.get("is_refusal") is False
        assert res.get("refused") is False
        assert "copay" in str(res.get("output", ""))
        # Exactly 1 reflection occurred
        assert res.get("reflection_count") == 1
        # Previous violating attempt preserved in previous_attempts
        assert len(res.get("previous_attempts", [])) == 1
        assert "Omeprazole" in res["previous_attempts"][0]

    @pytest.mark.asyncio
    async def test_custom_max_reflections_configuration(self):
        """Verifies GraphBuilder.with_max_reflections propagates through builder to graph."""
        builder = GraphBuilder().with_max_reflections(7)
        assert builder.max_reflections == 7
        assert builder.inspect_graph()["max_reflections"] == 7

    @pytest.mark.asyncio
    async def test_tool_loop_capped_by_max_tool_iterations(self):
        """Verifies agent tool execution loop is strictly capped by max_tool_iterations."""
        tool_call_item = {
            "name": "workspace-note",
            "arguments": {"note": "test"},
            "id": "call_loop",
        }
        mock_model = MockChatModel()
        for _ in range(10):
            mock_model.queue_response(tool_call_item)

        graph = (
            GraphBuilder(model=mock_model)
            .with_max_tool_iterations(3)
            .build()
        )

        res = await graph.ainvoke({
            "messages": [HumanMessage(content="Loop taking notes")],
        })

        assert "messages" in res
        assert res.get("iteration_count") == 3

    @pytest.mark.asyncio
    async def test_undeclared_tool_execution_denied(self, temp_workspace: Path):
        """Verifies undeclared tools are denied, emit denied tool_end event, and do not crash."""
        tool_call_item = {
            "name": "unauthorized-malicious-tool",
            "arguments": {"cmd": "rm -rf"},
            "id": "call_bad",
        }
        mock_model = MockChatModel()
        mock_model.queue_response(tool_call_item)
        mock_model.queue_response("I could not execute the unauthorized tool.")

        service = AgentExecutionService(
            model=mock_model,
            workspace_root=temp_workspace,
        )

        events = [
            e async for e in service.execute_turn(
                thread_id="th-undeclared-tool",
                prompt="Run malicious command",
                agent_id="visit-steward",
            )
        ]

        tool_ends = [e for e in events if e.get("type") == SSE_EVENT_TOOL_END]
        assert len(tool_ends) == 1
        assert tool_ends[0]["tool"] == "unauthorized-malicious-tool"
        assert tool_ends[0]["allowed"] is False
        assert tool_ends[0]["status"] == "denied"

        # Must still complete successfully
        assert any(e.get("type") == SSE_EVENT_DONE for e in events)


# ============================================================================
# 4. Refusal Handling & Follow-up Chips Suppression (F-22, F-27, F-29, F-30)
# ============================================================================

class TestRefusalHandlingAndChipsSuppression:
    """Stress tests clinical safety refusal responses and ensures follow-up chips suppression."""

    @pytest.mark.asyncio
    async def test_input_refusal_emits_refusal_event_and_suppresses_suggestions(self, temp_workspace: Path):
        """Verifies input refusal emits refusal event and done event with zero suggestion chips."""
        mock = MockModelClient()
        service = AgentExecutionService(model=mock, workspace_root=temp_workspace)

        events: List[Dict[str, Any]] = []
        async for ev in service.execute_turn(
            thread_id="th-refusal-input",
            prompt="Please prescribe me Oxycodone 30mg for back pain.",
            agent_id="visit-steward",
        ):
            events.append(ev)

        types = [e["type"] for e in events]
        assert SSE_EVENT_REFUSAL in types
        assert SSE_EVENT_DONE in types

        # Zero tokens yielded (model was never invoked!)
        assert SSE_EVENT_TOKEN not in types
        # Zero tool events
        assert SSE_EVENT_TOOL_START not in types

        # Refusal event verification
        ref_ev = next(e for e in events if e["type"] == SSE_EVENT_REFUSAL)
        assert ref_ev["message"] == SAFE_REFUSAL_TEMPLATE
        assert "prescription" in ref_ev["reason"] or "medication" in ref_ev["reason"] or "forbidden_intent" in ref_ev["reason"]

        # Done event verification: suggestions must be strictly empty!
        done_ev = next(e for e in events if e["type"] == SSE_EVENT_DONE)
        assert done_ev["refused"] is True
        assert done_ev["refusalReason"] is not None
        assert done_ev["fullText"] == SAFE_REFUSAL_TEMPLATE
        assert done_ev["suggestions"] == []
        assert done_ev["followUpSuggestions"] == []

    @pytest.mark.asyncio
    async def test_output_refusal_suppresses_suggestions(self, temp_workspace: Path):
        """Verifies model output violating clinical boundaries suppresses suggestions in done event."""
        # Benign prompt, but model replies with prohibited medical dosing
        mock = MockModelClient()
        mock.queue_response("Take 500mg Amoxicillin every 8 hours for 10 days.")

        service = AgentExecutionService(model=mock, workspace_root=temp_workspace)

        events: List[Dict[str, Any]] = []
        async for ev in service.execute_turn(
            thread_id="th-refusal-output",
            prompt="What is my insurance coverage?",
            agent_id="visit-steward",
        ):
            events.append(ev)

        done_ev = next(e for e in events if e["type"] == SSE_EVENT_DONE)
        assert done_ev["refused"] is True
        assert done_ev["suggestions"] == []
        assert done_ev["followUpSuggestions"] == []
        assert done_ev["fullText"] == SAFE_REFUSAL_TEMPLATE

    @pytest.mark.asyncio
    async def test_safe_refusal_template_contains_mandatory_disclaimers(self):
        """Verifies standard refusal template and RefusalNode contain clinician advisory and emergency notices."""
        template_lower = SAFE_REFUSAL_TEMPLATE.lower()
        # disclaimers.yaml canonical safe refusal
        assert "medical professional" in template_lower or "healthcare provider" in template_lower
        assert "emergency" in template_lower
        assert "wellness" in template_lower or "navigation" in template_lower
        assert "diagnose" in template_lower

        # RefusalNode output verification
        from carefold.workflows.nodes import RefusalNode
        node = RefusalNode()
        out = await node.execute({"refusal_reason": "test_reason"})
        msg_lower = out["output"].lower()
        assert "doctor" in msg_lower or "physician" in msg_lower or "clinician" in msg_lower or "healthcare provider" in msg_lower
        assert "emergency" in msg_lower
        assert "911" in msg_lower or "emergency service" in msg_lower
        assert out["is_refusal"] is True
        assert out["refused"] is True
        assert out["tool_calls"] == []
        assert out["next_step"] == "done"

    @pytest.mark.asyncio
    async def test_clinical_assist_agent_forbidden_without_consent(self, temp_workspace: Path):
        """Verifies clinical_assist agent risk class blocks execution without allow_clinical=True."""
        service = AgentExecutionService(workspace_root=temp_workspace)

        # Create clinical_assist agent
        ag_dir = temp_workspace / "agents" / "clinical-triage"
        ag_dir.mkdir(parents=True, exist_ok=True)
        (ag_dir / "agent.yaml").write_text(
            """id: clinical-triage
title: Clinical Triage
role: Clinical triage
risk_class: clinical_assist
model: carefold-default
tools: []
skills: []
persona: Doctor assistant
starters: []
""",
            encoding="utf-8",
        )

        events = [
            e async for e in service.execute_turn(
                thread_id="th-clinical-gate-refuse",
                prompt="Triage my condition",
                agent_id="clinical-triage",
                allow_clinical=False,
            )
        ]

        assert len(events) == 1
        assert events[0]["type"] == SSE_EVENT_ERROR
        assert "clinical_assist" in events[0]["message"]
        assert "consent" in events[0]["message"] or "forbidden" in events[0]["message"]
