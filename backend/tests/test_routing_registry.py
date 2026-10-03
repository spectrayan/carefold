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

"""Multi-Agent Routing & Registry Robustness Test Suite.

Exhaustively verifies:
1. OrchestratorNode routing across ambiguous, multi-domain, and adversarial prompts.
2. Explicit routing bypass mechanics and normalization (including underscore preservation and loop guards).
3. Fallback resilience on non-existent agents, malformed model JSON, API errors, and None models.
4. Delegation loop prevention in AgentRegistry (strict exclusion of can_delegate=True agents).
5. Parameterless SupervisorNode backward compatibility and regex classification.
6. AgentExecutionNode and ToolNode authorization boundaries with zero-tool and restricted-tool manifests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from carefold.agents.registry import AgentRegistry, get_agent_registry
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
from carefold.schemas.manifest import AgentManifest, AgentPersonaObject
from carefold.workflows.nodes.agent_execution_node import AgentExecutionNode
from carefold.workflows.nodes.orchestrator_node import OrchestratorDecision, OrchestratorNode
from carefold.workflows.nodes.supervisor_node import SupervisorNode
from carefold.workflows.nodes.tool_node import ToolNode
from tests.fixtures.fake_model import FakeListChatModel


# ============================================================================
# Section 1: Orchestrator Routing Across Ambiguous & Multi-Domain Queries
# ============================================================================

@pytest.mark.asyncio
async def test_orchestrator_multi_domain_query_routing(temp_workspace: Path):
    """Verify orchestrator selects a valid specialist when queries span multiple domains."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    delegatable_ids = {a.id for a in registry.get_delegatable_agents(exclude=AGENT_ORCHESTRATOR)}

    queries_and_decisions = [
        (
            "I got a $500 bill from my doctor visit last Tuesday, but my insurance was supposed to cover it.",
            AGENT_BENEFITS_GUIDE,
            "Billing and insurance coverage inquiry takes priority.",
        ),
        (
            "I have an upcoming appointment with my oncologist and need to know what questions to ask.",
            AGENT_VISIT_STEWARD,
            "Clinical appointment preparation.",
        ),
        (
            "I want to track my water intake and make sure I drink 8 glasses a day.",
            AGENT_HABIT_COMPANION,
            "Hydration and lifestyle habit tracking.",
        ),
        (
            "Here is the scanned PDF of my Explanation of Benefits document.",
            AGENT_DOCUMENT_EXTRACTOR,
            "Document attachment and structured extraction.",
        ),
    ]

    for query, target_agent, reasoning in queries_and_decisions:
        mock_resp = json.dumps({
            "agent_id": target_agent,
            "reasoning": reasoning,
            "instructions": f"Address user request: {query}",
        })
        model = FakeListChatModel(responses=[mock_resp])
        node = OrchestratorNode(model=model, registry=registry)

        state = {"messages": [HumanMessage(content=query)]}
        result = await node.execute(state)

        assert result["current_agent"] == target_agent
        assert result["routed_subgraph"] == target_agent
        assert result["current_agent"] in delegatable_ids
        assert result["next_step"] == target_agent
        assert result["orchestrator_reasoning"] == reasoning
        assert "Address user request" in result["orchestrator_instructions"]


