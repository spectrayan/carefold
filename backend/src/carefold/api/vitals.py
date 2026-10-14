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

"""REST API endpoints for Patient Vitals, Diurnal Trends, and Safety Red Flags (AU-30, AU-31, AU-32)."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import json
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, get_db, resolve_owner_user_id
from carefold.api.profiles import get_user_profile_access
from carefold.audit.logger import record_audit
from carefold.auth.ports import UserProfile
from carefold.clinical.bmi import calculate_adult_bmi, calculate_pediatric_bmi_percentile
from carefold.clinical.vitals import calculate_diurnal_bp_trends, normalize_fhir_vitals
from carefold.db.models import HealthResource, Profile
from carefold.logging import get_logger
from carefold.safety.vitals import check_vitals_red_flags

logger = get_logger("carefold.api.vitals")

router = APIRouter(tags=["vitals"])


# ============================================================================
# Section 1: Pydantic Data Models
# ============================================================================


class VitalMeasurements(BaseModel):
    """Input payload containing physiological measurement values."""

    systolic: Optional[float] = Field(None, description="Systolic blood pressure in mmHg")
    diastolic: Optional[float] = Field(None, description="Diastolic blood pressure in mmHg")
    heart_rate: Optional[float] = Field(None, description="Heart rate in beats per minute")
    blood_glucose: Optional[float] = Field(None, description="Blood glucose concentration")
    unit: Optional[str] = Field("mg/dL", description="Unit: mg/dL, mmol/L, kg, lbs, cm, in")
    spo2: Optional[float] = Field(None, description="Oxygen saturation %")
    oxygen_saturation: Optional[float] = Field(None, description="Alias for spo2")
    weight: Optional[float] = Field(None, description="Body weight in kg or lbs")
    height: Optional[float] = Field(None, description="Body height in cm or inches")


class VitalsCreateRequest(BaseModel):
    """Request schema for creating a profile vitals observation."""

    vitals: VitalMeasurements = Field(..., description="Key-value dictionary of vital signs")
    reported_symptoms: Optional[List[str]] = Field(default_factory=list, description="Concurrent symptoms")
    effective_at: Optional[datetime] = Field(None, description="Clinical observation timestamp (UTC)")
    source_type: Literal["manual", "device", "note_extracted"] = Field("manual", description="Observation origin")
    source_ref: Optional[str] = Field(None, max_length=255, description="Source URI or document reference")
    source_id: Optional[str] = Field(None, max_length=255, description="External reading ID for idempotency")


class EmergencyRedFlagResponse(BaseModel):
    """Clinical boundary safety screening evaluation."""

    triggered: bool = False
    category: Optional[str] = None
    severity: Literal["emergency", "urgent", "normal"] = "normal"
    directive: Optional[str] = None
    prompt_recheck: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)


class BmiCalculationResponse(BaseModel):
    """Calculated BMI or CDC pediatric LMS percentile."""

    bmi: Optional[float] = None
    classification: Optional[str] = None
    percentile: Optional[float] = None
    z_score: Optional[float] = None
    suppressed: bool = False
    weight_hidden: bool = False
    reason: Optional[str] = None


class VitalsCreateResponse(BaseModel):
    """Response schema upon vitals observation creation."""

    id: str
    profile_id: str
    resource_type: str = "observation"
    status: str = "active"
    data: Dict[str, Any]
    effective_at: datetime
    recorded_at: datetime
    bmi: Optional[BmiCalculationResponse] = None
    safety_flag: EmergencyRedFlagResponse
    undo_available: bool = True


class VitalsItemResponse(BaseModel):
    """Individual vital observation item in list response."""

    id: str
    profile_id: str
    resource_type: str
    source_type: str
    source_ref: Optional[str] = None
    source_id: Optional[str] = None
    status: str
    data: Dict[str, Any]
    effective_at: datetime
    recorded_at: datetime


class VitalsListResponse(BaseModel):
    """Paginated list of profile vitals observations."""

    items: List[VitalsItemResponse]
    total: int
    limit: int
    offset: int


class TrendWindowMetrics(BaseModel):
    """Diurnal window blood pressure metrics and AHA/ACC classification."""

    count: int = 0
    systolic: Optional[float] = None
    diastolic: Optional[float] = None
    classification: str = "Insufficient Data"


class DiurnalTrendWindow(BaseModel):
    """AM and PM diurnal breakdown for a moving average window."""

    am: TrendWindowMetrics
    pm: TrendWindowMetrics


class VitalsTrendsResponse(BaseModel):
    """Diurnal blood pressure moving averages (7/30/90 days)."""

    profile_id: str
    metric: str = "blood_pressure"
    timezone: str
    computed_at: datetime
    trends: Dict[str, DiurnalTrendWindow]
    latest_reading: Optional[Dict[str, Any]] = None


# ============================================================================
# Section 2: Permission & Auth Dependency
# ============================================================================


def require_profile_access(
    required_access: Literal["manage", "view_clinical", "view_paperwork"] = "view_clinical",
) -> Callable[..., Coroutine[Any, Any, Profile]]:
    """FastAPI dependency factory enforcing profile-level access control.

    Access Matrix:
    - 'manage': Required for mutating operations (POST /vitals).
    - 'view_clinical': Required for reading vitals & trends (GET /vitals).
    - 'view_paperwork': Strictly blocked from clinical vitals endpoints.
    """
    async def _dependency(
        profile_id: str,
        user: UserProfile = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> Profile:
        clean_id = (profile_id or "").strip()
        if not clean_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="profile_id path parameter is required.",
            )

        stmt = select(Profile).where(Profile.id == clean_id)
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile '{clean_id}' not found.",
            )

        access = await get_user_profile_access(profile, user, db)
        if access is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: you do not have permission for this profile.",
            )

        if required_access == "manage" and access != "manage":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: management permissions required to modify this profile's clinical data.",
            )

        if required_access == "view_clinical" and access not in ("manage", "view_clinical"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: clinical view permissions required to inspect clinical vitals.",
            )

        return profile

    return _dependency


_profile_preferences: Dict[str, Dict[str, Any]] = {}


def set_profile_preference(profile_id: str, key: str, value: Any) -> None:
    """Sets a runtime preference for a profile (e.g. hide_weight)."""
    _profile_preferences.setdefault(profile_id, {})[key] = value


def get_profile_preference(profile_id: str, key: str, default: Any = None) -> Any:
    """Gets a runtime preference for a profile."""
    return _profile_preferences.get(profile_id, {}).get(key, default)


def _is_weight_hidden(profile: Profile, override: Optional[bool] = None) -> bool:
    """Helper determining whether weight display should be suppressed for a profile."""
    if override is not None:
        return override
    pref = get_profile_preference(profile.id, "hide_weight")
    if pref is not None:
        return bool(pref)
    if getattr(profile, "hide_weight", False):
        return True
    if hasattr(profile, "preferences") and isinstance(profile.preferences, dict):
        return bool(profile.preferences.get("hide_weight", False))
    if hasattr(profile, "preferences_json") and profile.preferences_json:
        try:
            prefs = json.loads(profile.preferences_json)
            if isinstance(prefs, dict):
                return bool(prefs.get("hide_weight", False))
        except Exception:
            pass
    return False


def _mask_weight_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Masks weight measurement values in FHIR Observation JSON."""
    if not isinstance(data, dict):
        return data
    data_copy = copy.deepcopy(data)
    coding = data_copy.get("code", {}).get("coding", [])
    is_weight = any(
        c.get("code") == "29463-7" or "weight" in str(c.get("display", "")).lower()
        for c in coding
        if isinstance(c, dict)
    )
    if is_weight:
        if "valueQuantity" in data_copy and isinstance(data_copy["valueQuantity"], dict):
            data_copy["valueQuantity"]["value"] = None
        data_copy["weight_hidden"] = True
    return data_copy


