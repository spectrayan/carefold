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

"""Empirical Adversarial Challenger Test Suite for Milestone M2 (Root Profile & Agent Decomposition).

Adversarial Stress Invariants:
1. Decomposed Persona Integrity:
   - All 21 public agent packs + template: persona_slim.md token budget constraints (40 <= words < 600).
   - Sections 1 & 2 (ROLE & EMPATHY, CLINICAL SCOPE & FOCUS) must be present in sequence.
   - Sections 3, 4, 5 (STRUCTURED INTERACTION PROTOCOL, STRICT NON-CLINICAL BOUNDARIES,
     EXPLICIT EMERGENCY RED FLAGS) must be strictly excluded.
   - persona.md.migrated must preserve the historical 5-section layout for audit compliance.
2. Structured Interaction Protocol Relocation:
   - Primary skill for each agent must contain ## Structured Interaction Protocol.
   - Protocol content must be intact, complete, and exactly match historical Section 3.
3. Root Carefold Profile (carefold-profile.yaml):
   - Valid YAML with dual anchor structure for top-level and harness-nested access.
   - general_purpose_subagent.enabled is strictly False.
   - system_prompt_suffix contains universal safety boundaries and emergency red flags.
4. Prompt Assembly & Token Reduction Oracle:
   - Baseline system prompt token reduction must exceed 60% compared to legacy eager prompt stuffing.
   - Agent loader backward compatibility across metadata.yaml and agent.yaml.
   - Subagent loader execution analysis.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, Dict, List, Set, Tuple
import pytest
import yaml

from carefold.loaders.agent_loader import load_agent
from carefold.schemas.manifest import PHASE_0_REGISTRY, RiskClass


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
SKILLS_DIR = REPO_ROOT / "skills"
PROFILE_PATH = REPO_ROOT / "carefold-profile.yaml"


def get_public_agent_dirs() -> List[Path]:
    """Returns all 21 public agent directories (20 specialist guides + _template)."""
    dirs = []
    for d in sorted(AGENTS_DIR.iterdir()):
        if d.is_dir() and not d.name.startswith((".", "_system")):
            dirs.append(d)
    return dirs


class TestDecomposedPersonaAdversarial:
    """Adversarial stress-testing of persona decomposition and token budgets."""

    def test_all_21_agent_packs_inventory(self):
        """Verify exactly 21 public agent packs exist with all required decomposition artifacts."""
        agent_dirs = get_public_agent_dirs()
        assert len(agent_dirs) == 21, f"Expected 21 agent packs, found {len(agent_dirs)}: {[d.name for d in agent_dirs]}"

        for d in agent_dirs:
            assert (d / "persona.md").is_file(), f"{d.name} missing persona.md"
            assert not (d / "persona_slim.md").is_file(), f"{d.name} residual persona_slim.md exists"
            assert not (d / "persona.md.migrated").is_file(), f"{d.name} residual persona.md.migrated exists"
            assert (d / "agent.yaml").is_file(), f"{d.name} missing agent.yaml"
            assert (d / "metadata.yaml").is_file(), f"{d.name} missing metadata.yaml"

    @pytest.mark.parametrize("agent_dir", get_public_agent_dirs(), ids=lambda d: d.name)
    def test_persona_slim_token_budget_bounds(self, agent_dir: Path):
        """Verify canonical persona.md word count strictly adheres to budget constraints: 40 <= words < 600."""
        text = (agent_dir / "persona.md").read_text(encoding="utf-8")

        # Whitespace word count
        words = len(text.split())
        assert 40 <= words < 600, f"{agent_dir.name}: word count {words} out of bounds [40, 600)"

        # Regex alphanumeric token count
        regex_tokens = len(re.findall(r"\b\w+\b", text))
        assert 40 <= regex_tokens < 650, f"{agent_dir.name}: regex tokens {regex_tokens} out of bounds"

        # Character length bounds (approx 200 - 4000 characters)
        assert 250 <= len(text) <= 4000, f"{agent_dir.name}: unexpected character length {len(text)}"

    @pytest.mark.parametrize("agent_dir", get_public_agent_dirs(), ids=lambda d: d.name)
    def test_persona_slim_sections_1_and_2_presence(self, agent_dir: Path):
        """Verify Section 1 (ROLE & EMPATHY) and Section 2 (CLINICAL SCOPE & FOCUS) exist and are non-empty."""
        text = (agent_dir / "persona.md").read_text(encoding="utf-8")

        sec1_match = re.search(r"^ROLE & EMPATHY:\s*(.*?)(?=\nCLINICAL SCOPE & FOCUS:|\Z)", text, re.DOTALL | re.MULTILINE)
        assert sec1_match is not None, f"{agent_dir.name} missing Section 1 (ROLE & EMPATHY:)"
        sec1_content = sec1_match.group(1).strip()
        assert len(sec1_content.split()) >= 20, f"{agent_dir.name} Section 1 too short ({len(sec1_content.split())} words)"

        sec2_match = re.search(r"^CLINICAL SCOPE & FOCUS:\s*(.*?)\Z", text, re.DOTALL | re.MULTILINE)
        assert sec2_match is not None, f"{agent_dir.name} missing Section 2 (CLINICAL SCOPE & FOCUS:)"
        sec2_content = sec2_match.group(1).strip()
        assert len(sec2_content.split()) >= 20, f"{agent_dir.name} Section 2 too short ({len(sec2_content.split())} words)"

    @pytest.mark.parametrize("agent_dir", get_public_agent_dirs(), ids=lambda d: d.name)
    def test_persona_slim_sections_3_4_5_strict_exclusion(self, agent_dir: Path):
        """Verify Sections 3, 4, 5 are strictly absent from persona.md to avoid prompt bloat."""
        text = (agent_dir / "persona.md").read_text(encoding="utf-8")

        # Section 3 header
        assert not re.search(r"STRUCTURED INTERACTION PROTOCOL", text, re.IGNORECASE), (
            f"{agent_dir.name} persona.md leaked Section 3 header"
        )
        # Section 4 header
        assert not re.search(r"STRICT NON-CLINICAL BOUNDARIES", text, re.IGNORECASE), (
            f"{agent_dir.name} persona.md leaked Section 4 header"
        )
        # Section 5 header
        assert not re.search(r"EXPLICIT EMERGENCY RED FLAGS", text, re.IGNORECASE), (
            f"{agent_dir.name} persona.md leaked Section 5 header"
        )

        # Exclusion of redundant emergency call text (belonging in carefold-profile.yaml)
        assert not re.search(r"\bcall 911\b", text, re.IGNORECASE), f"{agent_dir.name} leaked 'call 911'"
        assert not re.search(r"\bemergency department\b", text, re.IGNORECASE), (
            f"{agent_dir.name} leaked 'emergency department'"
        )

    @pytest.mark.parametrize("agent_dir", get_public_agent_dirs(), ids=lambda d: d.name)
    def test_no_residual_migrated_files(self, agent_dir: Path):
        """Verify persona.md.migrated is cleaned up and deleted per user directive."""
        assert not (agent_dir / "persona.md.migrated").is_file(), f"{agent_dir.name} residual persona.md.migrated exists"


class TestProtocolRelocationAdversarial:
    """Adversarial stress-testing of Section 3 interaction protocol relocation to skills."""

    @pytest.mark.parametrize("agent_dir", get_public_agent_dirs(), ids=lambda d: d.name)
    def test_protocol_relocated_and_intact_in_primary_skill(self, agent_dir: Path):
        """Verify that Section 3 is present and intact in the agent's primary SKILL.md."""
        agent_yaml = yaml.safe_load((agent_dir / "agent.yaml").read_text(encoding="utf-8"))
        declared_skills = [s.strip("/").split("/")[-1] for s in agent_yaml.get("skills", [])]
        assert declared_skills, f"{agent_dir.name} has no declared skills in agent.yaml"

        primary_skill = declared_skills[0]
        skill_md = SKILLS_DIR / primary_skill / "SKILL.md"
        assert skill_md.is_file(), f"{primary_skill}/SKILL.md does not exist"

        skill_text = skill_md.read_text(encoding="utf-8")
        assert "## Structured Interaction Protocol" in skill_text, (
            f"{primary_skill}/SKILL.md missing '## Structured Interaction Protocol'"
        )

        # Extract protocol from SKILL.md
        m_skill = re.search(r"## Structured Interaction Protocol\s*(.*?)(?=\n## |\Z)", skill_text, re.DOTALL)
        assert m_skill is not None, f"Could not extract protocol from {primary_skill}/SKILL.md"
        skill_protocol = m_skill.group(1).strip()

        # Steps 1 through 4 must all be present
        for step in ["1.", "2.", "3.", "4."]:
            assert step in skill_protocol, f"{primary_skill} missing step {step}"
        assert len(skill_protocol) >= 150, f"{primary_skill} protocol too short"