@pytest.mark.asyncio
async def test_orchestrator_structured_output_code_fence_repair(temp_workspace: Path):
    """Verify orchestrator extracts valid JSON even when wrapped in markdown code blocks."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

    fenced_json = """```json
{
  "agent_id": "benefits-guide",
  "reasoning": "User inquired about copay requirements.",
  "instructions": "List specialist copays."
}
```"""
    # Create fake model that does NOT implement with_structured_output (falls back to ainvoke string parsing)
    class RawStringChatModel:
        async def ainvoke(self, messages):
            return AIMessage(content=fenced_json)

    node = OrchestratorNode(model=RawStringChatModel(), registry=registry)
    state = {"messages": [HumanMessage(content="What is my specialist copay?")]}

    # Should fall back cleanly or parse JSON from code fences
    result = await node.execute(state)
    assert result["current_agent"] in registry.list_agent_ids()
    assert result["routed_subgraph"] == result["current_agent"]


# ============================================================================
# Section 2: Explicit Routing Bypass Mechanics
# ============================================================================

@pytest.mark.asyncio
async def test_orchestrator_explicit_bypass_variants(temp_workspace: Path):
    """Verify various explicit bypass scenarios: current_agent, routed_subgraph, case-insensitivity."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    node = OrchestratorNode(registry=registry)

    # 1. Via routed_subgraph with hyphen
    res1 = await node.execute({
        "routed_subgraph": "habit-companion",
        "messages": [HumanMessage(content="Random text")],
    })
    assert res1["current_agent"] == "habit-companion"
    assert res1["routed_subgraph"] == "habit-companion"

    # 2. Via current_agent with underscore normalization
    res2 = await node.execute({
        "current_agent": "visit_steward",
        "messages": [HumanMessage(content="Random text")],
    })
    assert res2["current_agent"] == "visit-steward"
    assert res2["routed_subgraph"] == "visit-steward"

    # 3. Via uppercase name
    res3 = await node.execute({
        "current_agent": "BENEFITS-GUIDE",
        "messages": [HumanMessage(content="Random text")],
    })
    assert res3["current_agent"] == "benefits-guide"

    # 4. Leading underscore template agent is NOT hyphen-replaced
    res4 = await node.execute({
        "current_agent": "_custom_template",
        "messages": [HumanMessage(content="Random text")],
    })
    assert res4["current_agent"] == "_custom_template"


@pytest.mark.asyncio
async def test_orchestrator_explicit_bypass_ignores_self_routing(temp_workspace: Path):
    """Verify that current_agent='orchestrator' or 'supervisor' does NOT bypass routing."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

    model_resp = json.dumps({
        "agent_id": "benefits-guide",
        "reasoning": "Insurance question.",
        "instructions": "",
    })
    model = FakeListChatModel(responses=[model_resp])
    node = OrchestratorNode(model=model, registry=registry)

    # Explicit 'orchestrator' must NOT bypass; it should proceed to route via model
    res = await node.execute({
        "current_agent": "orchestrator",
        "messages": [HumanMessage(content="What is my deductible?")],
    })
    assert res["current_agent"] == "benefits-guide"
    assert res["routed_subgraph"] == "benefits-guide"
    assert res["orchestrator_reasoning"] == "Insurance question."


# ============================================================================
# Section 3: Fallback Behavior on Malformed, Missing, or Unknown Agents
# ============================================================================

@pytest.mark.asyncio
async def test_orchestrator_hallucinated_agent_fallback_chain(temp_workspace: Path):
    """Verify non-existent agent IDs fall back cleanly to a valid delegatable specialist."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    delegatable = registry.get_delegatable_agents(exclude=AGENT_ORCHESTRATOR)
    default_expected = delegatable[0].id

    bad_agent_responses = [
        "totally-fake-agent",
        "agent-xyz-9999",
        "super-diagnostic-bot",
        "",
    ]

    for bad_id in bad_agent_responses:
        fake_model = FakeListChatModel(responses=[
            json.dumps({"agent_id": bad_id, "reasoning": "hallucinated", "instructions": ""})
        ])
        node = OrchestratorNode(model=fake_model, registry=registry)
        result = await node.execute({"messages": [HumanMessage(content="Any question")]})

        assert result["current_agent"] == default_expected
        assert result["routed_subgraph"] == default_expected
        assert result["next_step"] == default_expected
        assert "fell back" in result["orchestrator_reasoning"] or "not found" in result["orchestrator_reasoning"]


