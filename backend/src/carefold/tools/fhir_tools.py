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

"""Scope-isolated FHIR R4 chart and repository MCP tool executors routed via McpDatabaseToolbox (#287, #344).

- `fhir_get_capabilities` executes directly in-memory via `handle_fhir_capabilities` with zero SQL queries.
- All database-backed FHIR R4 chart and repository tools execute through `McpDatabaseToolbox`.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any, Dict, Iterator, Optional, Tuple

from carefold.clinical.db_hooks import (
    _resolve_custom_session_factory,
    execute_governed_db_operation,
    register_carefold_db_toolbox,
)
from carefold.clinical.fhir_chart_queries import (
    CLINICAL_RESOURCE_TYPES,
    NON_CLINICAL_FHIR_TOOL_DISCLAIMER,
    PAPERWORK_RESOURCE_TYPES,
    REQUIRED_CLINICAL_SCOPE,
    _build_provenance_summary,
    _derive_interpretation_flag,
    _extract_observation_point_for_code,
    _extract_observation_value_summary,
    _extract_resource_display_and_codes,
    _extract_resource_status,
    _extract_source_name,
    _format_effective_date,
    _is_resource_untrusted,
    _matches_category_filter,
    _parse_code_token,
    _parse_iso_filter,
    _resolve_canonical_resource_type,
    _resource_matches_code,
    _summarize_health_resource,
    query_fhir_observation_trends as _query_fhir_observation_trends,
    query_fhir_patient_summary as _query_fhir_patient_summary,
    query_fhir_search_resources as _query_fhir_search_resources,
)
from carefold.db.scoped_session import register_scope_listeners
from carefold.engine.tool_exec import TaintFlag, UntrustedResult
from carefold.errors import CarefoldToolError
from carefold.fhir.operations import (
    FhirExecutionContext,
    FhirOperationError,
    handle_fhir_capabilities,
)
from carefold.scope.context import current_scope_context, is_scope_granted
from yarvelle_core.db.session import get_session_factory  # noqa: F401
from yarvelle_core.schemas.tool import ToolResult
import yarvelle_core.tools.mcp_db_toolbox as core_toolbox

register_scope_listeners()

logger = logging.getLogger("carefold.tools.fhir_tools")


class FhirToolResult(ToolResult):
    """ToolResult subclass supporting attribute access, dict access, and UntrustedResult taint metadata."""

    taint: bool = False
    trust: str = "trusted"
    source: str = "fhir_repository"

    def _as_dict(self) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "taint": self.taint,
            "trust": self.trust,
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

    @property
    def data(self) -> Any:
        return self.output

    @property
    def untrusted_result(self) -> Optional[UntrustedResult]:
        if self.taint or self.trust == "untrusted":
            return UntrustedResult(data=self.output, taint=True, source=self.source)
        return None

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


def _mark_context_tainted(ctx: Any) -> None:
    """Propagates monotone taint onto ToolContext when untrusted external records are read."""
    if ctx is None:
        return
    taint_obj = getattr(ctx, "taint", None)
    if taint_obj is not None and hasattr(taint_obj, "set"):
        taint_obj.set()
        return
    try:
        setattr(ctx, "taint", True)
    except Exception:
        try:
            object.__setattr__(ctx, "taint", TaintFlag(True))
        except Exception:
            pass


def _verify_profile_and_clinical_scope(
    args: Optional[Dict[str, Any]],
    ctx: Any,
    tool_name: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Enforces fail-closed `profile_id` and `ScopeContext` (`health.clinical`) isolation."""
    safe_args = args if isinstance(args, dict) else {}
    ctx_profile = getattr(ctx, "profile_id", None) if ctx is not None else None
    arg_profile = safe_args.get("profile_id")

    if ctx_profile is not None and isinstance(ctx_profile, str) and ctx_profile.strip():
        clean_ctx_profile = ctx_profile.strip()
        if arg_profile is not None and str(arg_profile).strip() and str(arg_profile).strip() != clean_ctx_profile:
            return None, (
                f"Security violation in {tool_name}: cross-profile access denied "
                f"(requested profile '{str(arg_profile).strip()}' != active profile '{clean_ctx_profile}')."
            )
        clean_profile_id = clean_ctx_profile
    elif ctx is None and arg_profile is not None and isinstance(arg_profile, str) and arg_profile.strip():
        clean_profile_id = arg_profile.strip()
    else:
        return None, (
            f"Security violation: profile_id is required; profile_id must be a non-empty string "
            f"for fail-closed {tool_name}."
        )

    if ctx is not None:
        ctx_scopes = getattr(ctx, "scopes", None) or getattr(ctx, "granted_scopes", None)
        if isinstance(ctx_scopes, (set, list, tuple)) and ctx_scopes:
            if not is_scope_granted(REQUIRED_CLINICAL_SCOPE, set(str(s) for s in ctx_scopes)):
                return None, (
                    f"Scope violation in {tool_name}: active context scopes {sorted(str(s) for s in ctx_scopes)} "
                    f"do not grant '{REQUIRED_CLINICAL_SCOPE}'."
                )

    ambient_ctx = current_scope_context()
    if ambient_ctx is not None:
        active_scopes = set(getattr(ambient_ctx, "active_scopes", None) or ())
        granted_scopes = set(getattr(ambient_ctx, "granted_scopes", None) or ())
        check_set = active_scopes or granted_scopes
        if check_set and not is_scope_granted(REQUIRED_CLINICAL_SCOPE, check_set):
            return None, (
                f"Scope violation in {tool_name}: ambient ScopeContext {sorted(check_set)} "
                f"does not permit '{REQUIRED_CLINICAL_SCOPE}'."
            )

    return clean_profile_id, None


