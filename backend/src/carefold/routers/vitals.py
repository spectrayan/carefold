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

from collections.abc import Mapping
import copy
from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import json
import re
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yarvelle_core.api.deps import get_current_user, get_db, resolve_owner_user_id
from yarvelle_core.api.errors import ProblemDetailsRoute
from yarvelle_core.api.profiles import get_user_profile_access
from yarvelle_core.audit.logger import record_audit
from yarvelle_core.auth.ports import UserProfile
from carefold.clinical.bmi import calculate_adult_bmi, calculate_pediatric_bmi_percentile
from carefold.clinical.vitals import (
    LOINC_CODES,
    calculate_diurnal_bp_trends,
    normalize_fhir_vitals,
    parse_all_vitals_observations,
)
from carefold.errors import YarvelleError
from carefold.fhir.sql_pushdown import (
    build_code_sql_filter,
    build_observation_coding_rows,
    get_session_dialect_name,
)
from carefold.models import HealthResource
from yarvelle_core.db.models import Profile
from yarvelle_core.logging import get_logger
from carefold.safety.vitals import check_vitals_red_flags

logger = get_logger("carefold.api.vitals")

router = APIRouter(tags=["vitals"], route_class=ProblemDetailsRoute)


# ============================================================================
# Section 1: Pydantic Data Models
# ============================================================================


_VITAL_KEY_ALIASES: Dict[str, str] = {
    "systolic_bp": "systolic",
    "bp_systolic": "systolic",
    "blood_pressure_systolic": "systolic",
    "systolic_blood_pressure": "systolic",
    "sbp": "systolic",
    "diastolic_bp": "diastolic",
    "bp_diastolic": "diastolic",
    "blood_pressure_diastolic": "diastolic",
    "diastolic_blood_pressure": "diastolic",
    "dbp": "diastolic",
    "hr": "heart_rate",
    "pulse": "heart_rate",
    "pulse_rate": "heart_rate",
    "o2_sat": "spo2",
    "o2_saturation": "spo2",
    "spo2_percent": "spo2",
    "blood_oxygen": "spo2",
    "glucose": "blood_glucose",
    "bg": "blood_glucose",
    "body_weight": "weight",
    "body_height": "height",
    "temp": "temperature",
    "body_temperature": "temperature",
    "resp_rate": "respiratory_rate",
    "rr": "respiratory_rate",
    "breathing_rate": "respiratory_rate",
}

_CANONICAL_VITAL_KEYS = frozenset({
    "systolic",
    "diastolic",
    "heart_rate",
    "blood_glucose",
    "unit",
    "spo2",
    "oxygen_saturation",
    "weight",
    "height",
    "temperature",
    "temp_unit",
    "respiratory_rate",
})

_NUMERIC_VITAL_FIELDS = frozenset({
    "systolic",
    "diastolic",
    "heart_rate",
    "blood_glucose",
    "spo2",
    "oxygen_saturation",
    "weight",
    "height",
    "temperature",
    "respiratory_rate",
})

_BP_SLASH_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)")
_VITAL_NUMERIC_UNIT_RE = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*"
    r"(mmhg|bpm|%|mg/dl|mmol/l|kg|lbs?|cm|in(?:ches)?|°?[fc]|deg[fc]|breaths/min|/min)?\s*$",
    re.IGNORECASE,
)


def _normalize_vital_key(raw_key: Any) -> str:
    return str(raw_key).strip().lower().replace("-", "_").replace(" ", "_")


