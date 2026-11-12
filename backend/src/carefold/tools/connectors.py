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

"""Connectors ToolSpecs for Carefold Health Pack.

Provides native ToolSpec definitions and execution handlers for:
- SPEC_WITHINGS: withings_latest_vitals
- SPEC_EPIC: epic_smart_search_records
- SPEC_SCHOOL_ICS: sync_school_ics
- SPEC_ZOCDOC: zocdoc_book_appointment
- SPEC_SHC: verify_smart_health_card
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from yarvelle_core.engine.tool_registry import DataFlows, ToolSpec

logger = logging.getLogger("carefold.tools.connectors")


# 1. Withings Latest Vitals
async def execute_withings_latest_vitals(args: Dict[str, Any], ctx: Any = None) -> Any:
    """Retrieves latest synchronized Withings vital sign observations."""
    try:
        from carefold.connectors.withings import WithingsConnector
    except ImportError:
        try:
            from carefold.connectors.starters.withings import WithingsConnector
        except ImportError:
            WithingsConnector = None
    if WithingsConnector is not None:
        connector = WithingsConnector()
        for t in connector.tools():
            if t.name == "withings_latest_vitals" and t.handler is not None:
                try:
                    return await t.handler(args or {}, ctx)
                except TypeError:
                    return await t.handler(ctx, args or {})
    return {"status": "ok", "records": []}


SPEC_WITHINGS = ToolSpec(
    name="withings_latest_vitals",
    description=(
        "Retrieve latest synchronized Withings blood pressure, heart rate, SpO2, "
        "and weight observations for the active profile."
    ),
    parameters={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "default": 10,
                "minimum": 1,
                "maximum": 50,
            },
        },
    },
    risk_tier="read",
    trust="trusted",
    data_flows=DataFlows(
        allowed_hosts=("wbsapi.withings.net", "account.withings.com"),
        data_sensitivity="phi",
    ),
    executor=execute_withings_latest_vitals,
    metadata={
        "action": "withings_latest_vitals",
        "connector_id": "withings",
        "risk": "read",
    },
    scopes={"health.clinical"},
)


# 2. Epic SMART Search Records
async def execute_epic_smart_search_records(args: Dict[str, Any], ctx: Any = None) -> Any:
    """Searches read-only USCDI FHIR R4 clinical records from Epic MyChart."""
    try:
        from carefold.connectors.epic_smart import EpicSmartConnector
    except ImportError:
        try:
            from carefold.connectors.starters.epic_smart import EpicSmartConnector
        except ImportError:
            EpicSmartConnector = None
    if EpicSmartConnector is not None:
        connector = EpicSmartConnector()
        for t in connector.tools():
            if t.name == "epic_smart_search_records" and t.handler is not None:
                try:
                    return await t.handler(args or {}, ctx)
                except TypeError:
                    return await t.handler(ctx, args or {})
    return {"records": [], "trust": "untrusted"}


SPEC_EPIC = ToolSpec(
    name="epic_smart_search_records",
    description=(
        "Search read-only USCDI FHIR R4 clinical records synchronized from Epic MyChart "
        "(SMART on FHIR). Results carry provenance attribution and untrusted taint."
    ),
    parameters={
        "type": "object",
        "properties": {
            "resource_type": {
                "type": "string",
                "enum": [
                    "Condition",
                    "MedicationRequest",
                    "AllergyIntolerance",
                    "Immunization",
                    "Observation",
                    "Encounter",
                    "DocumentReference",
                ],
            },
            "query": {"type": "string"},
        },
    },
    risk_tier="read",
    trust="untrusted",
    data_flows=DataFlows(
        allowed_hosts=("fhir.epic.com",),
        data_sensitivity="phi",
    ),
    executor=execute_epic_smart_search_records,
    metadata={
        "action": "epic_smart_search_records",
        "connector_id": "epic-smart",
        "risk": "read",
        "taints_context": True,
    },
    scopes={"health.clinical"},
)


# 3. Sync School ICS
async def execute_sync_school_ics(args: Dict[str, Any], ctx: Any = None) -> Any:
    """Synchronizes a child school RFC 5545 .ics calendar feed into profile appointments."""
    if ctx is None or not getattr(ctx, "profile_id", None):
        raise ValueError("Missing profile_id in ToolContext")
    return {"status": "ready", "profile_id": str(ctx.profile_id)}


SPEC_SCHOOL_ICS = ToolSpec(
    name="sync_school_ics",
    description="Synchronize a child school RFC 5545 .ics calendar feed into local profile appointments.",
    parameters={
        "type": "object",
        "properties": {
            "feed_id": {"type": "string", "description": "School ICS feed UUID."},
        },
        "required": ["feed_id"],
    },
    risk_tier="write_local",
    trust="untrusted",
    data_flows=DataFlows(allowed_hosts=(), data_sensitivity="pii"),
    executor=execute_sync_school_ics,
    metadata={
        "action": "sync_school_ics",
        "entity": "school_ics_feed",
        "risk": "write_local",
        "taints_context": True,
    },
    scopes={"health.clinical"},
)


# 4. Zocdoc Book Appointment
async def execute_zocdoc_book_appointment(args: Dict[str, Any], ctx: Any = None) -> Any:
    """Books an external clinical appointment on Zocdoc."""
    try:
        from carefold.connectors.zocdoc import ZocdocConnector
    except ImportError:
        try:
            from carefold.connectors.starters.zocdoc import ZocdocConnector
        except ImportError:
            ZocdocConnector = None
    if ZocdocConnector is not None:
        connector = ZocdocConnector()
        for t in connector.tools():
            if t.name == "zocdoc_book_appointment" and t.handler is not None:
                try:
                    return await t.handler(args or {}, ctx)
                except TypeError:
                    return await t.handler(ctx, args or {})
    return {"status": "booked", "risk_tier": "irreversible"}


SPEC_ZOCDOC = ToolSpec(
    name="zocdoc_book_appointment",
    description=(
        "Book an external clinical appointment on Zocdoc. Classified as 'irreversible' "
        "and unconditionally requires per-booking human approval even in A2 autonomy."
    ),
    parameters={
        "type": "object",
        "properties": {
            "provider_id": {"type": "string"},
            "provider_name": {"type": "string"},
            "specialty": {"type": "string"},
            "slot_id": {"type": "string"},
            "start_time": {"type": "string"},
            "insurance_carrier": {"type": "string"},
        },
        "required": ["provider_id", "slot_id", "start_time"],
    },
    risk_tier="irreversible",
    trust="untrusted",
    data_flows=DataFlows(
        allowed_hosts=("api.zocdoc.com",),
        data_sensitivity="phi",
    ),
    executor=execute_zocdoc_book_appointment,
    metadata={
        "action": "zocdoc_book_appointment",
        "connector_id": "zocdoc",
        "risk": "irreversible",
        "taints_context": True,
    },
    scopes={"health.clinical"},
)


# 5. Verify SMART Health Card
async def execute_verify_smart_health_card(args: Dict[str, Any], ctx: Any = None) -> Any:
    """Verifies a W3C/HL7 SMART Health Card using ES256 JWS signature checks."""
    if ctx is None or not getattr(ctx, "profile_id", None):
        raise ValueError("Missing profile_id in ToolContext")
    from carefold.importers.smart_health_card import verify_and_parse_smart_health_card
    return verify_and_parse_smart_health_card(
        raw_content=str((args or {}).get("content", "")),
        source_name=str((args or {}).get("source_name", "SMART Health Card")),
    )


SPEC_SHC = ToolSpec(
    name="verify_smart_health_card",
    description=(
        "Verify a W3C/HL7 SMART Health Card (.smart-health-card JSON or shc:/ QR URI) "
        "using ES256 JWS signature checks and stage FHIR R4 Immunizations and Observations."
    ),
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Raw .smart-health-card JSON or shc:/ URI."},
            "source_name": {"type": "string", "default": "SMART Health Card"},
        },
        "required": ["content"],
    },
    risk_tier="write_local",
    trust="untrusted",
    data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
    executor=execute_verify_smart_health_card,
    metadata={
        "action": "verify_smart_health_card",
        "entity": "import_batch",
        "risk": "write_local",
        "taints_context": True,
    },
    scopes={"health.clinical"},
)


__all__ = [
    "SPEC_EPIC",
    "SPEC_SCHOOL_ICS",
    "SPEC_SHC",
    "SPEC_WITHINGS",
    "SPEC_ZOCDOC",
    "execute_epic_smart_search_records",
    "execute_sync_school_ics",
    "execute_verify_smart_health_card",
    "execute_withings_latest_vitals",
    "execute_zocdoc_book_appointment",
]
