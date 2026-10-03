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

"""Adversarial PII Sanitization & Dossier Verification Test Suite.

Stress-tests boundary conditions, adversarial inputs, regex precision,
clinical vitals preservation, ReDoS resistance, and Pydantic validation on dossiers and sanitizers.
"""

from __future__ import annotations

import time
import pytest
from pydantic import ValidationError

from carefold.workflows.subgraphs.extraction.dossiers import (
    BaseDossier,
    ClinicalVisitDossier,
    GenericDocumentDossier,
    InsuranceBenefitsDossier,
    get_dossier_cls,
)
from carefold.workflows.subgraphs.extraction.sanitizer import (
    PIISanitizer,
    SanitizationResult,
    mask_pii,
    sanitize_pii,
    sanitize_pii_with_metadata,
)
from carefold.workflows.subgraphs.extraction.grounding import GroundingValidator


# ============================================================================
# 1. Adjacent PII Tokens Without Whitespace
# ============================================================================

class TestAdversarialAdjacentPiiTokens:
    """Stress-tests for adjacent PII tokens lacking separating whitespace."""

    def test_ssn_followed_immediately_by_mrn_with_label(self):
        raw = "SSN: 123-45-6789MRN: MRN998877"
        out = sanitize_pii(raw)
        assert "123-45-6789" not in out
        assert "MRN998877" not in out
        assert "[SSN]" in out
        assert "[MRN]" in out

    def test_ssn_glued_directly_to_mrn_token(self):
        raw = "123-45-6789MRN998877"
        out = sanitize_pii(raw)
        assert "123-45-6789" not in out
        assert "MRN998877" not in out
        assert "[SSN]" in out
        assert "[MRN]" in out

    def test_ssn_glued_to_parenthesized_phone(self):
        raw = "123-45-6789(555) 234-5678"
        out = sanitize_pii(raw)
        assert "123-45-6789" not in out
        assert "(555) 234-5678" not in out
        assert "[SSN]" in out
        assert "[PHONE]" in out

    def test_ssn_followed_by_email(self):
        raw = "SSN: 123-45-6789email:user@hospital.org"
        out = sanitize_pii(raw)
        assert "123-45-6789" not in out
        assert "user@hospital.org" not in out
        assert "[SSN]" in out
        assert "[EMAIL]" in out

    def test_mrn_separated_by_hyphen_from_ssn(self):
        raw = "MRN998877-123-45-6789"
        out = sanitize_pii(raw)
        assert "123-45-6789" not in out
        assert "MRN998877" not in out

    def test_unhyphenated_ssn_and_labeled_mrn(self):
        raw = "SSN: 123456789 MRN: MRN888123"
        out = sanitize_pii(raw)
        assert "123456789" not in out
        assert "MRN888123" not in out
        assert "[SSN]" in out
        assert "[MRN]" in out


# ============================================================================
# 2. Unhyphenated 9-Digit SSN & International Phone Numbers
# ============================================================================

class TestUnhyphenatedSsnAndInternationalPhones:
    """Stress-tests for raw 9-digit SSNs and varied international/domestic phone formats."""

    @pytest.mark.parametrize(
        "ssn_input",
        [
            "123456789",
            "987654321",
            "SSN: 123456789",
            "123-45-6789",
            "123.45.6789",
            "123 45 6789",
        ],
    )
    def test_valid_ssn_patterns_masked(self, ssn_input: str):
        out = sanitize_pii(f"Record: {ssn_input}")
        assert ssn_input not in out or "[SSN]" in out
        assert "[SSN]" in out

    @pytest.mark.parametrize(
        "non_ssn_input",
        [
            "12345678",    # 8 digits
            "1234567890",  # 10 digits
            "1234567",     # 7 digits
        ],
    )
    def test_non_nine_digit_numbers_not_masked_as_standalone_ssn(self, non_ssn_input: str):
        out = sanitize_pii(f"Count: {non_ssn_input}")
        assert non_ssn_input in out
        assert "[SSN]" not in out

    @pytest.mark.parametrize(
        "phone_input",
        [
            "+1-555-432-1098",
            "+1 (555) 234-5678",
            "+44 20 7946 0958",
            "+33 1 42 68 55 55",
            "+49-30-123456",
            "+15552345678",
            "(555) 234-5678",
            "555-234-5678",
            "555.234.5678",
            "555 234 5678",
            "555-234-5678 ext 1234",
            "+1 (555) 000-1111 x42",
        ],
    )
    def test_international_and_domestic_phones_masked(self, phone_input: str):
        out = sanitize_pii(f"Call dispatch at {phone_input} immediately.")
        assert phone_input not in out
        assert "[PHONE]" in out