def _classify_fhir_tool_denial_code(err: Optional[str]) -> str:
    msg = (err or "").lower()
    if "profile_id is required" in msg:
        return "YRV-300-014"
    return "CFD-300-006"


async def execute_fhir_get_capabilities(args: Optional[Dict[str, Any]] = None, ctx: Any = None) -> Dict[str, Any]:
    """Returns Carefold's HL7 FHIR R4 CapabilityStatement directly in-memory with zero SQL queries."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    clean_pid = str(profile_id).strip() if isinstance(profile_id, str) and profile_id.strip() else "capabilities"
    user_id = getattr(ctx, "user_id", None) if ctx is not None else None
    fhir_ctx = FhirExecutionContext(
        profile_id=clean_pid,
        user_id=user_id,
        scopes=frozenset({"health.clinical", "health.paperwork"}),
        principal="agent",
    )
    try:
        return await handle_fhir_capabilities(None, fhir_ctx, dict(args or {}))
    except FhirOperationError as err:
        raise CarefoldToolError(err.error_code, detail=err.diagnostics, cause=err) from err


async def _execute_fhir_toolbox_op(
    db_tool_name: str,
    db_params: Dict[str, Any],
    *,
    ctx: Any,
    extra_resource: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Executes a canonical FHIR R4 operation through McpDatabaseToolbox and maps FhirOperationError codes."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        raise CarefoldToolError(
            "YRV-300-014",
            detail=f"Security violation: profile_id is required in ToolContext for {db_tool_name}.",
        )
    clean_pid = profile_id.strip()
    user_id = getattr(ctx, "user_id", None) if ctx is not None else None
    scope = getattr(ctx, "scope", None) if ctx is not None else None

    register_carefold_db_toolbox()
    toolbox = core_toolbox.get_db_toolbox()

    base_extra = dict(getattr(ctx, "extra", None) or {}) if ctx is not None and isinstance(getattr(ctx, "extra", None), dict) else {}
    if extra_resource is not None:
        base_extra["fhir_resource"] = extra_resource
    wrapped_ctx = SimpleNamespace(
        profile_id=clean_pid,
        user_id=user_id,
        locale=getattr(ctx, "locale", "en-US") if ctx is not None else "en-US",
        scope=scope or "health.clinical",
        scopes=getattr(ctx, "scopes", None) if ctx is not None else None,
        taint=getattr(ctx, "taint", None) if ctx is not None else None,
        extra=base_extra,
    )

    explicit_session = getattr(ctx, "session", None) if ctx is not None else None
    if explicit_session is not None:
        res = await toolbox.execute(
            db_tool_name,
            db_params,
            profile_id=clean_pid,
            user_id=user_id,
            scope=scope or "health.clinical",
            session=explicit_session,
            ctx=wrapped_ctx,
        )
    else:
        custom_factory = _resolve_custom_session_factory(ctx, __name__)
        if custom_factory is not None:
            async with custom_factory() as managed_session:
                res = await toolbox.execute(
                    db_tool_name,
                    db_params,
                    profile_id=clean_pid,
                    user_id=user_id,
                    scope=scope or "health.clinical",
                    session=managed_session,
                    ctx=wrapped_ctx,
                )
        else:
            res = await toolbox.execute(
                db_tool_name,
                db_params,
                profile_id=clean_pid,
                user_id=user_id,
                scope=scope or "health.clinical",
                ctx=wrapped_ctx,
            )

    if res.get("status") == "error":
        err_info = res.get("error") or {}
        raise CarefoldToolError(
            str(res.get("error_code") or err_info.get("error_code") or "CFD-900-001"),
            detail=str(err_info.get("diagnostics") or "FHIR R4 operation failed."),
        )
    return dict(res.get("result") or res)


async def execute_fhir_r4_search_resources(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Executes canonical FHIR R4 Bundle search (`GET /api/v1/fhir/r4/{resource_type}`) via McpDatabaseToolbox."""
    safe = dict(args or {})
    return await _execute_fhir_toolbox_op(
        "fhir_search_resources",
        {
            "resource_type": str(safe.get("resource_type") or ""),
            "category": str(safe.get("category") or ""),
            "code": str(safe.get("code") or ""),
            "date": str(safe.get("date") or ""),
            "status": str(safe.get("status") or ""),
            "clinical_status": str(safe.get("clinical_status") or ""),
            "last_updated": str(safe.get("_lastUpdated") or safe.get("last_updated") or ""),
            "include": str(safe.get("_include") or safe.get("include") or ""),
            "sort": str(safe.get("_sort") or safe.get("sort") or "-date"),
            "count": int(safe.get("_count") if safe.get("_count") is not None else safe.get("count", 50)),
            "cursor": str(safe.get("_cursor") or safe.get("cursor") or ""),
        },
        ctx=ctx,
    )


