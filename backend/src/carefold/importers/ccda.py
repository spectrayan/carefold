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

"""C-CDA (HL7 Consolidated Clinical Document Architecture) XML parser (AU-38 / E10.1, E10.7).

Enforces:
- XXE defense: rejects `<!DOCTYPE` and `<!ENTITY` declarations prior to XML parsing.
- Extracts standard C-CDA sections (Problems, Medications, Allergies, Immunizations,
  Vital Signs, Results/Labs) by templateId OIDs, LOINC section codes, or section titles.
- Normalizes extracted clinical items to FHIR R4 resources with provenance
  (`From <source_name>, <date>`) and `"trust": "untrusted"` (E10.7).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from defusedxml import ElementTree as DET
from defusedxml.common import DefusedXmlException

# C-CDA Section templateId OIDs -> FHIR resourceType
_TEMPLATE_OID_MAP: Dict[str, Tuple[str, str]] = {
    "2.16.840.1.113883.10.20.22.2.5.1": ("Condition", "problems"),
    "2.16.840.1.113883.10.20.22.2.5": ("Condition", "problems"),
    "2.16.840.1.113883.10.20.22.2.1.1": ("MedicationStatement", "medications"),
    "2.16.840.1.113883.10.20.22.2.1": ("MedicationStatement", "medications"),
    "2.16.840.1.113883.10.20.22.2.6.1": ("AllergyIntolerance", "allergies"),
    "2.16.840.1.113883.10.20.22.2.6": ("AllergyIntolerance", "allergies"),
    "2.16.840.1.113883.10.20.22.2.2.1": ("Immunization", "immunizations"),
    "2.16.840.1.113883.10.20.22.2.2": ("Immunization", "immunizations"),
    "2.16.840.1.113883.10.20.22.2.4.1": ("Observation", "vitals"),
    "2.16.840.1.113883.10.20.22.2.4": ("Observation", "vitals"),
    "2.16.840.1.113883.10.20.22.2.3.1": ("Observation", "results"),
    "2.16.840.1.113883.10.20.22.2.3": ("Observation", "results"),
}

# C-CDA Section LOINC codes -> FHIR resourceType
_SECTION_LOINC_MAP: Dict[str, Tuple[str, str]] = {
    "11450-4": ("Condition", "problems"),
    "10160-0": ("MedicationStatement", "medications"),
    "48765-2": ("AllergyIntolerance", "allergies"),
    "11369-6": ("Immunization", "immunizations"),
    "8716-3": ("Observation", "vitals"),
    "30954-2": ("Observation", "results"),
}


def _local_name(tag: str) -> str:
    """Strips XML namespace URI prefix from tag name."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _parse_hl7_timestamp(raw_val: Optional[str], fallback_date: str) -> Tuple[str, str]:
    """Parses HL7 DTM strings (e.g. '20260315', '20260315103000') to ISO-8601 and YYYY-MM-DD."""
    if not raw_val or not str(raw_val).strip():
        return f"{fallback_date}T00:00:00+00:00", fallback_date
    clean = str(raw_val).strip()
    # Standard ISO format already
    if re.match(r"^\d{4}-\d{2}-\d{2}", clean):
        d_str = clean[:10]
        iso_str = clean if "T" in clean else f"{d_str}T00:00:00+00:00"
        return iso_str, d_str
    # HL7 YYYYMMDD[HHMMSS]
    digits = re.match(r"^(\d{4})(\d{2})(\d{2})(?:(\d{2})(\d{2})(\d{2})?)?", clean)
    if digits:
        yyyy, mm, dd, hh, mi, ss = digits.groups()
        d_str = f"{yyyy}-{mm}-{dd}"
        hh = hh or "00"
        mi = mi or "00"
        ss = ss or "00"
        return f"{d_str}T{hh}:{mi}:{ss}+00:00", d_str
    return f"{fallback_date}T00:00:00+00:00", fallback_date


