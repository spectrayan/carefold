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

"""Tests for declarative AgentRegistry and catalog formatting."""

from pathlib import Path
import pytest

from carefold.agents.registry import AgentRegistry, _extract_first_line
from carefold.constants.agents import (
    AGENT_BENEFITS_GUIDE,
    AGENT_DOCUMENT_EXTRACTOR,
    AGENT_HABIT_COMPANION,
    AGENT_ORCHESTRATOR,
    AGENT_SUGGESTION_GENERATOR,
    AGENT_VISIT_STEWARD,
    BUNDLED_AGENT_IDS,
)
from carefold.loaders.agent_loader import load_agent
from carefold.schemas.manifest import AgentManifest, AgentPersonaObject, RiskClass


def test_agent_registry_discovery(temp_workspace: Path):
    """Verify registry loads all valid agents and ignores templates and hidden folders."""
    agents_dir = temp_workspace / "agents"
    skills_dir = temp_workspace / "skills"

    registry = AgentRegistry(agents_dir, skills_dir)
    agent_ids = registry.list_agent_ids()

    assert AGENT_VISIT_STEWARD in agent_ids
    assert AGENT_BENEFITS_GUIDE in agent_ids
    assert AGENT_HABIT_COMPANION in agent_ids
    assert AGENT_ORCHESTRATOR in agent_ids
    assert AGENT_DOCUMENT_EXTRACTOR in agent_ids
    assert AGENT_SUGGESTION_GENERATOR in agent_ids
    assert "skill-generator" in agent_ids
    assert "_template" not in agent_ids
    assert len(registry) >= 7


def test_agent_registry_get_and_indexing(temp_workspace: Path):
    """Verify get() and dict-like indexing behavior."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

    manifest = registry.get(AGENT_VISIT_STEWARD)
    assert manifest is not None
    assert manifest.id == AGENT_VISIT_STEWARD
    assert manifest.title == "Visit Steward"

    assert registry[AGENT_VISIT_STEWARD].id == AGENT_VISIT_STEWARD

    assert registry.get("non-existent-agent") is None
    with pytest.raises(KeyError):
        _ = registry["non-existent-agent"]


def test_agent_registry_delegatable_agents(temp_workspace: Path):
    """Verify can_delegate agents (orchestrator) are filtered out from delegatable list."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

    delegatable = registry.get_delegatable_agents(exclude=AGENT_ORCHESTRATOR)
    delegatable_ids = {a.id for a in delegatable}

    assert AGENT_ORCHESTRATOR not in delegatable_ids
    assert AGENT_VISIT_STEWARD in delegatable_ids
    assert AGENT_BENEFITS_GUIDE in delegatable_ids
    assert AGENT_HABIT_COMPANION in delegatable_ids
    assert AGENT_DOCUMENT_EXTRACTOR in delegatable_ids
    for agent in delegatable:
        assert agent.can_delegate is False


def test_agent_registry_format_agent_catalog(temp_workspace: Path):
    """Verify markdown catalog format used for the orchestrator prompt."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    catalog = registry.format_agent_catalog(exclude=AGENT_ORCHESTRATOR)

    assert isinstance(catalog, str)
    assert f"- **{AGENT_BENEFITS_GUIDE}**" in catalog
    assert f"- **{AGENT_VISIT_STEWARD}**" in catalog
    assert f"- **{AGENT_HABIT_COMPANION}**" in catalog
    assert f"- **{AGENT_DOCUMENT_EXTRACTOR}**" in catalog
    assert f"- **{AGENT_SUGGESTION_GENERATOR}**" in catalog
    assert f"- **{AGENT_ORCHESTRATOR}**" not in catalog
    assert "Tools: [" in catalog


def test_agent_registry_effective_tools(temp_workspace: Path):
    """Verify registry exposes effective tools union."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    tools = registry.get_effective_tools(AGENT_VISIT_STEWARD)

    assert "attach-read" in tools
    assert "workspace-note" in tools
    assert "skill-docs" in tools


