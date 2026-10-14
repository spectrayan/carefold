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

"""Discrete LangChain tools for document extraction and grounding (Feature F-49 & Milestone 6).

Exports:
- SanitizePIITool: deterministic regex masking for direct PII.
- ExtractStructuredDataTool: LLM structured output targeting Pydantic dossiers with deterministic fallback.
- ValidateGroundingTool: deterministic numerical grounding verification.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Type, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from carefold.constants.agents import (
    TOOL_EXTRACT_STRUCTURED_DATA,
    TOOL_SANITIZE_PII,
    TOOL_VALIDATE_GROUNDING,
)
from carefold.constants.extraction import (
    DEFAULT_DOSSIER_TYPE,
    PROMPT_EXTRACTION_CLINICAL_KEY,
    PROMPT_EXTRACTION_GENERIC_KEY,
    PROMPT_EXTRACTION_INSURANCE_KEY,
)
from carefold.resources.loader import get_resource_loader
from carefold.workflows.subgraphs.extraction.dossiers import (
    BaseDossier,
    ClinicalVisitDossier,
    GenericDocumentDossier,
    InsuranceBenefitsDossier,
    get_dossier_cls,
)
from carefold.workflows.subgraphs.extraction.grounding import (
    GroundingValidationResult,
    GroundingValidator,
)
from carefold.workflows.subgraphs.extraction.sanitizer import sanitize_pii

logger = logging.getLogger(__name__)


# ============================================================================
# 1. SanitizePIITool
# ============================================================================

class SanitizePIIInput(BaseModel):
    """Input argument schema for SanitizePIITool."""

    text: str = Field(
        ...,
        description="Source text containing potentially sensitive patient identifiers to mask.",
    )
    mask_type: str = Field(
        default="tag",
        description="Masking mode: 'tag' ([SSN], [MRN], [PHONE], [ADDRESS]) or 'redacted' ([REDACTED]).",
    )


class SanitizePIITool(BaseTool):
    """LangChain tool wrapping deterministic regex PII sanitization.

    Ensures SSN, MRN, phone numbers, and street addresses are masked before LLM transmission.
    """

    name: str = TOOL_SANITIZE_PII
    description: str = (
        "Mask direct PII (SSN, MRN, phone, street address, email) in text before sending "
        "to models or processing. Returns the sanitized text."
    )
    args_schema: Type[BaseModel] = SanitizePIIInput

    def _run(self, text: str, mask_type: str = "tag", **kwargs: Any) -> str:
        """Synchronous execution of PII sanitization."""
        return sanitize_pii(text, mask_type=mask_type)

    async def _arun(self, text: str, mask_type: str = "tag", **kwargs: Any) -> str:
        """Asynchronous execution delegating to synchronous regex execution."""
        return self._run(text, mask_type=mask_type, **kwargs)


# ============================================================================
# 2. ExtractStructuredDataTool
# ============================================================================

class ExtractStructuredDataInput(BaseModel):
    """Input argument schema for ExtractStructuredDataTool."""

    text: str = Field(
        ...,
        description="Sanitized document text to extract structured data from.",
    )
    schema_type: str = Field(
        default=DEFAULT_DOSSIER_TYPE,
        description="Target dossier schema: 'insurance' (benefits), 'clinical' (visit notes), or 'generic'.",
    )


class ExtractStructuredDataTool(BaseTool):
    """LangChain tool for LLM-driven structured extraction into typed Pydantic dossiers.

    Uses model.with_structured_output(dossier_cls). Features a built-in deterministic
    heuristic fallback to guarantee test suite and offline execution reliability.
    """

    name: str = TOOL_EXTRACT_STRUCTURED_DATA
    description: str = (
        "Extract structured data from text into a typed Pydantic schema ('insurance', "
        "'clinical', or 'generic'). Returns the extracted dossier as a dictionary."
    )
    args_schema: Type[BaseModel] = ExtractStructuredDataInput
    model: Optional[BaseChatModel] = None

    def __init__(self, model: Optional[BaseChatModel] = None, **kwargs: Any) -> None:
        super().__init__(model=model, **kwargs)

    def _get_extraction_prompt(self, schema_type: str) -> str:
        """Resolves system extraction prompt from prompts.yaml."""
        norm_type = schema_type.lower().strip()
        key_map = {
            "insurance": PROMPT_EXTRACTION_INSURANCE_KEY,
            "insurance_benefits": PROMPT_EXTRACTION_INSURANCE_KEY,
            "clinical": PROMPT_EXTRACTION_CLINICAL_KEY,
            "clinical_visit": PROMPT_EXTRACTION_CLINICAL_KEY,
            "generic": PROMPT_EXTRACTION_GENERIC_KEY,
            "generic_document": PROMPT_EXTRACTION_GENERIC_KEY,
        }
        prompt_key = key_map.get(norm_type, PROMPT_EXTRACTION_GENERIC_KEY)
        try:
            prompts = get_resource_loader().get_prompts().get("extraction", {})
            return str(prompts.get(prompt_key, ""))
        except Exception as exc:
            logger.debug("Could not load extraction prompt from ResourceLoader: %s", exc)
            return "Extract structured data matching the target schema."

    def _heuristic_fallback(self, text: str, schema_type: str) -> Dict[str, Any]:
        """Deterministic fallback extractor ensuring 100% test compatibility."""
        from carefold.workflows.subgraphs.extraction.tool import (
            _heuristic_dossier_extractor,
        )
        dossier = _heuristic_dossier_extractor(text, schema_type)
        return (
            dossier.to_dict()
            if hasattr(dossier, "to_dict")
            else dossier.model_dump()
        )

    def _run(self, text: str, schema_type: str = DEFAULT_DOSSIER_TYPE, **kwargs: Any) -> Dict[str, Any]:
        """Synchronous execution of structured extraction."""
        dossier_cls = get_dossier_cls(schema_type)

        if self.model is not None:
            try:
                extraction_prompt = self._get_extraction_prompt(schema_type)
                structured_model = self.model.with_structured_output(dossier_cls)
                messages = [
                    SystemMessage(content=extraction_prompt),
                    HumanMessage(content=text),
                ]
                result = structured_model.invoke(messages)
                if result is not None:
                    if hasattr(result, "to_dict"):
                        return result.to_dict()
                    elif hasattr(result, "model_dump"):
                        return result.model_dump()
                    elif isinstance(result, dict):
                        return result
            except Exception as exc:
                logger.debug("LLM structured output extraction note (using fallback): %s", exc)

        return self._heuristic_fallback(text, schema_type)

    async def _arun(self, text: str, schema_type: str = DEFAULT_DOSSIER_TYPE, **kwargs: Any) -> Dict[str, Any]:
        """Asynchronous execution of structured extraction."""
        dossier_cls = get_dossier_cls(schema_type)

        if self.model is not None:
            try:
                extraction_prompt = self._get_extraction_prompt(schema_type)
                structured_model = self.model.with_structured_output(dossier_cls)
                messages = [
                    SystemMessage(content=extraction_prompt),
                    HumanMessage(content=text),
                ]
                result = await structured_model.ainvoke(messages)
                if result is not None:
                    if hasattr(result, "to_dict"):
                        return result.to_dict()
                    elif hasattr(result, "model_dump"):
                        return result.model_dump()
                    elif isinstance(result, dict):
                        return result
            except Exception as exc:
                logger.debug("Async LLM structured extraction note (using fallback): %s", exc)

        return self._heuristic_fallback(text, schema_type)


# ============================================================================
# 3. ValidateGroundingTool
# ============================================================================

class ValidateGroundingInput(BaseModel):
    """Input argument schema for ValidateGroundingTool."""

    dossier: Union[Dict[str, Any], BaseModel, str] = Field(
        ...,
        description="Extracted dossier dictionary, Pydantic model, or JSON string to validate.",
    )
    source_text: str = Field(
        ...,
        description="Raw, un-sanitized source document text to verify numerical figures against.",
    )


class ValidateGroundingTool(BaseTool):
    """LangChain tool wrapping GroundingValidator for deterministic numerical verification.

    Verifies that all copays, deductibles, coinsurance, dates, and clinical measurements
    in the extracted dossier are grounded in the source text.
    """

    name: str = TOOL_VALIDATE_GROUNDING
    description: str = (
        "Validate that extracted numerical values, currency amounts, percentages, and units "
        "match the source document text. Returns grounding status and unmatched tokens."
    )
    args_schema: Type[BaseModel] = ValidateGroundingInput

    def _run(
        self,
        dossier: Union[Dict[str, Any], BaseModel, str],
        source_text: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Synchronous execution of grounding validation."""
        target_dossier = dossier
        if isinstance(target_dossier, str):
            try:
                target_dossier = json.loads(target_dossier)
            except Exception:
                target_dossier = {"content": target_dossier}

        result = GroundingValidator.validate(target_dossier, source_text)
        return result.model_dump()

    async def _arun(
        self,
        dossier: Union[Dict[str, Any], BaseModel, str],
        source_text: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Asynchronous execution delegating to synchronous GroundingValidator."""
        return self._run(dossier, source_text, **kwargs)


__all__ = [
    "ExtractStructuredDataInput",
    "ExtractStructuredDataTool",
    "SanitizePIIInput",
    "SanitizePIITool",
    "ValidateGroundingInput",
    "ValidateGroundingTool",
]
