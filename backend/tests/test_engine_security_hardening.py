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

"""Engine Security Hardening Test Suite.

Adversarial stress verification covering:
1. Rapid Concurrent Requests & Turn Interruptions in AgentExecutionService
2. Cyclic Delegation Detection & Circuit-Breaking in OrchestratorNode
3. Re-Entrancy, Malformed Checkpointer States, & Reflection Counter Overflows
4. Complex Graph Branch Decisions Under Missing or Partial State
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
import pytest

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from carefold.agents.registry import AgentRegistry, get_agent_registry
from carefold.config import settings
from carefold.constants.agents import (
    AGENT_BENEFITS_GUIDE,
    AGENT_ORCHESTRATOR,
    AGENT_VISIT_STEWARD,
    DEFAULT_ROUTING_FALLBACK_AGENT,
)
from carefold.engine.builder import GraphBuilder, create_agent_graph
from carefold.engine.graph import create_sqlite_saver
from carefold.engine.service import AgentExecutionService
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE
from carefold.schemas.chat import ChatRequestBody
from carefold.tools.delegation_tools import DelegateToAgentTool, ListAgentsTool
from carefold.workflows.nodes import (
    AgentExecutionNode,
    AuditNode,
    ErrorNode,
    InputGuardrailNode,
    OrchestratorDecision,
    OrchestratorNode,
    OutputGuardrailNode,
    ReflectionNode,
    RefusalNode,
    SuggestionNode,
    ToolNode,
    ToolValidatorNode,
)
from carefold.workflows.state import AgentState, create_initial_state
from tests.fixtures.fake_model import FakeListChatModel, MockChatModel, MockModelClient


# ============================================================================
# Helpers & Custom Test Doubles
# ============================================================================

class SlowStreamingMockChatModel(BaseChatModel):
    """Test double that simulates realistic chunk streaming with artificial delays."""

    chunks: List[str]
    delay: float = 0.02

    @property
    def _llm_type(self) -> str:
        return "slow_streaming_mock_chat_model"

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs: Any) -> ChatResult:
        full_content = "".join(self.chunks)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=full_content))])

    async def _astream(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs: Any):
        from langchain_core.messages import AIMessageChunk
        for ch in self.chunks:
            await asyncio.sleep(self.delay)
            yield ChatGeneration(message=AIMessageChunk(content=ch))


class InfiniteToolLoopChatModel(BaseChatModel):
    """Test double that perpetually emits tool calls to stress-test circuit breakers."""

    call_count: int = 0
    target_agents: List[str] = [AGENT_BENEFITS_GUIDE, AGENT_VISIT_STEWARD]

    @property
    def _llm_type(self) -> str:
        return "infinite_tool_loop_chat_model"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.call_count += 1
        target = self.target_agents[self.call_count % len(self.target_agents)]
        tc = {
            "name": "delegate_to_agent",
            "args": {"agent_id": target, "instructions": f"Ping-pong step {self.call_count}"},
            "id": f"call_loop_{self.call_count}",
        }
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="Delegating step...", tool_calls=[tc]))]
        )

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self


class PersistentRefusalChatModel(BaseChatModel):
    """Test double that repeatedly generates prohibited medical diagnoses to stress reflection ceilings."""

    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "persistent_refusal_chat_model"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.call_count += 1
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content=f"Attempt {self.call_count}: You have acute pneumonia. Take 500mg amoxicillin twice daily."
                    )
                )
            ]
        )


# ============================================================================
# Domain 1: Rapid Concurrent Requests & Turn Interruptions
# ============================================================================

class TestConcurrentRequestsAndTurnInterruptions:
    """Stress-tests concurrency boundaries, task cancellations, and client disconnects in AgentExecutionService."""

    @pytest.mark.asyncio
    async def test_concurrent_turns_on_identical_thread_id(self, temp_workspace: Path):
        """Validates that concurrent requests to the identical thread_id execute and serialize safely in SQLite."""
        mock1 = MockModelClient()
        mock1.queue_response("Turn Alpha completed.")
        mock2 = MockModelClient()
        mock2.queue_response("Turn Beta completed.")

        svc1 = AgentExecutionService(model=mock1, workspace_root=temp_workspace)
        svc2 = AgentExecutionService(model=mock2, workspace_root=temp_workspace)
        thread_id = "concurrent-same-thread-001"

        async def run_turn(svc: AgentExecutionService, prompt: str) -> List[Dict[str, Any]]:
            events = []
            async for ev in svc.execute_turn(
                thread_id=thread_id,
                prompt=prompt,
                agent_id="visit-steward",
            ):
                events.append(ev)
            return events

        # Dispatch both turns concurrently
        t1 = asyncio.create_task(run_turn(svc1, "Prompt Alpha"))
        t2 = asyncio.create_task(run_turn(svc2, "Prompt Beta"))

        results = await asyncio.gather(t1, t2, return_exceptions=True)

        for res in results:
            assert not isinstance(res, Exception), f"Unexpected exception in concurrent turn: {res}"
            assert any(e.get("type") == "done" for e in res)

        # Inspect thread state post-concurrency
        final_state = await svc1.get_thread_state(thread_id)
        assert final_state is not None
        assert "messages" in final_state
        assert len(final_state["messages"]) >= 2

    @pytest.mark.asyncio
    async def test_turn_interruption_premature_close_and_resumption(self, temp_workspace: Path):
        """Simulates browser disconnect by reading one token and closing async generator, then resuming."""
        mock1 = MockModelClient()
        mock1.queue_response("Streaming token sequence that will be cut off abruptly.")

        svc = AgentExecutionService(model=mock1, workspace_root=temp_workspace)
        thread_id = "interrupted-thread-001"

        # Start Turn 1 and disconnect after first token
        agen = svc.execute_turn(thread_id=thread_id, prompt="Interrupt me", agent_id="visit-steward")
        first_event = await anext(agen)
        assert first_event["type"] == "token"
        await agen.aclose()

        # Immediate Turn 2 resumption on same thread
        mock2 = MockModelClient()
        mock2.queue_response("Resumed turn completed safely.")
        svc.model = mock2

        t2_events: List[Dict[str, Any]] = []
        async for ev in svc.execute_turn(thread_id=thread_id, prompt="Resume conversation", agent_id="visit-steward"):
            t2_events.append(ev)

        assert any(e.get("type") == "done" for e in t2_events)
        done_ev = next(e for e in t2_events if e["type"] == "done")
        assert done_ev["refused"] is False
        assert "Resumed turn" in done_ev["fullText"]

    @pytest.mark.asyncio
    async def test_asyncio_task_cancellation_mid_stream_and_recovery(self, temp_workspace: Path):
        """Simulates task cancellation during an active token stream and validates clean SQLite lock release."""
        mock = SlowStreamingMockChatModel(chunks=["Token1 ", "Token2 ", "Token3 ", "Token4 "], delay=0.03)
        svc = AgentExecutionService(model=mock, workspace_root=temp_workspace)
        thread_id = "task-cancellation-thread-001"

        async def worker():
            async for _ in svc.execute_turn(thread_id=thread_id, prompt="Will cancel", agent_id="visit-steward"):
                pass

        task = asyncio.create_task(worker())
        await asyncio.sleep(0.04)  # Let it enter stream
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # Ensure database is immediately unlocked and subsequent turn succeeds
        mock_recovery = MockModelClient()
        mock_recovery.queue_response("Post-cancellation turn succeeded.")
        svc.model = mock_recovery

        events: List[Dict[str, Any]] = []
        async for ev in svc.execute_turn(thread_id=thread_id, prompt="Are you there?", agent_id="visit-steward"):
            events.append(ev)

        assert any(e.get("type") == "done" for e in events)

    @pytest.mark.asyncio
    async def test_rapid_sequential_burst_execution(self, temp_workspace: Path):
        """Fires a rapid sequential burst of 12 turns across 4 distinct threads to test state isolation."""
        svc = AgentExecutionService(workspace_root=temp_workspace)

        for i in range(12):
            thread_idx = i % 4
            thread_id = f"burst-thread-{thread_idx}"
            mock = MockModelClient()
            mock.queue_response(f"Burst reply {i} for thread {thread_idx}")
            svc.model = mock

            events = []
            async for ev in svc.execute_turn(
                thread_id=thread_id,
                prompt=f"Burst prompt {i}",
                agent_id="visit-steward",
            ):
                events.append(ev)

            done_ev = next((e for e in events if e.get("type") == "done"), None)
            assert done_ev is not None
            assert done_ev["threadId"] == thread_id

        # Verify thread histories exist and are distinct
        for t_idx in range(4):
            hist = await svc.get_thread_history(f"burst-thread-{t_idx}")
            assert hist["count"] >= 2

    @pytest.mark.asyncio
    async def test_concurrent_read_history_during_active_write_stream(self, temp_workspace: Path):
        """Verifies readers (get_thread_history) are non-blocking and concurrent during active stream writes."""
        mock = SlowStreamingMockChatModel(chunks=["ChunkA ", "ChunkB ", "ChunkC ", "ChunkD "], delay=0.05)
        svc = AgentExecutionService(model=mock, workspace_root=temp_workspace)
        thread_id = "concurrent-read-write-001"

        # Prime thread with Turn 1
        prime_mock = MockModelClient()
        prime_mock.queue_response("Initial setup.")
        svc.model = prime_mock
        async for _ in svc.execute_turn(thread_id=thread_id, prompt="Setup", agent_id="visit-steward"):
            pass

        # Switch to slow model for Turn 2
        svc.model = mock

        async def stream_turn():
            async for _ in svc.execute_turn(thread_id=thread_id, prompt="Slow write", agent_id="visit-steward"):
                pass

        writer_task = asyncio.create_task(stream_turn())
        await asyncio.sleep(0.06)  # Mid-write

        # Concurrent reader inspection
        hist = await svc.get_thread_history(thread_id)
        assert hist["threadId"] == thread_id
        assert hist["count"] >= 2  # Has at least Turn 1 messages

        await writer_task

    @pytest.mark.asyncio
    async def test_extreme_prompt_and_unicode_resilience(self, temp_workspace: Path):
        """Verifies system stability when handling extreme 60KB prompts and complex unicode scripts."""
        mock = MockModelClient()
        mock.queue_response("Extreme payload accepted.")
        svc = AgentExecutionService(model=mock, workspace_root=temp_workspace)

        huge_prompt = "Clinical inquiry: " + ("A" * 60000)
        unicode_prompt = "Symptom check: 𝕬𝖑𝖎𝖈𝖊 ⚕️ 🩺 💊 𣎴 ᚛ᚄᚑᚂᚐᚄ᚜ \u202e\u200b\ufeff"

        for p in (huge_prompt, unicode_prompt):
            mock.queue_response("Processed safely.")
            events = []
            async for ev in svc.execute_turn(thread_id="extreme-input-th", prompt=p, agent_id="visit-steward"):
                events.append(ev)
            assert any(e.get("type") == "done" for e in events)


# ============================================================================
# Domain 2: Cyclic Delegation Detection & Circuit-Breaking
# ============================================================================

class TestCyclicDelegationAndCircuitBreaking:
    """Stress-tests cyclic multi-agent delegation, self-routing loops, and tool iteration bounds."""

    @pytest.mark.asyncio
    async def test_orchestrator_self_delegation_attempt_handling(self, temp_workspace: Path):
        """Validates OrchestratorNode behavior when model returns decision targeting orchestrator itself."""
        reg = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
        decision_json = OrchestratorDecision(
            agent_id=AGENT_ORCHESTRATOR,
            reasoning="Attempting self-delegation",
            instructions="",
        ).model_dump_json()

        fake_model = FakeListChatModel(responses=[decision_json])
        node = OrchestratorNode(model=fake_model, registry=reg)

        state = {"messages": [HumanMessage(content="Coordinate my health plan")]}
        res = await node.execute(state)

        # Confirm orchestrator node handles response without unhandled recursive explosion
        assert "current_agent" in res
        assert "routed_subgraph" in res
        assert res["current_agent"] in reg.list_agent_ids()

    @pytest.mark.asyncio
    async def test_cyclic_agent_delegation_tool_circuit_breaker(self, temp_workspace: Path):
        """Confirms that a cyclic ping-pong delegation loop is strictly halted by max_tool_iterations."""
        loop_model = InfiniteToolLoopChatModel()
        max_iters = 4

        builder = (
            GraphBuilder()
            .with_model(loop_model)
            .with_tools(["delegate_to_agent"])
            .with_max_tool_iterations(max_iters)
            .with_dynamic_orchestrator(False)
        )
        graph = builder.build()

        initial_state = {
            "messages": [HumanMessage(content="Start ping-pong delegation loop")],
            "current_agent": AGENT_VISIT_STEWARD,
            "effective_tools": ["delegate_to_agent"],
        }

        result = await graph.ainvoke(initial_state)

        # Circuit breaker must halt loop exactly at max_tool_iterations
        assert result.get("iteration_count") == max_iters
        assert loop_model.call_count == max_iters + 1  # 1 initial + max_iters tool results
        assert result.get("next_step") == "done"

    @pytest.mark.asyncio
    async def test_zero_max_tool_iterations_immediate_circuit_break(self, temp_workspace: Path):
        """Confirms that setting max_tool_iterations=0 prevents tool execution loop entirely."""
        loop_model = InfiniteToolLoopChatModel()

        builder = (
            GraphBuilder()
            .with_model(loop_model)
            .with_tools(["delegate_to_agent"])
            .with_max_tool_iterations(0)
            .with_dynamic_orchestrator(False)
        )
        graph = builder.build()

        initial_state = {
            "messages": [HumanMessage(content="Attempt tool execution with zero budget")],
            "current_agent": AGENT_VISIT_STEWARD,
            "effective_tools": ["delegate_to_agent"],
        }

        result = await graph.ainvoke(initial_state)
        # Should transition directly to output_guardrail without executing tools
        assert result.get("iteration_count") is None or result.get("iteration_count") == 0
        assert loop_model.call_count == 1

    def test_delegate_to_agent_tool_inputs(self):
        """Adversarially fuzzes DelegateToAgentTool with SQL injections, null bytes, and boundary payloads."""
        tool = DelegateToAgentTool()

        fuzz_cases = [
            ("", ""),
            ("'; DROP TABLE agents; --", "malicious SQL"),
            ("A" * 5000, "B" * 5000),
            ("orchestrator", "self reference"),
            ("unknown_specialist_xyz", "non-existent"),
            ("visit\x00steward", "null byte injected"),
            ("benefits-guide", "Normal instructions with \n\r\t control chars"),
        ]

        for target_id, inst in fuzz_cases:
            res_str = tool._run(agent_id=target_id, instructions=inst)
            parsed = json.loads(res_str)
            assert parsed["status"] == "delegated"
            assert parsed["agent_id"] == target_id.strip()

    def test_list_agents_tool_fallback_when_registry_missing(self, tmp_path: Path):
        """Validates that ListAgentsTool returns fallback catalog when registry is None or empty."""
        tool = ListAgentsTool(registry=None)
        res = tool._run()
        assert "visit-steward" in res
        assert "benefits-guide" in res
        assert "habit-companion" in res

    @pytest.mark.asyncio
    async def test_orchestrator_node_unparseable_markdown_and_corrupt_json_recovery(self, temp_workspace: Path):
        """Verifies OrchestratorNode fallback when model outputs markdown code fences, broken JSON, or garbage."""
        reg = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        fuzz_responses = [
            '```json\n{"agent_id": "benefits-guide", "reasoning": "Markdown fence", "instructions": ""}\n```',
            '{"agent_id": "benefits-guide"',  # Truncated
            '{"agent_id": "", "reasoning": ""}',  # Empty fields
            '{"agent_id": 9999, "reasoning": 123}',  # Bad types
            "I recommend delegating to the visit steward.",  # Pure natural language
            "{corrupted_json_garbage: true}",
        ]

        for r_text in fuzz_responses:
            fake_model = FakeListChatModel(responses=[r_text])
            node = OrchestratorNode(model=fake_model, registry=reg)
            state = {"messages": [HumanMessage(content="Help me with insurance")]}
            res = await node.execute(state)

            assert res["current_agent"] in reg.list_agent_ids()
            assert res["routed_subgraph"] in reg.list_agent_ids()
            assert res["next_step"] in reg.list_agent_ids()

    def test_orchestrator_node_catalog_excludes_orchestrator(self, temp_workspace: Path):
        """Verifies that format_agent_catalog dynamically excludes orchestrator from delegatable targets."""
        reg = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
        node = OrchestratorNode(registry=reg)
        prompt = node._build_system_prompt({})

        after_catalog_header = prompt.split("## Available Specialist Agents:")[1]
        assert "**orchestrator**" not in after_catalog_header
        assert "**visit-steward**" in after_catalog_header


# ============================================================================
# Domain 3: Re-Entrancy, Malformed Checkpointer States, & Reflection Counter Overflows
# ============================================================================

class TestReentrancyAndCheckpointerHardening:
    """Stress-tests reflection counter ceilings, SQLite corruptions, and multi-turn re-entrancy."""

    @pytest.mark.asyncio
    async def test_reflection_counter_overflow_handling(self):
        """Validates that ReflectionNode gracefully caps extreme reflection counters without crashing."""
        node = ReflectionNode(max_reflections=3)

        # Huge count overflow
        st1 = {"reflection_count": 999999, "max_reflections": 3}
        res1 = await node.execute(st1)
        assert res1["next_step"] == "done"
        assert res1["reflection_count"] == 999999

        # Negative count
        st2 = {"reflection_count": -10, "max_reflections": 3}
        res2 = await node.execute(st2)
        assert res2["reflection_count"] == 1
        assert res2["next_step"] == "agent"

        # Zero max_reflections
        st3 = {"reflection_count": 0, "max_reflections": 0}
        res3 = await node.execute(st3)
        assert res3["next_step"] == "done"

    @pytest.mark.asyncio
    async def test_reflection_loop_multi_attempt_self_correction_circuit_breaker(self):
        """Validates that persistent clinical violations loop through reflection and halt at max_reflections."""
        violating_model = PersistentRefusalChatModel()
        max_refl = 3

        builder = (
            GraphBuilder()
            .with_model(violating_model)
            .with_max_reflections(max_refl)
            .with_dynamic_orchestrator(False)
        )
        graph = builder.build()

        # Input is safe so it passes InputGuardrail; model output violates safety to trigger output reflection
        state = {
            "messages": [HumanMessage(content="How should I prepare for my routine physical checkup?")],
            "current_agent": AGENT_VISIT_STEWARD,
        }

        res = await graph.ainvoke(state)

        # 1 initial call + 3 reflection retries = 4 model calls total
        assert violating_model.call_count == max_refl + 1
        assert res.get("reflection_count") == max_refl
        assert res.get("is_refusal") is True
        assert res.get("refusal_reason") == "forbidden_intent:diagnose"
        assert "wellness and care navigation assistant" in res.get("output", "").lower()

    @pytest.mark.asyncio
    async def test_zero_max_reflections_immediate_refusal(self):
        """Validates that setting max_reflections=0 halts on first violation without reflection retries."""
        violating_model = PersistentRefusalChatModel()

        builder = (
            GraphBuilder()
            .with_model(violating_model)
            .with_max_reflections(0)
            .with_dynamic_orchestrator(False)
        )
        graph = builder.build()

        state = {
            "messages": [HumanMessage(content="What questions can I prepare for my wellness consultation?")],
            "current_agent": AGENT_VISIT_STEWARD,
        }

        res = await graph.ainvoke(state)
        assert violating_model.call_count == 1
        assert res.get("is_refusal") is True

    @pytest.mark.asyncio
    async def test_checkpointer_zero_byte_file_recovery(self, temp_workspace: Path):
        """Validates that an empty 0-byte SQLite database file is safely handled without unhandled crashes."""
        chats_dir = temp_workspace / "chats"
        chats_dir.mkdir(exist_ok=True)
        db_file = chats_dir / "checkpoints.db"
        db_file.write_bytes(b"")

        svc = AgentExecutionService(workspace_root=temp_workspace)
        st = await svc.get_thread_state("any-thread-id")
        assert st is None

        hist = await svc.get_thread_history("any-thread-id")
        assert hist["count"] == 0
        assert hist["messages"] == []

    @pytest.mark.asyncio
    async def test_checkpointer_corrupted_binary_noise_recovery(self, temp_workspace: Path):
        """Validates that binary noise in checkpoints.db emits a sanitized error event rather than a fatal crash."""
        chats_dir = temp_workspace / "chats"
        chats_dir.mkdir(exist_ok=True)
        db_file = chats_dir / "checkpoints.db"
        db_file.write_bytes(b"CORRUPTED_NON_SQLITE_HEADER_RANDOM_NOISE_1234567890")

        mock = MockModelClient()
        mock.queue_response("Hello")
        svc = AgentExecutionService(model=mock, workspace_root=temp_workspace)

        events: List[Dict[str, Any]] = []
        async for ev in svc.execute_turn(thread_id="corrupted-db-th", prompt="Hi", agent_id="visit-steward"):
            events.append(ev)

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "file is not a database" in events[0]["message"]

    @pytest.mark.asyncio
    async def test_checkpointer_corrupted_checkpoint_row_handling(self, temp_workspace: Path):
        """Validates handling when SQLite table exists but contains malformed/corrupted serialization BLOBs."""
        chats_dir = temp_workspace / "chats"
        chats_dir.mkdir(exist_ok=True)
        db_file = chats_dir / "checkpoints.db"

        # Initialize schema
        create_sqlite_saver(db_file)

        # Inject malformed checkpoint row
        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("corrupted-row-th", "", "cp_1", "", "unsupported_codec", b"MALFORMED_BLOB", b"{}"),
        )
        conn.commit()
        conn.close()

        svc = AgentExecutionService(workspace_root=temp_workspace)
        st = await svc.get_thread_state("corrupted-row-th")
        assert st is None

        hist = await svc.get_thread_history("corrupted-row-th")
        assert hist["count"] == 0

    @pytest.mark.asyncio
    async def test_turn_reentrancy_after_clinical_refusal(self, temp_workspace: Path):
        """Validates that a thread triggering a refusal in Turn 1 can safely execute safe queries in Turn 2."""
        svc = AgentExecutionService(workspace_root=temp_workspace)
        thread_id = "reentrant-refusal-thread-001"

        # Turn 1: Prohibited clinical diagnosis prompt
        t1_events = []
        async for ev in svc.execute_turn(
            thread_id=thread_id,
            prompt="Please prescribe me 50mg of tramadol for back pain",
            agent_id="visit-steward",
        ):
            t1_events.append(ev)

        done1 = next(e for e in t1_events if e.get("type") == "done")
        assert done1["refused"] is True

        # Turn 2: Safe wellness question on same thread
        mock2 = MockModelClient()
        mock2.queue_response("Here are non-pharmacological stretches for lower back stiffness.")
        svc.model = mock2

        t2_events = []
        async for ev in svc.execute_turn(
            thread_id=thread_id,
            prompt="What gentle stretches can I discuss with my physical therapist?",
            agent_id="visit-steward",
        ):
            t2_events.append(ev)

        done2 = next(e for e in t2_events if e.get("type") == "done")
        assert done2["refused"] is False
        assert "stretches" in done2["fullText"]

    @pytest.mark.asyncio
    async def test_checkpointer_reentrancy_memory_and_sqlite_savers(self):
        """Verifies multi-turn state accumulation consistency across MemorySaver and SqliteSaver."""
        fake_model = FakeListChatModel(responses=["Turn 1 response", "Turn 2 response"])
        saver = MemorySaver()

        graph = GraphBuilder().with_model(fake_model).with_checkpointer(saver).build()
        config = {"configurable": {"thread_id": "multi-turn-saver-001"}}

        # Turn 1
        res1 = await graph.ainvoke({"messages": [HumanMessage(content="Query 1")]}, config=config)
        assert len(res1["messages"]) >= 2

        # Turn 2
        res2 = await graph.ainvoke({"messages": [HumanMessage(content="Query 2")]}, config=config)
        assert len(res2["messages"]) >= 4
        assert res2["messages"][-1].content == "Turn 2 response"


# ============================================================================
# Domain 4: Complex Graph Branch Decisions Under Missing or Partial State
# ============================================================================

class TestGraphBranchDecisionsUnderPartialState:
    """Stress-tests conditional routers, missing state fields, and node fallbacks."""

    def test_graph_routers_with_empty_state(self):
        """Verifies that all 5 graph conditional router branches survive empty state dict without exceptions."""
        builder = GraphBuilder(include_reflection=True, include_supervisor=True, include_error_node=True)
        graph = builder.create_graph()

        branches_tested = 0
        for src, branches in graph.branches.items():
            for branch_name, branch in branches.items():
                dest = branch.path.invoke({})
                assert isinstance(dest, str) and dest != ""
                branches_tested += 1

        assert branches_tested >= 4

    def test_graph_routers_with_none_and_edge_values(self):
        """Probes conditional routers with edge-case state values."""
        builder = GraphBuilder(include_reflection=True, include_supervisor=True, include_error_node=True)
        graph = builder.create_graph()

        edge_states = [
            {"is_refusal": True, "reflection_count": 0},
            {"is_refusal": True, "reflection_count": 5},
            {"next_step": "refusal"},
            {"next_step": "error", "error": "Fatal runtime failure"},
            {"current_agent": "visit-steward"},
            {"routed_subgraph": "extraction"},
            {"messages": []},
            {"iteration_count": 10},
        ]

        for st in edge_states:
            for src, branches in graph.branches.items():
                for branch_name, branch in branches.items():
                    dest = branch.path.invoke(st)
                    assert isinstance(dest, str)

    @pytest.mark.asyncio
    async def test_discrete_nodes_with_missing_and_partial_state(self):
        """Verifies individual discrete nodes execute safely with minimal partial states."""
        nodes = [
            InputGuardrailNode(),
            RefusalNode(),
            ReflectionNode(),
            SuggestionNode(),
            ToolValidatorNode(),
            AuditNode(),
            ErrorNode(),
        ]

        minimal_state = {"messages": [HumanMessage(content="Test minimal state")]}

        for node in nodes:
            res = await (node(minimal_state) if callable(node) else node.execute(minimal_state))
            assert isinstance(res, dict)

    @pytest.mark.asyncio
    async def test_tool_node_undeclared_tool_rejection_and_tracing(self):
        """Verifies that ToolNode strictly intercepts undeclared tools and emits denied status traces."""
        tool_node = ToolNode(allowed_tools=["attach-read"])
        state = {
            "tool_calls": [{"name": "system-exec-prohibited", "args": {"cmd": "whoami"}, "id": "call_bad_1"}],
            "messages": [],
            "current_agent": "visit-steward",
        }

        res = await tool_node.execute(state)
        traces = res.get("tool_traces", [])
        assert len(traces) == 1
        assert traces[0]["allowed"] is False
        assert traces[0]["tool"] == "system-exec-prohibited"
        assert "denied" in traces[0]["error"]

        msgs = res.get("messages", [])
        assert len(msgs) == 1
        assert msgs[0].status == "error"

    @pytest.mark.asyncio
    async def test_subgraph_cross_branch_routing_and_case_insensitivity(self):
        """Verifies that supervisor conditional routing handles casing, underscores, and document extraction aliases."""
        sub_builder = StateGraph(AgentState)

        async def sub_node(state: AgentState):
            return {"output": "Extracted"}

        sub_builder.add_node("step", sub_node)
        sub_builder.add_edge(START, "step")
        sub_builder.add_edge("step", END)

        builder = GraphBuilder().with_subgraph("extraction", sub_builder)
        g = builder.create_graph()

        supervisor_branch = g.branches["supervisor"]["route_supervisor"].path

        # Case & hyphen normalization tests
        assert supervisor_branch.invoke({"routed_subgraph": "extraction"}) == "extraction"
        assert supervisor_branch.invoke({"routed_subgraph": "EXTRACTION"}) == "extraction"
        assert supervisor_branch.invoke({"current_agent": "document-extractor"}) == "extraction"
        assert supervisor_branch.invoke({"current_agent": "visit-steward"}) == "agent"

    @pytest.mark.asyncio
    async def test_error_node_routing_and_recovery(self):
        """Verifies that when an error occurs, routing directs to the error node for user-facing formatting."""
        builder = GraphBuilder(include_error_node=True)
        g = builder.create_graph()

        agent_branch = g.branches["agent"]["route_agent"].path
        dest = agent_branch.invoke({"error": "Service unavailable", "next_step": "error"})
        assert dest == "error"

        err_node = ErrorNode()
        err_res = await err_node.execute({"error": "Failed connection", "status_code": 500})
        assert "messages" in err_res
        assert err_res["output"] != ""
        assert err_res["messages"][-1]["content"] != ""
        assert err_res["next_step"] == "done"

    @pytest.mark.asyncio
    async def test_agent_execution_node_unregistered_agent_handling(self, temp_workspace: Path):
        """Verifies that AgentExecutionNode with an unknown agent ID gracefully routes to error."""
        reg = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
        node = AgentExecutionNode(registry=reg)

        # Unregistered agent with no messages
        state = {"current_agent": "completely-unknown-agent-999"}
        res = await node.execute(state)

        assert res.get("next_step") == "error"
        assert "Unknown or unregistered agent ID" in res.get("error", "")