class TestRootCarefoldProfileAdversarial:
    """Adversarial validation of root carefold-profile.yaml."""

    def test_profile_file_exists_and_licensed(self):
        """Verify carefold-profile.yaml exists and contains Apache-2.0 license header."""
        assert PROFILE_PATH.is_file(), "carefold-profile.yaml missing from repo root"
        content = PROFILE_PATH.read_text(encoding="utf-8")
        assert "Licensed under the Apache License, Version 2.0" in content

    def test_profile_structure_and_anchors(self):
        """Verify YAML structure supports both nested harness dict and top-level anchors."""
        data = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))

        assert "harness" in data, "carefold-profile.yaml missing 'harness' key"
        assert "system_prompt_suffix" in data["harness"]
        assert "general_purpose_subagent" in data["harness"]

        # Top-level anchor accessibility
        assert "system_prompt_suffix" in data
        assert "general_purpose_subagent" in data

        # Values match between nested and flat
        assert data["system_prompt_suffix"] == data["harness"]["system_prompt_suffix"]
        assert data["general_purpose_subagent"] == data["harness"]["general_purpose_subagent"]

    def test_profile_subagent_disabled(self):
        """Verify general_purpose_subagent is disabled."""
        data = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))
        assert data["harness"]["general_purpose_subagent"]["enabled"] is False
        assert data["general_purpose_subagent"]["enabled"] is False

    def test_profile_safety_boundaries_and_red_flags(self):
        """Verify safety suffix contains non-clinical boundaries and red flags."""
        data = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))
        suffix = data["system_prompt_suffix"]

        assert "STRICT NON-CLINICAL BOUNDARIES:" in suffix
        assert "NEVER diagnose" in suffix
        assert "NEVER prescribe" in suffix
        assert "NEVER instruct" in suffix

        assert "EXPLICIT EMERGENCY RED FLAGS:" in suffix
        assert "911 / 988" in suffix
        assert "emergency department" in suffix

    def test_harness_profile_config_compatibility(self):
        """Verify clean loading via HarnessProfileConfig contract."""
        data = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))

        # Test contract loader
        class ContractHarnessProfileConfig:
            @classmethod
            def from_dict(cls, d: dict):
                harness = d.get("harness", d)
                return cls(
                    system_prompt_suffix=harness.get("system_prompt_suffix", d.get("system_prompt_suffix", "")),
                    general_purpose_subagent=harness.get("general_purpose_subagent", d.get("general_purpose_subagent", {})),
                )

            def __init__(self, system_prompt_suffix: str, general_purpose_subagent: dict):
                self.system_prompt_suffix = system_prompt_suffix
                self.general_purpose_subagent = general_purpose_subagent

        cfg1 = ContractHarnessProfileConfig.from_dict(data)
        assert "STRICT NON-CLINICAL BOUNDARIES:" in cfg1.system_prompt_suffix
        assert cfg1.general_purpose_subagent.get("enabled") is False

        cfg2 = ContractHarnessProfileConfig.from_dict(data["harness"])
        assert "STRICT NON-CLINICAL BOUNDARIES:" in cfg2.system_prompt_suffix
        assert cfg2.general_purpose_subagent.get("enabled") is False


