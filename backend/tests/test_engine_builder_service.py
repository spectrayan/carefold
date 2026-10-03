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

"""Unit and integration tests for GraphBuilder, AgentExecutionService, and runner facade.

Tests Requirement R3, R7, and Features F-39, F-40, F-41:
- GraphBuilder fluent pattern, node topology, edge routing, subgraph auto-compilation, inspection
- AgentExecutionService turn streaming, SSE event formatting, thread lifecycle, disconnect safety
- Lightweight runner facade delegation
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List
import pytest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END, START
from langgraph.graph.state import CompiledStateGraph

from carefold.engine.builder import GraphBuilder, create_agent_graph
from carefold.engine.runner import ExecutionContext, create_chat_model, execute_agent_run
from carefold.engine.service import AgentExecutionService
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE
from carefold.schemas.chat import ChatMessage, ChatRequestBody
from carefold.schemas.manifest import AgentManifest, RiskClass
from carefold.workflows.state import AgentState
from tests.fixtures.fake_model import FakeListChatModel, MockChatModel, MockModelClient


# ============================================================================
# 1. GraphBuilder Unit & Integration Tests (F-39)
# ============================================================================

class TestGraphBuilderEngine:
    """Verifies fluent GraphBuilder API, compilation, introspection, and edge execution."""

    def test_fluent_builder_chaining(self):
        """Verifies all fluent configuration methods return self and update properties."""
        fake_model = FakeListChatModel(responses=["Hello"])
        saver = MemorySaver()

        builder = (
            GraphBuilder()
            .with_model(fake_model)
            .with_checkpointer(saver)
            .with_system_prompt("You are a helpful assistant.")
            .with_max_reflections(4)
            .with_max_tool_iterations(6)
            .with_tools(["attach-read", "workspace-note"])
        )

        assert builder.model is fake_model
        assert builder.checkpointer is saver
        assert builder.system_prompt == "You are a helpful assistant."
        assert builder.max_reflections == 4
        assert builder.max_tool_iterations == 6
        assert builder.tools == ["attach-read", "workspace-note"]

    def test_inspect_graph_metadata(self):
        """Verifies inspect_graph returns complete structural metadata."""
        fake_model = FakeListChatModel(responses=["Hello"])
        saver = MemorySaver()

        builder = (
            GraphBuilder(model=fake_model, checkpointer=saver)
            .with_tools(["attach-read"])
            .with_max_reflections(3)
            .with_max_tool_iterations(5)
        )
        info = builder.inspect_graph()

        assert "nodes" in info
        assert "input_guardrail" in info["nodes"]
        assert "supervisor" in info["nodes"]
        assert "agent" in info["nodes"]
        assert "tools" in info["nodes"]
        assert "tool_validator" in info["nodes"]
        assert "output_guardrail" in info["nodes"]
        assert "reflection" in info["nodes"]
        assert "refusal" in info["nodes"]
        assert "suggestion" in info["nodes"]
        assert "audit" in info["nodes"]
        assert "error" in info["nodes"]
        assert info["model"] == "FakeListChatModel"
        assert "Saver" in info["checkpointer"]
        assert info["tools_count"] == 1
        assert info["max_reflections"] == 3
        assert info["max_tool_iterations"] == 5

    def test_create_graph_and_compile(self):
        """Verifies create_graph produces uncompiled StateGraph and build compiles it."""
        fake_model = FakeListChatModel(responses=["Hello"])
        builder = GraphBuilder().with_model(fake_model)

        uncompiled = builder.create_graph()
        assert isinstance(uncompiled, StateGraph)

        compiled = builder.build()
        assert isinstance(compiled, CompiledStateGraph)

        # compile alias
        compiled_alias = builder.compile()
        assert isinstance(compiled_alias, CompiledStateGraph)

    def test_build_graph_classmethod(self):
        """Verifies GraphBuilder.build_graph convenience constructor."""
        fake_model = FakeListChatModel(responses=["Hello"])
        saver = MemorySaver()

        compiled = GraphBuilder.build_graph(
            model=fake_model,
            checkpointer=saver,
            system_prompt="Custom prompt",
        )
        assert isinstance(compiled, CompiledStateGraph)

    def test_subgraph_auto_compilation(self):
        """Verifies uncompiled subgraphs passed to with_subgraph are auto-compiled without TypeError."""
        # Create a mini uncompiled StateGraph as a specialist subgraph
        sub_builder = StateGraph(AgentState)

        async def dummy_subgraph_node(state: AgentState) -> Dict[str, Any]:
            return {"output": "Handled by specialist subgraph"}

        sub_builder.add_node("sub_step", dummy_subgraph_node)
        sub_builder.add_edge(START, "sub_step")
        sub_builder.add_edge("sub_step", END)

        fake_model = FakeListChatModel(responses=["Hello"])
        builder = (
            GraphBuilder()
            .with_model(fake_model)
            .with_subgraph("specialist_subgraph", sub_builder)
        )

        compiled = builder.build()
        assert isinstance(compiled, CompiledStateGraph)
        assert "specialist_subgraph" in builder.inspect_graph()["subgraphs"]

    @pytest.mark.asyncio
    async def test_standalone_create_agent_graph_execution(self):
        """Verifies standalone create_agent_graph backward compatibility factory."""
        fake_model = FakeListChatModel(responses=["Your deductible is $250."])
        saver = MemorySaver()

        graph = create_agent_graph(fake_model, checkpointer=saver)
        assert isinstance(graph, CompiledStateGraph)

        res = await graph.ainvoke(
            {"messages": [HumanMessage(content="What is my deductible?")]},
            config={"configurable": {"thread_id": "bld-thread-1"}},
        )
        assert "messages" in res
        assert len(res["messages"]) >= 2
        assert res["messages"][-1].content == "Your deductible is $250."

    @pytest.mark.asyncio
    async def test_clinical_refusal_routing(self):
        """Verifies input_guardrail blocks prohibited clinical prompts and routes to refusal."""
        fake_model = FakeListChatModel(responses=["Unused"])
        graph = GraphBuilder().with_model(fake_model).build()

        res = await graph.ainvoke({
            "messages": [HumanMessage(content="Please diagnose my appendicitis")],
        })

        assert res.get("is_refusal") is True or res.get("refused") is True
        assert "doctor" in str(res.get("output", "")).lower() or "911" in str(res.get("output", ""))


# ============================================================================
# 2. AgentExecutionService Unit & Integration Tests (F-40)
# ============================================================================

class TestAgentExecutionService:
    """Verifies turn streaming, SSE event encoding, and thread lifecycle management."""

    def test_sse_event_formatters(self):
        """Verifies all static SSE formatters adhere to the Carefold wire schema."""
        tok = AgentExecutionService.format_token_event("chunk")
        assert tok == {"type": "token", "delta": "chunk"}

        start = AgentExecutionService.format_tool_start_event("attach-read", {"path": "doc.txt"})
        assert start == {"type": "tool_start", "tool": "attach-read", "params": {"path": "doc.txt"}}

        end = AgentExecutionService.format_tool_end_event(
            "attach-read", 12.5, "completed", True, {"success": True}
        )
        assert end["type"] == "tool_end"
        assert end["status"] == "completed"
        assert end["allowed"] is True
        assert end["result"]["success"] is True

        ref = AgentExecutionService.format_refusal_event("forbidden_intent:diagnose")
        assert ref["type"] == "refusal"
        assert ref["reason"] == "forbidden_intent:diagnose"
        assert ref["message"] == SAFE_REFUSAL_TEMPLATE

        sug = AgentExecutionService.format_suggestions_event(["Q1?", "Q2?"])
        assert sug == {"type": "suggestions", "suggestions": ["Q1?", "Q2?"]}

        done = AgentExecutionService.format_done_event(
            "full response", "thread-123", audit_event_id="ts-1", suggestions=["Q1?"]
        )
        assert done["type"] == "done"
        assert done["fullText"] == "full response"
        assert done["threadId"] == "thread-123"
        assert done["refused"] is False
        assert done["suggestions"] == ["Q1?"]

        err = AgentExecutionService.format_error_event("Something broke")
        assert err["type"] == "error"
        assert err["message"] == "Something broke"

        wire = AgentExecutionService.format_sse_wire_event({"type": "token", "delta": "hi"})
        assert wire.startswith("event: token\ndata: ")
        assert wire.endswith("\n\n")

    @pytest.mark.asyncio
    async def test_service_execute_turn_safe_stream(self, temp_workspace: Path):
        """Verifies execute_turn streams token events and terminal done event."""
        mock = MockModelClient()
        mock.queue_response("Your copay is $20.")

        service = AgentExecutionService(
            model=mock,
            workspace_root=temp_workspace,
        )

        events: List[Dict[str, Any]] = []
        async for ev in service.execute_turn(
            thread_id="test-srv-turn-1",
            prompt="What is my office visit copay?",
            agent_id="visit-steward",
        ):
            events.append(ev)

        types = [e["type"] for e in events]
        assert "token" in types
        assert "done" in types

        done_ev = next(e for e in events if e["type"] == "done")
        assert done_ev["refused"] is False
        assert done_ev["threadId"] == "test-srv-turn-1"
        assert "copay is $20" in done_ev["fullText"]

    @pytest.mark.asyncio
    async def test_service_execute_chat_wire_and_raw(self, temp_workspace: Path):
        """Verifies execute_chat yields wire-formatted strings or raw dictionary events."""
        mock = MockModelClient()
        mock.queue_response("Welcome to Carefold.")

        service = AgentExecutionService(model=mock, workspace_root=temp_workspace)

        # Wire format test
        wire_chunks: List[str] = []
        async for chunk in service.execute_chat(
            ChatRequestBody(agentId="visit-steward", prompt="Hello", threadId="th-wire-1", allow_clinical=True),
            raw_events=False,
        ):
            wire_chunks.append(chunk)

        assert any(c.startswith("event: token\n") for c in wire_chunks)
        assert any(c.startswith("event: done\n") for c in wire_chunks)

        # Raw events test
        mock.queue_response("Second response.")
        raw_events: List[Dict[str, Any]] = []
        async for ev in service.execute_chat(
            {"agent_id": "visit-steward", "prompt": "Hi again", "thread_id": "th-raw-1", "allow_clinical": True},
            raw_events=True,
        ):
            raw_events.append(ev)

        assert any(e.get("type") == "token" for e in raw_events)
        assert any(e.get("type") == "done" for e in raw_events)

    @pytest.mark.asyncio
    async def test_service_thread_state_and_history(self, temp_workspace: Path):
        """Verifies get_thread_state, get_thread_history, and clear_thread_state."""
        mock = MockModelClient()
        mock.queue_response("Prescription history loaded.")

        service = AgentExecutionService(model=mock, workspace_root=temp_workspace)
        thread_id = "test-history-thread-42"

        async for _ in service.execute_turn(
            thread_id=thread_id,
            prompt="Can you check my prescriptions?",
            agent_id="visit-steward",
        ):
            pass

        # Inspect thread state
        state = await service.get_thread_state(thread_id)
        assert state is not None
        assert "messages" in state

        # Retrieve serialized thread history for REST API
        hist = await service.get_thread_history(thread_id)
        assert hist["threadId"] == thread_id
        assert hist["count"] >= 2
        assert any(m["role"] == "user" for m in hist["messages"])
        assert any(m["role"] == "assistant" for m in hist["messages"])

        # Clear state
        cleared = await service.clear_thread_state(thread_id)
        assert cleared is True

    @pytest.mark.asyncio
    async def test_service_clinical_assist_unauthorized_gating(self, temp_workspace: Path):
        """Verifies execution is rejected with error when clinical_assist agent lacks allow_clinical."""
        service = AgentExecutionService(workspace_root=temp_workspace)

        # Create a mock agent directory with clinical_assist risk class
        agent_dir = temp_workspace / "agents" / "clinical-agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "agent.yaml").write_text(
            """id: clinical-agent
