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

"""FHIR-Converter Sidecar Adapter & Production HL7v2 (`hl7apy`) / C-CDA Clinical Message Converter (AU-77 / #284).

Implements:
- `convert_clinical_payload_to_fhir`:
  - Calls an optional local FHIR-Converter sidecar (`POST {sidecar_url}/api/convert`) over `httpx.AsyncClient`
    after enforcing a strict loopback/allowlisted host check (SSRF defense).
  - Provides a production-grade local HL7v2 (`ADT^A01`, `ADT^A08`, `ORU^R01`, `VXU^V04`) parser powered by
    `hl7apy` (`hl7apy>=1.3.5`, MIT License — OSI-approved permissive license compatible with Carefold's
    PolyForm Noncommercial License 1.0.0 + Carefold Additional Terms) and C-CDA parser when no external
    sidecar is configured.
- Maps HL7v2 segments into validated FHIR R4 resources:
  - `MSH` -> `Bundle(type="collection")` metadata & message type (`ADT^A01`, `ADT^A08`, `ORU^R01`, `VXU^V04`)
  - `PID` -> `Patient` (identifiers, name, birthDate, administrative gender, telecom, address)
  - `PV1` -> `Encounter` (class `IMP`/`AMB`/`EMER`, status `finished`, period `PV1-44`/`PV1-45`, participant/location)
  - `OBR` -> `DiagnosticReport` (status, `code` from `OBR-4`, `effectiveDateTime` from `OBR-7`, `result` links to child `OBX` `Observation`s)
  - `OBX` -> `Observation` (`NM`/`SN` numeric with `valueQuantity`, `ST`/`TX`/`FT` with `valueString`, `CE`/`CWE` with `valueCodeableConcept`,
    `OBX-6` units, `OBX-7` `referenceRange`, `OBX-8` abnormal flags `H`/`L`/`HH`/`LL`/`A`/`N` -> `interpretation`, `OBX-11` status, `OBX-14` `effectiveDateTime`)
  - `RXA` -> `Immunization` (`RXA-3` `occurrenceDateTime`, `RXA-5` CVX `vaccineCode`, `RXA-6`/`RXA-7` `doseQuantity`,
    `RXA-15` `lotNumber`, `RXA-16` `expirationDate`, `RXA-20` completion status)
  - `DG1` -> `Condition` (`DG1-3` ICD-10-CM / SNOMED `code`, `DG1-5` `onsetDateTime`, `DG1-6` diagnosis type)
  - `AL1` -> `AllergyIntolerance` (`AL1-2` allergen type `DA`/`FA`/`EA`, `AL1-3` allergen `code`, `AL1-4` severity `MI`/`MO`/`SV`,
    `AL1-5` repeating reaction manifestations, `AL1-6` `recordedDate`)
- Properly unescapes HL7v2 escape sequences (`\\F\\`, `\\S\\`, `\\T\\`, `\\R\\`, `\\E\\`, `\\.br\\`, `\\X..\\`) and handles
  repeating fields (`~`), failing safely with PHI-redacted structured diagnostics on malformed inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional, Sequence, Tuple
from urllib.parse import urlparse

from fhir.resources.R4B.allergyintolerance import (
    AllergyIntolerance as FhirAllergyIntolerance,
)
from fhir.resources.R4B.bundle import Bundle as FhirBundle
from fhir.resources.R4B.condition import Condition as FhirCondition
from fhir.resources.R4B.diagnosticreport import (
    DiagnosticReport as FhirDiagnosticReport,
)
from fhir.resources.R4B.encounter import Encounter as FhirEncounter
from fhir.resources.R4B.immunization import Immunization as FhirImmunization
from fhir.resources.R4B.observation import Observation as FhirObservation
from fhir.resources.R4B.patient import Patient as FhirPatient
from hl7apy import VALIDATION_LEVEL
from hl7apy.parser import parse_message, parse_segment
import httpx

from carefold.importers.ccda import parse_ccda_xml
from carefold.importers.fhir_bundle import parse_fhir_bundle

HL7APY_LICENSE_ATTESTATION: Dict[str, str] = {
    "package": "hl7apy",
    "version_spec": ">=1.3.5",
    "license": "MIT",
    "compatibility": "Permissive OSI-approved MIT License; compatible with PolyForm Noncommercial License 1.0.0 + Carefold Additional Terms.",
}

ALLOWED_SIDECAR_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "fhir-converter"})

RECOGNIZED_HL7_SEGMENTS = frozenset({
    "MSH",
    "EVN",
    "PID",
    "PD1",
    "NK1",
    "PV1",
    "PV2",
    "ORC",
    "OBR",
    "OBX",
    "NTE",
    "RXA",
    "RXR",
    "DG1",
    "AL1",
    "PR1",
    "IN1",
})

_HL7_CODE_SYSTEM_MAP: Dict[str, str] = {
    "LN": "http://loinc.org",
    "LOINC": "http://loinc.org",
    "CVX": "http://hl7.org/fhir/sid/cvx",
    "SCT": "http://snomed.info/sct",
    "SNOMED": "http://snomed.info/sct",
    "SNM": "http://snomed.info/sct",
    "ICD10": "http://hl7.org/fhir/sid/icd-10-cm",
    "ICD-10": "http://hl7.org/fhir/sid/icd-10-cm",
    "ICD-10-CM": "http://hl7.org/fhir/sid/icd-10-cm",
    "I10": "http://hl7.org/fhir/sid/icd-10-cm",
    "I10C": "http://hl7.org/fhir/sid/icd-10-cm",
    "RXNORM": "http://www.nlm.nih.gov/research/umls/rxnorm",
    "RXN": "http://www.nlm.nih.gov/research/umls/rxnorm",
    "UCUM": "http://unitsofmeasure.org",
    "NDC": "http://hl7.org/fhir/sid/ndc",
    "CPT": "http://www.ama-assn.org/go/cpt",
    "C4": "http://www.ama-assn.org/go/cpt",
}

_OBX_STATUS_MAP: Dict[str, str] = {
    "F": "final",
    "P": "preliminary",
    "C": "corrected",
    "A": "amended",
    "R": "registered",
    "I": "registered",
    "W": "entered-in-error",
    "D": "entered-in-error",
    "X": "cancelled",
}

_OBR_STATUS_MAP: Dict[str, str] = {
    "F": "final",
    "P": "preliminary",
    "C": "corrected",
    "A": "amended",
    "R": "registered",
    "I": "registered",
    "O": "registered",
    "X": "cancelled",
}

_OBX_ABNORMAL_FLAG_MAP: Dict[str, Tuple[str, str]] = {
    "H": ("H", "High"),
    "HH": ("HH", "Critical high"),
    "L": ("L", "Low"),
    "LL": ("LL", "Critical low"),
    "A": ("A", "Abnormal"),
    "AA": ("AA", "Critical abnormal"),
    "N": ("N", "Normal"),
}

_PV1_CLASS_MAP: Dict[str, Tuple[str, str]] = {
    "I": ("IMP", "inpatient encounter"),
    "IMP": ("IMP", "inpatient encounter"),
    "O": ("AMB", "ambulatory"),
    "AMB": ("AMB", "ambulatory"),
    "E": ("EMER", "emergency"),
    "EMER": ("EMER", "emergency"),
    "P": ("PRENC", "pre-admission"),
    "R": ("AMB", "recurring patient"),
    "B": ("IMP", "obstetrics"),
}

_AL1_CATEGORY_MAP: Dict[str, str] = {
    "DA": "medication",
    "DRUG": "medication",
    "FA": "food",
    "FOOD": "food",
    "EA": "environment",
    "MA": "environment",
    "PA": "environment",
    "LA": "environment",
    "AA": "biologic",
}

_AL1_SEVERITY_MAP: Dict[str, Tuple[str, str]] = {
    "SV": ("severe", "high"),
    "SEVERE": ("severe", "high"),
    "MO": ("moderate", "low"),
    "MODERATE": ("moderate", "low"),
    "MI": ("mild", "low"),
    "MILD": ("mild", "low"),
}


@dataclass(frozen=True)
class HL7v2Diagnostic:
    """PHI-safe diagnostic emitted during HL7v2 message parsing."""

    code: str
    severity: Literal["error", "warning", "information"]
    message: str
    segment: Optional[str] = None
    line: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.segment:
            out["segment"] = self.segment
        if self.line is not None:
            out["line"] = self.line
        return out


class HL7v2ConversionError(ValueError):
    """Raised when an HL7v2 message is structurally unparseable; carries PHI-safe diagnostics."""

    def __init__(self, message: str, diagnostics: Optional[Sequence[HL7v2Diagnostic]] = None) -> None:
        super().__init__(message)
        self.diagnostics: List[Dict[str, Any]] = [
            d.to_dict() if isinstance(d, HL7v2Diagnostic) else dict(d)
            for d in (diagnostics or ())
        ]


@dataclass(frozen=True)
class _HL7EncodingChars:
    """HL7v2 encoding characters extracted from `MSH-1` and `MSH-2` (defaults to `|^~\\&`)."""

    field_sep: str = "|"
    component_sep: str = "^"
    repetition_sep: str = "~"
    escape_char: str = "\\"
    subcomponent_sep: str = "&"


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


def _extract_encoding_chars(lines: Sequence[str]) -> _HL7EncodingChars:
    """Extracts HL7v2 encoding characters from the first MSH segment, defaulting to `|^~\\&`."""
    for line in lines:
        if line.startswith("MSH") and len(line) >= 8:
            f_sep = line[3]
            enc = line[4:8]
            comp = enc[0] if len(enc) > 0 else "^"
            rep = enc[1] if len(enc) > 1 else "~"
            esc = enc[2] if len(enc) > 2 else "\\"
            sub = enc[3] if len(enc) > 3 else "&"
            return _HL7EncodingChars(
                field_sep=f_sep,
                component_sep=comp,
                repetition_sep=rep,
                escape_char=esc,
                subcomponent_sep=sub,
            )
    return _HL7EncodingChars()


def unescape_hl7v2_text(
    raw_text: Optional[str],
    enc: _HL7EncodingChars = _HL7EncodingChars(),
) -> str:
    """Unescapes HL7v2 escape sequences (`\\F\\`, `\\S\\`, `\\T\\`, `\\R\\`, `\\E\\`, `\\.br\\`, `\\X..\\`)."""
    if not raw_text:
        return ""
    esc = enc.escape_char
    if esc not in raw_text:
        return raw_text

    pattern = re.compile(re.escape(esc) + r"([^" + re.escape(esc) + r"]*)" + re.escape(esc))

    def _replace_match(match: re.Match[str]) -> str:
        token = match.group(1)
        if token == "F":
            return enc.field_sep
        if token == "S":
            return enc.component_sep
        if token == "T":
            return enc.subcomponent_sep
        if token == "R":
            return enc.repetition_sep
        if token == "E":
            return enc.escape_char
        if token.lower() in (".br", ".sp"):
            return "\n"
        if token.startswith(("X", "x")) and len(token) > 1:
            hex_part = token[1:]
            try:
                return bytes.fromhex(hex_part).decode("utf-8", errors="replace")
            except ValueError:
                return ""
        return match.group(0)

    return pattern.sub(_replace_match, raw_text)


def _parse_hl7_dtm(
    raw_dtm: Optional[str],
    fallback_date: str,
) -> Tuple[str, str]:
    """Converts an HL7v2 DTM string (`YYYYMMDD[HHMM[SS]][+/-ZZZZ]`) into `(iso_datetime, YYYY-MM-DD)`."""
    clean = (raw_dtm or "").strip()
    if not clean:
        return f"{fallback_date}T00:00:00+00:00", fallback_date

    # Check for explicit timezone offset (+HHMM or -HHMM)
    tz_suffix = "+00:00"
    tz_match = re.search(r"([+-])(\d{2})(\d{2})$", clean)
    base_part = clean
    if tz_match:
        tz_suffix = f"{tz_match.group(1)}{tz_match.group(2)}:{tz_match.group(3)}"
        base_part = clean[: tz_match.start()]

    digits_only = "".join(ch for ch in base_part[:14] if ch.isdigit())
    if len(digits_only) >= 8:
        yyyy = digits_only[0:4]
        mm = digits_only[4:6]
        dd = digits_only[6:8]
        hh = digits_only[8:10] if len(digits_only) >= 10 else "00"
        mi = digits_only[10:12] if len(digits_only) >= 12 else "00"
        ss = digits_only[12:14] if len(digits_only) >= 14 else "00"
        try:
            datetime(int(yyyy), int(mm), int(dd), int(hh), int(mi), int(ss))
            date_str = f"{yyyy}-{mm}-{dd}"
            return f"{date_str}T{hh}:{mi}:{ss}{tz_suffix}", date_str
        except ValueError:
            return f"{fallback_date}T00:00:00+00:00", fallback_date

    if len(clean) >= 10 and clean[4] == "-" and clean[7] == "-":
        date_str = clean[:10]
        iso_str = clean if "T" in clean else f"{date_str}T00:00:00+00:00"
        return iso_str, date_str

    return f"{fallback_date}T00:00:00+00:00", fallback_date


def _get_field(fields: Sequence[str], index: int) -> str:
    """Safely retrieves an HL7 pipe-delimited field by 1-based index (for non-MSH segments)."""
    if 0 <= index < len(fields):
        return fields[index].strip()
    return ""


def _split_repetitions(raw_field: str, enc: _HL7EncodingChars) -> List[str]:
    """Splits a field on the HL7v2 repetition separator (`~`), preserving non-empty repetitions."""
    if not raw_field:
        return []
    return [rep.strip() for rep in raw_field.split(enc.repetition_sep) if rep.strip()]


def _parse_ce_field(
    raw_ce: str,
    default_system: str,
    enc: _HL7EncodingChars = _HL7EncodingChars(),
) -> Tuple[str, str, str]:
    """Parses an HL7 CE/CWE component (`code^display^system`) into unescaped `(code, display, system_uri)`."""
    first_rep = _split_repetitions(raw_ce, enc)[0] if _split_repetitions(raw_ce, enc) else (raw_ce or "")
    parts = first_rep.split(enc.component_sep)
    code = unescape_hl7v2_text(parts[0].strip(), enc) if len(parts) > 0 else ""
    display = (
        unescape_hl7v2_text(parts[1].strip(), enc)
        if len(parts) > 1 and parts[1].strip()
        else code
    )
    raw_sys = (
        unescape_hl7v2_text(parts[2].strip(), enc).upper()
        if len(parts) > 2 and parts[2].strip()
        else ""
    )
    if raw_sys.startswith(("HTTP://", "HTTPS://", "URN:")):
        system_uri = parts[2].strip()
    else:
        system_uri = _HL7_CODE_SYSTEM_MAP.get(raw_sys, default_system)
    return code, display, system_uri


def _parse_reference_range(
    raw_range: str,
    unit_display: str,
    enc: _HL7EncodingChars,
) -> Optional[Dict[str, Any]]:
    """Parses `OBX-7` reference range string (e.g. `4.0-5.6`, `<200`, `>=60`) into a FHIR `Observation.referenceRange` item."""
    clean = unescape_hl7v2_text((raw_range or "").strip(), enc)
    if not clean:
        return None

    ref_entry: Dict[str, Any] = {"text": clean}
    range_match = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*$", clean)
    if range_match:
        low_val = float(range_match.group(1))
        high_val = float(range_match.group(2))
        low_q: Dict[str, Any] = {"value": low_val}
        high_q: Dict[str, Any] = {"value": high_val}
        if unit_display:
            low_q["unit"] = unit_display
            high_q["unit"] = unit_display
        ref_entry["low"] = low_q
        ref_entry["high"] = high_q
        return ref_entry

    upper_match = re.match(r"^\s*<=?\s*(-?\d+(?:\.\d+)?)\s*$", clean)
    if upper_match:
        high_q = {"value": float(upper_match.group(1))}
        if unit_display:
            high_q["unit"] = unit_display
        ref_entry["high"] = high_q
        return ref_entry

    lower_match = re.match(r"^\s*>=?\s*(-?\d+(?:\.\d+)?)\s*$", clean)
    if lower_match:
        low_q = {"value": float(lower_match.group(1))}
        if unit_display:
            low_q["unit"] = unit_display
        ref_entry["low"] = low_q
        return ref_entry

    return ref_entry


def _parse_obx_interpretation(
    raw_flag: str,
    enc: _HL7EncodingChars,
) -> Optional[List[Dict[str, Any]]]:
    """Parses `OBX-8` abnormal flags (`H`, `L`, `HH`, `LL`, `A`, `N`) into FHIR `Observation.interpretation`."""
    reps = _split_repetitions(raw_flag, enc)
    if not reps:
        return None

    codings: List[Dict[str, str]] = []
    for rep in reps:
        code_token = rep.split(enc.component_sep)[0].strip().upper()
        if code_token in _OBX_ABNORMAL_FLAG_MAP:
            mapped_code, mapped_disp = _OBX_ABNORMAL_FLAG_MAP[code_token]
            codings.append({
                "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                "code": mapped_code,
                "display": mapped_disp,
            })
    if not codings:
        return None
    return [{"coding": codings, "text": codings[0]["display"]}]


def _parse_segments_with_hl7apy(
    lines: Sequence[str],
    enc: _HL7EncodingChars,
) -> Tuple[List[Tuple[int, str, List[str], Optional[Any]]], List[HL7v2Diagnostic]]:
    """Parses HL7v2 lines using `hl7apy` (`parse_message` + per-segment `parse_segment` fallback) with diagnostics."""
    diagnostics: List[HL7v2Diagnostic] = []
    er7_message = "\r".join(lines)
    hl7apy_msg: Optional[Any] = None

    if lines and lines[0].startswith("MSH"):
        try:
            hl7apy_msg = parse_message(
                er7_message,
                find_groups=False,
                validation_level=VALIDATION_LEVEL.TOLERANT,
            )
        except Exception as exc:
            diagnostics.append(
                HL7v2Diagnostic(
                    code="hl7apy_message_fallback",
                    severity="warning",
                    message=f"hl7apy full-message parser reported non-standard structure ({type(exc).__name__}); falling back to segment-level parsing.",
                    segment="MSH",
                    line=1,
                )
            )

    parsed_rows: List[Tuple[int, str, List[str], Optional[Any]]] = []
    hl7apy_children = list(getattr(hl7apy_msg, "children", ()) or ()) if hl7apy_msg is not None else []
    child_idx = 0

    for line_no, raw_line in enumerate(lines, start=1):
        fields = raw_line.split(enc.field_sep)
        seg_name = fields[0].strip().upper() if fields else ""
        if not seg_name or len(seg_name) != 3 or not seg_name.isalnum():
            diagnostics.append(
                HL7v2Diagnostic(
                    code="malformed_segment_header",
                    severity="warning",
                    message="Skipped malformed HL7v2 line with invalid 3-character segment identifier.",
                    segment=seg_name[:10] if seg_name else None,
                    line=line_no,
                )
            )
            continue

        if len(fields) < 2:
            diagnostics.append(
                HL7v2Diagnostic(
                    code="missing_segment_fields",
                    severity="warning",
                    message=f"Skipped truncated HL7v2 '{seg_name}' segment with no field delimiter.",
                    segment=seg_name,
                    line=line_no,
                )
            )
            continue

        seg_obj: Optional[Any] = None
        if child_idx < len(hl7apy_children) and getattr(hl7apy_children[child_idx], "name", "") == seg_name:
            seg_obj = hl7apy_children[child_idx]
            child_idx += 1
        else:
            try:
                seg_obj = parse_segment(raw_line, validation_level=VALIDATION_LEVEL.TOLERANT)
            except Exception:
                seg_obj = None

        parsed_rows.append((line_no, seg_name, fields, seg_obj))

    return parsed_rows, diagnostics


def _fallback_hl7v2_to_fhir(
    raw_content: str,
    source_name: str = "HL7v2 Clinical Message",
) -> Dict[str, Any]:
    """Deterministically parses HL7v2 (`ADT^A01`/`A08`, `ORU^R01`, `VXU^V04`) via `hl7apy` into validated FHIR R4 resources."""
    if not isinstance(raw_content, str) or not raw_content.strip():
        raise HL7v2ConversionError(
            "HL7v2 message content cannot be empty.",
            diagnostics=[
                HL7v2Diagnostic(
                    code="empty_message",
                    severity="error",
                    message="HL7v2 message content is empty or whitespace-only.",
                )
            ],
        )

    lines = [
        line.strip()
        for line in raw_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if line.strip()
    ]
    if not lines:
        raise HL7v2ConversionError(
            "HL7v2 message contains no segments.",
            diagnostics=[
                HL7v2Diagnostic(
                    code="no_segments",
                    severity="error",
                    message="HL7v2 message contains no non-empty segment lines.",
                )
            ],
        )

    enc = _extract_encoding_chars(lines)
    has_hl7_segment = any(
        line[:3].upper() in RECOGNIZED_HL7_SEGMENTS and len(line) > 3 and line[3] == enc.field_sep
        for line in lines
    )
    if not has_hl7_segment:
        raise HL7v2ConversionError(
            "Invalid HL7v2 payload: no recognized MSH/PID/PV1/OBR/OBX/RXA/DG1/AL1 segments found.",
            diagnostics=[
                HL7v2Diagnostic(
                    code="unrecognized_hl7v2_payload",
                    severity="error",
                    message="No recognized HL7v2 segments (MSH, PID, PV1, OBR, OBX, RXA, DG1, AL1) were found.",
                )
            ],
        )

    parsed_segments, diagnostics = _parse_segments_with_hl7apy(lines, enc)
    clean_source = (source_name or "HL7v2 Clinical Message").strip()
    fallback_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    msg_date = fallback_date
    message_type = "UNKNOWN"
    message_control_id = ""

    patient_resource: Optional[Dict[str, Any]] = None
    patient_ref_display = "Patient"
    patient_id = "pat-hl7-1"
    active_encounter_id: Optional[str] = None

    staged_records: List[Dict[str, Any]] = []
    bundle_entries: List[Dict[str, Any]] = []
    counts_by_type: Dict[str, int] = {}
    dates: List[str] = []

    # Track open OBR DiagnosticReport so subsequent OBX observations link into DiagnosticReport.result
    current_diag_report: Optional[Dict[str, Any]] = None
    current_diag_staged: Optional[Dict[str, Any]] = None

    def _finalize_current_diagnostic_report() -> None:
        nonlocal current_diag_report, current_diag_staged
        if current_diag_report is None or current_diag_staged is None:
            return
        validated_dr = FhirDiagnosticReport.model_validate(current_diag_report)
        dr_clean = validated_dr.model_dump(mode="json", exclude_none=True)
        dr_fhir = dict(dr_clean)
        dr_fhir["_carefold_provenance"] = {
            "source_type": "hl7v2",
            "source_name": clean_source,
            "source_display": current_diag_staged["source_display"],
            "trust": "untrusted",
        }
        current_diag_staged["data"] = dr_fhir
        # Update bundle entry in place
        for b_entry in bundle_entries:
            res = b_entry.get("resource")
            if isinstance(res, dict) and res.get("resourceType") == "DiagnosticReport" and res.get("id") == dr_clean.get("id"):
                b_entry["resource"] = dr_clean
                break
        current_diag_report = None
        current_diag_staged = None

    for line_no, seg_name, fields, _seg_obj in parsed_segments:
        try:
            if seg_name == "MSH":
                # In MSH, fields[6] is MSH-7 (Date/Time of Message), fields[8] is MSH-9 (Message Type), fields[9] is MSH-10
                msh_dtm = _get_field(fields, 6)
                if msh_dtm:
                    _, msg_date = _parse_hl7_dtm(msh_dtm, fallback_date)
                raw_msg_type = _get_field(fields, 8)
                if raw_msg_type:
                    mt_parts = raw_msg_type.split(enc.component_sep)
                    if len(mt_parts) >= 2 and mt_parts[0] and mt_parts[1]:
                        message_type = f"{mt_parts[0].strip()}^{mt_parts[1].strip()}"
                    else:
                        message_type = raw_msg_type.strip()
                message_control_id = _get_field(fields, 9)

            elif seg_name == "PID":
                pid3_reps = _split_repetitions(_get_field(fields, 3), enc)
                primary_id_raw = (
                    pid3_reps[0].split(enc.component_sep)[0].strip()
                    if pid3_reps
                    else ""
                ) or "pat-hl7-1"
                clean_id_token = re.sub(r"[^A-Za-z0-9._-]", "-", unescape_hl7v2_text(primary_id_raw, enc)).strip("-") or "pat-hl7-1"
                patient_id = clean_id_token if clean_id_token.startswith("pat-") else f"pat-{clean_id_token}"

                identifiers: List[Dict[str, Any]] = []
                for rep in pid3_reps:
                    id_parts = rep.split(enc.component_sep)
                    id_val = unescape_hl7v2_text(id_parts[0].strip(), enc) if id_parts else ""
                    if not id_val:
                        continue
                    assigning = unescape_hl7v2_text(id_parts[3].strip(), enc) if len(id_parts) > 3 else ""
                    id_type = unescape_hl7v2_text(id_parts[4].strip(), enc) if len(id_parts) > 4 else ""
                    id_entry: Dict[str, Any] = {"value": id_val}
                    if assigning:
                        id_entry["system"] = f"urn:hl7v2:assigning-authority:{assigning.lower()}"
                    if id_type:
                        id_entry["type"] = {"text": id_type}
                    identifiers.append(id_entry)

                raw_name_reps = _split_repetitions(_get_field(fields, 5), enc)
                names: List[Dict[str, Any]] = []
                for name_rep in raw_name_reps:
                    name_parts = name_rep.split(enc.component_sep)
                    family = unescape_hl7v2_text(name_parts[0].strip(), enc) if len(name_parts) > 0 else ""
                    given = unescape_hl7v2_text(name_parts[1].strip(), enc) if len(name_parts) > 1 else ""
                    middle = unescape_hl7v2_text(name_parts[2].strip(), enc) if len(name_parts) > 2 else ""
                    if family or given:
                        n_entry: Dict[str, Any] = {}
                        if family:
                            n_entry["family"] = family
                        givens = [g for g in (given, middle) if g]
                        if givens:
                            n_entry["given"] = givens
                        names.append(n_entry)
                        if patient_ref_display == "Patient":
                            patient_ref_display = f"{given} {family}".strip()

                raw_dob = _get_field(fields, 7)
                raw_sex = _get_field(fields, 8).upper()
                gender_map = {"M": "male", "F": "female", "O": "other", "U": "unknown"}

                # Address (PID-11) & Telecom (PID-13)
                addresses: List[Dict[str, Any]] = []
                for addr_rep in _split_repetitions(_get_field(fields, 11), enc):
                    a_parts = addr_rep.split(enc.component_sep)
                    line1 = unescape_hl7v2_text(a_parts[0].strip(), enc) if len(a_parts) > 0 else ""
                    city = unescape_hl7v2_text(a_parts[2].strip(), enc) if len(a_parts) > 2 else ""
                    state = unescape_hl7v2_text(a_parts[3].strip(), enc) if len(a_parts) > 3 else ""
                    postal = unescape_hl7v2_text(a_parts[4].strip(), enc) if len(a_parts) > 4 else ""
                    country = unescape_hl7v2_text(a_parts[5].strip(), enc) if len(a_parts) > 5 else ""
                    addr_obj: Dict[str, Any] = {}
                    if line1:
                        addr_obj["line"] = [line1]
                    if city:
                        addr_obj["city"] = city
                    if state:
                        addr_obj["state"] = state
                    if postal:
                        addr_obj["postalCode"] = postal
                    if country:
                        addr_obj["country"] = country
                    if addr_obj:
                        addresses.append(addr_obj)

                telecoms: List[Dict[str, Any]] = []
                for tel_rep in _split_repetitions(_get_field(fields, 13), enc):
                    t_parts = tel_rep.split(enc.component_sep)
                    tel_val = unescape_hl7v2_text(t_parts[0].strip(), enc) if len(t_parts) > 0 else ""
                    email_val = unescape_hl7v2_text(t_parts[3].strip(), enc) if len(t_parts) > 3 else ""
                    if email_val and "@" in email_val:
                        telecoms.append({"system": "email", "value": email_val})
                    elif tel_val:
                        system = "email" if "@" in tel_val else "phone"
                        telecoms.append({"system": system, "value": tel_val})

                pat_candidate: Dict[str, Any] = {
                    "resourceType": "Patient",
                    "id": patient_id,
                }
                if identifiers:
                    pat_candidate["identifier"] = identifiers
                if names:
                    pat_candidate["name"] = names
                if raw_dob and len(raw_dob) >= 8 and raw_dob[:8].isdigit():
                    pat_candidate["birthDate"] = f"{raw_dob[0:4]}-{raw_dob[4:6]}-{raw_dob[6:8]}"
                if raw_sex in gender_map:
                    pat_candidate["gender"] = gender_map[raw_sex]
                if telecoms:
                    pat_candidate["telecom"] = telecoms
                if addresses:
                    pat_candidate["address"] = addresses

                validated_pat = FhirPatient.model_validate(pat_candidate)
                patient_resource = validated_pat.model_dump(mode="json", exclude_none=True)
                bundle_entries.append({"resource": patient_resource})

            elif seg_name == "PV1":
                set_id = _get_field(fields, 1) or str(line_no)
                pat_class_raw = _get_field(fields, 2).upper() or "O"
                class_code, class_display = _PV1_CLASS_MAP.get(pat_class_raw, ("AMB", "ambulatory"))
                loc_raw = _get_field(fields, 3)
                attending_raw = _get_field(fields, 7)
                visit_num_raw = _get_field(fields, 19).split(enc.component_sep)[0].strip()
                admit_dtm_raw = _get_field(fields, 44)
                discharge_dtm_raw = _get_field(fields, 45)

                start_iso, date_str = _parse_hl7_dtm(admit_dtm_raw, msg_date)
                dates.append(date_str)
                period_obj: Dict[str, Any] = {"start": start_iso}
                if discharge_dtm_raw:
                    end_iso, _ = _parse_hl7_dtm(discharge_dtm_raw, date_str)
                    period_obj["end"] = end_iso

                enc_id_suffix = re.sub(r"[^A-Za-z0-9._-]", "-", visit_num_raw or set_id).strip("-") or str(line_no)
                enc_id = f"enc-{enc_id_suffix}"
                active_encounter_id = enc_id

                enc_candidate: Dict[str, Any] = {
                    "resourceType": "Encounter",
                    "id": enc_id,
                    "status": "finished",
                    "class": {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                        "code": class_code,
                        "display": class_display,
                    },
                    "subject": {"reference": f"Patient/{patient_id}", "display": patient_ref_display},
                    "period": period_obj,
                }

                loc_parts = [unescape_hl7v2_text(p.strip(), enc) for p in loc_raw.split(enc.component_sep) if p.strip()]
                loc_display = " / ".join(loc_parts[:3]) if loc_parts else ""
                if loc_display:
                    enc_candidate["location"] = [{"location": {"display": loc_display}}]

                if attending_raw:
                    att_parts = attending_raw.split(enc.component_sep)
                    att_family = unescape_hl7v2_text(att_parts[1].strip(), enc) if len(att_parts) > 1 else ""
                    att_given = unescape_hl7v2_text(att_parts[2].strip(), enc) if len(att_parts) > 2 else ""
                    att_disp = f"{att_given} {att_family}".strip() or unescape_hl7v2_text(att_parts[0].strip(), enc)
                    if att_disp:
                        enc_candidate["participant"] = [{"individual": {"display": att_disp}}]

                validated_enc = FhirEncounter.model_validate(enc_candidate)
                enc_clean = validated_enc.model_dump(mode="json", exclude_none=True)
                bundle_entries.append({"resource": enc_clean})

                enc_fhir = dict(enc_clean)
                source_display = f"From {clean_source}, {date_str}"
                enc_fhir["_carefold_provenance"] = {
                    "source_type": "hl7v2",
                    "source_name": clean_source,
                    "source_display": source_display,
                    "trust": "untrusted",
                }
                summary_disp = f"{class_display.title()} ({loc_display})" if loc_display else class_display.title()
                staged_records.append({
                    "resource_type": "Encounter",
                    "source_id": f"Encounter:{enc_fhir['id']}",
                    "effective_at": start_iso,
                    "display": summary_disp,
                    "code": class_code,
                    "data": enc_fhir,
                    "source_display": source_display,
                    "trust": "untrusted",
                })
                counts_by_type["Encounter"] = counts_by_type.get("Encounter", 0) + 1

            elif seg_name == "OBR":
                _finalize_current_diagnostic_report()
                set_id = _get_field(fields, 1) or str(line_no)
                filler_order = _get_field(fields, 3).split(enc.component_sep)[0].strip()
                service_id_field = _get_field(fields, 4)
                obr_dtm_raw = _get_field(fields, 7) or _get_field(fields, 6)
                obr_status_raw = _get_field(fields, 25).upper() or "F"

                code_val, display_val, system_uri = _parse_ce_field(service_id_field, "http://loinc.org", enc)
                effective_iso, date_str = _parse_hl7_dtm(obr_dtm_raw, msg_date)
                dates.append(date_str)
                dr_status = _OBR_STATUS_MAP.get(obr_status_raw, "final")

                dr_id_token = re.sub(
                    r"[^A-Za-z0-9._-]",
                    "-",
                    f"obr-{set_id}-{code_val or filler_order or line_no}",
                ).strip("-")
                dr_candidate: Dict[str, Any] = {
                    "resourceType": "DiagnosticReport",
                    "id": dr_id_token,
                    "status": dr_status,
                    "code": {
                        "coding": [
                            {
                                "system": system_uri,
                                "code": code_val or "panel",
                                "display": display_val or "Diagnostic Panel",
                            }
                        ],
                        "text": display_val or code_val or "Diagnostic Panel",
                    },
                    "subject": {"reference": f"Patient/{patient_id}", "display": patient_ref_display},
                    "effectiveDateTime": effective_iso,
                    "result": [],
                }
                if active_encounter_id:
                    dr_candidate["encounter"] = {"reference": f"Encounter/{active_encounter_id}"}

                validated_dr = FhirDiagnosticReport.model_validate(dr_candidate)
                dr_clean = validated_dr.model_dump(mode="json", exclude_none=True)
                bundle_entries.append({"resource": dr_clean})

                dr_fhir = dict(dr_clean)
                source_display = f"From {clean_source}, {date_str}"
                dr_fhir["_carefold_provenance"] = {
                    "source_type": "hl7v2",
                    "source_name": clean_source,
                    "source_display": source_display,
                    "trust": "untrusted",
                }
                staged_item: Dict[str, Any] = {
                    "resource_type": "DiagnosticReport",
                    "source_id": f"DiagnosticReport:{dr_fhir['id']}",
                    "effective_at": effective_iso,
                    "display": display_val or code_val or "Diagnostic Report",
                    "code": code_val or None,
                    "data": dr_fhir,
                    "source_display": source_display,
                    "trust": "untrusted",
                }
                staged_records.append(staged_item)
                counts_by_type["DiagnosticReport"] = counts_by_type.get("DiagnosticReport", 0) + 1
                current_diag_report = dr_candidate
                current_diag_staged = staged_item

            elif seg_name == "OBX":
                set_id = _get_field(fields, 1) or str(line_no)
                val_type = _get_field(fields, 2).upper() or "ST"
                obs_id_field = _get_field(fields, 3)
                obs_val_raw = _get_field(fields, 5)
                units_field = _get_field(fields, 6)
                ref_range_raw = _get_field(fields, 7)
                abnormal_flag_raw = _get_field(fields, 8)
                status_code = _get_field(fields, 11).upper() or "F"
                obs_dtm_raw = _get_field(fields, 14)

                code_val, display_val, system_uri = _parse_ce_field(obs_id_field, "http://loinc.org", enc)
                unit_code, unit_display, _ = _parse_ce_field(units_field, "http://unitsofmeasure.org", enc)
                effective_iso, date_str = _parse_hl7_dtm(obs_dtm_raw, msg_date)
                dates.append(date_str)
                fhir_status = _OBX_STATUS_MAP.get(status_code, "final")

                obs_id = re.sub(
                    r"[^A-Za-z0-9._-]",
                    "-",
                    f"obx-{set_id}-{code_val or line_no}",
                ).strip("-")
                obs_candidate: Dict[str, Any] = {
                    "resourceType": "Observation",
                    "id": obs_id,
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
                if active_encounter_id:
                    obs_candidate["encounter"] = {"reference": f"Encounter/{active_encounter_id}"}

                ref_range_entry = _parse_reference_range(ref_range_raw, unit_display or unit_code, enc)
                if ref_range_entry is not None:
                    obs_candidate["referenceRange"] = [ref_range_entry]

                interp_list = _parse_obx_interpretation(abnormal_flag_raw, enc)
                if interp_list is not None:
                    obs_candidate["interpretation"] = interp_list

                summary_display = display_val or code_val or "Observation"
                val_reps = _split_repetitions(obs_val_raw, enc)
                joined_unescaped_val = "\n".join(unescape_hl7v2_text(r, enc) for r in val_reps) if val_reps else unescape_hl7v2_text(obs_val_raw, enc)

                if val_type in ("NM", "SN") or (obs_val_raw and _is_float(obs_val_raw)):
                    clean_num_str = joined_unescaped_val.lstrip("<>=").strip()
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
                        obs_candidate["valueString"] = joined_unescaped_val
                elif val_type in ("CE", "CWE") and enc.component_sep in obs_val_raw:
                    v_code, v_disp, v_sys = _parse_ce_field(obs_val_raw, "http://snomed.info/sct", enc)
                    obs_candidate["valueCodeableConcept"] = {
                        "coding": [{"system": v_sys, "code": v_code, "display": v_disp}],
                        "text": v_disp,
                    }
                    summary_display = f"{summary_display}: {v_disp}".strip()
                elif joined_unescaped_val:
                    obs_candidate["valueString"] = joined_unescaped_val
                    summary_display = f"{summary_display}: {joined_unescaped_val}".strip()

                validated_obs = FhirObservation.model_validate(obs_candidate)
                obs_clean = validated_obs.model_dump(mode="json", exclude_none=True)
                bundle_entries.append({"resource": obs_clean})

                if current_diag_report is not None:
                    current_diag_report.setdefault("result", []).append({
                        "reference": f"Observation/{obs_clean['id']}",
                        "display": summary_display,
                    })

                obs_fhir = dict(obs_clean)
                source_display = f"From {clean_source}, {date_str}"
                obs_fhir["_carefold_provenance"] = {
                    "source_type": "hl7v2",
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
                sub_id = _get_field(fields, 1) or str(line_no)
                rxa_dtm_raw = _get_field(fields, 3) or _get_field(fields, 4)
                rxa_code_field = _get_field(fields, 5)
                dose_amt_raw = _get_field(fields, 6)
                dose_unit_raw = _get_field(fields, 7)
                lot_reps = _split_repetitions(_get_field(fields, 15), enc)
                lot_number = unescape_hl7v2_text(lot_reps[0], enc) if lot_reps else ""
                exp_dtm_raw = _get_field(fields, 16)
                rxa_status_raw = _get_field(fields, 20).upper()

                cvx_code, vax_display, vax_system = _parse_ce_field(
                    rxa_code_field, "http://hl7.org/fhir/sid/cvx", enc
                )
                effective_iso, date_str = _parse_hl7_dtm(rxa_dtm_raw, msg_date)
                dates.append(date_str)
                imm_status = "not-done" if rxa_status_raw in ("RE", "NA") else "completed"

                imm_id = re.sub(
                    r"[^A-Za-z0-9._-]",
                    "-",
                    f"rxa-{sub_id}-{cvx_code or line_no}",
                ).strip("-")
                imm_candidate: Dict[str, Any] = {
                    "resourceType": "Immunization",
                    "id": imm_id,
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
                if active_encounter_id:
                    imm_candidate["encounter"] = {"reference": f"Encounter/{active_encounter_id}"}
                if lot_number:
                    imm_candidate["lotNumber"] = lot_number
                if exp_dtm_raw:
                    _, exp_date_str = _parse_hl7_dtm(exp_dtm_raw, date_str)
                    imm_candidate["expirationDate"] = exp_date_str
                if dose_amt_raw and _is_float(dose_amt_raw) and float(dose_amt_raw) != 999.0:
                    u_code, u_disp, _ = _parse_ce_field(dose_unit_raw, "http://unitsofmeasure.org", enc)
                    dq: Dict[str, Any] = {"value": float(dose_amt_raw)}
                    if u_disp or u_code:
                        dq["unit"] = u_disp or u_code
                        dq["system"] = "http://unitsofmeasure.org"
                        dq["code"] = u_code or u_disp
                    imm_candidate["doseQuantity"] = dq

                validated_imm = FhirImmunization.model_validate(imm_candidate)
                imm_clean = validated_imm.model_dump(mode="json", exclude_none=True)
                bundle_entries.append({"resource": imm_clean})

                imm_fhir = dict(imm_clean)
                source_display = f"From {clean_source}, {date_str}"
                imm_fhir["_carefold_provenance"] = {
                    "source_type": "hl7v2",
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

            elif seg_name == "DG1":
                set_id = _get_field(fields, 1) or str(line_no)
                dg_code_field = _get_field(fields, 3)
                dg_desc_fallback = unescape_hl7v2_text(_get_field(fields, 4), enc)
                dg_dtm_raw = _get_field(fields, 5)
                dg_type_raw = _get_field(fields, 6).upper()

                dg_code, dg_display, dg_system = _parse_ce_field(
                    dg_code_field, "http://hl7.org/fhir/sid/icd-10-cm", enc
                )
                if (not dg_display or dg_display == dg_code) and dg_desc_fallback:
                    dg_display = dg_desc_fallback
                effective_iso, date_str = _parse_hl7_dtm(dg_dtm_raw, msg_date)
                dates.append(date_str)

                cond_id = re.sub(
                    r"[^A-Za-z0-9._-]",
                    "-",
                    f"dg1-{set_id}-{dg_code or line_no}",
                ).strip("-")
                cat_code = "encounter-diagnosis" if dg_type_raw in ("A", "W", "F") else "problem-list-item"
                cond_candidate: Dict[str, Any] = {
                    "resourceType": "Condition",
                    "id": cond_id,
                    "clinicalStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                "code": "active",
                                "display": "Active",
                            }
                        ]
                    },
                    "category": [
                        {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                                    "code": cat_code,
                                }
                            ]
                        }
                    ],
                    "code": {
                        "coding": [
                            {
                                "system": dg_system,
                                "code": dg_code or "unknown",
                                "display": dg_display or "Condition",
                            }
                        ],
                        "text": dg_display or dg_code or "Condition",
                    },
                    "subject": {"reference": f"Patient/{patient_id}", "display": patient_ref_display},
                    "onsetDateTime": effective_iso,
                    "recordedDate": date_str,
                }
                if active_encounter_id:
                    cond_candidate["encounter"] = {"reference": f"Encounter/{active_encounter_id}"}

                validated_cond = FhirCondition.model_validate(cond_candidate)
                cond_clean = validated_cond.model_dump(mode="json", exclude_none=True)
                bundle_entries.append({"resource": cond_clean})

                cond_fhir = dict(cond_clean)
                source_display = f"From {clean_source}, {date_str}"
                cond_fhir["_carefold_provenance"] = {
                    "source_type": "hl7v2",
                    "source_name": clean_source,
                    "source_display": source_display,
                    "trust": "untrusted",
                }
                staged_records.append({
                    "resource_type": "Condition",
                    "source_id": f"Condition:{cond_fhir['id']}",
                    "effective_at": effective_iso,
                    "display": dg_display or dg_code or "Condition",
                    "code": dg_code or None,
                    "data": cond_fhir,
                    "source_display": source_display,
                    "trust": "untrusted",
                })
                counts_by_type["Condition"] = counts_by_type.get("Condition", 0) + 1

            elif seg_name == "AL1":
                set_id = _get_field(fields, 1) or str(line_no)
                al_type_raw = _get_field(fields, 2).split(enc.component_sep)[0].strip().upper()
                al_code_field = _get_field(fields, 3)
                al_sev_raw = _get_field(fields, 4).split(enc.component_sep)[0].strip().upper()
                al_reactions_raw = _get_field(fields, 5)
                al_date_raw = _get_field(fields, 6)

                al_code, al_display, al_system = _parse_ce_field(
                    al_code_field, "http://www.nlm.nih.gov/research/umls/rxnorm", enc
                )
                effective_iso, date_str = _parse_hl7_dtm(al_date_raw, msg_date)
                dates.append(date_str)

                al_id = re.sub(
                    r"[^A-Za-z0-9._-]",
                    "-",
                    f"al1-{set_id}-{al_code or line_no}",
                ).strip("-")
                al_candidate: Dict[str, Any] = {
                    "resourceType": "AllergyIntolerance",
                    "id": al_id,
                    "clinicalStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                                "code": "active",
                                "display": "Active",
                            }
                        ]
                    },
                    "code": {
                        "coding": [
                            {
                                "system": al_system,
                                "code": al_code or "unknown",
                                "display": al_display or "Allergen",
                            }
                        ],
                        "text": al_display or al_code or "Allergen",
                    },
                    "patient": {"reference": f"Patient/{patient_id}", "display": patient_ref_display},
                    "recordedDate": date_str,
                }
                if al_type_raw in _AL1_CATEGORY_MAP:
                    al_candidate["category"] = [_AL1_CATEGORY_MAP[al_type_raw]]

                reaction_severity: Optional[str] = None
                if al_sev_raw in _AL1_SEVERITY_MAP:
                    reaction_severity, criticality = _AL1_SEVERITY_MAP[al_sev_raw]
                    al_candidate["criticality"] = criticality

                reaction_reps = _split_repetitions(al_reactions_raw, enc)
                if reaction_reps or reaction_severity:
                    manifestations = [
                        {"text": unescape_hl7v2_text(r.split(enc.component_sep)[0].strip(), enc)}
                        for r in reaction_reps
                        if unescape_hl7v2_text(r.split(enc.component_sep)[0].strip(), enc)
                    ]
                    if not manifestations:
                        manifestations = [{"text": "Documented reaction"}]
                    rxn_item: Dict[str, Any] = {"manifestation": manifestations}
                    if reaction_severity:
                        rxn_item["severity"] = reaction_severity
                    al_candidate["reaction"] = [rxn_item]

                validated_al = FhirAllergyIntolerance.model_validate(al_candidate)
                al_clean = validated_al.model_dump(mode="json", exclude_none=True)
                bundle_entries.append({"resource": al_clean})

                al_fhir = dict(al_clean)
                source_display = f"From {clean_source}, {date_str}"
                al_fhir["_carefold_provenance"] = {
                    "source_type": "hl7v2",
                    "source_name": clean_source,
                    "source_display": source_display,
                    "trust": "untrusted",
                }
                staged_records.append({
                    "resource_type": "AllergyIntolerance",
                    "source_id": f"AllergyIntolerance:{al_fhir['id']}",
                    "effective_at": effective_iso,
                    "display": al_display or al_code or "AllergyIntolerance",
                    "code": al_code or None,
                    "data": al_fhir,
                    "source_display": source_display,
                    "trust": "untrusted",
                })
                counts_by_type["AllergyIntolerance"] = counts_by_type.get("AllergyIntolerance", 0) + 1

        except Exception as seg_exc:
            diagnostics.append(
                HL7v2Diagnostic(
                    code="segment_conversion_error",
                    severity="warning",
                    message=f"Failed to convert HL7v2 segment '{seg_name}' at line {line_no} ({type(seg_exc).__name__}).",
                    segment=seg_name,
                    line=line_no,
                )
            )

    _finalize_current_diagnostic_report()

    if not bundle_entries and diagnostics:
        raise HL7v2ConversionError(
            "HL7v2 message failed conversion: no valid clinical segments could be converted.",
            diagnostics=diagnostics,
        )

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
        "message_type": message_type,
        "message_control_id": message_control_id,
        "source_name": clean_source,
        "patient": patient_resource,
        "bundle": bundle_dict,
        "records": staged_records,
        "diagnostics": [d.to_dict() for d in diagnostics],
        "summary": {
            "total_records": len(staged_records),
            "counts_by_type": counts_by_type,
            "date_range": {
                "min": sorted_dates[0] if sorted_dates else msg_date,
                "max": sorted_dates[-1] if sorted_dates else msg_date,
            },
        },
    }


def parse_hl7v2_to_fhir(
    raw_content: str,
    source_name: str = "HL7v2 Clinical Message",
) -> Dict[str, Any]:
    """Deterministically parses HL7v2 (`ADT`, `ORU`, `VXU`) into validated FHIR R4 resources via `hl7apy`."""
    return _fallback_hl7v2_to_fhir(raw_content, source_name=source_name)


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
    """Executes deterministic local HL7v2 (`hl7apy`) or C-CDA conversion to FHIR R4 resources."""
    clean_type = (input_type or "hl7v2").strip().lower()
    if clean_type == "hl7v2":
        return _fallback_hl7v2_to_fhir(raw_content)
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
    patient_resource = next(
        (r.get("data") for r in parsed.get("records", []) if r.get("resource_type") == "Patient"),
        None,
    )
    clinical_records = [
        r for r in parsed.get("records", []) if r.get("resource_type") not in ("Provenance", "Patient")
    ]
    return {
        "format": input_type,
        "input_type": input_type,
        "converter_mode": "sidecar",
        "source_name": f"FHIR-Converter ({input_type.upper()})",
        "patient": patient_resource,
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
        raise HL7v2ConversionError(
            "Clinical payload content cannot be empty.",
            diagnostics=[
                HL7v2Diagnostic(
                    code="empty_message",
                    severity="error",
                    message="Clinical payload content cannot be empty.",
                )
            ],
        )

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
    "HL7APY_LICENSE_ATTESTATION",
    "HL7v2ConversionError",
    "HL7v2Diagnostic",
    "_fallback_hl7v2_to_fhir",
    "convert_clinical_payload_to_fhir",
    "parse_hl7v2_to_fhir",
    "unescape_hl7v2_text",
]
