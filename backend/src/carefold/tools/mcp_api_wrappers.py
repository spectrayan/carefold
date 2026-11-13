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

"""Declarative MCP tool executors providing 1:1 parity with Carefold domain APIs (#344).

Every executor validates inputs against the shared Pydantic contract in
`carefold.clinical.api_contracts`, enforces identical profile authorization and
`YRV-*`/`CFD-*` error codes, and routes all database operations exclusively
through `McpDatabaseToolbox` (`db-operator`). Zero raw ORM sessions are opened.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Coroutine, Dict, Optional, Set

from pydantic import ValidationError

from carefold.clinical.api_contracts import (
    CANONICAL_DOMAIN_ROUTE_SPECS,
    ApiMcpOperationContract,
    get_api_mcp_contract,
)
from carefold.clinical.db_hooks import (
    execute_governed_db_operation,
    execute_governed_fhir_toolbox_tool,
)
from carefold.errors import YarvelleError
from carefold.fhir.operations import FhirOperationError, execute_fhir_mcp_operation

_AGENT_PRINCIPALS = frozenset({"agent", "db-operator", "mcp_agent", "autonomous_agent"})

_SPEC_ATTR_TO_TOOL: Dict[str, str] = {
    f"SPEC_{spec.tool_name.upper()}": spec.tool_name
    for spec in CANONICAL_DOMAIN_ROUTE_SPECS
}


def _extract_principal(ctx: Any) -> str:
    if ctx is None:
        return ""
    direct = getattr(ctx, "principal", None)
    if direct:
        return str(direct).strip().lower()
    extra = getattr(ctx, "extra", None)
    if isinstance(extra, dict) and extra.get("principal"):
        return str(extra["principal"]).strip().lower()
    return ""


def _resolve_explicit_field_names(
    contract: ApiMcpOperationContract,
    validated: Any,
) -> Set[str]:
    """Maps Pydantic `model_fields_set` back to external alias names (e.g. `_count`)."""
    out: Set[str] = set()
    for py_name in validated.model_fields_set:
        finfo = contract.input_model.model_fields.get(py_name)
        alias = getattr(finfo, "alias", None) if finfo is not None else None
        out.add(alias or py_name)
    return out


async def _invoke_fhir_contract(
    contract: ApiMcpOperationContract,
    parsed_fields: Dict[str, Any],
    ctx: Any,
) -> Dict[str, Any]:
    fhir_tool = str(contract.spec.fhir_toolbox_tool)
    ctx_pid = getattr(ctx, "profile_id", None) if ctx is not None else None
    ctx_uid = getattr(ctx, "user_id", None) if ctx is not None else None
    effective_pid = (str(ctx_pid).strip() if ctx_pid else "")

    # 1. fhir_get_capabilities runs 100% in-memory with zero SQL unless profile_id is checked
    if fhir_tool == "fhir_get_capabilities":
        if effective_pid:
            await execute_governed_db_operation(
                "api.fhir_verify_profile",
                {"profile_id": effective_pid},
                ctx=ctx,
                profile_id=effective_pid,
                user_id=ctx_uid,
                risk_tier="read",
                caller_module_name=__name__,
            )
        try:
            return await execute_fhir_mcp_operation(
                "fhir_get_capabilities",
                {},
                session=None,
                profile_id=effective_pid or "metadata-default",
                user_id=ctx_uid,
            )
        except FhirOperationError as err:
            raise YarvelleError(
                err.error_code,
                detail=err.diagnostics,
                context={
                    "fhir_issue_code": err.issue_code,
                    "operation_outcome": err.to_operation_outcome(),
                },
                cause=err,
            ) from err

    # Resolve patient_id fallback when path parameter `id` is on /Patient/{id}/...
    if not effective_pid and "/Patient/{id}" in contract.spec.path:
        raw_pat = str(parsed_fields.get("id") or "").strip()
        if raw_pat.startswith("Patient/"):
            raw_pat = raw_pat.split("/", 1)[1].strip()
        if raw_pat.startswith("pat-"):
            raw_pat = raw_pat[4:]
        effective_pid = raw_pat
    if not effective_pid:
        cand = str(parsed_fields.get("patient") or parsed_fields.get("subject") or "").strip()
        if cand.startswith("Patient/"):
            cand = cand.split("/", 1)[1].strip()
        if cand.startswith("pat-"):
            cand = cand[4:]
        effective_pid = cand

    if not effective_pid:
        raise YarvelleError(
            "CFD-500-001",
            detail="Requested patient profile was not found.",
        )

    sql_params: Dict[str, Any] = {}
    raw_params: Dict[str, Any] = dict(parsed_fields)
    fhir_resource: Optional[Dict[str, Any]] = None
    confirmed = bool(parsed_fields.get("confirmed") is True)

    if fhir_tool == "fhir_search_resources":
        date_val = parsed_fields.get("date")
        last_upd = parsed_fields.get("_lastUpdated")
        sql_params = {
            "resource_type": str(parsed_fields["resource_type"]),
            "category": str(parsed_fields.get("category") or ""),
            "code": str(parsed_fields.get("code") or ""),
            "date": date_val[0] if isinstance(date_val, list) and date_val else str(date_val or ""),
            "status": str(parsed_fields.get("status") or ""),
            "clinical_status": str(parsed_fields.get("clinical_status") or ""),
            "last_updated": last_upd[0] if isinstance(last_upd, list) and last_upd else str(last_upd or ""),
            "include": str(parsed_fields.get("_include") or ""),
            "sort": str(parsed_fields.get("_sort") or "-date"),
            "count": int(parsed_fields.get("_count") or 50),
            "cursor": str(parsed_fields.get("_cursor") or ""),
        }
        if parsed_fields.get("clinical_status"):
            raw_params["clinical-status"] = parsed_fields["clinical_status"]
    elif fhir_tool == "fhir_read_resource":
        rid = str(parsed_fields.get("id") or parsed_fields.get("resource_id") or "")
        sql_params = {"resource_type": str(parsed_fields["resource_type"]), "resource_id": rid}
        raw_params["resource_id"] = rid
    elif fhir_tool == "fhir_get_resource_history":
        rid = str(parsed_fields.get("id") or parsed_fields.get("resource_id") or "")
        cnt = int(parsed_fields.get("_count") or 50)
        cur = str(parsed_fields.get("_cursor") or "")
        sql_params = {
            "resource_type": str(parsed_fields["resource_type"]),
            "resource_id": rid,
            "count": cnt,
            "cursor": cur,
        }
        raw_params.update({"resource_id": rid, "count": cnt, "cursor": cur})
    elif fhir_tool == "fhir_get_patient_everything":
        sql_params = {
            "resource_types": str(parsed_fields.get("_type") or ""),
            "since": str(parsed_fields.get("_since") or ""),
            "count": int(parsed_fields.get("_count") or 50),
            "cursor": str(parsed_fields.get("_cursor") or ""),
        }
        raw_params["patient_id"] = effective_pid
    elif fhir_tool == "fhir_get_patient_summary":
        sql_params = {}
        raw_params["patient_id"] = effective_pid
    elif fhir_tool == "fhir_upsert_resource":
        res_obj = parsed_fields.get("resource")
        fhir_resource = dict(res_obj) if isinstance(res_obj, dict) else {}
        rid = str(parsed_fields.get("id") or fhir_resource.get("id") or "")
        sql_params = {
            "resource_type": str(parsed_fields["resource_type"]),
            "resource_id": rid,
            "resource_json": json.dumps(fhir_resource, default=str),
            "if_match": str(parsed_fields.get("if_match") or ""),
            "idempotency_key": str(parsed_fields.get("idempotency_key") or ""),
            "confirmed": confirmed,
        }
        raw_params["resource_id"] = rid
    elif fhir_tool == "fhir_start_bulk_export":
        sql_params = {
            "resource_types": str(parsed_fields.get("_type") or ""),
            "since": str(parsed_fields.get("_since") or ""),
            "idempotency_key": str(parsed_fields.get("idempotency_key") or ""),
        }
        raw_params["patient_id"] = effective_pid
    elif fhir_tool == "fhir_get_bulk_export_status":
        sql_params = {"job_id": str(parsed_fields["job_id"])}
    elif fhir_tool == "fhir_download_bulk_export_file":
        rfile = str(parsed_fields["resource_file"])
        sql_params = {"job_id": str(parsed_fields["job_id"]), "resource_type": rfile}
        raw_params["resource_type"] = rfile

    res = await execute_governed_fhir_toolbox_tool(
        fhir_tool,
        sql_params,
        raw_params=raw_params,
        fhir_resource=fhir_resource,
        confirmed=confirmed,
        ctx=ctx,
        profile_id=effective_pid,
        user_id=ctx_uid,
        caller_module_name=__name__,
    )
    if isinstance(res, dict) and res.get("status") == "error":
        err_block = res.get("error") or {}
        err_code = str(res.get("error_code") or err_block.get("error_code") or "CFD-500-001")
        raise YarvelleError(
            err_code,
            detail=str(err_block.get("diagnostics") or "FHIR operation failed."),
            context={
                "fhir_issue_code": err_block.get("issue_code"),
                "operation_outcome": err_block.get("operation_outcome"),
            },
        )
    if isinstance(res, dict) and isinstance(res.get("result"), dict):
        return dict(res["result"])
    return dict(res) if isinstance(res, dict) else {"result": res}


async def invoke_api_mcp_wrapper(
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    ctx: Any = None,
) -> Dict[str, Any]:
    """Validates shared contract and executes the governed Carefold API <-> MCP operation."""
    contract = get_api_mcp_contract(tool_name)

    try:
        validated = contract.input_model.model_validate(args or {})
    except ValidationError as val_err:
        raise YarvelleError(
            "YRV-100-003",
            detail=str(val_err),
            cause=val_err,
        ) from val_err

    if contract.spec.human_decision_only and _extract_principal(ctx) in _AGENT_PRINCIPALS:
        raise YarvelleError(
            "YRV-300-013",
            detail=(
                "Autonomous agent principals cannot approve or reject pending approvals; "
                "explicit human steward decision is required."
            ),
        )

    parsed_fields = validated.model_dump(by_alias=True, exclude_unset=False)
    explicit_fields = _resolve_explicit_field_names(contract, validated)

    if contract.spec.fhir_toolbox_tool is not None:
        return await _invoke_fhir_contract(contract, parsed_fields, ctx)

    ctx_pid = getattr(ctx, "profile_id", None) if ctx is not None else None
    ctx_uid = getattr(ctx, "user_id", None) if ctx is not None else None
    effective_pid = str(ctx_pid).strip() if isinstance(ctx_pid, str) and ctx_pid.strip() else None
    risk_tier = "read" if contract.spec.risk_tier == "read" else "write_local"

    result = await execute_governed_db_operation(
        f"api.{tool_name}",
        {
            "parsed_fields": parsed_fields,
            "explicit_fields": sorted(explicit_fields),
        },
        ctx=ctx,
        profile_id=effective_pid,
        user_id=ctx_uid,
        risk_tier=risk_tier,
        caller_module_name=__name__,
    )
    return dict(result) if isinstance(result, dict) else {"result": result}


def _make_tool_executor(
    tool_name: str,
) -> Callable[[Dict[str, Any], Any], Coroutine[Any, Any, Dict[str, Any]]]:
    async def _executor(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        return await invoke_api_mcp_wrapper(tool_name, args, ctx)

    _executor.__name__ = f"execute_{tool_name}"
    _executor.__qualname__ = f"execute_{tool_name}"
    _executor.__doc__ = f"Declarative MCP parity executor for `{tool_name}` (#344)."
    return _executor


for _spec in CANONICAL_DOMAIN_ROUTE_SPECS:
    globals()[f"execute_{_spec.tool_name}"] = _make_tool_executor(_spec.tool_name)


def __getattr__(name: str) -> Any:
    if name in _SPEC_ATTR_TO_TOOL:
        from carefold.tools import get_health_tool_spec

        return get_health_tool_spec(_SPEC_ATTR_TO_TOOL[name])
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