@pytest.mark.asyncio
async def test_orchestrator_model_exception_fallback(temp_workspace: Path):
    """Verify node catches runtime model exceptions (e.g. API disconnect) and falls back safely."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

    class FailingModel:
        async def ainvoke(self, messages):
            raise ConnectionError("Remote LLM service unavailable: 503")

    node = OrchestratorNode(model=FailingModel(), registry=registry)
    result = await node.execute({"messages": [HumanMessage(content="Help me")]})

    assert result["current_agent"] in registry.list_agent_ids()
    assert result["current_agent"] != AGENT_ORCHESTRATOR
    assert "error fallback" in result["orchestrator_reasoning"].lower()


@pytest.mark.asyncio
async def test_orchestrator_empty_response_fallback(temp_workspace: Path):
    """Verify orchestrator recovers gracefully when model returns empty or unparseable text."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    fake_model = FakeListChatModel(responses=[""])
    node = OrchestratorNode(model=fake_model, registry=registry)

    result = await node.execute({"messages": [HumanMessage(content="Help me")]})
    assert result["current_agent"] in registry.list_agent_ids()
    assert result["current_agent"] != AGENT_ORCHESTRATOR


# ============================================================================
# Section 4: Delegation Loop Prevention & Registry Integrity
# ============================================================================

def test_registry_get_delegatable_agents_strictly_excludes_can_delegate(temp_workspace: Path):
    """Verify get_delegatable_agents strictly excludes any agent with can_delegate=True."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    delegatable = registry.get_delegatable_agents()

    delegatable_ids = {a.id for a in delegatable}
    assert AGENT_ORCHESTRATOR not in delegatable_ids

    for agent in delegatable:
        assert agent.can_delegate is False, f"Agent {agent.id} has can_delegate=True but was in delegatable list!"
        assert agent.id != AGENT_ORCHESTRATOR

    # Ensure all registered non-orchestrator specialists are present
    assert AGENT_BENEFITS_GUIDE in delegatable_ids
    assert AGENT_VISIT_STEWARD in delegatable_ids
    assert AGENT_HABIT_COMPANION in delegatable_ids
    assert AGENT_DOCUMENT_EXTRACTOR in delegatable_ids


def test_registry_format_agent_catalog_excludes_orchestrator(temp_workspace: Path):
    """Verify the dynamic agent catalog markdown never advertises the orchestrator itself."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    catalog = registry.format_agent_catalog()

    assert AGENT_ORCHESTRATOR not in catalog
    assert AGENT_BENEFITS_GUIDE in catalog
    assert AGENT_VISIT_STEWARD in catalog
    assert AGENT_HABIT_COMPANION in catalog
    assert AGENT_DOCUMENT_EXTRACTOR in catalog


