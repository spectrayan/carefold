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

"""Closed tool: create_typed_note routed via McpDatabaseToolbox (AU-35, #344)."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
from typing import Any, Dict, List
import uuid

from carefold.clinical.db_hooks import execute_governed_db_operation
from carefold.clinical.notes import VALID_NOTE_TYPES, validate_note_type  # noqa: F401
from yarvelle_core.db.session import get_session_factory  # noqa: F401
from yarvelle_core.schemas.tool import ToolResult

logger = logging.getLogger("carefold.tools.notes")


def _slugify(text: str) -> str:
    """Generates a URL-safe alphanumeric slug."""
    clean = re.sub(r"[^a-zA-Z0-9_\-\s]", "", text.strip())
    slug = re.sub(r"\s+", "-", clean).lower()
    return slug[:64] or "note"


async def execute_create_typed_note(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Creates a typed note via McpDatabaseToolbox with appointment linking and indexing."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("create_typed_note rejected: invalid or missing profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed create_typed_note.",
            error_code="YRV-300-014",
            retryable=False,
        )
    clean_profile_id = profile_id.strip()

    if not isinstance(args, dict):
        return ToolResult(
            success=False,
            output=None,
            error="Parameters must be provided as a dictionary.",
            error_code="CFD-100-014",
            retryable=False,
        )

    title = str(args.get("title", "")).strip()
    content = str(args.get("content", "")).strip()
    if not title or not content:
        return ToolResult(
            success=False,
            output=None,
            error="Parameters 'title' and 'content' must be non-empty strings.",
            error_code="CFD-100-014",
            retryable=False,
        )

    raw_type = str(args.get("type", "general")).strip()
    try:
        note_type = validate_note_type(raw_type)
    except ValueError as type_err:
        return ToolResult(
            success=False,
            output=None,
            error=str(type_err),
            error_code="CFD-100-014",
            retryable=False,
        )

    linked_appt_id = args.get("linked_appointment_id")
    if linked_appt_id is not None:
        linked_appt_id = str(linked_appt_id).strip() or None

    raw_tags = args.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    tags_list: List[str] = [str(t).strip().lower() for t in raw_tags if str(t).strip()]

    user_id = getattr(ctx, "user_id", None) if ctx is not None else None
    note_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    base_slug = _slugify(title)
    unique_slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

    try:
        res = await execute_governed_db_operation(
            "tool.create_typed_note",
            {
                "note_id": note_id,
                "note_type": note_type,
                "unique_slug": unique_slug,
                "title": title,
                "content": content,
                "tags_list": tags_list,
                "linked_appointment_id": linked_appt_id,
                "now": now.isoformat(),
            },
            ctx=ctx,
            profile_id=clean_profile_id,
            user_id=user_id,
            risk_tier="write_local",
            caller_module_name=__name__,
        )
        if not res.get("ok"):
            return ToolResult(
                success=False,
                output=None,
                error=res["error"],
                error_code=res["error_code"],
                retryable=False,
            )

        out = res["output"]
        try:
            from yarvelle_core.audit.logger import record_audit

            await record_audit(
                {
                    "profile_id": clean_profile_id,
                    "action": "create",
                    "tool": "create_typed_note",
                    "risk": "write_local",
                    "external_ref": f"note:{out['id']}",
                    "details": {
                        "note_id": out["id"],
                        "title": out["title"],
                        "type": out["type"],
                        "linked_appointment_id": out["linked_appointment_id"],
                    },
                },
                actor_user_id=user_id or "user",
                risk="write_local",
            )
        except Exception as audit_err:
            logger.debug("Audit logging failed during typed note creation: %s", audit_err)

        return ToolResult(
            success=True,
            output=out,
            metadata={
                "entity": "note",
                "id": out["id"],
                "undoable": True,
                "risk": "write_local",
            },
        )
    except Exception as exc:
        logger.exception("create_typed_note failed: %s", exc)
        return ToolResult(
            success=False,
            output=None,
            error="Failed to persist clinical note.",
            error_code="CFD-900-001",
            retryable=False,
        )


def __getattr__(name: str) -> Any:
    if name == "SPEC":
        from carefold.tools import get_health_tool_spec

        return get_health_tool_spec("create_typed_note")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["SPEC", "execute_create_typed_note"]