title: Clinical Triage Agent
role: Clinical assistant
risk_class: clinical_assist
model: carefold-default
tools: []
skills: []
persona: Professional
starters: []
""",
            encoding="utf-8",
        )

        events: List[Dict[str, Any]] = []
        async for ev in service.execute_turn(
            thread_id="th-clinical-gate",
            prompt="Assess my symptoms",
            agent_id="clinical-agent",
            allow_clinical=False,
        ):
            events.append(ev)

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "clinical_assist" in events[0]["message"]


# ============================================================================
# 3. Monolithic Runner Purge & Facade Verification (F-41)
# ============================================================================

class TestRunnerFacade:
    """Verifies runner.py is a clean delegation facade."""

    def test_runner_file_is_clean_and_concise(self):
        """Verifies runner.py does not exceed 100 lines and is a pure facade."""
        runner_file = Path(__file__).parents[1] / "src" / "carefold" / "engine" / "runner.py"
        assert runner_file.is_file()
        content = runner_file.read_text(encoding="utf-8")
        lines = [line for line in content.splitlines() if line.strip() and not line.strip().startswith("#")]
        # Facade should be clean and lean (under 100 non-blank lines)
        assert len(lines) < 100

    def test_runner_exports_preserved(self):
        """Verifies ExecutionContext, execute_agent_run, and create_chat_model are exported."""
        import carefold.engine.runner as runner_mod

        assert hasattr(runner_mod, "ExecutionContext")
        assert hasattr(runner_mod, "execute_agent_run")
        assert hasattr(runner_mod, "create_chat_model")

    @pytest.mark.asyncio
    async def test_execute_agent_run_delegates_to_service(self, temp_workspace: Path):
        """Verifies execute_agent_run facade runs successfully end-to-end."""
        mock = MockModelClient()
        mock.queue_response("Facade execution successful.")

        events: List[Dict[str, Any]] = []
        async for ev in execute_agent_run(
            agent_id="visit-steward",
            prompt="Test facade",
            model_client=mock,
            workspace_root=temp_workspace,
        ):
            events.append(ev)

        assert any(e.get("type") == "token" for e in events)
        assert any(e.get("type") == "done" for e in events)
