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

"""Streaming Apple Health (`export.xml` / `.zip`) parser with daily aggregation (AU-38 / E10.2, E8.0).

Enforces:
- Streaming O(1) memory footprint via `xml.etree.ElementTree.iterparse` and `elem.clear()`.
- XXE defense: rejects `<!ENTITY` declarations while safely stripping Apple Health's benign
  internal `<!DOCTYPE HealthData [...]>` header if present.
- High-Frequency Stream Aggregation Invariant (Titan S4 / E8.0):
  - High-frequency wearable streams (`HeartRate`, `StepCount`, `ActiveEnergyBurned`,
    `SleepAnalysis`) are aggregated per calendar day (`YYYY-MM-DD`) and NEVER emitted
    as raw minute-by-minute rows.
  - Low-frequency clinical vitals (`BloodPressureSystolic`/`Diastolic`, `BodyMass`,
    `Height`, `OxygenSaturation`, `BloodGlucose`) are emitted as individual FHIR R4
    `Observation` resources (pairing concurrent systolic + diastolic into BP panel `85354-9`).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from typing import Any, BinaryIO, Dict, List, Optional, Tuple
import zipfile

from defusedxml import ElementTree as DET
from defusedxml.common import DefusedXmlException

HIGH_FREQUENCY_HK_TYPES = frozenset({
    "HKQuantityTypeIdentifierHeartRate",
    "HKQuantityTypeIdentifierStepCount",
    "HKQuantityTypeIdentifierActiveEnergyBurned",
    "HKCategoryTypeIdentifierSleepAnalysis",
})

LOW_FREQUENCY_CLINICAL_HK_TYPES = frozenset({
    "HKQuantityTypeIdentifierBloodPressureSystolic",
    "HKQuantityTypeIdentifierBloodPressureDiastolic",
    "HKQuantityTypeIdentifierBodyMass",
    "HKQuantityTypeIdentifierHeight",
    "HKQuantityTypeIdentifierOxygenSaturation",
    "HKQuantityTypeIdentifierBloodGlucose",
})

_CLINICAL_LOINC_MAP: Dict[str, Tuple[str, str, str]] = {
    "HKQuantityTypeIdentifierBloodPressureSystolic": ("8480-6", "Systolic blood pressure", "mmHg"),
    "HKQuantityTypeIdentifierBloodPressureDiastolic": ("8462-4", "Diastolic blood pressure", "mmHg"),
    "HKQuantityTypeIdentifierBodyMass": ("29463-7", "Body weight", "kg"),
    "HKQuantityTypeIdentifierHeight": ("8302-2", "Body height", "cm"),
    "HKQuantityTypeIdentifierOxygenSaturation": ("59408-5", "Oxygen saturation", "%"),
    "HKQuantityTypeIdentifierBloodGlucose": ("2339-0", "Blood glucose", "mg/dL"),
}


def _parse_apple_timestamp(raw_ts: Optional[str]) -> Tuple[str, str]:
    """Converts Apple Health timestamp ('2026-03-15 08:30:00 -0500' or ISO) to (iso_str, YYYY-MM-DD)."""
    if not raw_ts or not str(raw_ts).strip():
        now = datetime.now(timezone.utc)
        return now.isoformat(), now.strftime("%Y-%m-%d")

    clean = str(raw_ts).strip()
    date_part = clean[:10] if len(clean) >= 10 else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(clean, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat(), dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    if "T" in clean:
        return clean, date_part
    return f"{date_part}T00:00:00+00:00", date_part


def _strip_benign_apple_doctype(raw_bytes: bytes) -> bytes:
    """Linear O(N) stripper for Apple Health's standard <!DOCTYPE HealthData [...]> prolog.

    Rejects any <!ENTITY declarations or non-HealthData DOCTYPE blocks without regular expressions.
    """
    head_len = min(len(raw_bytes), 32768)
    head_upper = raw_bytes[:head_len].upper()

    if b"<!ENTITY" in head_upper or b"<! ENTITY" in head_upper:
        raise ValueError("Security violation: XML ENTITY declarations are forbidden (XXE protection).")

    doctype_idx = head_upper.find(b"<!DOCTYPE")
    if doctype_idx == -1:
        return raw_bytes

    after_doctype = head_upper[doctype_idx + 9 :].lstrip()
    if not after_doctype.startswith(b"HEALTHDATA"):
        raise ValueError("Security violation: Unexpected XML DOCTYPE declaration rejected.")

    # Locate closing '>' of <!DOCTYPE HealthData [ ... ]> or <!DOCTYPE HealthData>
    bracket_open = head_upper.find(b"[", doctype_idx)
    gt_pos = head_upper.find(b">", doctype_idx)
    if gt_pos == -1:
        raise ValueError("Security violation: Unterminated XML DOCTYPE declaration rejected.")

    if bracket_open != -1 and bracket_open < gt_pos:
        bracket_close = head_upper.find(b"]>", bracket_open)
        if bracket_close == -1:
            raise ValueError("Security violation: Unterminated XML DOCTYPE internal subset rejected.")
        end_idx = bracket_close + 2
    else:
        end_idx = gt_pos + 1

    cleaned = raw_bytes[:doctype_idx] + raw_bytes[end_idx:]
    if b"<!DOCTYPE" in cleaned[:4096].upper():
        raise ValueError("Security violation: Multiple XML DOCTYPE declarations rejected.")
    return cleaned


def _open_apple_xml_stream(file_or_bytes: Any) -> BinaryIO:
    """Normalizes in-memory input (bytes, XML str, zipfile, or stream) into a sanitized UTF-8 BytesIO stream."""
    raw_bytes: bytes
    if isinstance(file_or_bytes, str):
        raw_bytes = file_or_bytes.encode("utf-8")
    elif isinstance(file_or_bytes, bytes):
        raw_bytes = file_or_bytes
    elif hasattr(file_or_bytes, "read"):
        content = file_or_bytes.read()
        raw_bytes = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    else:
        raise ValueError("Unsupported input type for Apple Health export.")

    # Handle .zip archive containing export.xml
    if raw_bytes[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            xml_names = [n for n in zf.namelist() if n.endswith("export.xml") or n.endswith(".xml")]
            if not xml_names:
                raise ValueError("Apple Health zip archive does not contain export.xml.")
            raw_bytes = zf.read(xml_names[0])

    cleaned_bytes = _strip_benign_apple_doctype(raw_bytes)
    return io.BytesIO(cleaned_bytes)


def parse_apple_health_export(
    file_or_bytes: Any,
    source_name: str = "Apple Health Export",
) -> Dict[str, Any]:
    """Streams an Apple Health export and aggregates high-frequency metrics per calendar day.

    Args:
        file_or_bytes: XML string, UTF-8 bytes, ZIP bytes, or binary file-like object.
        source_name: Human-readable origin label for provenance display.

    Returns:
        Dictionary containing `format`, `source_name`, `records`, `provenance`, and `summary`.
    """
    stream = _open_apple_xml_stream(file_or_bytes)
    clean_source = (source_name or "Apple Health Export").strip()

    # Daily aggregation buckets keyed by YYYY-MM-DD
    steps_by_day: Dict[str, Dict[str, float]] = {}
    hr_by_day: Dict[str, Dict[str, float]] = {}
    energy_by_day: Dict[str, Dict[str, float]] = {}
    sleep_by_day: Dict[str, Dict[str, float]] = {}

    # Low-frequency clinical records & BP pairing
    bp_by_timestamp: Dict[str, Dict[str, Any]] = {}
    clinical_records: List[Dict[str, Any]] = []
    dates: List[str] = []
    raw_sample_count = 0
    aggregated_raw_sample_count = 0

    try:
        context = DET.iterparse(
            stream,
            events=("end",),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
        for _event, elem in context:
            tag = elem.tag.split("}", 1)[-1] if "}" in elem.tag else elem.tag
            if tag != "Record":
                continue

            raw_sample_count += 1
            rec_type = (elem.attrib.get("type") or "").strip()
            raw_val = elem.attrib.get("value")
            unit = (elem.attrib.get("unit") or "").strip()
            start_raw = elem.attrib.get("startDate") or elem.attrib.get("creationDate")
            end_raw = elem.attrib.get("endDate")
            iso_ts, day_str = _parse_apple_timestamp(start_raw)
            dates.append(day_str)

            if rec_type in HIGH_FREQUENCY_HK_TYPES:
                aggregated_raw_sample_count += 1
                if rec_type == "HKQuantityTypeIdentifierStepCount":
                    try:
                        val = float(raw_val or 0.0)
                    except ValueError:
                        val = 0.0
                    bucket = steps_by_day.setdefault(day_str, {"sum": 0.0, "count": 0.0})
                    bucket["sum"] += val
                    bucket["count"] += 1.0

                elif rec_type == "HKQuantityTypeIdentifierHeartRate":
                    try:
                        val = float(raw_val or 0.0)
                    except ValueError:
                        elem.clear()
                        continue
                    bucket = hr_by_day.setdefault(
                        day_str,
                        {"min": val, "max": val, "sum": 0.0, "count": 0.0},
                    )
                    bucket["min"] = min(bucket["min"], val)
                    bucket["max"] = max(bucket["max"], val)
                    bucket["sum"] += val
                    bucket["count"] += 1.0

                elif rec_type == "HKQuantityTypeIdentifierActiveEnergyBurned":
                    try:
                        val = float(raw_val or 0.0)
                    except ValueError:
                        val = 0.0
                    bucket = energy_by_day.setdefault(day_str, {"sum": 0.0, "count": 0.0})
                    bucket["sum"] += val
                    bucket["count"] += 1.0

                elif rec_type == "HKCategoryTypeIdentifierSleepAnalysis":
                    dur_hours = 0.0
                    if start_raw and end_raw:
                        s_iso, _ = _parse_apple_timestamp(start_raw)
                        e_iso, _ = _parse_apple_timestamp(end_raw)
                        try:
                            s_dt = datetime.fromisoformat(s_iso)
                            e_dt = datetime.fromisoformat(e_iso)
                            dur_hours = max(0.0, (e_dt - s_dt).total_seconds() / 3600.0)
                        except ValueError:
                            dur_hours = 0.0
                    bucket = sleep_by_day.setdefault(day_str, {"sum": 0.0, "count": 0.0})
                    bucket["sum"] += dur_hours
                    bucket["count"] += 1.0

            elif rec_type in LOW_FREQUENCY_CLINICAL_HK_TYPES:
                try:
                    num_val = float(raw_val) if raw_val is not None else None
                except ValueError:
                    num_val = None

                if num_val is not None:
                    if rec_type == "HKQuantityTypeIdentifierBloodPressureSystolic":
                        bp = bp_by_timestamp.setdefault(
                            iso_ts,
                            {"date": day_str, "unit": unit or "mmHg"},
                        )
                        bp["systolic"] = num_val
                    elif rec_type == "HKQuantityTypeIdentifierBloodPressureDiastolic":
                        bp = bp_by_timestamp.setdefault(
                            iso_ts,
                            {"date": day_str, "unit": unit or "mmHg"},
                        )
                        bp["diastolic"] = num_val
                    else:
                        loinc_code, display_name, default_unit = _CLINICAL_LOINC_MAP[rec_type]
                        eff_unit = unit or default_unit
                        # Convert fractional SpO2 (0.98 -> 98.0%) if <= 1.0
                        if rec_type == "HKQuantityTypeIdentifierOxygenSaturation" and 0 < num_val <= 1.0:
                            num_val = round(num_val * 100.0, 1)
                        source_display = f"From {clean_source}, {day_str}"
                        fhir_obs: Dict[str, Any] = {
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
                                "text": display_name,
                            },
                            "effectiveDateTime": iso_ts,
                            "valueQuantity": {
                                "value": num_val,
                                "unit": eff_unit,
                            },
                            "meta": {"source": clean_source, "trust": "untrusted"},
                            "_carefold_provenance": {
                                "source_name": clean_source,
                                "source_display": source_display,
                                "trust": "untrusted",
                            },
                        }
                        clinical_records.append({
                            "resource_type": "Observation",
                            "source_id": f"apple_health:{loinc_code}:{iso_ts}",
                            "effective_at": iso_ts,
                            "display": f"{display_name}: {num_val} {eff_unit}",
                            "code": loinc_code,
                            "data": fhir_obs,
                            "source_display": source_display,
                            "trust": "untrusted",
                        })

            # Always clear element to keep memory O(1)
            elem.clear()
    except DefusedXmlException as exc:
        raise ValueError(f"Security violation: XML ENTITY/DTD declarations are forbidden (XXE protection): {exc}") from exc
    except DET.ParseError as exc:
        raise ValueError(f"Invalid Apple Health XML: {exc}") from exc

    staged_records: List[Dict[str, Any]] = []

    # 1. Emit daily aggregated Step Count Observations (LOINC 41950-7)
    for day_str in sorted(steps_by_day.keys()):
        b = steps_by_day[day_str]
        total_steps = int(round(b["sum"]))
        sample_count = int(b["count"])
        eff_iso = f"{day_str}T00:00:00+00:00"
        source_display = f"From {clean_source}, {day_str}"
        agg_meta = {
            "period": "daily",
            "date": day_str,
            "sum": total_steps,
            "sample_count": sample_count,
        }
        fhir_obs = {
            "resourceType": "Observation",
            "status": "final",
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "41950-7",
                        "display": "Number of steps in 24 hour Measured",
                    }
                ],
                "text": "Daily step count",
            },
            "effectiveDateTime": eff_iso,
            "valueQuantity": {"value": total_steps, "unit": "steps"},
            "aggregation": agg_meta,
            "meta": {"source": clean_source, "trust": "untrusted"},
            "_carefold_provenance": {
                "source_name": clean_source,
                "source_display": source_display,
                "trust": "untrusted",
            },
        }
        staged_records.append({
            "resource_type": "Observation",
            "source_id": f"apple_health:steps:{day_str}",
            "effective_at": eff_iso,
            "display": f"Daily step count: {total_steps} steps ({sample_count} samples)",
            "code": "41950-7",
            "aggregation": agg_meta,
            "data": fhir_obs,
            "source_display": source_display,
            "trust": "untrusted",
        })

    # 2. Emit daily aggregated Heart Rate Observations (LOINC 8867-4)
    for day_str in sorted(hr_by_day.keys()):
        b = hr_by_day[day_str]
        sample_count = int(b["count"])
        avg_hr = round(b["sum"] / max(1.0, b["count"]), 1)
        min_hr = round(b["min"], 1)
        max_hr = round(b["max"], 1)
        eff_iso = f"{day_str}T00:00:00+00:00"
        source_display = f"From {clean_source}, {day_str}"
        agg_meta = {
            "period": "daily",
            "date": day_str,
            "min": min_hr,
            "max": max_hr,
            "avg": avg_hr,
            "sample_count": sample_count,
        }
        fhir_obs = {
            "resourceType": "Observation",
            "status": "final",
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "8867-4",
                        "display": "Heart rate",
                    }
                ],
                "text": "Daily heart rate summary",
            },
            "effectiveDateTime": eff_iso,
            "valueQuantity": {"value": avg_hr, "unit": "bpm"},
            "component": [
                {
                    "code": {"text": "Minimum heart rate"},
                    "valueQuantity": {"value": min_hr, "unit": "bpm"},
                },
                {
                    "code": {"text": "Maximum heart rate"},
                    "valueQuantity": {"value": max_hr, "unit": "bpm"},
                },
            ],
            "aggregation": agg_meta,
            "meta": {"source": clean_source, "trust": "untrusted"},
            "_carefold_provenance": {
                "source_name": clean_source,
                "source_display": source_display,
                "trust": "untrusted",
            },
        }
        staged_records.append({
            "resource_type": "Observation",
            "source_id": f"apple_health:heart_rate:{day_str}",
            "effective_at": eff_iso,
            "display": (
                f"Daily heart rate: avg {avg_hr} bpm (min {min_hr}, max {max_hr}, "
                f"{sample_count} samples)"
            ),
            "code": "8867-4",
            "aggregation": agg_meta,
            "data": fhir_obs,
            "source_display": source_display,
            "trust": "untrusted",
        })

    # 3. Emit daily aggregated Active Energy Burned Observations (LOINC 41979-6)
    for day_str in sorted(energy_by_day.keys()):
        b = energy_by_day[day_str]
        total_kcal = round(b["sum"], 1)
        sample_count = int(b["count"])
        eff_iso = f"{day_str}T00:00:00+00:00"
        source_display = f"From {clean_source}, {day_str}"
        agg_meta = {
            "period": "daily",
            "date": day_str,
            "sum": total_kcal,
            "sample_count": sample_count,
        }
        fhir_obs = {
            "resourceType": "Observation",
            "status": "final",
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "41979-6",
                        "display": "Calories burned in 24 hour Calculated",
                    }
                ],
                "text": "Daily active energy burned",
            },
            "effectiveDateTime": eff_iso,
            "valueQuantity": {"value": total_kcal, "unit": "kcal"},
            "aggregation": agg_meta,
            "meta": {"source": clean_source, "trust": "untrusted"},
            "_carefold_provenance": {
                "source_name": clean_source,
                "source_display": source_display,
                "trust": "untrusted",
            },
        }
        staged_records.append({
            "resource_type": "Observation",
            "source_id": f"apple_health:active_energy:{day_str}",
            "effective_at": eff_iso,
            "display": f"Daily active energy: {total_kcal} kcal ({sample_count} samples)",
            "code": "41979-6",
            "aggregation": agg_meta,
            "data": fhir_obs,
            "source_display": source_display,
            "trust": "untrusted",
        })

    # 4. Emit daily aggregated Sleep Analysis Observations (LOINC 93832-4)
    for day_str in sorted(sleep_by_day.keys()):
        b = sleep_by_day[day_str]
        total_hours = round(b["sum"], 2)
        sample_count = int(b["count"])
        eff_iso = f"{day_str}T00:00:00+00:00"
        source_display = f"From {clean_source}, {day_str}"
        agg_meta = {
            "period": "daily",
            "date": day_str,
            "sum": total_hours,
            "sample_count": sample_count,
        }
        fhir_obs = {
            "resourceType": "Observation",
            "status": "final",
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "93832-4",
                        "display": "Sleep duration",
                    }
                ],
                "text": "Daily sleep duration",
            },
            "effectiveDateTime": eff_iso,
            "valueQuantity": {"value": total_hours, "unit": "h"},
            "aggregation": agg_meta,
            "meta": {"source": clean_source, "trust": "untrusted"},
            "_carefold_provenance": {
                "source_name": clean_source,
                "source_display": source_display,
                "trust": "untrusted",
            },
        }
        staged_records.append({
            "resource_type": "Observation",
            "source_id": f"apple_health:sleep:{day_str}",
            "effective_at": eff_iso,
            "display": f"Daily sleep duration: {total_hours} h ({sample_count} samples)",
            "code": "93832-4",
            "aggregation": agg_meta,
            "data": fhir_obs,
            "source_display": source_display,
            "trust": "untrusted",
        })

    # 5. Emit paired or single Blood Pressure clinical Observations
    for iso_ts in sorted(bp_by_timestamp.keys()):
        bp = bp_by_timestamp[iso_ts]
        day_str = bp["date"]
        unit = bp["unit"]
        sys_val = bp.get("systolic")
        dia_val = bp.get("diastolic")
        source_display = f"From {clean_source}, {day_str}"

        if sys_val is not None and dia_val is not None:
            fhir_bp = {
                "resourceType": "Observation",
                "status": "final",
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "85354-9",
                            "display": "Blood pressure panel with all children optional",
                        }
                    ],
                    "text": "Blood pressure panel",
                },
                "effectiveDateTime": iso_ts,
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
                        "valueQuantity": {"value": sys_val, "unit": unit},
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
                        "valueQuantity": {"value": dia_val, "unit": unit},
                    },
                ],
                "meta": {"source": clean_source, "trust": "untrusted"},
                "_carefold_provenance": {
                    "source_name": clean_source,
                    "source_display": source_display,
                    "trust": "untrusted",
                },
            }
            staged_records.append({
                "resource_type": "Observation",
                "source_id": f"apple_health:bp:{iso_ts}",
                "effective_at": iso_ts,
                "display": f"Blood pressure: {int(sys_val)}/{int(dia_val)} {unit}",
                "code": "85354-9",
                "data": fhir_bp,
                "source_display": source_display,
                "trust": "untrusted",
            })
        else:
            val = sys_val if sys_val is not None else dia_val
            loinc = "8480-6" if sys_val is not None else "8462-4"
            label = "Systolic blood pressure" if sys_val is not None else "Diastolic blood pressure"
            fhir_single = {
                "resourceType": "Observation",
                "status": "final",
                "code": {
                    "coding": [{"system": "http://loinc.org", "code": loinc, "display": label}],
                    "text": label,
                },
                "effectiveDateTime": iso_ts,
                "valueQuantity": {"value": val, "unit": unit},
                "meta": {"source": clean_source, "trust": "untrusted"},
                "_carefold_provenance": {
                    "source_name": clean_source,
                    "source_display": source_display,
                    "trust": "untrusted",
                },
            }
            staged_records.append({
                "resource_type": "Observation",
                "source_id": f"apple_health:{loinc}:{iso_ts}",
                "effective_at": iso_ts,
                "display": f"{label}: {val} {unit}",
                "code": loinc,
                "data": fhir_single,
                "source_display": source_display,
                "trust": "untrusted",
            })

    # 6. Append remaining low-frequency clinical Observations
    staged_records.extend(clinical_records)

    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sorted_dates = sorted(d for d in dates if d)
    date_range = {
        "min": sorted_dates[0] if sorted_dates else now_date,
        "max": sorted_dates[-1] if sorted_dates else now_date,
    }

    counts_by_type = {"Observation": len(staged_records)} if staged_records else {}

    provenance_record: Dict[str, Any] = {
        "resource_type": "Provenance",
        "resourceType": "Provenance",
        "source_id": f"Provenance:apple_health:{date_range['max']}",
        "effective_at": f"{date_range['max']}T00:00:00+00:00",
        "display": f"Provenance: From {clean_source}, {date_range['max']}",
        "code": "PROVENANCE",
        "data": {
            "resourceType": "Provenance",
            "recorded": datetime.now(timezone.utc).isoformat(),
            "agent": [{"who": {"display": clean_source}}],
            "text": {
                "status": "generated",
                "div": f"From {clean_source}, {date_range['max']}",
            },
        },
        "source_display": f"From {clean_source}, {date_range['max']}",
        "trust": "untrusted",
    }

    return {
        "format": "apple_health",
        "source_name": clean_source,
        "records": staged_records,
        "provenance": provenance_record,
        "summary": {
            "total_records": len(staged_records),
            "raw_sample_count": raw_sample_count,
            "aggregated_raw_sample_count": aggregated_raw_sample_count,
            "counts_by_type": counts_by_type,
            "date_range": date_range,
            "source_name": clean_source,
        },
    }


__all__ = [
    "HIGH_FREQUENCY_HK_TYPES",
    "LOW_FREQUENCY_CLINICAL_HK_TYPES",
    "parse_apple_health_export",
]