class VitalMeasurements(BaseModel):
    """Input payload containing physiological measurement values."""

    systolic: Optional[float] = Field(None, description="Systolic blood pressure in mmHg")
    diastolic: Optional[float] = Field(None, description="Diastolic blood pressure in mmHg")
    heart_rate: Optional[float] = Field(None, description="Heart rate in beats per minute")
    blood_glucose: Optional[float] = Field(None, description="Blood glucose concentration")
    unit: Optional[str] = Field(None, description="Unit: mg/dL, mmol/L, kg, lbs, cm, in")
    spo2: Optional[float] = Field(None, description="Oxygen saturation %")
    oxygen_saturation: Optional[float] = Field(None, description="Alias for spo2")
    weight: Optional[float] = Field(None, description="Body weight in kg or lbs")
    height: Optional[float] = Field(None, description="Body height in cm or inches")
    temperature: Optional[float] = Field(None, description="Body temperature in °F or °C")
    temp_unit: Optional[str] = Field(None, description="Body temperature unit: degF, F, Cel, C")
    respiratory_rate: Optional[float] = Field(None, description="Respiratory rate in breaths/min")

    @model_validator(mode="before")
    @classmethod
    def _normalize_vital_measurements(cls, raw: Any) -> Any:
        if not isinstance(raw, Mapping):
            return raw

        normalized: Dict[str, Any] = {}
        # Preserve exact canonical keys first, then fill from case/hyphen-folded & aliased keys.
        for raw_k, raw_v in raw.items():
            fold_k = _normalize_vital_key(raw_k)
            target_k = _VITAL_KEY_ALIASES.get(fold_k, fold_k)
            if str(raw_k) == target_k:
                normalized[target_k] = raw_v

        for raw_k, raw_v in raw.items():
            fold_k = _normalize_vital_key(raw_k)
            target_k = _VITAL_KEY_ALIASES.get(fold_k, fold_k)
            if target_k not in normalized or normalized[target_k] is None:
                normalized[target_k] = raw_v

        # Unpack compound blood_pressure / bp objects or "128/82 mmHg" strings.
        for bp_key in ("blood_pressure", "bp"):
            bp_val = normalized.pop(bp_key, None)
            if isinstance(bp_val, Mapping):
                bp_folded = {_normalize_vital_key(k): v for k, v in bp_val.items()}
                if normalized.get("systolic") is None and bp_folded.get("systolic") is not None:
                    normalized["systolic"] = bp_folded["systolic"]
                if normalized.get("diastolic") is None and bp_folded.get("diastolic") is not None:
                    normalized["diastolic"] = bp_folded["diastolic"]
            elif isinstance(bp_val, str):
                bp_match = _BP_SLASH_RE.match(bp_val)
                if bp_match:
                    if normalized.get("systolic") is None:
                        normalized["systolic"] = float(bp_match.group(1))
                    if normalized.get("diastolic") is None:
                        normalized["diastolic"] = float(bp_match.group(2))

        # Strip safe physiological unit suffixes from string-encoded measurements.
        for num_field in _NUMERIC_VITAL_FIELDS:
            val = normalized.get(num_field)
            if not isinstance(val, str):
                continue
            unit_match = _VITAL_NUMERIC_UNIT_RE.match(val)
            if not unit_match:
                continue
            normalized[num_field] = float(unit_match.group(1))
            unit_tok = (unit_match.group(2) or "").strip().lower()
            if num_field == "temperature" and not normalized.get("temp_unit"):
                if unit_tok in ("c", "°c", "cel", "degc"):
                    normalized["temp_unit"] = "Cel"
                elif unit_tok in ("f", "°f", "degf"):
                    normalized["temp_unit"] = "degF"
            elif num_field in ("blood_glucose", "weight", "height") and unit_tok and not normalized.get("unit"):
                unit_map = {
                    "mmol/l": "mmol/L",
                    "mg/dl": "mg/dL",
                    "lb": "lbs",
                    "lbs": "lbs",
                    "kg": "kg",
                    "in": "in",
                    "inch": "in",
                    "inches": "in",
                    "cm": "cm",
                }
                if unit_tok in unit_map:
                    normalized["unit"] = unit_map[unit_tok]

        return normalized


class VitalsUpdateRequest(BaseModel):
    """Payload for updating an existing vital observation."""

    vitals: Optional[VitalMeasurements] = None
    data: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    effective_at: Optional[datetime] = None


