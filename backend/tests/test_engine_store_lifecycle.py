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

"""Unit and lifecycle integration test suite for LangGraph BaseStore memory lifecycle.

Tests Requirement R3 and Milestone M3:
- Graph compilation with InMemoryStore and SpectorStore
- Phase 1 context recall populating recalled_memories, memory_context, and system_prompt
- Phase 5 turn persistence writing episodic turn records to ("memories", thread_id)
- Multi-turn conversational recall across successive turns within the same thread
- Multi-tenant thread isolation preventing cross-thread memory leakage
- Backward compatibility and graceful degradation when store is None or errors occur
- Emergency red-flag gate priority bypassing recall on acute symptoms
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.base import BaseStore, SearchItem
from langgraph.store.memory import InMemoryStore

from carefold.engine.builder import GraphBuilder, create_agent_graph
from carefold.engine.service import AgentExecutionService
from carefold.memory.adapters.spector.store import SpectorStore
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE
from carefold.workflows.nodes import InputGuardrailNode, ResponseSynthesizerNode
from carefold.workflows.state import AgentState, create_initial_state
from tests.fixtures.fake_model import FakeListChatModel
try:
    from tests.test_spector_store_adapter import SimulatedAsyncMemoryClient
except ImportError:
    from test_spector_store_adapter import SimulatedAsyncMemoryClient


# ============================================================================
# Test Doubles & Error Fixtures (Confined to backend/tests per Zero-Mock policy)
# ============================================================================

class FailingStore(BaseStore):
    """Test double that simulates network transport timeouts and store failures."""

    supports_ttl: bool = False

    def __init__(self, fail_search: bool = True, fail_put: bool = True) -> None:
        self.fail_search = fail_search
        self.fail_put = fail_put

    async def abatch(self, ops):
        from langgraph.store.base import GetOp, PutOp, SearchOp
        for op in ops:
            if isinstance(op, SearchOp) and self.fail_search:
                raise TimeoutError("Simulated search timeout to memory server")
            if isinstance(op, PutOp) and self.fail_put:
                raise ConnectionError("Simulated put connection failure")
        return [None for _ in ops]

    def batch(self, ops):
        raise NotImplementedError("Use async abatch.")


class SpyStore(InMemoryStore):
    """Test double recording search and put operation counts."""

    def __init__(self) -> None:
        super().__init__()
        self.search_calls: int = 0
        self.put_calls: int = 0

    async def asearch(self, *args, **kwargs):
        self.search_calls += 1
        return await super().asearch(*args, **kwargs)

    async def aput(self, *args, **kwargs):
        self.put_calls += 1
        return await super().aput(*args, **kwargs)


# ============================================================================
# 1. Graph Compilation & Store Binding Tests
# ============================================================================

class TestEngineStoreCompilation:
    """Verifies StateGraph compilation with BaseStore variants and backward compatibility."""

    def test_graph_builder_with_in_memory_store_compilation(self):
        """Verifies GraphBuilder compiles cleanly with an InMemoryStore."""
        fake_model = FakeListChatModel(responses=["Acknowledged"])
        store = InMemoryStore()
        builder = (
            GraphBuilder()
            .with_model(fake_model)
            .with_store(store)
        )
        assert builder.store is store

        compiled_graph = builder.build()
        assert compiled_graph is not None
        assert builder.inspect_graph()["store"] == "InMemoryStore"

    def test_graph_builder_with_spector_store_compilation(self):
        """Verifies GraphBuilder compiles cleanly with a SpectorStore instance."""
        fake_model = FakeListChatModel(responses=["Acknowledged"])
        client = SimulatedAsyncMemoryClient()
        store = SpectorStore(client=client)

        builder = (
            GraphBuilder()
            .with_model(fake_model)
            .with_store(store)
        )
        assert builder.store is store

        compiled_graph = builder.build()
        assert compiled_graph is not None
        assert builder.inspect_graph()["store"] == "SpectorStore"

    def test_create_agent_graph_convenience_store_forwarding(self):
        """Verifies standalone create_agent_graph accepts and binds store."""
        fake_model = FakeListChatModel(responses=["Acknowledged"])
        store = InMemoryStore()

        compiled_graph = create_agent_graph(
            model=fake_model,
            store=store,
        )
        assert compiled_graph is not None

    def test_backward_compatibility_compilation_without_store(self):
        """Verifies GraphBuilder and create_agent_graph compile with store=None."""
        fake_model = FakeListChatModel(responses=["Acknowledged"])

        builder = GraphBuilder().with_model(fake_model)
        assert builder.store is None
        compiled_from_builder = builder.build()
        assert compiled_from_builder is not None
        assert builder.inspect_graph()["store"] is None

        compiled_from_fn = create_agent_graph(model=fake_model)
        assert compiled_from_fn is not None


# ============================================================================
# 2. Phase 1 Context Recall Unit Tests (InputGuardrailNode)
# ============================================================================

class TestPhase1ContextRecall:
    """Unit tests for InputGuardrailNode Phase 1 context recall behavior."""

    @pytest.mark.asyncio
    async def test_recall_populates_state_from_existing_store_entries(self):
        """Verifies that pre-existing memory records in store are recalled and formatted into state."""
        store = InMemoryStore()
        thread_id = "test_thread_recall_001"

        # Pre-seed episodic turn memory
        now_iso = datetime.now(timezone.utc).isoformat()
        seed_turn = {
            "user_query": "I take 20mg Lisinopril for high blood pressure.",
            "agent_response": "Lisinopril is an ACE inhibitor. Ensure regular BP checks.",
            "tier": "EPISODIC",
            "timestamp": now_iso,
            "text": "User: I take 20mg Lisinopril for high blood pressure.\nCarefold: Lisinopril is an ACE inhibitor.",
        }
        await store.aput(("memories", thread_id), "turn_1000", seed_turn)

        node = InputGuardrailNode()
        state = create_initial_state(
            thread_id=thread_id,
            prompt="Are there any cough side effects with my medication?",
            system_prompt="You are a clinical care navigator.",
        )

        result = await node.execute(state, store=store)

        assert result["is_refusal"] is False
        assert result["refused"] is False
        assert len(result["recalled_memories"]) == 1
        recalled = result["recalled_memories"][0]
        assert recalled["key"] == "turn_1000"
        assert recalled["value"]["user_query"] == seed_turn["user_query"]

        assert "memory_context" in result
        assert "Lisinopril" in result["memory_context"]
        assert "Relevant Patient Context" in result["memory_context"]

        # Verify system_prompt was enriched with memory context
        assert "system_prompt" in result
        assert "You are a clinical care navigator." in result["system_prompt"]
        assert "Relevant Patient Context" in result["system_prompt"]

    @pytest.mark.asyncio
    async def test_recall_graceful_degradation_when_store_is_none(self):
        """Verifies InputGuardrailNode operates cleanly when store is None."""
        node = InputGuardrailNode()
        state = create_initial_state(
            thread_id="thread_no_store",
            prompt="What is normal resting heart rate?",
            system_prompt="Standard persona prompt.",
        )

        result = await node.execute(state, store=None)

        assert result["is_refusal"] is False
        assert result["refused"] is False
        assert result["recalled_memories"] == []
        assert "memory_context" not in result or result.get("memory_context") is None
        assert result.get("system_prompt") == "Standard persona prompt."

    @pytest.mark.asyncio
    async def test_recall_graceful_degradation_on_store_exception(self):
        """Verifies InputGuardrailNode catches store search exceptions without crashing."""
        failing_store = FailingStore(fail_search=True)
        node = InputGuardrailNode()
        state = create_initial_state(
            thread_id="thread_fail_store",
            prompt="Tell me about diet for hypertension.",
        )

        result = await node.execute(state, store=failing_store)

        # Must not raise, must not refuse, must return empty recalled_memories
        assert result["is_refusal"] is False
        assert result["refused"] is False
        assert result["recalled_memories"] == []
        assert result["next_step"] == "supervisor"

    @pytest.mark.asyncio
    async def test_recall_bypassed_on_acute_emergency_red_flag(self):
        """Verifies acute life-threatening emergency bypasses memory recall and immediately diverts to 911."""
        store = InMemoryStore()
        thread_id = "thread_emergency"
        await store.aput(("memories", thread_id), "turn_1", {"text": "Patient has stable angina history"})

        node = InputGuardrailNode()
        state = create_initial_state(
            thread_id=thread_id,
            prompt="I am having crushing chest pain radiating to my left arm right now!",
        )

        result = await node.execute(state, store=store)

        assert result["is_refusal"] is True
        assert result["refused"] is True
        assert result["next_step"] == "refusal"
        assert result["recalled_memories"] == []
        assert "EMERGENCY WARNING" in result["refusal_message"]

    @pytest.mark.asyncio
    async def test_recall_bypassed_on_suicidal_ideation_crisis(self):
        """Verifies active suicidal ideation halts in InputGuardrailNode with 0 store calls and 988 referral."""
        store = SpyStore()
        thread_id = "thread_suicide_crisis"
        await store.aput(("memories", thread_id), "turn_1", {"text": "Patient has depression history"})

        # Reset count after seeding episodic state
        store.search_calls = 0

        node = InputGuardrailNode()
        state = create_initial_state(
            thread_id=thread_id,
            prompt="I want to end my life right now, I have pills and I am feeling suicidal",
        )

        result = await node.execute(state, store=store)

        assert result["is_refusal"] is True
        assert result["refused"] is True
        assert result["next_step"] == "refusal"
        assert result["recalled_memories"] == []
        assert store.search_calls == 0
        assert "988" in result["refusal_message"]
        assert "EMERGENCY WARNING" in result["refusal_message"]
        assert result["safety_metadata"]["category"] == "suicide_crisis"
        assert result["emergency_red_flags"]["category"] == "suicide_crisis"


# ============================================================================
# 3. Phase 5 Turn Persistence Unit Tests (ResponseSynthesizerNode)
# ============================================================================

class TestPhase5TurnPersistence:
    """Unit tests for ResponseSynthesizerNode Phase 5 turn persistence behavior."""

    @pytest.mark.asyncio
    async def test_turn_persistence_stores_episodic_record(self):
        """Verifies ResponseSynthesizerNode persists completed turn into BaseStore."""
        store = InMemoryStore()
        thread_id = "thread_synth_persist_001"
        node = ResponseSynthesizerNode()

        state = create_initial_state(
            thread_id=thread_id,
            prompt="What should I ask my cardiologist at my visit?",
            specialist_outputs={
                "cardiology-guide": "Ask about target heart rate and exercise tolerance.",
            },
        )

        result = await node.execute(state, store=store)

        assert "output" in result
        assert "Ask about target heart rate" in result["output"]

        # Verify entry was written to store under ("memories", thread_id)
        records = await store.asearch(("memories", thread_id))
        assert len(records) == 1
        stored = records[0]
        assert stored.key.startswith("turn_")
        assert stored.value["user_query"] == "What should I ask my cardiologist at my visit?"
        assert stored.value["tier"] == "EPISODIC"
        assert "Ask about target heart rate" in stored.value["agent_response"]
        assert stored.value["metadata"]["thread_id"] == thread_id

    @pytest.mark.asyncio
    async def test_turn_persistence_graceful_degradation_when_store_is_none(self):
        """Verifies ResponseSynthesizerNode operates without store."""
        node = ResponseSynthesizerNode()
        state = create_initial_state(
            thread_id="thread_synth_none",
            prompt="Hello there",
            output="How can I help you navigate your healthcare today?",
        )

        result = await node.execute(state, store=None)
        assert "output" in result
        assert result["next_step"] == "output_guardrail"

    @pytest.mark.asyncio
    async def test_turn_persistence_graceful_degradation_on_put_exception(self):
        """Verifies ResponseSynthesizerNode catches store write exceptions without crashing."""
        failing_store = FailingStore(fail_put=True)
        node = ResponseSynthesizerNode()
        state = create_initial_state(
            thread_id="thread_synth_fail",
            prompt="Test prompt",
            output="Test response",
        )

        result = await node.execute(state, store=failing_store)
        # Must finish cleanly
        assert "output" in result
        assert result["next_step"] == "output_guardrail"


# ============================================================================
# 4. End-to-End Multi-Turn Workflow Tests
# ============================================================================

class TestEngineStoreLifecycleEndToEnd:
    """Integration tests running full graph execution across multiple conversation turns."""

    @pytest.mark.asyncio
    async def test_e2e_multiturn_interaction_with_in_memory_store(self):
        """Verifies multi-turn conversation: Turn 1 stores memory, Turn 2 recalls Turn 1."""
        store = InMemoryStore()
        saver = MemorySaver()
        thread_id = "th_e2e_multiturn_001"

        fake_model = FakeListChatModel(
            responses=[
                "Metoprolol succinate is prescribed for heart rate control.",
                "Common side effects of metoprolol include dizziness and fatigue.",
            ]
        )

        builder = (
            GraphBuilder()
            .with_model(fake_model)
            .with_checkpointer(saver)
            .with_store(store)
            .with_dynamic_orchestrator(False)
            .with_system_prompt("You are a helpful clinical guide.")
        )
        app = builder.build()

        # Turn 1
        config = {"configurable": {"thread_id": thread_id}}
        input_turn1 = create_initial_state(
            thread_id=thread_id,
            prompt="I was recently prescribed metoprolol succinate 25mg.",
        )
        res_turn1 = await app.ainvoke(input_turn1, config=config)
        assert res_turn1["refused"] is False
        assert "Metoprolol succinate" in res_turn1["output"]

        # Verify Turn 1 was persisted in store
        turn1_records = await store.asearch(("memories", thread_id))
        assert len(turn1_records) == 1
        assert "metoprolol" in turn1_records[0].value["user_query"].lower()

        # Turn 2: Query refers back to Turn 1's prescription
        input_turn2 = {
            "messages": [HumanMessage(content="What are the common side effects of that medicine?")],
            "prompt": "What are the common side effects of that medicine?",
            "thread_id": thread_id,
        }
        res_turn2 = await app.ainvoke(input_turn2, config=config)

        # Verify Turn 2 recalled Turn 1 context
        assert len(res_turn2.get("recalled_memories", [])) >= 1
        memory_ctx = res_turn2.get("memory_context", "")
        assert "metoprolol" in memory_ctx.lower()

        # Verify Turn 2 also persisted into store
        turn2_records = await store.asearch(("memories", thread_id))
        assert len(turn2_records) == 2

    @pytest.mark.asyncio
    async def test_e2e_multiturn_interaction_with_spector_store(self):
        """Verifies bi-directional persistence and cognitive recall with SpectorStore test double."""
        client = SimulatedAsyncMemoryClient()
        store = SpectorStore(client=client)
        saver = MemorySaver()
        thread_id = "th_spector_e2e_001"

        fake_model = FakeListChatModel(
            responses=[
                "For asthma symptoms, keep your albuterol rescue inhaler readily accessible.",
                "If using your rescue inhaler more than twice weekly, review asthma control.",
            ]
        )

        builder = (
            GraphBuilder()
            .with_model(fake_model)
            .with_checkpointer(saver)
            .with_store(store)
            .with_dynamic_orchestrator(False)
        )
        app = builder.build()

        config = {"configurable": {"thread_id": thread_id}}

        # Turn 1
        t1_input = create_initial_state(
            thread_id=thread_id,
            prompt="I experience wheezing when jogging outdoors in cold air.",
        )
        t1_res = await app.ainvoke(t1_input, config=config)
        assert t1_res["refused"] is False

        # Verify persisted into Spector client
        assert len(client.records) >= 1

        # Turn 2: Query mentions rescue inhaler
        t2_input = {
            "messages": [HumanMessage(content="How often can I use the rescue inhaler?")],
            "prompt": "How often can I use the rescue inhaler?",
            "thread_id": thread_id,
        }
        t2_res = await app.ainvoke(t2_input, config=config)

        assert t2_res["refused"] is False
        assert len(t2_res.get("recalled_memories", [])) >= 1
        assert "wheezing" in str(t2_res.get("recalled_memories")).lower()

    @pytest.mark.asyncio
    async def test_thread_isolation_between_sessions(self):
        """Verifies memories persisted in thread_A do not leak into thread_B queries."""
        store = InMemoryStore()
        saver = MemorySaver()

        fake_model = FakeListChatModel(
            responses=[
                "Managing diabetes involves monitoring A1C levels.",
                "Welcome! How can I assist you with your health questions today?",
            ]
        )

        builder = (
            GraphBuilder()
            .with_model(fake_model)
            .with_checkpointer(saver)
            .with_store(store)
            .with_dynamic_orchestrator(False)
        )
        app = builder.build()

        # Turn on Thread A: Mentions diabetes
        config_a = {"configurable": {"thread_id": "thread_patient_A"}}
        res_a = await app.ainvoke(
            create_initial_state(thread_id="thread_patient_A", prompt="I was diagnosed with type 2 diabetes."),
            config=config_a,
        )
        assert res_a["refused"] is False

        # Turn on Thread B: Patient B asks general question
        config_b = {"configurable": {"thread_id": "thread_patient_B"}}
        res_b = await app.ainvoke(
            create_initial_state(thread_id="thread_patient_B", prompt="Hello, I have a general question."),
            config=config_b,
        )
        assert res_b["refused"] is False

        # Thread B must have zero recalled memories (no leakage from Thread A)
        assert res_b.get("recalled_memories") == []
        assert res_b.get("memory_context") is None

    @pytest.mark.asyncio
    async def test_e2e_execution_with_store_none_backward_compatibility(self):
        """Verifies full execution graph runs cleanly when compiled without a store."""
        saver = MemorySaver()
        fake_model = FakeListChatModel(responses=["General wellness advice without memory store."])

        builder = (
            GraphBuilder()
            .with_model(fake_model)
            .with_checkpointer(saver)
            .with_dynamic_orchestrator(False)
        )
        # compile with store=None
        app = builder.build(store=None)

        config = {"configurable": {"thread_id": "thread_backward_compat"}}
        res = await app.ainvoke(
            create_initial_state(
                thread_id="thread_backward_compat",
                prompt="How much water should I drink daily?",
            ),
            config=config,
        )

        assert res["refused"] is False
        assert "General wellness advice" in res["output"]
        assert res.get("recalled_memories") == []
        assert res.get("memory_context") is None


# ============================================================================
# 5. AgentExecutionService Streaming Lifecycle Tests
# ============================================================================

class TestAgentExecutionServiceStoreIntegration:
    """Verifies AgentExecutionService turn streaming with store injection."""

    @pytest.mark.asyncio
    async def test_service_execute_turn_persists_interaction_to_store(self, tmp_path: Path):
        """Verifies execute_turn streams events and commits completed turn to attached store."""
        store = InMemoryStore()
        fake_model = FakeListChatModel(responses=["Take care of your health by walking 30 minutes daily."])

        service = AgentExecutionService(
            model=fake_model,
            workspace_root=tmp_path,
            store=store,
        )

        thread_id = "th_service_stream_001"
        events = []

        async for ev in service.execute_turn(
            thread_id=thread_id,
            prompt="What is a good introductory exercise routine?",
        ):
            events.append(ev)

        types = [e.get("type") for e in events]
        assert "done" in types

        # Check that turn was committed into store
        records = await store.asearch(("memories", thread_id))
        assert len(records) == 1
        assert "introductory exercise" in records[0].value["user_query"].lower()
