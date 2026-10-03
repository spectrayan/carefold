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

"""Unit and adversarial tests for manifest loaders and permission union engine."""

from pathlib import Path
import pytest

from carefold.loaders.agent_loader import (
    ManifestValidationError,
    extract_fallback_description,
    load_agent,
    load_all_agents,
)
from carefold.loaders.frontmatter import (
    MANDATORY_INTENDED_USE_LINES,
    check_mandatory_intended_use,
    parse_frontmatter,
)
from carefold.loaders.skill_loader import load_all_skills, load_skill
from carefold.loaders.union import ToolValidationError, compute_effective_tools
from carefold.schemas.manifest import AgentDomain, AgentMaturity, RiskClass, SkillManifest


def test_frontmatter_parsing_valid():
    md = """---
name: test-skill
description: A test skill
metadata:
  version: 1.0.0
---
# Body Title
Body content here.
"""
    parsed = parse_frontmatter(md)
    assert parsed.frontmatter["name"] == "test-skill"
    assert parsed.frontmatter["description"] == "A test skill"
    assert parsed.body == "# Body Title\nBody content here."


def test_frontmatter_missing_frontmatter():
    md = "# Just markdown without frontmatter"
    parsed = parse_frontmatter(md)
    assert parsed.frontmatter == {}
    assert parsed.body == md


def test_frontmatter_malformed_yaml():
    md = """---
name: [unterminated list
---
Body
"""
    with pytest.raises(ValueError, match="Malformed YAML"):
        parse_frontmatter(md)


def test_mandatory_intended_use_valid():
    content = """
    ## Intended Use & Safety Disclosures
    - Not a clinician and not emergency care
    - If this is an emergency, contact local emergency services
    - Do not change medication without the prescribing clinician
    """
    valid, missing = check_mandatory_intended_use(content)
    assert valid is True
    assert missing is None


def test_mandatory_intended_use_missing_statements():
    content1 = "Not a clinician and not emergency care. If this is an emergency, contact local emergency services."
    valid1, missing1 = check_mandatory_intended_use(content1)
    assert valid1 is False
    assert missing1 == "Do not change medication without the prescribing clinician"

    content2 = "Not a clinician and not emergency care. Do not change medication without the prescribing clinician."
    valid2, missing2 = check_mandatory_intended_use(content2)
    assert valid2 is False
    assert missing2 == "If this is an emergency, contact local emergency services"

    content3 = "If this is an emergency, contact local emergency services. Do not change medication without the prescribing clinician."
    valid3, missing3 = check_mandatory_intended_use(content3)
    assert valid3 is False
    assert missing3 == "Not a clinician and not emergency care"


def test_skill_load_bundled_skills(temp_workspace: Path):
    skills_dir = temp_workspace / "skills"
    skills = load_all_skills(skills_dir)
    skill_ids = {s.id for s in skills}

    assert "visit-prep" in skill_ids
    assert "benefits-explainer" in skill_ids
    assert "habit-checkin" in skill_ids

    visit_prep = load_skill(skills_dir / "visit-prep")
    assert visit_prep.id == "visit-prep"
    assert visit_prep.risk_class == RiskClass.WELLNESS
    assert "attach-read" in visit_prep.tools
    assert "skill-docs" in visit_prep.tools
    assert "checklist.md" in visit_prep.references
    assert visit_prep.is_verified is True


def test_skill_load_missing_carefold_yaml(tmp_path: Path):
    skill_dir = tmp_path / "custom-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: custom-skill
description: Custom skill without carefold.yaml
---
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician
""",
        encoding="utf-8",
    )

    skill = load_skill(skill_dir)
    assert skill.id == "custom-skill"
    assert skill.is_verified is False
    assert skill.unverified is True
    assert skill.tools == []
    assert skill.risk_class == RiskClass.WELLNESS


def test_skill_load_undeclared_tool_in_carefold_yaml(tmp_path: Path):
    skill_dir = tmp_path / "bad-tool-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: bad-tool-skill
description: Skill declaring non-phase0 tool
---
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician
""",
        encoding="utf-8",
    )
    (skill_dir / "carefold.yaml").write_text(
        """id: bad-tool-skill
tools:
  - web-search
  - attach-read
""",
        encoding="utf-8",
    )

    with pytest.raises(ToolValidationError, match="not in Phase 0 closed registry"):
        load_skill(skill_dir)


