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

"""Specialist Supervisor Subgraph and Multi-Agent Dispatch Test Suite.

Authoritative stress-testing for:
1. Specialist Supervisor Subgraph compilation and execution with:
   - FakeListChatModel
   - MockChatModel
   - MemorySaver checkpointer persistence
2. Multi-agent dispatch and state handoff across all 5 canonical specialists:
   - benefits-guide
   - visit-steward
   - document-extractor
   - habit-companion
   - generalist
3. Return transitions and supervisor loopback:
   - Clean termination to END
   - Dynamic loopback to supervisor via requires_supervisor / next_step
   - Multi-agent multi-hop delegation chain
4. Concurrency & thread safety:
   - 50 concurrent ainvoke executions via asyncio.gather
   - ThreadPoolExecutor multithreaded stress testing
5. Edge cases:
   - Empty state, missing human message, conflicting keywords, tool bindings
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List
import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from carefold.workflows.state import AgentState, create_initial_state
from carefold.workflows.subgraphs.supervisor import (
    DEFAULT_SPECIALISTS,
    SPECIALIST_BENEFITS_GUIDE,
    SPECIALIST_DOCUMENT_EXTRACTOR,
    SPECIALIST_GENERALIST,
    SPECIALIST_HABIT_COMPANION,
    SPECIALIST_VISIT_STEWARD,
    build_supervisor_subgraph,
    create_supervisor_router_node,
    create_supervisor_subgraph,
    route_specialist_return,
    route_supervisor,
)
from tests.fixtures.fake_model import FakeListChatModel, MockChatModel


# ============================================================================
# 1. Compilation & Structure Verification
# ============================================================================

class TestSupervisorCompilation:
    """Verifies graph assembly, compile flags, checkpointer integration, and node bindings."""

    def test_uncompiled_returns_stategraph(self):
        fake = FakeListChatModel(responses=["test response"])
        graph = create_supervisor_subgraph(model=fake, compile=False)
        assert isinstance(graph, StateGraph)
        assert "supervisor_node" in graph.nodes
        assert "benefits_guide" in graph.nodes
        assert "visit_steward" in graph.nodes
        assert "document_extractor" in graph.nodes
        assert "habit_companion" in graph.nodes
        assert "generalist" in graph.nodes

    def test_compiled_with_fakelistchatmodel(self):
        fake = FakeListChatModel(responses=["fake response"])
        app = build_supervisor_subgraph(model=fake)
        assert isinstance(app, CompiledStateGraph)

    def test_compiled_with_mockchatmodel(self):
        mock = MockChatModel()
        app = build_supervisor_subgraph(model=mock)
        assert isinstance(app, CompiledStateGraph)

    def test_compiled_with_checkpointer(self):
        memory = MemorySaver()
        fake = FakeListChatModel(responses=["persisted response"])
        app = build_supervisor_subgraph(model=fake, checkpointer=memory)
        assert isinstance(app, CompiledStateGraph)
        assert app.checkpointer is memory

    def test_custom_specialist_node_override(self):
        async def custom_benefits_node(state: AgentState) -> Dict[str, Any]:
            return {
                "output": "Custom Benefits Override",
                "current_agent": "custom-benefits",
                "next_step": "done",
            }

        fake = FakeListChatModel(responses=["default response"])
        app = build_supervisor_subgraph(
            model=fake,
            specialists={"benefits-guide": custom_benefits_node},
        )
        assert isinstance(app, CompiledStateGraph)


# ============================================================================
# 2. Multi-Agent Dispatch Across All Specialists
# ============================================================================

class TestSupervisorMultiAgentDispatch:
    """Verifies intent classification, dispatching, and state handoff across all 5 specialists."""

    @pytest.mark.asyncio
    async def test_dispatch_benefits_guide_inferred(self):
        fake = FakeListChatModel(responses=["Your in-network deductible is $500 with a $20 copay."])
        app = build_supervisor_subgraph(model=fake)

        state = create_initial_state(
            thread_id="t-benefits-1",
            user_id="u-1",
            messages=[HumanMessage(content="What is my in-network deductible and copay?")],
        )
        result = await app.ainvoke(state)

        assert result["current_agent"] == SPECIALIST_BENEFITS_GUIDE
        assert result["routed_subgraph"] == SPECIALIST_BENEFITS_GUIDE
        assert "deductible" in result["output"].lower()
        # Ensure message reducer added the AI message
        messages = result["messages"]
        assert len(messages) >= 2
        assert isinstance(messages[-1], AIMessage)
        assert "500" in messages[-1].content

    @pytest.mark.asyncio
    async def test_dispatch_visit_steward_inferred(self):
        fake = FakeListChatModel(responses=["Here is your doctor appointment prep checklist."])
        app = build_supervisor_subgraph(model=fake)

        state = create_initial_state(
            thread_id="t-visit-1",
            user_id="u-1",
            messages=[HumanMessage(content="Help me prepare a checklist for my doctor appointment tomorrow")],
        )
        result = await app.ainvoke(state)

        assert result["current_agent"] == SPECIALIST_VISIT_STEWARD
        assert result["routed_subgraph"] == SPECIALIST_VISIT_STEWARD
        assert "doctor" in result["output"].lower() or "checklist" in result["output"].lower()

    @pytest.mark.asyncio
    async def test_dispatch_document_extractor_without_dossiers(self):
        # document-extractor has deterministic node logic that returns summary when no dossiers
        fake = FakeListChatModel(responses=["unused"])
        app = build_supervisor_subgraph(model=fake)

        state = create_initial_state(
            thread_id="t-extract-1",
            user_id="u-1",
            messages=[HumanMessage(content="Extract structured tables from this document dossier scan")],
        )
        result = await app.ainvoke(state)

        assert result["current_agent"] == SPECIALIST_DOCUMENT_EXTRACTOR
        assert result["routed_subgraph"] == SPECIALIST_DOCUMENT_EXTRACTOR
        assert "Extracted document summary" in result["output"]

    @pytest.mark.asyncio
    async def test_defect_shadowed_extraction_keywords_misroute(self):
        """VERIFY FIX FOR SHADOWED EXTRACTION KEYWORDS:
        Document extraction patterns must take precedence over general benefits/visit patterns
        when document attachments or extraction keywords are present.
        """
        router = create_supervisor_router_node()

        # Prompt with 'summary of benefits' and document pdf is routed to document-extractor
        res_benefits = await router({
            "messages": [HumanMessage(content="Extract the summary of benefits from this document pdf")],
        })
        assert res_benefits["routed_subgraph"] == SPECIALIST_DOCUMENT_EXTRACTOR

        # Prompt with 'visit summary' and uploaded document is routed to document-extractor
        res_visit = await router({
            "messages": [HumanMessage(content="Extract the visit summary from this uploaded document")],
        })
        assert res_visit["routed_subgraph"] == SPECIALIST_DOCUMENT_EXTRACTOR

    @pytest.mark.asyncio
    async def test_dispatch_document_extractor_with_dossiers(self):
        fake = FakeListChatModel(responses=["unused"])
        app = build_supervisor_subgraph(model=fake)

        dossier = {"copay": 20, "deductible": 1000, "in_network": True}
        state = create_initial_state(
            thread_id="t-extract-2",
            user_id="u-1",
            messages=[HumanMessage(content="Extract data from uploaded scan")],
        )
        state["document_dossiers"] = [dossier]

        result = await app.ainvoke(state)

        assert result["current_agent"] == SPECIALIST_DOCUMENT_EXTRACTOR
        assert "Document extraction completed" in result["output"]
        assert len(result["document_dossiers"]) == 1
        assert result["document_dossiers"][0]["copay"] == 20

    @pytest.mark.asyncio
    async def test_dispatch_habit_companion_inferred(self):
        fake = FakeListChatModel(responses=["Let's build a consistent daily hydration habit of 64 ounces."])
        app = build_supervisor_subgraph(model=fake)

        state = create_initial_state(
            thread_id="t-habit-1",
            user_id="u-1",
            messages=[HumanMessage(content="Help me track my daily water hydration habit and routine")],
        )
        result = await app.ainvoke(state)

        assert result["current_agent"] == SPECIALIST_HABIT_COMPANION
        assert result["routed_subgraph"] == SPECIALIST_HABIT_COMPANION
        assert "hydration" in result["output"].lower()

    @pytest.mark.asyncio
    async def test_dispatch_explicit_preselection(self):
        """Caller explicitly specifies target agent in routed_subgraph or current_agent."""
        fake = FakeListChatModel(responses=["Generalist wellness assistance."])
        app = build_supervisor_subgraph(model=fake)

        state = create_initial_state(
            thread_id="t-explicit-1",
            user_id="u-1",
            messages=[HumanMessage(content="Hello there")],
        )
        state["routed_subgraph"] = SPECIALIST_GENERALIST

        result = await app.ainvoke(state)
        assert result["current_agent"] == SPECIALIST_GENERALIST
        assert result["output"] == "Generalist wellness assistance."

    @pytest.mark.asyncio
    async def test_dispatch_all_five_specialists_coverage(self):
        """Ensures every one of the 5 canonical specialists can be reached."""
        specialist_prompts = {
            SPECIALIST_BENEFITS_GUIDE: "What is my insurance copay?",
            SPECIALIST_VISIT_STEWARD: "Doctor visit checklist prep",
            SPECIALIST_DOCUMENT_EXTRACTOR: "Extract document pdf dossier",
            SPECIALIST_HABIT_COMPANION: "Track my sleep habit routine",
            SPECIALIST_GENERALIST: "General non-clinical care guidance",
        }

        fake = FakeListChatModel(responses=["Agent response"])
        app = build_supervisor_subgraph(model=fake)

        for spec_id, prompt in specialist_prompts.items():
            state = create_initial_state(
                thread_id=f"t-{spec_id}",
                user_id="u-test",
                messages=[HumanMessage(content=prompt)],
            )
            if spec_id == SPECIALIST_GENERALIST:
                state["routed_subgraph"] = SPECIALIST_GENERALIST

            result = await app.ainvoke(state)
            assert result["current_agent"] == spec_id, f"Failed routing to {spec_id}"


# ============================================================================
# 3. Execution With MockChatModel (Zero Network / CI Offline Double)
# ============================================================================

class TestSupervisorMockChatModelExecution:
    """Verifies that MockChatModel seamlessly powers the supervisor subgraph."""

    @pytest.mark.asyncio
    async def test_mock_chat_model_benefits_execution(self):
        mock = MockChatModel()
        app = build_supervisor_subgraph(model=mock)

        state = create_initial_state(
            thread_id="mock-t1",
            user_id="mock-u1",
            messages=[HumanMessage(content="What are my copay amounts for in-network visits?")],
        )
        result = await app.ainvoke(state)

        assert result["current_agent"] == SPECIALIST_BENEFITS_GUIDE
        assert isinstance(result["output"], str)
        assert len(result["output"]) > 0
        assert mock.call_count >= 1

    @pytest.mark.asyncio
    async def test_mock_chat_model_visit_execution(self):
        mock = MockChatModel()
        app = build_supervisor_subgraph(model=mock)

        state = create_initial_state(
            thread_id="mock-t2",
            user_id="mock-u1",
            messages=[HumanMessage(content="Questions to ask my doctor during clinical appointment")],
        )
        result = await app.ainvoke(state)

        assert result["current_agent"] == SPECIALIST_VISIT_STEWARD
        assert len(result["output"]) > 0


# ============================================================================
# 4. Return Transitions & Supervisor Loopback
# ============================================================================

class TestSupervisorReturnTransitions:
    """Tests clean termination to END and supervisor re-entry / multi-hop delegation."""

    def test_route_specialist_return_clean_exit(self):
        assert route_specialist_return({"next_step": "done"}) == END
        assert route_specialist_return({"next_step": ""}) == END
        assert route_specialist_return({}) == END

    def test_route_specialist_return_loopback_cases(self):
        assert route_specialist_return({"next_step": "supervisor"}) == "supervisor_node"
        assert route_specialist_return({"next_step": "supervisor_node"}) == "supervisor_node"
        assert route_specialist_return({"requires_supervisor": True}) == "supervisor_node"

    @pytest.mark.asyncio
    async def test_multi_hop_delegation_loop(self):
        """Simulates a specialist delegating back to supervisor, which routes to another specialist.
        
        Step 1: Benefits Guide identifies need for document extraction and sets:
                requires_supervisor=True, routed_subgraph='document-extractor'
        Step 2: Supervisor re-routes to Document Extractor.
        Step 3: Document Extractor finishes with next_step='done' -> END.
        """
        hop_counter = 0

        async def dynamic_benefits_node(state: AgentState) -> Dict[str, Any]:
            nonlocal hop_counter
            hop_counter += 1
            if hop_counter == 1:
                # First pass: request supervisor to delegate to document-extractor
                return {
                    "messages": [AIMessage(content="I need to inspect your document first.")],
                    "output": "Delegating to document extractor",
                    "current_agent": SPECIALIST_DOCUMENT_EXTRACTOR,
                    "routed_subgraph": SPECIALIST_DOCUMENT_EXTRACTOR,
                    "next_step": "supervisor",
                    "requires_supervisor": True,
                }
            # Fallback
            return {"next_step": "done", "output": "Done"}

        fake = FakeListChatModel(responses=["unused"])
        app = build_supervisor_subgraph(
            model=fake,
            specialists={SPECIALIST_BENEFITS_GUIDE: dynamic_benefits_node},
        )

        state = create_initial_state(
            thread_id="t-loop-1",
            user_id="u-1",
            messages=[HumanMessage(content="Can you check my benefits from my insurance card?")],
        )
        result = await app.ainvoke(state)

        # Confirm the chain ran through benefits_guide -> supervisor_node -> document_extractor -> END
        assert hop_counter == 1
        assert result["current_agent"] == SPECIALIST_DOCUMENT_EXTRACTOR
        assert result["routed_subgraph"] == SPECIALIST_DOCUMENT_EXTRACTOR
        assert "document summary" in result["output"].lower() or "dossier" in result["output"].lower()


# ============================================================================
# 5. Checkpointer & Multi-Turn State Persistence
# ============================================================================

class TestSupervisorStatePersistence:
    """Verifies state history accumulation across sequential turns via MemorySaver."""

    @pytest.mark.asyncio
    async def test_multi_turn_conversation_with_memory_saver(self):
        memory = MemorySaver()
        fake = FakeListChatModel(
            responses=[
                "Your deductible is $1000.",
                "Yes, your $20 copay counts after meeting your deductible.",
            ]
        )
        app = build_supervisor_subgraph(model=fake, checkpointer=memory)

        config = {"configurable": {"thread_id": "thread-multi-turn-1"}}

        # Turn 1: Ask about deductible
        state1 = create_initial_state(
            thread_id="thread-multi-turn-1",
            user_id="user-1",
            messages=[HumanMessage(content="What is my deductible under this insurance plan?")],
        )
        res1 = await app.ainvoke(state1, config=config)
        assert res1["current_agent"] == SPECIALIST_BENEFITS_GUIDE
        assert "$1000" in res1["output"]

        # Turn 2: Follow-up question on same thread
        state2 = {
            "messages": [HumanMessage(content="Does my copay count toward that deductible?")],
        }
        res2 = await app.ainvoke(state2, config=config)
        assert res2["current_agent"] == SPECIALIST_BENEFITS_GUIDE

        # Verify thread history in checkpointer
        checkpoint = await memory.aget(config)
        assert checkpoint is not None
        saved_messages = checkpoint["channel_values"]["messages"]
        # Turn 1 Human + Turn 1 AI + Turn 2 Human + Turn 2 AI = at least 4 messages
        assert len(saved_messages) >= 4
        assert any("$1000" in str(m.content) for m in saved_messages)


# ============================================================================
# 6. Concurrency & Thread Stress Testing
# ============================================================================

class TestSupervisorConcurrency:
    """High-load concurrency verification: parallel ainvoke, shared model, thread isolation."""

    @pytest.mark.asyncio
    async def test_concurrent_50_parallel_ainvokes(self):
        """Stress-tests 50 concurrent requests with varying specialist targets across shared graph."""
        mock = MockChatModel()
        app = build_supervisor_subgraph(model=mock)

        prompts = [
            ("benefits-guide", "What is my copay for specialist visits?"),
            ("visit-steward", "Doctor appointment question preparation checklist"),
            ("document-extractor", "Extract data from this uploaded document"),
            ("habit-companion", "Help me build a water intake habit"),
        ]

        async def run_single(idx: int) -> Dict[str, Any]:
            expected_agent, prompt_text = prompts[idx % len(prompts)]
            state = create_initial_state(
                thread_id=f"thread-concurrency-{idx}",
                user_id=f"user-{idx}",
                messages=[HumanMessage(content=prompt_text)],
            )
            res = await app.ainvoke(state)
            return {
                "idx": idx,
                "expected": expected_agent,
                "actual": res["current_agent"],
                "has_output": bool(res.get("output")),
            }

        tasks = [run_single(i) for i in range(50)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 50
        for r in results:
            assert r["actual"] == r["expected"], f"Crosstalk or mismatch at index {r['idx']}"
            assert r["has_output"] is True

    def test_sync_invoke_raises_type_error(self):
        """Documents limitation: async node implementations in supervisor raise TypeError on sync invoke."""
        mock = MockChatModel()
        app = build_supervisor_subgraph(model=mock)

        state = create_initial_state(
            thread_id="t-sync-1",
            user_id="user-sync",
            messages=[HumanMessage(content="Insurance deductible inquiry")],
        )
        with pytest.raises(TypeError, match='No synchronous function provided to "supervisor_node"'):
            app.invoke(state)

    def test_multithreaded_concurrent_ainvoke_stress(self):
        """Stress-tests async invocation across 10 concurrent OS threads, each running an event loop."""
        mock = MockChatModel()
        app = build_supervisor_subgraph(model=mock)

        def worker_task(thread_id: str) -> str:
            state = create_initial_state(
                thread_id=thread_id,
                user_id="user-thread",
                messages=[HumanMessage(content="Insurance deductible inquiry")],
            )
            res = asyncio.run(app.ainvoke(state))
            return res["current_agent"]

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker_task, f"thread-{i}") for i in range(20)]
            agents = [f.result(timeout=10) for f in futures]

        assert len(agents) == 20
        assert all(a == SPECIALIST_BENEFITS_GUIDE for a in agents)


# ============================================================================
# 7. Edge Cases & Robustness
# ============================================================================

class TestSupervisorEdgeCases:
    """Stress tests boundary conditions, missing attributes, and ambiguous inputs."""

    @pytest.mark.asyncio
    async def test_empty_messages_defaults_gracefully(self):
        fake = FakeListChatModel(responses=["Fallback guidance"])
        app = build_supervisor_subgraph(model=fake)

        state = {"messages": []}
        res = await app.ainvoke(state)
        # Should not crash; defaults to fallback agent (visit-steward)
        assert res["current_agent"] == SPECIALIST_VISIT_STEWARD
        assert res["output"] == "Fallback guidance"

    @pytest.mark.asyncio
    async def test_only_system_messages_in_history(self):
        fake = FakeListChatModel(responses=["Guidance response"])
        app = build_supervisor_subgraph(model=fake)

        state = {
            "messages": [SystemMessage(content="System directive: maintain HIPAA compliance.")],
        }
        res = await app.ainvoke(state)
        assert res["current_agent"] == SPECIALIST_VISIT_STEWARD

    @pytest.mark.asyncio
    async def test_competing_domain_keywords_priority(self):
        """Prompt combines insurance keywords and visit keywords.
        
        Benefits patterns are evaluated before visit patterns in router.
        """
        fake = FakeListChatModel(responses=["Benefits coverage for visit."])
        app = build_supervisor_subgraph(model=fake)

        prompt = "Does my insurance cover my doctor appointment visit deductible?"
        state = create_initial_state(
            thread_id="t-competing",
            user_id="u-1",
            messages=[HumanMessage(content=prompt)],
        )
        res = await app.ainvoke(state)
        # Benefits pattern matched first
        assert res["current_agent"] == SPECIALIST_BENEFITS_GUIDE
