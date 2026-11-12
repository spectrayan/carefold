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

"""Re-export shim combining yarvelle_core extraction package with Carefold domain dossiers and sanitizer."""

from __future__ import annotations

from typing import Any

from yarvelle_core.workflows.subgraphs.extraction import *  # noqa: F401, F403
import yarvelle_core.workflows.subgraphs.extraction as _target_module

from carefold.clinical.sanitizer import (  # noqa: F401
    DEFAULT_MRN_TAG,
    PIISanitizer,
    mask_pii,
    sanitize_pii,
    sanitize_pii_with_metadata,
)
from carefold.dossiers import ClinicalVisitDossier, InsuranceBenefitsDossier  # noqa: F401


def __getattr__(name: str) -> Any:
    return getattr(_target_module, name)


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(dir(_target_module)))
