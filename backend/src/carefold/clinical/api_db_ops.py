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

"""Governed AsyncSession handlers for 1:1 Carefold API <-> MCP parity operations (#344).

Every handler registered here executes exclusively inside `McpDatabaseToolbox._execute_in_session`
(`carefold_domain_read` / `carefold_domain_write`), invoking the exact FastAPI endpoint
authorization guard (`require_profile_access`) and domain logic over the governed session.
"""

from __future__ import annotations

from datetime import datetime, timezone
import inspect
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response
from yarvelle_core.api.deps import DEFAULT_STEWARD_USER
from yarvelle_core.auth.ports import UserProfile
from yarvelle_core.db.models import Profile, User

from carefold.api.profiles import get_user_profile_access
from carefold.clinical.api_contracts import (
    CANONICAL_DOMAIN_ROUTE_SPECS,
    ApiMcpOperationContract,
    get_api_mcp_contract,
)
from carefold.errors import YarvelleError, get_error_catalog

_HTTP_STATUS_TO_FALLBACK_CODE: Dict[int, str] = {
    400: "YRV-100-002",
    401: "YRV-300-001",
    403: "YRV-300-007",
    404: "YRV-500-002",
    409: "YRV-100-002",
    422: "YRV-100-003",
    429: "CFD-600-002",
}


async def _resolve_mcp_user_profile(
    session: AsyncSession,
    user_id: Optional[str],
    ctx: Any,
) -> UserProfile:
    """Resolves an authenticated `UserProfile` matching `get_current_user` semantics."""
    if ctx is not None:
        direct_user = getattr(ctx, "user", None)
        if isinstance(direct_user, UserProfile):
            return direct_user
        extra = getattr(ctx, "extra", None)
        if isinstance(extra, dict) and isinstance(extra.get("user"), UserProfile):
            return extra["user"]

    clean_uid = str(user_id or "").strip()
    if not clean_uid or clean_uid == DEFAULT_STEWARD_USER.id:
        return DEFAULT_STEWARD_USER

    now_utc = datetime.now(timezone.utc)
    db_user = await session.get(User, clean_uid)
    if db_user is not None:
        return UserProfile(
            id=db_user.id,
            email=db_user.email,
            username=getattr(db_user, "username", None) or db_user.id,
            full_name=getattr(db_user, "full_name", None) or getattr(db_user, "name", None) or db_user.email,
            role=getattr(db_user, "role", None) or "member",
            created_at=getattr(db_user, "created_at", None) or now_utc,
            updated_at=getattr(db_user, "updated_at", None) or now_utc,
        )

    extra = getattr(ctx, "extra", None) if ctx is not None else None
    role = (
        str(extra.get("role") or "member")
        if isinstance(extra, dict)
        else str(getattr(ctx, "role", "member") or "member")
    )
    return UserProfile(
        id=clean_uid,
        email=f"{clean_uid}@local.carefold",
        username=clean_uid,
        full_name=clean_uid,
        role=role,  # type: ignore[arg-type]
        created_at=now_utc,
        updated_at=now_utc,
    )


def _build_synthetic_starlette_request(
    contract: ApiMcpOperationContract,
    path_values: Dict[str, Any],
    ctx: Any,
) -> Request:
    """Constructs a minimal Starlette Request carrying headers and path_params."""
    raw_headers: Dict[str, str] = {}
    if ctx is not None:
        ctx_hdrs = getattr(ctx, "headers", None)
        if isinstance(ctx_hdrs, dict):
            raw_headers.update({str(k).lower(): str(v) for k, v in ctx_hdrs.items()})
        extra = getattr(ctx, "extra", None)
        if isinstance(extra, dict) and isinstance(extra.get("headers"), dict):
            raw_headers.update(
                {str(k).lower(): str(v) for k, v in extra["headers"].items()}
            )
    encoded_headers: List[Tuple[bytes, bytes]] = [
        (k.encode("latin-1"), v.encode("latin-1")) for k, v in raw_headers.items()
    ]
    rendered_path = contract.spec.path
    for pk, pv in path_values.items():
        rendered_path = rendered_path.replace("{" + pk + "}", str(pv))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": contract.spec.method.upper(),
        "scheme": "http",
        "path": rendered_path,
        "raw_path": rendered_path.encode("utf-8"),
        "query_string": b"",
        "headers": encoded_headers,
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 8000),
        "path_params": dict(path_values),
    }
    return Request(scope)


