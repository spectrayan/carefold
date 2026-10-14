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

"""Structured document extraction dossiers for Carefold (Requirement R2).

Implements typed Pydantic models for structured clinical and insurance
data extraction from ingested attachments, supporting strict validation,
convenience serialization methods, and grounding verification.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class BaseDossier(BaseModel):
    """Base class for all extraction dossiers providing shared serialization."""

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        validate_assignment=True,
    )

    @property
    def dossier_type(self) -> str:
        """Normalized identifier for the dossier model."""
        return "base"

    def to_dict(self, include_type: bool = False, **kwargs: Any) -> Dict[str, Any]:
        """Serialize dossier model to a Python dictionary.

        Args:
            include_type: If True, includes 'dossier_type' key in the output.
            **kwargs: Additional keyword arguments passed to model_dump.

        Returns:
            Dict[str, Any] representation of the model.
        """
        data = self.model_dump(**kwargs)
        if include_type:
            data["dossier_type"] = self.dossier_type
        return data

    def to_json(self, indent: Optional[int] = None, **kwargs: Any) -> str:
        """Serialize dossier model to a JSON string.

        Args:
            indent: Indentation spaces for formatted JSON output.
            **kwargs: Additional keyword arguments passed to model_dump_json.

        Returns:
            JSON-formatted string representation.
        """
        return self.model_dump_json(indent=indent, **kwargs)

    def extract_numerical_strings(self) -> List[str]:
        """Extract all string values containing numeric digits for grounding checks.

        Returns:
            List of string values containing one or more digits.
        """
        numerical_values: List[str] = []
        payload = self.model_dump()

        def _traverse(val: Any) -> None:
            if isinstance(val, str):
                if re.search(r"\d", val):
                    numerical_values.append(val)
            elif isinstance(val, list):
                for item in val:
                    _traverse(item)
            elif isinstance(val, dict):
                for v in val.values():
                    _traverse(v)

        _traverse(payload)
        return numerical_values


class InsuranceBenefitsDossier(BaseDossier):
    """Structured extraction dossier for health insurance summary and EOB documents."""

    deductible: str = Field(
        default="",
        description="Annual deductible amount (e.g. '$1,500').",
    )
    copays: Dict[str, str] = Field(
        default_factory=dict,
        description="Copayment amounts mapped by service type (e.g. {'primary_care': '$25'}).",
    )
    coinsurance: str = Field(
        default="",
        description="Coinsurance cost-sharing percentage (e.g. '20%').",
    )
    out_of_pocket_maximum: str = Field(
        default="",
        description="Maximum annual out-of-pocket liability (e.g. '$6,000').",
    )
    in_out_network_rules: str = Field(
        default="",
        description="Rules, coverage rates, and referral requirements for in- vs out-of-network.",
    )
    prior_authorization_flags: List[str] = Field(
        default_factory=list,
        description="List of medical procedures or services requiring pre-authorization.",
    )

    @property
    def dossier_type(self) -> str:
        return "insurance_benefits"


class ClinicalVisitDossier(BaseDossier):
    """Structured extraction dossier for physician encounter notes and visit summaries."""

    reason_for_visit: str = Field(
        default="",
        description="Primary clinical chief complaint or reason for encounter.",
    )
    physician_instructions: List[str] = Field(
        default_factory=list,
        description="Care instructions, lifestyle advice, or physician directives.",
    )
    follow_up_timeline: str = Field(
        default="",
        description="Scheduled follow-up timing or interval (e.g. '4 weeks').",
    )
    questions_to_ask: List[str] = Field(
        default_factory=list,
        description="Suggested or patient-prepared questions for future appointments.",
    )

    @property
    def dossier_type(self) -> str:
        return "clinical_visit"


class GenericDocumentDossier(BaseDossier):
    """Fallback extraction dossier for unclassified health and administrative documents."""

    summary: str = Field(
        default="",
        description="Executive summary or high-level document synthesis.",
    )
    key_numerical_values: Dict[str, str] = Field(
        default_factory=dict,
        description="Key extracted metrics, dates, and labeled numerical values.",
    )
    sections: List[str] = Field(
        default_factory=list,
        description="List of section headings and major content divisions.",
    )

    @property
    def dossier_type(self) -> str:
        return "generic_document"


# Union type of all structured extraction dossiers
DocumentDossier = Union[
    InsuranceBenefitsDossier,
    ClinicalVisitDossier,
    GenericDocumentDossier,
]

# Lookup registry mapping shorthand type strings to dossier classes
DOSSIER_REGISTRY: Dict[str, type[BaseDossier]] = {
    "insurance": InsuranceBenefitsDossier,
    "insurance_benefits": InsuranceBenefitsDossier,
    "clinical": ClinicalVisitDossier,
    "clinical_visit": ClinicalVisitDossier,
    "generic": GenericDocumentDossier,
    "generic_document": GenericDocumentDossier,
}


def get_dossier_cls(dossier_type: str) -> type[BaseDossier]:
    """Resolve a dossier class from a string identifier.

    Args:
        dossier_type: Type identifier (e.g. 'insurance', 'clinical', 'generic').

    Returns:
        The matching BaseDossier subclass, defaulting to GenericDocumentDossier.
    """
    normalized = dossier_type.lower().strip().replace("-", "_")
    return DOSSIER_REGISTRY.get(normalized, GenericDocumentDossier)


__all__ = [
    "BaseDossier",
    "ClinicalVisitDossier",
    "DOSSIER_REGISTRY",
    "DocumentDossier",
    "GenericDocumentDossier",
    "InsuranceBenefitsDossier",
    "get_dossier_cls",
]
