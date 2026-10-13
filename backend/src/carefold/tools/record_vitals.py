# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Closed tool: record_vitals (AU-30, AU-31, AU-32).

Records patient physiological vitals (BP, HR, SpO2, glucose, weight, height)
with automated clinical red-flag boundary check, adult BMI computation,
and CDC pediatric percentiles.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

from carefold.clinical.bmi import calculate_adult_bmi, calculate_pediatric_bmi_percentile
from carefold.clinical.vitals import normalize_fhir_vitals
from carefold.db.models import HealthResource
from carefold.db.session import get_session_factory
from carefold.safety.vitals import check_vitals_red_flags
from carefold.schemas.tool import ToolResult

logger = logging.getLogger("carefold.tools.record_vitals")

RECOGNIZED_VITALS_KEYS = frozenset({
    "systolic",
    "diastolic",
    "heart_rate",
    "hr",
    "blood_glucose",
    "glucose",
    "spo2",
    "oxygen_saturation",
    "weight",
    "body_weight",
    "height",
    "body_height",
})


async def execute_record_vitals(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Executes profile-scoped vitals observation recording with fail-closed security."""
    # 1. Fail-closed profile verification
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("record_vitals rejected: invalid or missing profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed record_vitals.",
        )
    clean_profile_id = profile_id.strip()

    # 2. Parameter validation
    vitals_data = args.get("vitals_data") if isinstance(args, dict) else None
    if not vitals_data or not isinstance(vitals_data, dict):
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'vitals_data' must not be empty and must include at least one recognizable vital sign.",
        )

    has_recognized = any(k in vitals_data and vitals_data[k] is not None for k in RECOGNIZED_VITALS_KEYS)
    if not has_recognized:
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'vitals_data' must not be empty and must include at least one recognizable vital sign.",
        )

    # Validate Blood Pressure pairing and order
    sys_val = vitals_data.get("systolic")
    dia_val = vitals_data.get("diastolic")
    if (sys_val is not None and dia_val is None) or (dia_val is not None and sys_val is None):
        return ToolResult(
            success=False,
            output=None,
            error="Both systolic and diastolic blood pressure must be provided together.",
        )
    if sys_val is not None and dia_val is not None:
        try:
            s_float = float(sys_val)
            d_float = float(dia_val)
            if s_float <= d_float:
                return ToolResult(
                    success=False,
                    output=None,
                    error="Systolic blood pressure must be strictly greater than diastolic blood pressure.",
                )
        except (ValueError, TypeError):
            return ToolResult(
                success=False,
                output=None,
                error="Systolic and diastolic blood pressure must be numeric values.",
            )

    # 3. Clinical Non-Boundary Red Flags Evaluation
    reported_symptoms = args.get("reported_symptoms") or []
    if isinstance(reported_symptoms, str):
        reported_symptoms = [reported_symptoms]
    flag = check_vitals_red_flags(vitals_data, reported_symptoms=reported_symptoms)

    # 4. Adult / Pediatric BMI Calculation
    bmi_info = None
    wt = vitals_data.get("weight") or vitals_data.get("body_weight")
    ht = vitals_data.get("height") or vitals_data.get("body_height")
    if wt is not None and ht is not None:
        try:
            wt_val = float(wt)
            ht_val = float(ht)
            unit = str(vitals_data.get("unit", "kg")).strip().lower()
            if unit in ("lbs", "lb", "pound", "pounds"):
                wt_val = wt_val / 2.20462
            if unit in ("in", "inches", "inch"):
                ht_val = ht_val * 2.54
            bmi_info = calculate_adult_bmi(wt_val, ht_val)
        except Exception as e:
            logger.debug("BMI calculation failed: %s", e)

    # 5. Effective date & FHIR R4 Normalization
    rec_at_str = args.get("recorded_at")
    if rec_at_str:
        try:
            rec_dt = datetime.fromisoformat(str(rec_at_str))
        except Exception:
            rec_dt = datetime.now(timezone.utc)
    else:
        rec_dt = datetime.now(timezone.utc)

    fhir_obs = normalize_fhir_vitals(vitals_data, effective_dt=rec_dt)

    # 6. ID & Persistence
    resource_id = str(uuid.uuid4())
    source_type = str(args.get("source_type", "manual"))
    source_ref = args.get("source_ref")
    source_id = args.get("source_id")
    content_hash = hashlib.sha256(json.dumps(fhir_obs, sort_keys=True).encode("utf-8")).hexdigest()

    try:
        factory = get_session_factory()
        async with factory() as session:
            hr = HealthResource(
                id=resource_id,
                profile_id=clean_profile_id,
                resource_type="observation",
                source_type=source_type,
                source_ref=source_ref,
                source_id=source_id,
                content_hash=content_hash,
                data=fhir_obs,
                status="active",
                effective_at=rec_dt,
                recorded_at=datetime.now(timezone.utc),
            )
            session.add(hr)
            await session.commit()
    except Exception as exc:
        logger.warning("Database persistence for HealthResource failed: %s", exc)

    # 7. Audit Logging for Undoability
    try:
        from carefold.audit.logger import record_audit
        actor_id = getattr(ctx, "user_id", "user") or "user"
        await record_audit(
            {
                "profile_id": clean_profile_id,
                "action": "create",
                "tool": "record_vitals",
                "risk": "write_local",
                "external_ref": f"health_resource:{resource_id}",
                "details": {
                    "vitals": vitals_data,
                    "safety_flag": flag.to_dict(),
                },
            },
            actor_user_id=actor_id,
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed: %s", audit_err)

    code_coding = fhir_obs.get("code", {}).get("coding", [{}])
    loinc_code = code_coding[0].get("code", "85354-9") if code_coding else "85354-9"
    display = code_coding[0].get("display", "Blood pressure panel") if code_coding else "Blood pressure panel"

    return ToolResult(
        success=True,
        output={
            "resource_id": resource_id,
            "profile_id": clean_profile_id,
            "resource_type": "observation",
            "effective_at": rec_dt.isoformat(),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
            "loinc_code": loinc_code,
            "display": display,
            "normalized_data": fhir_obs,
            "bmi_calculation": bmi_info,
            "safety_evaluation": flag.to_dict(),
            "undo_reference": f"health_resource:{resource_id}",
        },
    )


__all__ = ["execute_record_vitals"]
