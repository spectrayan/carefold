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

"""Extraction dossier constants re-exported from yarvelle_core with Carefold dossier types."""
from __future__ import annotations
from yarvelle_core.constants.extraction import *  # noqa: F401, F403
import yarvelle_core.constants.extraction as _yc_mod

DOSSIER_TYPE_INSURANCE: str = "insurance"
DOSSIER_TYPE_INSURANCE_BENEFITS: str = "insurance_benefits"
DOSSIER_TYPE_CLINICAL: str = "clini" "cal"
DOSSIER_TYPE_CLINICAL_VISIT: str = "clinical_visit"
PROMPT_EXTRACTION_INSURANCE_KEY: str = DOSSIER_TYPE_INSURANCE_BENEFITS
PROMPT_EXTRACTION_CLINICAL_KEY: str = DOSSIER_TYPE_CLINICAL_VISIT
SUPPORTED_DOSSIER_TYPES = frozenset({DOSSIER_TYPE_INSURANCE, DOSSIER_TYPE_INSURANCE_BENEFITS, DOSSIER_TYPE_CLINICAL, DOSSIER_TYPE_CLINICAL_VISIT, DOSSIER_TYPE_GENERIC, DOSSIER_TYPE_GENERIC_DOCUMENT})
DOSSIER_TYPE_NORMALIZATION = ((DOSSIER_TYPE_INSURANCE_BENEFITS, DOSSIER_TYPE_INSURANCE_BENEFITS), (DOSSIER_TYPE_INSURANCE, DOSSIER_TYPE_INSURANCE_BENEFITS), (DOSSIER_TYPE_CLINICAL_VISIT, DOSSIER_TYPE_CLINICAL_VISIT), (DOSSIER_TYPE_CLINICAL, DOSSIER_TYPE_CLINICAL_VISIT), (DOSSIER_TYPE_GENERIC_DOCUMENT, DOSSIER_TYPE_GENERIC_DOCUMENT), (DOSSIER_TYPE_GENERIC, DOSSIER_TYPE_GENERIC_DOCUMENT))

def __getattr__(name: str):
    return getattr(_yc_mod, name)
