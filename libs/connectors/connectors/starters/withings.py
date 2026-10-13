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

"""Withings Health Mate starter connector (AU-54 / E5.1)."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fhir.resources.R4B.observation import Observation as FhirObservation

from connectors.base import (
    Connector,
    NormalisedRecord,
    Page,
    StreamSpec,
    ToolContext,
    ToolSpec,
)
from connectors.http import ScopedHttp
from connectors.manifest import ConnectorManifest

_MANIFEST_PATH = Path(__file__).resolve().parent / "manifests" / "withings.yaml"

WITHINGS_MEASURE_URL = "https://wbsapi.withings.net/measure?action=getmeas"

# Withings meastype -> (LOINC code, display, unit display, UCUM code)
_SINGLE_MEAS_LOINC: Dict[int, Tuple[str, str, str, str]] = {
    1: ("29463-7", "Body weight", "kg", "kg"),
    4: ("8302-2", "Body height", "m", "m"),
    11: ("8867-4", "Heart rate", "beats/minute", "/min"),
    54: ("2708-6", "Oxygen saturation in Arterial blood", "%", "%"),
}

_BP_PANEL_LOINC = ("85354-9", "Blood pressure panel with all children optional")
_BP_SYSTOLIC_LOINC = ("8480-6", "Systolic blood pressure", "mmHg", "mm[Hg]")
_BP_DIASTOLIC_LOINC = ("8462-4", "Diastolic blood pressure", "mmHg", "mm[Hg]")


def _scale_withings_value(raw_measure: Dict[str, Any]) -> float:
    """Computes scaled float value from Withings `{value, unit}` representation."""
    raw_val = float(raw_measure.get("value", 0))
    unit_exp = raw_measure.get("unit")
    if unit_exp is None or isinstance(unit_exp, str):
        return round(raw_val, 4)
    return round(raw_val * (10 ** int(unit_exp)), 4)


def _extract_group_datetime(grp: Dict[str, Any]) -> Tuple[datetime, str, str]:
    """Extracts UTC datetime, ISO string, and YYYY-MM-DD from a Withings measuregrp."""
    raw_ts = grp.get("date") or grp.get("created")
    if isinstance(raw_ts, (int, float)):
        dt = datetime.fromtimestamp(float(raw_ts), tz=timezone.utc)
        iso_str = dt.isoformat()
        return dt, iso_str, dt.strftime("%Y-%m-%d")
    if isinstance(raw_ts, str) and raw_ts.strip():
        clean = raw_ts.strip()
        try:
            dt = datetime.fromisoformat(clean.replace("Z", "+00:00"))
            return dt, dt.isoformat(), dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    dt = datetime.now(timezone.utc)
    return dt, dt.isoformat(), dt.strftime("%Y-%m-%d")


class WithingsConnector:
    """Starter connector for Withings Health Mate smart scales and BP monitors."""

    def __init__(self, manifest: Optional[ConnectorManifest] = None) -> None:
        self._manifest = manifest or ConnectorManifest.from_yaml(_MANIFEST_PATH)
        self._latest_records: List[NormalisedRecord] = []

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def streams(self) -> List[StreamSpec]:
        return [
            StreamSpec(
                name="measures",
                description="Weight, blood pressure, heart rate, and SpO2 readings",
                read_mode="incremental",
                primary_key=["grpid"],
                cursor_field="lastupdate",
            )
        ]

    async def fetch(
        self,
        ctx: ToolContext,
        stream: str,
        cursor: Optional[str],
        http: ScopedHttp,
    ) -> Page:
        """Fetches measure groups from Withings `measure?action=getmeas` endpoint."""
        if not ctx.profile_id or not ctx.user_id:
            raise ValueError("ToolContext user_id and profile_id are required.")
        if stream != "measures":
            raise ValueError(f"Unsupported stream '{stream}' for WithingsConnector.")

        url = WITHINGS_MEASURE_URL
        if cursor:
            url = f"{WITHINGS_MEASURE_URL}&lastupdate={cursor}"

        response = await http.get(url)
        payload = response.json() if hasattr(response, "json") else {}
        body = payload.get("body") if isinstance(payload.get("body"), dict) else payload
        measuregrps = body.get("measuregrps") if isinstance(body, dict) else []
        if not isinstance(measuregrps, list):
            measuregrps = []

        enriched_groups: List[Dict[str, Any]] = []
        max_ts: Optional[int] = None
        for grp in measuregrps:
            if not isinstance(grp, dict):
                continue
            item = dict(grp)
            item.setdefault("profile_id", ctx.profile_id)
            enriched_groups.append(item)
            grp_ts = item.get("date") or item.get("created")
            if isinstance(grp_ts, (int, float)):
                ts_int = int(grp_ts)
                if max_ts is None or ts_int > max_ts:
                    max_ts = ts_int

        updatetime = body.get("updatetime") if isinstance(body, dict) else None
        next_cursor = (
            str(updatetime)
            if updatetime is not None
            else (str(max_ts) if max_ts is not None else cursor)
        )
        has_more = bool(body.get("more")) if isinstance(body, dict) else False

        return Page(
            stream=stream,
            records=enriched_groups,
            next_cursor=next_cursor,
            has_more=has_more,
            metadata={"profile_id": ctx.profile_id, "user_id": ctx.user_id},
        )

    def map(self, page: Page) -> List[NormalisedRecord]:
        """Normalizes Withings `measuregrps` into FHIR R4 `Observation` records."""
        normalised: List[NormalisedRecord] = []
        default_profile_id = str(page.metadata.get("profile_id") or "default-profile")

        for grp_idx, grp in enumerate(page.records):
            if not isinstance(grp, dict):
                continue
            profile_id = str(grp.get("profile_id") or default_profile_id)
            grp_id = str(grp.get("grpid") or grp.get("id") or f"grp-{grp_idx}")
            eff_dt, eff_iso, date_str = _extract_group_datetime(grp)
            measures = grp.get("measures") or []
            if not isinstance(measures, list):
                continue

            systolic_val: Optional[float] = None
            diastolic_val: Optional[float] = None

            for m_idx, m in enumerate(measures):
                if not isinstance(m, dict):
                    continue
                raw_type = m.get("type") if m.get("type") is not None else m.get("meastype")
                if raw_type is None:
                    continue
                mtype = int(raw_type)
                scaled_val = _scale_withings_value(m)

                if mtype == 10:
                    systolic_val = scaled_val
                    continue
                if mtype == 9:
                    diastolic_val = scaled_val
                    continue

                if mtype not in _SINGLE_MEAS_LOINC:
                    continue

                loinc_code, display_name, unit_label, ucum_code = _SINGLE_MEAS_LOINC[mtype]
                obs_id = f"withings-{grp_id}-{mtype}-{m_idx}"
                obs_candidate = {
                    "resourceType": "Observation",
                    "id": obs_id,
                    "meta": {
                        "source": "withings",
                        "tag": [
                            {
                                "system": "https://carefold.ai/trust",
                                "code": "trusted",
                                "display": f"From Withings Health Mate, {date_str}",
                            }
                        ],
                    },
                    "status": "final",
                    "category": [
                        {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                    "code": "vital-signs",
                                    "display": "Vital Signs",
                                }
                            ]
                        }
                    ],
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": loinc_code,
                                "display": display_name,
                            }
                        ],
                        "text": display_name,
                    },
                    "effectiveDateTime": eff_iso,
                    "valueQuantity": {
                        "value": scaled_val,
                        "unit": unit_label,
                        "system": "http://unitsofmeasure.org",
                        "code": ucum_code,
                    },
                }
                validated_obs = FhirObservation.model_validate(obs_candidate).model_dump(
                    mode="json", exclude_none=True
                )
                raw_hash = hashlib.sha256(
                    json.dumps(validated_obs, sort_keys=True).encode("utf-8")
                ).hexdigest()
                normalised.append(
                    NormalisedRecord(
                        id=obs_id,
                        stream=page.stream,
                        profile_id=profile_id,
                        source=self._manifest.id,
                        record_type="Observation",
                        timestamp=eff_dt,
                        data=validated_obs,
                        raw_hash=raw_hash,
                    )
                )

            if systolic_val is not None or diastolic_val is not None:
                components: List[Dict[str, Any]] = []
                if systolic_val is not None:
                    sys_code, sys_disp, sys_unit, sys_ucum = _BP_SYSTOLIC_LOINC
                    components.append(
                        {
                            "code": {
                                "coding": [
                                    {
                                        "system": "http://loinc.org",
                                        "code": sys_code,
                                        "display": sys_disp,
                                    }
                                ],
                                "text": sys_disp,
                            },
                            "valueQuantity": {
                                "value": systolic_val,
                                "unit": sys_unit,
                                "system": "http://unitsofmeasure.org",
                                "code": sys_ucum,
                            },
                        }
                    )
                if diastolic_val is not None:
                    dia_code, dia_disp, dia_unit, dia_ucum = _BP_DIASTOLIC_LOINC
                    components.append(
                        {
                            "code": {
                                "coding": [
                                    {
                                        "system": "http://loinc.org",
                                        "code": dia_code,
                                        "display": dia_disp,
                                    }
                                ],
                                "text": dia_disp,
                            },
                            "valueQuantity": {
                                "value": diastolic_val,
                                "unit": dia_unit,
                                "system": "http://unitsofmeasure.org",
                                "code": dia_ucum,
                            },
                        }
                    )

                bp_id = f"withings-{grp_id}-bp"
                bp_candidate = {
                    "resourceType": "Observation",
                    "id": bp_id,
                    "meta": {
                        "source": "withings",
                        "tag": [
                            {
                                "system": "https://carefold.ai/trust",
                                "code": "trusted",
                                "display": f"From Withings Health Mate, {date_str}",
                            }
                        ],
                    },
                    "status": "final",
                    "category": [
                        {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                    "code": "vital-signs",
                                    "display": "Vital Signs",
                                }
                            ]
                        }
                    ],
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": _BP_PANEL_LOINC[0],
                                "display": _BP_PANEL_LOINC[1],
                            }
                        ],
                        "text": _BP_PANEL_LOINC[1],
                    },
                    "effectiveDateTime": eff_iso,
                    "component": components,
                }
                validated_bp = FhirObservation.model_validate(bp_candidate).model_dump(
                    mode="json", exclude_none=True
                )
                raw_hash = hashlib.sha256(
                    json.dumps(validated_bp, sort_keys=True).encode("utf-8")
                ).hexdigest()
                normalised.append(
                    NormalisedRecord(
                        id=bp_id,
                        stream=page.stream,
                        profile_id=profile_id,
                        source=self._manifest.id,
                        record_type="Observation",
                        timestamp=eff_dt,
                        data=validated_bp,
                        raw_hash=raw_hash,
                    )
                )

        self._latest_records = list(normalised)
        return normalised

    def tools(self) -> List[ToolSpec]:
        async def _latest_vitals_handler(
            ctx: ToolContext,
            args: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            if not ctx.profile_id or not ctx.user_id:
                raise ValueError("ToolContext user_id and profile_id are required.")
            params = args or {}
            records = [
                r.data
                for r in self._latest_records
                if r.profile_id in (ctx.profile_id, "default-profile")
            ]
            limit = int(params.get("limit", 10))
            return {
                "connector_id": self._manifest.id,
                "profile_id": ctx.profile_id,
                "trust": "trusted",
                "count": len(records[:limit]),
                "observations": records[:limit],
            }

        return [
            ToolSpec(
                name="withings_latest_vitals",
                description="Retrieves the most recent normalized Withings vital sign observations.",
                parameters={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of recent vital observations to return",
                            "default": 10,
                        }
                    },
                },
                risk_class="read_only",
                risk_tier="read",
                trust="trusted",
                data_flows=("wbsapi.withings.net",),
                handler=_latest_vitals_handler,
            )
        ]


__all__ = [
    "WITHINGS_MEASURE_URL",
    "WithingsConnector",
]
