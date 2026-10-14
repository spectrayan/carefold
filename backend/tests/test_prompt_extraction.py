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

"""Tests for modular prompt extraction, individual prompt files, and parameterized rendering."""

import pytest
from carefold.resources.loader import get_resource_loader


def test_individual_prompt_files_exist():
    """Verify all individual prompt files exist and can be loaded directly."""
    loader = get_resource_loader()
    loader.clear_cache()

    # Safety preamble
    safety = loader.get_prompt_text("safety/safety_preamble")
    assert "CORE SYSTEM SAFETY CONTRACT" in safety
    assert "{forbidden_str}" in safety

    # Orchestrator prompt
    orchestrator = loader.get_prompt_text("orchestrator/system_prompt")
    assert "Carefold Multi-Agent Specialist Supervisor" in orchestrator

    # Extraction prompts
    insurance = loader.get_prompt_text("extraction/insurance_benefits")
    assert "InsuranceBenefitsDossier" in insurance

    clinical = loader.get_prompt_text("extraction/clinical_visit")
    assert "ClinicalVisitDossier" in clinical

    generic = loader.get_prompt_text("extraction/generic_document")
    assert "GenericDocumentDossier" in generic

    grounding = loader.get_prompt_text("extraction/grounding_validation")
    assert "numerical values" in grounding

    # Reflection prompt
    reflection = loader.get_prompt_text("reflection/system_prompt")
    assert "Output Safety and Compliance Critic" in reflection


def test_parameterized_prompt_rendering():
    """Verify parameterized prompt rendering with keyword substitution and validation."""
    loader = get_resource_loader()

    rendered = loader.render_prompt(
        "safety/safety_preamble",
        forbidden_str="diagnose, prescribe, dose",
    )
    assert "ENFORCED FORBIDDEN INTENT CODES: diagnose, prescribe, dose" in rendered
    assert "{forbidden_str}" not in rendered

    # Error raised on missing parameter
    with pytest.raises(ValueError) as exc:
        loader.render_prompt("safety/safety_preamble")
    assert "Missing required parameter" in str(exc.value)


def test_composed_prompts_match_expected_structure():
    """Verify get_prompts() composes individual prompt files into expected dictionary."""
    loader = get_resource_loader()
    loader.clear_cache()
    prompts = loader.get_prompts()

    assert "safety_preamble" in prompts
    assert "supervisor" in prompts
    assert "extraction" in prompts
    assert "insurance_benefits" in prompts["extraction"]
    assert "clinical_visit" in prompts["extraction"]
    assert "generic_document" in prompts["extraction"]
    assert "reflection" in prompts
    assert "suggestions" in prompts