# ============================================================================
# Section 3: REST Endpoints
# ============================================================================


@router.post(
    "/profiles/{profile_id}/vitals",
    response_model=VitalsCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record vital signs observation for a profile",
)
async def create_profile_vitals(
    profile_id: str,
    payload: VitalsCreateRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> VitalsCreateResponse:
    """Records a new vital signs observation with FHIR normalization, safety evaluation, and BMI calculation."""
    v = payload.vitals

    # 1. Physiological validation
    has_any = any(
        x is not None
        for x in [
            v.systolic,
            v.diastolic,
            v.heart_rate,
            v.blood_glucose,
            v.spo2,
            v.oxygen_saturation,
            v.weight,
            v.height,
        ]
    )
    if not has_any:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one vital measurement must be provided.",
        )

    if (v.systolic is not None and v.diastolic is None) or (v.diastolic is not None and v.systolic is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both systolic and diastolic blood pressure must be provided together.",
        )

    if v.systolic is not None and v.diastolic is not None:
        if v.systolic <= v.diastolic:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Systolic blood pressure must be strictly greater than diastolic blood pressure.",
            )

    if (v.weight is not None and v.weight <= 0) or (v.height is not None and v.height <= 0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Weight and height must be strictly positive.",
        )

    # 2. Observation timestamp
    effective_dt = payload.effective_at or datetime.now(dt_timezone.utc)
    now_utc = datetime.now(dt_timezone.utc)

    # 3. Clinical Non-Boundary Red Flags Screening
    vitals_dict = v.model_dump(exclude_none=True)
    flag = check_vitals_red_flags(vitals_dict, reported_symptoms=payload.reported_symptoms or [])
    safety_resp = EmergencyRedFlagResponse(
        triggered=flag.triggered,
        category=flag.category,
        severity=flag.severity,
        directive=flag.directive,
        prompt_recheck=flag.prompt_recheck,
        details=flag.details or {},
    )

    # 4. Adult / Pediatric BMI Calculation
    bmi_resp: Optional[BmiCalculationResponse] = None
    if v.weight is not None and v.height is not None:
        hide_weight = _is_weight_hidden(profile)
        unit = (v.unit or "kg").strip().lower()
        wt_kg = v.weight / 2.20462 if unit in ("lbs", "lb", "pound", "pounds") else v.weight
        ht_cm = v.height * 2.54 if unit in ("in", "inches", "inch") else v.height

        age_months = None
        if profile.date_of_birth:
            try:
                dob = datetime.strptime(profile.date_of_birth, "%Y-%m-%d").date()
                ref_date = effective_dt.date()
                age_months = (ref_date.year - dob.year) * 12 + (ref_date.month - dob.month)
            except Exception:
                age_months = None

        try:
            if age_months is not None and age_months < 0:
                # Future date of birth: suppress BMI with explanatory reason
                bmi_dict = {
                    "suppressed": True,
                    "weight_hidden": False,
                    "bmi": None,
                    "percentile": None,
                    "reason": "Date of birth is in the future; age in months cannot be negative.",
                }
            elif age_months is not None and 0 <= age_months < 240:
                raw_gender = (getattr(profile, "gender", "male") or "male").strip().lower()
                if raw_gender in ("male", "m", "boy"):
                    norm_gender = "male"
                elif raw_gender in ("female", "f", "girl"):
                    norm_gender = "female"
                else:
                    norm_gender = None

                if norm_gender is None:
                    # Non-binary or unlisted gender: compute adult BMI, suppress CDC LMS percentile
                    adult_fallback = calculate_adult_bmi(weight_kg=wt_kg, height_cm=ht_cm, hide_weight=hide_weight)
                    bmi_dict = {
                        "suppressed": True,
                        "weight_hidden": False,
                        "bmi": adult_fallback.get("bmi"),
                        "percentile": None,
                        "reason": "CDC pediatric LMS growth charts are defined for biological sex (male/female); percentile is suppressed for non-binary gender.",
                    }
                else:
                    bmi_dict = calculate_pediatric_bmi_percentile(
                        age_months=age_months,
                        gender=norm_gender,
                        weight_kg=wt_kg,
                        height_cm=ht_cm,
                        hide_weight=hide_weight,
                    )
            else:
                bmi_dict = calculate_adult_bmi(
                    weight_kg=wt_kg,
                    height_cm=ht_cm,
                    hide_weight=hide_weight,
                )
        except ValueError as e:
            bmi_dict = {
                "suppressed": True,
                "weight_hidden": False,
                "bmi": None,
                "percentile": None,
                "reason": f"BMI calculation suppressed due to invalid input: {e}",
            }

        bmi_resp = BmiCalculationResponse(
            bmi=bmi_dict.get("bmi"),
            classification=bmi_dict.get("classification"),
            percentile=bmi_dict.get("percentile"),
            z_score=bmi_dict.get("z_score"),
            suppressed=bmi_dict.get("suppressed", False),
            weight_hidden=bmi_dict.get("weight_hidden", False),
            reason=bmi_dict.get("reason"),
        )

    # 5. FHIR R4 Normalization
    fhir_obs = normalize_fhir_vitals(vitals_dict, effective_dt=effective_dt)

    # 6. Idempotency Check & Persistence
    if payload.source_ref is not None or payload.source_id is not None:
        dup_stmt = select(HealthResource.id).where(
            HealthResource.profile_id == profile.id,
            HealthResource.source_type == payload.source_type,
            HealthResource.source_ref == payload.source_ref,
            HealthResource.source_id == payload.source_id,
        )
        dup_res = await db.execute(dup_stmt)
        if dup_res.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Duplicate vital observation reading with identical source identifiers.",
            )

    new_id = str(uuid.uuid4())
    content_hash = hashlib.sha256(json.dumps(fhir_obs, sort_keys=True).encode("utf-8")).hexdigest()
    hr = HealthResource(
        id=new_id,
        profile_id=profile.id,
        resource_type="observation",
        source_type=payload.source_type,
        source_ref=payload.source_ref,
        source_id=payload.source_id,
        content_hash=content_hash,
        data=fhir_obs,
        status="active",
        effective_at=effective_dt,
        recorded_at=now_utc,
    )
    db.add(hr)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate vital observation reading with identical source identifiers.",
        )

    # 7. Audit Event Recording for Undoability
    actor_id = resolve_owner_user_id(user) or getattr(user, "id", "user") or "user"
    try:
        await record_audit(
            {
                "profile_id": profile.id,
                "action": "create",
                "tool": "record_vitals",
                "risk": "write_local",
                "external_ref": f"health_resource:{new_id}",
                "details": {
                    "vitals": vitals_dict,
                    "safety_flag": safety_resp.model_dump(),
                },
            },
            actor_user_id=actor_id,
            risk="write_local",
        )
    except Exception as err:
        logger.debug("Audit logging failed in vitals API: %s", err)

    return VitalsCreateResponse(
        id=new_id,
        profile_id=profile.id,
        resource_type="observation",
        status="active",
        data=fhir_obs,
        effective_at=effective_dt,
        recorded_at=now_utc,
        bmi=bmi_resp,
        safety_flag=safety_resp,
        undo_available=True,
    )