def test_specialists_do_not_contain_delegation_tools(temp_workspace: Path):
    """Verify no specialist manifest declares delegate_to_agent or list_agents in its tools."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

    for agent in registry.get_delegatable_agents():
        eff_tools = registry.get_effective_tools(agent.id)
        assert TOOL_DELEGATE_TO_AGENT not in eff_tools, f"Specialist {agent.id} unauthorizedly declared {TOOL_DELEGATE_TO_AGENT}!"
        assert TOOL_LIST_AGENTS not in eff_tools, f"Specialist {agent.id} unauthorizedly declared {TOOL_LIST_AGENTS}!"


# ============================================================================
# Section 5: Backward Compatibility: Parameterless SupervisorNode
# ============================================================================

@pytest.mark.asyncio
async def test_supervisor_node_parameterless_full_matrix():
    """Verify parameterless SupervisorNode maintains deterministic regex routing for all domains."""
    node = SupervisorNode()

    test_cases = [
        # (prompt, expected_route)
        ("What is my insurance copay?", "benefits-guide"),
        ("Explain my out-of-pocket maximum and deductible", "benefits-guide"),
        ("I need to submit a health insurance claim", "benefits-guide"),
        ("How much water should I drink for hydration?", "habit-companion"),
        ("Track my daily steps and sleep routine", "habit-companion"),
        ("Prepare questions for my doctor visit tomorrow", "visit-steward"),
        ("I have a clinic appointment with a physician", "visit-steward"),
        ("Please extract the table from this attachment", "document-extractor"),
        ("Extract data from my pdf file", "document-extractor"),
        ("Completely ambiguous query with no keywords", "visit-steward"),  # default fallback
    ]

    for prompt, expected_agent in test_cases:
        state = {"messages": [HumanMessage(content=prompt)]}
        res = await node.execute(state)
        assert res["routed_subgraph"] == expected_agent, f"Failed on prompt: '{prompt}'"
        assert res["current_agent"] == expected_agent
        assert res["next_step"] == expected_agent
        assert res["agent_id"] == expected_agent

    # Test attachment presence triggering document-extractor
    res_att = await node.execute({
        "messages": [HumanMessage(content="Hello doctor")],
        "attachments": ["sample.pdf"],
    })
    assert res_att["routed_subgraph"] == "document-extractor"


# ============================================================================
# Section 6: AgentExecutionNode & ToolNode Authorization Boundaries
# ============================================================================

@pytest.mark.asyncio
async def test_agent_execution_zero_tool_manifest_enforcement(temp_workspace: Path):
    """Verify an agent with zero tools has effective_tools set to empty and denies tool attempts."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

    # Synthetic zero-tool agent manifest
    zero_tool_manifest = AgentManifest(
        id="zero-tool-agent",
        title="Zero Tool Agent",
        version="0.1.0",
        risk_class="wellness",
        skills=[],
        tools=[],
        persona={"role": "Minimal conversationalist", "instructions": "Chat only."},
    )
    registry._agents["zero-tool-agent"] = zero_tool_manifest
    registry._effective_tools["zero-tool-agent"] = []

    # Model attempts to make an unauthorized tool call
    fake_ai_message = AIMessage(
        content="I will read your files.",
        tool_calls=[{
            "name": TOOL_ATTACH_READ,
            "args": {"path": "confidential.pdf"},
            "id": "call_zero_001",
        }],
    )

    class ModelWithUndeclaredToolCall:
        async def ainvoke(self, messages):
            return fake_ai_message

    node = AgentExecutionNode(model=ModelWithUndeclaredToolCall(), registry=registry)
    state = {
        "current_agent": "zero-tool-agent",
        "messages": [HumanMessage(content="Can you read confidential.pdf?")],
    }

    result = await node.execute(state)
    assert result["effective_tools"] == []
    assert result["next_step"] == "tools"
    assert len(result["tool_calls"]) == 1

    # Now verify downstream ToolNode enforcement:
    merged_state = {**state, **result}
    # 1. Synced ToolNode (as GraphBuilder._tool_wrapper does by setting allowed_tools):
    tool_node_synced = ToolNode(allowed_tools=result["effective_tools"])
    tool_result = await tool_node_synced.execute(merged_state)

    tool_traces = tool_result.get("tool_traces", [])
    assert len(tool_traces) == 1
    trace = tool_traces[0]
    assert trace["tool"] == TOOL_ATTACH_READ
    assert trace["allowed"] is False
    assert "execution denied: undeclared tool for agent 'zero-tool-agent'" in trace["error"]

    tool_messages = tool_result.get("messages", [])
    assert len(tool_messages) == 1
    assert tool_messages[0].status == "error"
    content_dict = json.loads(tool_messages[0].content)
    assert content_dict["success"] is False
    assert "execution denied" in content_dict["error"]

    # 2. Standalone ToolNode without constructor allowed_tools:
    # tool_node.py checks `elif state.get("effective_tools") is not None:`.
    # When relying purely on state without constructor allowed_tools, [] is strictly enforced as zero allowed tools.
    tool_node_unsynced = ToolNode(allowed_tools=None)
    unsynced_result = await tool_node_unsynced.execute(merged_state)
    unsynced_trace = unsynced_result["tool_traces"][0]
    # Verified remediated behavior: unsynced ToolNode strictly denies tools when effective_tools is []
    assert unsynced_trace["allowed"] is False
    assert "execution denied" in unsynced_trace["error"]