# ============================================================================
# 3. Street Address Variations & Strict Preservation of Clinical Terms
# ============================================================================

class TestStreetAddressesAndClinicalPreservation:
    """Tests address masking accuracy and ensures ZERO false positives on clinical terms."""

    @pytest.mark.parametrize(
        "address",
        [
            "123 Main Street",
            "456 Elm St.",
            "789 Oak Ave, Suite 200",
            "101 Pine Blvd., Fl 3",
            "202 Maple Road, Apt 4B, Boston, MA 02101",
            "303 Cedar Dr",
            "404 Walnut Ln",
            "505 Birch Way",
            "606 Spruce Ct",
            "707 Ash Pl",
            "808 Willow Ter",
            "909 Beech Cir",
            "111 Cherry Pkwy",
            "222 Cypress Hwy",
            "333 Magnolia Trl",
            "PO Box 5432, Austin, TX 78701",
            "P.O. Box 100",
        ],
    )
    def test_street_address_variations_masked(self, address: str):
        out = sanitize_pii(f"Patient resides at {address} for several years.")
        assert "[ADDRESS]" in out

    @pytest.mark.parametrize(
        "clinical_phrase",
        [
            "patient stay: 24 hours",
            "stay: 24 hours",
            "Dr. Smith prescribed",
            "Dr. Smith prescribed 500 mg Amoxicillin",
            "Avenue of the Americas",
            "Patient walked down Avenue of the Americas to the clinic.",
            "Length of hospital stay: 24 hours in observation unit.",
            "Inpatient stay: 48 hours for post-operative monitoring.",
            "Consult Dr. Johnson regarding physical therapy.",
            "Prescribed Amoxicillin 500 mg PO every 8 hours for 10 days.",
            "Follow Dr. recommendations carefully.",
        ],
    )
    def test_clinical_terms_have_zero_false_positives(self, clinical_phrase: str):
        out = sanitize_pii(clinical_phrase)
        assert out == clinical_phrase, f"False positive alteration of clinical text: {clinical_phrase!r} -> {out!r}"


# ============================================================================
# 4. Strict Preservation of Clinical Vitals
# ============================================================================

class TestClinicalVitalsStrictPreservation:
    """Tests that vitals (blood pressure, temperature, pulse, dosages) are never masked."""

    @pytest.mark.parametrize(
        "vital",
        [
            "120/80 mmHg",
            "98.6 F",
            "72 bpm",
            "10 mg/mL",
            "O2 saturation: 98% on room air",
            "BMI: 24.5 kg/m2",
            "Glucose: 95 mg/dL",
            "Hemoglobin A1c: 5.7%",
            "Lisinopril 10 mg PO daily",
            "Potassium: 4.2 mEq/L",
            "BP 118/76, HR 72 bpm, Temp 98.6 F, Resp 16",
            "Administer Epinephrine 0.3 mg/mL subcutaneous",
        ],
    )
    def test_clinical_vitals_strictly_preserved(self, vital: str):
        out = sanitize_pii(vital)
        assert out == vital, f"Clinical vital was altered or masked: {vital!r} -> {out!r}"

    def test_complex_encounter_note_preservation(self):
        note = (
            "Encounter Summary:\n"
            "Vitals: BP 120/80 mmHg, Pulse 72 bpm, Temp 98.6 F, RR 18, SpO2 99%.\n"
            "Medications: Insulin 10 units SC, Morphine 2 mg/mL IV, Lisinopril 20 mg PO.\n"
            "Plan: Stay: 24 hours observation. Follow-up in two weeks."
        )
        out = sanitize_pii(note)
        assert "120/80 mmHg" in out
        assert "72 bpm" in out
        assert "98.6 F" in out
        assert "2 mg/mL" in out
        assert "Stay: 24 hours" in out
        assert "[SSN]" not in out
        assert "[PHONE]" not in out
        assert "[ADDRESS]" not in out


# ============================================================================
# 5. Pydantic Dossier Validation with Invalid Data Types
# ============================================================================

