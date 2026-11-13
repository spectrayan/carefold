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

"""Carefold clinical pack registration and governed MCP DB Toolbox hooks (#344).

All Carefold agent database reads and writes execute through `yarvelle_core.tools.mcp_db_toolbox`
(`McpDatabaseToolbox`) using declarative SQL statements in `carefold/resources/db_tools.yaml`,
the dynamic AST-sandboxed tools (`db_inspect_schema`, `db_execute_query`, `db_mutate_records`),
and governed domain hooks registered in this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Set, Tuple
import uuid
import weakref

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from yarvelle_core.db.session import get_session_factory as _DEFAULT_CORE_GET_SESSION_FACTORY
import yarvelle_core.tools.mcp_db_toolbox as core_toolbox

logger = logging.getLogger(__name__)

CAREFOLD_DB_TOOLS_YAML = (
    Path(__file__).resolve().parents[1] / "resources" / "db_tools.yaml"
)

LOINC_VITAL_MAP: Dict[str, Tuple[str, str, str]] = {
    "blood_pressure": (
        "85354-9",
        "Blood pressure panel with all children optional",
        "mmHg",
    ),
    "heart_rate": ("8867-4", "Heart rate", "bpm"),
    "blood_glucose": ("2339-0", "Glucose [Mass/volume] in Blood", "mg/dL"),
    "spo2": ("2708-6", "Oxygen saturation in Arterial blood", "%"),
    "weight": ("29463-7", "Body weight", "kg"),
    "height": ("8302-2", "Body height", "cm"),
    "temperature": ("8310-5", "Body temperature", "Cel"),
}

DomainDbHandlerFn = Callable[
    [AsyncSession, Dict[str, Any], Optional[str], Optional[str], Any],
    Awaitable[Any],
]

_REGISTERED = False
_PROFILE_LISTENER_INSTALLED = False
_TOOLBOX_AUTO_STUB_PROFILE_IDS: Set[str] = set()
_DOMAIN_DB_HANDLERS: Dict[str, DomainDbHandlerFn] = {}
_DOMAIN_PRESERVE_AUTO_STUB: Set[str] = set()


def _install_profile_auto_stub_listener() -> None:
    """Tags Profile IDs synthesized by McpDatabaseToolbox._resolve_and_ensure_profile_id."""
    global _PROFILE_LISTENER_INSTALLED
    if _PROFILE_LISTENER_INSTALLED:
        return
    from yarvelle_core.db.models import Profile

    @event.listens_for(Profile, "init")
    def _on_profile_init(target: Any, args: Any, kwargs: Any) -> None:
        raw_id = kwargs.get("id") if isinstance(kwargs, dict) else None
        if not raw_id:
            return
        for depth in range(1, 16):
            try:
                frame = sys._getframe(depth)
            except ValueError:
                break
            if frame.f_code.co_name == "_resolve_and_ensure_profile_id":
                _TOOLBOX_AUTO_STUB_PROFILE_IDS.add(str(raw_id))
                break

    _PROFILE_LISTENER_INSTALLED = True


async def cleanup_toolbox_auto_stub(
    session: AsyncSession, profile_id: Optional[str]
) -> bool:
    """Removes a transient auto-stub Profile created by _resolve_and_ensure_profile_id if unseeded."""
    if not profile_id or not str(profile_id).strip():
        return False
    from yarvelle_core.db.models import Profile

    clean_pid = str(profile_id).strip()
    if clean_pid not in _TOOLBOX_AUTO_STUB_PROFILE_IDS:
        return False
    _TOOLBOX_AUTO_STUB_PROFILE_IDS.discard(clean_pid)
    prof = await session.get(Profile, clean_pid)
    if prof is not None:
        await session.delete(prof)
        await session.flush()
        return True
    return False


def register_domain_db_handler(
    operation_id: str,
    handler: DomainDbHandlerFn,
    *,
    preserve_auto_stub: bool = False,
) -> None:
    """Registers an AsyncSession handler invoked via carefold_domain_read / carefold_domain_write."""
    clean_op = operation_id.strip()
    _DOMAIN_DB_HANDLERS[clean_op] = handler
    if preserve_auto_stub:
        _DOMAIN_PRESERVE_AUTO_STUB.add(clean_op)
    else:
        _DOMAIN_PRESERVE_AUTO_STUB.discard(clean_op)


def _parse_iso_datetime(value: Any, fallback: Optional[datetime] = None) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except Exception:
            pass
    return fallback if fallback is not None else datetime.now(timezone.utc)


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", text).strip("-").lower()
    return cleaned or "note"


async def _hook_upsert_clinical_note(
    tool_name: str,
    exec_params: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    session: AsyncSession,
) -> Dict[str, Any]:
    """Upsert a clinical note by (profile_id, slug), enqueue search indexing, and mirror markdown."""
    from carefold.db.models import Job, Note
    from carefold.i18n.locale import normalize_text_nfc

    title = normalize_text_nfc(str(exec_params.get("title") or "").strip())
    content = normalize_text_nfc(str(exec_params.get("content") or "").strip())
    if not title or not content:
        raise ValueError("Both 'title' and 'content' must be non-empty.")

    raw_slug = str(exec_params.get("slug") or "").strip()
    slug = _slugify(raw_slug if raw_slug else title)
    note_type = str(exec_params.get("note_type") or "visit").strip().lower()
    tags_raw = exec_params.get("tags_json")
    if isinstance(tags_raw, list):
        tags_json = json.dumps(tags_raw)
    elif isinstance(tags_raw, str) and tags_raw.strip().startswith("["):
        tags_json = tags_raw.strip()
    else:
        tags_json = "[]"

    existing_note = (
        await session.execute(
            select(Note).where(Note.profile_id == profile_id, Note.slug == slug)
        )
    ).scalar_one_or_none()

    now_dt = _parse_iso_datetime(exec_params.get("now"))
    locale = str(exec_params.get("locale") or "en-US")

    if existing_note is not None:
        existing_note.title = title
        existing_note.type = note_type
        existing_note.content = content
        existing_note.tags_json = tags_json
        existing_note.locale = locale
        if exec_params.get("linked_appointment_id"):
            existing_note.linked_appointment_id = str(
                exec_params["linked_appointment_id"]
            )
        existing_note.updated_at = now_dt
        await session.flush()
        operation = "updated"
        note_id = existing_note.id
    else:
        note_id = str(exec_params.get("id") or uuid.uuid4())
        session.add(
            Note(
                id=note_id,
                user_id=user_id,
                profile_id=profile_id,
                slug=slug,
                title=title,
                type=note_type,
                content=content,
                tags_json=tags_json,
                locale=locale,
                linked_appointment_id=(
                    str(exec_params["linked_appointment_id"])
                    if exec_params.get("linked_appointment_id")
                    else None
                ),
                created_at=now_dt,
                updated_at=now_dt,
            )
        )
        await session.flush()
        operation = "created"

    session.add(
        Job(
            profile_id=profile_id,
            kind="index_doc",
            payload=json.dumps(
                {
                    "doc_id": note_id,
                    "profile_id": profile_id,
                    "source": "clinical_note",
                    "title": title,
                    "content": content,
                }
            ),
            next_run_at=now_dt,
            status="pending",
        )
    )

    ws_root = getattr(exec_params.get("_ctx"), "workspace_root", None)
    if ws_root:
        try:
            notes_dir = Path(ws_root) / "notes"
            notes_dir.mkdir(parents=True, exist_ok=True)
            (notes_dir / f"{slug}.md").write_text(
                (
                    f"---\n"
                    f'title: "{title}"\n'
                    f'created_at: "{now_dt.isoformat()}"\n'
                    f'profile_id: "{profile_id}"\n'
                    f"---\n\n"
                    f"{content}\n"
                ),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("Optional workspace markdown mirror skipped: %s", exc)

    record = {
        "id": note_id,
        "profile_id": profile_id,
        "slug": slug,
        "title": title,
        "type": note_type,
        "locale": locale,
        "updated_at": now_dt.isoformat(),
        "operation": operation,
    }
    return {
        "status": "ok",
        "tool": tool_name,
        "entity": "note",
        "record": record,
    }


async def _hook_record_vital_reading(
    tool_name: str,
    exec_params: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    session: AsyncSession,
) -> Dict[str, Any]:
    """Synthesize an HL7 FHIR R4 LOINC Observation and evaluate clinical vital red flags."""
    from carefold.db.models import HealthResource, Job
    from carefold.fhir.sql_pushdown import build_observation_coding_rows
    from carefold.safety.vitals import check_vitals_red_flags

    vital_type = str(exec_params.get("vital_type") or "").strip().lower()
    if vital_type not in LOINC_VITAL_MAP:
        raise ValueError(
            f"Unsupported vital_type '{vital_type}'. Must be one of: {', '.join(sorted(LOINC_VITAL_MAP))}."
        )
    loinc_code, display_name, default_unit = LOINC_VITAL_MAP[vital_type]
    unit = str(exec_params.get("unit") or default_unit).strip() or default_unit

    now_dt = _parse_iso_datetime(exec_params.get("now"))
    eff_raw = exec_params.get("effective_at")
    effective_dt = _parse_iso_datetime(eff_raw, fallback=now_dt) if eff_raw else now_dt

    vitals_eval_input: Dict[str, Any] = {}
    if vital_type == "blood_pressure":
        sys_val = exec_params.get("systolic")
        dia_val = exec_params.get("diastolic")
        if sys_val is None or dia_val is None:
            raise ValueError(
                "Both 'systolic' and 'diastolic' are required for blood_pressure."
            )
        sys_f, dia_f = float(sys_val), float(dia_val)
        vitals_eval_input.update({"systolic": sys_f, "diastolic": dia_f})
        fhir_payload: Dict[str, Any] = {
            "resourceType": "Observation",
            "status": "final",
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": loinc_code,
                        "display": display_name,
                    }
                ],
                "text": f"Blood Pressure {int(sys_f)}/{int(dia_f)} {unit}",
            },
            "effectiveDateTime": effective_dt.isoformat(),
            "component": [
                {
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": "8480-6",
                                "display": "Systolic blood pressure",
                            }
                        ]
                    },
                    "valueQuantity": {"value": sys_f, "unit": unit},
                },
                {
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": "8462-4",
                                "display": "Diastolic blood pressure",
                            }
                        ]
                    },
                    "valueQuantity": {"value": dia_f, "unit": unit},
                },
            ],
        }
    else:
        val = exec_params.get("value")
        if val is None:
            raise ValueError(
                f"Numeric 'value' is required for vital_type '{vital_type}'."
            )
        val_f = float(val)
        eval_key = "spo2" if vital_type == "oxygen_saturation" else vital_type
        vitals_eval_input.update({eval_key: val_f, "unit": unit})
        fhir_payload = {
            "resourceType": "Observation",
            "status": "final",
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": loinc_code,
                        "display": display_name,
                    }
                ],
                "text": f"{display_name}: {val_f} {unit}",
            },
            "effectiveDateTime": effective_dt.isoformat(),
            "valueQuantity": {"value": val_f, "unit": unit},
        }

    canonical_json = json.dumps(fhir_payload, sort_keys=True)
    content_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    rec_id = str(exec_params.get("id") or uuid.uuid4())

    session.add(
        HealthResource(
            id=rec_id,
            profile_id=profile_id,
            resource_type="observation",
            source_type="manual",
            source_ref="mcp_db_toolbox",
            source_id=rec_id,
            content_hash=content_hash,
            data=canonical_json,
            status="active",
            locale=str(exec_params.get("locale") or "en-US"),
            effective_at=effective_dt,
            recorded_at=now_dt,
            created_at=now_dt,
            updated_at=now_dt,
        )
    )
    coding_rows = build_observation_coding_rows(
        resource_id=rec_id,
        profile_id=str(profile_id),
        fhir_data=fhir_payload,
        resource_type="Observation",
    )
    if coding_rows:
        session.add_all(coding_rows)
    await session.flush()

    red_flags: List[Dict[str, Any]] = []
    rf_result = check_vitals_red_flags(vitals_eval_input)
    if getattr(rf_result, "triggered", False):
        red_flags.append(
            {
                "triggered": True,
                "category": rf_result.category,
                "severity": rf_result.severity,
                "directive": rf_result.directive,
                "prompt_recheck": rf_result.prompt_recheck,
                "details": rf_result.details,
            }
        )

    session.add(
        Job(
            profile_id=profile_id,
            kind="index_doc",
            payload=json.dumps(
                {
                    "doc_id": rec_id,
                    "profile_id": profile_id,
                    "source": "vital_observation",
                    "title": fhir_payload["code"]["text"],
                    "content": canonical_json,
                }
            ),
            next_run_at=now_dt,
            status="pending",
        )
    )

    record = {
        "id": rec_id,
        "profile_id": profile_id,
        "resource_type": "observation",
        "source_type": "manual",
        "effective_at": effective_dt.isoformat(),
        "status": "active",
    }
    return {
        "status": "ok",
        "tool": tool_name,
        "entity": "health_resource",
        "record": record,
        "fhir_resource": fhir_payload,
        "red_flags": red_flags,
    }


async def _hook_fhir_operation_registry(
    tool_name: str,
    exec_params: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    session: AsyncSession,
) -> Dict[str, Any]:
    """Executes an MCP DB Toolbox FHIR R4 tool through the single FHIR Operation Registry (#285, #344)."""
    from carefold.fhir.operations import (
        FHIR_MCP_TOOL_REGISTRY,
        FhirOperationError,
        execute_fhir_mcp_operation,
    )
    from carefold.scope.context import current_scope_context

    await cleanup_toolbox_auto_stub(session, profile_id)

    ctx_obj = exec_params.get("_ctx")
    taint_flag = getattr(ctx_obj, "taint", None) if ctx_obj is not None else None
    extra = getattr(ctx_obj, "extra", None) if ctx_obj is not None else None
    confirmed = bool(
        exec_params.get("confirmed") is True
        or (isinstance(extra, dict) and extra.get("confirmed") is True)
    )

    merged_params = dict(exec_params)
    if isinstance(extra, dict):
        if isinstance(extra.get("fhir_raw_params"), dict):
            merged_params.update(extra["fhir_raw_params"])
        if "fhir_resource" in extra and "resource" not in merged_params:
            merged_params["resource"] = extra["fhir_resource"]

    resolved_scopes: List[str] = ["health.clinical"]
    if isinstance(extra, dict) and extra.get("scopes"):
        resolved_scopes = [str(s) for s in extra["scopes"]]
    elif ctx_obj is not None and getattr(ctx_obj, "scopes", None):
        resolved_scopes = [str(s) for s in getattr(ctx_obj, "scopes")]
    else:
        raw_scope = str(exec_params.get("scope") or "").strip()
        if raw_scope in ("health.paperwork", "health.clinical", "health.*"):
            resolved_scopes = [raw_scope]
        ambient = current_scope_context()
        if ambient is not None and getattr(ambient, "granted_scopes", None):
            resolved_scopes = [str(s) for s in ambient.granted_scopes]
        elif ambient is not None and getattr(ambient, "scope", None):
            resolved_scopes = [str(ambient.scope)]

    op_spec = FHIR_MCP_TOOL_REGISTRY[tool_name]
    annotations_dict = op_spec.annotations.to_dict()
    try:
        clean_pid = str(profile_id or "").strip()
        if user_id and str(user_id).strip():
            from yarvelle_core.api.deps import DEFAULT_STEWARD_USER
            from yarvelle_core.auth.ports import UserProfile
            from yarvelle_core.db.models import Profile, User
            from carefold.api.profiles import get_user_profile_access

            clean_uid = str(user_id).strip()
            prof_row = await session.get(Profile, clean_pid) if clean_pid else None
            if prof_row is None:
                raise FhirOperationError(
                    404, "not-found", "Requested patient profile was not found."
                )
            if clean_uid == DEFAULT_STEWARD_USER.id:
                user_obj = DEFAULT_STEWARD_USER
            else:
                db_user = await session.get(User, clean_uid)
                if db_user is not None:
                    user_obj = UserProfile(
                        id=db_user.id,
                        email=db_user.email,
                        name=getattr(db_user, "name", None) or db_user.email,
                        role=getattr(db_user, "role", None) or "member",
                    )
                else:
                    user_obj = UserProfile(
                        id=clean_uid,
                        email=f"{clean_uid}@local.carefold",
                        name=clean_uid,
                        role="member",
                    )
            if await get_user_profile_access(prof_row, user_obj, session) is None:
                raise FhirOperationError(
                    404, "not-found", "Requested patient profile was not found."
                )

        result = await execute_fhir_mcp_operation(
            tool_name,
            merged_params,
            session=session,
            profile_id=clean_pid,
            user_id=user_id,
            scopes=resolved_scopes,
            confirmed=confirmed,
            taint_flag=taint_flag,
        )
    except FhirOperationError as err:
        return {
            "status": "error",
            "code": err.error_code,
            "error_code": err.error_code,
            "retryable": err.retryable,
            "tool": tool_name,
            "operation_id": op_spec.operation_id,
            "annotations": annotations_dict,
            "_mcp": {
                "tool_name": tool_name,
                "operation_id": op_spec.operation_id,
                "annotations": annotations_dict,
            },
            "error": {
                "code": err.error_code,
                "error_code": err.error_code,
                "retryable": err.retryable,
                "status_code": err.status_code,
                "issue_code": err.issue_code,
                "diagnostics": err.diagnostics,
                "operation_outcome": err.to_operation_outcome(),
                "problem_details": err.to_problem_details(),
            },
        }

    top_level = dict(result) if isinstance(result, dict) else {}
    return {
        **top_level,
        "status": "ok",
        "tool": tool_name,
        "operation_id": op_spec.operation_id,
        "annotations": annotations_dict,
        "_mcp": {
            "tool_name": tool_name,
            "operation_id": op_spec.operation_id,
            "annotations": annotations_dict,
        },
        "entity": "health_resource",
        "result": result,
    }


async def _hook_domain_db_operation(
    tool_name: str,
    exec_params: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    session: AsyncSession,
) -> Dict[str, Any]:
    """Dispatches governed carefold_domain_read / carefold_domain_write operations inside McpDatabaseToolbox."""
    op_id = str(exec_params.get("operation_id") or "").strip()
    handler = _DOMAIN_DB_HANDLERS.get(op_id)
    if handler is None:
        raise ValueError(f"Unknown Carefold governed DB operation '{op_id}'.")

    if op_id not in _DOMAIN_PRESERVE_AUTO_STUB:
        await cleanup_toolbox_auto_stub(session, profile_id)

    ctx_wrapper = exec_params.get("_ctx")
    if ctx_wrapper is not None and hasattr(ctx_wrapper, "_governed_raw_payload"):
        payload = dict(getattr(ctx_wrapper, "_governed_raw_payload"))
        inner_ctx = getattr(ctx_wrapper, "_governed_inner_ctx", None)
    else:
        raw_json = str(exec_params.get("payload_json") or "{}").strip() or "{}"
        parsed = json.loads(raw_json)
        payload = dict(parsed) if isinstance(parsed, dict) else {"value": parsed}
        inner_ctx = ctx_wrapper

    target_pid = str(exec_params.get("target_profile_id") or "").strip()
    if target_pid:
        effective_profile_id: Optional[str] = target_pid
    elif profile_id and not str(profile_id).startswith("__mcp_scope_"):
        effective_profile_id = str(profile_id)
    else:
        effective_profile_id = None

    data = await handler(session, payload, effective_profile_id, user_id, inner_ctx)
    return {
        "status": "ok",
        "tool": tool_name,
        "operation_id": op_id,
        "data": data,
    }


def _resolve_custom_session_factory(ctx: Any, caller_module_name: Optional[str]) -> Any:
    """Detects explicit ctx.session_factory or test-monkeypatched get_session_factory."""
    if ctx is not None:
        direct_sf = getattr(ctx, "session_factory", None)
        if callable(direct_sf):
            return direct_sf
        extra = getattr(ctx, "extra", None)
        if isinstance(extra, dict) and callable(extra.get("session_factory")):
            return extra["session_factory"]

    if caller_module_name:
        mod = sys.modules.get(caller_module_name)
        mod_sf = getattr(mod, "get_session_factory", None) if mod is not None else None
        if callable(mod_sf) and mod_sf is not _DEFAULT_CORE_GET_SESSION_FACTORY:
            return mod_sf()

    cf_sess_mod = sys.modules.get("carefold.db.session")
    cf_sf = getattr(cf_sess_mod, "get_session_factory", None) if cf_sess_mod is not None else None
    if (
        callable(cf_sf)
        and cf_sf is not _DEFAULT_CORE_GET_SESSION_FACTORY
        and core_toolbox.get_session_factory is _DEFAULT_CORE_GET_SESSION_FACTORY
    ):
        try:
            return cf_sf()
        except TypeError:
            pass
    return None


async def execute_governed_db_operation(
    operation_id: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    ctx: Any = None,
    profile_id: Optional[str] = None,
    user_id: Optional[str] = None,
    scope: Optional[str] = None,
    risk_tier: Literal["read", "write_local"] = "read",
    explicit_session: Optional[AsyncSession] = None,
    caller_module_name: Optional[str] = None,
) -> Any:
    """Executes a registered Carefold domain DB operation exclusively through McpDatabaseToolbox."""
    register_carefold_db_toolbox()
    toolbox = core_toolbox.get_db_toolbox()
    tool_name = "carefold_domain_write" if risk_tier != "read" else "carefold_domain_read"

    clean_payload = dict(payload or {})
    ctx_profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    target_pid = (profile_id or "").strip() or (
        str(ctx_profile_id).strip() if isinstance(ctx_profile_id, str) and ctx_profile_id.strip() else ""
    )
    resolved_user_id = user_id if user_id is not None else (getattr(ctx, "user_id", None) if ctx is not None else None)
    resolved_scope = scope or (getattr(ctx, "scope", None) if ctx is not None else None) or "health.clinical"
    sandbox_profile_id = target_pid or f"__mcp_scope_{resolved_user_id or 'anon'}__"

    try:
        serialized_payload = json.dumps(clean_payload, default=str)
    except Exception:
        serialized_payload = "{}"

    envelope_ctx = SimpleNamespace(
        profile_id=sandbox_profile_id,
        user_id=resolved_user_id,
        locale=getattr(ctx, "locale", "en-US") if ctx is not None else "en-US",
        scope=resolved_scope,
        _governed_raw_payload=clean_payload,
        _governed_inner_ctx=ctx,
    )
    tool_params = {
        "operation_id": operation_id,
        "target_profile_id": target_pid,
        "payload_json": serialized_payload,
    }

    active_session = explicit_session or (getattr(ctx, "session", None) if ctx is not None else None)
    if active_session is not None:
        res = await toolbox.execute(
            tool_name,
            tool_params,
            profile_id=sandbox_profile_id,
            user_id=resolved_user_id,
            scope=resolved_scope,
            session=active_session,
            ctx=envelope_ctx,
        )
        return res.get("data")

    custom_factory = _resolve_custom_session_factory(ctx, caller_module_name)
    if custom_factory is not None:
        async with custom_factory() as managed_session:
            res = await toolbox.execute(
                tool_name,
                tool_params,
                profile_id=sandbox_profile_id,
                user_id=resolved_user_id,
                scope=resolved_scope,
                session=managed_session,
                ctx=envelope_ctx,
            )
            return res.get("data")

    res = await toolbox.execute(
        tool_name,
        tool_params,
        profile_id=sandbox_profile_id,
        user_id=resolved_user_id,
        scope=resolved_scope,
        ctx=envelope_ctx,
    )
    return res.get("data")


async def execute_governed_fhir_toolbox_tool(
    fhir_tool_name: str,
    sql_params: Dict[str, Any],
    *,
    raw_params: Optional[Dict[str, Any]] = None,
    fhir_resource: Optional[Dict[str, Any]] = None,
    confirmed: bool = False,
    ctx: Any = None,
    profile_id: Optional[str] = None,
    user_id: Optional[str] = None,
    scope: Optional[str] = None,
    caller_module_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Executes one of the 9 SQL-backed FHIR R4 tools strictly through McpDatabaseToolbox."""
    register_carefold_db_toolbox()
    toolbox = core_toolbox.get_db_toolbox()

    ctx_profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    target_pid = (profile_id or "").strip() or (
        str(ctx_profile_id).strip()
        if isinstance(ctx_profile_id, str) and ctx_profile_id.strip()
        else ""
    )
    resolved_user_id = (
        user_id
        if user_id is not None
        else (getattr(ctx, "user_id", None) if ctx is not None else None)
    )
    resolved_scope = (
        scope
        or (getattr(ctx, "scope", None) if ctx is not None else None)
        or "health.clinical"
    )

    base_extra = dict(getattr(ctx, "extra", None) or {}) if ctx is not None else {}
    if raw_params:
        base_extra["fhir_raw_params"] = dict(raw_params)
    if fhir_resource is not None:
        base_extra["fhir_resource"] = fhir_resource
    if confirmed:
        base_extra["confirmed"] = True

    envelope_ctx = SimpleNamespace(
        profile_id=target_pid,
        user_id=resolved_user_id,
        locale=getattr(ctx, "locale", "en-US") if ctx is not None else "en-US",
        scope=resolved_scope,
        scopes=getattr(ctx, "scopes", None) if ctx is not None else None,
        taint=getattr(ctx, "taint", None) if ctx is not None else None,
        extra=base_extra,
    )

    active_session = getattr(ctx, "session", None) if ctx is not None else None
    if active_session is not None:
        return await toolbox.execute(
            fhir_tool_name,
            sql_params,
            profile_id=target_pid,
            user_id=resolved_user_id,
            scope=resolved_scope,
            session=active_session,
            ctx=envelope_ctx,
        )

    custom_factory = _resolve_custom_session_factory(ctx, caller_module_name)
    if custom_factory is not None:
        async with custom_factory() as managed_session:
            return await toolbox.execute(
                fhir_tool_name,
                sql_params,
                profile_id=target_pid,
                user_id=resolved_user_id,
                scope=resolved_scope,
                session=managed_session,
                ctx=envelope_ctx,
            )

    return await toolbox.execute(
        fhir_tool_name,
        sql_params,
        profile_id=target_pid,
        user_id=resolved_user_id,
        scope=resolved_scope,
        ctx=envelope_ctx,
    )


def register_carefold_db_toolbox() -> None:
    """Idempotently register Carefold's declarative YAML and governed clinical hooks."""
    global _REGISTERED
    _install_profile_auto_stub_listener()
    if _REGISTERED:
        return
    if CAREFOLD_DB_TOOLS_YAML.is_file():
        core_toolbox.register_db_tools_yaml(CAREFOLD_DB_TOOLS_YAML)
    core_toolbox.register_db_tool_hook(
        "upsert_clinical_note", _hook_upsert_clinical_note
    )
    core_toolbox.register_db_tool_hook(
        "record_vital_reading", _hook_record_vital_reading
    )
    core_toolbox.register_db_tool_hook(
        "carefold_domain_read", _hook_domain_db_operation
    )
    core_toolbox.register_db_tool_hook(
        "carefold_domain_write", _hook_domain_db_operation
    )
    from carefold.clinical.api_db_ops import register_api_parity_db_handlers
    from carefold.clinical.tool_db_ops import register_clinical_tool_db_handlers
    from carefold.fhir.operations import FHIR_MCP_TOOL_REGISTRY

    register_clinical_tool_db_handlers(register_domain_db_handler)
    register_api_parity_db_handlers(register_domain_db_handler)

    for fhir_tool_name in FHIR_MCP_TOOL_REGISTRY:
        if fhir_tool_name == "fhir_get_capabilities":
            continue
        core_toolbox.register_db_tool_hook(
            fhir_tool_name, _hook_fhir_operation_registry
        )
    _REGISTERED = True