def test_agent_load_bundled_agents(temp_workspace: Path):
    agents_dir = temp_workspace / "agents"
    skills_dir = temp_workspace / "skills"

    agent, effective_tools, loaded_skills = load_agent(agents_dir / "visit-steward", skills_dir)
    assert agent.id == "visit-steward"
    assert agent.risk_class == RiskClass.CLINICAL_ASSIST
    assert "visit-prep" in agent.skills

    # Effective tools union: agent tools [attach-read, workspace-note] ∪ skill tools [attach-read, skill-docs]
    assert set(effective_tools) == {"attach-read", "workspace-note", "skill-docs"}
    assert len(loaded_skills) == 1
    assert loaded_skills[0].id == "visit-prep"


def test_agent_effective_tools_union_and_registry_filter():
    skills = [
        SkillManifest(
            id="s1",
            name="s1",
            description="desc",
            tools=["attach-read", "skill-docs"],
        ),
        SkillManifest(
            id="s2",
            name="s2",
            description="desc",
            tools=["workspace-note"],
        ),
    ]
    eff = compute_effective_tools(["attach-read"], skills)
    assert set(eff) == {"attach-read", "skill-docs", "workspace-note"}


def test_agent_risk_class_elevation(tmp_path: Path):
    # Setup test skill that has clinical_assist risk class
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    clinical_skill_dir = skills_dir / "clinical-triage"
    clinical_skill_dir.mkdir()
    (clinical_skill_dir / "SKILL.md").write_text(
        """---
name: clinical-triage
description: Clinical skill
---
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician
""",
        encoding="utf-8",
    )
    (clinical_skill_dir / "carefold.yaml").write_text(
        """id: clinical-triage
risk_class: clinical_assist
tools:
  - skill-docs
""",
        encoding="utf-8",
    )

    # Setup agent claiming risk_class: wellness, but declaring clinical-triage
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    agent_dir = agents_dir / "elevated-agent"
    agent_dir.mkdir()
    (agent_dir / "agent.yaml").write_text(
        """id: elevated-agent
title: Elevated Agent
risk_class: wellness
skills:
  - clinical-triage
tools:
  - workspace-note
persona: Helper
""",
        encoding="utf-8",
    )

    agent, effective_tools, loaded_skills = load_agent(agent_dir, skills_dir)
    # Must be elevated to clinical_assist!
    assert agent.risk_class == RiskClass.CLINICAL_ASSIST
    assert set(effective_tools) == {"workspace-note", "skill-docs"}


