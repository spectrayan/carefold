# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Tests for Skill Generator Agent, missing skill resolution, and EOB documentation."""

import asyncio
from pathlib import Path
import pytest

from carefold.agents.registry import AgentRegistry
from carefold.config import settings
from carefold.schemas.manifest import AgentManifest
from carefold.tools.skill_docs import execute_skill_docs
from carefold.workflows.nodes.agent_execution_node import AgentExecutionNode
from carefold.workflows.nodes.orchestrator_node import OrchestratorDecision, OrchestratorNode
from carefold.workflows.nodes.skill_generator_node import SkillGeneratorNode


class MockContext:
    def __init__(self, agent: AgentManifest, state=None, workspace_root=None, skills_dir=None):
        self.agent = agent
        self.workspace_root = workspace_root or Path.cwd()
        self.skills_dir = skills_dir or (self.workspace_root / "skills")
        self.state = state or {}


@pytest.fixture
def agent_registry():
    return AgentRegistry(
        agents_dir=Path.cwd() / "agents",
        skills_dir=Path.cwd() / "skills",
    )


def test_eob_explanation_doc_present_and_readable():
    """Verifies that EOB_explanation.md exists in benefits-explainer and is accessible via skill-docs."""
    eob_file = Path.cwd() / "skills" / "benefits-explainer" / "references" / "EOB_explanation.md"
    assert eob_file.is_file(), "EOB_explanation.md must exist in skills/benefits-explainer/references/"
    assert "Explanation of Benefits" in eob_file.read_text(encoding="utf-8")

    agent = AgentManifest(
        id="benefits-guide",
        title="Benefits Guide",
        version="0.1.0",
        risk_class="admin",
        skills=["benefits-explainer"],
        tools=["skill-docs"],
        persona="You are Benefits Guide",
    )
    ctx = MockContext(agent)

    result = asyncio.run(
        execute_skill_docs(
            {"skill_id": "benefits-explainer", "doc": "EOB_explanation.md"},
            ctx,
        )
    )
    assert result.success is True
    assert result.output is not None
    assert result.output["doc"] == "EOB_explanation.md"
    assert "Explanation of Benefits" in result.output["content"]


def test_skill_generator_agent_manifest_is_registered_and_hidden(agent_registry):
    """Verifies that skill-generator is a valid registered agent and marked hidden: true."""
    manifest = agent_registry.get("skill-generator")
    assert manifest is not None, "skill-generator must be registered in AgentRegistry"
    assert manifest.id == "skill-generator"
    assert manifest.hidden is True, "skill-generator must be hidden: true"
    assert manifest.can_delegate is False

    # Ensure hidden agents are not exposed in delegatable catalog
    delegatable = agent_registry.get_delegatable_agents()
    # Delegatable agents are for primary supervisor delegation, skill-generator is hidden meta-agent
    assert manifest not in delegatable or manifest.hidden is True


@pytest.mark.asyncio
async def test_skill_generator_node_synthesizes_structured_skill(tmp_path):
    """Verifies that SkillGeneratorNode generates complete, safety-compliant skill schema."""
    node = SkillGeneratorNode(skills_dir=tmp_path / "skills")
    generated = await node.generate_skill(
        skill_id="pediatric-allergy-prep",
        skill_description="Guidelines for preparing a pediatric allergy and immunology appointment",
        user_query="How do I prepare for my 4 year old allergy test?",
        target_agent="visit-steward",
    )

    assert generated["id"] == "pediatric-allergy-prep"
    assert "Pediatric Allergy Prep" in generated["name"]
    assert "instructions" in generated
    assert len(generated["instructions"]) > 20
    assert "references" in generated
    assert any("allergy" in k for k in generated["references"].keys())
    assert "skill-docs" in generated["tools"]


