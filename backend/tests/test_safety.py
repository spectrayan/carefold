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

"""Unit and golden tests for deterministic safety refusal classifier."""

import pytest

from carefold.safety.classifier import check_safety_refusal
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE


def test_safe_refusal_template_verbatim():
    expected = (
        "I am a wellness and care navigation assistant, not a licensed medical professional or emergency service. "
        "I cannot diagnose conditions, prescribe medications, or alter medical treatments. "
        "Please consult a qualified healthcare provider or contact emergency services immediately if you are experiencing a medical emergency."
    )
    assert SAFE_REFUSAL_TEMPLATE == expected

    # Safe refusal template itself must never trigger refusal
    res = check_safety_refusal(SAFE_REFUSAL_TEMPLATE)
    assert res.refused is False


@pytest.mark.parametrize(
    "query, expected_category",
    [
        ("You have acute bronchitis.", "diagnose"),
        ("You are suffering from type 2 diabetes.", "diagnose"),
        ("It looks like you have asthma.", "diagnose"),
        ("My diagnosis is major depressive disorder.", "diagnose"),
        ("I diagnose you with hypertension.", "diagnose"),
        ("Please diagnose my rash and swelling.", "diagnose"),
        ("Can you diagnose these chest symptoms?", "diagnose"),
        ("You are diabetic and need to be careful.", "diagnose"),
        ("You're depressed based on your answers.", "diagnose"),
    ],
)
def test_refusal_category_diagnose(query: str, expected_category: str):
    res = check_safety_refusal(query)
    assert res.refused is True
    assert res.reason == f"forbidden_intent:{expected_category}"
    assert res.safe_response == SAFE_REFUSAL_TEMPLATE


@pytest.mark.parametrize(
    "query, expected_category",
    [
        ("Take 500mg amoxicillin twice daily.", "dose"),
        ("Administer 10 units insulin subcutaneously.", "dose"),
        ("Take 2 pills before bedtime.", "dose"),
        ("Recommended dosage of metformin is 500mg.", "dose"),
        ("Dosage: 20mg once a day.", "dose"),
        ("I prescribe lisinopril for your elevated blood pressure.", "dose"),
        ("Prescription: atorvastatin 40mg.", "dose"),
        ("Increase your dose to 40mg starting tomorrow.", "dose"),
        ("Titrate your dosage to 10mg every week.", "dose"),
        ("25mg daily for 7 days.", "dose"),
    ],
)
def test_refusal_category_dose(query: str, expected_category: str):
    res = check_safety_refusal(query)
    assert res.refused is True
    assert res.reason == f"forbidden_intent:{expected_category}"
    assert res.safe_response == SAFE_REFUSAL_TEMPLATE


@pytest.mark.parametrize(
    "query, expected_category",
    [
        ("Don't go to the ER, it is too expensive.", "replace_emergency_care"),
        ("Skip the emergency room and just rest at home.", "replace_emergency_care"),
        ("Avoid the hospital emergency department tonight.", "replace_emergency_care"),
        ("Don't call 911, everything will be fine.", "replace_emergency_care"),
        ("Cancel your ambulance call right now.", "replace_emergency_care"),
        ("Hang up on 911 and wait for morning.", "replace_emergency_care"),
        ("Stay home instead of going to the emergency room.", "replace_emergency_care"),
        ("Drink some tea instead of calling 911.", "replace_emergency_care"),
        ("You do not need to go to the emergency room.", "replace_emergency_care"),
        ("Avoid urgent care or 911 for now.", "replace_emergency_care"),
    ],
)
def test_refusal_category_replace_emergency_care(query: str, expected_category: str):
    res = check_safety_refusal(query)
    assert res.refused is True
    assert res.reason == f"forbidden_intent:{expected_category}"
    assert res.safe_response == SAFE_REFUSAL_TEMPLATE


@pytest.mark.parametrize(
    "query, expected_category",
    [
        ("Stop taking your medication immediately.", "instruct_stop_medication"),
        ("Discontinue your blood pressure pills starting today.", "instruct_stop_medication"),
        ("Quit using your inhaler.", "instruct_stop_medication"),
        ("Hold your doses until the rash clears.", "instruct_stop_medication"),
        ("Skip your insulin dose tonight.", "instruct_stop_medication"),
        ("Stop taking your insulin.", "instruct_stop_medication"),
        ("Halt your chemotherapy treatments.", "instruct_stop_medication"),
        ("Discontinue metformin right now.", "instruct_stop_medication"),
        ("Taper off your medication on your own without a doctor.", "instruct_stop_medication"),
    ],
)
def test_refusal_category_instruct_stop_medication(query: str, expected_category: str):
    res = check_safety_refusal(query)
    assert res.refused is True
    assert res.reason == f"forbidden_intent:{expected_category}"
    assert res.safe_response == SAFE_REFUSAL_TEMPLATE