def _classify_section(section_elem: Any) -> Optional[Tuple[str, str]]:
    """Determines (resource_type, section_category) for a C-CDA <section> element."""
    # 1. Check templateId OIDs
    for child in section_elem:
        if _local_name(child.tag) == "templateId":
            root_oid = (child.attrib.get("root") or "").strip()
            if root_oid in _TEMPLATE_OID_MAP:
                return _TEMPLATE_OID_MAP[root_oid]

    # 2. Check section <code> LOINC
    for child in section_elem:
        if _local_name(child.tag) == "code":
            code_val = (child.attrib.get("code") or "").strip()
            if code_val in _SECTION_LOINC_MAP:
                return _SECTION_LOINC_MAP[code_val]

    # 3. Check section <title>
    for child in section_elem:
        if _local_name(child.tag) == "title" and child.text:
            title_lower = child.text.strip().lower()
            if any(k in title_lower for k in ("problem", "condition", "diagnos")):
                return ("Condition", "problems")
            if "medication" in title_lower:
                return ("MedicationStatement", "medications")
            if "allerg" in title_lower or "intolerance" in title_lower:
                return ("AllergyIntolerance", "allergies")
            if "immuniz" in title_lower or "vaccin" in title_lower:
                return ("Immunization", "immunizations")
            if "vital" in title_lower:
                return ("Observation", "vitals")
            if "result" in title_lower or "lab" in title_lower:
                return ("Observation", "results")

    return None