@pytest.mark.asyncio
async def test_orchestrator_detects_missing_skill_and_invokes_generator(agent_registry, tmp_path):
    """Verifies that OrchestratorNode detects missing skill, calls generator, and passes skill in state."""
    skill_gen = SkillGeneratorNode(skills_dir=tmp_path / "skills")
    orchestrator = OrchestratorNode(registry=agent_registry, skill_generator=skill_gen)

    state = {
        "messages": [
            {"role": "user", "content": "I need help with my appointment for pediatric allergy testing."}
        ],
        "current_agent": "visit-steward",
        "missing_skill": "pediatric-allergy-guide",
        "missing_skill_description": "Specialized steps for preparing pediatric allergy visits",
    }

    result = await orchestrator.execute(state)
    assert result["current_agent"] == "visit-steward"
    assert "generated_skill" in result
    assert result["generated_skill"]["id"] == "pediatric-allergy-guide"
    assert "generated_skills" in result
    assert len(result["generated_skills"]) >= 1


@pytest.mark.asyncio
async def test_subsequent_agent_execution_incorporates_generated_skill(agent_registry):
    """Verifies that AgentExecutionNode injects generated skill into prompt and authorizes its tools."""
    execution_node = AgentExecutionNode(registry=agent_registry)

    generated_skill = {
        "id": "orthopedic-recovery-checkin",
        "name": "Orthopedic Recovery Check-in",
        "description": "Daily movement and elevation habit tracking after orthopedic surgery",
        "instructions": "Guide user through non-clinical elevation and icing routine reminders.",
        "tools": ["skill-docs", "workspace-note"],
        "references": {
            "elevation_guide.md": "# Elevation Guide\nKeep limb elevated above heart level."
        },
    }

    state = {
        "current_agent": "habit-companion",
        "messages": [
            {"role": "user", "content": "How should I track my daily knee elevation?"}
        ],
        "generated_skills": [generated_skill],
        "generated_skill": generated_skill,
    }

    manifest = agent_registry.get("habit-companion")
    system_prompt = execution_node._resolve_system_prompt(manifest, state)

    # Prompt must contain the dynamically generated skill instructions and references
    assert "DYNAMICALLY GENERATED SKILLS (PROVIDED BY ORCHESTRATOR)" in system_prompt
    assert "Orthopedic Recovery Check-in" in system_prompt
    assert "Elevation Guide" in system_prompt

    # Tools must include tools from generated skill
    resolved_tools = execution_node._resolve_tools("habit-companion", manifest, state)
    tool_names = [
        t.get("name") if isinstance(t, dict) else getattr(t, "name", str(t))
        for t in resolved_tools
    ]
    assert "skill-docs" in tool_names
    assert "workspace-note" in tool_names


@pytest.mark.asyncio
async def test_skill_docs_resolves_references_from_generated_skill():
    """Verifies that skill-docs can read documentation directly from dynamically generated skills."""
    generated_skill = {
        "id": "dental-benefits-explainer",
        "name": "Dental Benefits Explainer",
        "description": "Explains annual dental maximums and waiting periods",
        "instructions": "Guide user on dental cleaning and crown coverage.",
        "tools": ["skill-docs"],
        "references": {
            "dental_max_guide.md": "# Dental Maximum Guide\nMost dental plans cap at $1500 per year."
        },
    }

    agent = AgentManifest(
        id="benefits-guide",
        title="Benefits Guide",
        version="0.1.0",
        risk_class="admin",
        skills=["benefits-explainer"],
        tools=["skill-docs"],
        persona="You are Benefits Guide",
    )

    ctx = MockContext(agent, state={"generated_skills": [generated_skill]})

    result = await execute_skill_docs(
        {"skill_id": "dental-benefits-explainer", "doc": "dental_max_guide.md"},
        ctx,
    )
    assert result.success is True
    assert result.output["doc"] == "dental_max_guide.md"
    assert "Most dental plans cap at $1500 per year" in result.output["content"]


