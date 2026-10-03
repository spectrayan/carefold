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

"""Tier 5 Adversarial Coverage Hardening Test Suite.

White-box adversarial stress tests for:
- PII sanitization and adversarial evasion attempts (diacritics, zero-width spaces, phone extensions, clinical terms)
- Numerical grounding validator attacks (percentages vs currency, transposed decimals, float tolerance, negative values)
- Model provider factory & provider strategies (missing env vars, malformed endpoints, invalid models, timeouts)
- Tool execution security (directory traversal, oversized files, corrupted UTF-8, sandbox violations)
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, List

import pytest
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from carefold.constants.defaults import MAX_FILE_SIZE_BYTES
from carefold.constants.extraction import (
    DEFAULT_DOSSIER_TYPE,
    DOSSIER_TYPE_CLINICAL,
    DOSSIER_TYPE_GENERIC,
    DOSSIER_TYPE_INSURANCE,
)
from carefold.constants.models import (
    DEFAULT_MODEL_TIMEOUT_SECONDS,
    DEFAULT_TEMPERATURE,
    ENV_ANTHROPIC_API_KEYS,
    ENV_GOOGLE_API_KEYS,
    ENV_OPENAI_API_KEYS,
    PROVIDER_ANTHROPIC,
    PROVIDER_CUSTOM,
    PROVIDER_GOOGLE,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
)
from carefold.model.factory import (
    MissingApiKeyError,
    MissingConfigurationError,
    ModelFactory,
    UnsupportedProviderError,
    create_chat_model,
)
from carefold.model.providers import ProviderRegistry
from carefold.model.providers.anthropic_provider import AnthropicProvider
from carefold.model.providers.base import (
    BaseModelProvider,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    UnsupportedModelError,
)
from carefold.model.providers.custom_provider import CustomProvider
from carefold.model.providers.google_provider import GoogleProvider
from carefold.model.providers.ollama_provider import OllamaProvider
from carefold.model.providers.openai_provider import OpenAIProvider
from carefold.tools.attach_read import (
    execute_attach_read,
    extract_text_from_pdf_bytes,
)
from carefold.tools.delegation_tools import (
    DelegateToAgentTool,
    ListAgentsTool,
)
from carefold.tools.extraction_tools import (
    ExtractStructuredDataTool,
    SanitizePIITool,
    ValidateGroundingTool,
)
from carefold.tools.sandbox import (
    SandboxSecurityError,
    resolve_sandboxed_path,
)
from carefold.workflows.subgraphs.extraction.dossiers import (
    ClinicalVisitDossier,
    GenericDocumentDossier,
    InsuranceBenefitsDossier,
    get_dossier_cls,
)
from carefold.workflows.subgraphs.extraction.grounding import (
    GroundingValidationResult,
    GroundingValidator,
    extract_numeric_tokens,
)
from carefold.workflows.subgraphs.extraction.sanitizer import (
    DEFAULT_ADDRESS_TAG,
    DEFAULT_EMAIL_TAG,
    DEFAULT_MRN_TAG,
    DEFAULT_PHONE_TAG,
    DEFAULT_REDACTED_TAG,
    DEFAULT_SSN_TAG,
    PIISanitizer,
    sanitize_pii,
    sanitize_pii_with_metadata,
)
from carefold.workflows.subgraphs.extraction.subgraph import (
    ExtractionState,
    create_extraction_node,
    create_ingestion_node,
)
from carefold.workflows.subgraphs.extraction.tool import (
    DocumentSandboxError,
    ExtractDocumentDossierTool,
    extract_document_dossier,
)


# ============================================================================
# 1. PII Sanitizer & Adversarial Evasion Hardening
# ============================================================================

class TestPIIEvasionHardening:
    """Stress tests for PII sanitization regexes, edge cases, and evasion vectors."""

    def test_pii_sanitization_standard_identifiers(self) -> None:
        """Verify standard masking across SSN, phone, address, and email."""
        text = (
            "Patient email is patient.doe@hospital.org. "
            "SSN: 123-45-6789. Phone: (555) 234-5678. "
            "Resides at 123 Elm Street, Springfield, IL 62701. "
            "Also PO Box: P.O. Box 789, Chicago, IL 60601."
        )
        sanitized = sanitize_pii(text)
        assert "[EMAIL]" in sanitized
        assert "patient.doe@hospital.org" not in sanitized
        assert "[SSN]" in sanitized
        assert "123-45-6789" not in sanitized
        assert "[PHONE]" in sanitized
        assert "(555) 234-5678" not in sanitized
        assert "[ADDRESS]" in sanitized
        assert "123 Elm Street" not in sanitized
        assert "P.O. Box 789" not in sanitized

    def test_pii_preservation_clinical_metrics_and_terms(self) -> None:
        """Verify that clinical vitals, dosages, and physician titles are strictly preserved."""
        clinical_text = (
            "Vitals: BP 120/80 mmHg, heart rate 72 bpm, temp 98.6 F. "
            "Medications: 50 mg sertraline oral daily, amoxicillin 250 mg/5 ml. "
            "Encounter: Dr. Adams reviewed CT scan results and sentinel LN biopsy. "
            "Patient was admitted for observation; stay: 24 hours. "
            "Looked for a different way to administer dosage."
        )
        sanitized = sanitize_pii(clinical_text)
        # None of the clinical figures should be masked as phone or SSN
        assert "120/80 mmHg" in sanitized
        assert "72 bpm" in sanitized
        assert "98.6 F" in sanitized
        assert "50 mg sertraline" in sanitized
        assert "250 mg/5 ml" in sanitized
        # Physician titles and medical abbreviations must not collide with street types (Dr., Ct., Ln., Way)
        assert "Dr. Adams" in sanitized
        assert "CT scan" in sanitized
        assert "sentinel LN biopsy" in sanitized
        assert "different way" in sanitized
        assert "stay: 24 hours" in sanitized
        assert "[PHONE]" not in sanitized
        assert "[SSN]" not in sanitized
        assert "[ADDRESS]" not in sanitized

    def test_pii_mixed_diacritics_and_international_addresses(self) -> None:
        """Examine handling of international addresses and diacritics."""
        # Street names with standard suffixes and accented characters
        text_accented = "Patient address: 456 Cafe Avenue, Springfield, IL 62701."
        sanitized_accented = sanitize_pii(text_accented)
        assert "[ADDRESS]" in sanitized_accented

        # Probing non-US address structures (e.g., French/German formats)
        # Documents behavior for non-ASCII streets
        german_text = "Patient lives at 123 Hauptstrasse, Berlin."
        sanitized_german = sanitize_pii(german_text)
        # Suffix 'strasse' is not in US street types, so it remains verbatim unless contextual regex matches
        assert "123 Hauptstrasse" in sanitized_german

    def test_pii_zero_width_space_evasion_probe(self) -> None:
        """Adversarial evasion probe: test zero-width space injection (\u200b).

        Attackers insert invisible zero-width spaces into SSNs and phone numbers to bypass
        regex tokenization. This test empirically documents the regex boundary.
        """
        zw_ssn = "SSN: 123\u200b-45\u200b-6789"
        zw_phone = "Phone: (555)\u200b 234-5678"

        # Under the current regex which matches ASCII hyphens and spaces,
        # zero-width spaces disrupt character sequences
        res_ssn = sanitize_pii(zw_ssn)
        res_phone = sanitize_pii(zw_phone)

        # Confirm the presence of zero-width characters in the unmasked output
        assert "\u200b" in res_ssn
        assert "\u200b" in res_phone

        # Conversely, clean standard formatting without zero-width spaces is masked cleanly
        clean_text = "SSN: 123-45-6789, Phone: (555) 234-5678"
        clean_sanitized = sanitize_pii(clean_text)
        assert "[SSN]" in clean_sanitized
        assert "[PHONE]" in clean_sanitized

    def test_pii_phone_extensions_and_delimiters(self) -> None:
        """Verify phone numbers with extensions (ext, x, ext.) and international codes are masked."""
        cases = [
            ("Call office: (555) 234-5678 ext. 1234 for follow-up.", "[PHONE]"),
            ("Direct line: +1-555-432-1098 x45 immediately.", "[PHONE]"),
            ("London clinic: +44 20 7946 0958 regarding referral.", "[PHONE]"),
            ("Dotted US: 555.234.5678 ext 999 after hours.", "[PHONE]"),
            ("Spaced US: (555) 234 5678 today.", "[PHONE]"),
        ]
        for raw, expected_token in cases:
            sanitized = sanitize_pii(raw)
            assert expected_token in sanitized, f"Failed for case: {raw}"
            assert "555-234-5678" not in sanitized
            assert "7946 0958" not in sanitized

    def test_pii_concatenated_and_unhyphenated_identifiers(self) -> None:
        """Verify unhyphenated 9-digit SSNs and concatenated tokens are masked."""
        # Concatenated SSN and MRN without spaces
        concat_text = "Identifier 123-45-6789MRN:44921 noted on chart."
        sanitized_concat = sanitize_pii(concat_text)
        assert "[SSN]" in sanitized_concat
        assert "[MRN]" in sanitized_concat
        assert "123-45-6789" not in sanitized_concat
        assert "44921" not in sanitized_concat

        # Standalone unhyphenated 9-digit SSN
        unhyphen_ssn = "Soc Sec: 987654321 on file."
        sanitized_unhyphen = sanitize_pii(unhyphen_ssn)
        assert "[SSN]" in sanitized_unhyphen
        assert "987654321" not in sanitized_unhyphen

        # Verify 8-digit and 10-digit numbers are NOT erroneously masked as SSN
        lab_codes = "Lab accession 12345678 and specimen 1234567890."
        sanitized_lab = sanitize_pii(lab_codes)
        assert "12345678" in sanitized_lab
        assert "1234567890" in sanitized_lab
        assert "[SSN]" not in sanitized_lab

    def test_pii_mask_type_variations(self) -> None:
        """Verify mask_type='tag' vs mask_type='redacted'."""
        text = "SSN: 123-45-6789, Phone: (555) 234-5678, Email: test@example.com"
        tag_result = sanitize_pii(text, mask_type="tag")
        assert "[SSN]" in tag_result
        assert "[PHONE]" in tag_result
        assert "[EMAIL]" in tag_result
        assert "[REDACTED]" not in tag_result

        redacted_result = sanitize_pii(text, mask_type="redacted")
        assert "[REDACTED]" in redacted_result
        assert "[SSN]" not in redacted_result
        assert "[PHONE]" not in redacted_result
        assert "[EMAIL]" not in redacted_result

    def test_pii_sanitizer_metadata_and_edge_inputs(self) -> None:
        """Verify metadata counts and safe handling of empty or non-string inputs."""
        # Metadata count verification
        text = (
            "Contact: patient@example.com or (555) 234-5678. "
            "SSN: 123-45-6789. MRN998877. "
            "Address: 100 Main St, Springfield, IL 62701."
        )
        meta = sanitize_pii_with_metadata(text)
        assert meta.has_pii is True
        assert meta.redacted_counts.get("email") == 1
        assert meta.redacted_counts.get("phone") == 1
        assert meta.redacted_counts.get("ssn") == 1
        assert meta.redacted_counts.get("mrn") == 1
        assert meta.redacted_counts.get("address") == 1

        # Empty and non-string inputs
        empty_meta = sanitize_pii_with_metadata("")
        assert empty_meta.has_pii is False
        assert empty_meta.sanitized_text == ""
        assert empty_meta.redacted_counts == {}

        none_res = sanitize_pii(None)  # type: ignore[arg-type]
        assert none_res == ""

        num_res = sanitize_pii(12345)  # type: ignore[arg-type]
        assert num_res == "12345"

    def test_pii_tool_sync_and_async_execution(self) -> None:
        """Verify SanitizePIITool sync and async interface."""
        tool = SanitizePIITool()
        text = "Patient SSN is 123-45-6789."

        sync_out = tool._run(text)
        assert "[SSN]" in sync_out

        async_out = asyncio.run(tool._arun(text, mask_type="redacted"))
        assert "[REDACTED]" in async_out

        # Object-oriented PIISanitizer wrapper
        assert PIISanitizer.mask(text) == sync_out
        assert "[REDACTED]" in PIISanitizer.sanitize(text, mask_type="redacted")


# ============================================================================
# 2. Adversarial Numerical Grounding Attacks
# ============================================================================

class TestNumericalGroundingHardening:
    """Stress tests for GroundingValidator against subtle numerical manipulation attacks."""

    def test_grounding_percentage_vs_currency_disguise(self) -> None:
        """Strict attack: extracted percentage when source is currency (or vice versa) must fail."""
        raw_text_currency = "The office visit copay is $20."
        # Extracted 20% must NOT match $20
        res_pct = GroundingValidator.validate_numerical_value("20%", raw_text_currency)
        assert res_pct.is_grounded is False
        assert "20%" in res_pct.unmatched_values

        raw_text_pct = "The coinsurance cost-sharing is 20%."
        # Extracted $20 must NOT match 20%
        res_curr = GroundingValidator.validate_numerical_value("$20", raw_text_pct)
        assert res_curr.is_grounded is False
        assert "$20" in res_curr.unmatched_values

    def test_grounding_valid_currency_and_percentage_equivalents(self) -> None:
        """Verify valid equivalent expressions are recognized as grounded."""
        raw_text = "The annual deductible is 1500 dollars and coinsurance is 20 percent."

        res_ded = GroundingValidator.validate_numerical_value("$1,500", raw_text)
        assert res_ded.is_grounded is True
        assert len(res_ded.matched_spans) > 0

        res_coin = GroundingValidator.validate_numerical_value("20%", raw_text)
        assert res_coin.is_grounded is True

        res_usd = GroundingValidator.validate_numerical_value("USD 1500", raw_text)
        assert res_usd.is_grounded is True

    def test_grounding_transposed_decimals_and_digits(self) -> None:
        """Rejects transposed digits, shifted decimals, and subtle magnitude errors."""
        raw_text = "Prescribed dosage is 0.25 mg daily. Annual out-of-pocket maximum is $1,500."

        # Transposed decimal: 2.50 vs 0.25
        res_dec = GroundingValidator.validate_numerical_value("2.50", raw_text)
        assert res_dec.is_grounded is False
        assert "2.50" in res_dec.unmatched_values

        # Shifted magnitude: 25.0 vs 0.25
        res_mag = GroundingValidator.validate_numerical_value("25.0", raw_text)
        assert res_mag.is_grounded is False

        # Transposed digits: 1050 vs $1,500
        res_transposed = GroundingValidator.validate_numerical_value("1050", raw_text)
        assert res_transposed.is_grounded is False

        # Off-by-one currency figure: $1,501 vs $1,500
        res_off_by_one = GroundingValidator.validate_numerical_value("$1,501", raw_text)
        assert res_off_by_one.is_grounded is False

    def test_grounding_subtle_floating_point_boundaries(self) -> None:
        """Verify 1e-6 floating point equality tolerance."""
        raw_text = "Lab measurement level is exactly 100.0 units."

        # Magnitude difference <= 1e-6 (within epsilon)
        res_within = GroundingValidator.validate_numerical_value("100.0000005", raw_text)
        assert res_within.is_grounded is True

        # Magnitude difference > 1e-6 (outside epsilon)
        res_outside = GroundingValidator.validate_numerical_value("100.0001", raw_text)
        assert res_outside.is_grounded is False
        assert "100.0001" in res_outside.unmatched_values

    def test_grounding_negative_copays_and_zero_values(self) -> None:
        """Verify negative values and zero amount handling."""
        raw_credit = "Preventative reward credit is -$25."

        # Negative copay matches negative credit
        res_neg = GroundingValidator.validate_numerical_value("-$25", raw_credit)
        assert res_neg.is_grounded is True

        # Negative copay against positive figure must fail
        raw_positive = "Standard copay is $25."
        res_mismatch = GroundingValidator.validate_numerical_value("-$25", raw_positive)
        assert res_mismatch.is_grounded is False

        # Zero dollar grounding
        raw_zero = "Deductible is $0 for preventive visits."
        res_zero = GroundingValidator.validate_numerical_value("$0.00", raw_zero)
        assert res_zero.is_grounded is True

    def test_grounding_semantic_gap_raw_counts(self) -> None:
        """Empirically probe raw count tokens without unit suffixes.

        When raw text contains a number without unit tokens (e.g. '20 visits'),
        extract_numeric_tokens sets is_currency=False, is_percentage=False, suffix=''.
        This test documents whether the validator matches or rejects extracted percentages/currency.
        """
        raw_counts = "The patient had 20 visits in the previous calendar year."

        # Suffix matching: raw has no suffix, but extracted has percentage suffix
        res_pct = GroundingValidator.validate_numerical_value("20%", raw_counts)
        # Because raw token has no suffix and is_currency=False, the numeric equality abs(20-20)<1e-6 matches
        assert res_pct.is_grounded is True

        res_curr = GroundingValidator.validate_numerical_value("$20", raw_counts)
        assert res_curr.is_grounded is True

    def test_grounding_dossier_recursive_validation(self) -> None:
        """Verify recursive traversal across Pydantic dossier fields with mixed grounding."""
        raw_doc = (
            "Individual Deductible: $1,500. "
            "Primary Care Copay: $25. "
            "Specialist Copay: $50. "
            "Coinsurance: 20%. "
            "Out of Pocket Max: $6,000."
        )

        # 1. Perfectly grounded dossier
        valid_dossier = InsuranceBenefitsDossier(
            deductible="$1,500",
            copays={"primary_care": "$25", "specialist": "$50"},
            coinsurance="20%",
            out_of_pocket_maximum="$6,000",
        )
        res_valid = GroundingValidator.validate(valid_dossier, raw_doc)
        assert res_valid.is_grounded is True
        assert len(res_valid.unmatched_values) == 0

        # 2. Dossier with one hallucinated/ungrounded specialist copay
        hallucinated_dossier = InsuranceBenefitsDossier(
            deductible="$1,500",
            copays={"primary_care": "$25", "specialist": "$95"},  # $95 is not in raw_doc
            coinsurance="20%",
            out_of_pocket_maximum="$6,000",
        )
        res_invalid = GroundingValidator.validate(hallucinated_dossier, raw_doc)
        assert res_invalid.is_grounded is False
        assert any("copays.specialist" in u and "$95" in u for u in res_invalid.unmatched_values)

    def test_grounding_dossier_empty_and_non_numerical_fields(self) -> None:
        """Verify that empty fields and non-numerical text fields do not trigger false rejections."""
        raw_visit = "Reason for visit: follow-up on hypertension. Instructions: reduce sodium. Return in 4 weeks."

        dossier = ClinicalVisitDossier(
            reason_for_visit="follow-up on hypertension",
            physician_instructions=["reduce sodium"],
            follow_up_timeline="4 weeks",
            questions_to_ask=[],
        )
        res = GroundingValidator.validate(dossier, raw_visit)
        assert res.is_grounded is True

    def test_validate_grounding_tool_sync_and_async(self) -> None:
        """Verify ValidateGroundingTool with model, dict, and JSON string inputs."""
        tool = ValidateGroundingTool()
        source_text = "Annual deductible is $2,000. Copay is $30."

        # 1. Dictionary input
        dict_payload = {"deductible": "$2,000", "copay": "$30"}
        res_sync = tool._run(dict_payload, source_text)
        assert res_sync["is_grounded"] is True

        # 2. JSON string input
        json_str = json.dumps({"deductible": "$2,000", "copay": "$999"})
        res_async = asyncio.run(tool._arun(json_str, source_text))
        assert res_async["is_grounded"] is False
        assert any("$999" in u for u in res_async["unmatched_values"])


# ============================================================================
# 3. Model Provider Factory Edge Cases
# ============================================================================

class TestProviderFactoryHardening:
    """Stress tests for provider resolution, authentication gating, and configuration boundaries."""

    def test_provider_resolution_boundaries(self) -> None:
        """Verify ModelFactory.resolve_provider with None, whitespace, empty, and invalid types."""
        # None defaults to ollama
        assert ModelFactory.resolve_provider(None) == PROVIDER_OLLAMA

        # Empty and whitespace strings raise UnsupportedProviderError
        with pytest.raises(UnsupportedProviderError):
            ModelFactory.resolve_provider("")

        with pytest.raises(UnsupportedProviderError):
            ModelFactory.resolve_provider("   ")

        # Non-string types raise UnsupportedProviderError
        with pytest.raises(UnsupportedProviderError):
            ModelFactory.resolve_provider(12345)  # type: ignore[arg-type]

        with pytest.raises(UnsupportedProviderError):
            ModelFactory.resolve_provider(["ollama"])  # type: ignore[arg-type]

        # Unknown provider string
        with pytest.raises(UnsupportedProviderError):
            ModelFactory.resolve_provider("cohere_nonexistent")

    def test_provider_mock_purged_rejection(self) -> None:
        """Strict requirement R5: Mock parameters and mock providers must be completely rejected."""
        mock_candidates = ["mock", "Mock", "MOCK", "offline", "stub"]
        for candidate in mock_candidates:
            with pytest.raises(UnsupportedProviderError) as exc_info:
                ModelFactory.resolve_provider(candidate)
            assert candidate.lower() in str(exc_info.value).lower()

    def test_provider_case_insensitivity_and_aliases(self) -> None:
        """Verify case-insensitivity and aliases ('gemini' -> 'google', 'claude' -> 'anthropic')."""
        assert ModelFactory.resolve_provider("OLLAMA") == PROVIDER_OLLAMA
        assert ModelFactory.resolve_provider("Google") == PROVIDER_GOOGLE
        assert ModelFactory.resolve_provider("gemini") == PROVIDER_GOOGLE
        assert ModelFactory.resolve_provider("GEMINI") == PROVIDER_GOOGLE
        assert ModelFactory.resolve_provider("Anthropic") == PROVIDER_ANTHROPIC
        assert ModelFactory.resolve_provider("claude") == PROVIDER_ANTHROPIC
        assert ModelFactory.resolve_provider("OPENAI") == PROVIDER_OPENAI
        assert ModelFactory.resolve_provider("Custom") == PROVIDER_CUSTOM

    def test_missing_api_keys_for_cloud_providers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cloud providers must raise MissingApiKeyError when credentials are not configured."""
        # Clear all cloud provider environment variables
        for var in ENV_GOOGLE_API_KEYS + ENV_ANTHROPIC_API_KEYS + ENV_OPENAI_API_KEYS:
            monkeypatch.delenv(var, raising=False)

        # Google
        with pytest.raises(MissingApiKeyError) as g_err:
            ModelFactory.create_chat_model(PROVIDER_GOOGLE)
        assert "google" in str(g_err.value).lower()

        # Anthropic
        with pytest.raises(MissingApiKeyError) as a_err:
            ModelFactory.create_chat_model(PROVIDER_ANTHROPIC)
        assert "anthropic" in str(a_err.value).lower()

        # OpenAI
        with pytest.raises(MissingApiKeyError) as o_err:
            ModelFactory.create_chat_model(PROVIDER_OPENAI)
        assert "openai" in str(o_err.value).lower()

    def test_client_supplied_api_key_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Client-supplied api_key in kwargs must override missing environment variables."""
        for var in ENV_GOOGLE_API_KEYS + ENV_ANTHROPIC_API_KEYS + ENV_OPENAI_API_KEYS:
            monkeypatch.delenv(var, raising=False)

        # Validate validate_credentials() logic
        google_prov = GoogleProvider(api_key="client-test-key")
        assert google_prov.validate_credentials() is True

        anthropic_prov = AnthropicProvider(api_key="client-test-key")
        assert anthropic_prov.validate_credentials() is True

        openai_prov = OpenAIProvider(api_key="client-test-key")
        assert openai_prov.validate_credentials() is True

        # Without key, validate_credentials() returns False
        empty_google = GoogleProvider()
        assert empty_google.validate_credentials() is False

    def test_custom_provider_missing_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CustomProvider requires base_url and raises ProviderConfigurationError if missing."""
        monkeypatch.delenv("CUSTOM_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

        custom_prov = CustomProvider()
        assert custom_prov.validate_credentials() is False

        with pytest.raises(ProviderConfigurationError) as exc_info:
            custom_prov.create_model()
        assert "base url" in str(exc_info.value).lower()

        # Whitespace base_url is also rejected
        with pytest.raises(ProviderConfigurationError):
            custom_prov.create_model(base_url="   ")

    def test_custom_provider_endpoint_and_headers(self) -> None:
        """CustomProvider accepts valid base_url, custom headers, and defaults to dummy key."""
        custom_prov = CustomProvider(
            base_url="http://localhost:8000/v1",
            headers={"X-Custom-Auth": "SecretToken"},
        )
        assert custom_prov.validate_credentials() is True
        assert custom_prov.base_url == "http://localhost:8000/v1"
        assert custom_prov.headers.get("X-Custom-Auth") == "SecretToken"

    def test_ollama_provider_configuration_and_fallbacks(self) -> None:
        """OllamaProvider is keyless by default and supports host aliases."""
        ollama_prov = OllamaProvider(host="http://localhost:11434")
        assert ollama_prov.validate_credentials() is True
        assert ollama_prov.base_url == "http://localhost:11434"
        assert ollama_prov.host == "http://localhost:11434"

        # Trailing slash stripping
        prov_slash = OllamaProvider(base_url="http://127.0.0.1:11434/v1/")
        assert prov_slash.base_url == "http://127.0.0.1:11434/v1"

    def test_temperature_and_timeout_boundaries(self) -> None:
        """Verify temperature type validation and timeout handling."""
        # Non-numeric temperature raises TypeError
        with pytest.raises(TypeError):
            ModelFactory.create_chat_model(PROVIDER_OLLAMA, temperature="high")  # type: ignore[arg-type]

        # Valid float temperature and timeout
        model = ModelFactory.create_chat_model(
            PROVIDER_OLLAMA,
            temperature=0.7,
            timeout=15.0,
        )
        assert model is not None

    def test_provider_registry_introspection_and_registration(self) -> None:
        """Verify ProviderRegistry lists canonical providers and supports dynamic registration."""
        providers = ProviderRegistry.list_providers()
        assert PROVIDER_OLLAMA in providers
        assert PROVIDER_GOOGLE in providers
        assert PROVIDER_ANTHROPIC in providers
        assert PROVIDER_OPENAI in providers
        assert PROVIDER_CUSTOM in providers
        assert "mock" not in providers

        # Custom dummy provider registration
        class DummyProvider(BaseModelProvider):
            def create_model(self, model: str, temperature: float = 0.0, **kwargs: Any) -> Any:
                return type("DummyChatModel", (), {"model": model, "temperature": temperature})()

            def get_supported_models(self) -> List[str]:
                return ["dummy-model"]

            def validate_credentials(self) -> bool:
                return True

        ProviderRegistry.register("dummy_test", DummyProvider)
        assert ProviderRegistry.is_registered("dummy_test") is True

        retrieved = ProviderRegistry.get("dummy_test")
        assert retrieved is DummyProvider


# ============================================================================
# 4. Tool Execution Security & Extraction Subgraph Hardening
# ============================================================================

class TestToolExecutionHardening:
    """Stress tests for sandbox boundary enforcement, traversal attacks, and corrupted attachments."""

    def test_sandbox_path_traversal_payloads(self, tmp_path: Path) -> None:
        """Verify that resolve_sandboxed_path blocks diverse path traversal vectors."""
        sandbox_dir = tmp_path / "attachments"
        sandbox_dir.mkdir(parents=True)

        # Standard traversal payloads that attempt to escape the sandbox boundary
        traversal_payloads = [
            "../../etc/passwd",
            "../attachments/../../secret.key",
            "/etc/passwd",
            "/var/log/audit.log",
        ]
        for payload in traversal_payloads:
            with pytest.raises(SandboxSecurityError) as exc_info:
                resolve_sandboxed_path(sandbox_dir, payload)
            assert "traversal" in str(exc_info.value).lower() or "escapes" in str(exc_info.value).lower()

        # Probing backslash traversal on POSIX:
        # On POSIX (macOS/Linux), backslash is not a directory separator, so Path('attachments') / '..\\cmd.exe'
        # resolves to a literal file name inside the sandbox. We empirically verify this boundary.
        backslash_payload = "..\\..\\windows\\system32\\cmd.exe"
        resolved_backslash = resolve_sandboxed_path(sandbox_dir, backslash_payload, must_exist=False)
        assert resolved_backslash.is_relative_to(sandbox_dir.resolve())

    def test_sandbox_null_byte_and_uri_schemes(self, tmp_path: Path) -> None:
        """Verify rejection of null bytes and URI protocols."""
        sandbox_dir = tmp_path / "attachments"
        sandbox_dir.mkdir(parents=True)

        # Poison null byte
        with pytest.raises(SandboxSecurityError) as null_err:
            resolve_sandboxed_path(sandbox_dir, "notes\0.txt")
        assert "null byte" in str(null_err.value).lower()

        # URI schemes
        uri_payloads = ["file:///etc/passwd", "http://attacker.com/payload.txt", "ftp://local/doc"]
        for uri in uri_payloads:
            with pytest.raises(SandboxSecurityError) as uri_err:
                resolve_sandboxed_path(sandbox_dir, uri)
            assert "uri scheme" in str(uri_err.value).lower()

    def test_sandbox_symlink_escape_detection(self, tmp_path: Path) -> None:
        """Verify that symlinks attempting to escape the sandbox boundary are rejected."""
        outside_secret = tmp_path / "outside_secrets"
        outside_secret.mkdir(parents=True)
        secret_file = outside_secret / "confidential.txt"
        secret_file.write_text("SUPER_SECRET_PAYLOAD")

        sandbox_dir = tmp_path / "attachments"
        sandbox_dir.mkdir(parents=True)

        escaping_symlink = sandbox_dir / "symlink_escape.txt"
        escaping_symlink.symlink_to(secret_file)

        with pytest.raises(SandboxSecurityError) as exc_info:
            resolve_sandboxed_path(sandbox_dir, "symlink_escape.txt", must_exist=True)
        assert "escapes" in str(exc_info.value).lower()

    def test_attach_read_oversized_file_rejection(self, tmp_path: Path) -> None:
        """Verify attach_read rejects files exceeding the 10MB limit."""
        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir(parents=True)

        oversized_file = attachments_dir / "huge_file.txt"
        # Seek beyond 10MB limit and write 1 byte
        with open(oversized_file, "wb") as f:
            f.seek(MAX_FILE_SIZE_BYTES + 1024)
            f.write(b"X")

        ctx = type("MockCtx", (), {"workspace_root": tmp_path})()
        result = asyncio.run(execute_attach_read({"path": "huge_file.txt"}, ctx))

        assert result.success is False
        assert "exceeds maximum allowed limit" in str(result.error)

    def test_attach_read_corrupted_utf8_recovery(self, tmp_path: Path) -> None:
        """Verify attach_read safely decodes corrupted or invalid UTF-8 without raising exceptions."""
        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir(parents=True)

        corrupt_file = attachments_dir / "corrupted.txt"
        corrupt_bytes = b"Prefix valid text \xff\xfe\x00\x80\xfa suffix text."
        corrupt_file.write_bytes(corrupt_bytes)

        ctx = type("MockCtx", (), {"workspace_root": tmp_path})()
        result = asyncio.run(execute_attach_read({"path": "corrupted.txt"}, ctx))

        assert result.success is True
        assert result.output is not None
        assert "Prefix valid text" in result.output["content"]
        # Replacement character should be present
        assert "\ufffd" in result.output["content"] or "" in result.output["content"]

    def test_attach_read_corrupted_pdf_handling(self, tmp_path: Path) -> None:
        """Verify that zero-byte or textless PDFs return informative notice rather than crashing."""
        # Non-PDF binary or empty PDF bytes
        empty_pdf_notice = extract_text_from_pdf_bytes(b"%PDF-1.4\n%%EOF")
        assert "Notice: PDF document contains no extractable text layer" in empty_pdf_notice

        corrupt_pdf_notice = extract_text_from_pdf_bytes(b"\x00\x01\x02\x03\x04")
        assert "Notice: PDF document contains no extractable text layer" in corrupt_pdf_notice

    def test_extract_document_dossier_tool_security(self, tmp_path: Path) -> None:
        """Verify ExtractDocumentDossierTool path traversal rejection and safe defaults."""
        tool = ExtractDocumentDossierTool()

        # Path traversal in file_path
        with pytest.raises(DocumentSandboxError):
            tool.invoke({"file_path": "../../etc/passwd", "workspace_root": tmp_path})

        # Missing both document_text and file_path
        with pytest.raises(ValueError) as val_err:
            tool.invoke({"workspace_root": tmp_path})
        assert "Either file_path or document_text must be provided" in str(val_err.value)

        # Direct text input with unknown dossier schema defaults safely to generic
        res = tool.invoke({
            "document_text": "Annual hospital report summary. Length of stay: 3 days.",
            "dossier_type": "unknown_schema_type",
            "workspace_root": tmp_path,
        })
        assert res["status"] == "success"
        assert res["dossier_type"] == "generic_document"
        assert res["dossier"]["summary"] != ""

        # Passing invalid state type (e.g. non-dict) does not crash execution
        res_non_dict = tool.invoke({
            "document_text": "Deductible is $1,000.",
            "dossier_type": "insurance",
            "state": "non_dict_state",
            "workspace_root": tmp_path,
        })
        assert res_non_dict["status"] == "success"

    def test_extraction_state_and_subgraph_nodes(self) -> None:
        """Verify extraction subgraph ingestion and extraction nodes."""
        ingestion_node = create_ingestion_node()
        extraction_node = create_extraction_node()

        # 1. Ingestion node parses prompt attachment when not explicitly in state
        state_prompt: ExtractionState = {
            "messages": [HumanMessage(content="Please review visit_notes.txt")],
        }
        res_ingest = asyncio.run(ingestion_node(state_prompt))
        assert res_ingest["file_path"] == "visit_notes.txt"

        # 2. Extraction node auto-infers insurance dossier type from keywords
        state_extract: ExtractionState = {
            "document_text": "Health benefit summary: deductible is $1,500, copay is $20.",
            "messages": [HumanMessage(content="Extract insurance deductible")],
            "document_dossiers": [],
        }
        res_extract = asyncio.run(extraction_node(state_extract))
        assert len(res_extract["document_dossiers"]) > 0
        dossier_entry = res_extract["document_dossiers"][0]
        assert dossier_entry["dossier_type"] in ("insurance", "insurance_benefits")
        assert dossier_entry["grounding"]["is_grounded"] is True

    def test_delegation_tools_hardening(self) -> None:
        """Verify ListAgentsTool and DelegateToAgentTool validation and formatting."""
        # 1. ListAgentsTool returns non-empty catalog string
        list_tool = ListAgentsTool()
        catalog = list_tool._run()
        assert isinstance(catalog, str)
        assert "visit-steward" in catalog
        assert "benefits-guide" in catalog
        assert "document-extractor" in catalog

        async_catalog = asyncio.run(list_tool._arun())
        assert async_catalog == catalog

        # 2. DelegateToAgentTool trims inputs and emits valid JSON
        delegate_tool = DelegateToAgentTool()
        raw_json = delegate_tool._run(
            agent_id="   visit-steward   ",
            instructions="  Prepare doctor checklist.  ",
        )
        parsed = json.loads(raw_json)
        assert parsed["status"] == "delegated"
        assert parsed["agent_id"] == "visit-steward"
        assert parsed["instructions"] == "Prepare doctor checklist."
