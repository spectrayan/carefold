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

"""Local-First HL7 FHIR R4 REST API Router (`/api/v1/fhir/r4`) generated from the MCP Operation Registry (#285).

Exposes:
1. `GET  /api/v1/fhir/r4/metadata` -> `CapabilityStatement` (`application/fhir+json`)
2. `GET  /api/v1/fhir/r4/Patient/{id}/$everything` -> Longitudinal `Bundle(type="searchset")`
3. `GET  /api/v1/fhir/r4/Patient/{id}/$summary` -> HL7 IPS `Bundle(type="document")` (Composition LOINC `60591-5`)
4. `POST /api/v1/fhir/r4/Patient/{id}/$export` & `GET /api/v1/fhir/r4/Patient/{id}/$export` -> Async (`202 Accepted`
   + `Content-Location`) or streaming (`application/fhir+ndjson`) Bulk Data `$export`
5. `GET  /api/v1/fhir/r4/$export-status/{job_id}` -> Async Bulk Data job status manifest
6. `GET  /api/v1/fhir/r4/$export-status/{job_id}/files/{resource_type}.ndjson` -> Bulk Data `.ndjson` file download
7. `GET  /api/v1/fhir/r4/{resource_type}/{id}/_history` -> Version history `Bundle(type="history")`
8. `GET  /api/v1/fhir/r4/{resource_type}/{id}` -> Canonical FHIR R4 resource with `ETag: W/"{versionId}"`
9. `PUT  /api/v1/fhir/r4/{resource_type}/{id}` & `POST /api/v1/fhir/r4/{resource_type}` -> User-confirmed write
   with `If-Match` optimistic concurrency and `Idempotency-Key` support
10. `GET /api/v1/fhir/r4/{resource_type}` -> FHIR R4 search (`Bundle(type="searchset")`) with opaque `_cursor` paging
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.fhir.operations import (
    DEFAULT_FHIR_PAGE_COUNT,
    FHIR_JSON_MEDIA_TYPE,
    FHIR_NDJSON_MEDIA_TYPE,
    FHIR_OPERATION_REGISTRY,
    MAX_FHIR_WRITE_BYTES,
    PROBLEM_JSON_MEDIA_TYPE,
    FhirExecutionContext,
    FhirOperationError,
)
from carefold.scope.context import current_scope_context
from yarvelle_core.api.deps import get_current_user, get_db, resolve_owner_user_id
from yarvelle_core.api.profiles import get_user_profile_access
from yarvelle_core.auth.ports import UserProfile
from yarvelle_core.db.models import Approval, Profile

router = APIRouter(prefix="/fhir/r4", tags=["FHIR R4"])


def _build_error_response(request: Request, err: FhirOperationError) -> Response:
    """Formats a `FhirOperationError` as `application/fhir+json` (`OperationOutcome`) or RFC 9457 `application/problem+json`."""
    accept = (request.headers.get("accept") or "").lower()
    headers = dict(err.headers)
    if PROBLEM_JSON_MEDIA_TYPE in accept and FHIR_JSON_MEDIA_TYPE not in accept:
        problem = err.to_problem_details()
        problem["instance"] = str(request.url.path)
        return JSONResponse(
            status_code=err.status_code,
            content=problem,
            media_type=PROBLEM_JSON_MEDIA_TYPE,
            headers=headers,
        )
    outcome = err.to_operation_outcome()
    if "_problem_details" in outcome:
        outcome["_problem_details"]["instance"] = str(request.url.path)
    return JSONResponse(
        status_code=err.status_code,
        content=outcome,
        media_type=FHIR_JSON_MEDIA_TYPE,
        headers=headers,
    )


async def _resolve_active_profile_and_context(
    request: Request,
    user: UserProfile,
    db: AsyncSession,
    *,
    explicit_profile_id: Optional[str] = None,
    candidate_patient_id: Optional[str] = None,
    confirmed_param: bool = False,
) -> FhirExecutionContext:
    """Resolves the caller's isolated `FhirExecutionContext` without leaking cross-profile existence."""
    header_profile_id = (
        request.headers.get("x-carefold-profile-id")
        or request.headers.get("x-profile-id")
        or explicit_profile_id
        or ""
    ).strip()

    resolved_profile: Optional[Profile] = None
    if header_profile_id:
        prof = (
            await db.execute(select(Profile).where(Profile.id == header_profile_id))
        ).scalar_one_or_none()
        if prof is None:
            raise FhirOperationError(404, "not-found", "Requested patient profile was not found.")
        access = await get_user_profile_access(prof, user, db)
        if access is None:
            # Return 404 rather than 403 so cross-tenant profile existence is never leaked
            raise FhirOperationError(404, "not-found", "Requested patient profile was not found.")
        resolved_profile = prof
    elif candidate_patient_id:
        clean_cand = candidate_patient_id.strip()
        if clean_cand.startswith("Patient/"):
            clean_cand = clean_cand.split("/", 1)[1].strip()
        if clean_cand.startswith("pat-"):
            clean_cand = clean_cand[4:]
        prof = (
            await db.execute(select(Profile).where(Profile.id == clean_cand))
        ).scalar_one_or_none()
        if prof is None:
            raise FhirOperationError(404, "not-found", f"Patient/{candidate_patient_id} was not found.")
        access = await get_user_profile_access(prof, user, db)
        if access is None:
            raise FhirOperationError(404, "not-found", f"Patient/{candidate_patient_id} was not found.")
        resolved_profile = prof
    else:
        owner_id = resolve_owner_user_id(user)
        stmt = (
            select(Profile)
            .where(Profile.user_id == owner_id)
            .order_by(Profile.is_primary.desc(), Profile.created_at.asc())
        )
        for prof in (await db.execute(stmt)).scalars().all():
            if await get_user_profile_access(prof, user, db) is not None:
                resolved_profile = prof
                break
        if resolved_profile is None:
            all_profs = (
                await db.execute(
                    select(Profile).order_by(Profile.is_primary.desc(), Profile.created_at.asc())
                )
            ).scalars().all()
            for prof in all_profs:
                if await get_user_profile_access(prof, user, db) is not None:
                    resolved_profile = prof
                    break
        if resolved_profile is None:
            from yarvelle_core.db.models import User
            from carefold.api.profiles import auto_provision_primary_me_profile

            if user and getattr(user, "id", None):
                existing_user = await db.get(User, user.id)
                if existing_user is None:
                    db.add(
                        User(
                            id=user.id,
                            email=getattr(user, "email", None) or "steward@carefold.local",
                            username=getattr(user, "username", None) or "steward",
                            hashed_password="disabled",
                            role=getattr(user, "role", None) or "steward",
                            status="active",
                            auth_provider="disabled",
                        )
                    )
                    await db.commit()
            resolved_profile = await auto_provision_primary_me_profile(user, db)

    if resolved_profile is None:
        raise FhirOperationError(404, "not-found", "No accessible patient profile found for current user.")

    # Resolve granted scopes from X-Carefold-Scopes header or ambient ScopeContext
    raw_scope_header = (request.headers.get("x-carefold-scopes") or "").strip()
    if raw_scope_header:
        scopes: FrozenSet[str] = frozenset(s.strip() for s in raw_scope_header.split(",") if s.strip())
    else:
        ambient = current_scope_context()
        if ambient is not None and getattr(ambient, "granted_scopes", None):
            scopes = frozenset(str(s) for s in ambient.granted_scopes)
        else:
            scopes = frozenset({"health.clinical", "health.paperwork"})

    # Resolve explicit user confirmation from header, query flag, or verified Approval
    confirm_hdr = (request.headers.get("x-carefold-confirm") or "").strip().lower()
    approval_id = (request.headers.get("x-carefold-approval-id") or "").strip()
    is_confirmed = bool(confirmed_param or confirm_hdr in ("true", "1", "yes"))
    if not is_confirmed and approval_id:
        app_row = (
            await db.execute(
                select(Approval).where(
                    Approval.id == approval_id,
                    Approval.profile_id == resolved_profile.id,
                    Approval.status == "approved",
                )
            )
        ).scalar_one_or_none()
        if app_row is not None:
            is_confirmed = True

    base_url = str(request.base_url).rstrip("/") + "/api/v1/fhir/r4"
    return FhirExecutionContext(
        profile_id=resolved_profile.id,
        user_id=user.id,
        scopes=scopes,
        confirmed=is_confirmed,
        idempotency_key=(request.headers.get("idempotency-key") or "").strip() or None,
        if_match=(request.headers.get("if-match") or "").strip() or None,
        base_url=base_url,
        principal="user",
    )


