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

"""Heart and blood pressure medicine questions reach the heart care coordinator.

The main agent picks specialists from their descriptions (the Deep Agents
``task`` tool lists each agent's description) and from the pack's main-agent
instructions. In the E9 live eval a blood pressure medicine question went to
the prescription cost and appointment prep coordinators instead, and the
follow-up turn was answered without asking anyone. These tests pin the
descriptions and instructions that steer that choice; there is no keyword
routing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

HEART = "heart-care-coordinator"
COST = "prescription-cost-coordinator"
PREP = "appointment-prep-coordinator"


@pytest.fixture(scope="module")
def registry():
    from yarvelle_core.agents.registry import AgentRegistry

    return AgentRegistry(agents_dir=REPO_ROOT / "agents", skills_dir=REPO_ROOT / "skills")


def _description(registry, agent_id: str) -> str:
    return registry.get_subagent(agent_id)["description"].lower()


def test_heart_care_says_it_covers_blood_pressure_and_heart_medicines(registry) -> None:
    desc = _description(registry, HEART)
    assert "blood pressure" in desc
    assert "medicine" in desc
    assert "cardiologist" in desc


def test_prescription_cost_leaves_clinical_medicine_questions_to_the_condition_coordinator(registry) -> None:
    desc = _description(registry, COST)
    assert "cost" in desc
    assert "care coordinator" in desc


def test_appointment_prep_is_the_general_fallback(registry) -> None:
    assert "no condition-specific coordinator" in _description(registry, PREP)


@pytest.mark.parametrize(
    "question",
    [
        "My mom's blood pressure medicine got more expensive. What should we ask her cardiologist?",
        "Is her heart medicine still the right one? What should I ask the cardiologist?",
        "questions about dad's blood pressure medicine side effects",
    ],
)
def test_heart_care_ranks_first_for_heart_medicine_questions(registry, question: str) -> None:
    ranked = [a.id for a in registry.search(question)]
    assert ranked and ranked[0] == HEART, ranked[:4]


def _main_agent_prompt() -> str:
    import carefold
    from yarvelle_core.engine.orchestration.runtime import compose_main_prompt

    orch = carefold.get_pack().orchestration
    assert orch is not None
    return compose_main_prompt(None, orch.synthesis)


def test_main_agent_is_told_to_send_condition_medicine_questions_to_that_condition_coordinator() -> None:
    prompt = _main_agent_prompt().lower()
    assert "condition's care coordinator" in prompt
    assert "blood pressure or heart medicine" in prompt
    assert "prescription cost coordinator" in prompt


def test_main_agent_is_told_to_delegate_again_on_follow_ups() -> None:
    prompt = _main_agent_prompt().lower()
    assert "on a follow-up" in prompt
    assert "ask that specialist again" in prompt
