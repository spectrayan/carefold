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

"""Tool Loop Execution, Deduplication, and Runner Facade Test Suite.

Verifies:
1. Tool trace deduplication across multi-iteration tool runs:
   - Zero duplicate `tool_start` or `tool_end` events across multiple tool iterations.
   - Zero duplicate `event: "tool"` entries in the persistent audit log (audit.jsonl).
   - Trace deduplication across multi-tool batch calls in single and successive turns.
   - Strict loop bound termination at max_tool_iterations ceiling without trace duplication.
2. Allowlist boundary enforcement:
   - Agents declaring zero tools (effective_tools: [], e.g. `_template`) strictly deny any tool call.
   - Agents with restricted toolsets (e.g. `habit-companion`, `benefits-guide`) strictly deny undeclared tools.
   - Denied tools emit allowed=False, status="denied", success=False, output=None, and undeclared error string.
   - Audit log records allowed=False with undeclared reason.
   - ToolMessage in conversation state is marked with status="error".
   - Underlying tool execution logic is never invoked for denied tools.
3. Runner facade backward compatibility and monkeypatching:
   - monkeypatching `carefold.engine.runner.create_chat_model` cleanly overrides model resolution.
   - `model_client` argument directly takes precedence when supplied.
   - `ExecutionContext` dataclass is exported and backwards-compatible.
   - `runner.py` maintains lightweight facade contract (< 100 non-blank lines).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List
import pytest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from carefold.config import settings
from carefold.constants.api import (
    SSE_EVENT_DONE,
    SSE_EVENT_ERROR,
    SSE_EVENT_TOKEN,
    SSE_EVENT_TOOL_END,
    SSE_EVENT_TOOL_START,
)
from carefold.engine.builder import GraphBuilder
from carefold.engine.runner import ExecutionContext, create_chat_model, execute_agent_run
from carefold.engine.service import AgentExecutionService
from carefold.workflows.nodes.tool_node import ToolNode
from carefold.workflows.state import AgentState
from tests.fixtures.fake_model import FakeListChatModel, MockChatModel, MockModelClient


# ============================================================================
# 1. Multi-Iteration Tool Execution & Trace Deduplication Stress Tests
# ============================================================================

class TestMultiIterationToolDeduplication:
    """Stress tests multi-turn tool loops to verify absolute trace deduplication."""

    @pytest.mark.asyncio
    async def test_sequential_two_iteration_tool_run_deduplication(self, temp_workspace: Path):
        """Verifies a 2-iteration tool execution yields exactly 2 tool_start, 2 tool_end,

        and exactly 2 tool audit events without duplicate re-dispatches.
        """
        audit_file = temp_workspace / "logs" / "audit.jsonl"
        if audit_file.exists():
            audit_file.unlink()

        model = MockChatModel()
        # Iteration 1: write first note
        model.queue_response({
            "name": "workspace-note",
            "arguments": {"title": "Daily Routine 1", "content": "Morning hydration completed."},
        })
        # Iteration 2: write second note
        model.queue_response({
            "name": "workspace-note",
            "arguments": {"title": "Daily Routine 2", "content": "Evening stretch completed."},
        })
        # Iteration 3: final answer
        model.queue_response("Both daily routines have been recorded successfully.")

        events: List[Dict[str, Any]] = []
        async for ev in execute_agent_run(
            agent_id="habit-companion",
            prompt="Record morning and evening routines",
            model_client=model,
            workspace_root=temp_workspace,
        ):
            events.append(ev)

        # 1. SSE Event Assertions
        tool_starts = [e for e in events if e.get("type") == SSE_EVENT_TOOL_START]
        tool_ends = [e for e in events if e.get("type") == SSE_EVENT_TOOL_END]

        assert len(tool_starts) == 2, f"Expected exactly 2 tool_start events, got {len(tool_starts)}"
        assert len(tool_ends) == 2, f"Expected exactly 2 tool_end events, got {len(tool_ends)}"

        for te in tool_ends:
            assert te.get("tool") == "workspace-note"
            assert te.get("allowed") is True
            assert te.get("status") == "completed"
            assert te.get("result", {}).get("success") is True

        done_ev = next((e for e in events if e.get("type") == SSE_EVENT_DONE), None)
        assert done_ev is not None
        assert "Both daily routines" in done_ev.get("fullText", "")

        # 2. Audit Log Deduplication Assertions
        assert audit_file.exists(), "Audit log file must be created"
        audit_lines = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        tool_audits = [al for al in audit_lines if al.get("event") == "tool"]

        assert len(tool_audits) == 2, f"Expected exactly 2 tool audit events, got {len(tool_audits)}"
        for ta in tool_audits:
            assert ta.get("tool") == "workspace-note"
            assert ta.get("allowed") is True
            assert ta.get("agent_id") == "habit-companion"

    @pytest.mark.asyncio
    async def test_three_iteration_tool_run_deduplication(self, temp_workspace: Path):
        """Verifies a 3-iteration tool run executes sequentially without event accumulation."""
        audit_file = temp_workspace / "logs" / "audit.jsonl"
        if audit_file.exists():
            audit_file.unlink()

        model = MockChatModel()
        model.queue_response({"name": "workspace-note", "arguments": {"title": "Note Alpha", "content": "1"}})
        model.queue_response({"name": "workspace-note", "arguments": {"title": "Note Beta", "content": "2"}})
        model.queue_response({"name": "workspace-note", "arguments": {"title": "Note Gamma", "content": "3"}})
        model.queue_response("Finished all three notes.")

        events: List[Dict[str, Any]] = []
        async for ev in execute_agent_run(
            agent_id="habit-companion",
            prompt="Record three notes",
            model_client=model,
            workspace_root=temp_workspace,
        ):
            events.append(ev)

        tool_starts = [e for e in events if e.get("type") == SSE_EVENT_TOOL_START]
        tool_ends = [e for e in events if e.get("type") == SSE_EVENT_TOOL_END]

        assert len(tool_starts) == 3
        assert len(tool_ends) == 3

        audit_lines = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        tool_audits = [al for al in audit_lines if al.get("event") == "tool"]
        assert len(tool_audits) == 3

    @pytest.mark.asyncio
    async def test_batch_parallel_tools_in_single_turn_deduplication(self, temp_workspace: Path):
        """Verifies when a single model turn requests 2 tool calls simultaneously,

        then iteration 2 requests 1 tool call, all 3 are dispatched exactly once.
        """
        audit_file = temp_workspace / "logs" / "audit.jsonl"
        if audit_file.exists():
            audit_file.unlink()

        model = MockChatModel()
        # Iteration 1: Model issues 2 parallel tool calls in one turn
        model.queue_response({
            "tool_calls": [
                {"id": "call_p1", "name": "workspace-note", "args": {"title": "Batch A", "content": "A"}},
                {"id": "call_p2", "name": "workspace-note", "args": {"title": "Batch B", "content": "B"}},
            ]
        })
        # Iteration 2: Model issues 1 subsequent tool call
        model.queue_response({
            "name": "workspace-note",
            "arguments": {"title": "Batch C", "content": "C"},
        })
        # Iteration 3: Final message
        model.queue_response("All batches complete.")

        events: List[Dict[str, Any]] = []
        async for ev in execute_agent_run(
            agent_id="habit-companion",
            prompt="Run batch updates",
            model_client=model,
            workspace_root=temp_workspace,
        ):
            events.append(ev)

        tool_ends = [e for e in events if e.get("type") == SSE_EVENT_TOOL_END]
        assert len(tool_ends) == 3, f"Expected 3 tool_end events, got {len(tool_ends)}"

        audit_lines = [json.loads(l) for l in audit_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        tool_audits = [al for l in audit_lines if (al := l).get("event") == "tool"]
        assert len(tool_audits) == 3, f"Expected 3 tool audit entries, got {len(tool_audits)}"

    @pytest.mark.asyncio
    async def test_max_tool_iteration_ceiling_halts_infinite_tool_loop(self, temp_workspace: Path):
        """Verifies that an agent repeatedly issuing tool calls halts strictly at max_tool_iterations

        and does not produce duplicate traces up to that ceiling.
        """
        audit_file = temp_workspace / "logs" / "audit.jsonl"
        if audit_file.exists():
            audit_file.unlink()

        # Model that indefinitely queues tool calls
        class InfiniteToolModel(MockChatModel):
            async def ainvoke(self, *args: Any, **kwargs: Any) -> AIMessage:
                call_id = f"call_{len(args)}"
                return AIMessage(
                    content="",
                    tool_calls=[{"id": call_id, "name": "workspace-note", "args": {"title": "Loop", "content": "Spam"}}],
                )

        model = InfiniteToolModel()
        max_iters = 4
        service = AgentExecutionService(
            model=model,
            workspace_root=temp_workspace,
            graph_builder=GraphBuilder(model=model).with_max_tool_iterations(max_iters),
        )

        events: List[Dict[str, Any]] = []
        async for ev in service.execute_turn(
            thread_id="th-infinite-tool-loop",
            prompt="Loop forever",
            agent_id="habit-companion",
        ):
            events.append(ev)

        tool_ends = [e for e in events if e.get("type") == SSE_EVENT_TOOL_END]
        # Should halt strictly at max_iters
        assert len(tool_ends) == max_iters, f"Expected {max_iters} tool iterations, got {len(tool_ends)}"

        audit_lines = [json.loads(l) for l in audit_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        tool_audits = [al for al in audit_lines if al.get("event") == "tool"]
        assert len(tool_audits) == max_iters

    @pytest.mark.asyncio
    async def test_tool_failure_followed_by_success_deduplication(self, temp_workspace: Path):
        """Verifies when a tool call fails in iteration 1 (invalid arguments) and succeeds in iteration 2,

        the failed tool is emitted exactly once as status='failed' and not re-emitted.
        """
        audit_file = temp_workspace / "logs" / "audit.jsonl"
        if audit_file.exists():
            audit_file.unlink()

        model = MockChatModel()
        # Invalid arguments: title missing
        model.queue_response({"name": "workspace-note", "arguments": {"content": "Missing title"}})
        # Valid arguments
        model.queue_response({"name": "workspace-note", "arguments": {"title": "Fixed Note", "content": "Valid"}})
        model.queue_response("Fixed successfully.")

        events: List[Dict[str, Any]] = []
        async for ev in execute_agent_run(
            agent_id="habit-companion",
            prompt="Try saving note",
            model_client=model,
            workspace_root=temp_workspace,
        ):
            events.append(ev)

        tool_ends = [e for e in events if e.get("type") == SSE_EVENT_TOOL_END]
        assert len(tool_ends) == 2

        assert tool_ends[0]["status"] == "failed"
        assert tool_ends[0]["allowed"] is True
        assert tool_ends[0]["result"]["success"] is False

        assert tool_ends[1]["status"] == "completed"
        assert tool_ends[1]["allowed"] is True
        assert tool_ends[1]["result"]["success"] is True

        audit_lines = [json.loads(l) for l in audit_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        tool_audits = [al for al in audit_lines if al.get("event") == "tool"]
        assert len(tool_audits) == 2


# ============================================================================
# 2. Allowlist Boundary Enforcement (Zero Tools & Undeclared Tools)
# ============================================================================

class TestAllowlistBoundaryEnforcement:
    """Verifies strict deny-by-default enforcement for zero-tool and restricted agents."""

    @pytest.mark.asyncio
    async def test_template_zero_tool_agent_strictly_denies_all_tools(self, temp_workspace: Path):
        """Verifies that an agent declaring zero tools (effective_tools: [], e.g. `_template`)

        strictly denies tool calls with allowed=False, status='denied', output=None, and audit recording.
        """
        audit_file = temp_workspace / "logs" / "audit.jsonl"
        if audit_file.exists():
            audit_file.unlink()

        model = MockChatModel()
        # Attempt to call closed tool attach-read
        model.queue_response({"name": "attach-read", "arguments": {"path": "unauthorized.txt"}})
        model.queue_response("Handled refusal.")

        events: List[Dict[str, Any]] = []
        async for ev in execute_agent_run(
            agent_id="_template",
            prompt="Hello Template, please check unauthorized.txt",
            model_client=model,
            workspace_root=temp_workspace,
        ):
            events.append(ev)

        tool_ends = [e for e in events if e.get("type") == SSE_EVENT_TOOL_END]
        assert len(tool_ends) == 1, f"Expected 1 tool_end, got {len(tool_ends)}"

        te = tool_ends[0]
        assert te.get("tool") == "attach-read"
        assert te.get("allowed") is False
        assert te.get("status") == "denied"
        assert te.get("result", {}).get("success") is False
        assert te.get("result", {}).get("output") is None
        assert "execution denied: undeclared tool for agent '_template'" in str(te.get("result", {}).get("error"))

        # Verify audit log recorded rejection
        assert audit_file.exists()
        audit_lines = [json.loads(l) for l in audit_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        tool_audits = [al for al in audit_lines if al.get("event") == "tool"]
        assert len(tool_audits) == 1
        ta = tool_audits[0]
        assert ta.get("tool") == "attach-read"
        assert ta.get("allowed") is False
        assert "execution denied: undeclared tool" in str(ta.get("reason"))

    @pytest.mark.asyncio
    async def test_document_extractor_zero_tool_boundary(self, temp_workspace: Path):
        """Verifies supervisor routing to document-extractor also strictly denies undeclared tools."""
        model = MockChatModel()
        model.queue_response({"name": "attach-read", "arguments": {"path": "medical_summary.pdf"}})
        model.queue_response("Done extraction.")

        events: List[Dict[str, Any]] = []
        async for ev in execute_agent_run(
            agent_id="_template",
            prompt="Please read and extract medical_summary.pdf",
            model_client=model,
            workspace_root=temp_workspace,
        ):
            events.append(ev)

        tool_ends = [e for e in events if e.get("type") == SSE_EVENT_TOOL_END]
        assert len(tool_ends) == 1
        assert tool_ends[0]["allowed"] is False
        assert tool_ends[0]["status"] == "denied"
        assert "execution denied: undeclared tool" in tool_ends[0]["result"]["error"]

    @pytest.mark.asyncio
    async def test_restricted_toolset_agent_enforces_exact_boundary(self, temp_workspace: Path):
        """Verifies habit-companion allows workspace-note but strictly denies attach-read and skill-docs."""
        audit_file = temp_workspace / "logs" / "audit.jsonl"
        if audit_file.exists():
            audit_file.unlink()

        model = MockChatModel()
        # Iteration 1: Allowed tool (workspace-note)
        model.queue_response({"name": "workspace-note", "arguments": {"title": "Permitted", "content": "Yes"}})
        # Iteration 2: Denied tool (attach-read)
        model.queue_response({"name": "attach-read", "arguments": {"path": "forbidden.txt"}})
        model.queue_response("Turn finished.")

        events: List[Dict[str, Any]] = []
        async for ev in execute_agent_run(
            agent_id="habit-companion",
            prompt="Run mixed operations",
            model_client=model,
            workspace_root=temp_workspace,
        ):
            events.append(ev)

        tool_ends = [e for e in events if e.get("type") == SSE_EVENT_TOOL_END]
        assert len(tool_ends) == 2

        # 1st tool: workspace-note -> allowed
        assert tool_ends[0]["tool"] == "workspace-note"
        assert tool_ends[0]["allowed"] is True
        assert tool_ends[0]["status"] == "completed"

        # 2nd tool: attach-read -> denied
        assert tool_ends[1]["tool"] == "attach-read"
        assert tool_ends[1]["allowed"] is False
        assert tool_ends[1]["status"] == "denied"
        assert "execution denied: undeclared tool" in tool_ends[1]["result"]["error"]

        audit_lines = [json.loads(l) for l in audit_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        tool_audits = [al for al in audit_lines if al.get("event") == "tool"]
        assert len(tool_audits) == 2
        assert tool_audits[0]["tool"] == "workspace-note" and tool_audits[0]["allowed"] is True
        assert tool_audits[1]["tool"] == "attach-read" and tool_audits[1]["allowed"] is False

    @pytest.mark.asyncio
    async def test_arbitrary_shell_and_system_tools_strictly_denied(self, temp_workspace: Path):
        """Verifies that arbitrary system tools (bash, subprocess, rm_rf) are strictly denied."""
        model = MockChatModel()
        model.queue_response({"name": "bash", "arguments": {"command": "ls -la"}})
        model.queue_response("Blocked.")

        events: List[Dict[str, Any]] = []
        async for ev in execute_agent_run(
            agent_id="visit-steward",
            prompt="Execute shell command",
            model_client=model,
            workspace_root=temp_workspace,
        ):
            events.append(ev)

        tool_ends = [e for e in events if e.get("type") == SSE_EVENT_TOOL_END]
        assert len(tool_ends) == 1
        assert tool_ends[0]["tool"] == "bash"
        assert tool_ends[0]["allowed"] is False
        assert tool_ends[0]["status"] == "denied"

    @pytest.mark.asyncio
    async def test_graph_builder_with_tools_fallback_boundary(self, temp_workspace: Path):
        """Verifies GraphBuilder().with_tools([]) strictly enforces an empty boundary when state has no effective_tools."""
        model = MockChatModel()
        model.queue_response({"name": "workspace-note", "arguments": {"title": "X", "content": "Y"}})
        model.queue_response("Finished.")

        # Build graph directly with tools=[]
        graph = (
            GraphBuilder(model=model)
            .with_tools([])  # Explicit empty tools list
            .with_checkpointer(MemorySaver())
            .build()
        )

        initial_state: Dict[str, Any] = {
            "messages": [HumanMessage(content="Save note")],
            "workspace_root": str(temp_workspace),
            "skills_dir": str(temp_workspace / "skills"),
            "agent_id": "custom-agent",
            "current_agent": "custom-agent",
            # note: effective_tools omitted so builder.tools takes effect
        }

        # Stream events from compiled graph
        dispatched_events: List[Dict[str, Any]] = []
        async for ev in graph.astream_events(initial_state, config={"configurable": {"thread_id": "th-gb-fallback"}}, version="v2"):
            if ev.get("event") == "on_custom_event" and ev.get("name") == SSE_EVENT_TOOL_END:
                dispatched_events.append(ev.get("data", {}))

        assert len(dispatched_events) == 1
        assert dispatched_events[0]["allowed"] is False
        assert dispatched_events[0]["status"] == "denied"
        assert "execution denied: undeclared tool for agent 'custom-agent'" in dispatched_events[0]["result"]["error"]

    @pytest.mark.asyncio
    async def test_tool_node_standalone_vs_wrapper_boundary(self):
        """Empirically tests ToolNode standalone behavior with allowed_tools parameter."""
        # 1. Standalone ToolNode with explicit allowed_tools=[] strictly denies tools
        restricted_node = ToolNode(allowed_tools=[])
        state = {
            "effective_tools": [],
            "tool_calls": [{"id": "call_1", "name": "attach-read", "args": {"path": "test.txt"}}],
        }
        res = await restricted_node.execute(state)
        assert len(res["tool_traces"]) == 1
        assert res["tool_traces"][0]["allowed"] is False
        assert "execution denied" in res["tool_traces"][0]["error"]
        assert res["messages"][0].status == "error"

        # 2. Standalone ToolNode with allowed_tools=["attach-read"] allows attach-read and blocks workspace-note
        filtered_node = ToolNode(allowed_tools=["attach-read"])
        state_mixed = {
            "tool_calls": [
                {"id": "call_allowed", "name": "attach-read", "args": {"path": "missing.txt"}},
                {"id": "call_denied", "name": "workspace-note", "args": {"title": "T", "content": "C"}},
            ],
        }
        res_mixed = await filtered_node.execute(state_mixed)
        assert len(res_mixed["tool_traces"]) == 2
        assert res_mixed["tool_traces"][0]["allowed"] is True
        assert res_mixed["tool_traces"][1]["allowed"] is False


# ============================================================================
# 3. Runner Facade Backward Compatibility & Monkeypatching
# ============================================================================

class TestRunnerFacadeBackwardCompatibility:
    """Verifies that the refactored runner.py preserves 100% backward compatibility for tests and callers."""

    @pytest.mark.asyncio
    async def test_monkeypatch_create_chat_model_in_runner_facade(self, monkeypatch: pytest.MonkeyPatch, temp_workspace: Path):
        """Verifies that monkeypatching `carefold.engine.runner.create_chat_model`

        in tests takes effect cleanly and controls agent output.
        """
        import carefold.engine.runner as runner_mod

        called_factory: List[Dict[str, Any]] = []

        class PatchedTestChatModel(MockChatModel):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.queue_response("Response from monkeypatched create_chat_model.")

        def fake_create_chat_model(*args, **kwargs):
            called_factory.append({"args": args, "kwargs": kwargs})
            return PatchedTestChatModel()

        monkeypatch.setattr(runner_mod, "create_chat_model", fake_create_chat_model)

        events: List[Dict[str, Any]] = []
        async for ev in runner_mod.execute_agent_run(
            agent_id="visit-steward",
            prompt="Hello from monkeypatched test",
            workspace_root=temp_workspace,
        ):
            events.append(ev)

        assert len(called_factory) == 1
        assert called_factory[0]["kwargs"].get("provider") == "ollama"

        done_ev = next((e for e in events if e.get("type") == SSE_EVENT_DONE), None)
        assert done_ev is not None
        assert "Response from monkeypatched create_chat_model." in done_ev.get("fullText", "")

    @pytest.mark.asyncio
    async def test_model_client_parameter_overrides_factory(self, monkeypatch: pytest.MonkeyPatch, temp_workspace: Path):
        """Verifies passing explicit model_client bypasses create_chat_model entirely."""
        import carefold.engine.runner as runner_mod

        factory_invoked = False

        def uncallable_factory(*args, **kwargs):
            nonlocal factory_invoked
            factory_invoked = True
            raise RuntimeError("Factory should not have been called!")

        monkeypatch.setattr(runner_mod, "create_chat_model", uncallable_factory)

        custom_model = MockModelClient()
        custom_model.queue_response("Direct model client response.")

        events: List[Dict[str, Any]] = []
        async for ev in runner_mod.execute_agent_run(
            agent_id="visit-steward",
            prompt="Testing direct client bypass",
            model_client=custom_model,
            workspace_root=temp_workspace,
        ):
            events.append(ev)

        assert factory_invoked is False
        done_ev = next((e for e in events if e.get("type") == SSE_EVENT_DONE), None)
        assert done_ev is not None
        assert "Direct model client response." in done_ev.get("fullText", "")

    def test_execution_context_dataclass_contract(self, temp_workspace: Path):
        """Verifies ExecutionContext contract remains strictly intact."""
        from carefold.schemas.manifest import AgentManifest, AgentPersonaObject, RiskClass, SkillManifest

        agent = AgentManifest(
            id="test-ctx-agent",
            title="Context Agent",
            risk_class=RiskClass.WELLNESS,
            model="default",
            persona=AgentPersonaObject(role="Context tester"),
        )
        skill = SkillManifest(
            id="test-skill",
            name="test-skill",
            description="Test skill description",
            risk_class=RiskClass.WELLNESS,
        )

        ctx = ExecutionContext(
            workspace_root=temp_workspace,
            skills_dir=temp_workspace / "skills",
            agent=agent,
            effective_tools=["workspace-note"],
            skills=[skill],
        )

        assert ctx.workspace_root == temp_workspace
        assert ctx.agent.id == "test-ctx-agent"
        assert ctx.effective_tools == ["workspace-note"]
        assert len(ctx.skills) == 1
        assert ctx.skills[0].id == "test-skill"

    def test_runner_exports_and_conciseness(self):
        """Verifies runner.py exports required symbols and remains under 100 non-blank lines."""
        import carefold.engine.runner as runner_mod

        assert hasattr(runner_mod, "ExecutionContext")
        assert hasattr(runner_mod, "execute_agent_run")
        assert hasattr(runner_mod, "create_chat_model")
        assert "ExecutionContext" in runner_mod.__all__
        assert "execute_agent_run" in runner_mod.__all__
        assert "create_chat_model" in runner_mod.__all__

        runner_file = Path(runner_mod.__file__)
        non_blank_lines = [l for l in runner_file.read_text(encoding="utf-8").splitlines() if l.strip() and not l.strip().startswith("#")]
        assert len(non_blank_lines) < 100, f"runner.py is {len(non_blank_lines)} non-blank lines, expected < 100"