async def execute_fhir_read_resource(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Reads a canonical FHIR R4 resource (`GET /api/v1/fhir/r4/{resource_type}/{resource_id}`) via McpDatabaseToolbox."""
    safe = dict(args or {})
    return await _execute_fhir_toolbox_op(
        "fhir_read_resource",
        {
            "resource_type": str(safe.get("resource_type") or ""),
            "resource_id": str(safe.get("resource_id") or safe.get("id") or ""),
        },
        ctx=ctx,
    )


async def execute_fhir_get_resource_history(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Retrieves FHIR R4 resource version history (`_history`) via McpDatabaseToolbox."""
    safe = dict(args or {})
    return await _execute_fhir_toolbox_op(
        "fhir_get_resource_history",
        {
            "resource_type": str(safe.get("resource_type") or ""),
            "resource_id": str(safe.get("resource_id") or safe.get("id") or ""),
            "count": int(safe.get("_count") if safe.get("_count") is not None else safe.get("count", 50)),
            "cursor": str(safe.get("_cursor") or safe.get("cursor") or ""),
        },
        ctx=ctx,
    )


async def execute_fhir_get_patient_everything(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Executes FHIR R4 `Patient/{id}/$everything` via McpDatabaseToolbox."""
    safe = dict(args or {})
    if safe.get("patient_id"):
        active_pid = str(getattr(ctx, "profile_id", "") or "").strip()
        req_pid = str(safe["patient_id"]).strip()
        if req_pid.startswith("Patient/"):
            req_pid = req_pid.split("/", 1)[1].strip()
        if active_pid and req_pid not in (active_pid, f"pat-{active_pid}"):
            raise CarefoldToolError("CFD-500-001", detail=f"Patient/{safe['patient_id']} was not found.")
    return await _execute_fhir_toolbox_op(
        "fhir_get_patient_everything",
        {
            "resource_types": str(safe.get("_type") or safe.get("resource_types") or ""),
            "since": str(safe.get("_since") or safe.get("since") or ""),
            "count": int(safe.get("_count") if safe.get("_count") is not None else safe.get("count", 50)),
            "cursor": str(safe.get("_cursor") or safe.get("cursor") or ""),
        },
        ctx=ctx,
    )


async def execute_fhir_r4_patient_summary(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Executes canonical HL7 IPS Document Bundle (`GET /api/v1/fhir/r4/Patient/{id}/$summary`) via McpDatabaseToolbox."""
    safe = dict(args or {})
    if safe.get("patient_id"):
        active_pid = str(getattr(ctx, "profile_id", "") or "").strip()
        req_pid = str(safe["patient_id"]).strip()
        if req_pid.startswith("Patient/"):
            req_pid = req_pid.split("/", 1)[1].strip()
        if active_pid and req_pid not in (active_pid, f"pat-{active_pid}"):
            raise CarefoldToolError("CFD-500-001", detail=f"Patient/{safe['patient_id']} was not found.")
    return await _execute_fhir_toolbox_op("fhir_get_patient_summary", {}, ctx=ctx)


async def execute_fhir_upsert_resource(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Upserts a FHIR R4 resource via McpDatabaseToolbox with full ETag, If-Match, idempotency, and dedup invariants."""
    safe = dict(args or {})
    raw_res = safe.get("resource")
    raw_res_json = safe.get("resource_json")
    extra_res: Optional[Dict[str, Any]] = None
    if isinstance(raw_res, dict):
        extra_res = raw_res
        res_json_str = json.dumps(raw_res)
    elif isinstance(raw_res_json, str) and raw_res_json.strip():
        res_json_str = raw_res_json
    else:
        res_json_str = ""
    return await _execute_fhir_toolbox_op(
        "fhir_upsert_resource",
        {
            "resource_type": str(safe.get("resource_type") or ""),
            "resource_id": str(safe.get("resource_id") or safe.get("id") or ""),
            "resource_json": res_json_str,
            "if_match": str(safe.get("if_match") or ""),
            "idempotency_key": str(safe.get("idempotency_key") or ""),
            "confirmed": bool(safe.get("confirmed") is True),
        },
        ctx=ctx,
        extra_resource=extra_res,
    )


async def execute_fhir_start_bulk_export(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Starts an audited Bulk FHIR NDJSON `$export` job via McpDatabaseToolbox."""
    safe = dict(args or {})
    if safe.get("patient_id"):
        active_pid = str(getattr(ctx, "profile_id", "") or "").strip()
        req_pid = str(safe["patient_id"]).strip()
        if req_pid.startswith("Patient/"):
            req_pid = req_pid.split("/", 1)[1].strip()
        if active_pid and req_pid not in (active_pid, f"pat-{active_pid}"):
            raise CarefoldToolError("CFD-500-001", detail=f"Patient/{safe['patient_id']} was not found.")
    return await _execute_fhir_toolbox_op(
        "fhir_start_bulk_export",
        {
            "resource_types": str(safe.get("_type") or safe.get("resource_types") or ""),
            "since": str(safe.get("_since") or safe.get("since") or ""),
            "idempotency_key": str(safe.get("idempotency_key") or ""),
            "confirmed": bool(safe.get("confirmed") is True),
        },
        ctx=ctx,
    )


async def execute_fhir_get_bulk_export_status(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Polls Bulk FHIR `$export` job status via McpDatabaseToolbox."""
    safe = dict(args or {})
    return await _execute_fhir_toolbox_op(
        "fhir_get_bulk_export_status",
        {"job_id": str(safe.get("job_id") or "")},
        ctx=ctx,
    )


async def execute_fhir_download_bulk_export_file(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Downloads NDJSON output for a resource_type from a completed Bulk `$export` job via McpDatabaseToolbox."""
    safe = dict(args or {})
    return await _execute_fhir_toolbox_op(
        "fhir_download_bulk_export_file",
        {
            "job_id": str(safe.get("job_id") or ""),
            "resource_type": str(safe.get("resource_type") or ""),
        },
        ctx=ctx,
    )


async def execute_fhir_search_resources(args: Dict[str, Any], ctx: Any = None) -> FhirToolResult:
    """Executes coordinator `fhir_search_resources` via McpDatabaseToolbox."""
    clean_profile_id, err = _verify_profile_and_clinical_scope(args, ctx, "fhir_search_resources")
    if err or not clean_profile_id:
        logger.warning("fhir_search_resources rejected: %s", err)
        return FhirToolResult(
            success=False,
            output=None,
            error=err,
            error_code=_classify_fhir_tool_denial_code(err),
            retryable=False,
        )

    safe_args = args if isinstance(args, dict) else {}
    explicit_session = safe_args.get("session") or (getattr(ctx, "session", None) if ctx is not None else None)
    try:
        payload = await execute_governed_db_operation(
            "tool.fhir_chart_search",
            {
                "resource_type": str(safe_args.get("resource_type") or "").strip(),
                "code": safe_args.get("code"),
                "category": safe_args.get("category"),
                "date_from": safe_args.get("date_from"),
                "limit": safe_args.get("limit", 25),
            },
            ctx=ctx,
            profile_id=clean_profile_id,
            risk_tier="read",
            explicit_session=explicit_session,
            caller_module_name=__name__,
        )
    except ValueError as exc:
        msg = str(exc)
        err_code = "CFD-300-006" if "paperwork" in msg.lower() or "scope" in msg.lower() else "CFD-100-001"
        return FhirToolResult(
            success=False,
            output=None,
            error=msg,
            error_code=err_code,
            retryable=False,
        )

    is_tainted = bool(payload.get("tainted"))
    if is_tainted:
        _mark_context_tainted(ctx)

    return FhirToolResult(
        success=True,
        output=payload,
        error=None,
        taint=is_tainted,
        trust="untrusted" if is_tainted else "trusted",
        source="fhir_search_resources",
    )


async def execute_fhir_get_patient_summary(args: Optional[Dict[str, Any]] = None, ctx: Any = None) -> FhirToolResult:
    """Executes coordinator `fhir_get_patient_summary` via McpDatabaseToolbox."""
    clean_profile_id, err = _verify_profile_and_clinical_scope(args, ctx, "fhir_get_patient_summary")
    if err or not clean_profile_id:
        logger.warning("fhir_get_patient_summary rejected: %s", err)
        return FhirToolResult(
            success=False,
            output=None,
            error=err,
            error_code=_classify_fhir_tool_denial_code(err),
            retryable=False,
        )

    safe_args = args if isinstance(args, dict) else {}
    explicit_session = safe_args.get("session") or (getattr(ctx, "session", None) if ctx is not None else None)
    try:
        payload = await execute_governed_db_operation(
            "tool.fhir_chart_summary",
            {"limit_per_section": safe_args.get("limit_per_section", 15)},
            ctx=ctx,
            profile_id=clean_profile_id,
            risk_tier="read",
            explicit_session=explicit_session,
            caller_module_name=__name__,
        )
    except ValueError as exc:
        return FhirToolResult(
            success=False,
            output=None,
            error=str(exc),
            error_code="CFD-100-001",
            retryable=False,
        )

    is_tainted = bool(payload.get("tainted"))
    if is_tainted:
        _mark_context_tainted(ctx)

    return FhirToolResult(
        success=True,
        output=payload,
        error=None,
        taint=is_tainted,
        trust="untrusted" if is_tainted else "trusted",
        source="fhir_get_patient_summary",
    )


async def execute_fhir_get_observation_trends(args: Dict[str, Any], ctx: Any = None) -> FhirToolResult:
    """Executes coordinator `fhir_get_observation_trends` via McpDatabaseToolbox."""
    clean_profile_id, err = _verify_profile_and_clinical_scope(args, ctx, "fhir_get_observation_trends")
    if err or not clean_profile_id:
        logger.warning("fhir_get_observation_trends rejected: %s", err)
        return FhirToolResult(
            success=False,
            output=None,
            error=err,
            error_code=_classify_fhir_tool_denial_code(err),
            retryable=False,
        )

    safe_args = args if isinstance(args, dict) else {}
    loinc_or_code = str(safe_args.get("loinc_or_code") or safe_args.get("code") or "").strip()
    explicit_session = safe_args.get("session") or (getattr(ctx, "session", None) if ctx is not None else None)
    try:
        payload = await execute_governed_db_operation(
            "tool.fhir_chart_trends",
            {
                "loinc_or_code": loinc_or_code,
                "limit": safe_args.get("limit", 12),
            },
            ctx=ctx,
            profile_id=clean_profile_id,
            risk_tier="read",
            explicit_session=explicit_session,
            caller_module_name=__name__,
        )
    except ValueError as exc:
        return FhirToolResult(
            success=False,
            output=None,
            error=str(exc),
            error_code="CFD-100-001",
            retryable=False,
        )

    is_tainted = bool(payload.get("tainted"))
    if is_tainted:
        _mark_context_tainted(ctx)

    return FhirToolResult(
        success=True,
        output=payload,
        error=None,
        taint=is_tainted,
        trust="untrusted" if is_tainted else "trusted",
        source="fhir_get_observation_trends",
    )


async def fhir_search_resources(
    resource_type: Any = None,
    code: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[str] = None,
    limit: int = 25,
    *,
    ctx: Any = None,
    profile_id: Optional[str] = None,
    session: Any = None,
) -> FhirToolResult:
    """Queries the active profile's HealthResource repository and returns structured summaries."""
    if isinstance(resource_type, dict):
        return await execute_fhir_search_resources(resource_type, ctx=code if ctx is None else ctx)
    call_args: Dict[str, Any] = {
        "resource_type": resource_type,
        "code": code,
        "category": category,
        "date_from": date_from,
        "limit": limit,
    }
    if profile_id is not None:
        call_args["profile_id"] = profile_id
    if session is not None:
        call_args["session"] = session
    return await execute_fhir_search_resources(call_args, ctx=ctx)


async def fhir_get_patient_summary(
    args: Optional[Dict[str, Any]] = None,
    ctx: Any = None,
    *,
    limit_per_section: int = 15,
    profile_id: Optional[str] = None,
    session: Any = None,
) -> FhirToolResult:
    """Returns a structured International Patient Summary (IPS) digest for the active profile."""
    call_args: Dict[str, Any] = dict(args) if isinstance(args, dict) else {"limit_per_section": limit_per_section}
    if profile_id is not None:
        call_args["profile_id"] = profile_id
    if session is not None:
        call_args["session"] = session
    return await execute_fhir_get_patient_summary(call_args, ctx=ctx)


async def fhir_get_observation_trends(
    loinc_or_code: Any = None,
    limit: int = 12,
    *,
    ctx: Any = None,
    profile_id: Optional[str] = None,
    session: Any = None,
) -> FhirToolResult:
    """Returns chronological data points, reference ranges, and units for a specific lab or vital sign code."""
    if isinstance(loinc_or_code, dict):
        return await execute_fhir_get_observation_trends(
            loinc_or_code,
            ctx=limit if ctx is None and not isinstance(limit, int) else ctx,
        )
    call_args: Dict[str, Any] = {
        "loinc_or_code": loinc_or_code,
        "limit": limit,
    }
    if profile_id is not None:
        call_args["profile_id"] = profile_id
    if session is not None:
        call_args["session"] = session
    return await execute_fhir_get_observation_trends(call_args, ctx=ctx)


_SPEC_ATTRS = {
    "SPEC_GET_CAPABILITIES": "fhir_get_capabilities",
    "SPEC_SEARCH_RESOURCES": "fhir_search_resources",
    "SPEC_GET_PATIENT_SUMMARY": "fhir_get_patient_summary",
    "SPEC_GET_OBSERVATION_TRENDS": "fhir_get_observation_trends",
}


def __getattr__(name: str) -> Any:
    if name in _SPEC_ATTRS:
        from carefold.tools import get_health_tool_spec

        return get_health_tool_spec(_SPEC_ATTRS[name])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CLINICAL_RESOURCE_TYPES",
    "FhirToolResult",
    "NON_CLINICAL_FHIR_TOOL_DISCLAIMER",
    "PAPERWORK_RESOURCE_TYPES",
    "REQUIRED_CLINICAL_SCOPE",
    "SPEC_GET_CAPABILITIES",
    "SPEC_GET_OBSERVATION_TRENDS",
    "SPEC_GET_PATIENT_SUMMARY",
    "SPEC_SEARCH_RESOURCES",
    "_build_provenance_summary",
    "_derive_interpretation_flag",
    "_extract_observation_point_for_code",
    "_extract_observation_value_summary",
    "_extract_resource_display_and_codes",
    "_extract_resource_status",
    "_extract_source_name",
    "_format_effective_date",
    "_is_resource_untrusted",
    "_matches_category_filter",
    "_parse_code_token",
    "_parse_iso_filter",
    "_query_fhir_observation_trends",
    "_query_fhir_patient_summary",
    "_query_fhir_search_resources",
    "_resolve_canonical_resource_type",
    "_resource_matches_code",
    "_summarize_health_resource",
    "execute_fhir_download_bulk_export_file",
    "execute_fhir_get_bulk_export_status",
    "execute_fhir_get_capabilities",
    "execute_fhir_get_observation_trends",
    "execute_fhir_get_patient_everything",
    "execute_fhir_get_patient_summary",
    "execute_fhir_get_resource_history",
    "execute_fhir_r4_patient_summary",
    "execute_fhir_r4_search_resources",
    "execute_fhir_read_resource",
    "execute_fhir_search_resources",
    "execute_fhir_start_bulk_export",
    "execute_fhir_upsert_resource",
    "fhir_get_observation_trends",
    "fhir_get_patient_summary",
    "fhir_search_resources",
]
