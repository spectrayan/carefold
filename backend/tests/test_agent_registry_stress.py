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

"""Agent Registry and Tool Permission Boundaries Stress Test Suite.

Adversarially verifies:
1. ToolNode permission boundaries:
   - Strict deny-by-default when `state["effective_tools"] = []`.
   - Constructor `allowed_tools` allowlist enforcement (both empty set and restricted set).
   - Precedence order: constructor `allowed_tools` > `state["effective_tools"]` > `state["allowed_tools"]` > default closed tools.
   - Multiple batch tool calls, malformed argument handling, missing call IDs, blank tool names.
   - AIMessage tool call extraction under empty and restricted tool sets.
2. OrchestratorNode dynamic routing & AgentRegistry boundaries:
   - Routing decision parsing (structured output, code-fenced json, unstructured fallback).
   - Non-existent and disallowed agent fallback to delegatable agents.
   - Pre-routed bypass normalization.
   - None model fallback.
   - AgentRegistry delegation filtering (`can_delegate=True` exclusion).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from carefold.agents.registry import AgentRegistry
from carefold.constants.agents import (
    AGENT_BENEFITS_GUIDE,
    AGENT_DOCUMENT_EXTRACTOR,
    AGENT_HABIT_COMPANION,
    AGENT_ORCHESTRATOR,
    AGENT_VISIT_STEWARD,
    TOOL_ATTACH_READ,
    TOOL_DELEGATE_TO_AGENT,
    TOOL_LIST_AGENTS,
    TOOL_WORKSPACE_NOTE,
)
from carefold.schemas.manifest import AgentManifest
from carefold.tools.registry import CLOSED_TOOL_DEFINITIONS
from carefold.workflows.nodes.orchestrator_node import OrchestratorDecision, OrchestratorNode
from carefold.workflows.nodes.tool_node import ToolNode
from tests.fixtures.fake_model import FakeListChatModel


# ============================================================================
# Section 1: ToolNode Permission Boundaries & Deny-by-Default
# ============================================================================

@pytest.mark.asyncio
async def test_tool_node_effective_tools_empty_list_denies_all_tools(temp_workspace: Path):
    """Verify that when state['effective_tools'] = [], ALL tool calls are strictly denied."""
    node = ToolNode()

    state = {
        "current_agent": "benefits-guide",
        "workspace_root": str(temp_workspace),
        "effective_tools": [],  # Explicit zero-tool manifest
        "tool_calls": [
            {"id": "call_note", "name": TOOL_WORKSPACE_NOTE, "args": {"title": "X", "content": "Y"}},
            {"id": "call_attach", "name": TOOL_ATTACH_READ, "args": {"path": "test.txt"}},
            {"id": "call_delegate", "name": TOOL_DELEGATE_TO_AGENT, "args": {"agent_id": "habit-companion"}},
        ],
    }

    result = await node.execute(state)

    traces = result["tool_traces"]
    tool_messages = result["tool_messages"]

    assert len(traces) == 3
    assert len(tool_messages) == 3

    for idx, trace in enumerate(traces):
        assert trace["allowed"] is False, f"Trace {idx} should have allowed=False"
        assert "execution denied" in trace["error"]
        assert trace["duration_ms"] == 0.0

    for idx, msg in enumerate(tool_messages):
        assert msg.status == "error"
        payload = json.loads(msg.content)
        assert payload["success"] is False
        assert "execution denied" in payload["error"]

    assert result["next_step"] == "tool_validator"
    assert "error" in result["tool_output"]


@pytest.mark.asyncio
async def test_tool_node_effective_tools_empty_list_overrides_state_allowed_tools(temp_workspace: Path):
    """Verify state['effective_tools'] = [] takes precedence over state['allowed_tools']."""
    node = ToolNode()

    # Both effective_tools=[] and allowed_tools=['workspace-note'] are present in state.
    # effective_tools is evaluated first and must take precedence.
    state = {
        "current_agent": "benefits-guide",
        "workspace_root": str(temp_workspace),
        "effective_tools": [],
        "allowed_tools": [TOOL_WORKSPACE_NOTE],
        "tool_calls": [
            {"id": "call_1", "name": TOOL_WORKSPACE_NOTE, "args": {"title": "Notes", "content": "Text"}},
        ],
    }

    result = await node.execute(state)
    traces = result["tool_traces"]
    assert len(traces) == 1
    assert traces[0]["allowed"] is False
    assert "execution denied" in traces[0]["error"]


@pytest.mark.asyncio
async def test_tool_node_constructor_allowed_tools_empty_list_overrides_everything(temp_workspace: Path):
    """Verify that ToolNode(allowed_tools=[]) strictly denies tools even if state claims permissions."""
    node = ToolNode(allowed_tools=[])

    state = {
        "current_agent": "benefits-guide",
        "workspace_root": str(temp_workspace),
        "effective_tools": [TOOL_WORKSPACE_NOTE, TOOL_ATTACH_READ],
        "allowed_tools": [TOOL_WORKSPACE_NOTE, TOOL_ATTACH_READ],
        "tool_calls": [
            {"id": "call_1", "name": TOOL_WORKSPACE_NOTE, "args": {"title": "Notes", "content": "Text"}},
        ],
    }

    result = await node.execute(state)
    traces = result["tool_traces"]
    assert len(traces) == 1
    assert traces[0]["allowed"] is False
    assert "execution denied" in traces[0]["error"]


@pytest.mark.asyncio
async def test_tool_node_constructor_explicit_allowlist_enforcement(temp_workspace: Path):
    """Verify ToolNode with explicit allowed_tools allows only matching tools and denies others."""
    node = ToolNode(allowed_tools=[TOOL_WORKSPACE_NOTE])

    state = {
        "current_agent": "benefits-guide",
        "workspace_root": str(temp_workspace),
        "tool_calls": [
            {"id": "call_ok", "name": TOOL_WORKSPACE_NOTE, "args": {"title": "Allowed Note", "content": "Body"}},
            {"id": "call_denied_1", "name": TOOL_ATTACH_READ, "args": {"path": "unauthorized.txt"}},
            {"id": "call_denied_2", "name": "system_exec", "args": {"cmd": "whoami"}},
            {"id": "call_denied_3", "name": "", "args": {}},
        ],
    }

    result = await node.execute(state)
    traces = result["tool_traces"]
    assert len(traces) == 4

    # Call 1: Authorized workspace-note
    assert traces[0]["tool"] == TOOL_WORKSPACE_NOTE
    assert traces[0]["allowed"] is True

    # Call 2: Undeclared attach-read
    assert traces[1]["tool"] == TOOL_ATTACH_READ
    assert traces[1]["allowed"] is False
    assert "execution denied" in traces[1]["error"]

    # Call 3: Bogus/malicious tool
    assert traces[2]["tool"] == "system_exec"
    assert traces[2]["allowed"] is False

    # Call 4: Empty tool name
    assert traces[3]["tool"] == ""
    assert traces[3]["allowed"] is False


@pytest.mark.asyncio
async def test_tool_node_ai_message_tool_calls_extraction_with_empty_tools(temp_workspace: Path):
    """Verify tool calls attached to the latest AIMessage in state['messages'] are intercepted when effective_tools = []."""
    node = ToolNode()

    ai_msg = AIMessage(
        content="I will create a note for you.",
        tool_calls=[
            {
                "id": "ai_call_1",
                "name": TOOL_WORKSPACE_NOTE,
                "args": {"title": "Checkup", "content": "Need follow-up"},
            }
        ],
    )

    state = {
        "current_agent": "visit-steward",
        "workspace_root": str(temp_workspace),
        "effective_tools": [],
        "messages": [
            HumanMessage(content="Remind me to follow up"),
            ai_msg,
        ],
    }

    result = await node.execute(state)
    traces = result["tool_traces"]
    assert len(traces) == 1
    assert traces[0]["tool"] == TOOL_WORKSPACE_NOTE
    assert traces[0]["allowed"] is False
    assert "execution denied" in traces[0]["error"]
    assert result["tool_messages"][0].tool_call_id == "ai_call_1"


@pytest.mark.asyncio
async def test_tool_node_malformed_arguments_and_fallback_execution_context(temp_workspace: Path):
    """Verify ToolNode handles malformed JSON arguments, non-dict args, and non-existent agent without crashing."""
    node = ToolNode(allowed_tools=[TOOL_WORKSPACE_NOTE])

    state = {
        "current_agent": "non-existent-agent-id",  # Triggers FallbackExecutionContext
        "workspace_root": str(temp_workspace),
        "tool_calls": [
            {"id": "call_str_json", "name": TOOL_WORKSPACE_NOTE, "args": '{"title": "Note1", "content": "Ok"}'},
            {"id": "call_bad_json", "name": TOOL_WORKSPACE_NOTE, "args": "{malformed json:"},
            {"name": TOOL_WORKSPACE_NOTE, "args": None},  # No 'id', args is None
        ],
    }

    result = await node.execute(state)
    traces = result["tool_traces"]
    tool_messages = result["tool_messages"]

    assert len(traces) == 3
    assert len(tool_messages) == 3

    # All calls were allowed through the permission boundary because name in allowed_tools
    for trace in traces:
        assert trace["allowed"] is True

    # Missing id got assigned a default
    assert tool_messages[2].tool_call_id == "call_2"


@pytest.mark.asyncio
async def test_tool_node_empty_tool_calls_graceful_handling():
    """Verify ToolNode returns clean structure when no tool calls are present."""
    node = ToolNode()
    state = {
        "current_agent": "benefits-guide",
        "messages": [HumanMessage(content="Hello")],
    }
    result = await node.execute(state)
    assert result["messages"] == []
    assert result["tool_messages"] == []
    assert result["tool_traces"] == []
    assert result["tool_output"] == ""
    assert result["next_step"] == "tool_validator"


# ============================================================================
# Section 2: OrchestratorNode Dynamic Routing & Resilience
# ============================================================================

@pytest.mark.asyncio
async def test_orchestrator_dynamic_prompt_incorporates_registry_catalog(temp_workspace: Path):
    """Verify OrchestratorNode dynamically formats the agent catalog from AgentRegistry."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    node = OrchestratorNode(registry=registry)

    prompt = node._build_system_prompt({})

    # Must contain delegatable agents and exclude orchestrator
    assert AGENT_BENEFITS_GUIDE in prompt
    assert AGENT_VISIT_STEWARD in prompt
    assert AGENT_HABIT_COMPANION in prompt
    assert AGENT_DOCUMENT_EXTRACTOR in prompt
    assert f"- **{AGENT_ORCHESTRATOR}**" not in prompt