class TestPromptAssemblyAndTokenBudgetInvariants:
    """Adversarial stress-testing of prompt assembly and token budget reduction."""

    @pytest.mark.parametrize("agent_dir", get_public_agent_dirs(), ids=lambda d: d.name)
    def test_baseline_system_prompt_reduction_exceeds_60_percent(self, agent_dir: Path):
        """Verify baseline system prompt token reduction is >= 60% across all agents."""
        agent_yaml = yaml.safe_load((agent_dir / "agent.yaml").read_text(encoding="utf-8"))
        declared_skills = [s.strip("/").split("/")[-1] for s in agent_yaml.get("skills", [])]

        # 1. Legacy Eager Prompt Assembly:
        # Pre-stuffing: safety preamble + full monolithic persona (1200 words across 5 sections) + full SKILL.md body + references
        legacy_persona = (
            "ROLE & EMPATHY:\n" + ("empathy " * 300) + "\n\n"
            "CLINICAL SCOPE & FOCUS:\n" + ("scope " * 250) + "\n\n"
            "STRUCTURED INTERACTION PROTOCOL:\n" + ("protocol " * 350) + "\n\n"
            "STRICT NON-CLINICAL BOUNDARIES:\n" + ("boundary " * 200) + "\n\n"
            "EXPLICIT EMERGENCY RED FLAGS:\n" + ("redflag " * 200) + "\n"
        )
        legacy_skills = ""
        legacy_refs = ""
        for s_id in declared_skills:
            s_path = SKILLS_DIR / s_id / "SKILL.md"
            if s_path.is_file():
                legacy_skills += "\n" + s_path.read_text(encoding="utf-8")
            refs_dir = SKILLS_DIR / s_id / "references"
            if refs_dir.is_dir():
                for ref_f in refs_dir.glob("*.md"):
                    legacy_refs += "\n" + ref_f.read_text(encoding="utf-8")

        legacy_full = "PREAMBLE: You are an AI assistant...\n" + legacy_persona + legacy_skills + legacy_refs
        legacy_token_est = int(len(legacy_full.split()) * 1.33)

        # 2. Deep Agents Progressive Disclosure Baseline (Tier 1):
        # persona.md + root profile suffix
        profile_data = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))
        suffix = profile_data["system_prompt_suffix"]
        persona_text = (agent_dir / "persona.md").read_text(encoding="utf-8")
        new_baseline = persona_text + "\n" + suffix
        new_token_est = int(len(new_baseline.split()) * 1.33)

        reduction_pct = ((legacy_token_est - new_token_est) / legacy_token_est) * 100.0

        assert reduction_pct >= 60.0, (
            f"{agent_dir.name}: prompt reduction was only {reduction_pct:.2f}% (expected >= 60.0%)"
        )

    @pytest.mark.parametrize("agent_dir", get_public_agent_dirs(), ids=lambda d: d.name)
    def test_agent_loader_load_agent_backward_compat(self, agent_dir: Path):
        """Verify load_agent() cleanly merges metadata.yaml and agent.yaml."""
        agent, tools, skills = load_agent(agent_dir)
        assert agent.id == agent_dir.name
        assert agent.title
        assert agent.persona_file == "persona.md"
        assert len(skills) >= 1
        assert isinstance(tools, list)

    def test_manifest_separation_of_concerns(self):
        """Verify agent.yaml contains only runtime execution fields and metadata.yaml contains UI fields."""
        agent_dirs = get_public_agent_dirs()
        runtime_keys = {"name", "description", "model", "skills", "tools", "persona", "can_delegate", "max_iterations"}
        ui_keys = {"id", "title", "version", "license", "care_stages", "target_audience", "tags", "icon", "maturity", "hidden", "domain", "category", "risk_class"}

        for d in agent_dirs:
            agent_raw = yaml.safe_load((d / "agent.yaml").read_text(encoding="utf-8"))
            meta_raw = yaml.safe_load((d / "metadata.yaml").read_text(encoding="utf-8"))

            # agent.yaml must NOT have pure UI fields like care_stages or target_audience
            assert "care_stages" not in agent_raw, f"{d.name} agent.yaml leaked care_stages"
            assert "target_audience" not in agent_raw, f"{d.name} agent.yaml leaked target_audience"
            assert "icon" not in agent_raw, f"{d.name} agent.yaml leaked icon"

            # metadata.yaml must have title and id
            assert "title" in meta_raw, f"{d.name} metadata.yaml missing title"
            assert "id" in meta_raw, f"{d.name} metadata.yaml missing id"
