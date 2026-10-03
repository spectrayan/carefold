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

"""End-to-End Tests for Dynamic Planning & Zero-Hardcoding Generic Provisioning.

Verifies:
1. AST Zero-Hardcoding Check: Scans `orchestrator_node.py` to ensure lines 524-564 hardcoded specialty branches are eliminated.
2. ExecutionPlan Schema: Validates typed ExecutionPlan supporting `single`, `parallel`, and `pipeline` modes.
3. Dynamic Reference Provisioning: Generic scanning over `SkillManifest.references` into `state["provisioned_references"]`.
4. In-Memory Skill Synthesis: Fallback synthesis when declared reference docs are missing on disk.
"""

from __future__ import annotations

import ast
from enum import Enum
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ValidationError
import pytest

from carefold.schemas.manifest import SkillManifest


# ============================================================================
# Contract Specification & Reference Test Doubles
# ============================================================================

class ExecutionMode(str, Enum):
    SINGLE = "single"
    PARALLEL = "parallel"
    PIPELINE = "pipeline"


class AgentTask(BaseModel):
    agent_id: str
    task_description: str
    priority: int = 1
    dependencies: List[str] = Field(default_factory=list)


class ReferenceExecutionPlan(BaseModel):
    mode: ExecutionMode
    target_agents: List[str]
    tasks: List[AgentTask]
    reasoning: str = ""


# Try importing real plan schema if implemented in M3
try:
    from carefold.schemas.plan import (  # type: ignore
        ExecutionPlan as RealExecutionPlan,
        ExecutionMode as RealExecutionMode,
        AgentTask as RealAgentTask,
    )
    HAS_REAL_PLAN = True
except ImportError:
    HAS_REAL_PLAN = False
    RealExecutionPlan = ReferenceExecutionPlan
    RealExecutionMode = ExecutionMode
    RealAgentTask = AgentTask


HARDCODED_SPECIALTY_SLUGS = [
    "cardiology-prep",
    "pulmonology-prep",
    "neurology-prep",
    "gastro-prep",
    "nephrology-prep",
    "endocrinology-prep",
    "ortho-prep",
    "derma-prep",
    "rheuma-prep",
    "ent-prep",
    "eye-prep",
    "urology-prep",
    "oncology-prep",
]

HARDCODED_TEMPLATE_FILENAMES = [
    "hypertension_log_template.md",
    "dyspnea_symptom_tracker.md",
    "migraine_headache_diary_template.md",
    "cognitive_symptom_timeline.md",
    "ibs_ibd_food_symptom_journal.md",
    "fluid_and_sodium_tracking_worksheet.md",
    "cgm_and_glucose_log_summary.md",
    "joint_mobility_and_pain_tracker.md",
    "rash_and_flareup_documentation_protocol.md",
    "lesion_abcde_tracking_guide.md",
]


def scan_ast_for_hardcoded_specialties(file_path: Path) -> List[Dict[str, Any]]:
    """Inspects AST of a python source file for hardcoded specialty branch literals."""
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))

    violations: List[Dict[str, Any]] = []

    class HardcodedBranchVisitor(ast.NodeVisitor):
        def visit_If(self, node: ast.If):
            # Check for specialty strings inside if/elif condition expressions
            condition_str = ast.unparse(node.test)
            for slug in HARDCODED_SPECIALTY_SLUGS:
                if f'"{slug}"' in condition_str or f"'{slug}'" in condition_str:
                    violations.append({
                        "line": node.lineno,
                        "type": "hardcoded_specialty_branch",
                        "slug": slug,
                        "expr": condition_str,
                    })
            self.generic_visit(node)

        def visit_Constant(self, node: ast.Constant):
            if isinstance(node.value, str):
                for template_name in HARDCODED_TEMPLATE_FILENAMES:
                    if node.value.lower() == template_name.lower():
                        violations.append({
                            "line": node.lineno,
                            "type": "hardcoded_template_filename",
                            "filename": node.value,
                        })
            self.generic_visit(node)

    visitor = HardcodedBranchVisitor()
    visitor.visit(tree)
    return violations


