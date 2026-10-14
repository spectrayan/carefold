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

"""Tool executors for clinical and wearable file import staging and commit (AU-38).

Provides:
- `execute_stage_clinical_import`: Stages a FHIR R4 Bundle, C-CDA XML, or Apple Health
  export into `import_batches` for user review before saving.
- `execute_commit_clinical_import`: Commits a staged `ImportBatch` into `health_resources`
  with idempotency, search indexing, and audit logging.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from carefold.db.session import get_session_factory
from carefold.importers.service import commit_import_batch, stage_import

logger = logging.getLogger("carefold.tools.imports")


def _require_profile_context(ctx: Any, tool_name: str) -> str:
    """Enforces fail-closed profile_id check on ToolContext."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if ctx is None or not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError(
            f"Security violation: ToolContext with a non-empty 'profile_id' is required for {tool_name}."
        )
    return profile_id.strip()


def _mark_tainted(ctx: Any) -> None:
    """Marks ToolContext as tainted when untrusted imported records are loaded."""
    if ctx is None:
        return
    taint_obj = getattr(ctx, "taint", None)
    if taint_obj is not None and hasattr(taint_obj, "set"):
        taint_obj.set()
    else:
        try:
            object.__setattr__(ctx, "taint", True)
        except Exception:
            pass


async def execute_stage_clinical_import(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Stages a clinical or wearable import file for Review-Before-Save confirmation."""
    clean_profile_id = _require_profile_context(ctx, "stage_clinical_import")
    if not isinstance(args, dict):
        raise ValueError("Arguments must be provided as a dictionary.")

    filename = str(args.get("filename") or "clinical_import.dat").strip()
    content = args.get("content")
    if content is None or (isinstance(content, (str, bytes)) and len(content) == 0):
        raise ValueError("Parameter 'content' is required and must not be empty.")

    fmt = args.get("format") or args.get("fmt")
    source_name = args.get("source_name")
    user_id = getattr(ctx, "user_id", None)

    explicit_session = args.get("session") or getattr(ctx, "session", None)
    if explicit_session is not None:
        batch = await stage_import(
            session=explicit_session,
            profile_id=clean_profile_id,
            filename=filename,
            content=content,
            source_name=source_name,
            fmt=fmt,
            user_id=user_id,
        )
    else:
        session_factory = getattr(ctx, "session_factory", None) or (
            ctx.extra.get("session_factory") if isinstance(getattr(ctx, "extra", None), dict) else None
        ) or get_session_factory()
        async with session_factory() as session:
            batch = await stage_import(
                session=session,
                profile_id=clean_profile_id,
                filename=filename,
                content=content,
                source_name=source_name,
                fmt=fmt,
                user_id=user_id,
            )

    _mark_tainted(ctx)

    summary = json.loads(batch.summary_json or "{}")
    staged_records = json.loads(batch.staged_records_json or "[]")

    return {
        "id": batch.id,
        "batch_id": batch.id,
        "profile_id": batch.profile_id,
        "attachment_id": batch.attachment_id,
        "format": batch.format,
        "source_name": batch.source_name,
        "status": batch.status,
        "summary": summary,
        "staged_records": staged_records,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "trust": "untrusted",
    }


async def execute_commit_clinical_import(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Commits a staged `ImportBatch` into `HealthResource` rows."""
    clean_profile_id = _require_profile_context(ctx, "commit_clinical_import")
    if not isinstance(args, dict):
        raise ValueError("Arguments must be provided as a dictionary.")

    batch_id = str(args.get("batch_id") or "").strip()
    if not batch_id:
        raise ValueError("Parameter 'batch_id' is required.")

    raw_indices = args.get("selected_indices")
    selected_indices: Optional[List[int]] = (
        [int(i) for i in raw_indices] if isinstance(raw_indices, (list, tuple)) else None
    )
    actor_user_id = getattr(ctx, "user_id", None)

    explicit_session = args.get("session") or getattr(ctx, "session", None)
    if explicit_session is not None:
        return await commit_import_batch(
            session=explicit_session,
            profile_id=clean_profile_id,
            batch_id=batch_id,
            selected_indices=selected_indices,
            actor_user_id=actor_user_id,
        )

    session_factory = getattr(ctx, "session_factory", None) or (
        ctx.extra.get("session_factory") if isinstance(getattr(ctx, "extra", None), dict) else None
    ) or get_session_factory()
    async with session_factory() as session:
        return await commit_import_batch(
            session=session,
            profile_id=clean_profile_id,
            batch_id=batch_id,
            selected_indices=selected_indices,
            actor_user_id=actor_user_id,
        )


__all__ = [
    "execute_commit_clinical_import",
    "execute_stage_clinical_import",
]