def _extract_document_date(root: Any) -> str:
    """Extracts document-level effectiveTime or defaults to current UTC date."""
    for child in root:
        if _local_name(child.tag) == "effectiveTime":
            val = child.attrib.get("value")
            if val:
                _, d_str = _parse_hl7_timestamp(val, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
                return d_str
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _extract_entry_details(
    entry_elem: Any,
    rtype: str,
    section_cat: str,
    doc_date: str,
) -> List[Dict[str, Any]]:
    """Extracts one or more clinical items from a C-CDA <entry> element."""
    items: List[Dict[str, Any]] = []

    # For vital signs / lab organizers with multiple component observations, inspect observations
    target_nodes: List[Any] = []
    for elem in entry_elem.iter():
        lname = _local_name(elem.tag)
        if rtype == "Observation" and lname == "observation":
            target_nodes.append(elem)
        elif rtype == "Condition" and lname == "observation":
            target_nodes.append(elem)
        elif rtype == "AllergyIntolerance" and lname == "observation":
            target_nodes.append(elem)
        elif rtype == "MedicationStatement" and lname == "substanceAdministration":
            target_nodes.append(elem)
        elif rtype == "Immunization" and lname == "substanceAdministration":
            target_nodes.append(elem)

    if not target_nodes:
        target_nodes = [entry_elem]

    for node in target_nodes:
        code_val: Optional[str] = None
        display_val: Optional[str] = None
        system_val: Optional[str] = None
        value_num: Optional[Any] = None
        value_unit: Optional[str] = None
        value_text: Optional[str] = None
        eff_raw: Optional[str] = None
        entry_id: Optional[str] = None

        for sub in node.iter():
            sname = _local_name(sub.tag)
            if sname == "id" and not entry_id:
                root_attr = sub.attrib.get("root") or ""
                ext_attr = sub.attrib.get("extension") or ""
                entry_id = f"{root_attr}:{ext_attr}".strip(":") or None
            elif sname in ("effectiveTime", "low") and not eff_raw:
                if sub.attrib.get("value"):
                    eff_raw = sub.attrib.get("value")
            elif sname == "code":
                c = sub.attrib.get("code")
                d = sub.attrib.get("displayName")
                sys_oid = sub.attrib.get("codeSystemName") or sub.attrib.get("codeSystem")
                # Prefer specific clinical codes over generic section/act wrapper codes
                if d or (c and not code_val):
                    if c:
                        code_val = c
                    if d:
                        display_val = d
                    if sys_oid:
                        system_val = sys_oid
            elif sname == "value":
                v_code = sub.attrib.get("code")
                v_disp = sub.attrib.get("displayName")
                v_val = sub.attrib.get("value")
                v_unit = sub.attrib.get("unit")
                if v_val is not None:
                    try:
                        value_num = float(v_val)
                    except ValueError:
                        value_text = v_val
                    value_unit = v_unit
                elif v_disp:
                    # For conditions/allergies where <code code="ASSERTION"> and <value displayName="Asthma">
                    if not display_val or display_val.lower() in ("assertion", "problem", "condition", "allergy"):
                        display_val = v_disp
                        if v_code:
                            code_val = v_code
                    else:
                        value_text = v_disp
                elif sub.text and sub.text.strip():
                    value_text = sub.text.strip()
            elif sname == "name" and sub.text and sub.text.strip() and not display_val:
                display_val = sub.text.strip()

        if not display_val and not code_val and value_num is None and not value_text:
            continue

        eff_iso, eff_date = _parse_hl7_timestamp(eff_raw, doc_date)
        final_display = display_val or value_text or f"{rtype} ({code_val or 'record'})"
        if value_num is not None:
            unit_str = f" {value_unit}" if value_unit else ""
            final_display = f"{final_display}: {value_num}{unit_str}"
        elif value_text and value_text != final_display:
            final_display = f"{final_display}: {value_text}"

        items.append({
            "entry_id": entry_id,
            "code": code_val,
            "system": system_val,
            "display": final_display,
            "raw_display": display_val or final_display,
            "value_num": value_num,
            "value_unit": value_unit,
            "value_text": value_text,
            "effective_iso": eff_iso,
            "effective_date": eff_date,
            "section_category": section_cat,
        })

    return items


def parse_ccda_xml(
    raw_content: Union[str, bytes],
    source_name: str = "C-CDA Clinical Summary",
) -> Dict[str, Any]:
    """Safely parses a C-CDA XML document and normalizes clinical sections to FHIR R4 records.

    Args:
        raw_content: XML string or UTF-8 bytes of a C-CDA document.
        source_name: Human-readable origin label for provenance attribution.

    Returns:
        Dictionary containing `format`, `source_name`, `records`, `provenance`, and `summary`.

    Raises:
        ValueError: If XML contains XXE (`<!DOCTYPE` / `<!ENTITY`) or is malformed.
    """
    if isinstance(raw_content, bytes):
        xml_text = raw_content.decode("utf-8", errors="replace")
    elif isinstance(raw_content, str):
        xml_text = raw_content
    else:
        raise ValueError("C-CDA content must be str or bytes.")

    xml_text = xml_text.strip()
    if not xml_text:
        raise ValueError("C-CDA XML content is empty.")

    head_upper = xml_text[:16384].upper()
    if "<!DOCTYPE" in head_upper or "<!ENTITY" in head_upper or "<! DOCTYPE" in head_upper or "<! ENTITY" in head_upper:
        raise ValueError(
            "Security violation: XML DOCTYPE or ENTITY declarations are forbidden (XXE protection)."
        )

    try:
        root = DET.fromstring(
            xml_text,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except DefusedXmlException as exc:
        raise ValueError(
            f"Security violation: XML DOCTYPE or ENTITY declarations are forbidden (XXE protection): {exc}"
        ) from exc
    except DET.ParseError as exc:
        raise ValueError(f"Invalid C-CDA XML document: {exc}") from exc

    if _local_name(root.tag) != "ClinicalDocument":
        raise ValueError(
            f"Invalid C-CDA root element '{_local_name(root.tag)}'; expected 'ClinicalDocument'."
        )

    clean_source = (source_name or "C-CDA Clinical Summary").strip()
    doc_date = _extract_document_date(root)

    staged_records: List[Dict[str, Any]] = []
    counts_by_type: Dict[str, int] = {}
    dates: List[str] = [doc_date]

    for elem in root.iter():
        if _local_name(elem.tag) != "section":
            continue

        classification = _classify_section(elem)
        if classification is None:
            continue

        rtype, section_cat = classification
        entries = [ch for ch in elem if _local_name(ch.tag) == "entry"]

        extracted_items: List[Dict[str, Any]] = []
        for entry in entries:
            extracted_items.extend(
                _extract_entry_details(entry, rtype=rtype, section_cat=section_cat, doc_date=doc_date)
            )

        # Fallback to narrative <text> items if no structured <entry> items extracted
        if not extracted_items:
            for ch in elem:
                if _local_name(ch.tag) == "text":
                    narrative = " ".join(t.strip() for t in ch.itertext() if t and t.strip())
                    if narrative:
                        extracted_items.append({
                            "entry_id": None,
                            "code": None,
                            "system": None,
                            "display": narrative[:200],
                            "raw_display": narrative[:200],
                            "value_num": None,
                            "value_unit": None,
                            "value_text": narrative,
                            "effective_iso": f"{doc_date}T00:00:00+00:00",
                            "effective_date": doc_date,
                            "section_category": section_cat,
                        })

        for idx, item in enumerate(extracted_items):
            eff_iso = item["effective_iso"]
            eff_date = item["effective_date"]
            dates.append(eff_date)
            source_display = f"From {clean_source}, {eff_date}"

            fhir_data: Dict[str, Any] = {
                "resourceType": rtype,
                "status": "final" if rtype == "Observation" else "active",
                "code": {
                    "coding": [
                        {
                            "system": item["system"] or "urn:oid:ccda",
                            "code": item["code"] or "unknown",
                            "display": item["raw_display"],
                        }
                    ],
                    "text": item["display"],
                },
                "effectiveDateTime": eff_iso,
                "meta": {
                    "source": clean_source,
                    "trust": "untrusted",
                },
                "_carefold_provenance": {
                    "source_name": clean_source,
                    "source_display": source_display,
                    "section": section_cat,
                    "trust": "untrusted",
                },
            }
            if item["value_num"] is not None:
                fhir_data["valueQuantity"] = {
                    "value": item["value_num"],
                    "unit": item["value_unit"] or "",
                }
            elif item["value_text"]:
                fhir_data["valueString"] = item["value_text"]

            digest = hashlib.sha256(
                json.dumps(fhir_data, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:16]
            source_id = item["entry_id"] or f"ccda:{rtype}:{section_cat}:{idx}:{digest}"

            staged_records.append({
                "resource_type": rtype,
                "source_id": source_id,
                "effective_at": eff_iso,
                "display": item["display"],
                "code": item["code"],
                "data": fhir_data,
                "source_display": source_display,
                "trust": "untrusted",
            })
            counts_by_type[rtype] = counts_by_type.get(rtype, 0) + 1

    sorted_dates = sorted(d for d in dates if d)
    date_range = {
        "min": sorted_dates[0] if sorted_dates else doc_date,
        "max": sorted_dates[-1] if sorted_dates else doc_date,
    }

    provenance_record: Dict[str, Any] = {
        "resource_type": "Provenance",
        "resourceType": "Provenance",
        "source_id": f"Provenance:ccda:{doc_date}",
        "effective_at": f"{doc_date}T00:00:00+00:00",
        "display": f"Provenance: From {clean_source}, {doc_date}",
        "code": "PROVENANCE",
        "data": {
            "resourceType": "Provenance",
            "recorded": datetime.now(timezone.utc).isoformat(),
            "agent": [{"who": {"display": clean_source}}],
            "text": {
                "status": "generated",
                "div": f"From {clean_source}, {doc_date}",
            },
        },
        "source_display": f"From {clean_source}, {doc_date}",
        "trust": "untrusted",
    }

    return {
        "format": "ccda",
        "source_name": clean_source,
        "records": staged_records,
        "provenance": provenance_record,
        "summary": {
            "total_records": len(staged_records),
            "counts_by_type": counts_by_type,
            "date_range": date_range,
            "source_name": clean_source,
        },
    }


__all__ = ["parse_ccda_xml"]
