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

"""MCP-Native HL7 FHIR R4 Operation Registry — Single Source of Truth (#285).

Defines every Carefold FHIR R4 operation once with:
- Typed input/output JSON Schemas (Draft 2020-12)
- FHIR R4 REST binding (`method`, `path`, media types, `ETag`/`If-Match`, `Idempotency-Key`)
- MCP Tool & Resource binding (`mcp_tool_name`, `mcp_resource_uri_template`, MCP annotations
  `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`)
- Strict `profile_id` tenant isolation (`404 Not Found` on cross-profile references without
  leaking existence) and `ScopeContext` (`health.clinical` vs `health.paperwork`) enforcement
- User confirmation & idempotency gates on write and bulk export operations
- Tamper-evident SHA-256 hash-chained `AuditEventRecord` emission on clinical exports and writes
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import re
import time
from typing import Any, Callable, Coroutine, Dict, FrozenSet, List, Literal, Optional, Sequence, Set, Tuple
import uuid

from fhir.resources.R4B.bundle import Bundle as FhirBundle
from fhir.resources.R4B.capabilitystatement import (
    CapabilityStatement as FhirCapabilityStatement,
)
from fhir.resources.R4B.composition import Composition as FhirComposition
from fhir.resources.R4B.operationoutcome import (
    OperationOutcome as FhirOperationOutcome,
)
from sqlalchemy import asc, desc, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.fhir.sql_pushdown import (
    build_category_sql_filter,
    build_clinical_status_sql_filter,
    build_code_sql_filter,
    build_fhir_date_sql_filters,
    build_fhir_status_sql_filter,
    build_logical_id_sql_filter,
    get_session_dialect_name,
    json_string_expr,
)

from carefold.fhir.registry import (
    CLINICAL_FHIR_RESOURCE_TYPES,
    PAPERWORK_FHIR_RESOURCE_TYPES,
    R4B_ONLY_RESOURCE_TYPES,
    SUPPORTED_FHIR_RESOURCE_TYPES,
    TARGET_FHIR_VERSION,
    extract_effective_iso,
    get_r4_model_class,
    resolve_resource_scope,
    validate_and_normalize_fhir_resource,
)
from carefold.fhir.repository import (
    ensure_canonical_patient_resource,
    get_outbound_references,
    get_resource_version_history,
    upsert_fhir_resource_with_history,
)
from carefold.fhir.terminology import normalize_code_system_uri
from carefold.models import (
    HealthResource,
    HealthResourceCoding,
    HealthResourceVersion,
)
from yarvelle_core.db.models import AuditEventRecord, Job, Profile, utc_now

logger = logging.getLogger("carefold.fhir.operations")

FHIR_JSON_MEDIA_TYPE = "application/fhir+json"
FHIR_NDJSON_MEDIA_TYPE = "application/fhir+ndjson"
PROBLEM_JSON_MEDIA_TYPE = "application/problem+json"

MAX_FHIR_PAGE_COUNT = 100
DEFAULT_FHIR_PAGE_COUNT = 50
MAX_FHIR_WRITE_BYTES = 1_048_576  # 1 MiB
RATE_LIMIT_MAX_REQUESTS = 120
RATE_LIMIT_WINDOW_SECONDS = 60.0

_CURSOR_HMAC_KEY = b"carefold-fhir-r4-opaque-cursor-key-v1"

# Supported R4 (4.0.1) resource types exposed over REST and MCP
REST_SUPPORTED_R4_RESOURCE_TYPES: Tuple[str, ...] = tuple(
    sorted(SUPPORTED_FHIR_RESOURCE_TYPES - R4B_ONLY_RESOURCE_TYPES)
)

_CASE_INSENSITIVE_TYPE_MAP: Dict[str, str] = {
    rt.lower(): rt for rt in REST_SUPPORTED_R4_RESOURCE_TYPES
}

#Vital sign LOINC codes for classifying Vital Signs vs Lab Observations in IPS $summary
_VITAL_SIGN_LOINC_CODES: Set[str] = {
    "85353-1",
    "85354-9",
    "8480-6",
    "8462-4",
    "8867-4",
    "59408-5",
    "2708-6",
    "9279-1",
    "8310-5",
    "8302-2",
    "29463-7",
    "39156-5",
}

# In-memory idempotency cache & rate-limit state (scoped per (profile_id, operation_id, key))
_IDEMPOTENCY_CACHE: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
_RATE_LIMIT_BUCKETS: Dict[str, List[float]] = {}


def reset_fhir_rate_limits_and_idempotency_cache() -> None:
    """Clears in-memory rate-limit windows and idempotency cache (used by tests)."""
    _IDEMPOTENCY_CACHE.clear()
    _RATE_LIMIT_BUCKETS.clear()


def check_fhir_rate_limit(
    profile_id: str,
    limit: int = RATE_LIMIT_MAX_REQUESTS,
    window_seconds: float = RATE_LIMIT_WINDOW_SECONDS,
) -> None:
    """Enforces a per-profile sliding-window rate limit, raising `FhirOperationError(429)` if exceeded."""
    now_mono = time.monotonic()
    key = (profile_id or "anonymous").strip()
    bucket = _RATE_LIMIT_BUCKETS.setdefault(key, [])
    cutoff = now_mono - window_seconds
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    if len(bucket) >= limit:
        raise FhirOperationError(
            status_code=429,
            issue_code="throttled",
            diagnostics="FHIR API rate limit exceeded for profile. Please retry after the current window.",
            title="Too Many Requests",
            headers={"Retry-After": str(int(window_seconds))},
        )
    bucket.append(now_mono)


_FHIR_STATUS_TO_CFD_CODE: Dict[int, str] = {
    400: "CFD-100-001",
    401: "YRV-300-001",
    403: "CFD-300-006",
    404: "CFD-500-001",
    409: "CFD-500-010",
    412: "CFD-500-011",
    413: "CFD-100-012",
    422: "CFD-100-013",
    428: "CFD-700-001",
    429: "CFD-600-002",
    502: "CFD-600-001",
    503: "CFD-600-001",
    504: "CFD-600-001",
}


class FhirOperationError(Exception):
    """Structured error convertible to both FHIR R4 `OperationOutcome` and RFC 9457 `problem+json`."""

    def __init__(
        self,
        status_code: int,
        issue_code: str,
        diagnostics: str,
        *,
        severity: Literal["fatal", "error", "warning", "information"] = "error",
        title: Optional[str] = None,
        instance: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        error_code: Optional[str] = None,
    ) -> None:
        super().__init__(diagnostics)
        from carefold.errors import (
            CAREFOLD_ERROR_TYPE_BASE_URI,
            get_error_catalog,
            register_carefold_error_catalog,
        )

        self.status_code = int(status_code)
        self.issue_code = issue_code
        self.diagnostics = diagnostics
        self.severity = severity
        self.title = title or self._default_title(self.status_code)
        self.instance = instance or "/api/v1/fhir/r4"
        self.headers = dict(headers or {})

        resolved_code = error_code or _FHIR_STATUS_TO_CFD_CODE.get(self.status_code, "CFD-900-001")
        catalog = get_error_catalog()
        spec = catalog.get(resolved_code)
        if spec is None:
            register_carefold_error_catalog()
            spec = catalog.get(resolved_code) or catalog.resolve("YRV-900-001")
        self.error_spec = spec
        self.error_code: str = spec.code
        self.retryable: bool = bool(spec.retryable)
        self._error_system: str = (
            CAREFOLD_ERROR_TYPE_BASE_URI if spec.code.startswith("CFD-") else spec.type_base_uri
        )

    @staticmethod
    def _default_title(status_code: int) -> str:
        titles = {
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            409: "Conflict",
            412: "Precondition Failed",
            413: "Content Too Large",
            422: "Unprocessable Entity",
            428: "Precondition Required",
            429: "Too Many Requests",
        }
        return titles.get(status_code, "FHIR Operation Error")

    def to_problem_details(self) -> Dict[str, Any]:
        """Serializes the error to an RFC 9457 Problem Details JSON object (`application/problem+json`)."""
        return {
            "type": self.error_spec.type_uri(self._error_system),
            "title": self.title,
            "status": self.status_code,
            "detail": self.diagnostics,
            "instance": self.instance,
            "code": self.issue_code,
            "error_code": self.error_code,
            "cfd_code": self.error_code,
            "slug": self.error_spec.slug,
            "retryable": self.retryable,
            "fhir_issue_code": self.issue_code,
        }

    def to_operation_outcome(self) -> Dict[str, Any]:
        """Serializes the error to a validated FHIR R4 `OperationOutcome` with `CFD-XXX-YYY` coding."""
        problem = self.to_problem_details()
        candidate: Dict[str, Any] = {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": self.severity,
                    "code": self.issue_code,
                    "diagnostics": self.diagnostics,
                    "details": {
                        "coding": [
                            {
                                "system": self._error_system,
                                "code": self.error_code,
                                "display": self.error_spec.title,
                            }
                        ],
                        "text": f"[{problem['status']} {problem['title']}] {self.diagnostics}",
                    },
                }
            ],
        }
        validated = FhirOperationOutcome.model_validate(candidate)
        return validated.model_dump(mode="json", exclude_none=True)


@dataclass(frozen=True)
class FhirMcpAnnotations:
    """MCP specification tool annotations for safety and agent hint propagation."""

    readOnlyHint: bool = True
    destructiveHint: bool = False
    idempotentHint: bool = True
    openWorldHint: bool = False

    def to_dict(self) -> Dict[str, bool]:
        return {
            "readOnlyHint": self.readOnlyHint,
            "destructiveHint": self.destructiveHint,
            "idempotentHint": self.idempotentHint,
            "openWorldHint": self.openWorldHint,
        }


@dataclass(frozen=True)
class FhirExecutionContext:
    """Unified execution context shared identically by FastAPI REST routes and MCP tool invocations."""

    profile_id: str
    user_id: Optional[str] = None
    scopes: FrozenSet[str] = field(default_factory=lambda: frozenset({"health.clinical", "health.paperwork"}))
    confirmed: bool = False
    idempotency_key: Optional[str] = None
    if_match: Optional[str] = None
    base_url: str = "http://127.0.0.1:8000/api/v1/fhir/r4"
    taint_flag: Optional[Any] = None
    principal: str = "user"


@dataclass(frozen=True)
class FhirOperationSpec:
    """Single-source-of-truth definition for a FHIR R4 REST endpoint and its MCP tool/resource twin."""

    operation_id: str
    mcp_tool_name: str
    summary: str
    description: str
    rest_method: Literal["GET", "POST", "PUT"]
    rest_path: str
    annotations: FhirMcpAnnotations
    risk_tier: Literal["read", "write_local"]
    requires_confirmation: bool
    scopes: Tuple[str, ...]
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    handler: Callable[[AsyncSession, FhirExecutionContext, Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]
    mcp_resource_uri_template: Optional[str] = None


# ============================================================================
# Section 1: Opaque Cursor Pagination & Search Helpers
# ============================================================================


def encode_opaque_cursor(offset: int, sort_expr: str = "-date") -> str:
    """Encodes a pagination offset and sort expression into an HMAC-authenticated opaque cursor."""
    payload = json.dumps({"o": max(0, int(offset)), "s": str(sort_expr)}, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(_CURSOR_HMAC_KEY, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    token = f"{payload}|{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(token).decode("ascii").rstrip("=")


def decode_opaque_cursor(cursor: Optional[str]) -> Tuple[int, Optional[str]]:
    """Decodes and verifies an opaque cursor, raising `FhirOperationError(400)` if tampered."""
    if not cursor or not str(cursor).strip():
        return 0, None
    clean = str(cursor).strip()
    padding = "=" * ((4 - len(clean) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode((clean + padding).encode("ascii")).decode("utf-8")
        payload_str, sig = raw.rsplit("|", 1)
        expected_sig = hmac.new(_CURSOR_HMAC_KEY, payload_str.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected_sig):
            raise ValueError("Cursor signature mismatch")
        parsed = json.loads(payload_str)
        offset = int(parsed.get("o", 0))
        if offset < 0:
            raise ValueError("Negative cursor offset")
        return offset, parsed.get("s")
    except Exception as exc:
        raise FhirOperationError(
            status_code=400,
            issue_code="invalid",
            diagnostics="Invalid or corrupted pagination _cursor token.",
        ) from exc


def _resolve_canonical_resource_type(raw_type: str) -> str:
    clean = (raw_type or "").strip()
    if clean in R4B_ONLY_RESOURCE_TYPES:
        raise FhirOperationError(
            status_code=400,
            issue_code="not-supported",
            diagnostics=f"Resource type '{clean}' is R4B-only and is not supported by Carefold's FHIR R4 (4.0.1) endpoint.",
        )
    resolved = _CASE_INSENSITIVE_TYPE_MAP.get(clean.lower())
    if not resolved:
        raise FhirOperationError(
            status_code=404,
            issue_code="not-supported",
            diagnostics=f"Unsupported FHIR R4 resource type '{clean}'.",
        )
    return resolved


def _enforce_resource_type_scope(resource_type: str, ctx: FhirExecutionContext) -> str:
    required_scope = resolve_resource_scope(resource_type)
    if required_scope not in ctx.scopes and "health.*" not in ctx.scopes:
        raise FhirOperationError(
            status_code=403,
            issue_code="forbidden",
            diagnostics=(
                f"Scope violation: resource type '{resource_type}' requires scope '{required_scope}', "
                f"which is not granted in the active ScopeContext."
            ),
        )
    return required_scope


def _strip_internal_provenance(fhir_dict: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Returns a spec-clean FHIR R4 resource dict and a boolean indicating whether the record is untrusted."""
    clean = dict(fhir_dict)
    prov = clean.pop("_carefold_provenance", None)
    is_untrusted = False
    if isinstance(clean.get("meta"), dict):
        meta_copy = dict(clean["meta"])
        if meta_copy.pop("trust", None) == "untrusted":
            is_untrusted = True
        clean["meta"] = meta_copy
    if isinstance(prov, dict):
        if prov.get("trust") == "untrusted":
            is_untrusted = True
        src_display = prov.get("source_display") or prov.get("source_name")
        if src_display:
            meta = dict(clean.get("meta") or {})
            meta.setdefault("source", str(src_display))
            clean["meta"] = meta
    return clean, is_untrusted


