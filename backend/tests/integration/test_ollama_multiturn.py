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

"""On-demand real LLM multi-turn integration test suite targeting local Ollama.

Validates Requirement R5 and Milestone M5:
- Local Ollama daemon health check probe and graceful skip
- Live multi-turn conversation execution via compiled LangGraph and AgentExecutionService
- Phase 1 Context Recall (InputGuardrailNode) retrieving prior turn from BaseStore
- Phase 5 Turn Persistence (ResponseSynthesizerNode) committing episodic turns
- Memory recall across successive turns within the same thread (Sarah, Type 2 Diabetes, Metformin 500mg)
- Multi-turn state verification asserting both turns exist in ("memories", thread_id)
- Strict CI isolation: skipped by default unless CAREFOLD_RUN_OLLAMA_TESTS=1
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import uuid

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from carefold.engine.builder import GraphBuilder
from carefold.engine.service import AgentExecutionService
from carefold.memory.adapters.spector.store import SpectorStore
from carefold.model.factory import create_chat_model
from carefold.workflows.state import create_initial_state


# ============================================================================
# Test Suite Isolation & Daemon Probing Helpers
# ============================================================================

def probe_ollama_daemon(base_url: str = "http://localhost:11434") -> bool:
    """Probes whether the local Ollama daemon is accessible and responding."""
    import httpx
    clean_url = base_url.removesuffix("/v1").removesuffix("/")
    try:
        with httpx.Client(timeout=2.0) as client:
            res = client.get(f"{clean_url}/api/tags")
            return res.status_code == 200
    except Exception:
        return False


def get_ollama_test_config() -> Dict[str, str]:
    """Retrieves configured or default Ollama parameters for integration testing."""
    return {
        "base_url": os.getenv("CAREFOLD_OLLAMA_URL", "http://localhost:11434"),
        "model": os.getenv("CAREFOLD_OLLAMA_MODEL", "llama3.2:3b"),
    }


pytestmark = [
    pytest.mark.skipif(
        not os.getenv("CAREFOLD_RUN_OLLAMA_TESTS"),
        reason="Live Ollama tests run on-demand only (set CAREFOLD_RUN_OLLAMA_TESTS=1)",
    ),
    pytest.mark.ollama,
]


@pytest.fixture(autouse=True)
def ensure_ollama_daemon_available():
    """Probes local Ollama daemon before each test; skips if daemon is not running."""
    cfg = get_ollama_test_config()
    if not probe_ollama_daemon(cfg["base_url"]):
        pytest.skip(f"Local Ollama daemon not running at {cfg['base_url']}")


# ============================================================================
# 1. Connectivity & Model Availability Probe
# ============================================================================

class TestOllamaDaemonConnectivity:
    """Verifies local Ollama daemon reachability and model availability."""

    def test_ollama_daemon_responds_and_lists_models(self):
        """Verifies Ollama endpoint responds with HTTP 200 and provides available models."""
        import httpx
        cfg = get_ollama_test_config()
        clean_url = cfg["base_url"].removesuffix("/v1").removesuffix("/")
        with httpx.Client(timeout=3.0) as client:
            res = client.get(f"{clean_url}/api/tags")
            assert res.status_code == 200
            data = res.json()
            assert "models" in data
            model_names = [m.get("name") for m in data.get("models", [])]
            # Ensure either configured model or a llama3.2 variant is present
            target_model = cfg["model"]
            has_matching = any(
                target_model in name or "llama3.2" in name
                for name in model_names
            )
            assert has_matching, f"Model '{target_model}' not found in Ollama models: {model_names}"

    def test_live_chat_model_instantiation(self):
        """Verifies create_chat_model returns an active BaseChatModel targeting Ollama."""
        cfg = get_ollama_test_config()
        model = create_chat_model(
            provider="ollama",
            model=cfg["model"],
            base_url=cfg["base_url"],
            temperature=0.0,
        )
        assert model is not None
        assert hasattr(model, "ainvoke")


# ============================================================================
# 2. Multi-Turn Conversational Scenario via Compiled Graph
# ============================================================================

class TestOllamaMultiTurnGraphWorkflow:
    """Verifies multi-turn conversation and memory recall across turns via GraphBuilder."""

    @pytest.mark.asyncio
    async def test_multiturn_sarah_diabetes_recall_workflow(self):
        """Executes a 2-turn dialogue with real Ollama:
        Turn 1: Sarah introduces name, age (45), Type 2 Diabetes, and Metformin 500mg.
                -> Stored in episodic memory store.
        Turn 2: Asks 'What medication and dosage did I mention I am taking?'
                -> Recalled via Phase 1 context recall.
                -> Real LLM explicitly generates response referencing Metformin 500mg.
        """
        cfg = get_ollama_test_config()
        store = InMemoryStore()
        checkpointer = MemorySaver()
        thread_id = f"th_ollama_graph_{uuid.uuid4().hex[:8]}"

        model = create_chat_model(
            provider="ollama",
            model=cfg["model"],
            base_url=cfg["base_url"],
            temperature=0.0,
        )

        builder = (
            GraphBuilder()
            .with_model(model)
            .with_checkpointer(checkpointer)
            .with_store(store)
            .with_dynamic_orchestrator(False)
            .with_system_prompt("You are a helpful clinical navigation assistant.")
        )
        app = builder.build()
        config = {"configurable": {"thread_id": thread_id}}

        # --------------------------------------------------------------------
        # Turn 1: Patient Introduction & Medication Disclosure
        # --------------------------------------------------------------------
        turn1_prompt = (
            "Hello, I am Sarah, 45 years old, recently diagnosed with Type 2 Diabetes. "
            "I am currently taking Metformin 500mg."
        )
        turn1_input = create_initial_state(
            thread_id=thread_id,
            prompt=turn1_prompt,
        )
        turn1_result = await app.ainvoke(turn1_input, config=config)

        # Assert Turn 1 completed without safety refusal
        assert turn1_result.get("refused") is False
        turn1_output = turn1_result.get("output", "")
        assert isinstance(turn1_output, str)
        assert len(turn1_output.strip()) > 0

        # Assert Turn 1 was committed to episodic memory store
        turn1_records = await store.asearch(("memories", thread_id))
        assert len(turn1_records) == 1
        stored_turn1 = turn1_records[0]
        assert stored_turn1.key.startswith("turn_")
        stored_val = stored_turn1.value
        assert "Sarah" in stored_val["user_query"]
        assert "Metformin 500mg" in stored_val["user_query"]
        assert stored_val["tier"] == "EPISODIC"

        # --------------------------------------------------------------------
        # Turn 2: Follow-Up Query Relying Strictly on Recall
        # --------------------------------------------------------------------
        turn2_prompt = "What medication and dosage did I mention I am taking?"
        turn2_input = {
            "messages": [HumanMessage(content=turn2_prompt)],
            "prompt": turn2_prompt,
            "thread_id": thread_id,
        }
        turn2_result = await app.ainvoke(turn2_input, config=config)

        # Assert Turn 2 Phase 1 Context Recall populated recalled_memories and memory_context
        recalled = turn2_result.get("recalled_memories", [])
        assert len(recalled) >= 1, "Phase 1 context recall failed to retrieve prior turn"
        memory_ctx = turn2_result.get("memory_context", "")
        assert memory_ctx is not None
        assert "metformin" in memory_ctx.lower()
        assert "500" in memory_ctx

        # Assert assistant's generated response correctly mentions Metformin and 500mg
        turn2_output = turn2_result.get("output", "")
        assert isinstance(turn2_output, str)
        lower_output = turn2_output.lower()
        assert "metformin" in lower_output, f"Turn 2 did not mention Metformin: {turn2_output}"
        assert "500" in lower_output, f"Turn 2 did not mention 500mg dosage: {turn2_output}"

        # --------------------------------------------------------------------
        # Multi-Turn State Verification: Direct Query to BaseStore
        # --------------------------------------------------------------------
        all_records = await store.asearch(("memories", thread_id))
        assert len(all_records) == 2, f"Expected 2 stored turns, found {len(all_records)}"
        query_texts = [r.value.get("user_query", "") for r in all_records]
        assert any("Sarah" in q for q in query_texts)
        assert any("medication and dosage" in q for q in query_texts)


# ============================================================================
# 3. Multi-Turn Streaming Scenario via AgentExecutionService
# ============================================================================

class TestOllamaMultiTurnExecutionService:
    """Verifies multi-turn streaming execution through AgentExecutionService."""

    @pytest.mark.asyncio
    async def test_service_execute_turn_multiturn_flow(self, temp_workspace: Path):
        """Executes 2 successive turns via AgentExecutionService.execute_turn:
        Validates event streaming, token emission, and episodic memory persistence.
        """
        cfg = get_ollama_test_config()
        store = InMemoryStore()
        thread_id = f"th_service_ollama_{uuid.uuid4().hex[:8]}"

        model = create_chat_model(
            provider="ollama",
            model=cfg["model"],
            base_url=cfg["base_url"],
            temperature=0.0,
        )

        service = AgentExecutionService(
            model=model,
            store=store,
            workspace_root=temp_workspace,
        )

        # --------------------------------------------------------------------
        # Turn 1: Patient introduction
        # --------------------------------------------------------------------
        turn1_prompt = (
            "Hello, I am Sarah, 45 years old, recently diagnosed with Type 2 Diabetes. "
            "I am currently taking Metformin 500mg."
        )
        events_t1 = []
        async for event in service.execute_turn(
            thread_id=thread_id,
            prompt=turn1_prompt,
            agent_id="visit-steward",
            allow_clinical=True,
        ):
            events_t1.append(event)

        # Assert terminal 'done' event emitted
        done_events_t1 = [e for e in events_t1 if e.get("type") == "done"]
        assert len(done_events_t1) == 1
        t1_done = done_events_t1[0]
        assert t1_done.get("refused") is False
        t1_text = t1_done.get("fullText") or t1_done.get("full_text") or ""
        assert len(t1_text.strip()) > 0

        # Assert Turn 1 stored in episodic memory
        records_t1 = await store.asearch(("memories", thread_id))
        assert len(records_t1) == 1
        assert "metformin" in records_t1[0].value.get("user_query", "").lower()

        # --------------------------------------------------------------------
        # Turn 2: Follow-up query
        # --------------------------------------------------------------------
        turn2_prompt = "What medication and dosage did I mention I am taking?"
        events_t2 = []
        async for event in service.execute_turn(
            thread_id=thread_id,
            prompt=turn2_prompt,
            agent_id="visit-steward",
            allow_clinical=True,
        ):
            events_t2.append(event)

        # Assert terminal 'done' event emitted
        done_events_t2 = [e for e in events_t2 if e.get("type") == "done"]
        assert len(done_events_t2) == 1
        t2_done = done_events_t2[0]
        assert t2_done.get("refused") is False
        t2_text = t2_done.get("fullText") or t2_done.get("full_text") or ""
        lower_t2 = t2_text.lower()
        assert "metformin" in lower_t2, f"Turn 2 did not mention Metformin: {t2_text}"
        assert "500" in lower_t2, f"Turn 2 did not mention 500mg dosage: {t2_text}"

        # --------------------------------------------------------------------
        # State verification: BaseStore holds both turns
        # --------------------------------------------------------------------
        records_t2 = await store.asearch(("memories", thread_id))
        assert len(records_t2) == 2


# ============================================================================
# 4. Multi-Turn Workflow with SpectorStore Fallback
# ============================================================================

class TestOllamaMultiTurnSpectorStoreFallback:
    """Verifies live multi-turn continuity when paired with SpectorStore."""

    @pytest.mark.asyncio
    async def test_multiturn_with_spector_store_resilience(self):
        """Verifies multi-turn continuity with SpectorStore configured with fallback."""
        cfg = get_ollama_test_config()
        # SpectorStore pointing to unstarted port 7070 -> triggers transparent SQLite/InMemory fallback
        store = SpectorStore(base_url="http://localhost:7070", timeout=0.5)
        checkpointer = MemorySaver()
        thread_id = f"th_spector_ollama_{uuid.uuid4().hex[:8]}"

        model = create_chat_model(
            provider="ollama",
            model=cfg["model"],
            base_url=cfg["base_url"],
            temperature=0.0,
        )

        builder = (
            GraphBuilder()
            .with_model(model)
            .with_checkpointer(checkpointer)
            .with_store(store)
            .with_dynamic_orchestrator(False)
            .with_system_prompt("You are a helpful clinical navigation assistant.")
        )
        app = builder.build()
        config = {"configurable": {"thread_id": thread_id}}

        # Turn 1
        t1_input = create_initial_state(
            thread_id=thread_id,
            prompt="Hello, I am Sarah, 45 years old, taking Metformin 500mg.",
        )
        t1_res = await app.ainvoke(t1_input, config=config)
        assert t1_res.get("refused") is False

        # Turn 2
        turn2_prompt = "What medication and dosage did I mention I am taking?"
        t2_input = {
            "messages": [HumanMessage(content=turn2_prompt)],
            "prompt": turn2_prompt,
            "thread_id": thread_id,
        }
        t2_res = await app.ainvoke(t2_input, config=config)
        assert t2_res.get("refused") is False
        assert len(t2_res.get("recalled_memories", [])) >= 1
        t2_out = (t2_res.get("output") or "").lower()
        assert "metformin" in t2_out
        assert "500" in t2_out