@router.get(
    "/profiles/{profile_id}/vitals",
    response_model=VitalsListResponse,
    summary="Query vitals observations for a profile",
)
async def list_profile_vitals(
    profile_id: str,
    resource_type: str = "observation",
    loinc_code: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    status_filter: str = Query("active", alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> VitalsListResponse:
    """Lists historical vitals observations with pagination and privacy suppression."""
    stmt = select(HealthResource).where(HealthResource.profile_id == profile.id)

    if status_filter != "all":
        stmt = stmt.where(HealthResource.status == status_filter)
    if resource_type:
        stmt = stmt.where(HealthResource.resource_type == resource_type)
    if start_date:
        stmt = stmt.where(HealthResource.effective_at >= start_date)
    if end_date:
        stmt = stmt.where(HealthResource.effective_at <= end_date)

    # Order chronologically descending
    stmt = stmt.order_by(HealthResource.effective_at.desc(), HealthResource.recorded_at.desc())

    res = await db.execute(stmt)
    all_matching = list(res.scalars().all())

    # Optional LOINC code filter
    if loinc_code:
        filtered = []
        for r in all_matching:
            data = r.data or {}
            coding_list = data.get("code", {}).get("coding", [])
            has_code = any(c.get("code") == loinc_code for c in coding_list if isinstance(c, dict))
            if not has_code:
                for comp in data.get("component", []):
                    comp_codings = comp.get("code", {}).get("coding", [])
                    if any(c.get("code") == loinc_code for c in comp_codings if isinstance(c, dict)):
                        has_code = True
                        break
            if has_code:
                filtered.append(r)
        all_matching = filtered

    total = len(all_matching)
    paged_records = all_matching[offset : offset + limit]

    hide_weight = _is_weight_hidden(profile)
    items = []
    for r in paged_records:
        record_data = _mask_weight_data(r.data) if hide_weight else r.data
        items.append(
            VitalsItemResponse(
                id=r.id,
                profile_id=r.profile_id,
                resource_type=r.resource_type,
                source_type=r.source_type,
                source_ref=r.source_ref,
                source_id=r.source_id,
                status=r.status,
                data=record_data,
                effective_at=r.effective_at,
                recorded_at=r.recorded_at,
            )
        )

    return VitalsListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/profiles/{profile_id}/vitals/trends",
    response_model=VitalsTrendsResponse,
    summary="Get diurnal blood pressure trends for a profile",
)
async def get_profile_vitals_trends(
    profile_id: str,
    metric: str = Query("blood_pressure"),
    tz_param: Optional[str] = Query(None, alias="timezone"),
    days: Optional[int] = None,
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> VitalsTrendsResponse:
    """Calculates 7/30/90-day diurnal AM/PM blood pressure trends per AHA/ACC 2025 guidelines."""
    tz_name = tz_param or getattr(profile, "timezone", None) or "UTC"
    try:
        ZoneInfo(tz_name)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid IANA timezone identifier: {tz_name!r}",
        )

    now_utc = datetime.now(dt_timezone.utc)
    lookback_days = days if days is not None else 90
    cutoff = now_utc - timedelta(days=lookback_days)

    stmt = (
        select(HealthResource)
        .where(
            HealthResource.profile_id == profile.id,
            HealthResource.resource_type == "observation",
            HealthResource.status == "active",
            HealthResource.effective_at >= cutoff,
        )
        .order_by(HealthResource.effective_at.desc())
    )
    res = await db.execute(stmt)
    resources = list(res.scalars().all())

    readings = []
    latest_reading: Optional[Dict[str, Any]] = None
    for r in resources:
        readings.append({
            "effective_at": r.effective_at,
            "data": r.data,
        })
        if latest_reading is None and r.data:
            latest_reading = {
                "id": r.id,
                "effective_at": r.effective_at.isoformat(),
                "data": r.data,
            }

    trend_dict = calculate_diurnal_bp_trends(readings, now_dt=now_utc, user_tz=tz_name)
    trends_map: Dict[str, DiurnalTrendWindow] = {}
    for win_key, win_data in trend_dict.items():
        trends_map[win_key] = DiurnalTrendWindow(
            am=TrendWindowMetrics(
                count=win_data["am"]["count"],
                systolic=win_data["am"]["systolic"],
                diastolic=win_data["am"]["diastolic"],
                classification=win_data["am"]["classification"],
            ),
            pm=TrendWindowMetrics(
                count=win_data["pm"]["count"],
                systolic=win_data["pm"]["systolic"],
                diastolic=win_data["pm"]["diastolic"],
                classification=win_data["pm"]["classification"],
            ),
        )

    return VitalsTrendsResponse(
        profile_id=profile.id,
        metric=metric,
        timezone=tz_name,
        computed_at=now_utc,
        trends=trends_map,
        latest_reading=latest_reading,
    )


__all__ = ["router"]