def _propagate_taint_if_untrusted(ctx: FhirExecutionContext, is_untrusted: bool) -> None:
    if is_untrusted and ctx.taint_flag is not None:
        if hasattr(ctx.taint_flag, "set") and callable(ctx.taint_flag.set):
            ctx.taint_flag.set()


def _extract_logical_fhir_id(row: HealthResource, parsed_data: Dict[str, Any]) -> str:
    if isinstance(parsed_data.get("id"), str) and parsed_data["id"].strip():
        return parsed_data["id"].strip()
    if row.source_id and ":" in row.source_id:
        return row.source_id.split(":", 1)[1].strip()
    return row.source_id or row.id


def _load_clean_fhir_from_row(row: HealthResource) -> Tuple[Dict[str, Any], bool]:
    raw_data = json.loads(row.data) if isinstance(row.data, str) else dict(row.data or {})
    clean, is_untrusted = _strip_internal_provenance(raw_data)
    if row.source_type in ("import", "connector"):
        is_untrusted = True
    canonical_type = _CASE_INSENSITIVE_TYPE_MAP.get((row.resource_type or "").lower(), row.resource_type)
    clean["resourceType"] = canonical_type
    clean["id"] = _extract_logical_fhir_id(row, clean)
    meta = dict(clean.get("meta") or {})
    meta["versionId"] = str(getattr(row, "current_version", None) or meta.get("versionId") or 1)
    if row.updated_at:
        meta["lastUpdated"] = row.updated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    elif "lastUpdated" not in meta:
        meta["lastUpdated"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    clean["meta"] = meta
    return clean, is_untrusted


def _parse_date_filter_token(token: str) -> Tuple[str, datetime]:
    """Parses a FHIR date search parameter (`ge2026-01-01`, `le2026-12-31`, `2026-03-15`) into `(op, dt_utc)`."""
    clean = token.strip()
    op = "eq"
    if len(clean) > 2 and clean[:2].lower() in ("ge", "le", "gt", "lt", "eq", "sa", "eb"):
        op = clean[:2].lower()
        clean = clean[2:].strip()
    if op == "sa":
        op = "gt"
    elif op == "eb":
        op = "lt"

    iso_candidate = clean
    if len(clean) == 10 and clean[4] == "-" and clean[7] == "-":
        if op in ("le", "lt"):
            iso_candidate = f"{clean}T23:59:59.999999+00:00"
        else:
            iso_candidate = f"{clean}T00:00:00+00:00"
    elif clean.endswith("Z"):
        iso_candidate = clean[:-1] + "+00:00"
    elif "T" in clean and "+" not in clean and "-" not in clean[10:]:
        iso_candidate = clean + "+00:00"

    try:
        dt = datetime.fromisoformat(iso_candidate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return op, dt.astimezone(timezone.utc)
    except ValueError as exc:
        raise FhirOperationError(
            status_code=400,
            issue_code="invalid",
            diagnostics="Invalid FHIR date/time filter format; expected ISO-8601 date with optional ge/le/gt/lt prefix.",
        ) from exc


def _matches_date_filters(
    target_dt: Optional[datetime],
    raw_filters: Sequence[str],
) -> bool:
    if not raw_filters:
        return True
    if target_dt is None:
        return False
    aware_dt = target_dt if target_dt.tzinfo else target_dt.replace(tzinfo=timezone.utc)
    aware_dt = aware_dt.astimezone(timezone.utc)

    for raw_tok in raw_filters:
        if not raw_tok or not str(raw_tok).strip():
            continue
        op, bound_dt = _parse_date_filter_token(str(raw_tok))
        if op == "ge" and not (aware_dt >= bound_dt):
            return False
        if op == "gt" and not (aware_dt > bound_dt):
            return False
        if op == "le" and not (aware_dt <= bound_dt):
            return False
        if op == "lt" and not (aware_dt < bound_dt):
            return False
        if op == "eq":
            # Compare YYYY-MM-DD prefix when plain date was supplied
            clean_val = str(raw_tok).strip()
            if clean_val.startswith("eq"):
                clean_val = clean_val[2:].strip()
            if len(clean_val) == 10:
                if aware_dt.strftime("%Y-%m-%d") != clean_val:
                    return False
            elif aware_dt != bound_dt:
                return False
    return True


def _matches_category_filter(resource_dict: Dict[str, Any], category_filter: str) -> bool:
    target = category_filter.strip().lower()
    if not target:
        return True
    if "|" in target:
        _, target = target.split("|", 1)
    cats = resource_dict.get("category")
    if isinstance(cats, dict):
        cats = [cats]
    if not isinstance(cats, list):
        return False
    for cat in cats:
        if isinstance(cat, str) and cat.lower() == target:
            return True
        if isinstance(cat, dict):
            if str(cat.get("text") or "").lower() == target:
                return True
            for coding in cat.get("coding") or []:
                if isinstance(coding, dict):
                    if str(coding.get("code") or "").lower() == target:
                        return True
                    if str(coding.get("display") or "").lower() == target:
                        return True
    return False


def _matches_clinical_status_filter(resource_dict: Dict[str, Any], status_filter: str) -> bool:
    target = status_filter.strip().lower()
    if not target:
        return True
    cs = resource_dict.get("clinicalStatus")
    if isinstance(cs, str):
        return cs.lower() == target
    if isinstance(cs, dict):
        if str(cs.get("text") or "").lower() == target:
            return True
        for coding in cs.get("coding") or []:
            if isinstance(coding, dict) and str(coding.get("code") or "").lower() == target:
                return True
    return False


async def _append_hash_chained_fhir_audit_event(
    session: AsyncSession,
    *,
    ctx: FhirExecutionContext,
    operation_id: str,
    risk_tier: str,
    external_ref: str,
    details: Dict[str, Any],
) -> AuditEventRecord:
    """Appends a tamper-evident SHA-256 hash-chained `AuditEventRecord` (`prev_hash` -> `entry_hash`)."""
    prev_stmt = (
        select(AuditEventRecord)
        .where(AuditEventRecord.profile_id == ctx.profile_id)
        .order_by(desc(AuditEventRecord.ts), desc(AuditEventRecord.id))
        .limit(1)
    )
    prev_row = (await session.execute(prev_stmt)).scalars().first()
    prev_hash = (prev_row.entry_hash if prev_row and prev_row.entry_hash else None) or ("0" * 64)

    now = utc_now()
    record_id = str(uuid.uuid4())
    canonical_details = json.dumps(details, sort_keys=True, default=str)
    payload_hash = hashlib.sha256(canonical_details.encode("utf-8")).hexdigest()
    chain_input = f"{prev_hash}|{record_id}|{now.isoformat()}|{ctx.profile_id}|{operation_id}|{payload_hash}"
    entry_hash = hashlib.sha256(chain_input.encode("utf-8")).hexdigest()

    audit_row = AuditEventRecord(
        id=record_id,
        ts=now,
        profile_id=ctx.profile_id,
        actor_user_id=ctx.user_id,
        principal=ctx.principal,
        event="tool",
        tool=operation_id,
        risk=risk_tier,
        tier=risk_tier,
        decision="allow",
        payload_hash=payload_hash,
        external_ref=external_ref,
        detail_redacted=canonical_details,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
        pack_id="health",
        scope="health.clinical",
    )
    session.add(audit_row)
    await session.flush()
    return audit_row


async def _verify_profile_exists(session: AsyncSession, profile_id: str) -> Profile:
    clean_id = (profile_id or "").strip()
    if not clean_id:
        raise FhirOperationError(
            status_code=400,
            issue_code="required",
            diagnostics="profile_id is required in execution context.",
        )
    profile = (
        await session.execute(select(Profile).where(Profile.id == clean_id))
    ).scalar_one_or_none()
    if profile is None:
        raise FhirOperationError(
            status_code=404,
            issue_code="not-found",
            diagnostics="Requested patient profile was not found.",
        )
    return profile


def _verify_patient_id_matches_profile(requested_patient_id: Optional[str], active_profile_id: str) -> None:
    """Ensures a `Patient/{id}` path/query param matches `active_profile_id`; raises 404 on mismatch (never leaking existence)."""
    if not requested_patient_id:
        return
    clean = requested_patient_id.strip()
    if clean.startswith("Patient/"):
        clean = clean.split("/", 1)[1].strip()
    allowed = {active_profile_id, f"pat-{active_profile_id}"}
    if clean not in allowed:
        raise FhirOperationError(
            status_code=404,
            issue_code="not-found",
            diagnostics=f"Patient/{requested_patient_id} was not found.",
        )


# ============================================================================
# Section 2: Canonical Operation Handlers
# ============================================================================


async def handle_fhir_capabilities(
    session: Optional[AsyncSession],
    ctx: FhirExecutionContext,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Generates the validated HL7 FHIR R4 `CapabilityStatement` (`/api/v1/fhir/r4/metadata`)."""
    check_fhir_rate_limit(ctx.profile_id)
    rest_resources: List[Dict[str, Any]] = []
    search_param_defs = [
        {"name": "patient", "type": "reference", "documentation": "Patient reference filter (scoped to active profile)"},
        {"name": "category", "type": "token", "documentation": "Resource category code or text"},
        {"name": "code", "type": "token", "documentation": "Coded concept filter (system|code or code)"},
        {"name": "date", "type": "date", "documentation": "Effective date filter supporting eq/ge/le/gt/lt prefixes"},
        {"name": "status", "type": "token", "documentation": "Resource lifecycle status filter"},
        {"name": "clinical-status", "type": "token", "documentation": "Clinical status code (active, resolved, inactive)"},
        {"name": "_lastUpdated", "type": "date", "documentation": "Last updated timestamp filter"},
        {"name": "_include", "type": "special", "documentation": "Include linked outbound referenced resources"},
        {"name": "_count", "type": "number", "documentation": "Page size (1..100)"},
        {"name": "_sort", "type": "string", "documentation": "Sort order (date, -date, _lastUpdated, -_lastUpdated)"},
        {"name": "_cursor", "type": "string", "documentation": "Opaque pagination cursor"},
    ]

    for rt in REST_SUPPORTED_R4_RESOURCE_TYPES:
        res_entry: Dict[str, Any] = {
            "type": rt,
            "interaction": [
                {"code": "read"},
                {"code": "vread"},
                {"code": "history-instance"},
                {"code": "search-type"},
                {"code": "create"},
                {"code": "update"},
            ],
            "versioning": "versioned-update",
            "readHistory": True,
            "updateCreate": True,
            "searchParam": search_param_defs,
        }
        if rt == "Patient":
            res_entry["operation"] = [
                {
                    "name": "everything",
                    "definition": "http://hl7.org/fhir/OperationDefinition/Patient-everything",
                    "documentation": "Export complete longitudinal FHIR R4 record for the patient profile.",
                },
                {
                    "name": "summary",
                    "definition": "http://hl7.org/fhir/uv/ips/OperationDefinition/summary",
                    "documentation": "Synthesize an HL7 International Patient Summary (IPS) Document Bundle (LOINC 60591-5).",
                },
                {
                    "name": "export",
                    "definition": "http://hl7.org/fhir/uv/bulkdata/OperationDefinition/patient-export",
                    "documentation": "Asynchronous or streaming FHIR Bulk Data NDJSON export.",
                },
            ]
        rest_resources.append(res_entry)

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    cap_candidate: Dict[str, Any] = {
        "resourceType": "CapabilityStatement",
        "id": "carefold-fhir-r4-server",
        "status": "active",
        "date": now_iso,
        "publisher": "Spectrayan — Carefold Local-First Health Runtime",
        "kind": "instance",
        "software": {
            "name": "Carefold FHIR R4 Server & MCP Operation Registry",
            "version": "1.0.0",
        },
        "implementation": {
            "description": "Carefold Local-First Profile-Scoped HL7 FHIR R4 (4.0.1) Facade",
            "url": ctx.base_url,
        },
        "fhirVersion": TARGET_FHIR_VERSION,
        "format": [FHIR_JSON_MEDIA_TYPE, FHIR_NDJSON_MEDIA_TYPE],
        "rest": [
            {
                "mode": "server",
                "documentation": (
                    "All operations are strictly profile-scoped, authenticated, and generated from Carefold's "
                    "unified MCP-native FHIR Operation Registry."
                ),
                "security": {
                    "cors": False,
                    "description": "Localhost-only by default; requires authenticated session + ScopeContext enforcement.",
                },
                "resource": rest_resources,
                "operation": [
                    {
                        "name": "everything",
                        "definition": "http://hl7.org/fhir/OperationDefinition/Patient-everything",
                        "documentation": "Export complete longitudinal FHIR R4 record for the patient profile.",
                    },
                    {
                        "name": "summary",
                        "definition": "http://hl7.org/fhir/uv/ips/OperationDefinition/summary",
                        "documentation": "Synthesize an HL7 International Patient Summary (IPS) Document Bundle (LOINC 60591-5).",
                    },
                    {
                        "name": "export",
                        "definition": "http://hl7.org/fhir/uv/bulkdata/OperationDefinition/patient-export",
                        "documentation": "Asynchronous or streaming FHIR Bulk Data NDJSON export.",
                    },
                ],
            }
        ],
    }
    validated = FhirCapabilityStatement.model_validate(cap_candidate)
    return validated.model_dump(mode="json", exclude_none=True)


async def handle_fhir_read_resource(
    session: AsyncSession,
    ctx: FhirExecutionContext,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Reads a single canonical FHIR R4 resource by `resource_type` and `id` with `ETag: W/"{versionId}"`."""
    check_fhir_rate_limit(ctx.profile_id)
    await _verify_profile_exists(session, ctx.profile_id)

    resource_type = _resolve_canonical_resource_type(str(params.get("resource_type") or ""))
    _enforce_resource_type_scope(resource_type, ctx)

    logical_id = str(params.get("resource_id") or params.get("id") or "").strip()
    if not logical_id:
        raise FhirOperationError(
            status_code=400,
            issue_code="required",
            diagnostics="Resource logical id is required.",
        )

    if resource_type == "Patient":
        _verify_patient_id_matches_profile(logical_id, ctx.profile_id)
        pat_row = await ensure_canonical_patient_resource(session, profile_id=ctx.profile_id)
        await session.commit()
        clean_res, is_untrusted = _load_clean_fhir_from_row(pat_row)
        clean_res["id"] = ctx.profile_id
        _propagate_taint_if_untrusted(ctx, is_untrusted)
        model_cls = get_r4_model_class("Patient")
        validated = model_cls.model_validate(clean_res).model_dump(mode="json", exclude_none=True)
        return {
            "resource": validated,
            "etag": f'W/"{validated.get("meta", {}).get("versionId", "1")}"',
        }

    dialect = get_session_dialect_name(session)
    stmt = (
        select(HealthResource)
        .where(
            HealthResource.profile_id == ctx.profile_id,
            HealthResource.status != "deleted",
            build_logical_id_sql_filter(resource_type, logical_id, dialect_name=dialect),
        )
        .limit(5)
    )
    matched_row: Optional[HealthResource] = None
    for row in (await session.execute(stmt)).scalars().all():
        try:
            raw_d = json.loads(row.data) if isinstance(row.data, str) else dict(row.data or {})
        except Exception:
            raw_d = {}
        cand_id = _extract_logical_fhir_id(row, raw_d)
        if logical_id in (cand_id, row.id, row.source_id):
            matched_row = row
            break

    if matched_row is None:
        raise FhirOperationError(
            status_code=404,
            issue_code="not-found",
            diagnostics=f"{resource_type}/{logical_id} was not found.",
        )

    clean_res, is_untrusted = _load_clean_fhir_from_row(matched_row)
    _propagate_taint_if_untrusted(ctx, is_untrusted)
    model_cls = get_r4_model_class(resource_type)
    validated = model_cls.model_validate(clean_res).model_dump(mode="json", exclude_none=True)
    version_id = str(validated.get("meta", {}).get("versionId") or getattr(matched_row, "current_version", None) or 1)
    return {
        "resource": validated,
        "etag": f'W/"{version_id}"',
    }


async def handle_fhir_search_resources(
    session: AsyncSession,
    ctx: FhirExecutionContext,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Executes a FHIR R4 search (`GET /{resource_type}` / MCP `fhir_search_resources`) returning `Bundle(type="searchset")`."""
    check_fhir_rate_limit(ctx.profile_id)
    await _verify_profile_exists(session, ctx.profile_id)

    resource_type = _resolve_canonical_resource_type(str(params.get("resource_type") or "Observation"))
    _enforce_resource_type_scope(resource_type, ctx)

    patient_param = params.get("patient") or params.get("subject")
    if patient_param:
        _verify_patient_id_matches_profile(str(patient_param), ctx.profile_id)

    raw_count = params.get("_count") if params.get("_count") is not None else params.get("count", DEFAULT_FHIR_PAGE_COUNT)
    try:
        count = int(raw_count) if raw_count is not None else DEFAULT_FHIR_PAGE_COUNT
    except (TypeError, ValueError) as exc:
        raise FhirOperationError(400, "invalid", "_count must be an integer between 1 and 100.") from exc
    if count < 1 or count > MAX_FHIR_PAGE_COUNT:
        raise FhirOperationError(400, "invalid", f"_count must be between 1 and {MAX_FHIR_PAGE_COUNT}.")

    cursor_token = params.get("_cursor") or params.get("cursor")
    offset, cursor_sort = decode_opaque_cursor(cursor_token)
    sort_param = str(params.get("_sort") or params.get("sort") or cursor_sort or "-date").strip()

    dialect = get_session_dialect_name(session)

    if resource_type == "Patient":
        await ensure_canonical_patient_resource(session, profile_id=ctx.profile_id)
        await session.flush()

    # Normalize date & _lastUpdated filters into sequences (validates token syntax upfront)
    raw_date = params.get("date")
    date_filters: List[str] = (
        [str(x) for x in raw_date if x]
        if isinstance(raw_date, (list, tuple))
        else ([str(raw_date)] if raw_date else [])
    )
    raw_lu = params.get("_lastUpdated") or params.get("last_updated")
    lu_filters: List[str] = (
        [str(x) for x in raw_lu if x]
        if isinstance(raw_lu, (list, tuple))
        else ([str(raw_lu)] if raw_lu else [])
    )

    category_filter = str(params.get("category") or "").strip()
    status_filter = str(params.get("status") or "").strip().lower()
    clinical_status_filter = str(params.get("clinical_status") or params.get("clinical-status") or "").strip()

    where_clauses: List[Any] = [
        HealthResource.profile_id == ctx.profile_id,
        HealthResource.status != "deleted",
        func.lower(HealthResource.resource_type) == resource_type.lower(),
    ]

    # Code filter resolution pushed into SQL via HealthResourceCoding + unindexed JSON fallback
    code_param = str(params.get("code") or "").strip()
    if code_param:
        tokens = [t.strip() for t in code_param.split(",") if t.strip()]
        code_or_clauses: List[Any] = []
        for tok in tokens:
            if "|" in tok:
                raw_sys, raw_code = tok.split("|", 1)
                norm_sys = (
                    normalize_code_system_uri(raw_sys.strip(), code=raw_code.strip(), resource_type=resource_type).canonical_system
                    if raw_sys.strip()
                    else ""
                )
                code_or_clauses.append(
                    build_code_sql_filter(
                        raw_code.strip(),
                        system=norm_sys or None,
                        dialect_name=dialect,
                    )
                )
            else:
                code_or_clauses.append(
                    build_code_sql_filter(tok, dialect_name=dialect)
                )
        if code_or_clauses:
            where_clauses.append(or_(*code_or_clauses))

    if status_filter:
        where_clauses.append(build_fhir_status_sql_filter(status_filter, dialect_name=dialect))
    if category_filter:
        where_clauses.append(build_category_sql_filter(category_filter, dialect_name=dialect))
    if clinical_status_filter:
        where_clauses.append(build_clinical_status_sql_filter(clinical_status_filter, dialect_name=dialect))
    if date_filters:
        where_clauses.extend(
            build_fhir_date_sql_filters(HealthResource.effective_at, date_filters, _parse_date_filter_token)
        )
    if lu_filters:
        where_clauses.extend(
            build_fhir_date_sql_filters(HealthResource.updated_at, lu_filters, _parse_date_filter_token)
        )

    count_stmt = select(func.count(HealthResource.id)).where(*where_clauses)
    total_matches = int((await session.execute(count_stmt)).scalar_one() or 0)

    # Deterministic SQL sorting matching FHIR _sort
    reverse_sort = sort_param.startswith("-") or sort_param in ("date", "_lastUpdated")
    if sort_param in ("date", "_lastUpdated", "id"):
        reverse_sort = False

    sort_col = (
        HealthResource.updated_at
        if sort_param in ("_lastUpdated", "-_lastUpdated")
        else HealthResource.effective_at
    )
    logical_id_sort_expr = func.coalesce(
        json_string_expr(HealthResource.data, "id", dialect_name=dialect),
        HealthResource.source_id,
        HealthResource.id,
    )
    if sort_param == "id":
        order_clauses: List[Any] = [asc(logical_id_sort_expr), asc(HealthResource.id)]
    elif sort_param == "-id":
        order_clauses = [desc(logical_id_sort_expr), desc(HealthResource.id)]
    elif reverse_sort:
        order_clauses = [asc(sort_col.is_(None)), desc(sort_col), desc(logical_id_sort_expr)]
    else:
        order_clauses = [asc(sort_col.is_not(None)), asc(sort_col), asc(logical_id_sort_expr)]

    page_stmt = (
        select(HealthResource)
        .where(*where_clauses)
        .order_by(*order_clauses)
        .limit(count)
        .offset(offset)
    )
    page_rows = list((await session.execute(page_stmt)).scalars().all())

    entries: List[Dict[str, Any]] = []
    included_keys: Set[Tuple[str, str]] = set()
    include_param = str(params.get("_include") or params.get("include") or "").strip()

    for row in page_rows:
        clean_res, is_untrusted = _load_clean_fhir_from_row(row)
        _propagate_taint_if_untrusted(ctx, is_untrusted)
        model_cls = get_r4_model_class(resource_type)
        validated_res = model_cls.model_validate(clean_res).model_dump(mode="json", exclude_none=True)
        logical_id = validated_res["id"]
        entries.append({
            "fullUrl": f"{ctx.base_url}/{resource_type}/{logical_id}",
            "resource": validated_res,
            "search": {"mode": "match"},
        })
        included_keys.add((resource_type, logical_id))

        # Handle _include outbound references within the same profile via targeted SQL lookup
        if include_param:
            inc_parts = include_param.split(":")
            inc_src = inc_parts[0].strip() if len(inc_parts) >= 1 else "*"
            inc_field = inc_parts[1].strip() if len(inc_parts) >= 2 else None
            if inc_src in ("*", resource_type):
                out_refs = await get_outbound_references(
                    session,
                    profile_id=ctx.profile_id,
                    source_resource_id=row.id,
                    reference_field=inc_field if inc_field and inc_field != "*" else None,
                )
                for ref in out_refs:
                    t_type = _CASE_INSENSITIVE_TYPE_MAP.get((ref.target_type or "").lower(), ref.target_type)
                    if not t_type or (t_type, ref.target_id) in included_keys:
                        continue
                    # Enforce scope on included target resource
                    req_scope = resolve_resource_scope(t_type)
                    if req_scope not in ctx.scopes and "health.*" not in ctx.scopes:
                        continue
                    inc_stmt = (
                        select(HealthResource)
                        .where(
                            HealthResource.profile_id == ctx.profile_id,
                            HealthResource.status != "deleted",
                            build_logical_id_sql_filter(t_type, ref.target_id, dialect_name=dialect),
                        )
                        .limit(5)
                    )
                    for cand_row in (await session.execute(inc_stmt)).scalars().all():
                        cand_clean, cand_untrusted = _load_clean_fhir_from_row(cand_row)
                        if ref.target_id in (cand_clean["id"], cand_row.id, cand_row.source_id):
                            _propagate_taint_if_untrusted(ctx, cand_untrusted)
                            t_cls = get_r4_model_class(t_type)
                            val_target = t_cls.model_validate(cand_clean).model_dump(mode="json", exclude_none=True)
                            entries.append({
                                "fullUrl": f"{ctx.base_url}/{t_type}/{val_target['id']}",
                                "resource": val_target,
                                "search": {"mode": "include"},
                            })
                            included_keys.add((t_type, val_target["id"]))
                            break

    next_cursor: Optional[str] = None
    links: List[Dict[str, str]] = [
        {"relation": "self", "url": f"{ctx.base_url}/{resource_type}?_count={count}"}
    ]
    if offset + count < total_matches:
        next_cursor = encode_opaque_cursor(offset + count, sort_param)
        links.append({
            "relation": "next",
            "url": f"{ctx.base_url}/{resource_type}?_count={count}&_cursor={next_cursor}",
        })

    bundle_candidate: Dict[str, Any] = {
        "resourceType": "Bundle",
        "id": f"search-{uuid.uuid4().hex[:12]}",
        "type": "searchset",
        "total": total_matches,
        "link": links,
        "entry": entries,
    }
    validated_bundle = FhirBundle.model_validate(bundle_candidate).model_dump(mode="json", exclude_none=True)
    return validated_bundle


async def handle_fhir_resource_history(
    session: AsyncSession,
    ctx: FhirExecutionContext,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Returns `Bundle(type="history")` from `health_resource_versions` for a single resource."""
    check_fhir_rate_limit(ctx.profile_id)
    await _verify_profile_exists(session, ctx.profile_id)

    resource_type = _resolve_canonical_resource_type(str(params.get("resource_type") or ""))
    _enforce_resource_type_scope(resource_type, ctx)

    logical_id = str(params.get("resource_id") or params.get("id") or "").strip()
    if not logical_id:
        raise FhirOperationError(400, "required", "Resource id is required for _history.")

    raw_count = params.get("_count") if params.get("_count") is not None else params.get("count", DEFAULT_FHIR_PAGE_COUNT)
    count = max(1, min(int(raw_count or DEFAULT_FHIR_PAGE_COUNT), MAX_FHIR_PAGE_COUNT))
    offset, _ = decode_opaque_cursor(params.get("_cursor") or params.get("cursor"))

    dialect = get_session_dialect_name(session)
    target_row: Optional[HealthResource] = None
    stmt = (
        select(HealthResource)
        .where(
            HealthResource.profile_id == ctx.profile_id,
            build_logical_id_sql_filter(resource_type, logical_id, dialect_name=dialect),
        )
        .limit(5)
    )
    for row in (await session.execute(stmt)).scalars().all():
        clean_d, _ = _load_clean_fhir_from_row(row)
        if logical_id in (clean_d["id"], row.id, row.source_id):
            target_row = row
            break

    total_versions = 0
    page_versions: List[HealthResourceVersion] = []
    if target_row is not None:
        v_where = [
            HealthResourceVersion.profile_id == ctx.profile_id,
            HealthResourceVersion.resource_id == target_row.id,
        ]
        total_versions = int(
            (await session.execute(select(func.count(HealthResourceVersion.id)).where(*v_where))).scalar_one() or 0
        )
        if total_versions > 0:
            v_stmt = (
                select(HealthResourceVersion)
                .where(*v_where)
                .order_by(HealthResourceVersion.version_id.asc())
                .limit(count)
                .offset(offset)
            )
            page_versions = list((await session.execute(v_stmt)).scalars().all())

    if total_versions == 0:
        raise FhirOperationError(
            status_code=404,
            issue_code="not-found",
            diagnostics=f"History for {resource_type}/{logical_id} was not found.",
        )
    entries: List[Dict[str, Any]] = []
    model_cls = get_r4_model_class(resource_type)

    for ver in page_versions:
        ver_payload = getattr(ver, "fhir_json", None)
        if ver_payload is None:
            ver_payload = getattr(ver, "data", None)
        raw_snap = json.loads(ver_payload) if isinstance(ver_payload, str) else dict(ver_payload or {})
        clean_snap, is_untrusted = _strip_internal_provenance(raw_snap)
        if getattr(ver, "source_type", None) in ("import", "connector"):
            is_untrusted = True
        _propagate_taint_if_untrusted(ctx, is_untrusted)

        clean_snap["resourceType"] = resource_type
        clean_snap["id"] = logical_id
        meta = dict(clean_snap.get("meta") or {})
        meta["versionId"] = str(ver.version_id)
        ver_ts = getattr(ver, "recorded_at", None) or getattr(ver, "updated_at", None) or getattr(ver, "created_at", None)
        if ver_ts:
            meta["lastUpdated"] = ver_ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        clean_snap["meta"] = meta

        val_snap = model_cls.model_validate(clean_snap).model_dump(mode="json", exclude_none=True)
        method_map = {"create": "POST", "update": "PUT", "merge": "PUT", "delete": "DELETE"}
        ver_op = str(getattr(ver, "operation", None) or getattr(ver, "change_type", None) or "update").lower()
        http_method = method_map.get(ver_op, "PUT")
        entries.append({
            "fullUrl": f"{ctx.base_url}/{resource_type}/{logical_id}/_history/{ver.version_id}",
            "resource": val_snap,
            "request": {
                "method": http_method,
                "url": f"{resource_type}/{logical_id}",
            },
            "response": {
                "status": "200 OK" if http_method != "POST" else "201 Created",
                "etag": f'W/"{ver.version_id}"',
                "lastModified": meta.get("lastUpdated"),
            },
        })

    links: List[Dict[str, str]] = [
        {"relation": "self", "url": f"{ctx.base_url}/{resource_type}/{logical_id}/_history?_count={count}"}
    ]
    next_cursor: Optional[str] = None
    if offset + count < total_versions:
        next_cursor = encode_opaque_cursor(offset + count, "-version")
        links.append({
            "relation": "next",
            "url": f"{ctx.base_url}/{resource_type}/{logical_id}/_history?_count={count}&_cursor={next_cursor}",
        })

    bundle_candidate: Dict[str, Any] = {
        "resourceType": "Bundle",
        "id": f"history-{logical_id}-{uuid.uuid4().hex[:8]}",
        "type": "history",
        "total": total_versions,
        "link": links,
        "entry": entries,
    }
    validated_bundle = FhirBundle.model_validate(bundle_candidate).model_dump(mode="json", exclude_none=True)
    return validated_bundle


async def handle_fhir_patient_everything(
    session: AsyncSession,
    ctx: FhirExecutionContext,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Exports the complete longitudinal chart (`GET /Patient/{id}/$everything` / MCP `fhir_get_patient_everything`)."""
    check_fhir_rate_limit(ctx.profile_id)
    await _verify_profile_exists(session, ctx.profile_id)

    patient_id = str(params.get("patient_id") or ctx.profile_id).strip()
    _verify_patient_id_matches_profile(patient_id, ctx.profile_id)

    raw_count = params.get("_count") if params.get("_count") is not None else params.get("count", DEFAULT_FHIR_PAGE_COUNT)
    count = max(1, min(int(raw_count or DEFAULT_FHIR_PAGE_COUNT), MAX_FHIR_PAGE_COUNT))
    offset, _ = decode_opaque_cursor(params.get("_cursor") or params.get("cursor"))

    type_filter_raw = str(params.get("_type") or params.get("resource_types") or "").strip()
    allowed_types: Optional[Set[str]] = None
    if type_filter_raw:
        allowed_types = {_resolve_canonical_resource_type(t) for t in type_filter_raw.split(",") if t.strip()}
        for rt in allowed_types:
            _enforce_resource_type_scope(rt, ctx)

    since_raw = str(params.get("_since") or params.get("since") or "").strip()
    since_filters = [f"ge{since_raw}" if not since_raw.startswith(("ge", "gt")) else since_raw] if since_raw else []

    await ensure_canonical_patient_resource(session, profile_id=ctx.profile_id)
    await session.flush()

    scope_allowed_types = [
        rt
        for rt in REST_SUPPORTED_R4_RESOURCE_TYPES
        if (allowed_types is None or rt in allowed_types)
        and (resolve_resource_scope(rt) in ctx.scopes or "health.*" in ctx.scopes)
    ]

    if not scope_allowed_types:
        total = 0
        page_rows: List[HealthResource] = []
    else:
        ev_where: List[Any] = [
            HealthResource.profile_id == ctx.profile_id,
            HealthResource.status != "deleted",
            func.lower(HealthResource.resource_type).in_([rt.lower() for rt in scope_allowed_types]),
        ]
        if since_filters:
            ev_where.extend(
                build_fhir_date_sql_filters(
                    func.coalesce(HealthResource.updated_at, HealthResource.effective_at),
                    since_filters,
                    _parse_date_filter_token,
                )
            )
        total = int((await session.execute(select(func.count(HealthResource.id)).where(*ev_where))).scalar_one() or 0)
        stmt = (
            select(HealthResource)
            .where(*ev_where)
            .order_by(desc(HealthResource.effective_at), HealthResource.id)
            .limit(count)
            .offset(offset)
        )
        page_rows = list((await session.execute(stmt)).scalars().all())

    page_entries: List[Dict[str, Any]] = []
    for row in page_rows:
        row_rt = _CASE_INSENSITIVE_TYPE_MAP.get((row.resource_type or "").lower(), row.resource_type)
        if not row_rt:
            continue
        clean_res, is_untrusted = _load_clean_fhir_from_row(row)
        if row_rt == "Patient":
            clean_res["id"] = ctx.profile_id
        _propagate_taint_if_untrusted(ctx, is_untrusted)
        model_cls = get_r4_model_class(row_rt)
        val_res = model_cls.model_validate(clean_res).model_dump(mode="json", exclude_none=True)
        page_entries.append({
            "fullUrl": f"{ctx.base_url}/{row_rt}/{val_res['id']}",
            "resource": val_res,
            "search": {"mode": "match"},
        })
    links: List[Dict[str, str]] = [
        {"relation": "self", "url": f"{ctx.base_url}/Patient/{ctx.profile_id}/$everything?_count={count}"}
    ]
    next_cursor: Optional[str] = None
    if offset + count < total:
        next_cursor = encode_opaque_cursor(offset + count, "-date")
        links.append({
            "relation": "next",
            "url": f"{ctx.base_url}/Patient/{ctx.profile_id}/$everything?_count={count}&_cursor={next_cursor}",
        })

    await _append_hash_chained_fhir_audit_event(
        session,
        ctx=ctx,
        operation_id="fhir_patient_everything",
        risk_tier="read",
        external_ref=f"Patient/{ctx.profile_id}/$everything",
        details={
            "operation": "Patient/$everything",
            "profile_id": ctx.profile_id,
            "total_resources": total,
            "returned_count": len(page_entries),
        },
    )
    await session.commit()

    bundle_candidate: Dict[str, Any] = {
        "resourceType": "Bundle",
        "id": f"everything-{ctx.profile_id[:8]}-{uuid.uuid4().hex[:8]}",
        "type": "searchset",
        "total": total,
        "link": links,
        "entry": page_entries,
    }
    validated_bundle = FhirBundle.model_validate(bundle_candidate).model_dump(mode="json", exclude_none=True)
    return validated_bundle


def _is_vital_sign_observation(resource_dict: Dict[str, Any]) -> bool:
    for cat in resource_dict.get("category") or []:
        if isinstance(cat, dict):
            for coding in cat.get("coding") or []:
                if isinstance(coding, dict) and coding.get("code") == "vital-signs":
                    return True
    for coding in (resource_dict.get("code") or {}).get("coding") or []:
        if isinstance(coding, dict) and str(coding.get("code") or "") in _VITAL_SIGN_LOINC_CODES:
            return True
    return False


def _build_ips_section(
    title: str,
    loinc_code: str,
    loinc_display: str,
    references: List[Dict[str, str]],
) -> Dict[str, Any]:
    section: Dict[str, Any] = {
        "title": title,
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": loinc_code,
                    "display": loinc_display,
                }
            ],
            "text": title,
        },
        "text": {
            "status": "generated",
            "div": f'<div xmlns="http://www.w3.org/1999/xhtml"><p>{title}: {len(references)} item(s)</p></div>',
        },
    }
    if references:
        section["entry"] = references
    else:
        section["emptyReason"] = {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/list-empty-reason",
                    "code": "nilknown",
                    "display": "Nil Known",
                }
            ]
        }
    return section


async def handle_fhir_patient_summary(
    session: AsyncSession,
    ctx: FhirExecutionContext,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Synthesizes a validated HL7 International Patient Summary (IPS) Document Bundle (`GET /Patient/{id}/$summary`)."""
    check_fhir_rate_limit(ctx.profile_id)
    profile = await _verify_profile_exists(session, ctx.profile_id)

    patient_id = str(params.get("patient_id") or ctx.profile_id).strip()
    _verify_patient_id_matches_profile(patient_id, ctx.profile_id)
    _enforce_resource_type_scope("Patient", ctx)

    pat_row = await ensure_canonical_patient_resource(session, profile_id=ctx.profile_id)
    await session.flush()
    pat_clean, pat_untrusted = _load_clean_fhir_from_row(pat_row)
    pat_clean["id"] = ctx.profile_id
    _propagate_taint_if_untrusted(ctx, pat_untrusted)
    validated_patient = get_r4_model_class("Patient").model_validate(pat_clean).model_dump(mode="json", exclude_none=True)

    ips_section_groups: List[Tuple[str, ...]] = [
        ("Condition",),
        ("MedicationRequest", "MedicationStatement"),
        ("AllergyIntolerance",),
        ("Immunization",),
        ("Observation",),
        ("DiagnosticReport",),
        ("Procedure",),
    ]
    section_limit = max(1, min(int(params.get("_count") or params.get("limit_per_section") or 50), MAX_FHIR_PAGE_COUNT))
    rows: List[HealthResource] = []
    for rt_group in ips_section_groups:
        grp_stmt = (
            select(HealthResource)
            .where(
                HealthResource.profile_id == ctx.profile_id,
                HealthResource.status == "active",
                func.lower(HealthResource.resource_type).in_([t.lower() for t in rt_group]),
            )
            .order_by(desc(HealthResource.effective_at), HealthResource.id)
            .limit(section_limit)
        )
        rows.extend((await session.execute(grp_stmt)).scalars().all())

    prob_refs: List[Dict[str, str]] = []
    med_refs: List[Dict[str, str]] = []
    allergy_refs: List[Dict[str, str]] = []
    imm_refs: List[Dict[str, str]] = []
    result_refs: List[Dict[str, str]] = []
    vital_refs: List[Dict[str, str]] = []
    proc_refs: List[Dict[str, str]] = []
    clinical_entries: List[Dict[str, Any]] = []

    ips_types = {
        "Condition",
        "MedicationRequest",
        "MedicationStatement",
        "AllergyIntolerance",
        "Immunization",
        "Observation",
        "DiagnosticReport",
        "Procedure",
    }

    for row in rows:
        row_rt = _CASE_INSENSITIVE_TYPE_MAP.get((row.resource_type or "").lower(), row.resource_type)
        if row_rt not in ips_types:
            continue
        clean_res, is_untrusted = _load_clean_fhir_from_row(row)
        _propagate_taint_if_untrusted(ctx, is_untrusted)
        model_cls = get_r4_model_class(row_rt)
        val_res = model_cls.model_validate(clean_res).model_dump(mode="json", exclude_none=True)
        ref_obj = {"reference": f"{row_rt}/{val_res['id']}"}

        if row_rt == "Condition":
            prob_refs.append(ref_obj)
        elif row_rt in ("MedicationRequest", "MedicationStatement"):
            med_refs.append(ref_obj)
        elif row_rt == "AllergyIntolerance":
            allergy_refs.append(ref_obj)
        elif row_rt == "Immunization":
            imm_refs.append(ref_obj)
        elif row_rt == "Observation":
            if _is_vital_sign_observation(val_res):
                vital_refs.append(ref_obj)
            else:
                result_refs.append(ref_obj)
        elif row_rt == "DiagnosticReport":
            result_refs.append(ref_obj)
        elif row_rt == "Procedure":
            proc_refs.append(ref_obj)

        clinical_entries.append({
            "fullUrl": f"{ctx.base_url}/{row_rt}/{val_res['id']}",
            "resource": val_res,
        })

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    comp_id = f"ips-comp-{ctx.profile_id[:8]}"
    composition_candidate: Dict[str, Any] = {
        "resourceType": "Composition",
        "id": comp_id,
        "status": "final",
        "type": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "60591-5",
                    "display": "Patient summary Document",
                }
            ],
            "text": "International Patient Summary",
        },
        "subject": {
            "reference": f"Patient/{ctx.profile_id}",
            "display": profile.name or "Patient",
        },
        "date": now_iso,
        "author": [{"display": "Carefold Local-First FHIR R4 IPS Generator"}],
        "title": f"International Patient Summary — {profile.name or ctx.profile_id}",
        "section": [
            _build_ips_section("Active Problems", "11450-4", "Problem list - Reported", prob_refs),
            _build_ips_section("Medication Summary", "10160-0", "History of Medication use Narrative", med_refs),
            _build_ips_section("Allergies and Intolerances", "48765-2", "Allergies and adverse reactions Document", allergy_refs),
            _build_ips_section("History of Immunizations", "11369-6", "History of Immunization Narrative", imm_refs),
            _build_ips_section("Diagnostic Results", "30954-2", "Relevant diagnostic tests/laboratory data Narrative", result_refs),
            _build_ips_section("Vital Signs", "8716-3", "Vital signs", vital_refs),
            _build_ips_section("History of Procedures", "47519-4", "History of Procedures Document", proc_refs),
        ],
    }
    validated_comp = FhirComposition.model_validate(composition_candidate).model_dump(mode="json", exclude_none=True)

    bundle_entries: List[Dict[str, Any]] = [
        {"fullUrl": f"{ctx.base_url}/Composition/{comp_id}", "resource": validated_comp},
        {"fullUrl": f"{ctx.base_url}/Patient/{ctx.profile_id}", "resource": validated_patient},
        *clinical_entries,
    ]

    await _append_hash_chained_fhir_audit_event(
        session,
        ctx=ctx,
        operation_id="fhir_patient_summary",
        risk_tier="read",
        external_ref=f"Patient/{ctx.profile_id}/$summary",
        details={
            "operation": "Patient/$summary",
            "profile_id": ctx.profile_id,
            "entry_count": len(bundle_entries),
        },
    )
    await session.commit()

    bundle_candidate: Dict[str, Any] = {
        "resourceType": "Bundle",
        "id": f"ips-{ctx.profile_id[:8]}-{uuid.uuid4().hex[:8]}",
        "identifier": {
            "system": "urn:carefold:ips:bundle",
            "value": f"ips-{ctx.profile_id}-{now_iso[:10]}",
        },
        "type": "document",
        "timestamp": now_iso,
        "entry": bundle_entries,
    }
    return FhirBundle.model_validate(bundle_candidate).model_dump(mode="json", exclude_none=True)


async def handle_fhir_upsert_resource(
    session: AsyncSession,
    ctx: FhirExecutionContext,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """User-confirmed write operation (`POST /{resource_type}` / `PUT /{resource_type}/{id}` / MCP `fhir_upsert_resource`)."""
    check_fhir_rate_limit(ctx.profile_id)
    await _verify_profile_exists(session, ctx.profile_id)

    confirmed = bool(ctx.confirmed or params.get("confirmed") is True)
    if not confirmed:
        raise FhirOperationError(
            status_code=428,
            issue_code="precondition-failed",
            diagnostics=(
                "User confirmation is required for FHIR resource writes. Provide 'X-Carefold-Confirm: true' "
                "or an approved confirmation token."
            ),
        )

    resource_payload = params.get("resource")
    if resource_payload is None and params.get("resource_json"):
        raw_rj = params.get("resource_json")
        if isinstance(raw_rj, str):
            try:
                resource_payload = json.loads(raw_rj)
            except Exception as exc:
                raise FhirOperationError(400, "invalid", "Invalid JSON string in 'resource_json'.") from exc
        elif isinstance(raw_rj, dict):
            resource_payload = raw_rj
    if not isinstance(resource_payload, dict):
        raise FhirOperationError(400, "invalid", "A JSON object 'resource' payload is required.")

    serialized_bytes = len(json.dumps(resource_payload).encode("utf-8"))
    if serialized_bytes > MAX_FHIR_WRITE_BYTES:
        raise FhirOperationError(
            status_code=413,
            issue_code="too-costly",
            diagnostics=f"FHIR resource payload exceeds maximum allowed size of {MAX_FHIR_WRITE_BYTES} bytes.",
        )

    resource_type = _resolve_canonical_resource_type(
        str(params.get("resource_type") or resource_payload.get("resourceType") or "")
    )
    if resource_payload.get("resourceType") and resource_payload["resourceType"] != resource_type:
        raise FhirOperationError(
            status_code=422,
            issue_code="invalid",
            diagnostics=f"Payload resourceType '{resource_payload.get('resourceType')}' does not match endpoint '{resource_type}'.",
        )
    _enforce_resource_type_scope(resource_type, ctx)

    idem_key = (ctx.idempotency_key or str(params.get("idempotency_key") or "")).strip()
    if idem_key:
        cache_key = (ctx.profile_id, "fhir_upsert_resource", idem_key)
        if cache_key in _IDEMPOTENCY_CACHE:
            cached = dict(_IDEMPOTENCY_CACHE[cache_key])
            cached["idempotent_replay"] = True
            return cached

    path_id = str(params.get("resource_id") or "").strip()
    payload_copy = dict(resource_payload)
    payload_copy["resourceType"] = resource_type
    if path_id:
        payload_copy["id"] = path_id
    elif not payload_copy.get("id"):
        payload_copy["id"] = f"{resource_type.lower()}-{uuid.uuid4().hex[:10]}"
    logical_id = str(payload_copy["id"])

    # Enforce optimistic concurrency (If-Match: W/"{versionId}") on existing resource updates
    dialect = get_session_dialect_name(session)
    if_match_raw = (ctx.if_match or str(params.get("if_match") or "")).strip()
    existing_stmt = (
        select(HealthResource)
        .where(
            HealthResource.profile_id == ctx.profile_id,
            HealthResource.status != "deleted",
            build_logical_id_sql_filter(resource_type, logical_id, dialect_name=dialect),
        )
        .limit(5)
    )
    existing_match: Optional[HealthResource] = None
    existing_clean_ver: Optional[str] = None
    for row in (await session.execute(existing_stmt)).scalars().all():
        clean_d, _ = _load_clean_fhir_from_row(row)
        if logical_id in (clean_d["id"], row.id, row.source_id):
            existing_match = row
            existing_clean_ver = str((clean_d.get("meta") or {}).get("versionId") or "1")
            break

    if if_match_raw:
        expected_ver = if_match_raw.replace("W/", "").strip('"').strip()
        if existing_match is None or existing_clean_ver != expected_ver:
            raise FhirOperationError(
                status_code=412,
                issue_code="conflict",
                diagnostics=(
                    f"ETag precondition failed: If-Match '{if_match_raw}' does not match current version "
                    f"of {resource_type}/{logical_id}."
                ),
            )

    try:
        hr_row, ver_row, is_created = await upsert_fhir_resource_with_history(
            session,
            profile_id=ctx.profile_id,
            fhir_data=payload_copy,
            resource_type=resource_type,
            source_type="manual",
            source_ref="fhir_r4_api",
            source_id=f"{resource_type}:{logical_id}",
            actor_user_id=ctx.user_id,
            strict_patient_matching=False,
            enable_dedup=(existing_match is None and not path_id),
        )
        action = "created" if is_created else "updated"
    except ValueError as val_err:
        raise FhirOperationError(
            status_code=422,
            issue_code="invalid",
            diagnostics=f"FHIR R4 validation failed for {resource_type}.",
        ) from val_err

    await _append_hash_chained_fhir_audit_event(
        session,
        ctx=ctx,
        operation_id="fhir_upsert_resource",
        risk_tier="write_local",
        external_ref=f"{resource_type}/{logical_id}",
        details={
            "operation": "fhir_upsert_resource",
            "resource_type": resource_type,
            "logical_id": logical_id,
            "version_id": ver_row.version_id,
            "action": action,
        },
    )
    await session.commit()

    clean_saved, _ = _load_clean_fhir_from_row(hr_row)
    model_cls = get_r4_model_class(resource_type)
    validated_saved = model_cls.model_validate(clean_saved).model_dump(mode="json", exclude_none=True)
    result = {
        "resource": validated_saved,
        "etag": f'W/"{ver_row.version_id}"',
        "location": f"{ctx.base_url}/{resource_type}/{logical_id}/_history/{ver_row.version_id}",
        "action": action,
        "status_code": 201 if action == "created" else 200,
    }
    if idem_key:
        _IDEMPOTENCY_CACHE[(ctx.profile_id, "fhir_upsert_resource", idem_key)] = dict(result)
    return result


async def handle_fhir_bulk_export_start(
    session: AsyncSession,
    ctx: FhirExecutionContext,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Starts an audited Bulk FHIR NDJSON `$export` job (`Patient/{id}/$export` / MCP `fhir_start_bulk_export`)."""
    check_fhir_rate_limit(ctx.profile_id)
    await _verify_profile_exists(session, ctx.profile_id)

    patient_id = str(params.get("patient_id") or ctx.profile_id).strip()
    _verify_patient_id_matches_profile(patient_id, ctx.profile_id)

    confirmed = bool(ctx.confirmed or params.get("confirmed") is True)
    if not confirmed:
        raise FhirOperationError(
            status_code=428,
            issue_code="precondition-failed",
            diagnostics=(
                "Explicit user confirmation is required to start a Bulk FHIR $export. "
                "Provide 'X-Carefold-Confirm: true' or confirmed=True."
            ),
        )

    idem_key = (ctx.idempotency_key or str(params.get("idempotency_key") or "")).strip()
    if idem_key:
        cache_key = (ctx.profile_id, "fhir_bulk_export_start", idem_key)
        if cache_key in _IDEMPOTENCY_CACHE:
            cached = dict(_IDEMPOTENCY_CACHE[cache_key])
            cached["idempotent_replay"] = True
            return cached

    type_filter_raw = str(params.get("_type") or params.get("resource_types") or "").strip()
    allowed_types: Optional[Set[str]] = None
    if type_filter_raw:
        allowed_types = {_resolve_canonical_resource_type(t) for t in type_filter_raw.split(",") if t.strip()}
        for rt in allowed_types:
            _enforce_resource_type_scope(rt, ctx)

    since_raw = str(params.get("_since") or params.get("since") or "").strip()
    since_filters = [f"ge{since_raw}" if not since_raw.startswith(("ge", "gt")) else since_raw] if since_raw else []

    await ensure_canonical_patient_resource(session, profile_id=ctx.profile_id)
    await session.flush()

    export_allowed_types = [
        rt
        for rt in REST_SUPPORTED_R4_RESOURCE_TYPES
        if (allowed_types is None or rt in allowed_types)
        and (resolve_resource_scope(rt) in ctx.scopes or "health.*" in ctx.scopes)
    ]

    grouped_ndjson: Dict[str, List[str]] = {}
    if export_allowed_types:
        export_where: List[Any] = [
            HealthResource.profile_id == ctx.profile_id,
            HealthResource.status != "deleted",
            func.lower(HealthResource.resource_type).in_([rt.lower() for rt in export_allowed_types]),
        ]
        if since_filters:
            export_where.extend(
                build_fhir_date_sql_filters(
                    func.coalesce(HealthResource.updated_at, HealthResource.effective_at),
                    since_filters,
                    _parse_date_filter_token,
                )
            )
        stmt = (
            select(HealthResource)
            .where(*export_where)
            .order_by(HealthResource.resource_type, HealthResource.id)
        )
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            row_rt = _CASE_INSENSITIVE_TYPE_MAP.get((row.resource_type or "").lower(), row.resource_type)
            if not row_rt:
                continue
            clean_res, is_untrusted = _load_clean_fhir_from_row(row)
            if row_rt == "Patient":
                clean_res["id"] = ctx.profile_id
            _propagate_taint_if_untrusted(ctx, is_untrusted)
            model_cls = get_r4_model_class(row_rt)
            val_res = model_cls.model_validate(clean_res).model_dump(mode="json", exclude_none=True)
            grouped_ndjson.setdefault(row_rt, []).append(json.dumps(val_res, separators=(",", ":"), sort_keys=True))

    now = utc_now()
    job_id = str(uuid.uuid4())
    status_url = f"{ctx.base_url}/$export-status/{job_id}"
    output_manifest = [
        {
            "type": rt,
            "url": f"{ctx.base_url}/$export-status/{job_id}/files/{rt}.ndjson",
            "count": len(lines),
        }
        for rt, lines in sorted(grouped_ndjson.items())
    ]
    ndjson_by_type = {rt: "\n".join(lines) + "\n" for rt, lines in sorted(grouped_ndjson.items())}
    combined_ndjson = "".join(ndjson_by_type.values())

    job_payload = {
        "job_id": job_id,
        "profile_id": ctx.profile_id,
        "transaction_time": now.isoformat().replace("+00:00", "Z"),
        "request": f"{ctx.base_url}/Patient/{ctx.profile_id}/$export",
        "status": "completed",
        "progress": 100,
        "output": output_manifest,
        "ndjson_by_type": ndjson_by_type,
    }
    job_row = Job(
        id=job_id,
        profile_id=ctx.profile_id,
        kind="fhir_bulk_export",
        payload=json.dumps(job_payload),
        timezone="UTC",
        next_run_at=now,
        idempotency_key=f"fhir_export:{ctx.profile_id}:{idem_key or job_id}",
        status="completed",
    )
    session.add(job_row)

    await _append_hash_chained_fhir_audit_event(
        session,
        ctx=ctx,
        operation_id="fhir_bulk_export_start",
        risk_tier="write_local",
        external_ref=f"fhir_export:{job_id}",
        details={
            "operation": "Patient/$export",
            "job_id": job_id,
            "profile_id": ctx.profile_id,
            "resource_types": sorted(grouped_ndjson.keys()),
            "total_lines": sum(len(v) for v in grouped_ndjson.values()),
        },
    )
    await session.commit()

    result = {
        "job_id": job_id,
        "status": "completed",
        "progress": 100,
        "status_url": status_url,
        "transactionTime": job_payload["transaction_time"],
        "request": job_payload["request"],
        "requiresAccessToken": True,
        "output": output_manifest,
        "ndjson": combined_ndjson,
        "ndjson_by_type": ndjson_by_type,
    }
    if idem_key:
        _IDEMPOTENCY_CACHE[(ctx.profile_id, "fhir_bulk_export_start", idem_key)] = dict(result)
    return result


async def handle_fhir_bulk_export_status(
    session: AsyncSession,
    ctx: FhirExecutionContext,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Polls an async Bulk `$export` job (`GET /$export-status/{job_id}` / MCP `fhir_get_bulk_export_status`)."""
    check_fhir_rate_limit(ctx.profile_id)
    job_id = str(params.get("job_id") or "").strip()
    if not job_id:
        raise FhirOperationError(400, "required", "job_id is required.")

    stmt = select(Job).where(
        Job.id == job_id,
        Job.profile_id == ctx.profile_id,
        Job.kind == "fhir_bulk_export",
    )
    job_row = (await session.execute(stmt)).scalar_one_or_none()
    if job_row is None:
        # Return 404 without leaking whether job_id exists under another profile
        raise FhirOperationError(404, "not-found", f"Bulk export job '{job_id}' was not found.")

    payload = json.loads(job_row.payload or "{}")
    return {
        "job_id": job_id,
        "status": payload.get("status", job_row.status),
        "progress": payload.get("progress", 100 if job_row.status == "completed" else 50),
        "transactionTime": payload.get("transaction_time"),
        "request": payload.get("request"),
        "requiresAccessToken": True,
        "output": payload.get("output", []),
        "error": [],
    }


async def handle_fhir_bulk_export_download(
    session: AsyncSession,
    ctx: FhirExecutionContext,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Downloads a `.ndjson` file for a completed Bulk `$export` job (`GET /$export-status/{job_id}/files/{resource_type}.ndjson`)."""
    check_fhir_rate_limit(ctx.profile_id)
    job_id = str(params.get("job_id") or "").strip()
    raw_type = str(params.get("resource_type") or "").strip()
    if raw_type.endswith(".ndjson"):
        raw_type = raw_type[: -len(".ndjson")]
    resource_type = _resolve_canonical_resource_type(raw_type)
    _enforce_resource_type_scope(resource_type, ctx)

    stmt = select(Job).where(
        Job.id == job_id,
        Job.profile_id == ctx.profile_id,
        Job.kind == "fhir_bulk_export",
    )
    job_row = (await session.execute(stmt)).scalar_one_or_none()
    if job_row is None:
        raise FhirOperationError(404, "not-found", f"Bulk export job '{job_id}' was not found.")

    payload = json.loads(job_row.payload or "{}")
    ndjson_by_type = payload.get("ndjson_by_type") or {}
    if resource_type not in ndjson_by_type:
        raise FhirOperationError(
            status_code=404,
            issue_code="not-found",
            diagnostics=f"No '{resource_type}.ndjson' file was produced in export job '{job_id}'.",
        )
    content = str(ndjson_by_type[resource_type])
    return {
        "job_id": job_id,
        "resource_type": resource_type,
        "media_type": FHIR_NDJSON_MEDIA_TYPE,
        "ndjson": content,
        "line_count": len([ln for ln in content.splitlines() if ln.strip()]),
    }


# ============================================================================
# Section 3: Declarative Operation Registry & MCP Resource Definitions
# ============================================================================


FHIR_OPERATION_SPECS: Tuple[FhirOperationSpec, ...] = (
    FhirOperationSpec(
        operation_id="fhir_capabilities",
        mcp_tool_name="fhir_get_capabilities",
        summary="Get FHIR R4 CapabilityStatement",
        description=(
            "Return Carefold's HL7 FHIR R4 (4.0.1) CapabilityStatement declaring supported clinical resource types, "
            "search parameters, and system/patient operations ($everything, $summary IPS, $export)."
        ),
        rest_method="GET",
        rest_path="/metadata",
        annotations=FhirMcpAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        risk_tier="read",
        requires_confirmation=False,
        scopes=("health.clinical",),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object", "required": ["resourceType", "fhirVersion", "rest"]},
        handler=handle_fhir_capabilities,
        mcp_resource_uri_template="fhir://profiles/{profile_id}/metadata",
    ),
    FhirOperationSpec(
        operation_id="fhir_search_resources",
        mcp_tool_name="fhir_search_resources",
        summary="Search FHIR R4 Resources",
        description=(
            "Search the active patient profile's FHIR R4 clinical repository by resource_type, category, "
            "code (system|code or code), date range (ge/le/gt/lt), status, clinical_status, _lastUpdated, "
            "_include, _sort, _count, and opaque _cursor. Returns a validated FHIR R4 searchset Bundle."
        ),
        rest_method="GET",
        rest_path="/{resource_type}",
        annotations=FhirMcpAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        risk_tier="read",
        requires_confirmation=False,
        scopes=("health.clinical",),
        input_schema={
            "type": "object",
            "properties": {
                "resource_type": {
                    "type": "string",
                    "description": "FHIR R4 resource type (e.g. 'Observation', 'Condition', 'MedicationRequest', 'Immunization', 'AllergyIntolerance', 'DiagnosticReport', 'Encounter').",
                },
                "category": {"type": "string", "description": "Optional category code or display filter (e.g. 'laboratory', 'vital-signs')."},
                "code": {"type": "string", "description": "Optional code filter ('system|code' or 'code', e.g. 'http://loinc.org|4548-4' or '4548-4')."},
                "date": {"type": "string", "description": "Optional ISO-8601 effective date filter supporting eq/ge/le/gt/lt prefixes (e.g. 'ge2026-01-01')."},
                "status": {"type": "string", "description": "Optional lifecycle status filter (e.g. 'final', 'active', 'completed')."},
                "clinical_status": {"type": "string", "description": "Optional clinicalStatus filter ('active', 'resolved', 'inactive')."},
                "_lastUpdated": {"type": "string", "description": "Optional last-updated timestamp filter with ge/le/gt/lt prefix."},
                "_include": {"type": "string", "description": "Optional outbound reference include expression (e.g. 'DiagnosticReport:result')."},
                "_sort": {"type": "string", "description": "Sort order ('date', '-date', '_lastUpdated', '-_lastUpdated').", "default": "-date"},
                "_count": {"type": "integer", "description": "Maximum entries per page (1..100).", "default": 50},
                "_cursor": {"type": "string", "description": "Opaque pagination cursor from a previous Bundle."},
            },
            "required": ["resource_type"],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "required": ["resourceType", "type", "total"]},
        handler=handle_fhir_search_resources,
    ),
    FhirOperationSpec(
        operation_id="fhir_read_resource",
        mcp_tool_name="fhir_read_resource",
        summary="Read FHIR R4 Resource by ID",
        description=(
            "Read a single canonical FHIR R4 resource by resource_type and logical id within the active "
            "patient profile, returning the validated resource and its weak ETag (W/\"{versionId}\")."
        ),
        rest_method="GET",
        rest_path="/{resource_type}/{id}",
        annotations=FhirMcpAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        risk_tier="read",
        requires_confirmation=False,
        scopes=("health.clinical",),
        input_schema={
            "type": "object",
            "properties": {
                "resource_type": {"type": "string", "description": "FHIR R4 resource type (e.g. 'Observation', 'Patient')."},
                "resource_id": {"type": "string", "description": "Logical FHIR resource ID."},
            },
            "required": ["resource_type", "resource_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "required": ["resource", "etag"]},
        handler=handle_fhir_read_resource,
        mcp_resource_uri_template="fhir://profiles/{profile_id}/{resource_type}/{id}",
    ),
    FhirOperationSpec(
        operation_id="fhir_resource_history",
        mcp_tool_name="fhir_get_resource_history",
        summary="Get FHIR R4 Resource Version History (_history)",
        description=(
            "Retrieve the immutable version history Bundle (type='history') for a specific FHIR R4 resource "
            "in the active patient profile, ordered from newest to oldest revision."
        ),
        rest_method="GET",
        rest_path="/{resource_type}/{id}/_history",
        annotations=FhirMcpAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        risk_tier="read",
        requires_confirmation=False,
        scopes=("health.clinical",),
        input_schema={
            "type": "object",
            "properties": {
                "resource_type": {"type": "string", "description": "FHIR R4 resource type."},
                "resource_id": {"type": "string", "description": "Logical FHIR resource ID."},
                "count": {"type": "integer", "description": "Maximum revisions per page (1..100).", "default": 50},
                "cursor": {"type": "string", "description": "Opaque pagination cursor."},
            },
            "required": ["resource_type", "resource_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "required": ["resourceType", "type", "total", "entry"]},
        handler=handle_fhir_resource_history,
    ),
    FhirOperationSpec(
        operation_id="fhir_patient_everything",
        mcp_tool_name="fhir_get_patient_everything",
        summary="Export Patient Longitudinal Record ($everything)",
        description=(
            "Execute the FHIR R4 Patient/$everything operation for the active profile, returning a longitudinal "
            "searchset Bundle across all clinical resource types and recording a hash-chained audit event."
        ),
        rest_method="GET",
        rest_path="/Patient/{id}/$everything",
        annotations=FhirMcpAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        risk_tier="read",
        requires_confirmation=False,
        scopes=("health.clinical",),
        input_schema={
            "type": "object",
            "properties": {
                "_type": {"type": "string", "description": "Optional comma-separated FHIR resource types to include."},
                "_since": {"type": "string", "description": "Optional ISO-8601 timestamp lower bound."},
                "_count": {"type": "integer", "description": "Maximum entries per page (1..100).", "default": 50},
                "_cursor": {"type": "string", "description": "Opaque pagination cursor."},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object", "required": ["resourceType", "type", "total", "entry"]},
        handler=handle_fhir_patient_everything,
    ),
    FhirOperationSpec(
        operation_id="fhir_patient_summary",
        mcp_tool_name="fhir_get_patient_summary",
        summary="Generate HL7 International Patient Summary (IPS $summary)",
        description=(
            "Synthesize a standards-compliant HL7 International Patient Summary (IPS) Document Bundle "
            "(Bundle.type='document') headed by a Composition (LOINC 60591-5) with structured sections for "
            "Active Problems (11450-4), Medications (10160-0), Allergies (48765-2), Immunizations (11369-6), "
            "Results (30954-2), Vital Signs (8716-3), and Procedures (47519-4)."
        ),
        rest_method="GET",
        rest_path="/Patient/{id}/$summary",
        annotations=FhirMcpAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        risk_tier="read",
        requires_confirmation=False,
        scopes=("health.clinical",),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object", "required": ["resourceType", "type", "entry"]},
        handler=handle_fhir_patient_summary,
        mcp_resource_uri_template="fhir://profiles/{profile_id}/Patient/$summary",
    ),
    FhirOperationSpec(
        operation_id="fhir_upsert_resource",
        mcp_tool_name="fhir_upsert_resource",
        summary="Create or Update a FHIR R4 Resource (User-Confirmed Write)",
        description=(
            "Persist a user-intended creation or update of a validated FHIR R4 resource in the active profile's "
            "repository with version history, optimistic concurrency (If-Match ETag), idempotency key support, "
            "and hash-chained audit logging. Requires explicit user confirmation."
        ),
        rest_method="PUT",
        rest_path="/{resource_type}/{id}",
        annotations=FhirMcpAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True),
        risk_tier="write_local",
        requires_confirmation=True,
        scopes=("health.clinical",),
        input_schema={
            "type": "object",
            "properties": {
                "resource_type": {"type": "string", "description": "FHIR R4 resource type."},
                "resource_id": {"type": "string", "description": "Optional logical FHIR resource ID."},
                "resource": {"type": "object", "description": "Complete FHIR R4 JSON resource object."},
                "if_match": {"type": "string", "description": "Optional ETag (W/\"{versionId}\") for optimistic concurrency."},
                "idempotency_key": {"type": "string", "description": "Optional idempotency key for safe retries."},
                "confirmed": {"type": "boolean", "description": "Explicit user confirmation flag (must be true)."},
            },
            "required": ["resource_type", "resource"],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "required": ["resource", "etag", "action"]},
        handler=handle_fhir_upsert_resource,
    ),
    FhirOperationSpec(
        operation_id="fhir_bulk_export_start",
        mcp_tool_name="fhir_start_bulk_export",
        summary="Start Bulk FHIR NDJSON Export ($export)",
        description=(
            "Kick off an audited FHIR Bulk Data ($export) job for the active patient profile, producing "
            "multi-file NDJSON streams grouped by FHIR R4 resource type. Requires explicit user confirmation."
        ),
        rest_method="POST",
        rest_path="/Patient/{id}/$export",
        annotations=FhirMcpAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True),
        risk_tier="write_local",
        requires_confirmation=True,
        scopes=("health.clinical",),
        input_schema={
            "type": "object",
            "properties": {
                "_type": {"type": "string", "description": "Optional comma-separated FHIR R4 resource types to export."},
                "_since": {"type": "string", "description": "Optional ISO-8601 timestamp lower bound."},
                "idempotency_key": {"type": "string", "description": "Optional idempotency key."},
                "confirmed": {"type": "boolean", "description": "Explicit user confirmation flag (must be true)."},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object", "required": ["job_id", "status", "status_url", "output"]},
        handler=handle_fhir_bulk_export_start,
    ),
    FhirOperationSpec(
        operation_id="fhir_bulk_export_status",
        mcp_tool_name="fhir_get_bulk_export_status",
        summary="Check Bulk FHIR Export Job Status",
        description="Poll the status, progress, and output file manifest of an asynchronous Bulk FHIR $export job.",
        rest_method="GET",
        rest_path="/$export-status/{job_id}",
        annotations=FhirMcpAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        risk_tier="read",
        requires_confirmation=False,
        scopes=("health.clinical",),
        input_schema={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Bulk export job UUID returned by fhir_start_bulk_export."},
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "required": ["job_id", "status", "progress", "output"]},
        handler=handle_fhir_bulk_export_status,
    ),
    FhirOperationSpec(
        operation_id="fhir_bulk_export_download",
        mcp_tool_name="fhir_download_bulk_export_file",
        summary="Download Bulk FHIR Export NDJSON File",
        description="Download the generated application/fhir+ndjson lines for a specific resource_type from a completed Bulk $export job.",
        rest_method="GET",
        rest_path="/$export-status/{job_id}/files/{resource_type}.ndjson",
        annotations=FhirMcpAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        risk_tier="read",
        requires_confirmation=False,
        scopes=("health.clinical",),
        input_schema={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Bulk export job UUID."},
                "resource_type": {"type": "string", "description": "FHIR R4 resource type (e.g. 'Observation', 'Patient')."},
            },
            "required": ["job_id", "resource_type"],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "required": ["job_id", "resource_type", "ndjson", "line_count"]},
        handler=handle_fhir_bulk_export_download,
    ),
)

FHIR_OPERATION_REGISTRY: Dict[str, FhirOperationSpec] = {
    spec.operation_id: spec for spec in FHIR_OPERATION_SPECS
}

FHIR_MCP_TOOL_REGISTRY: Dict[str, FhirOperationSpec] = {
    spec.mcp_tool_name: spec for spec in FHIR_OPERATION_SPECS
}


async def execute_fhir_mcp_operation(
    tool_name_or_op_id: str,
    params: Dict[str, Any],
    *,
    session: Optional[AsyncSession] = None,
    profile_id: str,
    user_id: Optional[str] = None,
    scopes: Optional[Sequence[str]] = None,
    confirmed: bool = False,
    taint_flag: Optional[Any] = None,
) -> Dict[str, Any]:
    """Executes a registered FHIR operation via its MCP tool name or operation_id using the canonical handler."""
    spec = FHIR_MCP_TOOL_REGISTRY.get(tool_name_or_op_id) or FHIR_OPERATION_REGISTRY.get(tool_name_or_op_id)
    if spec is None:
        raise ValueError(f"Unknown FHIR operation or MCP tool '{tool_name_or_op_id}'.")
    if session is None and spec.operation_id != "fhir_capabilities":
        raise ValueError(f"AsyncSession is required for FHIR operation '{spec.operation_id}'.")

    effective_scopes = frozenset(scopes) if scopes is not None else frozenset({"health.clinical", "health.paperwork"})
    ctx = FhirExecutionContext(
        profile_id=(profile_id or "").strip(),
        user_id=user_id,
        scopes=effective_scopes,
        confirmed=bool(confirmed or params.get("confirmed") is True),
        idempotency_key=params.get("idempotency_key"),
        if_match=params.get("if_match"),
        taint_flag=taint_flag,
        principal="agent",
    )
    return await spec.handler(session, ctx, params)


async def read_fhir_mcp_resource(
    uri_or_session: Any,
    ctx_or_none: Optional[Any] = None,
    maybe_uri: Optional[str] = None,
    *,
    session: Optional[AsyncSession] = None,
    profile_id: Optional[str] = None,
    user_id: Optional[str] = None,
    scopes: Optional[Sequence[str]] = None,
    taint_flag: Optional[Any] = None,
) -> Dict[str, Any]:
    """Resolves a read-only `fhir://profiles/{profile_id}/...` MCP Resource URI via the Operation Registry."""
    if isinstance(uri_or_session, str):
        clean_uri = uri_or_session.strip()
        resolved_session = session
        resolved_profile_id = str(profile_id or "").strip()
        resolved_user_id = user_id
        resolved_scopes = scopes
        resolved_taint = taint_flag
    else:
        resolved_session = uri_or_session
        clean_uri = str(maybe_uri or "").strip()
        resolved_profile_id = getattr(ctx_or_none, "profile_id", "") or str(profile_id or "").strip()
        resolved_user_id = getattr(ctx_or_none, "user_id", None) or user_id
        resolved_scopes = getattr(ctx_or_none, "scopes", None) or scopes
        resolved_taint = getattr(ctx_or_none, "taint_flag", None) or taint_flag

    if resolved_session is None:
        raise ValueError("AsyncSession is required for read_fhir_mcp_resource.")

    def _enforce_uri_profile(uri_prof_id: str) -> None:
        if uri_prof_id != resolved_profile_id:
            raise FhirOperationError(
                status_code=403,
                issue_code="forbidden",
                diagnostics="Cross-profile MCP FHIR resource URI access is forbidden.",
            )

    m_meta = re.match(r"^fhir://profiles/([^/]+)/metadata$", clean_uri)
    if m_meta:
        _enforce_uri_profile(m_meta.group(1))
        return await execute_fhir_mcp_operation(
            "fhir_get_capabilities",
            {},
            session=resolved_session,
            profile_id=resolved_profile_id,
            user_id=resolved_user_id,
            scopes=resolved_scopes,
            taint_flag=resolved_taint,
        )

    m_ips = re.match(r"^fhir://profiles/([^/]+)/Patient/(?:([^/]+)/)?\$summary$", clean_uri)
    if m_ips:
        _enforce_uri_profile(m_ips.group(1))
        if m_ips.group(2):
            _enforce_uri_profile(m_ips.group(2))
        return await execute_fhir_mcp_operation(
            "fhir_get_patient_summary",
            {"patient_id": m_ips.group(1)},
            session=resolved_session,
            profile_id=resolved_profile_id,
            user_id=resolved_user_id,
            scopes=resolved_scopes,
            taint_flag=resolved_taint,
        )

    m_res = re.match(r"^fhir://profiles/([^/]+)/([A-Za-z]+)/([^/]+)$", clean_uri)
    if m_res:
        _enforce_uri_profile(m_res.group(1))
        return await execute_fhir_mcp_operation(
            "fhir_read_resource",
            {"resource_type": m_res.group(2), "resource_id": m_res.group(3)},
            session=resolved_session,
            profile_id=resolved_profile_id,
            user_id=resolved_user_id,
            scopes=resolved_scopes,
            taint_flag=resolved_taint,
        )

    raise FhirOperationError(404, "not-found", f"Unsupported MCP FHIR resource URI '{clean_uri}'.")


__all__ = [
    "DEFAULT_FHIR_PAGE_COUNT",
    "FHIR_JSON_MEDIA_TYPE",
    "FHIR_MCP_TOOL_REGISTRY",
    "FHIR_NDJSON_MEDIA_TYPE",
    "FHIR_OPERATION_REGISTRY",
    "FHIR_OPERATION_SPECS",
    "MAX_FHIR_PAGE_COUNT",
    "MAX_FHIR_WRITE_BYTES",
    "PROBLEM_JSON_MEDIA_TYPE",
    "REST_SUPPORTED_R4_RESOURCE_TYPES",
    "FhirExecutionContext",
    "FhirMcpAnnotations",
    "FhirOperationError",
    "FhirOperationSpec",
    "check_fhir_rate_limit",
    "decode_opaque_cursor",
    "encode_opaque_cursor",
    "execute_fhir_mcp_operation",
    "handle_fhir_bulk_export_download",
    "handle_fhir_bulk_export_start",
    "handle_fhir_bulk_export_status",
    "handle_fhir_capabilities",
    "handle_fhir_patient_everything",
    "handle_fhir_patient_summary",
    "handle_fhir_read_resource",
    "handle_fhir_resource_history",
    "handle_fhir_search_resources",
    "handle_fhir_upsert_resource",
    "read_fhir_mcp_resource",
    "reset_fhir_rate_limits_and_idempotency_cache",
]
