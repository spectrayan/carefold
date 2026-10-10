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

"""Adversarial stress-testing suite for Prompt Token Reduction & Engine Runner Fuzzing.

Verifies:
1. Empirically verifies >=60% system prompt token reduction across all 20 specialist agents + _template.
2. Empirically verifies complete absence of legacy Section 3 interaction protocols and full skill bodies from Turn-1 prompts.
3. Stress-tests and fuzzes agent_factory.py, load_subagent_from_yaml(), load_all_subagents(), and AgentRegistry.
4. Validates dynamic skill generation prompt assembly and tool resolution.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
from typing import Any, Dict, List
import pytest
import tiktoken
import yaml

from carefold.agents.registry import AgentRegistry, get_agent_registry
from carefold.constants.paths import AGENTS_DIR, SKILLS_DIR
from carefold.engine.agent_factory import load_all_subagents
from carefold.loaders.agent_loader import load_subagent_from_yaml
from carefold.resources.loader import get_resource_loader
from carefold.schemas.manifest import PHASE_0_REGISTRY, AgentManifest
from carefold.templates.engine import render_template
from carefold.workflows.nodes.agent_execution_node import AgentExecutionNode


@pytest.fixture(scope="module")
def token_encoder():
    return tiktoken.get_encoding("cl100k_base")


@pytest.fixture(scope="module")
def workspace_root():
    ws = Path(__file__).resolve().parent.parent.parent
    if not (ws / "agents").is_dir():
        ws = Path.cwd()
    return ws


@pytest.fixture(scope="module")
def agent_registry(workspace_root):
    return get_agent_registry(workspace_root / "agents", workspace_root / "skills", force_reload=True)


@pytest.fixture(scope="module")
def execution_node(agent_registry):
    return AgentExecutionNode(registry=agent_registry)


def get_all_agent_directories(workspace_root: Path) -> List[Path]:
    agents_dir = workspace_root / "agents"
    return sorted([d for d in agents_dir.iterdir() if d.is_dir() and d.name != "_system"])


# =============================================================================
# Section 1: Empirical System Prompt Token Reduction & Protocol Purge
# =============================================================================

class TestSystemPromptTokenReductionAndProtocolPurge:
    """Empirical verification of >=60% token reduction and absence of legacy protocols."""

    @pytest.mark.parametrize("agent_dir", get_all_agent_directories(Path(__file__).resolve().parent.parent.parent), ids=lambda d: d.name)
    def test_native_subagent_token_reduction_exceeds_60_percent(self, agent_dir: Path, workspace_root: Path, token_encoder):
        """Empirically asserts that native SubAgent prompt (+ root profile suffix) reduces tokens by >= 60%."""
        aid = agent_dir.name
        skills_dir = workspace_root / "skills"

        # 1. Reconstruct legacy eager stuffed prompt from origin/main
        try:
            legacy_persona = subprocess.check_output(
                ["git", "show", f"origin/main:agents/{aid}/persona.md"],
                text=True,
                cwd=workspace_root,
            )
        except Exception:
            legacy_persona = (agent_dir / "persona.md").read_text(encoding="utf-8")

        ay = yaml.safe_load((agent_dir / "agent.yaml").read_text(encoding="utf-8")) or {}
        declared_skills = ay.get("skills", [])

        legacy_skills = []
        legacy_refs = []
        for s_id in declared_skills:
            s_file = skills_dir / s_id / "SKILL.md"
            if s_file.is_file():
                try:
                    raw_sk = subprocess.check_output(
                        ["git", "show", f"origin/main:skills/{s_id}/SKILL.md"],
                        text=True,
                        cwd=workspace_root,
                    )
                except Exception:
                    raw_sk = s_file.read_text(encoding="utf-8")
                legacy_skills.append({"id": s_id, "name": s_id.replace("-", " ").title(), "instructions": raw_sk})
            r_dir = skills_dir / s_id / "references"
            if r_dir.is_dir():
                for rf in r_dir.glob("*.md"):
                    legacy_refs.append({"name": rf.name, "content": rf.read_text(encoding="utf-8")})

        loader = get_resource_loader()
        forbidden_rules = ay.get("forbidden") or loader.get_refusal_patterns().get("default_forbidden_intents", [])
        forbidden_str = ", ".join(forbidden_rules)
        safety_preamble = loader.get_safety_preamble_template().format(forbidden_str=forbidden_str)

        manifest_mock = AgentManifest(
            id=aid,
            title=ay.get("title") or aid.replace("-", " ").title(),
            version=ay.get("version", "0.1.0"),
            risk_class=ay.get("risk_class", "wellness"),
            skills=declared_skills,
            persona=legacy_persona.strip(),
        )

        legacy_ctx = {
            "safety_preamble": safety_preamble,
            "manifest": manifest_mock,
            "persona": legacy_persona.strip(),
            "skills": legacy_skills,
            "has_skills": bool(legacy_skills),
            "provisioned_references": legacy_refs,
            "has_provisioned_references": bool(legacy_refs),
        }
        legacy_prompt = render_template("agent_execution_prompt", legacy_ctx)
        legacy_tokens = len(token_encoder.encode(legacy_prompt))

        # 2. Measure Deep Agents progressive disclosure prompt (subagent prompt + carefold profile suffix)
        profile_path = workspace_root / "carefold-profile.yaml"
        profile_data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
        profile_suffix = profile_data.get("harness", {}).get("system_prompt_suffix", "")

        sub = load_subagent_from_yaml(agent_dir)
        subagent_prompt = sub["system_prompt"] + "\n" + profile_suffix
        subagent_tokens = len(token_encoder.encode(subagent_prompt))

        reduction_pct = (legacy_tokens - subagent_tokens) / legacy_tokens * 100.0

        assert reduction_pct >= 60.0, (
            f"Agent '{aid}' token reduction was {reduction_pct:.2f}% (expected >= 60.0%). "
            f"Legacy tokens: {legacy_tokens}, SubAgent tokens: {subagent_tokens}."
        )

    @pytest.mark.parametrize("agent_dir", get_all_agent_directories(Path(__file__).resolve().parent.parent.parent), ids=lambda d: d.name)
    def test_no_legacy_section3_interaction_protocol_in_turn1(self, agent_dir: Path, agent_registry, execution_node):
        """Asserts that no legacy Section 3 interaction protocols remain in Turn-1 system prompts or personas."""
        aid = agent_dir.name
        forbidden_protocol_patterns = [
            "STRUCTURED INTERACTION PROTOCOL",
            "Structured Interaction Protocol",
            "When a user seeks guidance, you follow a 4-step structured protocol",
            "When a user seeks guidance, you follow a 5-step structured protocol",
        ]

        # 1. Check persona.md directly
        persona_text = (agent_dir / "persona.md").read_text(encoding="utf-8")
        for pat in forbidden_protocol_patterns:
            assert pat not in persona_text, f"Agent '{aid}' persona.md still contains legacy protocol: '{pat}'"

        # 2. Check SubAgent system prompt
        sub = load_subagent_from_yaml(agent_dir)
        sub_prompt = sub.get("system_prompt", "")
        for pat in forbidden_protocol_patterns:
            assert pat not in sub_prompt, f"Agent '{aid}' SubAgent system_prompt contains legacy protocol: '{pat}'"

        # 3. Check AgentExecutionNode Turn-1 system prompt
        manifest = agent_registry.get(aid)
        if manifest:
            node_prompt = execution_node._resolve_system_prompt(manifest, {})
            for pat in forbidden_protocol_patterns:
                assert pat not in node_prompt, f"Agent '{aid}' Turn-1 prompt contains legacy protocol: '{pat}'"

    @pytest.mark.parametrize("agent_dir", get_all_agent_directories(Path(__file__).resolve().parent.parent.parent), ids=lambda d: d.name)
    def test_no_full_skill_bodies_in_turn1_prompts(self, agent_dir: Path, agent_registry, execution_node):
        """Asserts that full skill bodies are not eagerly inlined into Turn-1 prompts."""
        aid = agent_dir.name
        forbidden_skill_sections = [
            "## Intended Use & Safety Disclosures",
            "## Scope & Capabilities",
            "## Reference Materials",
            "## Strict Negative Constraints",
        ]

        # 1. Subagent prompt
        sub = load_subagent_from_yaml(agent_dir)
        sub_prompt = sub.get("system_prompt", "")
        for sec in forbidden_skill_sections:
            assert sec not in sub_prompt, f"Agent '{aid}' SubAgent prompt inlines skill section: '{sec}'"

        # 2. Node Turn-1 prompt
        manifest = agent_registry.get(aid)
        if manifest:
            node_prompt = execution_node._resolve_system_prompt(manifest, {})
            for sec in forbidden_skill_sections:
                assert sec not in node_prompt, f"Agent '{aid}' Turn-1 prompt inlines full skill section: '{sec}'"


# =============================================================================
# Section 2: Fuzzing & Stress-Testing agent_factory and load_subagent_from_yaml
# =============================================================================

class TestAgentFactoryFuzzingAndStressHarness:
    """Fuzzing and adversarial input harness for loader and factory functions."""

    def test_load_subagent_missing_yaml_raises_filenotfound(self, tmp_path):
        """Missing agent.yaml in agent dir must raise FileNotFoundError."""
        empty_dir = tmp_path / "ghost-agent"
        empty_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="Missing required agent.yaml"):
            load_subagent_from_yaml(empty_dir)

    def test_load_subagent_empty_yaml_returns_safe_defaults(self, tmp_path):
        """Empty agent.yaml must return default SubAgent structure without crashing."""
        agent_dir = tmp_path / "blank-agent"
        agent_dir.mkdir()
        (agent_dir / "agent.yaml").write_text("", encoding="utf-8")
        sub = load_subagent_from_yaml(agent_dir)

        assert sub["name"] == "blank-agent"
        assert sub["description"] == ""
        assert sub["system_prompt"] == ""
        assert sub["model"] == "ollama:llama3.2"
        assert sub["skills"] == []
        assert sub["tools"] == []

    def test_load_subagent_filters_unauthorized_tools_outside_phase0(self, tmp_path):
        """Tools outside PHASE_0_REGISTRY must be strictly dropped from valid_tools."""
        agent_dir = tmp_path / "toxic-tools-agent"
        agent_dir.mkdir()
        (agent_dir / "agent.yaml").write_text(
            "name: toxic-agent\n"
            "tools:\n"
            "  - attach-read\n"
            "  - skill-docs\n"
            "  - bash_exec\n"
            "  - python_eval\n"
            "  - shell_command\n"
            "  - workspace-note\n",
            encoding="utf-8",
        )
        sub = load_subagent_from_yaml(agent_dir)

        assert "attach-read" in sub["tools"]
        assert "skill-docs" in sub["tools"]
        assert "workspace-note" in sub["tools"]
        assert "bash_exec" not in sub["tools"]
        assert "python_eval" not in sub["tools"]
        assert "shell_command" not in sub["tools"]
        for t in sub["tools"]:
            assert t in PHASE_0_REGISTRY

    def test_load_subagent_malformed_yaml_raises_parser_error(self, tmp_path):
        """Malformed YAML syntax must raise a YAML parsing exception."""
        agent_dir = tmp_path / "broken-yaml-agent"
        agent_dir.mkdir()
        (agent_dir / "agent.yaml").write_text("name: broken\nskills: [unclosed sequence", encoding="utf-8")
        with pytest.raises(yaml.YAMLError):
            load_subagent_from_yaml(agent_dir)

    def test_load_subagent_resilient_to_non_list_tools_and_skills(self, tmp_path):
        """Malformed field types (string instead of list) must be handled defensively."""
        agent_dir = tmp_path / "type-mismatch-agent"
        agent_dir.mkdir()
        (agent_dir / "agent.yaml").write_text(
            "name: mismatched\n"
            "tools: attach-read\n"  # String instead of list
            "skills: cardiology-prep\n",  # String instead of list
            encoding="utf-8",
        )
        sub = load_subagent_from_yaml(agent_dir)
        assert isinstance(sub["tools"], list)
        assert isinstance(sub["skills"], list)

    def test_load_all_subagents_ignores_hidden_and_system_directories(self, tmp_path):
        """load_all_subagents must skip entries starting with '.' or '_'."""
        (tmp_path / "_template").mkdir()
        ((tmp_path / "_template") / "agent.yaml").write_text("name: template\n", encoding="utf-8")

        (tmp_path / ".hidden").mkdir()
        ((tmp_path / ".hidden") / "agent.yaml").write_text("name: hidden\n", encoding="utf-8")

        valid = tmp_path / "cardio-agent"
        valid.mkdir()
        (valid / "agent.yaml").write_text("name: cardio\n", encoding="utf-8")

        subs = load_all_subagents(tmp_path)
        names = [s["name"] for s in subs]
        assert "cardio" in names
        assert "template" not in names
        assert "hidden" not in names

    def test_load_all_subagents_resilient_to_corrupted_directory(self, tmp_path):
        """load_all_subagents skips corrupted directories without crashing the whole batch."""
        valid = tmp_path / "valid-agent"
        valid.mkdir()
        (valid / "agent.yaml").write_text("name: valid\n", encoding="utf-8")

        broken = tmp_path / "broken-agent"
        broken.mkdir()
        (broken / "agent.yaml").write_text("name: [unclosed", encoding="utf-8")

        subs = load_all_subagents(tmp_path)
        assert len(subs) == 1
        assert subs[0]["name"] == "valid"

    def test_load_all_subagents_empty_or_nonexistent_returns_empty(self, tmp_path):
        """Non-existent or empty directories safely return empty list."""
        assert load_all_subagents(tmp_path / "nonexistent") == []
        empty = tmp_path / "empty_dir"
        empty.mkdir()
        assert load_all_subagents(empty) == []


# =============================================================================
# Section 3: AgentRegistry SubAgent Integration Tests
# =============================================================================

class TestAgentRegistrySubagentMethods:
    """Verification of AgentRegistry.get_subagent() and AgentRegistry.list_subagents()."""

    def test_get_subagent_valid_specialist(self, agent_registry):
        """get_subagent returns complete SubAgent dict for registered specialist."""
        sub = agent_registry.get_subagent("cardiology-guide")
        assert sub is not None
        assert sub["name"] == "cardiology-guide"
        assert "cardiology-prep" in sub["skills"]
        assert "skill-docs" in sub["tools"]
        assert sub["system_prompt"]
        assert "ROLE & EMPATHY:" in sub["system_prompt"]

    def test_get_subagent_invalid_or_hidden_returns_none(self, agent_registry):
        """get_subagent returns None for empty, invalid, or leading-underscore IDs."""
        assert agent_registry.get_subagent("") is None
        assert agent_registry.get_subagent(None) is None
        assert agent_registry.get_subagent("_template") is None
        assert agent_registry.get_subagent(".hidden") is None
        assert agent_registry.get_subagent("nonexistent-agent-id-12345") is None

    def test_list_subagents_returns_non_empty_list(self, agent_registry):
        """list_subagents returns all specialist subagents."""
        subs = agent_registry.list_subagents()
        assert len(subs) >= 20
        sub_names = {s["name"] for s in subs}
        assert "cardiology-guide" in sub_names
        assert "pulmonology-guide" in sub_names
        assert "benefits-guide" in sub_names
        assert "visit-steward" in sub_names


# =============================================================================
# Section 4: Dynamic Skill Generation Prompt Assembly & Tool Resolution
# =============================================================================

class TestDynamicSkillPromptAssembly:
    """Stress tests dynamic skill injection into AgentExecutionNode prompts."""

    @pytest.mark.asyncio
    async def test_execution_node_injects_dynamic_skills_and_references(self, agent_registry):
        """Verifies that generated_skills are properly formatted into prompt without corrupting Turn-1 base."""
        node = AgentExecutionNode(registry=agent_registry)
        manifest = agent_registry.get("habit-companion")

        dyn_skill = {
            "id": "hydration-tracking",
            "name": "Daily Hydration Tracking",
            "description": "Encouraging 8 glasses of water daily",
            "instructions": "Track ounces of water consumed each morning and evening.",
            "references": {
                "hydration_targets.md": "# Hydration Targets\nTarget 64 oz minimum per day.",
            },
            "tools": ["workspace-note"],
        }

        state = {
            "current_agent": "habit-companion",
            "generated_skills": [dyn_skill],
        }

        prompt = node._resolve_system_prompt(manifest, state)
        assert "DYNAMICALLY GENERATED SKILLS (PROVIDED BY ORCHESTRATOR)" in prompt
        assert "Daily Hydration Tracking" in prompt
        assert "Track ounces of water consumed each morning and evening." in prompt
        assert "Hydration Targets" in prompt
        assert "Target 64 oz minimum per day." in prompt

    def test_execution_node_resolves_dynamic_tools(self, agent_registry):
        """Verifies that tools declared in dynamic skills are resolved into agent execution tools."""
        node = AgentExecutionNode(registry=agent_registry)
        manifest = agent_registry.get("habit-companion")

        dyn_skill = {
            "id": "hydration-tracking",
            "name": "Daily Hydration Tracking",
            "tools": ["workspace-note", "attach-read"],
        }

        state = {
            "current_agent": "habit-companion",
            "generated_skills": [dyn_skill],
        }

        resolved_tools = node._resolve_tools("habit-companion", manifest, state)
        tool_names = [t.name if hasattr(t, "name") else (t.get("name") if isinstance(t, dict) else str(t)) for t in resolved_tools]
        assert "workspace-note" in tool_names
        assert "attach-read" in tool_names