class TestPydanticDossierValidationRejection:
    """Tests that Pydantic models strictly raise ValidationError on invalid types."""

    @pytest.mark.parametrize(
        "model_cls, kwargs, field_tested",
        [
            (ClinicalVisitDossier, {"reason_for_visit": 12345}, "reason_for_visit int"),
            (ClinicalVisitDossier, {"reason_for_visit": {"nested": "value"}}, "reason_for_visit dict"),
            (ClinicalVisitDossier, {"physician_instructions": "not_a_list"}, "physician_instructions str"),
            (ClinicalVisitDossier, {"physician_instructions": 999}, "physician_instructions int"),
            (ClinicalVisitDossier, {"follow_up_timeline": [1, 2, 3]}, "follow_up_timeline list"),
            (ClinicalVisitDossier, {"questions_to_ask": {"not": "list"}}, "questions_to_ask dict"),
            (InsuranceBenefitsDossier, {"deductible": 1500}, "deductible int"),
            (InsuranceBenefitsDossier, {"copays": "not_a_dict"}, "copays str"),
            (InsuranceBenefitsDossier, {"copays": 123}, "copays int"),
            (InsuranceBenefitsDossier, {"coinsurance": ["not", "str"]}, "coinsurance list"),
            (InsuranceBenefitsDossier, {"out_of_pocket_maximum": 6000}, "out_of_pocket_maximum int"),
            (InsuranceBenefitsDossier, {"prior_authorization_flags": "not_a_list"}, "prior_auth str"),
            (InsuranceBenefitsDossier, {"prior_authorization_flags": 123}, "prior_auth int"),
            (GenericDocumentDossier, {"summary": {"invalid": "dict"}}, "summary dict"),
            (GenericDocumentDossier, {"summary": 123}, "summary int"),
            (GenericDocumentDossier, {"key_numerical_values": "not_a_dict"}, "key_numerical_values str"),
            (GenericDocumentDossier, {"key_numerical_values": [1, 2, 3]}, "key_numerical_values list"),
            (GenericDocumentDossier, {"sections": "not_a_list"}, "sections str"),
            (GenericDocumentDossier, {"sections": 123}, "sections int"),
        ],
    )
    def test_pydantic_invalid_type_raises_validation_error(self, model_cls, kwargs, field_tested):
        with pytest.raises(ValidationError):
            model_cls(**kwargs)


# ============================================================================
# 6. Extreme Strings, Scripts, XSS, Emojis, and Serialization
# ============================================================================

class TestDossierExtremeStringsAndSpecialChars:
    """Tests 5000+ character strings, XSS payloads, emojis, and serialization."""

    def test_5000_plus_character_strings_in_clinical_dossier(self):
        giant_5k = "Clinical note content. " * 250  # ~5,750 characters
        giant_50k = "Detailed physician instructions and discharge summary. " * 1000  # ~55,000 chars

        dossier = ClinicalVisitDossier(
            reason_for_visit=giant_5k,
            physician_instructions=[giant_50k],
            follow_up_timeline="4 weeks",
            questions_to_ask=[giant_5k],
        )

        assert len(dossier.reason_for_visit) >= 5000
        assert len(dossier.physician_instructions[0]) >= 50000

        # Serialization roundtrip
        d_dict = dossier.to_dict(include_type=True)
        assert d_dict["dossier_type"] == "clinical_visit"
        assert len(d_dict["reason_for_visit"]) >= 5000

        d_json = dossier.to_json()
        assert len(d_json) > 55000

    def test_special_characters_xss_and_scripts_preserved_without_escaping(self):
        xss_reason = "<script>alert('XSS-Attempt');</script><img src='x' onerror='exploit()'>"
        sql_inst = "Robert'); DROP TABLE EncounterRecords;--"
        crlf_q = "Line 1\r\nLine 2\tTabbed\nLine 3"

        dossier = ClinicalVisitDossier(
            reason_for_visit=xss_reason,
            physician_instructions=[sql_inst],
            follow_up_timeline="<xml><tag>2 weeks</tag></xml>",
            questions_to_ask=[crlf_q],
        )

        assert dossier.reason_for_visit == xss_reason
        assert "<script>" in dossier.reason_for_visit
        assert sql_inst in dossier.physician_instructions[0]

        json_out = dossier.to_json()
        assert "<script>" in json_out

    def test_medical_emojis_and_unicode_in_generic_dossier(self):
        emojis = "🩺 🏥 💉 💊 🧬 🩸 🧪 🤒 🚑 👨‍⚕️ 👩‍⚕️ ❤️‍🩹 📋 🌡️"
        dossier = GenericDocumentDossier(
            summary=f"Emergency department intake: {emojis}",
            key_numerical_values={"dosage": "100 💊/day", "temp": "38.5 🌡️"},
            sections=[f"Section with {emojis}"],
        )

        assert emojis in dossier.summary
        assert "💊" in dossier.key_numerical_values["dosage"]

        d_dict = dossier.to_dict()
        assert emojis in d_dict["summary"]

        d_json = dossier.to_json()
        assert "💊" in d_json


