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

"""FHIR-Converter Sidecar Adapter & Deterministic HL7v2 / C-CDA Fallback Parser (AU-77 / E10.1).

Implements:
- `convert_clinical_payload_to_fhir`:
  - Calls an optional local FHIR-Converter sidecar (`POST {sidecar_url}/api/convert`) over `httpx.AsyncClient`
    after enforcing a strict loopback/allowlisted host check (SSRF defense).
  - Provides a deterministic local HL7v2 (`MSH`, `PID`, `OBX`, `RXA`) and C-CDA fallback parser when no
    external sidecar is configured, validating all emitted `Observation` and `Immunization` resources via
    `fhir.resources.R4B`.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional, Tuple
from urllib.parse import urlparse

from fhir.resources.R4B.bundle import Bundle as FhirBundle
from fhir.resources.R4B.immunization import Immunization as FhirImmunization
from fhir.resources.R4B.observation import Observation as FhirObservation
from fhir.resources.R4B.patient import Patient as FhirPatient
import httpx

from carefold.importers.ccda import parse_ccda_xml
from carefold.importers.fhir_bundle import parse_fhir_bundle

ALLOWED_SIDECAR_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "fhir-converter"})

_HL7_CODE_SYSTEM_MAP: Dict[str, str] = {
    "LN": "http://loinc.org",
    "LOINC": "http://loinc.org",
    "CVX": "http://hl7.org/fhir/sid/cvx",
    "SCT": "http://snomed.info/sct",
    "SNOMED": "http://snomed.info/sct",
    "ICD10": "http://hl7.org/fhir/sid/icd-10-cm",
    "I10": "http://hl7.org/fhir/sid/icd-10-cm",
    "RXNORM": "http://www.nlm.nih.gov/research/umls/rxnorm",
    "UCUM": "http://unitsofmeasure.org",
}

_OBX_STATUS_MAP: Dict[str, str] = {
    "F": "final",
    "P": "preliminary",
    "C": "corrected",
    "A": "amended",
    "R": "registered",
    "W": "entered-in-error",
}


class _AwaitableFhirConversionResult(dict):  # type: ignore[type-arg]
    """Dictionary result that can be used directly or awaited in async workflows."""

    def __init__(
        self,
        initial_data: Optional[Dict[str, Any]] = None,
        async_loader: Optional[Callable[[], Coroutine[Any, Any, Dict[str, Any]]]] = None,
    ) -> None:
        super().__init__(initial_data or {})
        self._async_loader = async_loader

    def __await__(self):  # type: ignore[no-untyped-def]
        async def _resolve() -> Dict[str, Any]:
            if self._async_loader is not None:
                loaded = await self._async_loader()
                self.clear()
                self.update(loaded)
            return dict(self)

        return _resolve().__await__()


def _validate_sidecar_url(sidecar_url: str) -> str:
    """Validates that `sidecar_url` targets an allowlisted loopback/sidecar host over HTTP(S)."""
    clean = (sidecar_url or "").strip()
    parsed = urlparse(clean)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid FHIR-Converter sidecar URL scheme '{parsed.scheme}'; expected http or https.")
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname or hostname not in ALLOWED_SIDECAR_HOSTS:
        raise ValueError(
            f"Security violation: FHIR-Converter sidecar host '{hostname}' is not in the loopback allowlist "
            f"({sorted(ALLOWED_SIDECAR_HOSTS)})."
        )
    return clean.rstrip("/")


def _parse_hl7_dtm(raw_dtm: Optional[str], fallback_date: str) -> Tuple[str, str]:
    """Converts an HL7v2 DTM string (`YYYYMMDD[HHMM[SS]]`) into `(iso_datetime, YYYY-MM-DD)`."""
    clean = (raw_dtm or "").strip()
    if not clean:
        return f"{fallback_date}T00:00:00+00:00", fallback_date

    # Extract leading digits up to 14 characters
    digits_only = "".join(ch for ch in clean[:14] if ch.isdigit())
    if len(digits_only) >= 8:
        yyyy = digits_only[0:4]
        mm = digits_only[4:6]
        dd = digits_only[6:8]
        hh = digits_only[8:10] if len(digits_only) >= 10 else "00"
        mi = digits_only[10:12] if len(digits_only) >= 12 else "00"
        ss = digits_only[12:14] if len(digits_only) >= 14 else "00"
        date_str = f"{yyyy}-{mm}-{dd}"
        return f"{date_str}T{hh}:{mi}:{ss}+00:00", date_str

    if len(clean) >= 10 and clean[4] == "-" and clean[7] == "-":
        date_str = clean[:10]
        iso_str = clean if "T" in clean else f"{date_str}T00:00:00+00:00"
        return iso_str, date_str

    return f"{fallback_date}T00:00:00+00:00", fallback_date


def _get_field(fields: List[str], index: int) -> str:
    """Safely retrieves an HL7 pipe-delimited field by 1-based index (for non-MSH segments)."""
    if 0 <= index < len(fields):
        return fields[index].strip()
    return ""


def _parse_ce_field(raw_ce: str, default_system: str) -> Tuple[str, str, str]:
    """Parses an HL7 CE/CWE component (`code^display^system`) into `(code, display, system_uri)`."""
    parts = (raw_ce or "").split("^")
    code = parts[0].strip() if len(parts) > 0 else ""
    display = parts[1].strip() if len(parts) > 1 and parts[1].strip() else code
    raw_sys = parts[2].strip().upper() if len(parts) > 2 and parts[2].strip() else ""
    system_uri = _HL7_CODE_SYSTEM_MAP.get(raw_sys, default_system)
    return code, display, system_uri


def parse_hl7v2_to_fhir(
    raw_content: str,
    source_name: str = "HL7v2 Clinical Message",
) -> Dict[str, Any]:
    """Deterministically parses HL7v2 (`MSH`, `PID`, `OBX`, `RXA`) into validated FHIR R4 resources."""
    if not isinstance(raw_content, str) or not raw_content.strip():
        raise ValueError("HL7v2 message content cannot be empty.")

    lines = [
        line.strip()
        for line in raw_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if line.strip()
    ]
    if not lines:
        raise ValueError("HL7v2 message contains no segments.")

    has_hl7_segment = any(
        line.startswith(("MSH|", "PID|", "OBR|", "OBX|", "RXA|")) for line in lines
    )
    if not has_hl7_segment:
        raise ValueError("Invalid HL7v2 payload: no recognized MSH/PID/OBX/RXA segments found.")

    clean_source = (source_name or "HL7v2 Clinical Message").strip()
    fallback_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    msg_date = fallback_date

    patient_resource: Optional[Dict[str, Any]] = None
    patient_ref_display = "Patient"
    patient_id = "pat-hl7-1"

    staged_records: List[Dict[str, Any]] = []
    bundle_entries: List[Dict[str, Any]] = []
    counts_by_type: Dict[str, int] = {}
    dates: List[str] = []

    for idx, line in enumerate(lines):
        fields = line.split("|")
        seg_name = fields[0].strip().upper()

        if seg_name == "MSH":
            # In MSH, fields[6] is MSH-7 (Date/Time of Message)
            msh_dtm = _get_field(fields, 6)
            if msh_dtm:
                _, msg_date = _parse_hl7_dtm(msh_dtm, fallback_date)

        elif seg_name == "PID":
            raw_pid_id = _get_field(fields, 3).split("^")[0].strip() or "pat-hl7-1"
            patient_id = f"pat-{raw_pid_id}"
            raw_name = _get_field(fields, 5)
            name_parts = raw_name.split("^")
            family = name_parts[0].strip() if len(name_parts) > 0 else ""
            given = name_parts[1].strip() if len(name_parts) > 1 else ""
            raw_dob = _get_field(fields, 7)
            raw_sex = _get_field(fields, 8).upper()
            gender_map = {"M": "male", "F": "female", "O": "other", "U": "unknown"}

            pat_candidate: Dict[str, Any] = {
                "resourceType": "Patient",
                "id": patient_id,
            }
            if family or given:
                name_entry: Dict[str, Any] = {}
                if family:
                    name_entry["family"] = family
                if given:
                    name_entry["given"] = [given]
                pat_candidate["name"] = [name_entry]
                patient_ref_display = f"{given} {family}".strip()
            if raw_dob and len(raw_dob) >= 8 and raw_dob[:8].isdigit():
                pat_candidate["birthDate"] = f"{raw_dob[0:4]}-{raw_dob[4:6]}-{raw_dob[6:8]}"
            if raw_sex in gender_map:
                pat_candidate["gender"] = gender_map[raw_sex]

            validated_pat = FhirPatient.model_validate(pat_candidate)
            patient_resource = validated_pat.model_dump(mode="json", exclude_none=True)
            bundle_entries.append({"resource": patient_resource})

        elif seg_name == "OBX":
            set_id = _get_field(fields, 1) or str(idx)
            val_type = _get_field(fields, 2).upper() or "ST"
            obs_id_field = _get_field(fields, 3)
            obs_val_raw = _get_field(fields, 5)
            units_field = _get_field(fields, 6)
            status_code = _get_field(fields, 11).upper() or "F"
            obs_dtm_raw = _get_field(fields, 14)

            code_val, display_val, system_uri = _parse_ce_field(obs_id_field, "http://loinc.org")
            unit_code, unit_display, _ = _parse_ce_field(units_field, "http://unitsofmeasure.org")
            effective_iso, date_str = _parse_hl7_dtm(obs_dtm_raw, msg_date)
            dates.append(date_str)
            fhir_status = _OBX_STATUS_MAP.get(status_code, "final")

            obs_candidate: Dict[str, Any] = {
                "resourceType": "Observation",
                "id": f"obx-{set_id}-{code_val or idx}",
                "status": fhir_status,
                "code": {
                    "coding": [
                        {
                            "system": system_uri,
                            "code": code_val or "unknown",
                            "display": display_val or "Observation",
                        }
                    ],
                    "text": display_val or code_val or "Observation",
                },
                "subject": {"reference": f"Patient/{patient_id}", "display": patient_ref_display},
                "effectiveDateTime": effective_iso,
            }

            summary_display = display_val or code_val or "Observation"
            if val_type in ("NM", "SN") or (obs_val_raw and _is_float(obs_val_raw)):
                clean_num_str = obs_val_raw.lstrip("<>=").strip()
                if _is_float(clean_num_str):
                    num_val = float(clean_num_str)
                    vq: Dict[str, Any] = {"value": num_val}
                    if unit_display or unit_code:
                        vq["unit"] = unit_display or unit_code
                        vq["system"] = "http://unitsofmeasure.org"
                        vq["code"] = unit_code or unit_display
                    obs_candidate["valueQuantity"] = vq
                    summary_display = f"{summary_display}: {num_val} {unit_display or unit_code}".strip()
                else:
                    obs_candidate["valueString"] = obs_val_raw
            elif val_type in ("CE", "CWE") and "^" in obs_val_raw:
                v_code, v_disp, v_sys = _parse_ce_field(obs_val_raw, "http://snomed.info/sct")
                obs_candidate["valueCodeableConcept"] = {
                    "coding": [{"system": v_sys, "code": v_code, "display": v_disp}],
                    "text": v_disp,
                }
                summary_display = f"{summary_display}: {v_disp}".strip()
            elif obs_val_raw:
                obs_candidate["valueString"] = obs_val_raw
                summary_display = f"{summary_display}: {obs_val_raw}".strip()

            validated_obs = FhirObservation.model_validate(obs_candidate)
            obs_clean = validated_obs.model_dump(mode="json", exclude_none=True)
            bundle_entries.append({"resource": obs_clean})

            obs_fhir = dict(obs_clean)
            source_display = f"From {clean_source}, {date_str}"
            obs_fhir["_carefold_provenance"] = {
                "source_name": clean_source,
                "source_display": source_display,
                "trust": "untrusted",
            }
            staged_records.append({
                "resource_type": "Observation",
                "source_id": f"Observation:{obs_fhir['id']}",
                "effective_at": effective_iso,
                "display": summary_display,
                "code": code_val or None,
                "data": obs_fhir,
                "source_display": source_display,
                "trust": "untrusted",
            })
            counts_by_type["Observation"] = counts_by_type.get("Observation", 0) + 1

        elif seg_name == "RXA":
            sub_id = _get_field(fields, 1) or str(idx)
            rxa_dtm_raw = _get_field(fields, 3) or _get_field(fields, 4)
            rxa_code_field = _get_field(fields, 5)
            lot_number = _get_field(fields, 15)
            rxa_status_raw = _get_field(fields, 20).upper()

            cvx_code, vax_display, vax_system = _parse_ce_field(
                rxa_code_field, "http://hl7.org/fhir/sid/cvx"
            )
            effective_iso, date_str = _parse_hl7_dtm(rxa_dtm_raw, msg_date)
            dates.append(date_str)
            imm_status = "not-done" if rxa_status_raw in ("RE", "NA") else "completed"

            imm_candidate: Dict[str, Any] = {
                "resourceType": "Immunization",
                "id": f"rxa-{sub_id}-{cvx_code or idx}",
                "status": imm_status,
                "vaccineCode": {
                    "coding": [
                        {
                            "system": vax_system,
                            "code": cvx_code or "unknown",
                            "display": vax_display or "Immunization",
                        }
                    ],
                    "text": vax_display or cvx_code or "Immunization",
                },
                "patient": {"reference": f"Patient/{patient_id}", "display": patient_ref_display},
                "occurrenceDateTime": date_str,
            }
            if lot_number:
                imm_candidate["lotNumber"] = lot_number

            validated_imm = FhirImmunization.model_validate(imm_candidate)
            imm_clean = validated_imm.model_dump(mode="json", exclude_none=True)
            bundle_entries.append({"resource": imm_clean})

            imm_fhir = dict(imm_clean)
            source_display = f"From {clean_source}, {date_str}"
            imm_fhir["_carefold_provenance"] = {
                "source_name": clean_source,
                "source_display": source_display,
                "trust": "untrusted",
            }
            staged_records.append({
                "resource_type": "Immunization",
                "source_id": f"Immunization:{imm_fhir['id']}",
                "effective_at": effective_iso,
                "display": f"{vax_display or 'Immunization'} (CVX {cvx_code}) — {date_str}"
                if cvx_code
                else f"{vax_display or 'Immunization'} — {date_str}",
                "code": cvx_code or None,
                "data": imm_fhir,
                "source_display": source_display,
                "trust": "untrusted",
            })
            counts_by_type["Immunization"] = counts_by_type.get("Immunization", 0) + 1

    bundle_id = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()[:12]
    validated_bundle = FhirBundle.model_validate({
        "resourceType": "Bundle",
        "id": f"hl7v2-bundle-{bundle_id}",
        "type": "collection",
        "entry": bundle_entries,
    })
    bundle_dict = validated_bundle.model_dump(mode="json", exclude_none=True)

    sorted_dates = sorted(d for d in dates if d)
    return {
        "format": "hl7v2",
        "input_type": "hl7v2",
        "converter_mode": "local_fallback",
        "source_name": clean_source,
        "patient": patient_resource,
        "bundle": bundle_dict,
        "records": staged_records,
        "summary": {
            "total_records": len(staged_records),
            "counts_by_type": counts_by_type,
            "date_range": {
                "min": sorted_dates[0] if sorted_dates else msg_date,
                "max": sorted_dates[-1] if sorted_dates else msg_date,
            },
        },
    }


def _is_float(val: str) -> bool:
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False


def _convert_locally(
    raw_content: str,
    input_type: Literal["hl7v2", "ccda"],
) -> Dict[str, Any]:
    """Executes deterministic local HL7v2 or C-CDA conversion to FHIR R4 resources."""
    clean_type = (input_type or "hl7v2").strip().lower()
    if clean_type == "hl7v2":
        return parse_hl7v2_to_fhir(raw_content)
    if clean_type == "ccda":
        ccda_parsed = parse_ccda_xml(raw_content, source_name="C-CDA Sidecar Converter")
        clinical_records = [
            r for r in ccda_parsed.get("records", []) if r.get("resource_type") != "Provenance"
        ]
        entries = [{"resource": r["data"]} for r in clinical_records if isinstance(r.get("data"), dict)]
        return {
            "format": "ccda",
            "input_type": "ccda",
            "converter_mode": "local_fallback",
            "source_name": ccda_parsed.get("source_name", "C-CDA Sidecar Converter"),
            "bundle": {
                "resourceType": "Bundle",
                "type": "collection",
                "entry": entries,
            },
            "records": clinical_records,
            "summary": ccda_parsed.get("summary", {}),
        }
    raise ValueError(f"Unsupported input_type '{input_type}'. Expected 'hl7v2' or 'ccda'.")


async def _convert_via_sidecar(
    raw_content: str,
    input_type: Literal["hl7v2", "ccda"],
    validated_base_url: str,
    transport: Optional[Any] = None,
) -> Dict[str, Any]:
    """Calls an external FHIR-Converter sidecar (`POST {sidecar_url}/api/convert`) and validates output."""
    endpoint = f"{validated_base_url}/api/convert"
    root_template = "ADT_A01" if input_type == "hl7v2" else "CCD"
    request_payload = {
        "input_data": raw_content,
        "input_type": input_type,
        "root_template": root_template,
    }
    async with httpx.AsyncClient(transport=transport, timeout=15.0) as client:
        response = await client.post(endpoint, json=request_payload)
        response.raise_for_status()
        body = response.json()

    fhir_bundle = body.get("fhirResource") if isinstance(body, dict) and "fhirResource" in body else body
    if not isinstance(fhir_bundle, dict) or fhir_bundle.get("resourceType") != "Bundle":
        raise ValueError("FHIR-Converter sidecar did not return a valid FHIR R4 Bundle.")

    parsed = parse_fhir_bundle(json.dumps(fhir_bundle), source_name=f"FHIR-Converter ({input_type.upper()})")
    clinical_records = [
        r for r in parsed.get("records", []) if r.get("resource_type") != "Provenance"
    ]
    return {
        "format": input_type,
        "input_type": input_type,
        "converter_mode": "sidecar",
        "source_name": f"FHIR-Converter ({input_type.upper()})",
        "bundle": fhir_bundle,
        "records": clinical_records,
        "summary": parsed.get("summary", {}),
    }


def convert_clinical_payload_to_fhir(
    raw_content: str,
    input_type: Literal["hl7v2", "ccda"] = "hl7v2",
    sidecar_url: Optional[str] = None,
    transport: Optional[Any] = None,
) -> _AwaitableFhirConversionResult:
    """Converts an HL7v2 or C-CDA clinical payload into validated FHIR R4 resources.

    Supports both synchronous invocation (`res = convert_clinical_payload_to_fhir(...)`) and
    asynchronous invocation (`res = await convert_clinical_payload_to_fhir(...)`).
    When `sidecar_url` is provided, enforces the loopback/allowlisted host check and invokes
    `POST {sidecar_url}/api/convert` via `httpx.AsyncClient`.
    """
    if not isinstance(raw_content, str) or not raw_content.strip():
        raise ValueError("Clinical payload content cannot be empty.")

    clean_type = (input_type or "hl7v2").strip().lower()
    if clean_type not in ("hl7v2", "ccda"):
        raise ValueError(f"Unsupported input_type '{input_type}'. Expected 'hl7v2' or 'ccda'.")

    if sidecar_url is not None and str(sidecar_url).strip():
        validated_url = _validate_sidecar_url(sidecar_url)

        async def _loader() -> Dict[str, Any]:
            return await _convert_via_sidecar(
                raw_content=raw_content,
                input_type=clean_type,  # type: ignore[arg-type]
                validated_base_url=validated_url,
                transport=transport,
            )

        return _AwaitableFhirConversionResult(async_loader=_loader)

    local_result = _convert_locally(raw_content=raw_content, input_type=clean_type)  # type: ignore[arg-type]
    return _AwaitableFhirConversionResult(initial_data=local_result)


__all__ = [
    "ALLOWED_SIDECAR_HOSTS",
    "convert_clinical_payload_to_fhir",
    "parse_hl7v2_to_fhir",
]
