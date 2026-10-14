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

"""State Immunization Information System (IIS) PDF Certificate Parser (AU-61 / E11.3).

Parses state IIS immunisation certificate text or PDF bytes, validates extracted doses
against `fhir.resources.R4B.immunization.Immunization` with standard CDC CVX codes,
and tags every staged record with `trust="untrusted"` and `From <source_name>, <date>`
provenance for Review-Before-Save (`AU-38`).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from fhir.resources.R4B.immunization import Immunization as FhirImmunization

# Canonical vaccine registry: (token_lower, canonical_name, cvx_code, display_text)
SUPPORTED_IIS_VACCINES: Tuple[Tuple[str, str, str, str], ...] = (
    (
        "dtap",
        "DTaP",
        "20",
        "Diphtheria, tetanus toxoids and acellular pertussis vaccine (DTaP)",
    ),
    (
        "tdap",
        "Tdap",
        "115",
        "Tetanus toxoid, reduced diphtheria toxoid, and acellular pertussis vaccine (Tdap)",
    ),
    (
        "mmr",
        "MMR",
        "03",
        "Measles, mumps and rubella virus vaccine (MMR)",
    ),
    (
        "ipv",
        "IPV",
        "10",
        "Poliovirus vaccine, inactivated (IPV)",
    ),
    (
        "hepb",
        "HepB",
        "08",
        "Hepatitis B vaccine, pediatric or pediatric/adolescent dosage (HepB)",
    ),
    (
        "hepatitis b",
        "HepB",
        "08",
        "Hepatitis B vaccine, pediatric or pediatric/adolescent dosage (HepB)",
    ),
    (
        "hepa",
        "HepA",
        "83",
        "Hepatitis A vaccine, pediatric/adolescent dosage, 2 dose schedule (HepA)",
    ),
    (
        "hepatitis a",
        "HepA",
        "83",
        "Hepatitis A vaccine, pediatric/adolescent dosage, 2 dose schedule (HepA)",
    ),
    (
        "varicella",
        "Varicella",
        "21",
        "Varicella virus vaccine",
    ),
    (
        "hib",
        "Hib",
        "17",
        "Haemophilus influenzae type b vaccine (Hib)",
    ),
    (
        "pcv13",
        "PCV13",
        "133",
        "Pneumococcal conjugate vaccine, 13 valent (PCV13)",
    ),
    (
        "pcv15",
        "PCV15",
        "215",
        "Pneumococcal conjugate vaccine, 15 valent (PCV15)",
    ),
    (
        "rotavirus",
        "Rotavirus",
        "116",
        "Rotavirus, live, pentavalent vaccine",
    ),
    (
        "hpv",
        "HPV",
        "165",
        "Human Papillomavirus 9-valent vaccine (HPV9)",
    ),
    (
        "menacwy",
        "MenACWY",
        "114",
        "Meningococcal MCV4P conjugate vaccine (MenACWY)",
    ),
    (
        "influenza",
        "Influenza",
        "141",
        "Influenza, seasonal, injectable",
    ),
    (
        "covid-19",
        "COVID-19",
        "213",
        "SARS-COV-2 (COVID-19) vaccine",
    ),
    (
        "covid19",
        "COVID-19",
        "213",
        "SARS-COV-2 (COVID-19) vaccine",
    ),
)

_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_US_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


def _extract_text_from_bytes_or_str(raw_input: Union[str, bytes]) -> str:
    """Extracts plain text from either a raw text string or PDF bytes."""
    if isinstance(raw_input, str):
        return raw_input
    if not isinstance(raw_input, bytes):
        raise ValueError("IIS immunisation content must be str or bytes.")

    if raw_input.startswith(b"%PDF"):
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw_input))
            pages = [page.extract_text() or "" for page in reader.pages]
            extracted = "\n".join(pages).strip()
            if extracted:
                return extracted
        except Exception:
            pass

    return raw_input.decode("utf-8", errors="replace")


def _extract_dates_from_line(line: str) -> List[str]:
    """Extracts all valid YYYY-MM-DD dates from a line (supporting YYYY-MM-DD and MM/DD/YYYY)."""
    dates: List[str] = []
    for m in _ISO_DATE_RE.finditer(line):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            norm = f"{y:04d}-{mo:02d}-{d:02d}"
            if norm not in dates:
                dates.append(norm)

    for m in _US_DATE_RE.finditer(line):
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            norm = f"{y:04d}-{mo:02d}-{d:02d}"
            if norm not in dates:
                dates.append(norm)

    return dates


def _match_vaccine_in_line(line: str) -> Optional[Tuple[str, str, str]]:
    """Matches a supported vaccine name in a text line and returns (canonical_name, cvx_code, display)."""
    lower = line.lower()
    # Pad non-alphanumeric boundaries for accurate token matching
    normalized_tokens = re.sub(r"[^a-z0-9-]+", " ", lower)
    padded = f" {normalized_tokens} "
    for token, canonical_name, cvx_code, display_text in SUPPORTED_IIS_VACCINES:
        if f" {token} " in padded or lower.startswith(token):
            return canonical_name, cvx_code, display_text
    return None


def parse_iis_immunisation_text(
    raw_text: Union[str, bytes],
    source_name: str = "State IIS Registry PDF",
) -> Dict[str, Any]:
    """Parses state IIS immunisation certificate text into FHIR R4 `Immunization` staged records."""
    text = _extract_text_from_bytes_or_str(raw_text).strip()
    if not text:
        raise ValueError("IIS immunisation certificate text is empty.")

    clean_source = (source_name or "State IIS Registry PDF").strip()
    staged_records: List[Dict[str, Any]] = []
    seen_keys: set[Tuple[str, str]] = set()
    all_dates: List[str] = []

    for line in text.splitlines():
        clean_line = line.strip()
        if not clean_line:
            continue

        matched_vax = _match_vaccine_in_line(clean_line)
        if matched_vax is None:
            continue

        canonical_name, cvx_code, display_text = matched_vax
        line_dates = _extract_dates_from_line(clean_line)
        if not line_dates:
            continue

        for dose_idx, date_str in enumerate(line_dates):
            dedup_key = (canonical_name, date_str)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            all_dates.append(date_str)

            digest = hashlib.sha256(f"{canonical_name}:{cvx_code}:{date_str}".encode("utf-8")).hexdigest()[:12]
            rec_id = f"iis-{canonical_name.lower()}-{date_str}-{digest}"
            source_id = f"Immunization:{rec_id}"
            source_display = f"From {clean_source}, {date_str}"
            effective_iso = f"{date_str}T00:00:00+00:00"

            imm_model = FhirImmunization.model_validate({
                "resourceType": "Immunization",
                "id": rec_id,
                "status": "completed",
                "vaccineCode": {
                    "coding": [
                        {
                            "system": "http://hl7.org/fhir/sid/cvx",
                            "code": cvx_code,
                            "display": display_text,
                        }
                    ],
                    "text": canonical_name,
                },
                "patient": {"display": "Patient"},
                "occurrenceDateTime": date_str,
                "primarySource": False,
            })
            fhir_data: Dict[str, Any] = imm_model.model_dump(mode="json", exclude_none=True)
            fhir_data["meta"] = {
                "source": clean_source,
                "trust": "untrusted",
            }
            fhir_data["_carefold_provenance"] = {
                "source_name": clean_source,
                "source_display": source_display,
                "trust": "untrusted",
            }

            staged_records.append({
                "resource_type": "Immunization",
                "source_id": source_id,
                "effective_at": effective_iso,
                "display": f"{canonical_name} (CVX {cvx_code}) — {date_str}",
                "code": cvx_code,
                "vaccine_name": canonical_name,
                "dose_number": dose_idx + 1,
                "data": fhir_data,
                "source_display": source_display,
                "trust": "untrusted",
            })

    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sorted_dates = sorted(all_dates)
    date_range = {
        "min": sorted_dates[0] if sorted_dates else now_date,
        "max": sorted_dates[-1] if sorted_dates else now_date,
    }

    return {
        "format": "iis_pdf",
        "source_name": clean_source,
        "records": staged_records,
        "summary": {
            "format": "iis_pdf",
            "total_records": len(staged_records),
            "clinical_records": len(staged_records),
            "counts_by_type": {"Immunization": len(staged_records)} if staged_records else {},
            "date_range": date_range,
            "source_name": clean_source,
        },
    }


__all__ = [
    "SUPPORTED_IIS_VACCINES",
    "parse_iis_immunisation_text",
]