@pytest.mark.asyncio
async def test_orchestrator_non_existent_agent_fallback_to_delegatable(temp_workspace: Path):
    """Verify that if the model hallucinates an invalid agent, OrchestratorNode falls back with audit info."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

    hallucinated_response = json.dumps({
        "agent_id": "non-existent-miracle-cure-agent",
        "reasoning": "This agent cures all ailments.",
        "instructions": "",
    })

    model = FakeListChatModel(responses=[hallucinated_response])
    node = OrchestratorNode(model=model, registry=registry)

    state = {"messages": [HumanMessage(content="Help me with medical question")]}
    result = await node.execute(state)

    delegatable_ids = {a.id for a in registry.get_delegatable_agents(exclude=AGENT_ORCHESTRATOR)}
    assert result["current_agent"] in delegatable_ids
    assert "not found in registry; fell back to" in result["orchestrator_reasoning"]


@pytest.mark.asyncio
async def test_orchestrator_unstructured_and_garbage_model_output(temp_workspace: Path):
    """Verify OrchestratorNode survives raw text and malformed garbage responses."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

    garbage_response = "I am a helpful assistant and I cannot route this in JSON."
    model = FakeListChatModel(responses=[garbage_response])
    node = OrchestratorNode(model=model, registry=registry)

    state = {"messages": [HumanMessage(content="What is my copay?")]}
    result = await node.execute(state)

    delegatable_ids = {a.id for a in registry.get_delegatable_agents(exclude=AGENT_ORCHESTRATOR)}
    assert result["current_agent"] in delegatable_ids
    assert "Parsed unstructured model response" in result["orchestrator_reasoning"]


