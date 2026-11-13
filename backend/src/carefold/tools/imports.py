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

"""Tool executors for clinical and wearable file import staging and commit via McpDatabaseToolbox (AU-38, #344)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from carefold.clinical.db_hooks import execute_governed_db_operation
from carefold.errors import CarefoldToolError
from yarvelle_core.db.session import get_session_factory  # noqa: F401
from yarvelle_core.tools.sql_ast_sandbox import SqlValidationError

logger = logging.getLogger("carefold.tools.imports")


def _require_profile_context(ctx: Any, tool_name: str) -> str:
    """Enforces fail-closed profile_id check on ToolContext."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if ctx is None or not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        raise CarefoldToolError(
            "YRV-300-014",
            detail=f"Security violation: ToolContext with a non-empty 'profile_id' is required for {tool_name}.",
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
    """Stages a clinical or wearable import file via McpDatabaseToolbox."""
    clean_profile_id = _require_profile_context(ctx, "stage_clinical_import")
    if not isinstance(args, dict):
        raise CarefoldToolError("CFD-100-006", detail="Arguments must be provided as a dictionary.")

    filename = str(args.get("filename") or "clinical_import.dat").strip()
    content = args.get("content")
    if content is None or (isinstance(content, (str, bytes)) and len(content) == 0):
        raise CarefoldToolError("CFD-100-006", detail="Parameter 'content' is required and must not be empty.")

    fmt = args.get("format") or args.get("fmt")
    source_name = args.get("source_name")
    user_id = getattr(ctx, "user_id", None)
    explicit_session = args.get("session") or getattr(ctx, "session", None)

    try:
        out = await execute_governed_db_operation(
            "tool.stage_clinical_import",
            {
                "filename": filename,
                "content": content,
                "source_name": source_name,
                "fmt": fmt,
            },
            ctx=ctx,
            profile_id=clean_profile_id,
            user_id=user_id,
            risk_tier="write_local",
            explicit_session=explicit_session,
            caller_module_name=__name__,
        )
    except CarefoldToolError:
        raise
    except (ValueError, SqlValidationError) as exc:
        raise CarefoldToolError("CFD-100-006", detail=str(exc), cause=exc) from exc

    _mark_tainted(ctx)
    return out


async def execute_commit_clinical_import(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Commits a staged ImportBatch into HealthResource rows via McpDatabaseToolbox."""
    clean_profile_id = _require_profile_context(ctx, "commit_clinical_import")
    if not isinstance(args, dict):
        raise CarefoldToolError("CFD-100-006", detail="Arguments must be provided as a dictionary.")

    batch_id = str(args.get("batch_id") or "").strip()
    if not batch_id:
        raise CarefoldToolError("CFD-100-006", detail="Parameter 'batch_id' is required.")

    raw_indices = args.get("selected_indices")
    selected_indices: Optional[List[int]] = (
        [int(i) for i in raw_indices] if isinstance(raw_indices, (list, tuple)) else None
    )
    actor_user_id = getattr(ctx, "user_id", None)
    explicit_session = args.get("session") or getattr(ctx, "session", None)

    try:
        return await execute_governed_db_operation(
            "tool.commit_clinical_import",
            {
                "batch_id": batch_id,
                "selected_indices": selected_indices,
            },
            ctx=ctx,
            profile_id=clean_profile_id,
            user_id=actor_user_id,
            risk_tier="write_local",
            explicit_session=explicit_session,
            caller_module_name=__name__,
        )
    except CarefoldToolError:
        raise
    except (ValueError, SqlValidationError) as exc:
        msg = str(exc)
        err_code = "CFD-500-003" if "not found" in msg.lower() else "CFD-100-006"
        raise CarefoldToolError(err_code, detail=msg, cause=exc) from exc


__all__ = [
    "SPEC_COMMIT",
    "SPEC_STAGE",
    "execute_commit_clinical_import",
    "execute_stage_clinical_import",
]

_SPEC_ATTRS = {
    "SPEC_STAGE": "stage_clinical_import",
    "SPEC_COMMIT": "commit_clinical_import",
}


def __getattr__(name: str) -> Any:
    if name in _SPEC_ATTRS:
        from carefold.tools import get_health_tool_spec

        return get_health_tool_spec(_SPEC_ATTRS[name])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
