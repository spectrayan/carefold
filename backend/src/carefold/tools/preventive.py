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

"""Closed tools for Preventive Care & Immunisation Engine (AU-36)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterator

from carefold.clinical.preventive import (
    VALID_PREVENTIVE_STATUSES,
    VALID_SCHEDULE_SOURCES,
    evaluate_preventive_care,
    update_preventive_record,
)
from carefold.db.session import get_session_factory
from carefold.schemas.tool import ToolResult

logger = logging.getLogger("carefold.tools.preventive")


class PreventiveToolResult(ToolResult):
    """ToolResult subclass supporting both attribute access (.success, .output) and dict access (['items'])."""

    def _as_dict(self) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "success": self.success,
            "output": self.output,
            "error": self.error,
        }
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
    """Evaluates preventive care screenings and immunisations for the active profile (fail-closed)."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("check_preventive_care rejected: missing or invalid profile_id in ToolContext")
        return PreventiveToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed check_preventive_care.",
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
            )
    else:
        clean_sched = None

    sex_filter = safe_args.get("sex")
    category_filter = safe_args.get("category")

    factory = get_session_factory()
    async with factory() as session:
        try:
            evaluation = await evaluate_preventive_care(
                session,
                clean_profile_id,
                schedule_source=clean_sched,
                sex=sex_filter,
                category=category_filter,
            )
        except ValueError as exc:
            return PreventiveToolResult(
                success=False,
                output=None,
                error=str(exc),
            )

    return PreventiveToolResult(
        success=True,
        output=evaluation,
        error=None,
    )


async def execute_update_preventive_status(args: Dict[str, Any], ctx: Any = None) -> PreventiveToolResult:
    """Updates the status of a preventive care item for the active profile (fail-closed)."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("update_preventive_status rejected: missing or invalid profile_id in ToolContext")
        return PreventiveToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed update_preventive_status.",
        )
    clean_profile_id = profile_id.strip()

    safe_args = args if isinstance(args, dict) else {}
    rule_id = str(safe_args.get("rule_id") or "").strip()
    if not rule_id:
        return PreventiveToolResult(
            success=False,
            output=None,
            error="Parameter 'rule_id' must be a non-empty string.",
        )

    status_val = str(safe_args.get("status") or "").strip().lower()
    if status_val not in VALID_PREVENTIVE_STATUSES:
        return PreventiveToolResult(
            success=False,
            output=None,
            error=f"Invalid status '{status_val}'. Permitted: {sorted(VALID_PREVENTIVE_STATUSES)}.",
        )

    notes = safe_args.get("notes")
    completed_at = safe_args.get("completed_at")
    schedule_source = safe_args.get("schedule_source")
    actor_id = getattr(ctx, "user_id", "user") or "user"

    factory = get_session_factory()
    async with factory() as session:
        try:
            record = await update_preventive_record(
                session,
                profile_id=clean_profile_id,
                rule_id=rule_id,
                status=status_val,
                notes=notes,
                completed_at=completed_at,
                schedule_source=schedule_source,
                actor_user_id=actor_id,
            )
        except ValueError as exc:
            return PreventiveToolResult(
                success=False,
                output=None,
                error=str(exc),
            )

    ext_ref = f"preventive_record:{record.id}"
    return PreventiveToolResult(
        success=True,
        output={
            "id": record.id,
            "record_id": record.id,
            "profile_id": record.profile_id,
            "rule_id": record.rule_id,
            "status": record.status,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
            "notes": record.notes,
            "schedule_source": record.schedule_source,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            "external_ref": ext_ref,
            "undo_reference": ext_ref,
        },
        error=None,
    )


__all__ = [
    "PreventiveToolResult",
    "execute_check_preventive_care",
    "execute_update_preventive_status",
]
