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

"""Carefold tools package (re-exporting core tools and native health ToolSpec definitions)."""

from __future__ import annotations

from typing import Any, List

from yarvelle_core.engine.tool_registry import ToolSpec
from yarvelle_core.tools import *  # noqa: F401, F403
import yarvelle_core.tools as _core_tools


from carefold.tools.appointments import (
    SPEC_CREATE as SPEC_CREATE_APPOINTMENT,
    SPEC_LIST as SPEC_LIST_APPOINTMENTS,
    SPEC_UPDATE_STATUS as SPEC_UPDATE_APPOINTMENT_STATUS,
)
from carefold.tools.connectors import (
    SPEC_EPIC,
    SPEC_SCHOOL_ICS,
    SPEC_SHC,
    SPEC_WITHINGS,
    SPEC_ZOCDOC,
)
from carefold.tools.imports import (
    SPEC_COMMIT as SPEC_COMMIT_CLINICAL_IMPORT,
    SPEC_STAGE as SPEC_STAGE_CLINICAL_IMPORT,
)
from carefold.tools.notes import SPEC as SPEC_CREATE_TYPED_NOTE
from carefold.tools.prep_pack import SPEC as SPEC_GENERATE_PREP_PACK
from carefold.tools.preventive import (
    SPEC_CHECK as SPEC_CHECK_PREVENTIVE_CARE,
    SPEC_UPDATE as SPEC_UPDATE_PREVENTIVE_STATUS,
)
from carefold.tools.record_vitals import SPEC as SPEC_RECORD_VITALS
from carefold.tools.school_forms import (
    SPEC_CREATE as SPEC_CREATE_SCHOOL_FORM,
    SPEC_LIST as SPEC_LIST_SCHOOL_FORMS,
)
from carefold.tools.fhir_tools import (
    SPEC_GET_OBSERVATION_TRENDS as SPEC_FHIR_GET_OBSERVATION_TRENDS,
    SPEC_GET_PATIENT_SUMMARY as SPEC_FHIR_GET_PATIENT_SUMMARY,
    SPEC_SEARCH_RESOURCES as SPEC_FHIR_SEARCH_RESOURCES,
)

HEALTH_TOOL_SPECS: List[ToolSpec] = [
    SPEC_RECORD_VITALS,
    SPEC_CREATE_APPOINTMENT,
    SPEC_LIST_APPOINTMENTS,
    SPEC_UPDATE_APPOINTMENT_STATUS,
    SPEC_GENERATE_PREP_PACK,
    SPEC_CREATE_TYPED_NOTE,
    SPEC_CHECK_PREVENTIVE_CARE,
    SPEC_UPDATE_PREVENTIVE_STATUS,
    SPEC_STAGE_CLINICAL_IMPORT,
    SPEC_COMMIT_CLINICAL_IMPORT,
    SPEC_CREATE_SCHOOL_FORM,
    SPEC_LIST_SCHOOL_FORMS,
    SPEC_WITHINGS,
    SPEC_EPIC,
    SPEC_SCHOOL_ICS,
    SPEC_ZOCDOC,
    SPEC_SHC,
    SPEC_FHIR_SEARCH_RESOURCES,
    SPEC_FHIR_GET_PATIENT_SUMMARY,
    SPEC_FHIR_GET_OBSERVATION_TRENDS,
]


def get_health_tool_specs() -> List[ToolSpec]:
    """Returns the 20 clinical and health ToolSpecs defined natively in carefold."""
    return list(HEALTH_TOOL_SPECS)


__all__ = [
    "HEALTH_TOOL_SPECS",
    "SPEC_CHECK_PREVENTIVE_CARE",
    "SPEC_COMMIT_CLINICAL_IMPORT",
    "SPEC_CREATE_APPOINTMENT",
    "SPEC_CREATE_SCHOOL_FORM",
    "SPEC_CREATE_TYPED_NOTE",
    "SPEC_EPIC",
    "SPEC_FHIR_GET_OBSERVATION_TRENDS",
    "SPEC_FHIR_GET_PATIENT_SUMMARY",
    "SPEC_FHIR_SEARCH_RESOURCES",
    "SPEC_GENERATE_PREP_PACK",
    "SPEC_LIST_APPOINTMENTS",
    "SPEC_LIST_SCHOOL_FORMS",
    "SPEC_RECORD_VITALS",
    "SPEC_SCHOOL_ICS",
    "SPEC_SHC",
    "SPEC_STAGE_CLINICAL_IMPORT",
    "SPEC_UPDATE_APPOINTMENT_STATUS",
    "SPEC_UPDATE_PREVENTIVE_STATUS",
    "SPEC_WITHINGS",
    "SPEC_ZOCDOC",
    "ToolSpec",
    "get_health_tool_specs",
]
