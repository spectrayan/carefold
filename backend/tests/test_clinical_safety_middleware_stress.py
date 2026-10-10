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

"""Test Suite for Clinical Safety Middleware & Tool Registry.

Adversarially fuzzes and stress-tests:
1. `ClinicalSafetyMiddleware`:
   - Unauthorized tools in agent-level tools (`tools`, `declared_tools`)
   - Unauthorized tools in skill metadata (`metadata.tools`, `tools`, `allowed-tools`)
   - Tool boundary enforcement in `before_tool` and `wrap_tool_call`
   - Secondary field tool validation bypass vulnerability
   - Fail-open behavior in `wrap_tool_call` on empty/missing tool names
   - Dynamic risk elevation across permutations of risk classes (`admin`, `wellness`, `education`, `clinical_assist`)
   - Case sensitivity in risk class parsing
   - Intended-use disclaimer enforcement in `after_agent`
   - Omission of disclaimer enforcement on native `DeepAgentState` (messages-only)
2. `CarefoldSkillsMiddleware`:
   - Unescaped `{path}` placeholder causing runtime `KeyError: 'path'` in `modify_request`
   - Chrooted `FilesystemBackend` path resolution defect causing 0 skills to load
   - Robustness to empty skills, missing metadata, and corrupted frontmatter
   - Slot 1 in-place replacement failure in `create_deep_agent` due to unaliased middleware `.name`
3. Engine Integration & Harness Profile:
   - Root `carefold-profile.yaml` loader failure due to top-level `harness:` wrapper
"""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock
import pytest
import yaml

from deepagents import HarnessProfileConfig
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.graph import _apply_custom_middleware
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.skills import SkillsMiddleware, _list_skills_with_errors
from langchain_core.messages import AIMessage

from carefold.constants.paths import SKILLS_DIR
from carefold.loaders.frontmatter import check_mandatory_intended_use
from carefold.loaders.union import ToolValidationError
from carefold.middleware.clinical_safety import ClinicalSafetyMiddleware
from carefold.middleware.skills import (
    CAREFOLD_SKILLS_PROMPT,
    CarefoldSkillsMiddleware,
    create_carefold_skills_middleware,
)
from carefold.schemas.manifest import PHASE_0_REGISTRY, RiskClass


# ============================================================================
# Section 1: ClinicalSafetyMiddleware - Tool Boundary Fuzzing
# ============================================================================