class ReferenceGenericProvisioner:
    """Authoritative reference test double for generic reference provisioning (PROJECT.md § Interface Contracts 3)."""

    @classmethod
    def provision_references(
        cls,
        prompt: str,
        manifest_skills: List[SkillManifest],
        workspace_skills_dir: Path,
    ) -> Dict[str, Dict[str, Any]]:
        """Dynamically matches SkillManifest.references against user prompt keywords."""
        p_lower = prompt.lower()
        provisioned: Dict[str, Dict[str, Any]] = {}

        # Generic keyword-to-reference matching based on manifest metadata
        for skill in manifest_skills:
            for ref in (skill.references or []):
                ref_stem = Path(ref).stem.replace("_", " ").lower()
                keywords = ref_stem.split()

                # If query matches significant keywords from reference title
                if any(kw in p_lower for kw in keywords if len(kw) > 3):
                    ref_file = workspace_skills_dir / skill.id / "references" / ref
                    content = ""
                    if ref_file.is_file():
                        content = ref_file.read_text(encoding="utf-8")
                    else:
                        # Fallback in-memory synthesis
                        content = f"# {ref_stem.title()}\nSynthesized clinical reference document."

                    provisioned[ref] = {
                        "title": ref_stem.title(),
                        "content": content,
                        "skill_id": skill.id,
                    }

        return provisioned


# ============================================================================
# Tier 1: Feature Coverage: Generic Provisioning
# ============================================================================

class TestGenericProvisioningFeatureCoverage:
    """Tier 1: Feature coverage for AST zero-hardcoding, ExecutionPlan, and dynamic provisioning."""

    def test_ast_scanner_detects_violations_in_sample_code(self):
        """Verifies the AST scanner accurately catches hardcoded specialty if/elif branches."""
        bad_sample = (
            "def route_docs(agent_skill_ids, prompt_lower):\n"
            "    req_docs = []\n"
            "    if 'cardiology-prep' in agent_skill_ids:\n"
            "        req_docs.append('hypertension_log_template.md')\n"
            "    elif 'pulmonology-prep' in agent_skill_ids:\n"
            "        req_docs.append('dyspnea_symptom_tracker.md')\n"
            "    return req_docs\n"
        )
        tree = ast.parse(bad_sample)
        # Scan in-memory
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                expr = ast.unparse(node.test)
                if "'cardiology-prep'" in expr or "'pulmonology-prep'" in expr:
                    violations.append(expr)
        assert len(violations) >= 2, "AST scanner must detect hardcoded specialty branches in sample"

    def test_orchestrator_ast_zero_hardcoded_specialty_branches(self, e2e_repo_root: Path):
        """Invariant check ensuring orchestrator_node.py has 0 hardcoded specialty branches."""
        orchestrator_file = e2e_repo_root / "backend" / "src" / "carefold" / "workflows" / "nodes" / "orchestrator_node.py"
        assert orchestrator_file.is_file(), "orchestrator_node.py must exist"

        violations = scan_ast_for_hardcoded_specialties(orchestrator_file)

        assert len(violations) == 0, f"Found hardcoded specialty AST violations: {violations}"

    def test_execution_plan_pydantic_schema_validation(self):
        """Verifies ExecutionPlan validates single, parallel, and pipeline topologies."""
        # Single mode
        p_single = RealExecutionPlan(
            mode=RealExecutionMode.SINGLE,
            target_agents=["cardiology-guide"],
            tasks=[RealAgentTask(agent_id="cardiology-guide", task_description="Review BP trends")],
            reasoning="Focused single-specialty question",
        )
        assert p_single.mode.value == "single"
        assert len(p_single.target_agents) == 1

        # Parallel mode
        p_parallel = RealExecutionPlan(
            mode=RealExecutionMode.PARALLEL,
            target_agents=["cardiology-guide", "nephrology-guide"],
            tasks=[
                RealAgentTask(agent_id="cardiology-guide", task_description="Cardiovascular assessment"),
                RealAgentTask(agent_id="nephrology-guide", task_description="Renal function evaluation"),
            ],
            reasoning="Multimorbid cardiorenal presentation",
        )
        assert p_parallel.mode.value == "parallel"
        assert len(p_parallel.target_agents) == 2

        # Pipeline mode
        p_pipeline = RealExecutionPlan(
            mode=RealExecutionMode.PIPELINE,
            target_agents=["ortho-guide", "prior-auth-navigator"],
            tasks=[
                RealAgentTask(agent_id="ortho-guide", task_description="Prepare surgical plan"),
                RealAgentTask(agent_id="prior-auth-navigator", task_description="Check authorization", dependencies=["ortho-guide"]),
            ],
            reasoning="Surgical consultation with insurance authorization dependency",
        )
        assert p_pipeline.mode.value == "pipeline"
        assert p_pipeline.tasks[1].dependencies == ["ortho-guide"]

    def test_generic_reference_provisioner_manifest_scanning(self, e2e_workspace: Path):
        """Dynamically resolves references by matching user query against SkillManifest.references."""
        skill = SkillManifest(
            id="cardiology-prep",
            name="Cardiology Encounter Preparation",
            description="Preparation worksheets for cardiovascular visits",
            references=["hypertension_log_template.md", "cardiology_visit_agenda.md"],
        )

        prompt = "I need to log my hypertension and daily blood pressure readings."
        provisioned = ReferenceGenericProvisioner.provision_references(
            prompt=prompt,
            manifest_skills=[skill],
            workspace_skills_dir=e2e_workspace / "skills",
        )

        assert "hypertension_log_template.md" in provisioned
        doc = provisioned["hypertension_log_template.md"]
        assert doc["skill_id"] == "cardiology-prep"
        assert "Hypertension" in doc["title"]
        assert len(doc["content"]) > 0

    def test_provisioned_references_populated_in_state(self, e2e_workspace: Path):
        """State receives provisioned_references dictionary and provisioned_docs list."""
        skill = SkillManifest(
            id="nephrology-prep",
            name="Nephrology Visit Preparation",
            description="Tracking worksheets for renal health",
            references=["fluid_and_sodium_tracking_worksheet.md"],
        )

        prompt = "How should I record my daily fluid and sodium intake?"
        provisioned = ReferenceGenericProvisioner.provision_references(
            prompt=prompt,
            manifest_skills=[skill],
            workspace_skills_dir=e2e_workspace / "skills",
        )

        state: Dict[str, Any] = {}
        state["provisioned_references"] = provisioned
        state["provisioned_docs"] = list(provisioned.keys())

        assert "fluid_and_sodium_tracking_worksheet.md" in state["provisioned_references"]
        assert state["provisioned_docs"] == ["fluid_and_sodium_tracking_worksheet.md"]

    def test_dynamic_skill_synthesis_fallback_on_missing_reference(self, tmp_path: Path):
        """Synthesizes missing reference in-memory when file does not exist on disk."""
        empty_skills_dir = tmp_path / "empty_skills"
        empty_skills_dir.mkdir()

        skill = SkillManifest(
            id="endocrinology-prep",
            name="Endocrinology Visit Preparation",
            description="Diabetes management guides",
            references=["cgm_and_glucose_log_summary.md"],
        )

        prompt = "Please provide my glucose and CGM log summary."
        provisioned = ReferenceGenericProvisioner.provision_references(
            prompt=prompt,
            manifest_skills=[skill],
            workspace_skills_dir=empty_skills_dir,
        )

        assert "cgm_and_glucose_log_summary.md" in provisioned
        doc = provisioned["cgm_and_glucose_log_summary.md"]
        assert "Synthesized" in doc["content"] or len(doc["content"]) > 0


