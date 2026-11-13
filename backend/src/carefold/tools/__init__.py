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

"""Carefold tools package loading declarative health ToolSpecs from YAML resources (#338)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from yarvelle_core.engine.tool_registry import ToolSpec, bound_declarative_to_tool_spec
from yarvelle_core.tools import *  # noqa: F401, F403
import yarvelle_core.tools as _core_tools
from yarvelle_core.tools.spec_loader import get_tool_spec_loader, register_pack_tool_manifest

_PACK_YAML_PATH = Path(__file__).resolve().parent.parent / "pack.yaml"
_TOOLS_RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources" / "tools"

_SPEC_ALIAS_TO_TOOL_NAME: Dict[str, str] = {
    "SPEC_RECORD_VITALS": "record_vitals",
    "SPEC_CREATE_APPOINTMENT": "create_appointment",
    "SPEC_LIST_APPOINTMENTS": "list_appointments",
    "SPEC_UPDATE_APPOINTMENT_STATUS": "update_appointment_status",
    "SPEC_GENERATE_PREP_PACK": "generate_prep_pack",
    "SPEC_CREATE_TYPED_NOTE": "create_typed_note",
    "SPEC_CHECK_PREVENTIVE_CARE": "check_preventive_care",
    "SPEC_UPDATE_PREVENTIVE_STATUS": "update_preventive_status",
    "SPEC_STAGE_CLINICAL_IMPORT": "stage_clinical_import",
    "SPEC_COMMIT_CLINICAL_IMPORT": "commit_clinical_import",
    "SPEC_CREATE_SCHOOL_FORM": "create_school_form",
    "SPEC_LIST_SCHOOL_FORMS": "list_school_forms",
    "SPEC_WITHINGS": "withings_latest_vitals",
    "SPEC_EPIC": "epic_smart_search_records",
    "SPEC_SCHOOL_ICS": "sync_school_ics",
    "SPEC_ZOCDOC": "zocdoc_book_appointment",
    "SPEC_SHC": "verify_smart_health_card",
    "SPEC_FHIR_SEARCH_RESOURCES": "fhir_search_resources",
    "SPEC_FHIR_GET_PATIENT_SUMMARY": "fhir_get_patient_summary",
    "SPEC_FHIR_GET_OBSERVATION_TRENDS": "fhir_get_observation_trends",
}

_CACHED_SPECS_TUPLE: Optional[Tuple[ToolSpec, ...]] = None
_CACHED_SPECS_BY_NAME: Optional[Dict[str, ToolSpec]] = None


def _declared_pack_tool_order() -> Tuple[str, ...]:
    """Reads canonical tool ordering from pack.yaml so declarative specs match manifest order."""
    if not _PACK_YAML_PATH.is_file():
        return tuple(_SPEC_ALIAS_TO_TOOL_NAME.values())
    raw = yaml.safe_load(_PACK_YAML_PATH.read_text(encoding="utf-8")) or {}
    entries = (raw.get("provides") or {}).get("tools") or []
    ordered = [str(item["id"]).strip() for item in entries if isinstance(item, dict) and item.get("id")]
    return tuple(ordered) if ordered else tuple(_SPEC_ALIAS_TO_TOOL_NAME.values())


def _ensure_cached_health_specs() -> Tuple[Tuple[ToolSpec, ...], Dict[str, ToolSpec]]:
    global _CACHED_SPECS_TUPLE, _CACHED_SPECS_BY_NAME
    if _CACHED_SPECS_TUPLE is not None and _CACHED_SPECS_BY_NAME is not None:
        return _CACHED_SPECS_TUPLE, _CACHED_SPECS_BY_NAME

    loader = get_tool_spec_loader()
    if "health" not in loader.registered_pack_ids():
        register_pack_tool_manifest("health", _TOOLS_RESOURCES_DIR)

    by_name: Dict[str, ToolSpec] = {
        bound.spec.name: bound_declarative_to_tool_spec(bound)
        for bound in loader.load_pack_tools("health")
    }
    ordered: List[ToolSpec] = []
    seen = set()
    for tool_id in _declared_pack_tool_order():
        if tool_id in by_name:
            ordered.append(by_name[tool_id])
            seen.add(tool_id)
    for remaining in sorted(k for k in by_name if k not in seen):
        ordered.append(by_name[remaining])

    _CACHED_SPECS_TUPLE = tuple(ordered)
    _CACHED_SPECS_BY_NAME = by_name
    return _CACHED_SPECS_TUPLE, _CACHED_SPECS_BY_NAME


def get_health_tool_spec(name: str) -> ToolSpec:
    """Returns a single declarative Carefold ToolSpec by canonical tool name."""
    _, by_name = _ensure_cached_health_specs()
    clean = (name or "").strip()
    if clean not in by_name:
        raise KeyError(f"Unknown Carefold declarative tool '{name}'.")
    return by_name[clean]


def get_health_tool_specs() -> List[ToolSpec]:
    """Returns all declarative clinical, FHIR, connector, and domain API parity ToolSpecs."""
    ordered, _ = _ensure_cached_health_specs()
    return list(ordered)


def __getattr__(name: str) -> Any:
    if name == "HEALTH_TOOL_SPECS":
        return get_health_tool_specs()
    if name in _SPEC_ALIAS_TO_TOOL_NAME:
        return get_health_tool_spec(_SPEC_ALIAS_TO_TOOL_NAME[name])
    if name.startswith("SPEC_"):
        candidate = name[5:].lower()
        _, by_name = _ensure_cached_health_specs()
        if candidate in by_name:
            return by_name[candidate]
    return getattr(_core_tools, name)


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
    "get_health_tool_spec",
    "get_health_tool_specs",
]