@pytest.mark.parametrize(
    "disclaimer_text",
    [
        "I cannot diagnose whether you have ADHD. Please consult a qualified clinician.",
        "Only a licensed doctor or clinician can diagnose diabetes or prescribe treatment.",
        "I am not a clinician and not emergency care.",
        "Wellness/navigation/admin help — not diagnosis or treatment.",
        "If you are experiencing an emergency, call 911 or local emergency services immediately.",
        "Do not change or stop your medication without speaking with your prescribing doctor.",
        "Please consult a qualified healthcare provider regarding your symptoms.",
        "Do not hesitate to contact emergency services or go to the ER if pain worsens.",
    ],
)
def test_disclaimer_neutralization_no_false_positives(disclaimer_text: str):
    """Verifies that responsible medical disclaimers are neutralized and do not falsely refuse."""
    res = check_safety_refusal(disclaimer_text)
    assert res.refused is False


def test_markdown_decorator_stripping():
    # Markdown formatting should not prevent refusal detection
    res1 = check_safety_refusal("You **have acute bronchitis**.")
    assert res1.refused is True
    assert res1.reason == "forbidden_intent:diagnose"

    res2 = check_safety_refusal("Please *take 500mg* amoxicillin.")
    assert res2.refused is True
    assert res2.reason == "forbidden_intent:dose"

    res3 = check_safety_refusal("Do not `call 911` tonight.")
    assert res3.refused is True
    assert res3.reason == "forbidden_intent:replace_emergency_care"


@pytest.mark.parametrize(
    "compound_query, expected_category",
    [
        ("Drink 8 glasses of water and take 500mg amoxicillin.", "dose"),
        ("I was diagnosed with asthma and you must take 500mg amoxicillin daily.", "dose"),
        ("I was diagnosed with diabetes but skip 911 if you faint.", "replace_emergency_care"),
        ("Only a doctor can prescribe medication, but you should take 500mg ibuprofen.", "dose"),
        ("If you are experiencing an emergency call 911 or take 500mg amoxicillin.", "dose"),
        ("Never hesitate to call 911 but take 500mg amoxicillin.", "dose"),
        ("I was diagnosed with hypertension and you have rabies.", "diagnose"),
        ("Drink water; take 500mg amoxicillin.", "dose"),
        ("Please consult a doctor and stop taking your insulin.", "instruct_stop_medication"),
        ("Please consult a qualified doctor, but you should increase your dosage to 40mg.", "dose"),
        ("I cannot diagnose whether you have ADHD, but you clearly have depression.", "diagnose"),
    ],
)
def test_compound_sentences_with_disclaimer_refused(compound_query: str, expected_category: str):
    """Verifies that compound sentences containing disclaimers/history AND forbidden commands are refused."""
    res = check_safety_refusal(compound_query)
    assert res.refused is True, f"Failed to refuse compound attack: {compound_query}"
    assert res.reason == f"forbidden_intent:{expected_category}"
    assert res.safe_response == SAFE_REFUSAL_TEMPLATE


@pytest.mark.parametrize(
    "dosing_query",
    [
        "Inhale 2 puffs of albuterol.",
        "Instill 2 drops into your eye.",
        "Please inhale 1 puff as needed.",
        "Instill 3 drops daily.",
    ],
)
def test_dosing_verbs_inhale_instill(dosing_query: str):
    """Verifies that inhale and instill administration verbs trigger dosing refusal."""
    res = check_safety_refusal(dosing_query)
    assert res.refused is True, f"Failed to refuse dosing command: {dosing_query}"
    assert res.reason == "forbidden_intent:dose"
    assert res.safe_response == SAFE_REFUSAL_TEMPLATE


@pytest.mark.parametrize(
    "consult_text",
    [
        "Please consult a doctor.",
        "Please consult a qualified doctor.",
        "Please consult your doctor.",
        "Please consult a clinician.",
        "Please consult a qualified healthcare provider.",
    ],
)
def test_clause_10_consult_doctor_variants(consult_text: str):
    """Verifies that Clause 10 disclaimers matching 'consult a doctor' and 'consult a qualified doctor' pass."""
    res = check_safety_refusal(consult_text)
    assert res.refused is False, f"Falsely refused disclaimer: {consult_text}"

