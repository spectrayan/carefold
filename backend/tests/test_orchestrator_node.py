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

"""Unit and integration tests for OrchestratorNode and AgentExecutionNode."""

from pathlib import Path
import json
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from carefold.agents.registry import AgentRegistry
from carefold.constants.agents import (
    AGENT_BENEFITS_GUIDE,
    AGENT_DOCUMENT_EXTRACTOR,
    AGENT_HABIT_COMPANION,
    AGENT_ORCHESTRATOR,
    AGENT_VISIT_STEWARD,
)
from carefold.workflows.nodes.agent_execution_node import AgentExecutionNode
from carefold.workflows.nodes.orchestrator_node import OrchestratorDecision, OrchestratorNode
from carefold.workflows.nodes.supervisor_node import SupervisorNode
from tests.fixtures.fake_model import FakeListChatModel


def test_orchestrator_decision_schema():
    """Validates Pydantic serialization and defaults for OrchestratorDecision."""
    decision = OrchestratorDecision(
        agent_id="benefits-guide",
        reasoning="User is asking about copays and deductibles.",
        instructions="Focus on in-network specialist copays.",
    )
    assert decision.agent_id == "benefits-guide"
    assert decision.reasoning == "User is asking about copays and deductibles."
    assert decision.instructions == "Focus on in-network specialist copays."

    data = decision.model_dump()
    assert data["agent_id"] == "benefits-guide"

    # Default instructions
    d2 = OrchestratorDecision(agent_id="visit-steward", reasoning="Appointment prep.")
    assert d2.instructions == ""


def test_orchestrator_dynamic_prompt(temp_workspace: Path):
    """Confirms dynamic agent catalog from AgentRegistry is injected into _build_system_prompt."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    node = OrchestratorNode(registry=registry)

    prompt = node._build_system_prompt({})
    assert "Available Specialist Agents:" in prompt
    assert AGENT_BENEFITS_GUIDE in prompt
    assert AGENT_VISIT_STEWARD in prompt
    assert AGENT_HABIT_COMPANION in prompt
    assert AGENT_DOCUMENT_EXTRACTOR in prompt
    assert AGENT_ORCHESTRATOR not in prompt.split("Available Specialist Agents:")[1]


@pytest.mark.asyncio
async def test_orchestrator_explicit_routing_bypass(temp_workspace: Path):
    """Verifies that pre-routed routed_subgraph or current_agent bypasses model call."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    node = OrchestratorNode(registry=registry)

    state = {
        "current_agent": "benefits-guide",
        "messages": [HumanMessage(content="Hello")],
    }
    result = await node.execute(state)

    assert result["current_agent"] == "benefits-guide"
    assert result["routed_subgraph"] == "benefits-guide"
    assert result["next_step"] == "benefits-guide"
    assert "Explicitly requested" in result["orchestrator_reasoning"]


@pytest.mark.asyncio
async def test_orchestrator_model_unconfigured_fallback(temp_workspace: Path):
    """Verifies that OrchestratorNode falls back gracefully when model is None."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    node = OrchestratorNode(model=None, registry=registry)

    state = {"messages": [HumanMessage(content="I need help with my medication checklist")]}
    result = await node.execute(state)

    assert result["current_agent"] in registry.list_agent_ids()
    assert result["routed_subgraph"] == result["current_agent"]
    assert "Model unconfigured" in result["orchestrator_reasoning"]


@pytest.mark.asyncio
async def test_orchestrator_structured_invocation(temp_workspace: Path):
    """Verifies structured output routing to specialist agent using JSON model response."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    model_response = json.dumps({
        "agent_id": "benefits-guide",
        "reasoning": "Inquiry is regarding insurance deductible details.",
        "instructions": "Clarify in-network vs out-of-network rules.",
    })
    fake_model = FakeListChatModel(responses=[model_response])
    node = OrchestratorNode(model=fake_model, registry=registry)

    state = {"messages": [HumanMessage(content="What is my deductible?")]}
    result = await node.execute(state)

    assert result["current_agent"] == "benefits-guide"
    assert result["routed_subgraph"] == "benefits-guide"
    assert result["orchestrator_instructions"] == "Clarify in-network vs out-of-network rules."


