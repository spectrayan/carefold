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

"""Unit and contract tests for extracted Handlebars templates, Gmail YAML heuristics, and shared test factories (#343)."""

from __future__ import annotations

from fastapi import Depends, FastAPI
import pytest

from carefold.connectors.gmail_mcp import (
    ALLOWED_GMAIL_LABELS,
    DEFAULT_APPOINTMENT_HOUR,
    DEFAULT_APPOINTMENT_MINUTE,
    DEFAULT_PROVIDER_FALLBACK,
    DEFAULT_SPECIALTY_FALLBACK,
    PROVIDER_LINE_PREFIXES,
    SCHOOL_EXCLUSION_PHRASES,
    load_gmail_heuristics,
    parse_gmail_messages_to_staged_items,
)
from carefold.templates.engine import render_template
from carefold.workflows.nodes.skill_generator_node import SkillGeneratorNode
from yarvelle_core.api.deps import get_current_user


def test_skill_reference_doc_handlebars_template_renders_safety_banner():
    """Verifies skill_reference_doc.hbs renders both with and without user_query and preserves safety disclosures."""
    rendered_with_query = render_template(
        "skill_reference_doc.hbs",
        {
            "clean_stem": "Pediatric Asthma Action Plan",
            "skill_title": "Pediatric Asthma",
            "doc_name": "pediatric_asthma_action_plan.md",
            "user_query": "What questions should we ask about controller inhalers?",
            "body": "## Preparation Checklist\n- Bring current spacer and peak flow log.",
        },
    )
    assert "# Pediatric Asthma Action Plan" in rendered_with_query
    assert "## Clinical Context & User Inquiry" in rendered_with_query
    assert "What questions should we ask about controller inhalers?" in rendered_with_query
    assert "## ⚠️ Carefold Boundary & Safety Disclosures" in rendered_with_query
    assert "immediately call 911" in rendered_with_query

    rendered_without_query = render_template(
        "skill_reference_doc.hbs",
        {
            "clean_stem": "Dental Benefits Guide",
            "skill_title": "Dental Care",
            "doc_name": "dental_benefits_guide.md",
            "user_query": "",
            "body": "## Annual Maximums\n- Track calendar-year maximums.",
        },
    )
    assert "## Clinical Context & User Inquiry" not in rendered_without_query
    assert "## ⚠️ Carefold Boundary & Safety Disclosures" in rendered_without_query

    node = SkillGeneratorNode(model=None)
    synthesized = node.synthesize_reference_doc_content(
        skill_id="cardiology-prep",
        doc_name="visit_checklist.md",
        user_query="Blood pressure log questions",
    )
    assert "## ⚠️ Carefold Boundary & Safety Disclosures" in synthesized
    assert "Blood pressure log questions" in synthesized


def test_skill_reference_synthesis_prompt_template_renders():
    """Verifies skill_reference_synthesis_prompt.hbs interpolates skill_id, clean_doc, target_agent, and user_query."""
    rendered = render_template(
        "skill_reference_synthesis_prompt.hbs",
        {
            "clean_doc": "lipid_panel_questions.md",
            "skill_id": "heart-care",
            "target_agent": "heart-care-coordinator",
            "user_query": "Understanding LDL targets before cardiology follow-up",
        },
    )
    assert "lipid_panel_questions.md" in rendered
    assert "heart-care" in rendered
    assert "heart-care-coordinator" in rendered
    assert "Understanding LDL targets before cardiology follow-up" in rendered
    assert "strict non-clinical disclaimers" in rendered


def test_gmail_heuristics_loaded_from_declarative_yaml():
    """Verifies gmail_mcp classification hints and defaults are backed by resources/gmail_heuristics.yaml."""
    raw = load_gmail_heuristics()
    assert tuple(raw["allowed_labels"]) == ALLOWED_GMAIL_LABELS
    assert DEFAULT_APPOINTMENT_HOUR == 9
    assert DEFAULT_APPOINTMENT_MINUTE == 0
    assert DEFAULT_PROVIDER_FALLBACK == "Healthcare Provider"
    assert DEFAULT_SPECIALTY_FALLBACK == "General"
    assert "provider:" in PROVIDER_LINE_PREFIXES
    assert "appointment confirmation" in SCHOOL_EXCLUSION_PHRASES

    parsed = parse_gmail_messages_to_staged_items(
        [
            {
                "id": "msg-heur-1",
                "labels": ["appointments"],
                "subject": "Appointment scheduled on 2026-12-01",
                "body": "Provider: Metro Dermatology Associates\nPlease arrive 15 minutes early.",
            }
        ],
        label_filter="appointments",
    )
    assert len(parsed["records"]) == 1
    rec = parsed["records"][0]
    assert rec["provider_name"] == "Metro Dermatology Associates"
    assert rec["specialty"] == "Dermatology"
    assert "T09:00:00" in rec["start_time"]


