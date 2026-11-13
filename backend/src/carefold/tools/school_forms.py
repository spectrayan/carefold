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

"""Closed tools for Pediatric School Health Forms via McpDatabaseToolbox (AU-39, #344)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterator

from carefold.clinical.db_hooks import execute_governed_db_operation
from yarvelle_core.db.session import get_session_factory  # noqa: F401
from yarvelle_core.schemas.tool import ToolResult

logger = logging.getLogger("carefold.tools.school_forms")


class SchoolFormToolResult(ToolResult):
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


async def execute_create_school_form(args: Dict[str, Any], ctx: Any = None) -> SchoolFormToolResult:
    """Creates a school/camp health form via McpDatabaseToolbox."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("create_school_form rejected: missing or invalid profile_id in ToolContext")
        return SchoolFormToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed create_school_form.",
            error_code="YRV-300-014",
            retryable=False,
        )
    clean_profile_id = profile_id.strip()

    safe_args = args if isinstance(args, dict) else {}
    title = str(safe_args.get("title") or "").strip()
    if not title:
        return SchoolFormToolResult(
            success=False,
            output=None,
            error="Parameter 'title' must be a non-empty string.",
            error_code="CFD-100-007",
            retryable=False,
        )

    actor_id = getattr(ctx, "user_id", "user") or "user"
    try:
        serialized = await execute_governed_db_operation(
            "tool.create_school_form",
            {
                "title": title,
                "school_or_camp_name": safe_args.get("school_or_camp_name"),
                "form_type": str(safe_args.get("form_type") or "general").strip().lower(),
                "attachment_id": safe_args.get("attachment_id"),
                "expires_at": safe_args.get("expires_at"),
                "status": str(safe_args.get("status") or "draft").strip().lower(),
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
        err_code = "CFD-500-004" if "not found" in msg.lower() else "CFD-100-007"
        return SchoolFormToolResult(
            success=False,
            output=None,
            error=msg,
            error_code=err_code,
            retryable=False,
        )

    ext_ref = f"school_form:{serialized['id']}"
    serialized["external_ref"] = ext_ref
    serialized["undo_reference"] = ext_ref
    return SchoolFormToolResult(success=True, output=serialized, error=None)


async def execute_list_school_forms(args: Dict[str, Any], ctx: Any = None) -> SchoolFormToolResult:
    """Lists school and camp health forms via McpDatabaseToolbox."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("list_school_forms rejected: missing or invalid profile_id in ToolContext")
        return SchoolFormToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed list_school_forms.",
            error_code="YRV-300-014",
            retryable=False,
        )
    clean_profile_id = profile_id.strip()

    safe_args = args if isinstance(args, dict) else {}
    out = await execute_governed_db_operation(
        "tool.list_school_forms",
        {
            "status": safe_args.get("status"),
            "form_type": safe_args.get("form_type"),
        },
        ctx=ctx,
        profile_id=clean_profile_id,
        risk_tier="read",
        caller_module_name=__name__,
    )
    return SchoolFormToolResult(success=True, output=out, error=None)


__all__ = [
    "SPEC_CREATE",
    "SPEC_LIST",
    "SchoolFormToolResult",
    "execute_create_school_form",
    "execute_list_school_forms",
]

_SPEC_ATTRS = {
    "SPEC_CREATE": "create_school_form",
    "SPEC_LIST": "list_school_forms",
}


def __getattr__(name: str) -> Any:
    if name in _SPEC_ATTRS:
        from carefold.tools import get_health_tool_spec

        return get_health_tool_spec(_SPEC_ATTRS[name])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