# ============================================================================
# 7. ReDoS Resistance and Pathological Sanitizer Performance
# ============================================================================

class TestSanitizerReDoSAndPathologicalResilience:
    """Verifies sanitizer resilience against pathological inputs and ReDoS attacks."""

    def test_140k_character_document_with_dense_pii_performance(self):
        dense_pii = (
            "Patient John Doe (SSN: 123-45-6789, MRN: MRN44921, Phone: 555-234-5678, "
            "Address: 123 Elm Street, Springfield, Email: doe@example.com). "
        ) * 1000  # ~140,000 characters

        t0 = time.perf_counter()
        result = sanitize_pii_with_metadata(dense_pii)
        elapsed = time.perf_counter() - t0

        assert elapsed < 1.0, f"Processing 140k characters took too long: {elapsed:.3f}s"
        assert result.has_pii is True
        assert result.redacted_counts["ssn"] == 1000
        assert result.redacted_counts["email"] == 1000
        assert "123-45-6789" not in result.sanitized_text

    @pytest.mark.parametrize(
        "pathological_pattern",
        [
            "+" + "1-" * 1500 + "555-1234",          # nested phone prefix
            "(" * 800 + "555" + ")" * 800,           # nested parentheses
            "123 " * 1500 + "Street",                 # runaway address house numbers
            "A" * 30000 + "@" + "B" * 30000 + ".com", # giant email username/domain
            "MRN" + "9" * 40000,                      # long MRN token
            "0" * 50000,                              # long digit stream
        ],
    )
    def test_pathological_patterns_terminate_within_deadline(self, pathological_pattern: str):
        t0 = time.perf_counter()
        _ = sanitize_pii(pathological_pattern)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.5, f"Potential ReDoS detected: took {elapsed:.4f}s"

    def test_none_and_empty_inputs(self):
        assert sanitize_pii("") == ""
        assert sanitize_pii(None) == ""
        assert sanitize_pii("   ") == "   "
        res = sanitize_pii_with_metadata("")
        assert res.has_pii is False
        assert res.redacted_counts == {}


# ============================================================================
# 8. Empirical Defect Isolation: Clinical Collisions with Street Suffixes
# ============================================================================

class TestClinicalCollisionsDefectIsolation:
    """Verifies remediation of defects where ADDRESS_PATTERN collided with clinical terminology."""

    def test_defect_doctor_reference_preceded_by_duration_masked_as_address(self):
        # In follow-up instructions, "2 weeks with Dr. Smith" must be preserved
        raw = "Follow-up in 2 weeks with Dr. Smith."
        sanitized = sanitize_pii(raw)
        assert "2 weeks with Dr. Smith" in sanitized

    def test_defect_ct_scan_masked_as_address(self):
        # In medical imaging orders, "1 pelvic CT" must be preserved
        raw = "Scheduled 1 pelvic CT scan."
        sanitized = sanitize_pii(raw)
        assert "1 pelvic CT" in sanitized

    def test_defect_lymph_node_abbreviation_masked_as_address(self):
        # In pathology / oncology notes, "1 sentinel LN" must be preserved
        raw = "Biopsy of 1 sentinel LN showed no malignancy."
        sanitized = sanitize_pii(raw)
        assert "1 sentinel LN" in sanitized

    def test_defect_common_word_way_masked_as_address(self):
        # Common word "way" must not be treated as a street address
        raw = "Dosed 1 different way."
        sanitized = sanitize_pii(raw)
        assert "1 different way" in sanitized
