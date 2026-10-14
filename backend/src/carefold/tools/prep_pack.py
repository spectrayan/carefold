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

"""Closed tool: generate_prep_pack (AU-33, AU-34).

Compiles and persists a consultation visit prep pack dossier linking to an
optional appointment with fail-closed profile verification and audit logging.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from carefold.clinical.prep_pack import generate_and_persist_prep_pack
from carefold.db.session import get_session_factory
from carefold.schemas.tool import ToolResult

logger = logging.getLogger("carefold.tools.prep_pack")


async def execute_generate_prep_pack(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Executes consultation prep pack compilation and persistence with fail-closed security."""
    # 1. Fail-closed profile verification
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("generate_prep_pack rejected: invalid or missing profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed generate_prep_pack.",
        )
    clean_profile_id = profile_id.strip()

    appointment_id = args.get("appointment_id") if isinstance(args, dict) else None
    specialty = args.get("specialty") if isinstance(args, dict) else None
    visit_reason = args.get("visit_reason") if isinstance(args, dict) else None
    doctor_questions = args.get("doctor_questions") if isinstance(args, dict) else None

    user_id = getattr(ctx, "user_id", None) if ctx is not None else None

    try:
        factory = get_session_factory()
        async with factory() as session:
            res = await generate_and_persist_prep_pack(
                session=session,
                profile_id=clean_profile_id,
                appointment_id=appointment_id,
                specialty=specialty,
                visit_reason=visit_reason,
                doctor_questions=doctor_questions,
                user_id=user_id,
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
        return ToolResult(
            success=False,
            output=None,
            error=str(val_err),
        )
    except Exception as exc:
        logger.exception("generate_prep_pack failed: %s", exc)
        return ToolResult(
            success=False,
            output=None,
            error=f"generate_prep_pack failed: {exc}",
        )


__all__ = ["execute_generate_prep_pack"]