@pytest.mark.asyncio
async def test_orchestrator_hallucinated_agent_fallback(temp_workspace: Path):
    """Verifies that an unknown agent_id returned by the model falls back safely."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    model_response = json.dumps({
        "agent_id": "non-existent-specialist-123",
        "reasoning": "Made up agent name.",
        "instructions": "",
    })
    fake_model = FakeListChatModel(responses=[model_response])
    node = OrchestratorNode(model=fake_model, registry=registry)

    state = {"messages": [HumanMessage(content="Random query")]}
    result = await node.execute(state)

    assert result["current_agent"] in registry.list_agent_ids()
    assert result["current_agent"] != "non-existent-specialist-123"
    assert "not found in registry" in result["orchestrator_reasoning"]


@pytest.mark.asyncio
async def test_agent_execution_resolves_persona_and_safety(temp_workspace: Path):
    """Validates persona instructions and forbidden safety preamble formatting."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    fake_model = FakeListChatModel(responses=["I am ready to help you navigate your benefits."])
    node = AgentExecutionNode(model=fake_model, registry=registry)

    state = {
        "current_agent": "benefits-guide",
        "messages": [HumanMessage(content="Hello")],
        "orchestrator_instructions": "Check copays carefully.",
    }
    result = await node.execute(state)

    assert result["current_agent"] == "benefits-guide"
    assert result["output"] == "I am ready to help you navigate your benefits."
    assert result["next_step"] == "output_guardrail"


@pytest.mark.asyncio
async def test_agent_execution_resolves_tools(temp_workspace: Path):
    """Validates effective tool resolution for active specialist agent."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    fake_model = FakeListChatModel(responses=["Checking documentation..."])
    node = AgentExecutionNode(model=fake_model, registry=registry)

    state = {
        "current_agent": "visit-steward",
        "messages": [HumanMessage(content="Read my note")],
    }
    result = await node.execute(state)

    assert "attach-read" in result["effective_tools"]
    assert "workspace-note" in result["effective_tools"]


@pytest.mark.asyncio
async def test_agent_execution_unknown_agent_error(temp_workspace: Path):
    """Verifies that execution with an unregistered agent ID routes to error."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    node = AgentExecutionNode(registry=registry)

    state = {"current_agent": "invalid-agent-xyz"}
    result = await node.execute(state)

    assert result["next_step"] == "error"
    assert "Unknown or unregistered agent ID" in result["error"]


@pytest.mark.asyncio
async def test_supervisor_node_fallback_regex(temp_workspace: Path):
    """Confirms parameterless SupervisorNode maintains deterministic regex routing."""
    node = SupervisorNode()

    # Benefits
    out_b = await node.execute({"messages": [HumanMessage(content="What is my in-network copay?")]})
    assert out_b["routed_subgraph"] == "benefits-guide"

    # Extraction
    out_e = await node.execute({"messages": [HumanMessage(content="Please extract my document")]})
    assert out_e["routed_subgraph"] == "document-extractor"


def test_orchestrator_decision_includes_required_docs():
    """Validates that OrchestratorDecision schema supports required_docs."""
    dec = OrchestratorDecision(
        agent_id="visit-steward",
        reasoning="Appointment prep",
        required_docs=["symptom_log_template.md", "questions_guide.md"],
    )
    assert dec.required_docs == ["symptom_log_template.md", "questions_guide.md"]
    data = dec.model_dump()
    assert "required_docs" in data
    assert data["required_docs"] == ["symptom_log_template.md", "questions_guide.md"]


@pytest.mark.asyncio
async def test_orchestrator_preflight_proactively_provisions_reference_doc(temp_workspace: Path):
    """Verifies that orchestrator proactively provisions missing reference docs before specialist runs."""
    from carefold.workflows.nodes.skill_generator_node import SkillGeneratorNode

    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    skill_gen = SkillGeneratorNode(skills_dir=temp_workspace / "skills")
    node = OrchestratorNode(registry=registry, skill_generator=skill_gen)

    # User explicitly asking for a symptom log via visit-steward
    state = {
        "current_agent": "visit-steward",
        "routed_subgraph": "visit-steward",
        "messages": [HumanMessage(content="I want to log my symptoms and build a timeline for my doctor appointment.")],
        "required_docs": ["clinical_timeline_tracker.md"],
    }

    result = await node.execute(state)

    assert result["current_agent"] == "visit-steward"
    assert "provisioned_docs" in result
    assert any("clinical_timeline_tracker.md" in p for p in result["provisioned_docs"])

    # Verify the document actually exists in the visit-prep references directory
    doc_file = temp_workspace / "skills" / "visit-prep" / "references" / "clinical_timeline_tracker.md"
    assert doc_file.is_file()
    content = doc_file.read_text(encoding="utf-8")
    assert "Clinical Timeline Tracker" in content