class TestClinicalSafetyMiddlewareToolBoundaries:
    """Adversarially challenges tool boundary checks across all execution phases."""

    @pytest.mark.parametrize("malicious_tool", [
        "bash",
        "exec",
        "curl",
        "subagent_run",
        "eval",
        "rm",
        "sudo",
        "cmd.exe",
        "powershell",
        "system_exec",
    ])
    def test_unauthorized_tools_in_agent_tools_rejected(self, malicious_tool: str):
        """Verifies agent-level declared tools reject unauthorized tools unconditionally."""
        mw = ClinicalSafetyMiddleware()
        state = {"tools": ["skill-docs", malicious_tool]}
        with pytest.raises(ToolValidationError) as exc:
            mw.before_agent(state)
        assert malicious_tool in str(exc.value)

    @pytest.mark.parametrize("malicious_tool", [
        "bash",
        "exec",
        "curl",
        "subagent_run",
        "python_eval",
    ])
    def test_unauthorized_tools_in_declared_tools_key_rejected(self, malicious_tool: str):
        """Verifies state['declared_tools'] key is also intercepted and validated."""
        mw = ClinicalSafetyMiddleware()
        state = {"declared_tools": [malicious_tool]}
        with pytest.raises(ToolValidationError) as exc:
            mw.before_agent(state)
        assert malicious_tool in str(exc.value)

    @pytest.mark.parametrize("malicious_tool", [
        "bash",
        "exec",
        "curl",
        "subagent_run",
    ])
    def test_unauthorized_tools_in_skill_metadata_tools_rejected(self, malicious_tool: str):
        """Verifies skill metadata.tools rejects unauthorized tools unconditionally."""
        mw = ClinicalSafetyMiddleware()
        state = {
            "skills_metadata": [
                {
                    "name": "malicious-skill",
                    "metadata": {
                        "risk_class": "clinical_assist",
                        "tools": ["skill-docs", malicious_tool],
                    },
                }
            ]
        }
        with pytest.raises(ToolValidationError) as exc:
            mw.before_agent(state)
        assert malicious_tool in str(exc.value)

    @pytest.mark.parametrize("malicious_tool", [
        "bash",
        "exec",
        "curl",
        "subagent_run",
        "",
        None,
    ])
    def test_before_tool_invocation_boundary(self, malicious_tool: Optional[str]):
        """Verifies before_tool unconditionally rejects any non-PHASE_0 tool invocation."""
        mw = ClinicalSafetyMiddleware()
        with pytest.raises(ToolValidationError):
            mw.before_tool(malicious_tool)

    def test_before_tool_allows_all_phase0_tools(self):
        """Verifies before_tool permits every valid tool in PHASE_0_REGISTRY."""
        mw = ClinicalSafetyMiddleware()
        for tool in PHASE_0_REGISTRY:
            # Should not raise ToolValidationError
            mw.before_tool(tool)

    @pytest.mark.parametrize("malicious_tool", [
        "bash",
        "exec",
        "curl",
        "subagent_run",
    ])
    def test_wrap_tool_call_dict_request(self, malicious_tool: str):
        """Verifies wrap_tool_call rejects dict requests specifying unauthorized tools."""
        mw = ClinicalSafetyMiddleware()
        handler = MagicMock()
        with pytest.raises(ToolValidationError):
            mw.wrap_tool_call({"name": malicious_tool}, handler)
        handler.assert_not_called()

    @pytest.mark.parametrize("malicious_tool", [
        "bash",
        "exec",
        "curl",
        "subagent_run",
    ])
    def test_wrap_tool_call_object_request(self, malicious_tool: str):
        """Verifies wrap_tool_call rejects object requests specifying unauthorized tools."""
        mw = ClinicalSafetyMiddleware()
        handler = MagicMock()

        class ToolRequest:
            def __init__(self, name: str):
                self.tool_name = name

        with pytest.raises(ToolValidationError):
            mw.wrap_tool_call(ToolRequest(malicious_tool), handler)
        handler.assert_not_called()

    def test_wrap_tool_call_allows_phase0_tool(self):
        """Verifies wrap_tool_call executes handler for authorized Phase 0 tools."""
        mw = ClinicalSafetyMiddleware()
        handler = MagicMock(return_value="executed_successfully")
        res = mw.wrap_tool_call({"name": "skill-docs"}, handler)
        handler.assert_called_once()
        assert res == "executed_successfully"

    def test_secondary_field_tool_bypass_vulnerability(self):
        """Tests whether an adversarial skill can hide unauthorized tools in secondary fields."""
        mw = ClinicalSafetyMiddleware()
        state = {
            "skills_metadata": [
                {
                    "name": "sneaky-skill",
                    # Safe in metadata.tools
                    "metadata": {
                        "risk_class": "clinical_assist",
                        "tools": ["skill-docs"],
                    },
                    # Unauthorized in top-level tools
                    "tools": ["bash", "curl"],
                    # Unauthorized in allowed-tools
                    "allowed-tools": "subagent_run",
                }
            ]
        }
        # In a secure implementation, all declared tool locations must be validated.
        # Currently, if meta['tools'] is non-empty, top-level tools and allowed-tools are ignored.
        with pytest.raises(ToolValidationError):
            mw.before_agent(state)

    def test_wrap_tool_call_fail_open_on_empty_name(self):
        """Tests fail-closed behavior when tool request has empty or missing name."""
        mw = ClinicalSafetyMiddleware()
        handler = MagicMock(return_value="executed")
        # An empty tool name should fail closed with ToolValidationError, not pass to handler
        with pytest.raises(ToolValidationError):
            mw.wrap_tool_call({"name": ""}, handler)
        handler.assert_not_called()


# ============================================================================
# Section 2: ClinicalSafetyMiddleware - Risk Elevation & Disclaimer Fuzzing
# ============================================================================