def test_extract_first_line_helper():
    """Verify persona line extraction helper handles string, dict, and object personas."""
    assert _extract_first_line("Line 1\nLine 2") == "Line 1"
    assert _extract_first_line("# Header\nFirst real sentence\nLine 3") == "First real sentence"

    obj = AgentPersonaObject(role="Medical assistant", instructions="Do things")
    assert _extract_first_line(obj) == "Medical assistant"

    d = {"role": "Billing guide", "instructions": "Review"}
    assert _extract_first_line(d) == "Billing guide"

    assert _extract_first_line("") == ""
    assert _extract_first_line(None) == ""


def test_agent_registry_taxonomy_metadata(temp_workspace: Path):
    """Verify that AgentRegistry exposes the 7 taxonomy fields on retrieved manifests."""
    agents_dir = temp_workspace / "agents"
    skills_dir = temp_workspace / "skills"
    registry = AgentRegistry(agents_dir, skills_dir)

    # 1. visit-steward
    vs = registry.get(AGENT_VISIT_STEWARD)
    assert vs is not None
    assert vs.domain == "navigation"
    assert vs.category == "navigation.appointments"
    assert vs.care_stages == ["pre_visit", "during_visit"]
    assert vs.tags == ["visit-prep", "appointment", "checklist", "doctor"]
    assert vs.icon == "Stethoscope"
    assert vs.maturity == "stable"
    assert isinstance(vs.target_audience, list)

    # 2. benefits-guide
    bg = registry.get(AGENT_BENEFITS_GUIDE)
    assert bg is not None
    assert bg.domain == "navigation"
    assert bg.category == "navigation.insurance"
    assert bg.care_stages == ["post_visit", "daily_living"]
    assert bg.tags == ["insurance", "benefits", "EOB", "deductible", "copay"]
    assert bg.icon == "FileText"
    assert bg.maturity == "stable"

    # 3. habit-companion
    hc = registry.get(AGENT_HABIT_COMPANION)
    assert hc is not None
    assert hc.domain == "wellness"
    assert hc.category == "wellness.habits"
    assert hc.care_stages == ["daily_living"]
    assert hc.tags == ["habits", "hydration", "sleep", "checklist"]
    assert hc.icon == "HeartPulse"
    assert hc.maturity == "stable"


def test_agent_registry_all_manifests_conform_to_taxonomy(temp_workspace: Path):
    """Verify that all manifests in the registry have valid taxonomy attributes."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    valid_domains = {"wellness", "clinical", "therapy", "navigation", "education"}
    valid_maturities = {"draft", "beta", "stable", "deprecated"}

    for manifest in registry.list_agents():
        domain_val = manifest.domain.value if hasattr(manifest.domain, "value") else str(manifest.domain)
        maturity_val = manifest.maturity.value if hasattr(manifest.maturity, "value") else str(manifest.maturity)

        assert domain_val in valid_domains, f"Agent {manifest.id} has invalid domain: {manifest.domain}"
        assert maturity_val in valid_maturities, f"Agent {manifest.id} has invalid maturity: {manifest.maturity}"
        assert isinstance(manifest.category, str)
        assert isinstance(manifest.care_stages, list)
        assert isinstance(manifest.target_audience, list)
        assert isinstance(manifest.tags, list)
        assert isinstance(manifest.icon, str) and len(manifest.icon) > 0


def test_agent_registry_system_agents_and_get_resolution(temp_workspace: Path):
    """Verify registry resolves system agents located in _system/ via get() and marks them hidden."""
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

    for sys_id in ["orchestrator", "document-extractor", "skill-generator", "suggestion-generator"]:
        agent = registry.get(sys_id)
        assert agent is not None, f"System agent '{sys_id}' not found via get()"
        assert agent.id == sys_id
        assert agent.hidden is True
        assert registry[sys_id].id == sys_id

    assert registry.get("_template") is None


