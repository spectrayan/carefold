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

"""Closed tool: generate_prep_pack routed via McpDatabaseToolbox (AU-33, AU-34, #344)."""

from __future__ import annotations

import logging
from typing import Any, Dict

from carefold.clinical.db_hooks import execute_governed_db_operation
from yarvelle_core.db.session import get_session_factory  # noqa: F401
from yarvelle_core.schemas.tool import ToolResult

logger = logging.getLogger("carefold.tools.prep_pack")


async def execute_generate_prep_pack(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Executes consultation prep pack compilation and persistence via McpDatabaseToolbox."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("generate_prep_pack rejected: invalid or missing profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed generate_prep_pack.",
            error_code="YRV-300-014",
            retryable=False,
        )
    clean_profile_id = profile_id.strip()

    safe_args = args if isinstance(args, dict) else {}
    user_id = getattr(ctx, "user_id", None) if ctx is not None else None

    try:
        res = await execute_governed_db_operation(
            "tool.generate_prep_pack",
            {
                "appointment_id": safe_args.get("appointment_id"),
                "specialty": safe_args.get("specialty"),
                "visit_reason": safe_args.get("visit_reason"),
                "doctor_questions": safe_args.get("doctor_questions"),
            },
            ctx=ctx,
            profile_id=clean_profile_id,
            user_id=user_id,
            risk_tier="write_local",
            caller_module_name=__name__,
        )
        return ToolResult(
            success=True,
            output=res,
            metadata={
                "entity": "note",
                "id": res["note_id"],
                "undoable": True,
                "risk": "write_local",
            },
        )
    except ValueError as val_err:
        logger.warning("generate_prep_pack validation error: %s", val_err)
        msg = str(val_err)
        err_code = "CFD-500-002" if "not found" in msg.lower() else "CFD-100-011"
        return ToolResult(
            success=False,
            output=None,
            error=msg,
            error_code=err_code,
            retryable=False,
        )
    except Exception as exc:
        logger.exception("generate_prep_pack failed: %s", exc)
        return ToolResult(
            success=False,
            output=None,
            error="Failed to generate appointment preparation pack.",
            error_code="CFD-900-002",
            retryable=False,
        )


def __getattr__(name: str) -> Any:
    if name == "SPEC":
        from carefold.tools import get_health_tool_spec

        return get_health_tool_spec("generate_prep_pack")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["SPEC", "execute_generate_prep_pack"]
