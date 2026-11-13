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

"""Closed tools for Preventive Care & Immunisation Engine via McpDatabaseToolbox (AU-36, #344)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterator

from carefold.clinical.db_hooks import execute_governed_db_operation
from carefold.clinical.preventive import (
    VALID_PREVENTIVE_STATUSES,
    VALID_SCHEDULE_SOURCES,
)
from yarvelle_core.db.session import get_session_factory  # noqa: F401
from yarvelle_core.schemas.tool import ToolResult
from yarvelle_core.tools.sql_ast_sandbox import SqlValidationError

logger = logging.getLogger("carefold.tools.preventive")


class PreventiveToolResult(ToolResult):
    """ToolResult subclass supporting both attribute access (.success, .output) and dict access."""

    def _as_dict(self) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "success": self.success,
            "output": self.output,
            "error": self.error,
        }
        if not self.success:
            base["code"] = self.error_code
            base["error_code"] = self.error_code
            base["retryable"] = self.retryable
        if isinstance(self.output, dict):
            for k, v in self.output.items():
                if k not in base:
                    base[k] = v
        return base

    def __getitem__(self, key: str) -> Any:
        d = self._as_dict()
        if key in d:
            return d[key]
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        return key in self._as_dict()

    def get(self, key: str, default: Any = None) -> Any:
        return self._as_dict().get(key, default)

    def keys(self) -> Any:
        return self._as_dict().keys()

    def items(self) -> Any:
        return self._as_dict().items()

    def __iter__(self) -> Iterator[str]:
        return iter(self._as_dict())


async def execute_check_preventive_care(args: Dict[str, Any], ctx: Any = None) -> PreventiveToolResult:
    """Evaluates preventive care screenings and immunisations via McpDatabaseToolbox."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("check_preventive_care rejected: missing or invalid profile_id in ToolContext")
        return PreventiveToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed check_preventive_care.",
            error_code="YRV-300-014",
            retryable=False,
        )
    clean_profile_id = profile_id.strip()

    safe_args = args if isinstance(args, dict) else {}
    schedule_source = safe_args.get("schedule_source")
    if schedule_source is not None and str(schedule_source).strip():
        clean_sched = str(schedule_source).strip().lower()
        if clean_sched not in VALID_SCHEDULE_SOURCES:
            return PreventiveToolResult(
                success=False,
                output=None,
                error=f"Invalid schedule_source '{schedule_source}'. Permitted: 'aap_2026', 'cdc'.",
                error_code="CFD-100-005",
                retryable=False,
            )
    else:
        clean_sched = None

    try:
        evaluation = await execute_governed_db_operation(
            "tool.check_preventive_care",
            {
                "schedule_source": clean_sched,
                "sex": safe_args.get("sex"),
                "category": safe_args.get("category"),
            },
            ctx=ctx,
            profile_id=clean_profile_id,
            risk_tier="read",
            caller_module_name=__name__,
        )
    except (ValueError, SqlValidationError) as exc:
        msg = str(exc)
        err_code = "CFD-500-008" if "not found" in msg.lower() else "CFD-100-005"
        return PreventiveToolResult(
            success=False,
            output=None,
            error=msg,
            error_code=err_code,
            retryable=False,
        )

    return PreventiveToolResult(success=True, output=evaluation, error=None)


async def execute_update_preventive_status(args: Dict[str, Any], ctx: Any = None) -> PreventiveToolResult:
    """Updates the status of a preventive care item via McpDatabaseToolbox."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("update_preventive_status rejected: missing or invalid profile_id in ToolContext")
        return PreventiveToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed update_preventive_status.",
            error_code="YRV-300-014",
            retryable=False,
        )
    clean_profile_id = profile_id.strip()

    safe_args = args if isinstance(args, dict) else {}
    rule_id = str(safe_args.get("rule_id") or "").strip()
    if not rule_id:
        return PreventiveToolResult(
            success=False,
            output=None,
            error="Parameter 'rule_id' must be a non-empty string.",
            error_code="CFD-100-005",
            retryable=False,
        )

    status_val = str(safe_args.get("status") or "").strip().lower()
    if status_val not in VALID_PREVENTIVE_STATUSES:
        return PreventiveToolResult(
            success=False,
            output=None,
            error=f"Invalid status '{status_val}'. Permitted: {sorted(VALID_PREVENTIVE_STATUSES)}.",
            error_code="CFD-100-005",
            retryable=False,
        )

    actor_id = getattr(ctx, "user_id", "user") or "user"
    try:
        out = await execute_governed_db_operation(
            "tool.update_preventive_status",
            {
                "rule_id": rule_id,
                "status": status_val,
                "notes": safe_args.get("notes"),
                "completed_at": safe_args.get("completed_at"),
                "schedule_source": safe_args.get("schedule_source"),
                "actor_user_id": actor_id,
            },
            ctx=ctx,
            profile_id=clean_profile_id,
            user_id=actor_id,
            risk_tier="write_local",
            caller_module_name=__name__,
        )
    except ValueError as exc:
        msg = str(exc)
        err_code = "CFD-500-008" if "not found" in msg.lower() else "CFD-100-005"
        return PreventiveToolResult(
            success=False,
            output=None,
            error=msg,
            error_code=err_code,
            retryable=False,
        )

    return PreventiveToolResult(success=True, output=out, error=None)


__all__ = [
    "PreventiveToolResult",
    "SPEC_CHECK",
    "SPEC_UPDATE",
    "execute_check_preventive_care",
    "execute_update_preventive_status",
]

_SPEC_ATTRS = {
    "SPEC_CHECK": "check_preventive_care",
    "SPEC_UPDATE": "update_preventive_status",
}


def __getattr__(name: str) -> Any:
    if name in _SPEC_ATTRS:
        from carefold.tools import get_health_tool_spec

        return get_health_tool_spec(_SPEC_ATTRS[name])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