@pytest.mark.asyncio
async def test_orchestrator_none_model_defaults_cleanly(temp_workspace: Path):
    """Verify OrchestratorNode with model=None routes cleanly to default specialist."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    node = OrchestratorNode(model=None, registry=registry)

    state = {"messages": [HumanMessage(content="Track my steps")]}
    result = await node.execute(state)

    delegatable_ids = {a.id for a in registry.get_delegatable_agents(exclude=AGENT_ORCHESTRATOR)}
    assert result["current_agent"] in delegatable_ids
    assert "Model unconfigured" in result["orchestrator_reasoning"]


@pytest.mark.asyncio
async def test_orchestrator_explicit_bypass_normalization(temp_workspace: Path):
    """Verify explicit routed_subgraph or current_agent bypasses LLM invocation and normalizes casing/hyphens."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    node = OrchestratorNode(model=None, registry=registry)

    # Test underscore to hyphen normalization
    state1 = {"current_agent": "benefits_guide"}
    res1 = await node.execute(state1)
    assert res1["current_agent"] == "benefits-guide"
    assert res1["next_step"] == "benefits-guide"

    # Test exact registered match
    state2 = {"routed_subgraph": "visit-steward"}
    res2 = await node.execute(state2)
    assert res2["current_agent"] == "visit-steward"
    assert res2["next_step"] == "visit-steward"


# ============================================================================
# Section 3: AgentRegistry Delegation & Tool Manifest Invariants
# ============================================================================

def test_agent_registry_delegatable_agents_excludes_orchestrator(temp_workspace: Path):
    """Verify get_delegatable_agents strictly excludes agents where can_delegate=True."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

    delegatable = registry.get_delegatable_agents()
    delegatable_ids = [a.id for a in delegatable]

    assert AGENT_ORCHESTRATOR not in delegatable_ids
    for agent in delegatable:
        assert agent.can_delegate is False

    # Check orchestrator manifest in registry has can_delegate=True
    orch = registry.get(AGENT_ORCHESTRATOR)
    if orch:
        assert orch.can_delegate is True


def test_agent_registry_effective_tools_map(temp_workspace: Path):
    """Verify effective_tools_map provides the resolved tool sets for each registered agent."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    tools_map = registry.effective_tools_map

    assert isinstance(tools_map, dict)
    assert AGENT_BENEFITS_GUIDE in tools_map
    assert AGENT_VISIT_STEWARD in tools_map
    assert AGENT_HABIT_COMPANION in tools_map
    assert AGENT_DOCUMENT_EXTRACTOR in tools_map

    # Document extractor must have extraction tools
    doc_tools = tools_map[AGENT_DOCUMENT_EXTRACTOR]
    assert "attach-read" in doc_tools
    assert "sanitize_pii" in doc_tools
    assert "extract_structured_data" in doc_tools
    assert "validate_grounding" in doc_tools