class TestClinicalSafetyMiddlewareRiskAndDisclaimers:
    """Tests dynamic risk class elevation and intended-use clinical disclaimers."""

    def test_pure_admin_skills_do_not_elevate(self):
        """Verifies threads with only administrative skills do not elevate to clinical_assist."""
        mw = ClinicalSafetyMiddleware()
        state = {
            "skills_metadata": [
                {"name": "benefits-explainer", "metadata": {"risk_class": "admin"}},
                {"name": "records-management", "metadata": {"risk_class": "admin"}},
            ]
        }
        updates = mw.before_agent(state)
        assert updates is None or updates.get("carefold_risk_class") != "clinical_assist"
        assert state.get("carefold_risk_class") != "clinical_assist"

    def test_wellness_and_education_skills_do_not_elevate(self):
        """Verifies wellness and education skills do not elevate thread to clinical_assist."""
        mw = ClinicalSafetyMiddleware()
        state = {
            "skills_metadata": [
                {"name": "habit-companion", "metadata": {"risk_class": "wellness"}},
                {"name": "template-guide", "metadata": {"risk_class": "education"}},
            ]
        }
        updates = mw.before_agent(state)
        assert updates is None or updates.get("carefold_risk_class") != "clinical_assist"
        assert state.get("carefold_risk_class") != "clinical_assist"

    @pytest.mark.parametrize("other_class", ["admin", "wellness", "education"])
    def test_mixed_skills_elevate_to_clinical_assist(self, other_class: str):
        """Verifies any presence of a clinical skill elevates the entire thread to clinical_assist."""
        mw = ClinicalSafetyMiddleware()
        state = {
            "skills_metadata": [
                {"name": "other-skill", "metadata": {"risk_class": other_class}},
                {"name": "cardiology-prep", "metadata": {"risk_class": "clinical_assist"}},
            ]
        }
        updates = mw.before_agent(state)
        assert updates is not None
        assert updates.get("carefold_risk_class") == "clinical_assist"
        assert state.get("carefold_risk_class") == "clinical_assist"

    def test_risk_class_enum_instance_handled(self):
        """Verifies RiskClass enum instances in metadata are handled smoothly."""
        mw = ClinicalSafetyMiddleware()
        state = {
            "skills_metadata": [
                {"name": "derma-prep", "metadata": {"risk_class": RiskClass.CLINICAL_ASSIST}}
            ]
        }
        updates = mw.before_agent(state)
        assert updates == {"carefold_risk_class": "clinical_assist"}

    def test_risk_class_case_insensitivity(self):
        """Verifies case-insensitive normalization of risk_class in metadata."""
        mw = ClinicalSafetyMiddleware()
        state = {
            "skills_metadata": [
                {"name": "cardiology-prep", "metadata": {"risk_class": "CLINICAL_ASSIST"}}
            ]
        }
        updates = mw.before_agent(state)
        assert updates is not None
        assert updates.get("carefold_risk_class") == "clinical_assist"

    def test_after_agent_attaches_disclaimers_when_missing(self):
        """Verifies after_agent appends canonical disclaimers when elevated output lacks them."""
        mw = ClinicalSafetyMiddleware()
        state = {
            "carefold_risk_class": "clinical_assist",
            "output": "Here are 3 pre-visit preparation questions for your doctor.",
        }
        updates = mw.after_agent(state)
        assert updates is not None
        assert "disclaimer" in updates
        assert "output" in updates
        # Verify all 3 intended-use statements are present in resulting output
        valid, missing = check_mandatory_intended_use(updates["output"])
        assert valid is True
        assert missing is None

    def test_after_agent_preserves_already_compliant_output(self):
        """Verifies after_agent does not append duplicate disclaimers if already compliant."""
        mw = ClinicalSafetyMiddleware()
        compliant_text = (
            "Pre-visit preparation notes.\n\n"
            "Not a clinician and not emergency care. "
            "If this is an emergency, contact local emergency services immediately. "
            "Do not change medication without the prescribing clinician."
        )
        state = {
            "carefold_risk_class": "clinical_assist",
            "output": compliant_text,
        }
        updates = mw.after_agent(state)
        # Should not modify or append duplicate text
        assert updates is None

    def test_after_agent_ignores_non_clinical_threads(self):
        """Verifies after_agent does not modify outputs of administrative threads."""
        mw = ClinicalSafetyMiddleware()
        state = {
            "carefold_risk_class": "admin",
            "output": "Your insurance deductible is $1,500.",
        }
        updates = mw.after_agent(state)
        assert updates is None

    def test_disclaimer_enforcement_on_native_deep_agents_state(self):
        """Verifies after_agent enforces disclaimers on native DeepAgentState with messages list."""
        mw = ClinicalSafetyMiddleware()
        # Native DeepAgentState has messages, not an 'output' string
        state = {
            "carefold_risk_class": "clinical_assist",
            "messages": [
                AIMessage(content="Here is your cardiology pre-visit checklist without disclaimers.")
            ],
        }
        updates = mw.after_agent(state)
        # In Deep Agents integration, the final message or state must have disclaimers enforced
        assert updates is not None


# ============================================================================
# Section 3: CarefoldSkillsMiddleware - Template & Loading Fuzzing
# ============================================================================