def test_agent_missing_declared_skill(tmp_path: Path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    agent_dir = agents_dir / "bad-agent"
    agent_dir.mkdir()
    (agent_dir / "agent.yaml").write_text(
        """id: bad-agent
title: Bad Agent
skills:
  - non-existent-skill
persona: Helper
""",
        encoding="utf-8",
    )

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    with pytest.raises(ManifestValidationError, match="Missing declared skill"):
        load_agent(agent_dir, skills_dir)


def test_agent_invalid_tool_in_agent_yaml(tmp_path: Path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    agent_dir = agents_dir / "tool-agent"
    agent_dir.mkdir()
    (agent_dir / "agent.yaml").write_text(
        """id: tool-agent
title: Tool Agent
tools:
  - execute-bash
persona: Helper
""",
        encoding="utf-8",
    )

    with pytest.raises(ToolValidationError, match="not in Phase 0 closed registry"):
        load_agent(agent_dir)


def test_agent_load_bundled_agents_taxonomy(temp_workspace: Path):
    """Verify that load_agent loads all 7 taxonomy fields for bundled user-facing agents."""
    agents_dir = temp_workspace / "agents"
    skills_dir = temp_workspace / "skills"

    # 1. visit-steward
    agent_vs, _, _ = load_agent(agents_dir / "visit-steward", skills_dir)
    assert agent_vs.domain == "navigation"
    assert agent_vs.category == "navigation.appointments"
    assert agent_vs.care_stages == ["pre_visit", "during_visit"]
    assert agent_vs.tags == ["visit-prep", "appointment", "checklist", "doctor"]
    assert agent_vs.icon == "Stethoscope"
    assert agent_vs.maturity == "stable"
    assert isinstance(agent_vs.target_audience, list)

    # 2. benefits-guide
    agent_bg, _, _ = load_agent(agents_dir / "benefits-guide", skills_dir)
    assert agent_bg.domain == "navigation"
    assert agent_bg.category == "navigation.insurance"
    assert agent_bg.care_stages == ["post_visit", "daily_living"]
    assert agent_bg.tags == ["insurance", "benefits", "EOB", "deductible", "copay"]
    assert agent_bg.icon == "FileText"
    assert agent_bg.maturity == "stable"

    # 3. habit-companion
    agent_hc, _, _ = load_agent(agents_dir / "habit-companion", skills_dir)
    assert agent_hc.domain == "wellness"
    assert agent_hc.category == "wellness.habits"
    assert agent_hc.care_stages == ["daily_living"]
    assert agent_hc.tags == ["habits", "hydration", "sleep", "checklist"]
    assert agent_hc.icon == "HeartPulse"
    assert agent_hc.maturity == "stable"


def test_agent_load_defaults_backward_compatibility(tmp_path: Path):
    """Verify that an agent.yaml without taxonomy fields loads with sensible defaults."""
    agent_dir = tmp_path / "legacy-agent"
    agent_dir.mkdir()
    (agent_dir / "agent.yaml").write_text(
        """id: legacy-agent
title: Legacy Agent
persona: Legacy assistant role
""",
        encoding="utf-8",
    )

    agent, effective_tools, skills = load_agent(agent_dir)
    assert agent.id == "legacy-agent"
    # Verify all 7 defaults
    assert agent.domain == AgentDomain.WELLNESS or agent.domain == "wellness"
    assert agent.category == ""
    assert agent.care_stages == []
    assert agent.target_audience == []
    assert agent.tags == []
    assert agent.icon == "Shield"
    assert agent.maturity == AgentMaturity.STABLE or agent.maturity == "stable"


def test_agent_load_invalid_taxonomy_enum(tmp_path: Path):
    """Verify that invalid taxonomy domain or maturity raises ManifestValidationError."""
    bad_domain_dir = tmp_path / "bad-domain-agent"
    bad_domain_dir.mkdir()
    (bad_domain_dir / "agent.yaml").write_text(
        """id: bad-domain-agent
title: Bad Domain Agent
domain: invalid_domain_xyz
persona: Helper
""",
        encoding="utf-8",
    )
    with pytest.raises(ManifestValidationError, match="domain"):
        load_agent(bad_domain_dir)

    bad_maturity_dir = tmp_path / "bad-maturity-agent"
    bad_maturity_dir.mkdir()
    (bad_maturity_dir / "agent.yaml").write_text(
        """id: bad-maturity-agent
title: Bad Maturity Agent
maturity: immortal
persona: Helper
""",
        encoding="utf-8",
    )
    with pytest.raises(ManifestValidationError, match="maturity"):
        load_agent(bad_maturity_dir)


def test_load_all_agents_includes_taxonomy(temp_workspace: Path):
    """Verify that load_all_agents propagates all 7 taxonomy fields to AgentSummary."""
    agents_dir = temp_workspace / "agents"
    skills_dir = temp_workspace / "skills"

    summaries = load_all_agents(agents_dir, skills_dir)
    by_id = {s.id: s for s in summaries}

    assert "visit-steward" in by_id
    vs = by_id["visit-steward"]
    assert vs.domain == "navigation"
    assert vs.category == "navigation.appointments"
    assert vs.care_stages == ["pre_visit", "during_visit"]
    assert vs.tags == ["visit-prep", "appointment", "checklist", "doctor"]
    assert vs.icon == "Stethoscope"
    assert vs.maturity == "stable"
    assert isinstance(vs.target_audience, list)

    assert "benefits-guide" in by_id
    bg = by_id["benefits-guide"]
    assert bg.domain == "navigation"
    assert bg.category == "navigation.insurance"
    assert bg.care_stages == ["post_visit", "daily_living"]
    assert bg.tags == ["insurance", "benefits", "EOB", "deductible", "copay"]
    assert bg.icon == "FileText"
    assert bg.maturity == "stable"

    assert "habit-companion" in by_id
    hc = by_id["habit-companion"]
    assert hc.domain == "wellness"
    assert hc.category == "wellness.habits"
    assert hc.care_stages == ["daily_living"]
    assert hc.tags == ["habits", "hydration", "sleep", "checklist"]
    assert hc.icon == "HeartPulse"
    assert hc.maturity == "stable"


def test_skill_load_taxonomy_fields(tmp_path: Path):
    """Verify that load_skill correctly parses domain, category, and tags from carefold.yaml."""
    skill_dir = tmp_path / "taxonomy-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: taxonomy-skill
description: Skill with taxonomy in carefold.yaml
domain: wellness
category: general.wellness
tags:
  - general
---
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician
""",
        encoding="utf-8",
    )
    (skill_dir / "carefold.yaml").write_text(
        """id: taxonomy-skill
domain: clinical
category: clinical.pediatrics.allergy
tags:
  - pediatric
  - allergy
  - food-allergy
tools:
  - skill-docs
""",
        encoding="utf-8",
    )

    skill = load_skill(skill_dir)
    assert skill.id == "taxonomy-skill"
    assert skill.domain == "clinical"
    assert skill.category == "clinical.pediatrics.allergy"
    # Merged tags from carefold.yaml and SKILL.md
    assert skill.tags == ["pediatric", "allergy", "food-allergy", "general"]


def test_skill_load_defaults_backward_compatibility(tmp_path: Path):
    """Verify that a skill without taxonomy fields defaults to wellness, empty category and empty tags."""
    skill_dir = tmp_path / "legacy-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: legacy-skill
description: Legacy skill without taxonomy
---
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician
""",
        encoding="utf-8",
    )
    (skill_dir / "carefold.yaml").write_text(
        """id: legacy-skill
tools:
  - attach-read
""",
        encoding="utf-8",
    )

    skill = load_skill(skill_dir)
    assert skill.domain == "wellness" or skill.domain == AgentDomain.WELLNESS
    assert skill.category == ""
    assert skill.tags == []


def test_agent_load_skills_three_levels_up(tmp_path: Path):
    """Verify that load_agent resolves skills 3 levels up when agent is in a nested directory."""
    # Setup workspace: workspace_root/skills and workspace_root/agents/_system/test-sys-agent
    ws = tmp_path / "workspace"
    ws.mkdir()
    skills_dir = ws / "skills"
    skills_dir.mkdir()
    skill_dir = skills_dir / "shared-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: shared-skill
description: A shared skill
---
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician
""",
        encoding="utf-8",
    )
    (skill_dir / "carefold.yaml").write_text(
        """id: shared-skill
tools:
  - attach-read
""",
        encoding="utf-8",
    )

    agents_dir = ws / "agents"
    system_dir = agents_dir / "_system"
    system_dir.mkdir(parents=True)
    agent_dir = system_dir / "test-sys-agent"
    agent_dir.mkdir()
    (agent_dir / "agent.yaml").write_text(
        """id: test-sys-agent
title: System Agent
skills:
  - shared-skill
tools:
  - attach-read
persona: Internal helper
""",
        encoding="utf-8",
    )

    # Calling load_agent without explicitly specifying skills_dir tests resolution 3 levels up
    agent, eff_tools, loaded_skills = load_agent(agent_dir)
    assert agent.id == "test-sys-agent"
    assert len(loaded_skills) == 1
    assert loaded_skills[0].id == "shared-skill"
    assert "attach-read" in eff_tools


def test_load_all_agents_discovers_system_agents(temp_workspace: Path):
    """Verify that load_all_agents discovers agents in agents/_system/ and marks them hidden."""
    agents_dir = temp_workspace / "agents"
    skills_dir = temp_workspace / "skills"

    summaries = load_all_agents(agents_dir, skills_dir)
    by_id = {s.id: s for s in summaries}

    # Verify user-facing agents
    assert "visit-steward" in by_id
    assert by_id["visit-steward"].hidden is False

    assert "benefits-guide" in by_id
    assert by_id["benefits-guide"].hidden is False

    assert "habit-companion" in by_id
    assert by_id["habit-companion"].hidden is False

    # Verify system agents discovered from _system/
    expected_system_agents = [
        "orchestrator",
        "document-extractor",
        "skill-generator",
        "suggestion-generator",
    ]
    for sys_id in expected_system_agents:
        assert sys_id in by_id, f"Expected system agent '{sys_id}' in load_all_agents output"
        assert by_id[sys_id].hidden is True

    # Verify _template is NEVER loaded
    assert "_template" not in by_id


def test_load_all_agents_skips_template_and_hidden_dirs(tmp_path: Path):
    """Verify load_all_agents ignores _template, dotfiles, and other underscore dirs."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    agents_dir = ws / "agents"
    agents_dir.mkdir()

    # User agent
    user_agent = agents_dir / "user-agent"
    user_agent.mkdir()
    (user_agent / "agent.yaml").write_text("id: user-agent\ntitle: User Agent\npersona: Helper\n", encoding="utf-8")

    # Template dir
    template_dir = agents_dir / "_template"
    template_dir.mkdir()
    (template_dir / "agent.yaml").write_text("id: _template\ntitle: Template\npersona: Template\n", encoding="utf-8")

    # Dot dir
    dot_dir = agents_dir / ".git"
    dot_dir.mkdir()

    # Other underscore dir
    other_dir = agents_dir / "_other"
    other_dir.mkdir()
    (other_dir / "agent.yaml").write_text("id: _other\ntitle: Other\npersona: Other\n", encoding="utf-8")

    # System dir with valid agent
    system_dir = agents_dir / "_system"
    system_dir.mkdir()
    sys_agent = system_dir / "sys-agent"
    sys_agent.mkdir()
    (sys_agent / "agent.yaml").write_text("id: sys-agent\ntitle: Sys Agent\npersona: Helper\n", encoding="utf-8")

    summaries = load_all_agents(agents_dir)
    ids = [s.id for s in summaries]

    assert "user-agent" in ids
    assert "sys-agent" in ids
    assert "_template" not in ids
    assert "_other" not in ids
    assert ".git" not in ids

    sys_summary = next(s for s in summaries if s.id == "sys-agent")
    assert sys_summary.hidden is True
    user_summary = next(s for s in summaries if s.id == "user-agent")
    assert user_summary.hidden is False


def test_extract_fallback_description():
    """Verify extract_fallback_description ignores markdown headers and section titles."""
    # Classic markdown header
    p1 = "ROLE & EMPATHY:\nYou are Benefits Guide, a helpful assistant.\nMore text."
    assert extract_fallback_description(p1) == "You are Benefits Guide, a helpful assistant."

    # Markdown hash heading
    p2 = "# Role & Empathy\nYou are Visit Steward, an organized assistant."
    assert extract_fallback_description(p2) == "You are Visit Steward, an organized assistant."

    # Leading whitespace and blank lines
    p3 = "\n\n  ROLE:\n\n  Dedicated oncology care steward."
    assert extract_fallback_description(p3) == "Dedicated oncology care steward."

    # Dictionary persona
    p4 = {"role": "Healthcare insurance navigator"}
    assert extract_fallback_description(p4) == "Healthcare insurance navigator"

    # Dictionary persona with header in role falling back to instructions
    p5 = {"role": "ROLE & EMPATHY:", "instructions": "You are a test guide."}
    assert extract_fallback_description(p5) == "You are a test guide."

    # Empty inputs
    assert extract_fallback_description("") == ""
    assert extract_fallback_description(None) == ""


def test_all_agents_have_valid_descriptions():
    """Verify that all live agents in the repo have substantive, non-header descriptions."""
    repo_agents_dir = Path(__file__).resolve().parent.parent.parent / "agents"
    if not repo_agents_dir.is_dir():
        pytest.skip("Repo agents directory not found")

    summaries = load_all_agents(repo_agents_dir)
    assert len(summaries) >= 20

    for agent in summaries:
        assert agent.description, f"Agent '{agent.id}' has empty description"
        assert not agent.description.upper().startswith("ROLE & EMPATHY"), (
            f"Agent '{agent.id}' description leaked header: {agent.description}"
        )
        assert not agent.description.upper().startswith("ROLE:"), (
            f"Agent '{agent.id}' description leaked header: {agent.description}"
        )
        assert len(agent.description) >= 20, (
            f"Agent '{agent.id}' description is too short: {agent.description}"
        )


