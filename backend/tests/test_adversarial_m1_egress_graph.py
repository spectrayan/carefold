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

"""Adversarial stress and empirical verification suite for Milestone 1 (R1 & R2).

Empirically challenges:
1. Single Graph Execution Consolidation & Choke Point Bypass Resistance:
   - Verifies engine/graph.py:create_agent_graph constructs strictly via GraphBuilder.
   - Confirms that tool executions route unconditionally through ToolNode and execute_tool_call.
   - Verifies fail-closed behavior on missing or empty profile_id / user_id.
   - Confirms undeclared tools are denied by ToolNode.
   - Verifies tool loop iteration ceilings prevent infinite recursion.
2. Network Egress Policy in execute_tool_call:
   - Probes subdomain spoofing, URL credentials (@), path traversal, IP addresses, and metadata endpoints.
   - Tests parameter smuggling with multiple destination keys.
   - Tests URI schemes (file, gopher, ftp, ipv6).
   - Verifies case-insensitivity and port variations for authorized hostnames.
   - Validates that external write tools without declared data_flows fail closed.
   - Verifies monotone taint tracking across untrusted tool executions.
3. Multi-turn Reentrancy:
   - Stress-tests multi-turn conversational loops on identical thread_ids without premature halts.
   - Tests alternating turns with tool executions and state cleanliness.
   - Verifies reentrancy and recovery after input guardrail clinical emergency refusals.
   - Tests rapid sequential turn execution without SQLite lock contention.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph

from carefold.constants.defaults import MAX_TOOL_ITERATIONS
from carefold.engine.builder import GraphBuilder
from carefold.engine.graph import create_agent_graph, tools_node
from carefold.engine.service import AgentExecutionService
from carefold.engine.tool_exec import (
    RiskTier,
    TaintFlag,
    ToolContext,
    ToolSpec,
    execute_tool_call,
)
from carefold.schemas.tool import ToolResult
from carefold.workflows.nodes.tool_node import ToolNode
from tests.fixtures.fake_model import FakeListChatModel, MockChatModel


# ============================================================================
# Suite 1: Graph Consolidation & Choke Point Bypass Resistance
# ============================================================================

class TestGraphConsolidationAndBypassAdversarial:
    """Empirically tests that graph creation routes via GraphBuilder and cannot bypass execute_tool_call."""

    def test_create_agent_graph_routes_strictly_through_graph_builder(self):
        """Verifies that engine.graph.create_agent_graph delegates to GraphBuilder."""
        fake_model = FakeListChatModel(responses=["Hello world"])
        with patch("carefold.engine.builder.GraphBuilder") as mock_builder_cls:
            mock_builder_inst = mock_builder_cls.return_value
            mock_builder_inst.build.return_value = "fake_compiled_graph"

            res = create_agent_graph(fake_model)

            assert res == "fake_compiled_graph"
            mock_builder_cls.assert_called_once()
            mock_builder_inst.build.assert_called_once()

    def test_compiled_graph_contains_canonical_nodes_and_tool_wiring(self):
        """Verifies compiled graph topology contains canonical nodes from GraphBuilder."""
        fake_model = FakeListChatModel(responses=["Test response"])
        graph = create_agent_graph(fake_model)

        node_keys = set(graph.nodes.keys())
        expected_nodes = {"agent", "tools", "input_guardrail", "output_guardrail", "refusal", "suggestion", "audit"}
        for expected in expected_nodes:
            assert expected in node_keys, f"Expected node '{expected}' missing from compiled graph"

    @pytest.mark.asyncio
    async def test_tool_execution_in_graph_strictly_routes_through_execute_tool_call(self, tmp_path: Path):
        """Empirically tests that invoking a tool through the compiled graph routes through execute_tool_call."""
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)

        tool_call_dict = {
            "name": "workspace-note",
            "arguments": {"title": "ChokePointVerification", "content": "Audited note payload"},
        }

        mock_model = MockChatModel()
        mock_model.queue_response(tool_call_dict)
        mock_model.queue_response("Note recorded successfully.")

        ctx = ToolContext(
            user_id="verifier_user",
            profile_id="verifier_profile",
            workspace_root=tmp_path,
        )

        with patch("carefold.engine.tool_exec.execute_tool_call", wraps=execute_tool_call) as spy_exec:
            graph = create_agent_graph(
                model=mock_model,
                tools=["workspace-note"],
            )

            result = await graph.ainvoke(
                {
                    "messages": [HumanMessage(content="Please save an empirical verification note.")],
                    "agent_id": "visit-steward",
                    "effective_tools": ["workspace-note"],
                    "workspace_root": str(tmp_path),
                },
                config={"configurable": {"tool_context": ctx}},
            )

            assert spy_exec.called, "Tool execution must route through execute_tool_call choke point!"
            called_ctx = spy_exec.call_args[0][0]
            called_spec = spy_exec.call_args[0][1]
            assert isinstance(called_ctx, ToolContext)
            assert called_ctx.user_id == "verifier_user"
            assert called_ctx.profile_id == "verifier_profile"
            assert called_spec.name == "workspace-note"

    @pytest.mark.asyncio
    async def test_legacy_tools_node_in_graph_py_delegates_to_tool_node(self, tmp_path: Path):
        """Verifies that engine/graph.py:tools_node delegates to ToolNode and choke point."""
        ctx = ToolContext(
            user_id="legacy_user",
            profile_id="legacy_profile",
            workspace_root=tmp_path,
        )
        state = {
            "current_agent": "visit-steward",
            "effective_tools": ["workspace-note"],
            "tool_calls": [{"id": "c1", "name": "workspace-note", "args": {"title": "LegacyT", "content": "LegacyC"}}],
            "workspace_root": str(tmp_path),
            "tool_context": ctx,
        }

        with patch("carefold.engine.tool_exec.execute_tool_call", wraps=execute_tool_call) as spy_exec:
            res = await tools_node(state)
            assert spy_exec.called
            assert "messages" in res
            assert len(res["messages"]) == 1
            assert res["messages"][0].status == "success"

    @pytest.mark.asyncio
    async def test_tool_node_fails_closed_when_profile_id_missing_or_empty(self):
        """Verifies fail-closed behavior in ToolNode when profile_id is missing or empty."""
        node = ToolNode()
        state = {
            "tool_calls": [{"id": "c1", "name": "workspace-note", "args": {"title": "T", "content": "C"}}],
            "effective_tools": ["workspace-note"],
        }

        # Empty string
        with pytest.raises(ValueError) as exc1:
            await node.execute(state, config={"configurable": {"user_id": "u1", "profile_id": ""}})
        assert "requires a non-empty 'profile_id'. Fail-closed." in str(exc1.value)

        # Whitespace
        with pytest.raises(ValueError) as exc2:
            await node.execute(state, config={"configurable": {"user_id": "u1", "profile_id": "   \n "}})
        assert "requires a non-empty 'profile_id'. Fail-closed." in str(exc2.value)

    @pytest.mark.asyncio
    async def test_undeclared_tool_is_strictly_denied_in_consolidated_graph(self, tmp_path: Path):
        """Verifies that undeclared tools attempted by model are strictly denied by ToolNode."""
        mock_model = MockChatModel()
        mock_model.queue_response({
            "name": "unauthorized_exploit_tool",
            "arguments": {"cmd": "whoami"},
        })
        mock_model.queue_response("Execution finished.")

        ctx = ToolContext(
            user_id="u1",
            profile_id="p1",
            workspace_root=tmp_path,
        )

        graph = create_agent_graph(
            model=mock_model,
            tools=["workspace-note"],
        )

        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content="Run exploit")],
                "agent_id": "visit-steward",
                "effective_tools": ["workspace-note"],
                "workspace_root": str(tmp_path),
            },
            config={"configurable": {"tool_context": ctx}},
        )

        messages = result.get("messages", [])
        tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
        assert len(tool_msgs) >= 1
        denied_msg = tool_msgs[0]
        assert denied_msg.status == "error"
        assert "Tool 'unauthorized_exploit_tool' execution denied: undeclared tool for agent 'visit-steward'." in denied_msg.content

    @pytest.mark.asyncio
    async def test_tool_loop_max_iterations_ceiling_enforced(self, tmp_path: Path):
        """Verifies that an agent repeatedly requesting tools is stopped at MAX_TOOL_ITERATIONS."""
        mock_model = MockChatModel()
        # Queue 5 consecutive tool calls (exceeding MAX_TOOL_ITERATIONS = 3)
        for i in range(5):
            mock_model.queue_response({
                "name": "workspace-note",
                "arguments": {"title": f"Note_{i}", "content": f"Content_{i}"},
            })

        ctx = ToolContext(
            user_id="u1",
            profile_id="p1",
            workspace_root=tmp_path,
        )

        graph = create_agent_graph(
            model=mock_model,
            tools=["workspace-note"],
        )

        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content="Infinite note loop")],
                "agent_id": "visit-steward",
                "effective_tools": ["workspace-note"],
                "workspace_root": str(tmp_path),
            },
            config={"configurable": {"tool_context": ctx}},
        )

        # Iteration count must not exceed MAX_TOOL_ITERATIONS
        assert result.get("iteration_count", 0) <= MAX_TOOL_ITERATIONS


# ============================================================================
# Suite 2: Network Egress Policy in execute_tool_call
# ============================================================================

class TestNetworkEgressPolicyAdversarial:
    """Empirically stress-tests network egress filtering against spec.data_flows."""

    @pytest.mark.asyncio
    async def test_egress_subdomain_spoofing_attempts_are_blocked(self):
        """Probes subdomain and domain suffix spoofing attacks against allowlist."""
        ctx = ToolContext(user_id="u1", profile_id="p1")

        async def mock_executor(args, c):
            return ToolResult(success=True, output="sensitive_data")

        spec = ToolSpec(
            name="fetch_ehr",
            risk_tier="read",
            data_flows=("hospital.org",),
            executor=mock_executor,
        )

        attack_urls = [
            "https://evil-hospital.org/api",
            "https://hospital.org.evil-domain.com/api",
            "https://sub.hospital.org/api",  # Subdomain not explicitly in data_flows
            "https://hospital.org@evil-exfiltration.net/data",  # Credential tricking
            "https://evil.org/hospital.org",  # Path confusion
            "https://not-hospital.org",
        ]

        for attack_url in attack_urls:
            res = await execute_tool_call(ctx, spec, {"url": attack_url})
            assert res.success is False, f"Egress to '{attack_url}' should have been blocked!"
            assert "Security violation: Network egress to host" in res.error

    @pytest.mark.asyncio
    async def test_egress_cloud_metadata_and_localhost_ssrf_blocked(self):
        """Verifies SSRF targeting cloud metadata and local loopback interfaces are blocked."""
        ctx = ToolContext(user_id="u1", profile_id="p1")

        async def mock_executor(args, c):
            return ToolResult(success=True, output="internal_data")

        spec = ToolSpec(
            name="query_endpoint",
            risk_tier="read",
            data_flows=("api.approved-partner.com",),
            executor=mock_executor,
        )

        ssrf_targets = [
            "http://169.254.169.254/latest/meta-data/",
            "http://169.254.169.254:80/latest/user-data",
            "http://127.0.0.1:8000/api/keys",
            "http://127.0.0.1:11434/api/generate",
            "http://localhost:8080/admin",
            "http://0.0.0.0:8000/status",
        ]

        for target in ssrf_targets:
            res = await execute_tool_call(ctx, spec, {"url": target})
            assert res.success is False, f"SSRF target '{target}' should have been rejected!"
            assert "Security violation: Network egress to host" in res.error

    @pytest.mark.asyncio
    async def test_egress_parameter_smuggling_with_multiple_destination_keys(self):
        """Verifies attacker cannot smuggle unauthorized URL alongside a legitimate URL in different keys."""
        ctx = ToolContext(user_id="u1", profile_id="p1")

        async def mock_executor(args, c):
            return ToolResult(success=True)

        spec = ToolSpec(
            name="connector_sync",
            risk_tier="read",
            data_flows=("api.hospital.org",),
            executor=mock_executor,
        )

        # Legitimate 'url', but malicious 'endpoint' smuggled in same args
        smuggled_args = {
            "url": "https://api.hospital.org/v1/patient",
            "endpoint": "https://exfiltration.attacker.com/leak",
        }

        res = await execute_tool_call(ctx, spec, smuggled_args)
        assert res.success is False, "Smuggled parameter must be detected and rejected!"
        assert "Security violation: Network egress to host 'exfiltration.attacker.com'" in res.error

    @pytest.mark.asyncio
    async def test_egress_uri_schemes_and_special_targets_blocked(self):
        """Verifies special URI schemes (file, gopher, ftp, ipv6) outside data_flows are blocked."""
        ctx = ToolContext(user_id="u1", profile_id="p1")

        async def mock_executor(args, c):
            return ToolResult(success=True)

        spec = ToolSpec(
            name="resource_loader",
            risk_tier="read",
            data_flows=("api.hospital.org",),
            executor=mock_executor,
        )

        special_targets = [
            "file:///etc/passwd",
            "gopher://evil.attacker.com",
            "ftp://files.attacker.com/upload",
            "http://[::1]:8080/data",
            "http://0177.0.0.1/admin",
        ]

        for target in special_targets:
            res = await execute_tool_call(ctx, spec, {"url": target})
            assert res.success is False, f"Target '{target}' should have been blocked!"

    @pytest.mark.asyncio
    async def test_egress_checks_all_destination_keys(self):
        """Verifies egress checks examine all parameter keys (url, endpoint, host, target_url, base_url)."""
        ctx = ToolContext(user_id="u1", profile_id="p1")

        async def mock_executor(args, c):
            return ToolResult(success=True)

        spec = ToolSpec(
            name="connector_tool",
            risk_tier="read",
            data_flows=("allowed.service.com",),
            executor=mock_executor,
        )

        for key in ("url", "endpoint", "host", "target_url", "base_url"):
            res = await execute_tool_call(ctx, spec, {key: "https://evil.unauthorized.com/test"})
            assert res.success is False, f"Destination key '{key}' was not filtered!"
            assert "Security violation: Network egress to host 'evil.unauthorized.com'" in res.error

    @pytest.mark.asyncio
    async def test_write_external_without_data_flows_fails_closed(self):
        """Verifies external write tools lacking declared data_flows fail closed."""
        ctx = ToolContext(user_id="u1", profile_id="p1")

        async def mock_post(args, c):
            return ToolResult(success=True)

        spec = ToolSpec(
            name="webhook_sender",
            risk_tier="write_external",
            data_flows=(),  # Undeclared / empty data_flows
            executor=mock_post,
        )

        res = await execute_tool_call(ctx, spec, {"endpoint": "https://api.external.com/push"})
        assert res.success is False
        assert "External egress tool 'webhook_sender' has no authorized data_flows configured." in res.error

    @pytest.mark.asyncio
    async def test_authorized_host_allows_ports_and_case_variations(self):
        """Verifies legitimate hostnames with port numbers and varying cases are accepted."""
        ctx = ToolContext(user_id="u1", profile_id="p1")

        async def mock_executor(args, c):
            return ToolResult(success=True, output="ok")

        spec = ToolSpec(
            name="fetch_records",
            risk_tier="read",
            data_flows=("api.hospital.org",),
            executor=mock_executor,
        )

        valid_targets = [
            "https://api.hospital.org/v1/patient",
            "https://api.hospital.org:8443/v1/patient",  # Non-standard port
            "https://API.HOSPITAL.ORG/v1/patient",        # Uppercase
            "api.hospital.org",                          # Raw host without scheme
        ]

        for target in valid_targets:
            res = await execute_tool_call(ctx, spec, {"url": target})
            assert res.success is True, f"Target '{target}' should have succeeded!"
            assert res.output == "ok"

    @pytest.mark.asyncio
    async def test_untrusted_tool_taints_context_monotonically(self):
        """Verifies untrusted tools set TaintFlag monotonically."""
        ctx = ToolContext(user_id="u1", profile_id="p1")
        assert not bool(ctx.taint)

        async def untrusted_exec(args, c):
            return ToolResult(success=True, output="raw untrusted web scrapings")

        async def trusted_exec(args, c):
            return ToolResult(success=True, output="clean trusted note")

        untrusted_spec = ToolSpec(name="scraper", trust="untrusted", executor=untrusted_exec)
        trusted_spec = ToolSpec(name="trusted_calc", trust="trusted", executor=trusted_exec)

        # 1. Run untrusted tool -> taint set
        res1 = await execute_tool_call(ctx, untrusted_spec, {})
        assert res1.success is True
        assert bool(ctx.taint) is True

        # 2. Run trusted tool -> taint remains set (monotone)
        res2 = await execute_tool_call(ctx, trusted_spec, {})
        assert res2.success is True
        assert bool(ctx.taint) is True


# ============================================================================
# Suite 3: Multi-turn Reentrancy
# ============================================================================

class TestMultiTurnReentrancyAdversarial:
    """Empirically stress-tests continuous multi-turn execution on identical threads."""

    @pytest.mark.asyncio
    async def test_five_consecutive_turns_on_same_thread_execute_without_halt(self, tmp_path: Path):
        """Fires 5 consecutive conversational turns on the identical thread_id to ensure no premature halts."""
        mock = MockChatModel()
        mock.queue_response("Response Turn 1: Welcome to Carefold.")
        mock.queue_response("Response Turn 2: I can help review your visit questions.")
        mock.queue_response("Response Turn 3: Blood pressure of 120/80 is normal.")
        mock.queue_response("Response Turn 4: Let us prepare a checklist for your doctor.")
        mock.queue_response("Response Turn 5: All questions organized cleanly.")

        svc = AgentExecutionService(model=mock, workspace_root=tmp_path)
        thread_id = "test-reentrancy-5turns-001"

        turns = [
            "Hello, who are you?",
            "What can you assist me with?",
            "What does a blood pressure of 120/80 mean?",
            "Help me prepare my checklist.",
            "Thank you, summarize everything.",
        ]

        for idx, prompt in enumerate(turns, 1):
            events = []
            async for ev in svc.execute_turn(
                thread_id=thread_id,
                prompt=prompt,
                agent_id="visit-steward",
            ):
                events.append(ev)

            done_ev = next((e for e in events if e.get("type") == "done"), None)
            assert done_ev is not None, f"Turn {idx} failed to emit 'done' event!"
            assert done_ev["refused"] is False
            assert f"Response Turn {idx}" in done_ev["fullText"]

        # Verify full thread message history accumulated monotonically
        history = await svc.get_thread_history(thread_id)
        assert history["count"] == 10  # 5 HumanMessage + 5 AIMessage

    @pytest.mark.asyncio
    async def test_multi_turn_with_alternating_tool_invocations(self, temp_workspace: Path):
        """Tests multi-turn execution where turns alternate between tool execution and conversational responses."""
        notes_dir = temp_workspace / "workspace" / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)

        mock = MockChatModel()
        # Turn 1: Tool call to create Note 1
        mock.queue_response({
            "name": "workspace-note",
            "arguments": {"title": "NoteOne", "content": "First note content"},
        })
        mock.queue_response("Note 1 has been saved.")

        # Turn 2: Conversational response (no tool)
        mock.queue_response("I am ready for the next instruction.")

        # Turn 3: Tool call to create Note 2
        mock.queue_response({
            "name": "workspace-note",
            "arguments": {"title": "NoteTwo", "content": "Second note content"},
        })
        mock.queue_response("Note 2 has been saved.")

        # Turn 4: Conversational conclusion
        mock.queue_response("Both notes are saved and indexed.")

        svc = AgentExecutionService(model=mock, workspace_root=temp_workspace)
        thread_id = "test-reentrancy-alternating-tools-002"

        prompts = [
            "Please create NoteOne.",
            "What is our status?",
            "Now please create NoteTwo.",
            "Confirm what we have done.",
        ]

        for idx, p in enumerate(prompts, 1):
            events = []
            async for ev in svc.execute_turn(
                thread_id=thread_id,
                prompt=p,
                agent_id="visit-steward",
            ):
                events.append(ev)

            done_ev = next((e for e in events if e.get("type") == "done"), None)
            assert done_ev is not None, f"Turn {idx} failed to complete!"

        # Verify files were actually written in workspace (workspace-note tool slugifies title to lowercase)
        assert (notes_dir / "noteone.md").is_file()
        assert (notes_dir / "notetwo.md").is_file()

        # Check total messages in history:
        # Turn 1: Human, AI(tool_call), ToolMessage, AI(final) -> 4
        # Turn 2: Human, AI -> 2
        # Turn 3: Human, AI(tool_call), ToolMessage, AI(final) -> 4
        # Turn 4: Human, AI -> 2
        # Total = 12 messages
        history = await svc.get_thread_history(thread_id)
        assert history["count"] == 12

    @pytest.mark.asyncio
    async def test_reentrancy_after_clinical_emergency_refusal(self, tmp_path: Path):
        """Verifies that an emergency refusal on Turn 1 does not freeze the thread for Turn 2."""
        mock = MockChatModel()
        # Turn 1 triggers refusal before model is reached, but we queue a response for Turn 2
        mock.queue_response("Normal blood pressure is usually around 120/80 mmHg.")

        svc = AgentExecutionService(model=mock, workspace_root=tmp_path)
        thread_id = "test-reentrancy-after-refusal-003"

        # Turn 1: Acute life-threatening emergency prompt
        t1_events = []
        async for ev in svc.execute_turn(
            thread_id=thread_id,
            prompt="I have crushing chest pain radiating to my jaw and I can barely breathe.",
            agent_id="visit-steward",
        ):
            t1_events.append(ev)

        t1_done = next((e for e in t1_events if e.get("type") == "done"), None)
        assert t1_done is not None
        assert t1_done["refused"] is True, "Turn 1 must trigger clinical safety refusal!"

        # Turn 2: Normal non-emergency clinical education question on the SAME thread
        t2_events = []
        async for ev in svc.execute_turn(
            thread_id=thread_id,
            prompt="What is normal blood pressure?",
            agent_id="visit-steward",
        ):
            t2_events.append(ev)

        t2_done = next((e for e in t2_events if e.get("type") == "done"), None)
        assert t2_done is not None
        assert t2_done["refused"] is False, "Turn 2 must NOT be refused after previous turn refusal!"
        assert "Normal blood pressure" in t2_done["fullText"]

    @pytest.mark.asyncio
    async def test_rapid_sequential_turns_sqlite_stress(self, tmp_path: Path):
        """Fires 8 rapid sequential turns without pause to verify SQLite checkpointer lock concurrency."""
        svc = AgentExecutionService(workspace_root=tmp_path)
        thread_id = "test-rapid-sqlite-004"

        for i in range(8):
            mock = MockChatModel()
            mock.queue_response(f"Fast reply {i}")
            svc.model = mock

            events = []
            async for ev in svc.execute_turn(
                thread_id=thread_id,
                prompt=f"Fast turn {i}",
                agent_id="visit-steward",
            ):
                events.append(ev)

            done_ev = next((e for e in events if e.get("type") == "done"), None)
            assert done_ev is not None
            assert f"Fast reply {i}" in done_ev["fullText"]

        history = await svc.get_thread_history(thread_id)
        assert history["count"] == 16
