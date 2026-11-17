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

"""REST API endpoints for Health Insurance Coverage, Claims, Appeals, and Prior Authorizations (Issue #359)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, Path, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yarvelle_core.api.deps import get_current_user, get_db
from yarvelle_core.api.errors import ProblemDetailsRoute
from yarvelle_core.auth.ports import UserProfile

from carefold.api.profiles import get_user_profile_access
from carefold.audit.logger import record_audit
from carefold.errors import YarvelleError
from carefold.models.health import Appeal, Claim, CoveragePlan, PriorAuthorization
from yarvelle_core.db.models import Profile

router = APIRouter(tags=["insurance"], route_class=ProblemDetailsRoute)


# ============================================================================
# Schemas
# ============================================================================


class CoveragePlanCreateRequest(BaseModel):
    payer_name: str = Field(..., min_length=1, max_length=255, description="Insurance carrier or health plan payer name")
    policy_number: str = Field(..., min_length=1, max_length=128, description="Member policy or subscriber ID")
    profile_id: Optional[str] = Field(None, description="Optional profile ID from payload")
    group_number: Optional[str] = Field(None, max_length=128)
    deductible_individual: Optional[float] = Field(0.0, ge=0.0)
    deductible_family: Optional[float] = Field(0.0, ge=0.0)
    oop_max_individual: Optional[float] = Field(0.0, ge=0.0)
    oop_max_family: Optional[float] = Field(0.0, ge=0.0)
    copay_pcp: Optional[float] = Field(0.0, ge=0.0)
    copay_specialist: Optional[float] = Field(0.0, ge=0.0)
    coinsurance_pct: Optional[float] = Field(0.0, ge=0.0, le=100.0)
    status: Optional[str] = Field("active", max_length=32)


class CoveragePlanResponse(BaseModel):
    id: str
    profile_id: str
    payer_name: str
    policy_number: str
    group_number: Optional[str] = None
    deductible_individual: Optional[float] = 0.0
    deductible_family: Optional[float] = 0.0
    oop_max_individual: Optional[float] = 0.0
    oop_max_family: Optional[float] = 0.0
    copay_pcp: Optional[float] = 0.0
    copay_specialist: Optional[float] = 0.0
    coinsurance_pct: Optional[float] = 0.0
    status: str
    created_at: datetime
    updated_at: datetime


class ClaimCreateRequest(BaseModel):
    service_date: str = Field(..., description="Date of medical service (YYYY-MM-DD)")
    billed_amount: float = Field(..., ge=0.0, description="Total billed charge amount in dollars")
    profile_id: Optional[str] = Field(None, description="Optional profile ID from payload")
    allowed_amount: Optional[float] = Field(0.0, ge=0.0)
    patient_responsibility: Optional[float] = Field(0.0, ge=0.0)
    status: Optional[str] = Field("submitted", max_length=32)
    denial_reason: Optional[str] = None
    denial_code: Optional[str] = None
    provider_name: Optional[str] = None


class ClaimUpdateRequest(BaseModel):
    service_date: Optional[str] = None
    billed_amount: Optional[float] = Field(None, ge=0.0)
    allowed_amount: Optional[float] = Field(None, ge=0.0)
    patient_responsibility: Optional[float] = Field(None, ge=0.0)
    status: Optional[str] = None
    denial_reason: Optional[str] = None
    denial_code: Optional[str] = None
    provider_name: Optional[str] = None


class ClaimResponse(BaseModel):
    id: str
    profile_id: str
    service_date: str
    billed_amount: float
    allowed_amount: Optional[float] = 0.0
    patient_responsibility: Optional[float] = 0.0
    status: str
    denial_reason: Optional[str] = None
    denial_code: Optional[str] = None
    provider_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AppealCreateRequest(BaseModel):
    clinical_justification: str = Field(..., min_length=1, description="Clinical evidence supporting medical necessity")
    profile_id: Optional[str] = Field(None, description="Optional profile ID from payload")
    claim_id: Optional[str] = None
    prior_auth_id: Optional[str] = None
    denial_code: Optional[str] = None
    deadline_date: Optional[str] = None
    status: Optional[str] = Field("draft", max_length=32)
    letter_content: Optional[str] = None


class AppealUpdateRequest(BaseModel):
    clinical_justification: Optional[str] = None
    claim_id: Optional[str] = None
    prior_auth_id: Optional[str] = None
    denial_code: Optional[str] = None
    deadline_date: Optional[str] = None
    status: Optional[str] = None
    letter_content: Optional[str] = None


class AppealResponse(BaseModel):
    id: str
    profile_id: str
    clinical_justification: str
    claim_id: Optional[str] = None
    prior_auth_id: Optional[str] = None
    denial_code: Optional[str] = None
    deadline_date: Optional[str] = None
    status: str
    letter_content: Optional[str] = None
    timeliness_warning: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PriorAuthCreateRequest(BaseModel):
    procedure_code: str = Field(..., min_length=1, max_length=64, description="CPT or HCPCS procedure code")
    procedure_name: str = Field(..., min_length=1, max_length=255, description="Procedure or service name")
    profile_id: Optional[str] = Field(None, description="Optional profile ID from payload")
    provider_name: Optional[str] = None
    status: Optional[str] = Field("pending", max_length=32)
    submitted_date: Optional[str] = None
    decision_date: Optional[str] = None
    notes: Optional[str] = None


class PriorAuthUpdateRequest(BaseModel):
    procedure_code: Optional[str] = None
    procedure_name: Optional[str] = None
    provider_name: Optional[str] = None
    status: Optional[str] = None
    submitted_date: Optional[str] = None
    decision_date: Optional[str] = None
    notes: Optional[str] = None


class PriorAuthResponse(BaseModel):
    id: str
    profile_id: str
    procedure_code: str
    procedure_name: str
    provider_name: Optional[str] = None
    status: str
    submitted_date: Optional[str] = None
    decision_date: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ============================================================================
# Helpers
# ============================================================================


async def _verify_profile(profile_id: str, user: UserProfile, db: AsyncSession) -> Profile:
    clean_id = (profile_id or "").strip()
    stmt = select(Profile).where(Profile.id == clean_id)
    profile = (await db.execute(stmt)).scalar_one_or_none()
    if profile is None:
        raise YarvelleError(
            "YRV-500-002",
            detail=f"Profile '{clean_id}' not found.",
            context={"profile_id": clean_id},
        )
    access = await get_user_profile_access(profile, user, db)
    if access is None:
        raise YarvelleError(
            "YRV-300-007",
            detail=f"Access denied to profile '{clean_id}'.",
            context={"profile_id": clean_id},
        )
    return profile


# ============================================================================
# 1. Coverage Plan Endpoints
# ============================================================================


@router.post(
    "/profiles/{profile_id}/coverage",
    response_model=CoveragePlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or update insurance coverage plan",
)
async def create_coverage_plan(
    profile_id: str,
    payload: CoveragePlanCreateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CoveragePlanResponse:
    profile = await _verify_profile(profile_id, user, db)
    now = datetime.now(timezone.utc)
    plan_id = str(uuid.uuid4())

    plan = CoveragePlan(
        id=plan_id,
        profile_id=profile.id,
        payer_name=payload.payer_name.strip(),
        policy_number=payload.policy_number.strip(),
        group_number=payload.group_number.strip() if payload.group_number else None,
        deductible_individual=payload.deductible_individual or 0.0,
        deductible_family=payload.deductible_family or 0.0,
        oop_max_individual=payload.oop_max_individual or 0.0,
        oop_max_family=payload.oop_max_family or 0.0,
        copay_pcp=payload.copay_pcp or 0.0,
        copay_specialist=payload.copay_specialist or 0.0,
        coinsurance_pct=payload.coinsurance_pct or 0.0,
        status=payload.status or "active",
        created_at=now,
        updated_at=now,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)

    return CoveragePlanResponse(
        id=plan.id,
        profile_id=plan.profile_id,
        payer_name=plan.payer_name,
        policy_number=plan.policy_number,
        group_number=plan.group_number,
        deductible_individual=plan.deductible_individual,
        deductible_family=plan.deductible_family,
        oop_max_individual=plan.oop_max_individual,
        oop_max_family=plan.oop_max_family,
        copay_pcp=plan.copay_pcp,
        copay_specialist=plan.copay_specialist,
        coinsurance_pct=plan.coinsurance_pct,
        status=plan.status,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


@router.get(
    "/profiles/{profile_id}/coverage",
    response_model=List[CoveragePlanResponse],
    summary="Get active coverage plans for profile",
)
async def get_coverage_plans(
    profile_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[CoveragePlanResponse]:
    profile = await _verify_profile(profile_id, user, db)
    stmt = (
        select(CoveragePlan)
        .where(CoveragePlan.profile_id == profile.id)
        .order_by(CoveragePlan.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        CoveragePlanResponse(
            id=p.id,
            profile_id=p.profile_id,
            payer_name=p.payer_name,
            policy_number=p.policy_number,
            group_number=p.group_number,
            deductible_individual=p.deductible_individual,
            deductible_family=p.deductible_family,
            oop_max_individual=p.oop_max_individual,
            oop_max_family=p.oop_max_family,
            copay_pcp=p.copay_pcp,
            copay_specialist=p.copay_specialist,
            coinsurance_pct=p.coinsurance_pct,
            status=p.status,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in rows
    ]


@router.get(
    "/profiles/{profile_id}/coverage/{plan_id}",
    response_model=CoveragePlanResponse,
    summary="Get specific coverage plan by ID",
)
async def get_coverage_plan_by_id(
    profile_id: str,
    plan_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CoveragePlanResponse:
    profile = await _verify_profile(profile_id, user, db)
    stmt = select(CoveragePlan).where(CoveragePlan.profile_id == profile.id, CoveragePlan.id == plan_id)
    plan = (await db.execute(stmt)).scalar_one_or_none()
    if plan is None:
        raise YarvelleError(
            "CFD-500-001",
            detail=f"Coverage plan '{plan_id}' not found.",
            context={"plan_id": plan_id, "profile_id": profile.id},
        )
    return CoveragePlanResponse(
        id=plan.id,
        profile_id=plan.profile_id,
        payer_name=plan.payer_name,
        policy_number=plan.policy_number,
        group_number=plan.group_number,
        deductible_individual=plan.deductible_individual,
        deductible_family=plan.deductible_family,
        oop_max_individual=plan.oop_max_individual,
        oop_max_family=plan.oop_max_family,
        copay_pcp=plan.copay_pcp,
        copay_specialist=plan.copay_specialist,
        coinsurance_pct=plan.coinsurance_pct,
        status=plan.status,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


@router.delete(
    "/profiles/{profile_id}/coverage/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete coverage plan",
)
async def delete_coverage_plan(
    profile_id: str,
    plan_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    profile = await _verify_profile(profile_id, user, db)
    stmt = select(CoveragePlan).where(CoveragePlan.profile_id == profile.id, CoveragePlan.id == plan_id)
    plan = (await db.execute(stmt)).scalar_one_or_none()
    if plan is not None:
        await db.delete(plan)
        await db.commit()
    return Response(status_code=204)


# ============================================================================
# 2. Claims Endpoints
# ============================================================================


@router.post(
    "/profiles/{profile_id}/claims",
    response_model=ClaimResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit or track medical insurance claim",
)
async def create_claim(
    profile_id: str,
    payload: ClaimCreateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClaimResponse:
    profile = await _verify_profile(profile_id, user, db)
    now = datetime.now(timezone.utc)
    claim_id = str(uuid.uuid4())

    claim = Claim(
        id=claim_id,
        profile_id=profile.id,
        service_date=payload.service_date,
        billed_amount=payload.billed_amount,
        allowed_amount=payload.allowed_amount or 0.0,
        patient_responsibility=payload.patient_responsibility or 0.0,
        status=payload.status or "submitted",
        denial_reason=payload.denial_reason,
        denial_code=payload.denial_code,
        provider_name=payload.provider_name,
        created_at=now,
        updated_at=now,
    )
    db.add(claim)
    await db.commit()
    await db.refresh(claim)

    return ClaimResponse(
        id=claim.id,
        profile_id=claim.profile_id,
        service_date=claim.service_date,
        billed_amount=claim.billed_amount,
        allowed_amount=claim.allowed_amount,
        patient_responsibility=claim.patient_responsibility,
        status=claim.status,
        denial_reason=claim.denial_reason,
        denial_code=claim.denial_code,
        provider_name=claim.provider_name,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )


@router.get(
    "/profiles/{profile_id}/claims",
    response_model=List[ClaimResponse],
    summary="List insurance claims for profile",
)
async def list_claims(
    profile_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ClaimResponse]:
    profile = await _verify_profile(profile_id, user, db)
    stmt = select(Claim).where(Claim.profile_id == profile.id)
    if status_filter:
        stmt = stmt.where(Claim.status == status_filter)
    stmt = stmt.order_by(Claim.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()

    return [
        ClaimResponse(
            id=c.id,
            profile_id=c.profile_id,
            service_date=c.service_date,
            billed_amount=c.billed_amount,
            allowed_amount=c.allowed_amount,
            patient_responsibility=c.patient_responsibility,
            status=c.status,
            denial_reason=c.denial_reason,
            denial_code=c.denial_code,
            provider_name=c.provider_name,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in rows
    ]


@router.get(
    "/profiles/{profile_id}/claims/{claim_id}",
    response_model=ClaimResponse,
    summary="Get claim detail by ID",
)
async def get_claim(
    profile_id: str,
    claim_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClaimResponse:
    profile = await _verify_profile(profile_id, user, db)
    stmt = select(Claim).where(Claim.profile_id == profile.id, Claim.id == claim_id)
    claim = (await db.execute(stmt)).scalar_one_or_none()
    if claim is None:
        raise YarvelleError(
            "CFD-500-001",
            detail=f"Claim '{claim_id}' not found.",
            context={"claim_id": claim_id, "profile_id": profile.id},
        )

    return ClaimResponse(
        id=claim.id,
        profile_id=claim.profile_id,
        service_date=claim.service_date,
        billed_amount=claim.billed_amount,
        allowed_amount=claim.allowed_amount,
        patient_responsibility=claim.patient_responsibility,
        status=claim.status,
        denial_reason=claim.denial_reason,
        denial_code=claim.denial_code,
        provider_name=claim.provider_name,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )


@router.patch(
    "/profiles/{profile_id}/claims/{claim_id}",
    response_model=ClaimResponse,
    summary="Update claim status or amounts",
)
async def update_claim(
    profile_id: str,
    claim_id: str,
    payload: ClaimUpdateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClaimResponse:
    profile = await _verify_profile(profile_id, user, db)
    stmt = select(Claim).where(Claim.profile_id == profile.id, Claim.id == claim_id)
    claim = (await db.execute(stmt)).scalar_one_or_none()
    if claim is None:
        raise YarvelleError(
            "CFD-500-001",
            detail=f"Claim '{claim_id}' not found.",
            context={"claim_id": claim_id, "profile_id": profile.id},
        )

    if payload.service_date is not None:
        claim.service_date = payload.service_date
    if payload.billed_amount is not None:
        claim.billed_amount = payload.billed_amount
    if payload.allowed_amount is not None:
        claim.allowed_amount = payload.allowed_amount
    if payload.patient_responsibility is not None:
        claim.patient_responsibility = payload.patient_responsibility
    if payload.status is not None:
        claim.status = payload.status
    if payload.denial_reason is not None:
        claim.denial_reason = payload.denial_reason
    if payload.denial_code is not None:
        claim.denial_code = payload.denial_code
    if payload.provider_name is not None:
        claim.provider_name = payload.provider_name

    claim.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(claim)

    return ClaimResponse(
        id=claim.id,
        profile_id=claim.profile_id,
        service_date=claim.service_date,
        billed_amount=claim.billed_amount,
        allowed_amount=claim.allowed_amount,
        patient_responsibility=claim.patient_responsibility,
        status=claim.status,
        denial_reason=claim.denial_reason,
        denial_code=claim.denial_code,
        provider_name=claim.provider_name,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )


@router.delete(
    "/profiles/{profile_id}/claims/{claim_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete claim",
)
async def delete_claim(
    profile_id: str,
    claim_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    profile = await _verify_profile(profile_id, user, db)
    stmt = select(Claim).where(Claim.profile_id == profile.id, Claim.id == claim_id)
    claim = (await db.execute(stmt)).scalar_one_or_none()
    if claim is not None:
        await db.delete(claim)
        await db.commit()
    return Response(status_code=204)


# ============================================================================
# 3. Appeals Endpoints
# ============================================================================


def _compute_timeliness_warning(deadline_date: Optional[str]) -> Optional[str]:
    if not deadline_date:
        return None
    try:
        deadline_str = deadline_date.replace("Z", "+00:00")
        dl_dt = datetime.fromisoformat(deadline_str)
        if dl_dt.tzinfo is None:
            dl_dt = dl_dt.replace(tzinfo=timezone.utc)
        if dl_dt < datetime.now(timezone.utc):
            return "Appeal submitted after regulatory window; timeliness exception justification required."
    except (ValueError, TypeError):
        pass
    return None


@router.post(
    "/profiles/{profile_id}/appeals",
    response_model=AppealResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create appeal dossier for denied claim or prior-authorization",
)
async def create_appeal(
    profile_id: str,
    payload: AppealCreateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AppealResponse:
    profile = await _verify_profile(profile_id, user, db)
    now = datetime.now(timezone.utc)
    appeal_id = str(uuid.uuid4())

    timeliness_warning = None
    letter_content = payload.letter_content
    if payload.deadline_date:
        try:
            deadline_str = payload.deadline_date.replace("Z", "+00:00")
            dl_dt = datetime.fromisoformat(deadline_str)
            if dl_dt.tzinfo is None:
                dl_dt = dl_dt.replace(tzinfo=timezone.utc)
            if dl_dt < now:
                timeliness_warning = "Appeal submitted after regulatory window; timeliness exception justification required."
                warning_banner = f"[WARNING: Timeliness Exception Required - Filing deadline expired on {payload.deadline_date}]"
                if letter_content:
                    letter_content = f"{warning_banner}\n\n{letter_content}"
                else:
                    letter_content = warning_banner
        except (ValueError, TypeError):
            pass

    appeal = Appeal(
        id=appeal_id,
        profile_id=profile.id,
        claim_id=payload.claim_id,
        prior_auth_id=payload.prior_auth_id,
        denial_code=payload.denial_code,
        clinical_justification=payload.clinical_justification.strip(),
        deadline_date=payload.deadline_date,
        status=payload.status or "draft",
        letter_content=letter_content,
        created_at=now,
        updated_at=now,
    )
    db.add(appeal)
    await db.commit()
    await db.refresh(appeal)

    return AppealResponse(
        id=appeal.id,
        profile_id=appeal.profile_id,
        claim_id=appeal.claim_id,
        prior_auth_id=appeal.prior_auth_id,
        denial_code=appeal.denial_code,
        clinical_justification=appeal.clinical_justification,
        deadline_date=appeal.deadline_date,
        status=appeal.status,
        letter_content=appeal.letter_content,
        timeliness_warning=timeliness_warning,
        created_at=appeal.created_at,
        updated_at=appeal.updated_at,
    )


@router.get(
    "/profiles/{profile_id}/appeals",
    response_model=List[AppealResponse],
    summary="List appeal dossiers for profile",
)
async def list_appeals(
    profile_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[AppealResponse]:
    profile = await _verify_profile(profile_id, user, db)
    stmt = select(Appeal).where(Appeal.profile_id == profile.id).order_by(Appeal.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()

    return [
        AppealResponse(
            id=a.id,
            profile_id=a.profile_id,
            claim_id=a.claim_id,
            prior_auth_id=a.prior_auth_id,
            denial_code=a.denial_code,
            clinical_justification=a.clinical_justification,
            deadline_date=a.deadline_date,
            status=a.status,
            letter_content=a.letter_content,
            timeliness_warning=_compute_timeliness_warning(a.deadline_date),
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in rows
    ]


@router.get(
    "/profiles/{profile_id}/appeals/{appeal_id}",
    response_model=AppealResponse,
    summary="Get appeal detail by ID",
)
async def get_appeal(
    profile_id: str,
    appeal_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AppealResponse:
    profile = await _verify_profile(profile_id, user, db)
    stmt = select(Appeal).where(Appeal.profile_id == profile.id, Appeal.id == appeal_id)
    appeal = (await db.execute(stmt)).scalar_one_or_none()
    if appeal is None:
        raise YarvelleError(
            "CFD-500-001",
            detail=f"Appeal '{appeal_id}' not found.",
            context={"appeal_id": appeal_id, "profile_id": profile.id},
        )

    return AppealResponse(
        id=appeal.id,
        profile_id=appeal.profile_id,
        claim_id=appeal.claim_id,
        prior_auth_id=appeal.prior_auth_id,
        denial_code=appeal.denial_code,
        clinical_justification=appeal.clinical_justification,
        deadline_date=appeal.deadline_date,
        status=appeal.status,
        letter_content=appeal.letter_content,
        timeliness_warning=_compute_timeliness_warning(appeal.deadline_date),
        created_at=appeal.created_at,
        updated_at=appeal.updated_at,
    )


@router.patch(
    "/profiles/{profile_id}/appeals/{appeal_id}",
    response_model=AppealResponse,
    summary="Update appeal status or letter content",
)
async def update_appeal(
    profile_id: str,
    appeal_id: str,
    payload: AppealUpdateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AppealResponse:
    profile = await _verify_profile(profile_id, user, db)
    stmt = select(Appeal).where(Appeal.profile_id == profile.id, Appeal.id == appeal_id)
    appeal = (await db.execute(stmt)).scalar_one_or_none()
    if appeal is None:
        raise YarvelleError(
            "CFD-500-001",
            detail=f"Appeal '{appeal_id}' not found.",
            context={"appeal_id": appeal_id, "profile_id": profile.id},
        )

    if payload.clinical_justification is not None:
        appeal.clinical_justification = payload.clinical_justification.strip()
    if payload.claim_id is not None:
        appeal.claim_id = payload.claim_id
    if payload.prior_auth_id is not None:
        appeal.prior_auth_id = payload.prior_auth_id
    if payload.denial_code is not None:
        appeal.denial_code = payload.denial_code
    if payload.deadline_date is not None:
        appeal.deadline_date = payload.deadline_date
    if payload.status is not None:
        appeal.status = payload.status
    if payload.letter_content is not None:
        appeal.letter_content = payload.letter_content

    appeal.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(appeal)

    return AppealResponse(
        id=appeal.id,
        profile_id=appeal.profile_id,
        claim_id=appeal.claim_id,
        prior_auth_id=appeal.prior_auth_id,
        denial_code=appeal.denial_code,
        clinical_justification=appeal.clinical_justification,
        deadline_date=appeal.deadline_date,
        status=appeal.status,
        letter_content=appeal.letter_content,
        timeliness_warning=_compute_timeliness_warning(appeal.deadline_date),
        created_at=appeal.created_at,
        updated_at=appeal.updated_at,
    )


@router.delete(
    "/profiles/{profile_id}/appeals/{appeal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete appeal dossier",
)
async def delete_appeal(
    profile_id: str,
    appeal_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    profile = await _verify_profile(profile_id, user, db)
    stmt = select(Appeal).where(Appeal.profile_id == profile.id, Appeal.id == appeal_id)
    appeal = (await db.execute(stmt)).scalar_one_or_none()
    if appeal is not None:
        await db.delete(appeal)
        await db.commit()
    return Response(status_code=204)


# ============================================================================
# 4. Prior Authorization Endpoints
# ============================================================================


@router.post(
    "/profiles/{profile_id}/prior-auths",
    response_model=PriorAuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create prior-authorization request",
)
async def create_prior_auth(
    profile_id: str,
    payload: PriorAuthCreateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PriorAuthResponse:
    profile = await _verify_profile(profile_id, user, db)
    now = datetime.now(timezone.utc)
    pa_id = str(uuid.uuid4())

    code = payload.procedure_code.strip()
    name = payload.procedure_name.strip()
    status_val = payload.status or "pending"
    notes_val = payload.notes

    # Emergency procedure statutory bypass (EMTALA / ACA layperson emergency standard)
    # E.g. Emergency Department visits (CPT 99281-99285) or explicit emergency services
    is_emergency = (
        code.startswith("9928")
        or "emergency" in name.lower()
        or (notes_val is not None and "emergency" in notes_val.lower())
    )
    if is_emergency and (payload.status is None or payload.status == "pending"):
        status_val = "approved"
        bypass_msg = "Emergency procedure: statutory prior authorization requirement bypassed per EMTALA/prudent layperson standard."
        notes_val = f"{notes_val}\n{bypass_msg}".strip() if notes_val else bypass_msg

    pa = PriorAuthorization(
        id=pa_id,
        profile_id=profile.id,
        procedure_code=code,
        procedure_name=name,
        provider_name=payload.provider_name,
        status=status_val,
        submitted_date=payload.submitted_date or now.isoformat(),
        decision_date=payload.decision_date or (now.isoformat() if status_val == "approved" else None),
        notes=notes_val,
        created_at=now,
        updated_at=now,
    )
    db.add(pa)
    await db.commit()
    await db.refresh(pa)

    return PriorAuthResponse(
        id=pa.id,
        profile_id=pa.profile_id,
        procedure_code=pa.procedure_code,
        procedure_name=pa.procedure_name,
        provider_name=pa.provider_name,
        status=pa.status,
        submitted_date=pa.submitted_date,
        decision_date=pa.decision_date,
        notes=pa.notes,
        created_at=pa.created_at,
        updated_at=pa.updated_at,
    )


@router.get(
    "/profiles/{profile_id}/prior-auths",
    response_model=List[PriorAuthResponse],
    summary="List prior authorization requests for profile",
)
async def list_prior_auths(
    profile_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[PriorAuthResponse]:
    profile = await _verify_profile(profile_id, user, db)
    stmt = select(PriorAuthorization).where(PriorAuthorization.profile_id == profile.id).order_by(PriorAuthorization.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()

    return [
        PriorAuthResponse(
            id=p.id,
            profile_id=p.profile_id,
            procedure_code=p.procedure_code,
            procedure_name=p.procedure_name,
            provider_name=p.provider_name,
            status=p.status,
            submitted_date=p.submitted_date,
            decision_date=p.decision_date,
            notes=p.notes,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in rows
    ]


@router.get(
    "/profiles/{profile_id}/prior-auths/{prior_auth_id}",
    response_model=PriorAuthResponse,
    summary="Get prior authorization by ID",
)
async def get_prior_auth(
    profile_id: str,
    prior_auth_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PriorAuthResponse:
    profile = await _verify_profile(profile_id, user, db)
    stmt = select(PriorAuthorization).where(
        PriorAuthorization.profile_id == profile.id, PriorAuthorization.id == prior_auth_id
    )
    pa = (await db.execute(stmt)).scalar_one_or_none()
    if pa is None:
        raise YarvelleError(
            "CFD-500-001",
            detail=f"Prior authorization '{prior_auth_id}' not found.",
            context={"prior_auth_id": prior_auth_id, "profile_id": profile.id},
        )

    return PriorAuthResponse(
        id=pa.id,
        profile_id=pa.profile_id,
        procedure_code=pa.procedure_code,
        procedure_name=pa.procedure_name,
        provider_name=pa.provider_name,
        status=pa.status,
        submitted_date=pa.submitted_date,
        decision_date=pa.decision_date,
        notes=pa.notes,
        created_at=pa.created_at,
        updated_at=pa.updated_at,
    )


@router.patch(
    "/profiles/{profile_id}/prior-auths/{prior_auth_id}",
    response_model=PriorAuthResponse,
    summary="Update prior authorization request",
)
async def update_prior_auth(
    profile_id: str,
    prior_auth_id: str,
    payload: PriorAuthUpdateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PriorAuthResponse:
    profile = await _verify_profile(profile_id, user, db)
    stmt = select(PriorAuthorization).where(
        PriorAuthorization.profile_id == profile.id, PriorAuthorization.id == prior_auth_id
    )
    pa = (await db.execute(stmt)).scalar_one_or_none()
    if pa is None:
        raise YarvelleError(
            "CFD-500-001",
            detail=f"Prior authorization '{prior_auth_id}' not found.",
            context={"prior_auth_id": prior_auth_id, "profile_id": profile.id},
        )

    if payload.procedure_code is not None:
        pa.procedure_code = payload.procedure_code.strip()
    if payload.procedure_name is not None:
        pa.procedure_name = payload.procedure_name.strip()
    if payload.provider_name is not None:
        pa.provider_name = payload.provider_name
    if payload.status is not None:
        pa.status = payload.status
    if payload.submitted_date is not None:
        pa.submitted_date = payload.submitted_date
    if payload.decision_date is not None:
        pa.decision_date = payload.decision_date
    if payload.notes is not None:
        pa.notes = payload.notes

    pa.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(pa)

    return PriorAuthResponse(
        id=pa.id,
        profile_id=pa.profile_id,
        procedure_code=pa.procedure_code,
        procedure_name=pa.procedure_name,
        provider_name=pa.provider_name,
        status=pa.status,
        submitted_date=pa.submitted_date,
        decision_date=pa.decision_date,
        notes=pa.notes,
        created_at=pa.created_at,
        updated_at=pa.updated_at,
    )


@router.delete(
    "/profiles/{profile_id}/prior-auths/{prior_auth_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete prior authorization request",
)
async def delete_prior_auth(
    profile_id: str,
    prior_auth_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    profile = await _verify_profile(profile_id, user, db)
    stmt = select(PriorAuthorization).where(
        PriorAuthorization.profile_id == profile.id, PriorAuthorization.id == prior_auth_id
    )
    pa = (await db.execute(stmt)).scalar_one_or_none()
    if pa is not None:
        await db.delete(pa)
        await db.commit()
    return Response(status_code=204)


# Prior-authorizations path aliases
router.add_api_route(
    "/profiles/{profile_id}/prior-authorizations",
    create_prior_auth,
    methods=["POST"],
    response_model=PriorAuthResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
router.add_api_route(
    "/profiles/{profile_id}/prior-authorizations",
    list_prior_auths,
    methods=["GET"],
    response_model=List[PriorAuthResponse],
    include_in_schema=False,
)
router.add_api_route(
    "/profiles/{profile_id}/prior-authorizations/{prior_auth_id}",
    get_prior_auth,
    methods=["GET"],
    response_model=PriorAuthResponse,
    include_in_schema=False,
)
router.add_api_route(
    "/profiles/{profile_id}/prior-authorizations/{prior_auth_id}",
    update_prior_auth,
    methods=["PATCH"],
    response_model=PriorAuthResponse,
    include_in_schema=False,
)
router.add_api_route(
    "/profiles/{profile_id}/prior-authorizations/{prior_auth_id}",
    delete_prior_auth,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
