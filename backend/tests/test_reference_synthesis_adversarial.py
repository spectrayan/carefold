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

"""Empirical adversarial tests for in-memory reference doc synthesis.

Verifies:
1. In-memory reference doc synthesis under read-only disk and missing file conditions.
2. Graceful degradation when disk writes raise PermissionError/OSError.
3. Actual filesystem chmod 555 read-only directory handling.
4. Refusal filtering when LLM returns conversational disclaimers.
5. Orchestrator state population for provisioned_references when disk is read-only.
6. Malformed/adversarial document names and edge cases.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from carefold.schemas.plan import AgentTask, ExecutionMode, ExecutionPlan
from carefold.workflows.nodes.orchestrator_node import OrchestratorNode
from carefold.workflows.nodes.skill_generator_node import SkillGeneratorNode


@pytest.mark.asyncio
async def test_synthesize_reference_doc_when_disk_raises_permission_error():
    """Verify that synthesize_reference_doc succeeds and returns valid in-memory content

    even when writing to disk raises PermissionError (read-only filesystem).
    """
    node = SkillGeneratorNode(model=None)

    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir) / "skills"
        state = {"skills_dir": str(skills_dir)}

        # Patch Path.write_text to simulate read-only filesystem PermissionError
        with patch.object(Path, "write_text", side_effect=PermissionError("Read-only filesystem")):
            result = await node.synthesize_reference_doc(
                skill_id="cardiology-prep",
                doc_name="hypertension_log_template.md",
                user_query="My BP is 150/95 and I have headaches",
                target_agent="cardiology-guide",
                state=state,
            )

            assert isinstance(result, dict)
            assert result["title"] == "Hypertension Log Template"
            assert result["skill_id"] == "cardiology-prep"
            assert result["path"] is None  # Write failed, so path is None
            assert len(result["content"]) > 200
            assert "Hypertension Log Template" in result["content"]
            assert "Tracking Log Matrix" in result["content"]
            assert "Carefold Boundary & Safety Disclosures" in result["content"]
            assert node._is_valid_reference_doc_content(result["content"]) is True


@pytest.mark.asyncio
async def test_synthesize_reference_doc_actual_chmod_readonly_directory():
    """Verify in-memory fallback on an actual read-only directory (chmod 555)."""
    node = SkillGeneratorNode(model=None)

    with tempfile.TemporaryDirectory() as tmpdir:
        ro_skills_dir = Path(tmpdir) / "readonly_skills"
        ro_skills_dir.mkdir(parents=True, exist_ok=True)
        # Make read-only (r-x r-x r-x): cannot create child directories or files
        os.chmod(ro_skills_dir, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP)

        try:
            state = {"skills_dir": str(ro_skills_dir)}
            result = await node.synthesize_reference_doc(
                skill_id="pulmonology-prep",
                doc_name="dyspnea_symptom_tracker.md",
                user_query="I have shortness of breath on exertion",
                target_agent="pulmonology-guide",
                state=state,
            )

            assert isinstance(result, dict)
            assert result["title"] == "Dyspnea Symptom Tracker"
            assert result["skill_id"] == "pulmonology-prep"
            # Since the directory is read-only, disk persistence fails gracefully
            assert result["path"] is None
            assert "Dyspnea Symptom Tracker" in result["content"]
            assert len(result["content"]) > 200
            assert node._is_valid_reference_doc_content(result["content"]) is True
        finally:
            # Restore permissions for cleanup
            os.chmod(ro_skills_dir, stat.S_IRWXU)


@pytest.mark.asyncio
async def test_synthesize_reference_doc_when_missing_on_disk():
    """Verify that when a reference file is missing on disk, it is dynamically synthesized

    and persisted if disk is writable, returning valid path and content.
    """
    node = SkillGeneratorNode(model=None)

    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir) / "skills"
        state = {"skills_dir": str(skills_dir)}

        target_file = skills_dir / "visit-prep" / "references" / "pre_visit_checklist.md"
        assert not target_file.exists()

        result = await node.synthesize_reference_doc(
            skill_id="visit-prep",
            doc_name="pre_visit_checklist.md",
            user_query="Annual wellness check questions",
            target_agent="visit-steward",
            state=state,
        )

        assert isinstance(result, dict)
        assert result["title"] == "Pre Visit Checklist"
        assert target_file.exists()
        assert result["path"] == target_file.resolve()
        disk_content = target_file.read_text(encoding="utf-8")
        assert disk_content == result["content"]
        assert "Pre Visit Checklist" in disk_content
        assert node._is_valid_reference_doc_content(disk_content) is True


@pytest.mark.asyncio
async def test_synthesize_reference_doc_rejects_conversational_refusal_from_model():
    """Verify that if model output is an LLM conversational refusal,

    it is rejected by _is_valid_reference_doc_content and falls back to rule-based synthesis.
    """
    mock_model = AsyncMock()
    # Mock model returning an LLM medical disclaimer refusal
    mock_resp = MagicMock()
    mock_resp.content = (
        "# Notice\n\n"
        "As an AI, I cannot provide medical advice. Please consult a qualified healthcare professional "
        "or licensed physician if you are experiencing symptoms. I am not a doctor and I cannot diagnose."
    )
    mock_model.ainvoke.return_value = mock_resp

    node = SkillGeneratorNode(model=mock_model)

    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir) / "skills"
        state = {"skills_dir": str(skills_dir)}

        result = await node.synthesize_reference_doc(
            skill_id="cardiology-prep",
            doc_name="hypertension_log_template.md",
            user_query="BP is high",
            target_agent="cardiology-guide",
            state=state,
        )

        assert isinstance(result, dict)
        # Should NOT contain the AI refusal
        assert "As an AI" not in result["content"]
        assert "I cannot provide medical advice" not in result["content"]
        # Should contain valid rule-based structured tracking table
        assert "Tracking Log Matrix" in result["content"]
        assert node._is_valid_reference_doc_content(result["content"]) is True


@pytest.mark.asyncio
async def test_orchestrator_dynamic_provisioning_under_readonly_disk():
    """Verify that OrchestratorNode provisions references into state['provisioned_references']

    even when the reference file does not exist on disk AND the filesystem is read-only.
    """
    orchestrator = OrchestratorNode()

    # Test with a non-existent doc name to force synthesis fallback
    non_existent_doc = "custom_cardiac_rehab_tracker.md"

    # Force skill_generator to experience write failure
    with patch.object(Path, "write_text", side_effect=PermissionError("Read-only filesystem")):
        state = {
            "required_docs": [non_existent_doc],
            "provisioned_references": {},
        }
        gen_skills, gen_skill, prov_docs = await orchestrator._preflight_prepare_skills_and_docs(
            target_agent="cardiology-guide",
            missing_skill=None,
            missing_skill_description="",
            required_docs=[non_existent_doc],
            prompt_text="Help me track my hypertension and blood pressure readings",
            state=state,
        )

        assert non_existent_doc in prov_docs
        assert non_existent_doc in state["provisioned_references"]
        entry = state["provisioned_references"][non_existent_doc]
        assert entry["title"] == "Custom Cardiac Rehab Tracker"
        assert len(entry["content"]) > 200
        assert "Tracking Log Matrix" in entry["content"]
        assert "Carefold Boundary & Safety Disclosures" in entry["content"]


@pytest.mark.asyncio
async def test_adversarial_doc_names_and_path_safety():
    """Verify that unusual or adversarial doc names are handled safely without crashing."""
    node = SkillGeneratorNode(model=None)

    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir) / "skills"
        state = {"skills_dir": str(skills_dir)}

        # 1. Missing extension
        res1 = await node.synthesize_reference_doc(
            skill_id="cardiology-prep",
            doc_name="blood_pressure_log",
            user_query="BP readings",
            state=state,
        )
        assert res1["title"] == "Blood Pressure Log"
        assert len(res1["content"]) > 100

        # 2. Path traversal in doc_name
        res2 = await node.synthesize_reference_doc(
            skill_id="cardiology-prep",
            doc_name="../../evil_doc.md",
            user_query="test",
            state=state,
        )
        # Should sanitize stem title and synthesize safely
        assert "Evil Doc" in res2["title"]
        assert len(res2["content"]) > 100


@pytest.mark.asyncio
async def test_synthesize_reference_doc_when_resolve_skills_dir_raises():
    """Verify that synthesize_reference_doc gracefully handles _resolve_skills_dir raising PermissionError."""
    node = SkillGeneratorNode(model=None)

    with patch.object(node, "_resolve_skills_dir", side_effect=PermissionError("Cannot create/resolve dir")):
        result = await node.synthesize_reference_doc(
            skill_id="endocrinology-prep",
            doc_name="glucose_log_template.md",
            user_query="CGM monitoring data",
            target_agent="endocrinology-guide",
            state=None,  # test state=None as well
        )

        assert isinstance(result, dict)
        assert result["title"] == "Glucose Log Template"
        assert result["path"] is None
        assert len(result["content"]) > 200
        assert node._is_valid_reference_doc_content(result["content"]) is True


@pytest.mark.asyncio
async def test_synthesize_reference_doc_with_extreme_query_and_none_state(tmp_path: Path):
    """Verify synthesis works with extreme user query and state=None."""
    node = SkillGeneratorNode(model=None, skills_dir=tmp_path / "skills")
    huge_query = "symptom " * 5000  # 40,000 characters

    result = await node.synthesize_reference_doc(
        skill_id="gastro-prep",
        doc_name="ibd_food_tracker.md",
        user_query=huge_query,
        target_agent="gastro-guide",
        state=None,
    )

    assert isinstance(result, dict)
    assert result["title"] == "Ibd Food Tracker"
    assert len(result["content"]) > 200
    assert "Tracking Log Matrix" in result["content"]


def test_execution_plan_validation_and_field_sync():
    """Verify ExecutionPlan and AgentTask schema validation, serialization, and alias synchronization."""
    # Test AgentTask field sync: task_description -> instructions
    task1 = AgentTask(agent_id="cardiology-guide", task_description="Review ECG")
    assert task1.instructions == "Review ECG"
    assert task1.task_description == "Review ECG"

    # Test AgentTask field sync: instructions -> task_description
    task2 = AgentTask(agent_id="nephrology-guide", instructions="Check eGFR")
    assert task2.instructions == "Check eGFR"
    assert task2.task_description == "Check eGFR"

    # Test dependencies <-> depends_on sync
    task3 = AgentTask(agent_id="prior-auth-navigator", dependencies=["cardiology-guide"])
    assert task3.depends_on == ["cardiology-guide"]

    # Test ExecutionPlan schema
    plan = ExecutionPlan(
        mode=ExecutionMode.PARALLEL,
        target_agents=["cardiology-guide", "nephrology-guide"],
        tasks=[task1, task2],
        reasoning="Cardiorenal multimorbid evaluation",
    )
    d = plan.to_dict()
    assert d["mode"] == "parallel"
    assert len(d["tasks"]) == 2
    assert d["target_agents"] == ["cardiology-guide", "nephrology-guide"]
    rebuilt = ExecutionPlan.model_validate(d)
    assert rebuilt.mode == ExecutionMode.PARALLEL


@pytest.mark.asyncio
async def test_reproduce_defect_prior_auth_hijacked_by_visit_steward():
    """EMPIRICAL CHALLENGE REPRODUCTION:

    Demonstrates that OrchestratorNode._route over-eagerly hijacks prior-auth queries
    containing generic words like 'medication' and routes them to 'visit-steward' as
    effective_agent / current_agent, overriding the classifier's selection of 'prior-auth-navigator'.
    """
    from langchain_core.messages import HumanMessage
    from carefold.memory.adapters.sqlite.catalog_adapter import SqliteCatalogAdapter
    from carefold.agents.registry import AgentRegistry
    from carefold.config import settings

    # Setup orchestrator with minimal mock returning prior-auth-navigator
    node = OrchestratorNode()

    # User asking an administrative prior authorization question for medication
    query = "Insurance denied my medication requiring prior authorization and step therapy fail first"
    state = {
        "messages": [HumanMessage(content=query)],
        "routed_subgraph": "prior-auth-navigator",
        "current_agent": "prior-auth-navigator",
    }

    # When explicit routed_subgraph is given, execute respects it:
    res1 = await node.execute(state)
    assert res1["current_agent"] == "prior-auth-navigator"

    # But when determined via LLM / 2-tier classifier decision (target_agent="prior-auth-navigator"):
    # In _route:
    plan = node._route(
        target_agent="prior-auth-navigator",
        prompt_text=query,
        state={},
    )
    # DEFECT: Because 'medication' is in specialty_keywords, _route treats this as cross-functional
    # and defaults primary_agent to 'visit-steward' instead of keeping prior-auth-navigator!
    print("Computed plan mode:", plan.mode)
    print("Computed target agents:", plan.target_agents)
    assert plan.mode == ExecutionMode.SINGLE
    assert plan.target_agents == ["prior-auth-navigator"]
    assert plan.target_agents[0] == "prior-auth-navigator"

