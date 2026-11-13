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

"""Carefold CFD error catalog registration and typed clinical/tool error helpers (#340)."""

from __future__ import annotations

from pathlib import Path
from typing import List

from yarvelle_core.errors import (
    PROBLEM_JSON_MEDIA_TYPE,
    ErrorCodeSpec,
    YarvelleError,
    ensure_yarvelle_error,
    get_error_catalog,
    register_pack_error_catalog,
)

CAREFOLD_ERROR_PREFIX = "CFD"
CAREFOLD_ERROR_PACK_ID = "health"
CAREFOLD_ERROR_TYPE_BASE_URI = "https://errors.carefold.dev"
CAREFOLD_ERRORS_YAML_PATH = Path(__file__).resolve().parent / "resources" / "errors.yaml"


def register_carefold_error_catalog() -> List[ErrorCodeSpec]:
    """Idempotently registers Carefold's ``CFD-XXX-YYY`` catalog with ``yarvelle_core``."""
    return register_pack_error_catalog(
        CAREFOLD_ERROR_PACK_ID,
        CAREFOLD_ERROR_PREFIX,
        CAREFOLD_ERRORS_YAML_PATH,
        type_base_uri=CAREFOLD_ERROR_TYPE_BASE_URI,
    )


class CarefoldToolError(YarvelleError, ValueError):
    """Typed ``YarvelleError`` that also satisfies ``ValueError`` callers in direct tool invocations."""


__all__ = [
    "CAREFOLD_ERRORS_YAML_PATH",
    "CAREFOLD_ERROR_PACK_ID",
    "CAREFOLD_ERROR_PREFIX",
    "CAREFOLD_ERROR_TYPE_BASE_URI",
    "CarefoldToolError",
    "ErrorCodeSpec",
    "PROBLEM_JSON_MEDIA_TYPE",
    "YarvelleError",
    "ensure_yarvelle_error",
    "get_error_catalog",
    "register_carefold_error_catalog",
]