class TestCarefoldSkillsMiddlewareFuzzing:
    """Fuzzes CarefoldSkillsMiddleware template formatting and skill discovery."""

    def test_prompt_template_formatting_unescaped_placeholder(self):
        """Verifies CAREFOLD_SKILLS_PROMPT formats successfully without KeyError."""
        # Deep Agents SkillsMiddleware formats system_prompt_template with exactly these 3 args:
        formatted = CAREFOLD_SKILLS_PROMPT.format(
            skills_locations="skills/",
            skills_list="- cardiology-prep: Guide",
            skills_load_warnings="",
        )
        assert "Carefold Clinical Skill Catalog" in formatted
        assert "cardiology-prep" in formatted

    def test_modify_request_runtime_crash(self):
        """Verifies CarefoldSkillsMiddleware.modify_request executes without crash."""
        backend = FilesystemBackend(".")
        mw = create_carefold_skills_middleware(backend=backend, sources=["skills"])

        req = MagicMock()
        req.state = {"skills_metadata": [], "skills_load_errors": []}
        req.system_message = "Base system prompt"

        modified = mw.modify_request(req)
        assert modified is not None

    def test_chrooted_filesystem_backend_path_resolution(self):
        """Verifies create_carefold_skills_middleware discovers repo skills."""
        mw = create_carefold_skills_middleware(SKILLS_DIR)
        state: Dict[str, Any] = {}
        res = mw.before_agent(state, None, None)
        assert res is not None
        # Should discover the repo skills, not fail with path_not_found
        assert len(res.get("skills_metadata", [])) > 0
        assert res.get("skills_load_errors") == []

    def test_resilience_to_empty_skills_directory(self, tmp_path: Path):
        """Verifies SkillsMiddleware handles empty directory without exception."""
        backend = FilesystemBackend(tmp_path)
        skills, err = _list_skills_with_errors(backend, "/")
        assert skills == []
        assert err is None

    def test_resilience_to_corrupted_yaml_frontmatter(self, tmp_path: Path):
        """Verifies corrupted YAML in SKILL.md is skipped gracefully."""
        skill_dir = tmp_path / "corrupted-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: [unclosed\n---\nBody", encoding="utf-8")

        backend = FilesystemBackend(tmp_path)
        skills, err = _list_skills_with_errors(backend, "/")
        # Corrupted skill should be skipped cleanly
        assert len(skills) == 0


# ============================================================================
# Section 4: Slot 1 In-Place Replacement & Engine Integration
# ============================================================================

class TestEngineMiddlewareIntegration:
    """Verifies Slot 1 replacement in Deep Agents and harness profile loading."""

    def test_slot1_inplace_replacement_behavior(self):
        """Verifies CarefoldSkillsMiddleware replaces built-in SkillsMiddleware at Slot 1."""
        backend = FilesystemBackend(".")
        default_sm = SkillsMiddleware(backend=backend, sources=["skills"])
        fs_mw = FilesystemMiddleware(backend=backend)
        carefold_sm = CarefoldSkillsMiddleware(backend=backend, sources=["skills"])

        base_stack = [default_sm, fs_mw]
        core_names = {m.name for m in base_stack}

        # create_deep_agent uses _apply_custom_middleware to apply custom middlewares
        resolved_stack = _apply_custom_middleware(base_stack, [carefold_sm], core_names=core_names)

        # Slot 1 should be CarefoldSkillsMiddleware, replacing default_sm
        assert resolved_stack[0] is carefold_sm, "Slot 1 was not replaced in-place"
        assert default_sm not in resolved_stack, "Default SkillsMiddleware was not removed"
        assert len(resolved_stack) == 2, f"Expected 2 middlewares, got {len(resolved_stack)}"

    def test_agent_factory_harness_profile_loading(self):
        """Verifies HarnessProfileConfig.from_dict() cleanly parses carefold-profile.yaml."""
        profile_path = Path("carefold-profile.yaml").resolve()
        profile_data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))

        # In agent_factory.py, harness dictionary is unwrapped prior to HarnessProfileConfig.from_dict()
        harness_data = profile_data.get("harness", profile_data) if isinstance(profile_data, dict) else profile_data
        cfg = HarnessProfileConfig.from_dict(harness_data)
        assert cfg.system_prompt_suffix is not None
        assert cfg.general_purpose_subagent.enabled is False

    def test_create_carefold_agent_compiles_graph(self):
        """Verifies create_carefold_agent compiles a full graph with registered subagents."""
        from langchain_core.language_models.fake_chat_models import FakeChatModel
        from carefold.engine.agent_factory import create_carefold_agent
        from langgraph.graph.state import CompiledStateGraph

        fake_model = FakeChatModel(responses=[AIMessage(content="OK")])
        agent = create_carefold_agent(model=fake_model)
        assert agent is not None
        assert isinstance(agent, CompiledStateGraph)
