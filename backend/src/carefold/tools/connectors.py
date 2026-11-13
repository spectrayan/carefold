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

"""Async execution handlers for Carefold connector and clinical import tools (#338).

Declarative ToolSpec metadata lives in `carefold/resources/tools/`; legacy
`SPEC_*` attributes resolve lazily from the declarative loader.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping

import httpx

from carefold.errors import CarefoldToolError, YarvelleError
from yarvelle_core.db.session import get_session_factory

logger = logging.getLogger("carefold.tools.connectors")

_SPEC_ATTRS: Dict[str, str] = {
    "SPEC_WITHINGS": "withings_latest_vitals",
    "SPEC_EPIC": "epic_smart_search_records",
    "SPEC_SCHOOL_ICS": "sync_school_ics",
    "SPEC_ZOCDOC": "zocdoc_book_appointment",
    "SPEC_SHC": "verify_smart_health_card",
}


async def _invoke_connector_tool(connector: Any, tool_name: str, args: Any, ctx: Any) -> Any:
    if isinstance(ctx, Mapping) and not isinstance(args, Mapping):
        args, ctx = ctx, args
    clean_args = dict(args) if isinstance(args, Mapping) else {}
    for tool_spec in connector.tools():
        if tool_spec.name == tool_name and tool_spec.handler is not None:
            try:
                return await tool_spec.handler(ctx, clean_args)
            except TypeError:
                return await tool_spec.handler(clean_args, ctx)
    raise RuntimeError(f"Connector '{connector.manifest.id}' does not expose handler for '{tool_name}'.")


async def execute_withings_latest_vitals(args: Dict[str, Any], ctx: Any = None) -> Any:
    """Retrieves latest synchronized Withings vital sign observations."""
    from carefold.connectors.withings import WithingsConnector

    return await _invoke_connector_tool(WithingsConnector(), "withings_latest_vitals", args or {}, ctx)


async def execute_epic_smart_search_records(args: Dict[str, Any], ctx: Any = None) -> Any:
    """Searches read-only USCDI FHIR R4 clinical records from Epic MyChart."""
    from carefold.connectors.epic_smart import EpicSmartConnector

    return await _invoke_connector_tool(EpicSmartConnector(), "epic_smart_search_records", args or {}, ctx)


async def execute_sync_school_ics(args: Dict[str, Any], ctx: Any = None) -> Any:
    """Synchronizes a child school RFC 5545 .ics calendar feed into profile appointments."""
    if isinstance(ctx, Mapping) and not isinstance(args, Mapping):
        args, ctx = ctx, args
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        raise CarefoldToolError("YRV-300-014", detail="Missing profile_id in ToolContext")
    clean_profile_id = profile_id.strip()

    safe_args = dict(args) if isinstance(args, Mapping) else {}
    feed_id = str(safe_args.get("feed_id") or "").strip()
    if not feed_id:
        raise CarefoldToolError("CFD-100-008", detail="Missing required parameter 'feed_id' for sync_school_ics")

    raw_ics_content = safe_args.get("raw_ics_content")
    if raw_ics_content is not None:
        raw_ics_content = str(raw_ics_content)

    from carefold.clinical.school_ics import sync_school_ics_feed

    ctx_extra = getattr(ctx, "extra", None) or {}
    session_factory = (
        getattr(ctx, "session_factory", None)
        or (ctx_extra.get("session_factory") if isinstance(ctx_extra, Mapping) else None)
        or get_session_factory()
    )
    try:
        async with session_factory() as session:
            return await sync_school_ics_feed(
                session=session,
                profile_id=clean_profile_id,
                feed_id=feed_id,
                raw_ics_content=raw_ics_content,
            )
    except CarefoldToolError:
        raise
    except httpx.HTTPError as exc:
        raise CarefoldToolError(
            "CFD-600-003",
            detail="Failed to fetch school calendar ICS feed from upstream server.",
            cause=exc,
        ) from exc
    except ValueError as exc:
        msg = str(exc)
        err_code = "CFD-500-005" if "not found" in msg.lower() else "CFD-100-008"
        raise CarefoldToolError(err_code, detail=msg, cause=exc) from exc


async def execute_zocdoc_book_appointment(args: Dict[str, Any], ctx: Any = None) -> Any:
    """Books an external clinical appointment on Zocdoc."""
    from carefold.connectors.zocdoc import ZocdocConnector

    return await _invoke_connector_tool(ZocdocConnector(), "zocdoc_book_appointment", args or {}, ctx)


async def execute_verify_smart_health_card(args: Dict[str, Any], ctx: Any = None) -> Any:
    """Verifies a W3C/HL7 SMART Health Card using ES256 JWS signature checks."""
    if isinstance(ctx, Mapping) and not isinstance(args, Mapping):
        args, ctx = ctx, args
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        raise CarefoldToolError("YRV-300-014", detail="Missing profile_id in ToolContext")
    from carefold.importers.smart_health_card import verify_and_parse_smart_health_card

    safe_args = dict(args) if isinstance(args, Mapping) else {}
    try:
        return verify_and_parse_smart_health_card(
            raw_content=str(safe_args.get("content", "")),
            source_name=str(safe_args.get("source_name", "SMART Health Card")),
        )
    except ValueError as exc:
        raise CarefoldToolError("CFD-100-006", detail=str(exc), cause=exc) from exc


def __getattr__(name: str) -> Any:
    if name in _SPEC_ATTRS:
        from carefold.tools import get_health_tool_spec

        return get_health_tool_spec(_SPEC_ATTRS[name])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