class VitalsCreateRequest(BaseModel):
    """Request schema for creating a profile vitals observation."""

    vitals: VitalMeasurements = Field(
        ...,
        description=(
            "Object of numeric vital signs using exact keys: systolic (mmHg), diastolic (mmHg), "
            "heart_rate (bpm), spo2 (%), blood_glucose, weight, height, temperature, respiratory_rate."
        ),
    )
    reported_symptoms: Optional[List[str]] = Field(
        default_factory=list,
        description="Optional list of concurrent symptom strings (pass [] if none).",
    )
    effective_at: Optional[datetime] = Field(None, description="Clinical observation timestamp (UTC)")
    source_type: Literal["manual", "device", "note_extracted"] = Field("manual", description="Observation origin")
    source_ref: Optional[str] = Field(
        None,
        max_length=255,
        description="Optional external source URI; leave null for manual entries.",
    )
    source_id: Optional[str] = Field(
        None,
        max_length=255,
        description="Optional external reading ID for device sync idempotency; leave null for manual entries.",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_create_request(cls, raw: Any) -> Any:
        if not isinstance(raw, Mapping):
            return raw

        data = dict(raw)
        if "reported_symptoms" in data:
            rs = data["reported_symptoms"]
            if rs is None or isinstance(rs, Mapping) or rs == "":
                data["reported_symptoms"] = []
            elif isinstance(rs, str):
                data["reported_symptoms"] = [rs.strip()] if rs.strip() else []

        if data.get("vitals") is None:
            recognized_top = _CANONICAL_VITAL_KEYS | set(_VITAL_KEY_ALIASES.keys()) | {"blood_pressure", "bp"}
            top_vitals: Dict[str, Any] = {}
            for k in list(data.keys()):
                if k in ("vitals", "reported_symptoms", "effective_at", "source_type", "source_ref", "source_id"):
                    continue
                if _normalize_vital_key(k) in recognized_top:
                    top_vitals[k] = data.pop(k)
            if top_vitals:
                data["vitals"] = top_vitals

        return data


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
    """Diurnal blood pressure moving averages (7/30/90 days) or single-metric trends."""

    profile_id: str
    metric: str = "blood_pressure"
    timezone: str
    computed_at: datetime
    trends: Dict[str, Any]
    latest_reading: Optional[Dict[str, Any]] = None


# ============================================================================
# Section 2: Permission & Auth Dependency
# ============================================================================


def require_profile_access(
    required_access: Literal["manage", "view_records", "view_paperwork"] = "view_records",
) -> Callable[..., Coroutine[Any, Any, Profile]]:
    """FastAPI dependency factory enforcing profile-level access control.

    Access Matrix:
    - 'manage': Required for mutating operations (POST /vitals).
    - 'view_records': Required for reading vitals & trends (GET /vitals).
    - 'view_paperwork': Strictly blocked from clinical vitals endpoints.
    """
    async def _dependency(
        profile_id: str,
        user: UserProfile = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> Profile:
        clean_id = (profile_id or "").strip()
        if not clean_id:
            raise YarvelleError(
                "YRV-100-004",
                detail="profile_id path parameter is required.",
                context={'parameter': "profile_id"},
            )

        stmt = select(Profile).where(Profile.id == clean_id)
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()
        if profile is None:
            raise YarvelleError(
                "YRV-500-002",
                detail=f"Profile '{clean_id}' not found.",
                context={'profile_id': clean_id},
            )

        access = await get_user_profile_access(profile, user, db)
        if access is None:
            raise YarvelleError(
                "YRV-300-007",
                detail="Access denied: you do not have permission for this profile.",
                context={'profile_id': clean_id},
            )

        if required_access == "manage" and access != "manage":
            raise YarvelleError(
                "CFD-300-003",
                detail="Access denied: management permissions required to modify this profile's clinical data.",
            )

        if required_access == "view_records" and access not in ("manage", "view_records"):
            raise YarvelleError(
                "CFD-300-003",
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
            v.temperature,
            v.respiratory_rate,
        ]
    )
    if not has_any:
        raise YarvelleError(
            "CFD-100-002",
            detail=(
                "At least one vital measurement must be provided "
                "(systolic, diastolic, heart_rate, spo2, blood_glucose, weight, height, temperature, or respiratory_rate)."
            ),
        )

    if (v.systolic is not None and v.diastolic is None) or (v.diastolic is not None and v.systolic is None):
        raise YarvelleError(
            "CFD-100-002",
            detail="Both systolic and diastolic blood pressure must be provided together.",
        )

    if v.systolic is not None and v.diastolic is not None:
        if v.systolic <= v.diastolic:
            raise YarvelleError(
                "CFD-100-002",
                detail="Systolic blood pressure must be strictly greater than diastolic blood pressure.",
            )

    if (v.weight is not None and v.weight <= 0) or (v.height is not None and v.height <= 0):
        raise YarvelleError(
            "CFD-100-002",
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
    all_observations = parse_all_vitals_observations(vitals_dict, effective_dt=effective_dt)
    if not all_observations:
        all_observations = [normalize_fhir_vitals(vitals_dict, effective_dt=effective_dt)]

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
            raise YarvelleError(
                "CFD-500-009",
                detail="Duplicate vital observation reading with identical source identifiers.",
            )

    created_ids: List[str] = []
    primary_id: Optional[str] = None
    primary_obs = all_observations[0]

    for idx, obs_item in enumerate(all_observations):
        new_id = str(uuid.uuid4())
        if idx == 0:
            primary_id = new_id
        created_ids.append(new_id)
        content_hash = hashlib.sha256(json.dumps(obs_item, sort_keys=True).encode("utf-8")).hexdigest()
        hr = HealthResource(
            id=new_id,
            profile_id=profile.id,
            resource_type="observation",
            source_type=payload.source_type,
            source_ref=payload.source_ref,
            source_id=payload.source_id,
            content_hash=content_hash,
            data=obs_item,
            status="active",
            effective_at=effective_dt,
            recorded_at=now_utc,
        )
        db.add(hr)
        coding_rows = build_observation_coding_rows(
            resource_id=new_id,
            profile_id=profile.id,
            fhir_data=obs_item,
            resource_type="Observation",
        )
        if coding_rows:
            db.add_all(coding_rows)

    try:
        await db.commit()
    except IntegrityError as integrity_err:
        await db.rollback()
        raise YarvelleError(
            "CFD-500-009",
            detail="Duplicate vital observation reading with identical source identifiers.",
            cause=integrity_err,
        ) from integrity_err

    # 7. Audit Event Recording for Undoability
    actor_id = resolve_owner_user_id(user) or getattr(user, "id", "user") or "user"
    try:
        await record_audit(
            {
                "profile_id": profile.id,
                "action": "create",
                "tool": "record_vitals",
                "risk": "write_local",
                "external_ref": f"health_resource:{primary_id}",
                "details": {
                    "vitals": vitals_dict,
                    "created_ids": created_ids,
                    "safety_flag": safety_resp.model_dump(),
                },
            },
            actor_user_id=actor_id,
            risk="write_local",
        )
    except Exception as err:
        logger.debug("Audit logging failed in vitals API: %s", err)

    return VitalsCreateResponse(
        id=primary_id or str(uuid.uuid4()),
        profile_id=profile.id,
        resource_type="observation",
        status="active",
        data=primary_obs,
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
    profile: Profile = Depends(require_profile_access("view_records")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> VitalsListResponse:
    """Lists historical vitals observations with SQL filtering, pagination, and privacy suppression."""
    dialect_name = get_session_dialect_name(db)
    conditions = [HealthResource.profile_id == profile.id]

    if status_filter != "all":
        conditions.append(HealthResource.status == status_filter)
    if resource_type:
        conditions.append(func.lower(HealthResource.resource_type) == resource_type.lower())
    if start_date:
        conditions.append(HealthResource.effective_at >= start_date)
    if end_date:
        conditions.append(HealthResource.effective_at <= end_date)
    if loinc_code:
        conditions.append(
            build_code_sql_filter(
                loinc_code,
                component_only_or_top=True,
                dialect_name=dialect_name,
            )
        )

    count_stmt = select(func.count()).select_from(HealthResource).where(*conditions)
    total = int((await db.execute(count_stmt)).scalar_one() or 0)

    page_stmt = (
        select(HealthResource)
        .where(*conditions)
        .order_by(HealthResource.effective_at.desc(), HealthResource.recorded_at.desc())
        .limit(limit)
        .offset(offset)
    )
    paged_records = list((await db.execute(page_stmt)).scalars().all())

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
    summary="Get diurnal blood pressure trends or metric trends for a profile",
)
async def get_profile_vitals_trends(
    profile_id: str,
    metric: str = Query("blood_pressure"),
    tz_param: Optional[str] = Query(None, alias="timezone"),
    days: Optional[int] = None,
    profile: Profile = Depends(require_profile_access("view_records")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> VitalsTrendsResponse:
    """Calculates 7/30/90-day diurnal AM/PM blood pressure trends or single-metric trends."""
    tz_name = tz_param or getattr(profile, "timezone", None) or "UTC"
    try:
        ZoneInfo(tz_name)
    except Exception as tz_err:
        raise YarvelleError(
            "CFD-100-002",
            detail=f"Invalid IANA timezone identifier: {tz_name!r}",
            cause=tz_err,
        ) from tz_err

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

    target_metric = (metric or "blood_pressure").strip().lower()

    if target_metric == "blood_pressure":
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
                    "effective_at": r.effective_at.isoformat() if r.effective_at else now_utc.isoformat(),
                    "data": r.data,
                }

        trend_dict = calculate_diurnal_bp_trends(readings, now_dt=now_utc, user_tz=tz_name)
        trends_map: Dict[str, Any] = {}
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
    else:
        loinc = LOINC_CODES.get(target_metric)
        metric_values: List[Dict[str, Any]] = []
        latest_reading = None
        for r in resources:
            if not isinstance(r.data, dict):
                continue
            val = None
            obs_code = None
            codings = r.data.get("code", {}).get("coding", [])
            for c in codings:
                c_code = c.get("code")
                if c_code:
                    obs_code = c_code
                    break

            if loinc and obs_code == loinc:
                val = r.data.get("valueQuantity", {}).get("value")
            elif target_metric in ("glucose", "blood_glucose") and obs_code == LOINC_CODES.get("blood_glucose"):
                val = r.data.get("valueQuantity", {}).get("value")
            elif target_metric in ("spo2", "oxygen_saturation") and obs_code == LOINC_CODES.get("oxygen_saturation"):
                val = r.data.get("valueQuantity", {}).get("value")
            elif target_metric in ("heart_rate", "hr") and obs_code == LOINC_CODES.get("heart_rate"):
                val = r.data.get("valueQuantity", {}).get("value")
            elif target_metric in ("weight", "body_weight") and obs_code == LOINC_CODES.get("body_weight"):
                val = r.data.get("valueQuantity", {}).get("value")
            elif target_metric in ("temperature", "temp") and obs_code == LOINC_CODES.get("temperature"):
                val = r.data.get("valueQuantity", {}).get("value")
            elif target_metric in ("respiratory_rate", "rr") and obs_code == LOINC_CODES.get("respiratory_rate"):
                val = r.data.get("valueQuantity", {}).get("value")

            if val is not None:
                try:
                    num_val = float(val)
                    eff_dt = r.effective_at or now_utc
                    if eff_dt.tzinfo is None:
                        eff_dt = eff_dt.replace(tzinfo=dt_timezone.utc)
                    metric_values.append({"val": num_val, "dt": eff_dt})
                    if latest_reading is None:
                        latest_reading = {
                            "id": r.id,
                            "effective_at": r.effective_at.isoformat() if r.effective_at else now_utc.isoformat(),
                            "data": r.data,
                        }
                except (ValueError, TypeError):
                    pass

        trends_map = {}
        for win_days, win_key in [(7, "7_day"), (30, "30_day"), (90, "90_day")]:
            win_cutoff = now_utc - timedelta(days=win_days)
            w_vals = [m["val"] for m in metric_values if m["dt"] >= win_cutoff]
            if w_vals:
                trends_map[win_key] = {
                    "count": len(w_vals),
                    "mean": round(sum(w_vals) / len(w_vals), 1),
                    "min": min(w_vals),
                    "max": max(w_vals),
                    "latest": w_vals[0],
                }
            else:
                trends_map[win_key] = {
                    "count": 0,
                    "mean": None,
                    "min": None,
                    "max": None,
                    "latest": None,
                }

    return VitalsTrendsResponse(
        profile_id=profile.id,
        metric=metric,
        timezone=tz_name,
        computed_at=now_utc,
        trends=trends_map,
        latest_reading=latest_reading,
    )


@router.get(
    "/profiles/{profile_id}/vitals/{vital_id}",
    response_model=VitalsItemResponse,
    summary="Get a specific vital observation",
)
async def get_profile_vital_reading(
    profile_id: str,
    vital_id: str,
    profile: Profile = Depends(require_profile_access("view_records")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> VitalsItemResponse:
    """Retrieves a single vital sign observation by ID with privacy suppression."""
    clean_vid = vital_id.strip()
    stmt = select(HealthResource).where(
        HealthResource.profile_id == profile.id,
        HealthResource.id == clean_vid,
        func.lower(HealthResource.resource_type) == "observation",
    )
    res = await db.execute(stmt)
    hr = res.scalar_one_or_none()
    if hr is None or hr.status == "deleted":
        raise YarvelleError(
            "CFD-500-001",
            detail=f"Vital observation '{clean_vid}' not found.",
            context={"vital_id": clean_vid, "profile_id": profile.id},
        )
    hide_weight = _is_weight_hidden(profile)
    record_data = _mask_weight_data(hr.data) if hide_weight else hr.data
    return VitalsItemResponse(
        id=hr.id,
        profile_id=hr.profile_id,
        resource_type=hr.resource_type,
        source_type=hr.source_type,
        source_ref=hr.source_ref,
        source_id=hr.source_id,
        status=hr.status,
        data=record_data,
        effective_at=hr.effective_at,
        recorded_at=hr.recorded_at,
    )


@router.patch(
    "/profiles/{profile_id}/vitals/{vital_id}",
    response_model=VitalsItemResponse,
    summary="Update a specific vital observation",
)
async def update_profile_vital_reading(
    profile_id: str,
    vital_id: str,
    payload: VitalsUpdateRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> VitalsItemResponse:
    """Updates an existing vital observation record."""
    clean_vid = vital_id.strip()
    stmt = select(HealthResource).where(
        HealthResource.profile_id == profile.id,
        HealthResource.id == clean_vid,
        func.lower(HealthResource.resource_type) == "observation",
    )
    res = await db.execute(stmt)
    hr = res.scalar_one_or_none()
    if hr is None or hr.status == "deleted":
        raise YarvelleError(
            "CFD-500-001",
            detail=f"Vital observation '{clean_vid}' not found.",
            context={"vital_id": clean_vid, "profile_id": profile.id},
        )

    if payload.vitals is not None:
        v_dict = payload.vitals.model_dump(exclude_none=True)
        if v_dict:
            new_obs = normalize_fhir_vitals(v_dict, effective_dt=payload.effective_at or hr.effective_at)
            hr.data = new_obs
    elif payload.data is not None:
        hr.data = payload.data

    if payload.status is not None:
        hr.status = payload.status
    if payload.effective_at is not None:
        hr.effective_at = payload.effective_at

    hr.updated_at = datetime.now(dt_timezone.utc)
    hr.content_hash = hashlib.sha256(json.dumps(hr.data, sort_keys=True).encode("utf-8")).hexdigest()

    await db.commit()
    await db.refresh(hr)

    actor_id = resolve_owner_user_id(user) or getattr(user, "id", "user") or "user"
    try:
        await record_audit(
            {
                "profile_id": profile.id,
                "action": "update",
                "tool": "update_vital_reading",
                "risk": "write_local",
                "external_ref": f"health_resource:{clean_vid}",
                "details": {"payload": payload.model_dump(exclude_none=True)},
            },
            actor_user_id=actor_id,
            risk="write_local",
        )
    except Exception as err:
        logger.debug("Audit logging failed in vitals update: %s", err)

    hide_weight = _is_weight_hidden(profile)
    record_data = _mask_weight_data(hr.data) if hide_weight else hr.data
    return VitalsItemResponse(
        id=hr.id,
        profile_id=hr.profile_id,
        resource_type=hr.resource_type,
        source_type=hr.source_type,
        source_ref=hr.source_ref,
        source_id=hr.source_id,
        status=hr.status,
        data=record_data,
        effective_at=hr.effective_at,
        recorded_at=hr.recorded_at,
    )


@router.delete(
    "/profiles/{profile_id}/vitals/{vital_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a vital observation",
)
async def delete_profile_vital_reading(
    profile_id: str,
    vital_id: str,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Response:
    """Deletes a vital observation from health_resources."""
    clean_vid = vital_id.strip()
    stmt = select(HealthResource).where(
        HealthResource.profile_id == profile.id,
        HealthResource.id == clean_vid,
        func.lower(HealthResource.resource_type) == "observation",
    )
    res = await db.execute(stmt)
    hr = res.scalar_one_or_none()
    if hr is None or hr.status == "deleted":
        raise YarvelleError(
            "CFD-500-001",
            detail=f"Vital observation '{clean_vid}' not found.",
            context={"vital_id": clean_vid, "profile_id": profile.id},
        )

    await db.delete(hr)
    await db.commit()

    actor_id = resolve_owner_user_id(user) or getattr(user, "id", "user") or "user"
    try:
        await record_audit(
            {
                "profile_id": profile.id,
                "action": "delete",
                "tool": "delete_vital_reading",
                "risk": "write_local",
                "external_ref": f"health_resource:{clean_vid}",
                "details": {"vital_id": clean_vid},
            },
            actor_user_id=actor_id,
            risk="write_local",
        )
    except Exception as err:
        logger.debug("Audit logging failed in vitals delete: %s", err)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
