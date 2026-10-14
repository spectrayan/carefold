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

"""Closed tools for Pediatric School Health Forms (AU-39)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterator

from sqlalchemy import select

from carefold.clinical.school_forms import (
    create_school_form,
    serialize_school_form,
)
from carefold.db.models import SchoolForm
from carefold.db.session import get_session_factory
from carefold.schemas.tool import ToolResult

logger = logging.getLogger("carefold.tools.school_forms")


class SchoolFormToolResult(ToolResult):
    """ToolResult subclass supporting both attribute access (.success, .output) and dict access."""

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


async def execute_create_school_form(args: Dict[str, Any], ctx: Any = None) -> SchoolFormToolResult:
    """Creates a school/camp health form with compiled draft prefill and optional renewal reminder."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("create_school_form rejected: missing or invalid profile_id in ToolContext")
        return SchoolFormToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed create_school_form.",
        )
    clean_profile_id = profile_id.strip()

    safe_args = args if isinstance(args, dict) else {}
    title = str(safe_args.get("title") or "").strip()
    if not title:
        return SchoolFormToolResult(
            success=False,
            output=None,
            error="Parameter 'title' must be a non-empty string.",
        )

    school_or_camp_name = safe_args.get("school_or_camp_name")
    form_type = str(safe_args.get("form_type") or "general").strip().lower()
    attachment_id = safe_args.get("attachment_id")
    expires_at = safe_args.get("expires_at")
    status_val = str(safe_args.get("status") or "draft").strip().lower()
    actor_id = getattr(ctx, "user_id", "user") or "user"

    factory = get_session_factory()
    async with factory() as session:
        try:
            form = await create_school_form(
                session,
                profile_id=clean_profile_id,
                title=title,
                school_or_camp_name=school_or_camp_name,
                form_type=form_type,
                attachment_id=attachment_id,
                expires_at=expires_at,
                status=status_val,
                actor_user_id=actor_id,
            )
            serialized = serialize_school_form(form)
        except ValueError as exc:
            return SchoolFormToolResult(
                success=False,
                output=None,
                error=str(exc),
            )

    ext_ref = f"school_form:{serialized['id']}"
    serialized["external_ref"] = ext_ref
    serialized["undo_reference"] = ext_ref

    return SchoolFormToolResult(
        success=True,
        output=serialized,
        error=None,
    )


async def execute_list_school_forms(args: Dict[str, Any], ctx: Any = None) -> SchoolFormToolResult:
    """Lists school and camp health forms for the active profile."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("list_school_forms rejected: missing or invalid profile_id in ToolContext")
        return SchoolFormToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed list_school_forms.",
        )
    clean_profile_id = profile_id.strip()

    safe_args = args if isinstance(args, dict) else {}
    status_filter = safe_args.get("status")
    form_type_filter = safe_args.get("form_type")

    factory = get_session_factory()
    async with factory() as session:
        stmt = select(SchoolForm).where(SchoolForm.profile_id == clean_profile_id)
        if status_filter and str(status_filter).strip():
            stmt = stmt.where(SchoolForm.status == str(status_filter).strip().lower())
        if form_type_filter and str(form_type_filter).strip():
            stmt = stmt.where(SchoolForm.form_type == str(form_type_filter).strip().lower())
        stmt = stmt.order_by(SchoolForm.created_at.desc())

        res = await session.execute(stmt)
        forms = [serialize_school_form(f) for f in res.scalars().all()]

    return SchoolFormToolResult(
        success=True,
        output={
            "profile_id": clean_profile_id,
            "forms": forms,
            "items": forms,
            "total": len(forms),
        },
        error=None,
    )


__all__ = [
    "SchoolFormToolResult",
    "execute_create_school_form",
    "execute_list_school_forms",
]