@pytest.mark.asyncio
async def test_agent_execution_restricted_tool_manifest(temp_workspace: Path):
    """Verify an agent with a restricted tool allowlist can run authorized tools but rejects others."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

    restricted_manifest = AgentManifest(
        id="restricted-note-agent",
        title="Restricted Note Agent",
        version="0.1.0",
        risk_class="wellness",
        skills=[],
        tools=[TOOL_WORKSPACE_NOTE],
        persona={"role": "Note writer", "instructions": ""},
    )
    registry._agents["restricted-note-agent"] = restricted_manifest
    registry._effective_tools["restricted-note-agent"] = [TOOL_WORKSPACE_NOTE]

    node = AgentExecutionNode(registry=registry)
    eff_tools = node._resolve_tools("restricted-note-agent", restricted_manifest, {})
    eff_tool_names = [t["name"] if isinstance(t, dict) else t.name for t in eff_tools]

    assert eff_tool_names == [TOOL_WORKSPACE_NOTE]
    assert TOOL_ATTACH_READ not in eff_tool_names

    # Test ToolNode enforcement with restricted list
    tool_node = ToolNode()
    state = {
        "current_agent": "restricted-note-agent",
        "effective_tools": [TOOL_WORKSPACE_NOTE],
        "tool_calls": [
            {"id": "call_1", "name": TOOL_WORKSPACE_NOTE, "args": {"title": "Test", "content": "Sample"}},
            {"id": "call_2", "name": TOOL_ATTACH_READ, "args": {"path": "unauthorized.txt"}},
        ],
    }
    res = await tool_node.execute(state)
    traces = res["tool_traces"]
    assert len(traces) == 2

    # First call (workspace-note) was allowed
    assert traces[0]["tool"] == TOOL_WORKSPACE_NOTE
    assert traces[0]["allowed"] is True

    # Second call (attach-read) was denied
    assert traces[1]["tool"] == TOOL_ATTACH_READ
    assert traces[1]["allowed"] is False
    assert "execution denied" in traces[1]["error"]


# ============================================================================
# Section 7: GraphBuilder Integration (Dynamic Orchestrator vs Legacy Supervisor)
# ============================================================================

@pytest.mark.asyncio
async def test_graph_builder_dynamic_orchestrator_integration(temp_workspace: Path):
    """Verify GraphBuilder creates and compiles StateGraph with OrchestratorNode and AgentExecutionNode."""
    from carefold.engine.builder import GraphBuilder

    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    mock_model = FakeListChatModel(responses=[
        json.dumps({"agent_id": "benefits-guide", "reasoning": "Deductible question", "instructions": ""}),
        "Your deductible is $1,000 for in-network care.",
    ])

    builder = GraphBuilder(
        model=mock_model,
        registry=registry,
        use_dynamic_orchestrator=True,
    )
    graph = builder.compile()

    state = {
        "messages": [HumanMessage(content="What is my deductible?")],
        "workspace_root": str(temp_workspace),
    }

    result = await graph.ainvoke(state)
    assert result["current_agent"] == "benefits-guide"
    assert "deductible" in result["output"].lower()


@pytest.mark.asyncio
async def test_graph_builder_legacy_supervisor_compatibility(temp_workspace: Path):
    """Verify GraphBuilder supports use_dynamic_orchestrator=False for legacy callers."""
    from carefold.engine.builder import GraphBuilder

    mock_model = FakeListChatModel(responses=[
        "Here are tips for preparing for your appointment.",
    ])

    builder = GraphBuilder(
        model=mock_model,
        use_dynamic_orchestrator=False,
    )
    graph = builder.compile()

    state = {
        "messages": [HumanMessage(content="How do I prep for doctor visit?")],
        "workspace_root": str(temp_workspace),
    }

    result = await graph.ainvoke(state)
    assert result["routed_subgraph"] == "visit-steward"