@pytest.mark.asyncio
async def test_shared_conftest_factories_end_to_end(
    user_factory,
    profile_factory,
    health_resource_factory,
    appointment_factory,
    auth_async_client,
):
    """Verifies shared conftest factories create isolated ORM entities and authenticated AsyncClient sessions."""
    user = await user_factory(email="factory-test@carefold.test")
    profile = await profile_factory(user_id=user.id, name="Factory Patient")
    hr = await health_resource_factory(profile_id=profile.id)
    appt = await appointment_factory(profile_id=profile.id, provider_name="Dr. Rivera")

    assert profile.user_id == user.id
    assert hr.profile_id == profile.id
    assert appt.profile_id == profile.id

    mini_app = FastAPI()

    @mini_app.get("/whoami")
    async def _whoami(current_user=Depends(get_current_user)):
        return {"id": current_user.id, "email": current_user.email}

    async with auth_async_client(user=user, fastapi_app=mini_app) as (ac, user_profile):
        resp = await ac.get("/whoami")
        assert resp.status_code == 200
        assert resp.json() == {"id": user.id, "email": user_profile.email}


def test_carefold_skills_prompt_renders_skills_middleware_hbs(monkeypatch):
    """Verifies CAREFOLD_SKILLS_PROMPT renders skills_middleware.hbs cleanly across primary and fallback paths."""
    import inspect
    import carefold.middleware.skills as skills_mod
    from carefold.middleware.skills import CAREFOLD_SKILLS_PROMPT, render_carefold_skills_prompt

    assert "## Carefold Clinical Skill Catalog" in CAREFOLD_SKILLS_PROMPT
    assert "CLINICAL SAFETY BOUNDARY" in CAREFOLD_SKILLS_PROMPT
    assert "{skills_locations}" in CAREFOLD_SKILLS_PROMPT
    assert "{skills_list}" in CAREFOLD_SKILLS_PROMPT
    assert '{{path}}' in CAREFOLD_SKILLS_PROMPT
    assert "skills_system_prompt.md.hbs" not in inspect.getsource(skills_mod)

    custom = render_carefold_skills_prompt("Custom non-diagnostic clinical scope notice.")
    assert "Custom non-diagnostic clinical scope notice." in custom
    assert "You do NOT provide formal medical diagnoses" not in custom

    # Verify fallback path (when compose_skills_system_prompt is unavailable) renders the exact same template
    monkeypatch.setattr(skills_mod, "compose_skills_system_prompt", None)
    fallback_default = render_carefold_skills_prompt()
    assert fallback_default == CAREFOLD_SKILLS_PROMPT


def test_dossier_heuristics_externalized_from_package_init():
    """Verifies clinical_visit and insurance_benefits heuristics live in dossier_heuristics.yaml + module, not __init__.py."""
    import ast
    from pathlib import Path

    import carefold
    from carefold.clinical.dossier_heuristics import (
        extract_clinical_visit_heuristic,
        extract_insurance_benefits_heuristic,
        load_dossier_heuristics,
    )
    from carefold.dossiers import ClinicalVisitDossier, InsuranceBenefitsDossier

    init_src = Path(carefold.__file__).read_text(encoding="utf-8")
    tree = ast.parse(init_src)
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "re" not in imported_modules
    assert "_extract_clinical_visit_heuristic" not in init_src
    assert "_extract_insurance_benefits_heuristic" not in init_src

    raw = load_dossier_heuristics()
    assert "clinical_visit" in raw
    assert "insurance_benefits" in raw

    visit = extract_clinical_visit_heuristic(
        "Reason for visit: Persistent morning headaches.\n"
        "Physician instructions: Track hydration, bring blood pressure cuff, avoid NSAID overuse\n"
        "Follow-up: return in 4 weeks\n"
        "Questions to ask: Should we check ferritin, is an ophthalmology referral needed\n",
        ClinicalVisitDossier,
    )
    assert visit.reason_for_visit == "Persistent morning headaches"
    assert visit.follow_up_timeline == "4 weeks"
    assert visit.physician_instructions == [
        "Track hydration",
        "bring blood pressure cuff",
        "avoid NSAID overuse",
    ]
    assert visit.questions_to_ask == [
        "Should we check ferritin",
        "is an ophthalmology referral needed",
    ]

    benefits = extract_insurance_benefits_heuristic(
        "Annual deductible: 1500. Primary care copay: $25. Specialist visit copay is 50.\n"
        "Coinsurance: 20%. Out-of-pocket maximum: $6,500.\n"
        "All in-network preventive visits are covered at 100%.\n"
        "Prior auth required for MRI, PET, and physical therapy.",
        InsuranceBenefitsDossier,
    )
    assert benefits.deductible == "$1500"
    assert benefits.copays == {"primary_care": "$25", "specialist": "$50"}
    assert benefits.coinsurance == "20%"
    assert benefits.out_of_pocket_maximum == "$6,500"
    assert "in-network" in benefits.in_out_network_rules.lower()
    assert benefits.prior_authorization_flags == ["MRI", "PET", "physical therapy"]