def _normalize_endpoint_output(
    contract: ApiMcpOperationContract,
    raw_result: Any,
) -> Dict[str, Any]:
    """Validates and normalizes endpoint output through the shared OutputModel."""
    if isinstance(raw_result, Response):
        body_bytes = getattr(raw_result, "body", b"") or b""
        content_text = (
            body_bytes.decode("utf-8", errors="replace")
            if isinstance(body_bytes, (bytes, bytearray))
            else str(body_bytes)
        )
        return {
            "content": content_text,
            "media_type": raw_result.media_type,
            "status_code": raw_result.status_code,
        }

    if contract.output_model is not None:
        validated = contract.output_model.model_validate(raw_result)
        return validated.model_dump(mode="json")

    if isinstance(raw_result, BaseModel):
        return raw_result.model_dump(mode="json")

    if isinstance(raw_result, list):
        items = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in raw_result
        ]
        return {"items": items, "count": len(items)}

    if isinstance(raw_result, dict):
        return dict(raw_result)

    return {"result": raw_result}


async def _handle_fhir_verify_profile(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    """Verifies profile access for FHIR /metadata when an explicit profile_id is supplied."""
    clean_pid = (profile_id or str(payload.get("profile_id") or "")).strip()
    prof = await session.get(Profile, clean_pid) if clean_pid else None
    if prof is None:
        raise YarvelleError(
            "CFD-500-001",
            detail="Requested patient profile was not found.",
        )
    user = await _resolve_mcp_user_profile(session, user_id, ctx)
    if await get_user_profile_access(prof, user, session) is None:
        raise YarvelleError(
            "CFD-500-001",
            detail="Requested patient profile was not found.",
        )
    return {"profile_id": prof.id}


async def _execute_contract_in_session(
    tool_name: str,
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    contract = get_api_mcp_contract(tool_name)
    parsed_fields: Dict[str, Any] = dict(payload.get("parsed_fields") or {})
    explicit_fields: Set[str] = set(payload.get("explicit_fields") or ())

    user = await _resolve_mcp_user_profile(session, user_id, ctx)
    endpoint_kwargs: Dict[str, Any] = {}
    path_values: Dict[str, Any] = {}

    # 1. Path parameters
    for pname in contract.path_param_names:
        if pname == "profile_id":
            clean_pid = (profile_id or "").strip()
            if not clean_pid:
                raise YarvelleError(
                    "YRV-100-004",
                    detail="profile_id is required",
                    context={"parameter": "profile_id"},
                )
            endpoint_kwargs["profile_id"] = clean_pid
            path_values["profile_id"] = clean_pid
        elif pname in contract.context_remaps:
            mcp_key = contract.context_remaps[pname]
            val = parsed_fields.get(mcp_key)
            endpoint_kwargs[pname] = val
            path_values[pname] = val
        else:
            val = parsed_fields.get(pname)
            endpoint_kwargs[pname] = val
            path_values[pname] = val

    # 2. Query parameters
    for qname, qdefault in contract.query_param_defaults.items():
        if qname == "profile_id":
            endpoint_kwargs["profile_id"] = (profile_id or "").strip() or qdefault
        elif qname in contract.context_remaps:
            mcp_key = contract.context_remaps[qname]
            endpoint_kwargs[qname] = parsed_fields.get(mcp_key, qdefault)
        else:
            endpoint_kwargs[qname] = parsed_fields.get(qname, qdefault)

    # 3. Header parameters
    ctx_headers: Dict[str, Any] = {}
    if ctx is not None:
        if isinstance(getattr(ctx, "headers", None), dict):
            ctx_headers.update(getattr(ctx, "headers"))
        extra = getattr(ctx, "extra", None)
        if isinstance(extra, dict) and isinstance(extra.get("headers"), dict):
            ctx_headers.update(extra["headers"])
    for hname, hdefault in contract.header_param_defaults.items():
        header_lookup = hname.replace("_", "-").lower()
        matched = next(
            (v for k, v in ctx_headers.items() if str(k).lower() == header_lookup),
            hdefault,
        )
        endpoint_kwargs[hname] = matched

    # 4. Request body Pydantic model
    if contract.body_param_name and contract.body_model is not None:
        body_kwargs: Dict[str, Any] = {}
        any_body_field_set = False
        for bfield in contract.body_model.model_fields:
            if bfield in contract.context_remaps:
                mcp_key = contract.context_remaps[bfield]
                if mcp_key in explicit_fields:
                    body_kwargs[bfield] = parsed_fields[mcp_key]
                    any_body_field_set = True
            elif bfield == "profile_id":
                clean_pid = (profile_id or "").strip()
                if clean_pid:
                    body_kwargs["profile_id"] = clean_pid
            elif bfield == "locale":
                ctx_locale = getattr(ctx, "locale", None) if ctx is not None else None
                if ctx_locale:
                    body_kwargs["locale"] = str(ctx_locale)
            elif bfield == "run_id":
                ctx_run_id = getattr(ctx, "run_id", None) if ctx is not None else None
                if ctx_run_id:
                    body_kwargs["run_id"] = str(ctx_run_id)
            else:
                if bfield in explicit_fields:
                    body_kwargs[bfield] = parsed_fields[bfield]
                    any_body_field_set = True
                elif bfield in parsed_fields and contract.body_model.model_fields[bfield].is_required():
                    body_kwargs[bfield] = parsed_fields[bfield]
                    any_body_field_set = True

        if contract.body_is_optional and not any_body_field_set:
            endpoint_kwargs[contract.body_param_name] = None
        else:
            try:
                endpoint_kwargs[contract.body_param_name] = (
                    contract.body_model.model_validate(body_kwargs)
                )
            except ValidationError as val_err:
                raise YarvelleError(
                    "YRV-100-003",
                    detail=str(val_err),
                    cause=val_err,
                ) from val_err

    # 5. Optional Starlette Request
    if contract.request_param_name:
        endpoint_kwargs[contract.request_param_name] = _build_synthetic_starlette_request(
            contract, path_values, ctx
        )

    # 6. FastAPI Depends(...) resolution (enforces the exact router require_profile_access!)
    for dep in contract.route.dependant.dependencies:
        dep_name = dep.name
        if not dep_name:
            continue
        if dep_name == "db":
            endpoint_kwargs["db"] = session
        elif dep_name in ("user", "_user"):
            endpoint_kwargs[dep_name] = user
        elif dep_name == "profile":
            req_pid = str(endpoint_kwargs.get("profile_id") or profile_id or "").strip()
            if not req_pid:
                raise YarvelleError(
                    "YRV-100-004",
                    detail="profile_id is required",
                    context={"parameter": "profile_id"},
                )
            dep_fn = dep.call
            if inspect.iscoroutinefunction(dep_fn):
                resolved_prof = await dep_fn(profile_id=req_pid, user=user, db=session)
            else:
                resolved_prof = dep_fn(profile_id=req_pid, user=user, db=session)
            endpoint_kwargs["profile"] = resolved_prof
        elif dep_name == "port":
            custom_port = getattr(ctx, "memory_port", None) if ctx is not None else None
            endpoint_kwargs["port"] = custom_port if custom_port is not None else dep.call()
        elif dep_name == "storage":
            custom_storage = getattr(ctx, "storage", None) if ctx is not None else None
            endpoint_kwargs["storage"] = (
                custom_storage if custom_storage is not None else dep.call()
            )

    # Filter kwargs strictly to parameters accepted by endpoint signature
    sig = inspect.signature(contract.endpoint)
    accepts_var_kw = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if not accepts_var_kw:
        endpoint_kwargs = {
            k: v for k, v in endpoint_kwargs.items() if k in sig.parameters
        }

    try:
        if inspect.iscoroutinefunction(contract.endpoint):
            raw_result = await contract.endpoint(**endpoint_kwargs)
        else:
            raw_result = contract.endpoint(**endpoint_kwargs)
    except YarvelleError:
        raise
    except Exception as http_exc:
        status_code = getattr(http_exc, "status_code", None)
        if not isinstance(status_code, int):
            raise
        fallback_code = _HTTP_STATUS_TO_FALLBACK_CODE.get(status_code, "YRV-100-002")
        cat = get_error_catalog()
        if cat.get(fallback_code) is None:
            fallback_code = "YRV-100-002"
        raise YarvelleError(
            fallback_code,
            detail=str(getattr(http_exc, "detail", "Request failed.")),
        ) from http_exc

    return _normalize_endpoint_output(contract, raw_result)


def _make_domain_handler(tool_name: str) -> Callable[..., Any]:
    async def _handler(
        session: AsyncSession,
        payload: Dict[str, Any],
        profile_id: Optional[str],
        user_id: Optional[str],
        ctx: Any,
    ) -> Dict[str, Any]:
        return await _execute_contract_in_session(
            tool_name, session, payload, profile_id, user_id, ctx
        )

    return _handler


def register_api_parity_db_handlers(register_fn: Callable[..., None]) -> None:
    """Registers governed McpDatabaseToolbox handlers for all canonical domain API wrappers."""
    register_fn("api.fhir_verify_profile", _handle_fhir_verify_profile)
    for spec in CANONICAL_DOMAIN_ROUTE_SPECS:
        if spec.fhir_toolbox_tool is not None:
            continue
        register_fn(f"api.{spec.tool_name}", _make_domain_handler(spec.tool_name))


__all__ = ["register_api_parity_db_handlers"]