# ============================================================================
# 1. GET /api/v1/fhir/r4/metadata — CapabilityStatement
# ============================================================================


@router.get(
    "/metadata",
    summary="Get FHIR R4 CapabilityStatement",
    operation_id="fhir_r4_capabilities",
)
async def get_fhir_metadata(
    request: Request,
    profile_id: Optional[str] = Query(None, description="Optional target profile ID"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Returns Carefold's validated `fhir.resources.R4B.capabilitystatement.CapabilityStatement`."""
    try:
        try:
            ctx = await _resolve_active_profile_and_context(
                request, user, db, explicit_profile_id=profile_id
            )
        except FhirOperationError as exc:
            if exc.status_code == 404 and not profile_id and not request.headers.get("x-carefold-profile-id"):
                ctx = FhirExecutionContext(
                    profile_id="metadata-default",
                    user_id=user.id,
                    base_url=str(request.base_url).rstrip("/") + "/api/v1/fhir/r4",
                )
            else:
                raise
        op = FHIR_OPERATION_REGISTRY["fhir_capabilities"]
        payload = await op.handler(db, ctx, {})
        return JSONResponse(status_code=200, content=payload, media_type=FHIR_JSON_MEDIA_TYPE)
    except FhirOperationError as err:
        return _build_error_response(request, err)


# ============================================================================
# 2. Bulk Data $export Status & File Download Routes
# ============================================================================


@router.get(
    "/$export-status/{job_id}",
    summary="Poll Bulk FHIR $export Job Status",
    operation_id="fhir_r4_bulk_export_status",
)
async def get_fhir_bulk_export_status_route(
    request: Request,
    job_id: str = Path(..., description="Bulk export job UUID"),
    profile_id: Optional[str] = Query(None, description="Optional profile ID"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        ctx = await _resolve_active_profile_and_context(request, user, db, explicit_profile_id=profile_id)
        op = FHIR_OPERATION_REGISTRY["fhir_bulk_export_status"]
        payload = await op.handler(db, ctx, {"job_id": job_id})
        if payload.get("status") != "completed":
            return JSONResponse(
                status_code=202,
                content=payload,
                media_type=FHIR_JSON_MEDIA_TYPE,
                headers={"X-Progress": f"{payload.get('progress', 50)}%"},
            )
        return JSONResponse(status_code=200, content=payload, media_type=FHIR_JSON_MEDIA_TYPE)
    except FhirOperationError as err:
        return _build_error_response(request, err)


@router.get(
    "/$export-status/{job_id}/files/{resource_file}",
    summary="Download Bulk FHIR $export NDJSON File",
    operation_id="fhir_r4_bulk_export_download",
)
async def download_fhir_bulk_export_file_route(
    request: Request,
    job_id: str = Path(..., description="Bulk export job UUID"),
    resource_file: str = Path(..., description="Resource NDJSON filename (e.g. 'Observation.ndjson')"),
    profile_id: Optional[str] = Query(None, description="Optional profile ID"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        ctx = await _resolve_active_profile_and_context(request, user, db, explicit_profile_id=profile_id)
        op = FHIR_OPERATION_REGISTRY["fhir_bulk_export_download"]
        payload = await op.handler(
            db,
            ctx,
            {"job_id": job_id, "resource_type": resource_file},
        )
        return Response(
            content=payload["ndjson"],
            status_code=200,
            media_type=FHIR_NDJSON_MEDIA_TYPE,
        )
    except FhirOperationError as err:
        return _build_error_response(request, err)


# ============================================================================
# 3. Patient-Level Operations ($everything, $summary IPS, $export)
# ============================================================================


@router.get(
    "/Patient/{id}/$everything",
    summary="Patient/$everything Longitudinal Record Export",
    operation_id="fhir_r4_patient_everything",
)
async def get_patient_everything_route(
    request: Request,
    id: str = Path(..., description="Patient / Profile logical ID"),
    _type: Optional[str] = Query(None, description="Comma-separated FHIR resource types"),
    _since: Optional[str] = Query(None, description="ISO-8601 lower bound timestamp"),
    _count: int = Query(DEFAULT_FHIR_PAGE_COUNT, description="Maximum entries per page (1..100)"),
    _cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    profile_id: Optional[str] = Query(None, description="Optional active profile ID"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        ctx = await _resolve_active_profile_and_context(
            request,
            user,
            db,
            explicit_profile_id=profile_id,
            candidate_patient_id=id,
        )
        op = FHIR_OPERATION_REGISTRY["fhir_patient_everything"]
        payload = await op.handler(
            db,
            ctx,
            {
                "patient_id": id,
                "_type": _type,
                "_since": _since,
                "_count": _count,
                "_cursor": _cursor,
            },
        )
        return JSONResponse(status_code=200, content=payload, media_type=FHIR_JSON_MEDIA_TYPE)
    except FhirOperationError as err:
        return _build_error_response(request, err)


@router.get(
    "/Patient/{id}/$summary",
    summary="Patient/$summary HL7 International Patient Summary (IPS)",
    operation_id="fhir_r4_patient_summary",
)
async def get_patient_summary_ips_route(
    request: Request,
    id: str = Path(..., description="Patient / Profile logical ID"),
    profile_id: Optional[str] = Query(None, description="Optional active profile ID"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        ctx = await _resolve_active_profile_and_context(
            request,
            user,
            db,
            explicit_profile_id=profile_id,
            candidate_patient_id=id,
        )
        op = FHIR_OPERATION_REGISTRY["fhir_patient_summary"]
        payload = await op.handler(db, ctx, {"patient_id": id})
        return JSONResponse(status_code=200, content=payload, media_type=FHIR_JSON_MEDIA_TYPE)
    except FhirOperationError as err:
        return _build_error_response(request, err)


async def _execute_patient_bulk_export(
    request: Request,
    id: str,
    _type: Optional[str],
    _since: Optional[str],
    _async: Optional[bool],
    confirmed: bool,
    profile_id: Optional[str],
    prefer: Optional[str],
    user: UserProfile,
    db: AsyncSession,
) -> Response:
    try:
        ctx = await _resolve_active_profile_and_context(
            request,
            user,
            db,
            explicit_profile_id=profile_id,
            candidate_patient_id=id,
            confirmed_param=confirmed,
        )
        op = FHIR_OPERATION_REGISTRY["fhir_bulk_export_start"]
        payload = await op.handler(
            db,
            ctx,
            {
                "patient_id": id,
                "_type": _type,
                "_since": _since,
                "confirmed": ctx.confirmed,
            },
        )
        prefer_async = (
            request.method.upper() == "POST"
            or _async is True
            or "respond-async" in (prefer or "").lower()
        )
        headers = {"Content-Location": payload["status_url"]}
        if prefer_async and _async is not False:
            return JSONResponse(
                status_code=202,
                content=payload,
                media_type=FHIR_JSON_MEDIA_TYPE,
                headers=headers,
            )
        return Response(
            content=payload["ndjson"],
            status_code=200,
            media_type=FHIR_NDJSON_MEDIA_TYPE,
            headers=headers,
        )
    except FhirOperationError as err:
        return _build_error_response(request, err)


@router.post(
    "/Patient/{id}/$export",
    summary="Start Patient/$export Bulk FHIR NDJSON Export Job",
    operation_id="fhir_r4_patient_bulk_export_start",
)
async def post_patient_bulk_export_route(
    request: Request,
    id: str = Path(..., description="Patient / Profile logical ID"),
    _type: Optional[str] = Query(None, description="Comma-separated FHIR resource types"),
    _since: Optional[str] = Query(None, description="ISO-8601 lower bound timestamp"),
    _async: Optional[bool] = Query(None, description="Force async 202 response when true"),
    confirmed: bool = Query(False, description="Explicit user confirmation flag"),
    profile_id: Optional[str] = Query(None, description="Optional active profile ID"),
    prefer: Optional[str] = Header(None, alias="Prefer"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _execute_patient_bulk_export(
        request=request,
        id=id,
        _type=_type,
        _since=_since,
        _async=_async,
        confirmed=confirmed,
        profile_id=profile_id,
        prefer=prefer,
        user=user,
        db=db,
    )


@router.get(
    "/Patient/{id}/$export",
    summary="Stream or Start Patient/$export Bulk FHIR NDJSON Export",
    operation_id="fhir_r4_patient_bulk_export_get",
)
async def get_patient_bulk_export_route(
    request: Request,
    id: str = Path(..., description="Patient / Profile logical ID"),
    _type: Optional[str] = Query(None, description="Comma-separated FHIR resource types"),
    _since: Optional[str] = Query(None, description="ISO-8601 lower bound timestamp"),
    _async: Optional[bool] = Query(None, description="Force async 202 response when true"),
    confirmed: bool = Query(False, description="Explicit user confirmation flag"),
    profile_id: Optional[str] = Query(None, description="Optional active profile ID"),
    prefer: Optional[str] = Header(None, alias="Prefer"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _execute_patient_bulk_export(
        request=request,
        id=id,
        _type=_type,
        _since=_since,
        _async=_async,
        confirmed=confirmed,
        profile_id=profile_id,
        prefer=prefer,
        user=user,
        db=db,
    )


# ============================================================================
# 4. Instance History, Read, Write & Search Routes
# ============================================================================


@router.get(
    "/{resource_type}/{id}/_history",
    summary="Get FHIR R4 Resource Version History (_history)",
    operation_id="fhir_r4_resource_history",
)
async def get_fhir_resource_history_route(
    request: Request,
    resource_type: str = Path(..., description="FHIR R4 resource type"),
    id: str = Path(..., description="Logical FHIR resource ID"),
    _count: int = Query(DEFAULT_FHIR_PAGE_COUNT, description="Max revisions per page (1..100)"),
    _cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    profile_id: Optional[str] = Query(None, description="Optional active profile ID"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        ctx = await _resolve_active_profile_and_context(request, user, db, explicit_profile_id=profile_id)
        op = FHIR_OPERATION_REGISTRY["fhir_resource_history"]
        payload = await op.handler(
            db,
            ctx,
            {
                "resource_type": resource_type,
                "resource_id": id,
                "_count": _count,
                "_cursor": _cursor,
            },
        )
        return JSONResponse(status_code=200, content=payload, media_type=FHIR_JSON_MEDIA_TYPE)
    except FhirOperationError as err:
        return _build_error_response(request, err)


@router.get(
    "/{resource_type}/{id}",
    summary="Read FHIR R4 Resource by ID",
    operation_id="fhir_r4_read_resource",
)
async def read_fhir_resource_route(
    request: Request,
    resource_type: str = Path(..., description="FHIR R4 resource type"),
    id: str = Path(..., description="Logical FHIR resource ID"),
    profile_id: Optional[str] = Query(None, description="Optional active profile ID"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        cand_pat = id if resource_type.lower() == "patient" else None
        ctx = await _resolve_active_profile_and_context(
            request,
            user,
            db,
            explicit_profile_id=profile_id,
            candidate_patient_id=cand_pat,
        )
        op = FHIR_OPERATION_REGISTRY["fhir_read_resource"]
        result = await op.handler(
            db,
            ctx,
            {"resource_type": resource_type, "resource_id": id},
        )
        return JSONResponse(
            status_code=200,
            content=result["resource"],
            media_type=FHIR_JSON_MEDIA_TYPE,
            headers={"ETag": result["etag"]},
        )
    except FhirOperationError as err:
        return _build_error_response(request, err)


@router.put(
    "/{resource_type}/{id}",
    summary="Update or Create FHIR R4 Resource by ID (User-Confirmed)",
    operation_id="fhir_r4_put_resource",
)
async def put_fhir_resource_route(
    request: Request,
    resource_type: str = Path(..., description="FHIR R4 resource type"),
    id: str = Path(..., description="Logical FHIR resource ID"),
    confirmed: bool = Query(False, description="Explicit user confirmation flag"),
    profile_id: Optional[str] = Query(None, description="Optional active profile ID"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        raw_body = await request.body()
        if len(raw_body) > MAX_FHIR_WRITE_BYTES:
            raise FhirOperationError(
                status_code=413,
                issue_code="too-costly",
                diagnostics=f"Request body exceeds maximum size of {MAX_FHIR_WRITE_BYTES} bytes.",
            )
        try:
            body_json = await request.json()
        except Exception as exc:
            raise FhirOperationError(400, "invalid", "Request body must be valid FHIR R4 JSON.") from exc

        ctx = await _resolve_active_profile_and_context(
            request,
            user,
            db,
            explicit_profile_id=profile_id,
            confirmed_param=confirmed,
        )
        op = FHIR_OPERATION_REGISTRY["fhir_upsert_resource"]
        result = await op.handler(
            db,
            ctx,
            {
                "resource_type": resource_type,
                "resource_id": id,
                "resource": body_json,
                "confirmed": ctx.confirmed,
            },
        )
        return JSONResponse(
            status_code=result["status_code"],
            content=result["resource"],
            media_type=FHIR_JSON_MEDIA_TYPE,
            headers={
                "ETag": result["etag"],
                "Location": result["location"],
            },
        )
    except FhirOperationError as err:
        return _build_error_response(request, err)


@router.post(
    "/{resource_type}",
    summary="Create FHIR R4 Resource (User-Confirmed)",
    operation_id="fhir_r4_post_resource",
)
async def post_fhir_resource_route(
    request: Request,
    resource_type: str = Path(..., description="FHIR R4 resource type"),
    confirmed: bool = Query(False, description="Explicit user confirmation flag"),
    profile_id: Optional[str] = Query(None, description="Optional active profile ID"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        raw_body = await request.body()
        if len(raw_body) > MAX_FHIR_WRITE_BYTES:
            raise FhirOperationError(
                status_code=413,
                issue_code="too-costly",
                diagnostics=f"Request body exceeds maximum size of {MAX_FHIR_WRITE_BYTES} bytes.",
            )
        try:
            body_json = await request.json()
        except Exception as exc:
            raise FhirOperationError(400, "invalid", "Request body must be valid FHIR R4 JSON.") from exc

        ctx = await _resolve_active_profile_and_context(
            request,
            user,
            db,
            explicit_profile_id=profile_id,
            confirmed_param=confirmed,
        )
        op = FHIR_OPERATION_REGISTRY["fhir_upsert_resource"]
        result = await op.handler(
            db,
            ctx,
            {
                "resource_type": resource_type,
                "resource": body_json,
                "confirmed": ctx.confirmed,
            },
        )
        return JSONResponse(
            status_code=201,
            content=result["resource"],
            media_type=FHIR_JSON_MEDIA_TYPE,
            headers={
                "ETag": result["etag"],
                "Location": result["location"],
            },
        )
    except FhirOperationError as err:
        return _build_error_response(request, err)


@router.get(
    "/{resource_type}",
    summary="Search FHIR R4 Resources",
    operation_id="fhir_r4_search_resources",
)
async def search_fhir_resources_route(
    request: Request,
    resource_type: str = Path(..., description="FHIR R4 resource type"),
    patient: Optional[str] = Query(None, description="Patient reference filter"),
    subject: Optional[str] = Query(None, description="Subject reference filter"),
    category: Optional[str] = Query(None, description="Category token filter"),
    code: Optional[str] = Query(None, description="Coded concept filter (system|code or code)"),
    date: Optional[List[str]] = Query(None, description="Effective date filter(s) with eq/ge/le/gt/lt prefix"),
    status: Optional[str] = Query(None, description="Lifecycle status filter"),
    clinical_status: Optional[str] = Query(None, alias="clinical-status", description="Clinical status filter"),
    _lastUpdated: Optional[List[str]] = Query(None, description="Last updated timestamp filter(s)"),
    _include: Optional[str] = Query(None, description="Outbound reference include expression"),
    _sort: Optional[str] = Query("-date", description="Sort expression"),
    _count: int = Query(DEFAULT_FHIR_PAGE_COUNT, description="Page size (1..100)"),
    _cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    profile_id: Optional[str] = Query(None, description="Optional active profile ID"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        ctx = await _resolve_active_profile_and_context(
            request,
            user,
            db,
            explicit_profile_id=profile_id,
            candidate_patient_id=patient or subject,
        )
        op = FHIR_OPERATION_REGISTRY["fhir_search_resources"]
        payload = await op.handler(
            db,
            ctx,
            {
                "resource_type": resource_type,
                "patient": patient,
                "subject": subject,
                "category": category,
                "code": code,
                "date": date,
                "status": status,
                "clinical-status": clinical_status,
                "_lastUpdated": _lastUpdated,
                "_include": _include,
                "_sort": _sort,
                "_count": _count,
                "_cursor": _cursor,
            },
        )
        return JSONResponse(status_code=200, content=payload, media_type=FHIR_JSON_MEDIA_TYPE)
    except FhirOperationError as err:
        return _build_error_response(request, err)


def generate_fhir_r4_openapi_spec() -> Dict[str, Any]:
    """Generate the canonical OpenAPI 3.1.0 contract for `/api/v1/fhir/r4/*` routes."""
    from fastapi import FastAPI
    from fastapi.openapi.utils import get_openapi
    from carefold.fhir.operations import FHIR_OPERATION_SPECS

    spec_app = FastAPI(
        title="Carefold Local-First HL7 FHIR R4 REST & MCP Surface",
        version="4.0.1",
    )
    spec_app.include_router(router, prefix="/api/v1")
    schema = get_openapi(
        title=spec_app.title,
        version=spec_app.version,
        openapi_version="3.1.0",
        description=(
            "Profile-scoped, local-first HL7 FHIR R4 REST API and MCP operation contract "
            "backed by Carefold's single FHIR Operation Registry (`carefold.fhir.operations`)."
        ),
        routes=spec_app.routes,
    )
    schema["openapi"] = "3.1.0"
    schema["x-carefold-mcp-operations"] = [
        {
            "operation_id": spec.operation_id,
            "mcp_tool_name": spec.mcp_tool_name,
            "http_method": spec.rest_method,
            "rest_path": spec.rest_path,
            "risk_tier": spec.risk_tier,
            "requires_confirmation": spec.requires_confirmation,
            "annotations": spec.annotations.to_dict(),
            "mcp_resource_uri_template": spec.mcp_resource_uri_template,
        }
        for spec in FHIR_OPERATION_SPECS
    ]
    return schema


__all__ = ["router", "generate_fhir_r4_openapi_spec"]
