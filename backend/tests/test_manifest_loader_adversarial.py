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

"""Adversarial Test Suite for Manifest & SubAgent Loader Robustness.

Focus Areas:
1. Manifest & SubAgent Loader Robustness:
   - Probing load_subagent_from_yaml execution against all 21 specialist agents.
2. Metadata vs Runtime Agent Manifest Split:
   - Behavior when metadata.yaml is missing (fallback to agent.yaml & primary skill).
   - Behavior when metadata.yaml contains malformed YAML syntax.
   - Behavior when metadata.yaml contains non-dict YAML (scalars, lists).
   - Behavior when metadata.yaml contains mismatched agent IDs.
   - Behavior when metadata.yaml contains type corruption (invalid enums, bad types).
3. AgentRegistry Resilience:
   - Fault isolation when individual agent packs have corrupted metadata.
   - Dynamic catalog formatting with fallback metadata.
   - On-demand loading behavior for corrupt/missing agents.
4. Persona Slim & Archive Integrity:
   - Manifest loader behavior when persona_slim.md is missing.
   - Persona file traversal defenses.
5. Root Profile Schema:
   - Verification of carefold-profile.yaml contracts.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any, Dict, List
import pytest
import yaml

from carefold.agents.registry import AgentRegistry
from carefold.loaders.agent_loader import (
    ManifestValidationError,
    load_agent,
    load_all_agents,
    load_subagent_from_yaml,
)
from carefold.schemas.manifest import AgentManifest, AgentMaturity, RiskClass


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
SKILLS_DIR = REPO_ROOT / "skills"
PROFILE_PATH = REPO_ROOT / "carefold-profile.yaml"

SPECIALIST_AGENT_IDS = [
    "cardiology-guide",
    "pulmonology-guide",
    "derma-guide",
    "gastro-guide",
    "neurology-guide",
    "nephrology-guide",
    "endocrinology-guide",
    "rheuma-guide",
    "ortho-guide",
    "urology-guide",
    "ent-guide",
    "eye-guide",
    "oncology-navigator",
    "visit-steward",
    "benefits-guide",
    "claims-appeals-guide",
    "prior-auth-navigator",
    "formulary-guide",
    "records-coordinator",
    "habit-companion",
]


# ============================================================================
# Section 1: SubAgent Loader Execution & Bug Reproduction
# ============================================================================

class TestSubAgentLoaderExecution:
    """Probes load_subagent_from_yaml execution against runtime agent packs."""

    @pytest.mark.parametrize("agent_id", SPECIALIST_AGENT_IDS)
    def test_load_subagent_from_yaml_execution(self, agent_id: str):
        """Empirically asserts load_subagent_from_yaml can execute without NameError."""
        agent_dir = AGENTS_DIR / agent_id
        assert agent_dir.is_dir(), f"Agent directory missing: {agent_dir}"
        # This will raise NameError: name 'PHASE_0_REGISTRY' is not defined
        subagent = load_subagent_from_yaml(agent_dir)
        assert isinstance(subagent, dict)
        assert subagent["name"] == agent_id
        assert "system_prompt" in subagent
        assert "tools" in subagent


# ============================================================================
# Section 2: load_agent() Metadata Fallback & Resilience
# ============================================================================

class TestLoadAgentMetadataResilience:
    """Adversarially probes load_agent() with corrupted, missing, and mismatched metadata."""

    def test_load_agent_missing_metadata_yaml_fallback(self, tmp_path: Path):
        """Verifies clean fallback when metadata.yaml is completely absent."""
        # Create an isolated mock agent pack
        agent_dir = tmp_path / "cardiology-guide"
        agent_dir.mkdir(parents=True)

        slim_agent_yaml = {
            "name": "cardiology-guide",
            "description": "Custom cardiology test description.",
            "model": "ollama:llama3.2",
            "skills": ["cardiology-prep"],
            "tools": ["skill-docs", "attach-read"],
            "persona": "persona_slim.md",
        }
        (agent_dir / "agent.yaml").write_text(yaml.dump(slim_agent_yaml), encoding="utf-8")
        (agent_dir / "persona_slim.md").write_text(
            "# ROLE & EMPATHY:\nYou are a cardiology navigator.\n\n# CLINICAL SCOPE & FOCUS:\nFocus on heart health.",
            encoding="utf-8",
        )

        manifest, effective_tools, loaded_skills = load_agent(agent_dir, SKILLS_DIR)

        assert manifest.id == "cardiology-guide"
        # Title must fall back to title-cased ID
        assert manifest.title == "Cardiology Guide"
        # Risk class falls back to primary skill's declared risk class (wellness)
        assert manifest.risk_class == RiskClass.WELLNESS
        # Domain and category must fall back to primary skill
        assert manifest.domain.value == "clinical"
        assert manifest.category == "clinical.cardiology"
        # Effective tools union must be computed correctly
        assert "attach-read" in effective_tools
        assert "skill-docs" in effective_tools

    def test_load_agent_clinical_skill_elevation(self, tmp_path: Path):
        """Verifies load_agent elevates risk_class to clinical_assist if a declared skill is clinical_assist."""
        agent_dir = tmp_path / "custom-agent"
        agent_dir.mkdir(parents=True)

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(parents=True)
        mock_skill = skills_dir / "clinical-skill"
        mock_skill.mkdir(parents=True)
        (mock_skill / "SKILL.md").write_text(
            "---\nname: clinical-skill\ndescription: A clinical skill\nallowed-tools: skill-docs\n"
            "metadata:\n  risk_class: clinical_assist\n  domain: clinical\n  category: clinical.test\n"
            "  tools:\n  - skill-docs\n---\n"
            "Not a clinician and not emergency care. If this is an emergency, contact local emergency services. "
            "Do not change medication without the prescribing clinician.\n",
            encoding="utf-8",
        )

        agent_yaml = {
            "name": "custom-agent",
            "persona": "persona_slim.md",
            "skills": ["clinical-skill"],
        }
        (agent_dir / "agent.yaml").write_text(yaml.dump(agent_yaml), encoding="utf-8")
        (agent_dir / "persona_slim.md").write_text("Test persona", encoding="utf-8")

        manifest, _, _ = load_agent(agent_dir, skills_dir)
        assert manifest.risk_class == RiskClass.CLINICAL_ASSIST

    def test_load_agent_malformed_metadata_yaml(self, tmp_path: Path):
        """Verifies load_agent raises ManifestValidationError on syntactically invalid YAML in metadata.yaml."""
        agent_dir = tmp_path / "cardiology-guide"
        agent_dir.mkdir(parents=True)

        slim_agent_yaml = {
            "name": "cardiology-guide",
            "persona": "persona_slim.md",
            "skills": ["cardiology-prep"],
        }
        (agent_dir / "agent.yaml").write_text(yaml.dump(slim_agent_yaml), encoding="utf-8")
        (agent_dir / "persona_slim.md").write_text("Test persona", encoding="utf-8")
        (agent_dir / "metadata.yaml").write_text("title: [unclosed list", encoding="utf-8")

        with pytest.raises(ManifestValidationError) as exc_info:
            load_agent(agent_dir, SKILLS_DIR)
        assert "Malformed YAML in" in str(exc_info.value)

    def test_load_agent_non_dict_metadata_yaml(self, tmp_path: Path):
        """Verifies load_agent ignores non-dict YAML in metadata.yaml and falls back gracefully."""
        agent_dir = tmp_path / "cardiology-guide"
        agent_dir.mkdir(parents=True)

        slim_agent_yaml = {
            "name": "cardiology-guide",
            "persona": "persona_slim.md",
            "skills": ["cardiology-prep"],
        }
        (agent_dir / "agent.yaml").write_text(yaml.dump(slim_agent_yaml), encoding="utf-8")
        (agent_dir / "persona_slim.md").write_text("Test persona", encoding="utf-8")
        # metadata.yaml contains a list, not a mapping
        (agent_dir / "metadata.yaml").write_text("- item1\n- item2\n- item3\n", encoding="utf-8")

        manifest, _, _ = load_agent(agent_dir, SKILLS_DIR)
        assert manifest.id == "cardiology-guide"
        assert manifest.title == "Cardiology Guide"

    def test_load_agent_mismatched_id_in_metadata_yaml(self, tmp_path: Path):
        """Verifies load_agent rejects metadata.yaml that alters agent id to mismatch directory name."""
        agent_dir = tmp_path / "cardiology-guide"
        agent_dir.mkdir(parents=True)

        # agent.yaml has no explicit 'id' key (standard in decomposed agents)
        slim_agent_yaml = {
            "name": "cardiology-guide",
            "persona": "persona_slim.md",
            "skills": ["cardiology-prep"],
        }
        (agent_dir / "agent.yaml").write_text(yaml.dump(slim_agent_yaml), encoding="utf-8")
        (agent_dir / "persona_slim.md").write_text("Test persona", encoding="utf-8")
        # metadata.yaml provides conflicting id
        (agent_dir / "metadata.yaml").write_text("id: conflicting-guide\ntitle: Conflicting\n", encoding="utf-8")

        with pytest.raises(ManifestValidationError) as exc_info:
            load_agent(agent_dir, SKILLS_DIR)
        assert "Agent ID mismatch" in str(exc_info.value)

    def test_load_agent_corrupted_field_types_in_metadata(self, tmp_path: Path):
        """Verifies Pydantic schema validation rejects corrupt field types in metadata.yaml."""
        agent_dir = tmp_path / "cardiology-guide"
        agent_dir.mkdir(parents=True)

        slim_agent_yaml = {
            "name": "cardiology-guide",
            "persona": "persona_slim.md",
            "skills": ["cardiology-prep"],
        }
        (agent_dir / "agent.yaml").write_text(yaml.dump(slim_agent_yaml), encoding="utf-8")
        (agent_dir / "persona_slim.md").write_text("Test persona", encoding="utf-8")
        # metadata.yaml has invalid maturity and tags type
        (agent_dir / "metadata.yaml").write_text(
            "maturity: invalid_maturity_state\ntags: 12345\n",
            encoding="utf-8",
        )

        with pytest.raises(ManifestValidationError) as exc_info:
            load_agent(agent_dir, SKILLS_DIR)
        assert "Invalid agent.yaml in" in str(exc_info.value)

    def test_load_agent_missing_persona_slim_rejected(self, tmp_path: Path):
        """Verifies load_agent rejects agent pack when persona_slim.md is missing."""
        agent_dir = tmp_path / "cardiology-guide"
        agent_dir.mkdir(parents=True)

        slim_agent_yaml = {
            "name": "cardiology-guide",
            "persona": "persona_slim.md",
            "skills": ["cardiology-prep"],
        }
        (agent_dir / "agent.yaml").write_text(yaml.dump(slim_agent_yaml), encoding="utf-8")
        # Do not create persona_slim.md

        with pytest.raises(ManifestValidationError) as exc_info:
            load_agent(agent_dir, SKILLS_DIR)
        assert 'Persona file not found: "persona_slim.md"' in str(exc_info.value)


# ============================================================================
# Section 3: AgentRegistry Resilience Under Metadata Corruption
# ============================================================================

class TestAgentRegistryResilience:
    """Stress tests AgentRegistry under corrupted and missing metadata scenarios."""

    def test_registry_fault_isolation_on_corrupted_agent_pack(self, tmp_path: Path):
        """Asserts that one corrupted agent pack does not crash the registry or block other agents."""
        agents_root = tmp_path / "agents"
        agents_root.mkdir()

        # Agent 1: Valid
        a1 = agents_root / "valid-agent"
        a1.mkdir()
        (a1 / "agent.yaml").write_text(
            yaml.dump({"name": "valid-agent", "persona": "persona_slim.md", "tools": ["skill-docs"]}),
            encoding="utf-8",
        )
        (a1 / "persona_slim.md").write_text("Valid persona", encoding="utf-8")
        (a1 / "metadata.yaml").write_text("title: Valid Agent\n", encoding="utf-8")

        # Agent 2: Corrupted metadata
        a2 = agents_root / "corrupt-agent"
        a2.mkdir()
        (a2 / "agent.yaml").write_text(
            yaml.dump({"name": "corrupt-agent", "persona": "persona_slim.md"}),
            encoding="utf-8",
        )
        (a2 / "persona_slim.md").write_text("Corrupt persona", encoding="utf-8")
        (a2 / "metadata.yaml").write_text("title: [broken yaml: {", encoding="utf-8")

        registry = AgentRegistry(agents_root)

        # Registry should cleanly load valid-agent and skip corrupt-agent
        assert "valid-agent" in registry
        assert "corrupt-agent" not in registry
        assert registry.get("valid-agent") is not None
        assert registry.get("corrupt-agent") is None

        with pytest.raises(KeyError):
            _ = registry["corrupt-agent"]

    def test_registry_format_agent_catalog_with_decomposed_agents(self):
        """Asserts that format_agent_catalog formats live decomposed agents cleanly."""
        registry = AgentRegistry(AGENTS_DIR, SKILLS_DIR)
        catalog = registry.format_agent_catalog()
        assert len(catalog) > 100
        for agent_id in ["cardiology-guide", "pulmonology-guide", "visit-steward"]:
            assert f"**{agent_id}**" in catalog


# ============================================================================
# Section 4: Root Profile & Contract Verification
# ============================================================================

class TestCarefoldProfileContract:
    """Verifies carefold-profile.yaml structure and safety directives."""

    def test_carefold_profile_exists_and_parses(self):
        """Verifies carefold-profile.yaml exists, is valid YAML, and contains required keys."""
        assert PROFILE_PATH.is_file(), f"carefold-profile.yaml missing at {PROFILE_PATH}"
        data = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

        # Check harness structure
        assert "harness" in data, "Missing top-level 'harness' key"
        harness = data["harness"]
        assert "system_prompt_suffix" in harness, "Missing 'system_prompt_suffix' in harness"
        assert "general_purpose_subagent" in harness, "Missing 'general_purpose_subagent' in harness"
        assert harness["general_purpose_subagent"].get("enabled") is False, (
            "general_purpose_subagent.enabled must be False"
        )

        suffix = harness["system_prompt_suffix"]
        assert "UNIVERSAL CLINICAL SAFETY BOUNDARIES" in suffix
        assert "911" in suffix or "emergency" in suffix.lower()

    def test_all_21_specialists_have_metadata_and_slim_persona(self):
        """Verifies all 21 specialist agents have required canonical files."""
        for agent_id in SPECIALIST_AGENT_IDS:
            a_dir = AGENTS_DIR / agent_id
            assert (a_dir / "agent.yaml").is_file(), f"{agent_id} missing agent.yaml"
            assert (a_dir / "metadata.yaml").is_file(), f"{agent_id} missing metadata.yaml"
            assert (a_dir / "persona.md").is_file(), f"{agent_id} missing persona.md"
            assert not (a_dir / "persona_slim.md").is_file(), f"{agent_id} has residual persona_slim.md"
            assert not (a_dir / "persona.md.migrated").is_file(), f"{agent_id} has residual persona.md.migrated"

            # Check that persona.md is slim (< 400 words)
            persona_text = (a_dir / "persona.md").read_text(encoding="utf-8")
            words = len(persona_text.split())
            assert 100 <= words <= 350, f"{agent_id} persona.md word count {words} outside 100-350"