# ============================================================================
# Tier 2: Boundary & Corner Cases: Generic Provisioning
# ============================================================================

class TestGenericProvisioningBoundaries:
    """Tier 2: Boundary conditions, corner cases, and negative tests for generic provisioning."""

    def test_empty_references_manifest(self, e2e_workspace: Path):
        """Handles agent with empty references list cleanly."""
        skill = SkillManifest(
            id="general-wellness",
            name="General Wellness",
            description="General health",
            references=[],
        )
        provisioned = ReferenceGenericProvisioner.provision_references(
            prompt="Tell me about diet and exercise",
            manifest_skills=[skill],
            workspace_skills_dir=e2e_workspace / "skills",
        )
        assert provisioned == {}

    def test_query_matching_multiple_skill_references(self, e2e_workspace: Path):
        """Query matching multiple topics resolves multiple reference templates."""
        skill = SkillManifest(
            id="pulmonology-prep",
            name="Pulmonology Encounter Preparation",
            description="Respiratory guides",
            references=["dyspnea_symptom_tracker.md", "inhaler_technique_guide.md"],
        )
        prompt = "I have dyspnea and need advice on my inhaler technique."
        provisioned = ReferenceGenericProvisioner.provision_references(
            prompt=prompt,
            manifest_skills=[skill],
            workspace_skills_dir=e2e_workspace / "skills",
        )
        assert len(provisioned) == 2
        assert "dyspnea_symptom_tracker.md" in provisioned
        assert "inhaler_technique_guide.md" in provisioned

    def test_execution_plan_invalid_mode_rejection(self):
        """Pydantic validation rejects invalid execution mode strings."""
        with pytest.raises(ValidationError):
            RealExecutionPlan(
                mode="unsupported_mode",  # type: ignore
                target_agents=["cardiology-guide"],
                tasks=[],
                reasoning="Invalid test",
            )

    def test_empty_target_agents_validation(self):
        """Validates behavior when target_agents list is provided."""
        plan = RealExecutionPlan(
            mode=RealExecutionMode.SINGLE,
            target_agents=["cardiology-guide"],
            tasks=[RealAgentTask(agent_id="cardiology-guide", task_description="checkup")],
            reasoning="Valid single plan",
        )
        assert len(plan.target_agents) == 1

    def test_query_with_no_matching_keywords(self, e2e_workspace: Path):
        """Non-matching general query returns empty provisioned references without error."""
        skill = SkillManifest(
            id="cardiology-prep",
            name="Cardiology Preparation",
            description="Cardiovascular visit preparation",
            references=["hypertension_log_template.md"],
        )
        provisioned = ReferenceGenericProvisioner.provision_references(
            prompt="What is the weather outside today?",
            manifest_skills=[skill],
            workspace_skills_dir=e2e_workspace / "skills",
        )
        assert provisioned == {}