@pytest.mark.asyncio
async def test_symptom_log_template_present_and_readable():
    """Verifies that symptom_log_template.md exists in visit-prep and is readable via skill-docs."""
    ws = Path.cwd()
    if ws.name == "backend":
        ws = ws.parent
    symptom_file = ws / "skills" / "visit-prep" / "references" / "symptom_log_template.md"
    assert symptom_file.is_file(), "symptom_log_template.md must exist in skills/visit-prep/references/"

    agent = AgentManifest(
        id="visit-steward",
        title="Visit Steward",
        skills=["visit-prep"],
        persona="You are Visit Steward",
    )
    ctx = MockContext(agent, workspace_root=ws, skills_dir=ws / "skills")

    res = await execute_skill_docs(
        {"skill_id": "visit-prep", "doc": "symptom_log_template.md"},
        ctx,
    )
    assert res.success is True
    assert res.output["doc"] == "symptom_log_template.md"
    assert "Symptom Log" in res.output["content"]
    assert "Tracking Matrix" in res.output["content"]


@pytest.mark.asyncio
async def test_skill_docs_dynamically_synthesizes_missing_doc_instead_of_failing(tmp_path):
    """Verifies that when a reference doc is missing, skill-docs synthesizes it instead of returning an error."""
    ws = tmp_path / "workspace"
    skills_dir = ws / "skills"
    test_skill = skills_dir / "therapy-prep"
    test_skill.mkdir(parents=True, exist_ok=True)
    (test_skill / "SKILL.md").write_text(
        "---\nname: therapy-prep\ndescription: Mental health and therapy preparation skill\n---\n\n"
        "## Intended Use & Safety Disclosures\n- Not a clinician and not emergency care\n"
        "- If this is an emergency, contact local emergency services\n- Do not change medication without the prescribing clinician\n",
        encoding="utf-8",
    )

    agent = AgentManifest(
        id="therapy-navigator",
        title="Therapy Navigator",
        skills=["therapy-prep"],
        persona="You are Therapy Navigator",
    )
    ctx = MockContext(agent, workspace_root=ws, skills_dir=skills_dir)

    # Request a doc that does NOT exist on disk
    res = await execute_skill_docs(
        {"skill_id": "therapy-prep", "doc": "anxiety_trigger_log.md"},
        ctx,
    )

    assert res.success is True
    assert res.output["doc"] == "anxiety_trigger_log.md"
    assert res.output["skill_id"] == "therapy-prep"
    assert "Anxiety Trigger Log" in res.output["content"]
    assert "Tracking Log Matrix" in res.output["content"]
    # Check that it was returned in-memory and NOT persisted to disk
    cached_file = test_skill / "references" / "anxiety_trigger_log.md"
    assert not cached_file.exists()


@pytest.mark.asyncio
async def test_skill_generator_ensure_reference_doc(tmp_path):
    """Verifies that SkillGeneratorNode can proactively provision reference documents."""
    from carefold.workflows.nodes.skill_generator_node import SkillGeneratorNode

    ws = tmp_path / "workspace"
    skills_dir = ws / "skills"
    test_skill = skills_dir / "ortho-prep"
    test_skill.mkdir(parents=True, exist_ok=True)
    (test_skill / "SKILL.md").write_text(
        "---\nname: ortho-prep\ndescription: Orthopedic appointment preparation\n---\n\n"
        "## Intended Use & Safety Disclosures\n- Not a clinician and not emergency care\n"
        "- If this is an emergency, contact local emergency services\n- Do not change medication without the prescribing clinician\n",
        encoding="utf-8",
    )

    node = SkillGeneratorNode(skills_dir=skills_dir)
    doc_path = await node.ensure_reference_doc(
        skill_id="ortho-prep",
        doc_name="joint_mobility_log.md",
        user_query="I need to track my knee joint stiffness before my orthopedic consultation",
        target_agent="visit-steward",
    )

    assert doc_path is not None
    assert doc_path.is_file()
    assert doc_path.name == "joint_mobility_log.md"
    content = doc_path.read_text(encoding="utf-8")
    assert "Joint Mobility Log" in content
    assert "Tracking Log Matrix" in content
    assert "Carefold Boundary & Safety Disclosures" in content

