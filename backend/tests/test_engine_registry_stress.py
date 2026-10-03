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

"""Adversarial engine and registry stress-fuzzing suite.

Verifies:
1. Stress-tests create_carefold_agent() with various subagent combinations and Ollama configurations.
2. Verifies langchain-ollama initializes ollama:llama3.2 without ImportError.
3. Verifies AgentRegistry.list_subagents() returns exactly 20 specialist subagents with valid tools.
4. Fuzzes AgentRegistry.get_subagent() against traversal attacks and corrupted input.
5. Verifies harness profile unwrapping, schema resolution, and safety middleware enforcement.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List
import pytest
import yaml

from carefold.agents.registry import AgentRegistry, get_agent_registry
from carefold.constants.paths import AGENTS_DIR, SKILLS_DIR
from carefold.engine.agent_factory import (
    create_carefold_agent,
    load_all_subagents,
    load_subagent_from_yaml,
)
from carefold.loaders.union import ToolValidationError
from carefold.middleware.clinical_safety import ClinicalSafetyMiddleware
from carefold.middleware.skills import (
    CAREFOLD_SKILLS_PROMPT,
    CarefoldSkillsMiddleware,
    create_carefold_skills_middleware,
)
from carefold.model.providers.ollama_provider import OllamaProvider
from carefold.schemas.manifest import PHASE_0_REGISTRY, RiskClass
from carefold.tools.registry import CLOSED_TOOL_DEFINITIONS
from langchain.chat_models import init_chat_model
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph


@pytest.fixture(scope="module")
def workspace_root() -> Path:
    ws = Path(__file__).resolve().parent.parent.parent
    if not (ws / "agents").is_dir():
        ws = Path.cwd()
    return ws


@pytest.fixture(scope="module")
def agent_registry(workspace_root: Path) -> AgentRegistry:
    return get_agent_registry(workspace_root / "agents", workspace_root / "skills", force_reload=True)


# =============================================================================
# 1. langchain-ollama and Ollama Model Resolution
# =============================================================================

class TestLangchainOllamaResolution:
    """Verifies clean initialization and backward compatibility of langchain-ollama."""

    def test_langchain_ollama_package_installed_and_version(self):
        """Verifies langchain-ollama is installed and meets the >=1.1.0 dependency."""
        import langchain_ollama

        assert hasattr(langchain_ollama, "__version__")
        version_parts = [int(p) for p in langchain_ollama.__version__.split(".")[:2]]
        assert version_parts >= [1, 1], f"Expected >=1.1.0, got {langchain_ollama.__version__}"

    def test_init_chat_model_ollama_llama32_no_importerror(self):
        """Verifies init_chat_model('ollama:llama3.2') initializes cleanly with ChatOllama."""
        from langchain_ollama.chat_models import ChatOllama

        model = init_chat_model("ollama:llama3.2")
        assert isinstance(model, ChatOllama)
        assert model.model == "llama3.2"

    @pytest.mark.parametrize("model_tag", ["ollama:llama3.1", "ollama:mistral", "ollama:phi3"])
    def test_init_chat_model_other_ollama_variants(self, model_tag: str):
        """Verifies init_chat_model initializes multiple Ollama model families cleanly."""
        from langchain_ollama.chat_models import ChatOllama

        model = init_chat_model(model_tag)
        assert isinstance(model, ChatOllama)
        expected_name = model_tag.split(":", 1)[1]
        assert model.model == expected_name

    def test_ollama_provider_create_model_returns_chat_ollama(self):
        """Verifies OllamaProvider strategy instantiates ChatOllama with expected configuration."""
        from langchain_ollama.chat_models import ChatOllama

        provider = OllamaProvider(base_url="http://127.0.0.1:11434", model="llama3.2", temperature=0.0)
        inst = provider.create_model()
        assert isinstance(inst, ChatOllama)
        assert inst.model == "llama3.2"
        assert inst.temperature == 0.0

    def test_ollama_provider_backward_compatible_properties(self):
        """Verifies ChatOllama monkey-patched properties for legacy test suite compatibility."""
        provider = OllamaProvider(base_url="http://127.0.0.1:11434", model="llama3.2")
        inst = provider.create_model()

        assert hasattr(inst, "model_name")
        assert inst.model_name == "llama3.2"
        assert hasattr(inst, "openai_api_base")
        assert inst.openai_api_base.endswith("/v1")
        assert hasattr(inst, "openai_api_key")


# =============================================================================
# 2. AgentRegistry SubAgent Discovery & Tool Validity
# =============================================================================

class TestAgentRegistrySubagentDiscoveryAndTools:
    """Verifies that AgentRegistry returns exactly 20 specialist subagents and 0 system agents."""

    EXPECTED_SPECIALISTS = {
        "benefits-guide",
        "cardiology-guide",
        "claims-appeals-guide",
        "derma-guide",
        "endocrinology-guide",
        "ent-guide",
        "eye-guide",
        "formulary-guide",
        "gastro-guide",
        "habit-companion",
        "nephrology-guide",
        "neurology-guide",
        "oncology-navigator",
        "ortho-guide",
        "prior-auth-navigator",
        "pulmonology-guide",
        "records-coordinator",
        "rheuma-guide",
        "urology-guide",
        "visit-steward",
    }

    DISALLOWED_SYSTEM_AGENTS = {
        "_template",
        "orchestrator",
        "document-extractor",
        "quality-reviewer",
        "skill-generator",
        "suggestion-generator",
        "triage-auditor",
    }

    def test_list_subagents_returns_exactly_20_specialists(self, agent_registry: AgentRegistry):
        """Asserts list_subagents() returns exactly 20 subagents matching the specialist manifest."""
        subagents = agent_registry.list_subagents()
        assert len(subagents) == 20, f"Expected 20 specialist subagents, got {len(subagents)}"
        names = {s["name"] for s in subagents}
        assert names == self.EXPECTED_SPECIALISTS

    def test_list_subagents_contains_zero_system_agents(self, agent_registry: AgentRegistry):
        """Asserts zero system agents or template agents leak into list_subagents()."""
        subagents = agent_registry.list_subagents()
        names = {s["name"] for s in subagents}
        overlap = names.intersection(self.DISALLOWED_SYSTEM_AGENTS)
        assert len(overlap) == 0, f"System agents found in subagents list: {overlap}"
        for name in names:
            assert not name.startswith(("_", ".")), f"Hidden or private agent found: {name}"

    def test_list_subagents_tools_strictly_in_phase_0_registry(self, agent_registry: AgentRegistry):
        """Asserts every declared tool across all 20 subagents is in PHASE_0_REGISTRY."""
        subagents = agent_registry.list_subagents(resolve_tools=True)
        for sub in subagents:
            agent_name = sub["name"]
            tools = sub.get("tools", [])
            assert len(tools) > 0, f"Agent '{agent_name}' has empty tools list"
            for t in tools:
                tool_name = t.get("name") if isinstance(t, dict) else (getattr(t, "name", None) or str(t))
                assert tool_name in PHASE_0_REGISTRY, (
                    f"Agent '{agent_name}' declares tool '{tool_name}' not in PHASE_0_REGISTRY: {PHASE_0_REGISTRY}"
                )

    def test_list_subagents_structure_fields(self, agent_registry: AgentRegistry):
        """Asserts all 20 subagents contain required Deep Agents SubAgent dictionary fields."""
        subagents = agent_registry.list_subagents()
        for sub in subagents:
            assert isinstance(sub, dict)
            assert "name" in sub and isinstance(sub["name"], str)
            assert "description" in sub and isinstance(sub["description"], str)
            assert "system_prompt" in sub and isinstance(sub["system_prompt"], str)
            assert "tools" in sub and isinstance(sub["tools"], list)
            assert "skills" in sub and isinstance(sub["skills"], list)

    @pytest.mark.parametrize(
        "invalid_id",
        [
            "",
            None,
            "_template",
            ".hidden",
            "../../../etc/passwd",
            "../agents/cardiology-guide",
            "_system/orchestrator",
            "_system",
            "nonexistent-specialist",
            "   ",
            "\x00nullbyte",
        ],
    )
    def test_get_subagent_invalid_ids_return_none(self, agent_registry: AgentRegistry, invalid_id: Any):
        """Fuzzes get_subagent with adversarial, malformed, and traversal inputs."""
        assert agent_registry.get_subagent(invalid_id) is None

    def test_get_subagent_immutability(self, agent_registry: AgentRegistry):
        """Asserts mutating the returned subagent dict does not corrupt registry state."""
        sub1 = agent_registry.get_subagent("cardiology-guide")
        assert sub1 is not None
        orig_tools_len = len(sub1["tools"])
        sub1["tools"].append("malicious-injected-tool")

        sub2 = agent_registry.get_subagent("cardiology-guide")
        assert sub2 is not None
        assert len(sub2["tools"]) == orig_tools_len
        assert "malicious-injected-tool" not in sub2["tools"]


# =============================================================================
# 3. create_carefold_agent() Stress & Fuzzing Harness
# =============================================================================

class TestCreateCarefoldAgentStress:
    """Stress tests create_carefold_agent() across models, subagent combinations, and workspaces."""

    def test_create_carefold_agent_default_compilation(self, workspace_root: Path):
        """Verifies default create_carefold_agent compiles into a valid CompiledStateGraph."""
        agent = create_carefold_agent(workspace_root=workspace_root)
        assert isinstance(agent, CompiledStateGraph)
        assert "__start__" in agent.nodes
        assert "model" in agent.nodes
        assert "tools" in agent.nodes
        assert "clinical_safety.before_agent" in agent.nodes
        assert "clinical_safety.after_agent" in agent.nodes

    def test_create_carefold_agent_with_memory_checkpointer(self, workspace_root: Path):
        """Verifies checkpointer parameter attaches cleanly to CompiledStateGraph."""
        saver = MemorySaver()
        agent = create_carefold_agent(workspace_root=workspace_root, checkpointer=saver)
        assert isinstance(agent, CompiledStateGraph)
        assert agent.checkpointer is saver

    @pytest.mark.parametrize("model_str", ["ollama:llama3.2", "ollama:llama3.1", "ollama:mistral"])
    def test_create_carefold_agent_ollama_models(self, workspace_root: Path, model_str: str):
        """Verifies multiple Ollama model strings compile into the agent graph."""
        agent = create_carefold_agent(model=model_str, workspace_root=workspace_root)
        assert isinstance(agent, CompiledStateGraph)

    def test_create_carefold_agent_with_fake_model(self, workspace_root: Path):
        """Verifies create_carefold_agent works when passed a custom BaseChatModel."""
        fake_llm = FakeListChatModel(responses=["Test response"])
        agent = create_carefold_agent(model=fake_llm, workspace_root=workspace_root)
        assert isinstance(agent, CompiledStateGraph)

    def test_create_carefold_agent_empty_workspace(self, tmp_path: Path):
        """Verifies create_carefold_agent handles workspace with 0 subagents gracefully."""
        (tmp_path / "agents").mkdir()
        (tmp_path / "skills").mkdir()
        agent = create_carefold_agent(workspace_root=tmp_path)
        assert isinstance(agent, CompiledStateGraph)

    def test_create_carefold_agent_single_subagent(self, tmp_path: Path, workspace_root: Path):
        """Verifies create_carefold_agent compiles with exactly 1 subagent."""
        (tmp_path / "agents").mkdir()
        (tmp_path / "skills").mkdir()
        shutil.copytree(workspace_root / "agents" / "cardiology-guide", tmp_path / "agents" / "cardiology-guide")
        shutil.copytree(workspace_root / "skills" / "cardiology-prep", tmp_path / "skills" / "cardiology-prep")

        agent = create_carefold_agent(workspace_root=tmp_path)
        assert isinstance(agent, CompiledStateGraph)

    def test_create_carefold_agent_subset_subagents(self, tmp_path: Path, workspace_root: Path):
        """Verifies create_carefold_agent compiles with a subset of 5 subagents."""
        (tmp_path / "agents").mkdir()
        (tmp_path / "skills").mkdir()
        subset = ["cardiology-guide", "pulmonology-guide", "derma-guide", "gastro-guide", "habit-companion"]
        for s in subset:
            shutil.copytree(workspace_root / "agents" / s, tmp_path / "agents" / s)

        subs = load_all_subagents(tmp_path / "agents")
        assert len(subs) == 5
        agent = create_carefold_agent(workspace_root=tmp_path)
        assert isinstance(agent, CompiledStateGraph)

    def test_create_carefold_agent_corrupted_profile_yaml_graceful_recovery(self, tmp_path: Path):
        """Verifies create_carefold_agent catches corrupt profile YAML without aborting agent creation."""
        (tmp_path / "agents").mkdir()
        (tmp_path / "skills").mkdir()
        (tmp_path / "carefold-profile.yaml").write_text("broken: [unclosed yaml", encoding="utf-8")

        agent = create_carefold_agent(workspace_root=tmp_path)
        assert isinstance(agent, CompiledStateGraph)

    def test_create_carefold_agent_flat_profile_yaml(self, tmp_path: Path):
        """Verifies carefold-profile.yaml with flat structure (no 'harness:' wrapper) is accepted."""
        (tmp_path / "agents").mkdir()
        (tmp_path / "skills").mkdir()
        flat_profile = {
            "system_prompt_suffix": "# FLAT SAFETY BOUNDARIES",
            "general_purpose_subagent": {"enabled": False},
        }
        (tmp_path / "carefold-profile.yaml").write_text(yaml.safe_dump(flat_profile), encoding="utf-8")

        agent = create_carefold_agent(workspace_root=tmp_path)
        assert isinstance(agent, CompiledStateGraph)

    def test_create_carefold_agent_subagent_tool_schema_resolution(self, workspace_root: Path):
        """Verifies subagent tool strings are converted into CLOSED_TOOL_DEFINITIONS schemas."""
        subagents = load_all_subagents(workspace_root / "agents", resolve_tools=True)
        for sub in subagents:
            for t in sub.get("tools", []):
                t_name = t.get("name") if isinstance(t, dict) else str(t)
                assert t_name in CLOSED_TOOL_DEFINITIONS


# =============================================================================
# 4. Middleware Protocol and Hardening Assertions
# =============================================================================

class TestMiddlewareProtocolHardening:
    """Verifies Slot 1 and Slot 7 middleware naming, template formatting, and boundary security."""

    def test_skills_middleware_prompt_template_escaped_path(self):
        """Verifies {path} placeholder in CAREFOLD_SKILLS_PROMPT is escaped to {{path}}."""
        assert "{{path}}" in CAREFOLD_SKILLS_PROMPT
        # Attempting str.format with only expected keys should succeed without KeyError: 'path'
        formatted = CAREFOLD_SKILLS_PROMPT.format(
            skills_locations="/mock/path",
            skills_list="- test skill",
            skills_load_warnings="",
        )
        assert "{path}" in formatted  # Retained literally for downstream runtime substitution
        assert "/mock/path" in formatted

    def test_skills_middleware_name_override(self, workspace_root: Path):
        """Verifies CarefoldSkillsMiddleware overrides .name to 'SkillsMiddleware' for in-place replacement."""
        mw = create_carefold_skills_middleware(workspace_root / "skills")
        assert mw.name == "SkillsMiddleware"

    def test_clinical_safety_middleware_slot_and_name(self):
        """Verifies ClinicalSafetyMiddleware specifies Slot 7 and name 'clinical_safety'."""
        mw = ClinicalSafetyMiddleware()
        assert mw.slot == 7
        assert mw.name == "clinical_safety"

    def test_clinical_safety_middleware_blocks_arbitrary_unauthorized_tool(self):
        """Verifies ClinicalSafetyMiddleware raises ToolValidationError on unauthorized tool execution."""
        mw = ClinicalSafetyMiddleware()
        with pytest.raises(ToolValidationError, match="Phase 0 closed registry"):
            mw.before_tool("arbitrary_bash_execution")

    @pytest.mark.parametrize("risk_input", ["clinical_assist", "CLINICAL_ASSIST", "Clinical_Assist", RiskClass.CLINICAL_ASSIST])
    def test_clinical_safety_middleware_case_insensitive_risk_elevation(self, risk_input: Any):
        """Verifies case-insensitive normalization elevates risk class to 'clinical_assist'."""
        mw = ClinicalSafetyMiddleware()
        state: Dict[str, Any] = {
            "skills_metadata": [
                {
                    "name": "cardiology-prep",
                    "metadata": {"risk_class": risk_input, "tools": ["skill-docs"]},
                }
            ]
        }
        updates = mw.before_agent(state)
        assert updates is not None
        assert updates.get("carefold_risk_class") == RiskClass.CLINICAL_ASSIST.value
        assert state.get("carefold_risk_class") == RiskClass.CLINICAL_ASSIST.value

    def test_clinical_safety_middleware_appends_disclaimer_to_messages(self):
        """Verifies disclaimer is appended to messages list in DeepAgentState when output key is absent."""
        from langchain_core.messages import AIMessage

        mw = ClinicalSafetyMiddleware()
        state: Dict[str, Any] = {
            "carefold_risk_class": "clinical_assist",
            "messages": [AIMessage(content="Here is some preparation information.")],
        }
        updates = mw.after_agent(state)
        assert updates is not None
        assert "output" in updates
        assert "Not a clinician and not emergency care" in updates["output"]
        assert mw.get_canonical_disclaimer() in updates["output"]
        assert len(updates.get("messages", [])) == 1
        assert mw.get_canonical_disclaimer() in updates["messages"][0].content