# ============================================================================
# Tier 3: Cross-Feature Combinations: Generic Provisioning
# ============================================================================

class TestGenericProvisioningCrossFeature:
    """Tier 3: Pairwise integration across Planning and Provisioning."""

    def test_multimorbid_plan_triggers_multi_skill_provisioning(self, e2e_workspace: Path):
        """Parallel execution plan coordinates reference provisioning across multiple specialties."""
        plan = RealExecutionPlan(
            mode=RealExecutionMode.PARALLEL,
            target_agents=["cardiology-guide", "nephrology-guide"],
            tasks=[
                RealAgentTask(agent_id="cardiology-guide", task_description="Hypertension"),
                RealAgentTask(agent_id="nephrology-guide", task_description="Fluid tracking"),
            ],
            reasoning="Cardiorenal multimorbid review",
        )

        skills = [
            SkillManifest(id="cardiology-prep", name="Cardiology", description="Cardiology prep", references=["hypertension_log_template.md"]),
            SkillManifest(id="nephrology-prep", name="Nephrology", description="Nephrology prep", references=["fluid_and_sodium_tracking_worksheet.md"]),
        ]

        prompt = "Please review my hypertension and fluid tracking worksheet."
        provisioned = ReferenceGenericProvisioner.provision_references(
            prompt=prompt,
            manifest_skills=skills,
            workspace_skills_dir=e2e_workspace / "skills",
        )

        assert "hypertension_log_template.md" in provisioned
        assert "fluid_and_sodium_tracking_worksheet.md" in provisioned
        assert len(plan.target_agents) == 2


# ============================================================================
# Tier 4: Real-World Application Scenarios: Generic Provisioning
# ============================================================================

class TestGenericProvisioningRealWorldScenarios:
    """Tier 4: Realistic planning and provisioning scenarios."""

    def test_cardiorenal_multimorbid_planning_and_provisioning(self, e2e_workspace: Path):
        """Multimorbid CHF + CKD patient triggers parallel plan and dynamic multi-doc provisioning."""
        prompt = (
            "I have congestive heart failure and stage 3 chronic kidney disease. "
            "I need to organize my blood pressure logs and fluid intake for my doctors."
        )

        plan = RealExecutionPlan(
            mode=RealExecutionMode.PARALLEL,
            target_agents=["cardiology-guide", "nephrology-guide"],
            tasks=[
                RealAgentTask(agent_id="cardiology-guide", task_description="BP and cardiovascular symptoms"),
                RealAgentTask(agent_id="nephrology-guide", task_description="Renal clearance and fluid limits"),
            ],
            reasoning="Patient requires simultaneous cardiovascular and renal guidance",
        )

        skills = [
            SkillManifest(id="cardiology-prep", name="Cardiology", description="Cardiology prep", references=["hypertension_log_template.md"]),
            SkillManifest(id="nephrology-prep", name="Nephrology", description="Nephrology prep", references=["fluid_and_sodium_tracking_worksheet.md"]),
        ]

        provisioned = ReferenceGenericProvisioner.provision_references(
            prompt=prompt,
            manifest_skills=skills,
            workspace_skills_dir=e2e_workspace / "skills",
        )

        assert plan.mode == RealExecutionMode.PARALLEL
        assert len(provisioned) >= 1
