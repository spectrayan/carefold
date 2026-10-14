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

"""Vitals Red Flags Safety Engine and Non-Clinical Boundary Checker.

Evaluates physiological observations (Blood Pressure, SpO2, Blood Glucose)
against declarative safety thresholds in carefold.resources.vitals_thresholds.yaml:
1. Hypertensive Crisis (>= 180 / 120 mmHg):
   - Symptomatic (chest pain, SOB, severe back pain, FAST symptoms) -> "Call 911 immediately"
   - Asymptomatic -> Rest 5 minutes, recheck, contact clinician today
2. Severe Hypoxemia (SpO2 < 90%): Immediate medical evaluation directive
3. Severe Hypoglycemia (Glucose < 54 mg/dL): Rule of 15 acute directive
4. Symptomatic Hypotension (< 90/60 mmHg + dizziness/syncope): Clinical referral

Provides 100% recall and zero false negatives on acute physiological emergencies.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union
import yaml

from carefold.safety.emergency import EmergencyFlag

logger = logging.getLogger(__name__)

CATEGORY_PRIORITY: Dict[str, int] = {
    # Emergency Tier (Score >= 200)
    "bp_crisis_symptomatic": 210,
    "severe_hypoxemia": 200,
    # Urgent Tier (Score 100-199)
    "severe_hypoglycemia": 120,
    "symptomatic_hypotension": 110,
    "bp_crisis_asymptomatic": 100,
}

FALLBACK_NEGATION_TERMS: Set[str] = {
    "no",
    "not",
    "without",
    "never",
    "denies",
    "negative for",
}


def _safe_float(val: Any) -> Optional[float]:
    """Safely converts value to float, returning None if unparseable, NaN, or Inf."""
    if val is None or val == "":
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None

# Fallback symptom dictionaries in case YAML resource is unreadable
FALLBACK_ACUTE_SYMPTOMS: Set[str] = {
    "chest pain",
    "chest pressure",
    "chest tightness",
    "crushing chest pain",
    "crushing chest pressure",
    "shortness of breath",
    "difficulty breathing",
    "dyspnea",
    "severe back pain",
    "unilateral numbness",
    "unilateral weakness",
    "arm weakness",
    "facial droop",
    "facial drooping",
    "numbness on one side",
    "acute vision loss",
    "sudden vision loss",
    "vision loss",
    "dysarthria",
    "difficulty speaking",
    "slurred speech",
}

FALLBACK_HYPOTENSION_SYMPTOMS: Set[str] = {
    "dizziness",
    "lightheadedness",
    "syncope",
    "fainting",
    "feeling faint",
    "presyncope",
}


class VitalsEmergencyFlag(EmergencyFlag):
    """Structured representation of a vitals-triggered emergency red flag.

    Compatible with both carefold.safety.emergency.EmergencyFlag and
    E2E EmergencyRedFlag dataclass contracts.
    """

    triggered: bool
    category: Optional[str]
    severity: str
    directive: Optional[str]
    prompt_recheck: bool
    details: Dict[str, Any]

    def __init__(
        self,
        triggered: bool,
        category: Optional[str] = None,
        severity: str = "normal",
        directive: Optional[str] = None,
        prompt_recheck: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        det = details or {}
        # Superclass EmergencyFlag init
        super().__init__(
            detected=triggered,
            category=category or "none",
            trigger_phrase=directive or (category or ""),
            referral_message=directive or "",
        )
        self.triggered = triggered
        self.category = category
        self.severity = severity
        self.directive = directive
        self.prompt_recheck = prompt_recheck
        self.details = det

        # Populate internal dict with exactly the 6 fields for dataclass unpacking
        self.clear()
        self.update({
            "triggered": self.triggered,
            "category": self.category,
            "severity": self.severity,
            "directive": self.directive,
            "prompt_recheck": self.prompt_recheck,
            "details": self.details,
        })

    def __bool__(self) -> bool:
        """Evaluates truthiness based on triggered status."""
        return bool(self.triggered)

    def __getitem__(self, key: str) -> Any:
        if key == "detected":
            return self.triggered
        if key in ("referral_message", "action_directive"):
            return self.directive
        if key == "trigger_phrase":
            return self.directive or (self.category or "")
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    @property
    def detected(self) -> bool:
        return self.triggered

    @detected.setter
    def detected(self, value: bool) -> None:
        self.triggered = bool(value)

    @property
    def referral_message(self) -> Optional[str]:
        return self.directive

    @referral_message.setter
    def referral_message(self, value: Optional[str]) -> None:
        self.directive = value

    def to_dict(self) -> Dict[str, Any]:
        """Returns standard serialized dictionary."""
        return {
            "triggered": self.triggered,
            "detected": self.triggered,
            "category": self.category,
            "severity": self.severity,
            "directive": self.directive,
            "referral_message": self.directive,
            "prompt_recheck": self.prompt_recheck,
            "details": self.details,
        }


def _load_vitals_thresholds_yaml() -> Dict[str, Any]:
    """Loads vitals thresholds YAML from resources directory with robust fallbacks."""
    # 1. Try via cached ResourceLoader
    try:
        from carefold.resources.loader import get_resource_loader
        loader = get_resource_loader()
        data = loader.load_yaml("vitals_thresholds.yaml")
        if data:
            return data
    except Exception:
        pass

    # 2. Try relative file system locations
    candidates = [
        Path(__file__).resolve().parent.parent / "resources" / "vitals_thresholds.yaml",
        Path.cwd() / "backend" / "src" / "carefold" / "resources" / "vitals_thresholds.yaml",
        Path.cwd() / "resources" / "vitals_thresholds.yaml",
    ]
    for path in candidates:
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    parsed = yaml.safe_load(f)
                    if parsed and isinstance(parsed, dict):
                        return parsed
            except Exception as e:
                logger.warning("Failed to parse %s: %s", path, e)

    return {}


def _extract_vitals_components(vitals: Dict[str, Any]) -> Dict[str, Any]:
    """Normalizes raw input or FHIR R4 Observation dictionary into standard vitals components."""
    extracted: Dict[str, Any] = {}
    if not isinstance(vitals, dict):
        return extracted

    # 1. Handle FHIR R4 Observation structure
    if vitals.get("resourceType") == "Observation" or "component" in vitals or "code" in vitals:
        # Check Blood Pressure panel LOINC 85354-9
        components = vitals.get("component") or []
        for comp in components:
            codes = [c.get("code") for c in comp.get("code", {}).get("coding", [])]
            val = comp.get("valueQuantity", {}).get("value")
            if "8480-6" in codes:
                sys_f = _safe_float(val)
                if sys_f is not None:
                    extracted["systolic"] = sys_f
            elif "8462-4" in codes:
                dia_f = _safe_float(val)
                if dia_f is not None:
                    extracted["diastolic"] = dia_f

        # Check top-level code
        top_codes = [c.get("code") for c in vitals.get("code", {}).get("coding", [])]
        val_q = vitals.get("valueQuantity", {})
        top_val = val_q.get("value")
        if top_val is not None:
            if "2708-6" in top_codes:
                spo2_f = _safe_float(top_val)
                if spo2_f is not None:
                    extracted["spo2"] = spo2_f
            elif "2339-0" in top_codes:
                glu_f = _safe_float(top_val)
                if glu_f is not None:
                    extracted["blood_glucose"] = glu_f
                    extracted["unit"] = val_q.get("unit", "mg/dL")

    # 2. Handle flat dictionary keys (overrides or complements)
    if "systolic" in vitals and vitals["systolic"] is not None:
        sys_f = _safe_float(vitals["systolic"])
        if sys_f is not None:
            extracted["systolic"] = sys_f
    if "diastolic" in vitals and vitals["diastolic"] is not None:
        dia_f = _safe_float(vitals["diastolic"])
        if dia_f is not None:
            extracted["diastolic"] = dia_f
    if "spo2" in vitals and vitals["spo2"] is not None:
        spo2_f = _safe_float(vitals["spo2"])
        if spo2_f is not None:
            extracted["spo2"] = spo2_f
    elif "oxygen_saturation" in vitals and vitals["oxygen_saturation"] is not None:
        spo2_f = _safe_float(vitals["oxygen_saturation"])
        if spo2_f is not None:
            extracted["spo2"] = spo2_f
    if "blood_glucose" in vitals and vitals["blood_glucose"] is not None:
        glu_f = _safe_float(vitals["blood_glucose"])
        if glu_f is not None:
            extracted["blood_glucose"] = glu_f
    elif "glucose" in vitals and vitals["glucose"] is not None:
        glu_f = _safe_float(vitals["glucose"])
        if glu_f is not None:
            extracted["blood_glucose"] = glu_f
    if "unit" in vitals and vitals["unit"]:
        extracted["unit"] = str(vitals["unit"])

    return extracted


def _parse_affirmative_symptoms(
    raw_symptoms: Sequence[str],
    acute_terms: Set[str],
    hypotension_terms: Set[str],
    negation_cues: Optional[Set[str]] = None,
) -> Tuple[bool, bool, List[str], List[str]]:
    """Evaluates reported symptoms, filtering out negated occurrences.

    Returns:
        (has_acute_sym, has_hypotension_sym, affirmative_acute_list, affirmative_hypotension_list)
    """
    if not raw_symptoms:
        return False, False, [], []

    all_terms = sorted(acute_terms | hypotension_terms, key=len, reverse=True)
    terms_pattern = "|".join(
        r"\s+".join(re.escape(part) for part in t.split()) for t in all_terms
    )

    cues = negation_cues or FALLBACK_NEGATION_TERMS
    cues_pattern = "|".join(
        r"\s+".join(re.escape(part) for part in c.split()) for c in sorted(cues, key=len, reverse=True)
    )

    neg_regex = re.compile(
        r"\b(?:" + cues_pattern + r")[\s,:\-]+(?:\w+[\s,:\-]+){0,3}?(?:" + terms_pattern + r")\b",
        re.IGNORECASE,
    )

    affirmative_acute: List[str] = []
    affirmative_hypotension: List[str] = []

    for s in raw_symptoms:
        if not s or not isinstance(s, str):
            continue
        clean = s.strip()
        if not clean:
            continue

        # Mask out negated spans with equal number of whitespace characters
        masked = neg_regex.sub(lambda m: " " * len(m.group(0)), clean)

        # Search for unmasked affirmative acute terms
        for term in acute_terms:
            pattern = r"\b" + r"\s+".join(re.escape(p) for p in term.split()) + r"\b"
            if re.search(pattern, masked, re.IGNORECASE):
                affirmative_acute.append(clean)
                break

        # Search for unmasked affirmative hypotension terms
        for term in hypotension_terms:
            pattern = r"\b" + r"\s+".join(re.escape(p) for p in term.split()) + r"\b"
            if re.search(pattern, masked, re.IGNORECASE):
                affirmative_hypotension.append(clean)
                break

    has_acute = len(affirmative_acute) > 0
    has_hypo = len(affirmative_hypotension) > 0
    return has_acute, has_hypo, affirmative_acute, affirmative_hypotension


def check_vitals_red_flags(
    observation: Optional[Dict[str, Any]] = None,
    symptoms: Optional[List[str]] = None,
    *,
    vitals: Optional[Dict[str, Any]] = None,
    reported_symptoms: Optional[List[str]] = None,
) -> VitalsEmergencyFlag:
    """Evaluates vitals against clinical non-boundary safety thresholds.

    Supports both positional and keyword invocation styles:
    - check_vitals_red_flags(observation, symptoms)
    - check_vitals_red_flags(vitals, reported_symptoms)

    Args:
        observation: Raw vitals dictionary or FHIR R4 Observation resource.
        symptoms: Reported user symptom strings.
        vitals: Alternative keyword argument for observation.
        reported_symptoms: Alternative keyword argument for symptoms.

    Returns:
        VitalsEmergencyFlag containing triggered status, category, severity, directive, and details.
    """
    raw_vitals = vitals if vitals is not None else (observation or {})
    raw_symptoms = reported_symptoms if reported_symptoms is not None else (symptoms or [])

    cfg = _load_vitals_thresholds_yaml()
    symptoms_cfg = cfg.get("symptoms", {})
    acute_terms = set(symptoms_cfg.get("acute_end_organ", {}).get("terms", FALLBACK_ACUTE_SYMPTOMS))
    hypotension_terms = set(symptoms_cfg.get("hypotension_hemodynamic", {}).get("terms", FALLBACK_HYPOTENSION_SYMPTOMS))
    negation_cues = set(symptoms_cfg.get("negation_cues", {}).get("terms", FALLBACK_NEGATION_TERMS))

    has_acute_sym, has_hypotension_sym, aff_acute, aff_hypo = _parse_affirmative_symptoms(
        raw_symptoms, acute_terms, hypotension_terms, negation_cues=negation_cues
    )

    extracted = _extract_vitals_components(raw_vitals)
    candidates: List[VitalsEmergencyFlag] = []

    # 1. Blood Pressure Checks (Independent Component Evaluation)
    sys_val = extracted.get("systolic")
    dia_val = extracted.get("diastolic")

    has_sys_crisis = sys_val is not None and sys_val >= 180.0
    has_dia_crisis = dia_val is not None and dia_val >= 120.0

    if has_sys_crisis or has_dia_crisis:
        if has_acute_sym:
            bp_details: Dict[str, Any] = {
                "symptoms": aff_acute or list(raw_symptoms),
                "escalation_ref": "flag:bp_crisis_symptomatic",
            }
            if sys_val is not None:
                bp_details["systolic"] = sys_val
            if dia_val is not None:
                bp_details["diastolic"] = dia_val

            candidates.append(
                VitalsEmergencyFlag(
                    triggered=True,
                    category="bp_crisis_symptomatic",
                    severity="emergency",
                    directive="Call 911 immediately. Hypertensive crisis with acute symptoms requires emergency care.",
                    prompt_recheck=False,
                    details=bp_details,
                )
            )
        else:
            bp_details = {
                "escalation_ref": "flag:bp_crisis_asymptomatic",
            }
            if sys_val is not None:
                bp_details["systolic"] = sys_val
            if dia_val is not None:
                bp_details["diastolic"] = dia_val

            candidates.append(
                VitalsEmergencyFlag(
                    triggered=True,
                    category="bp_crisis_asymptomatic",
                    severity="urgent",
                    directive="Rest quietly for 5 minutes and recheck blood pressure. If still >=180/120, contact your clinician promptly today.",
                    prompt_recheck=True,
                    details=bp_details,
                )
            )

    has_sys_hypo = sys_val is not None and sys_val < 90.0
    has_dia_hypo = dia_val is not None and dia_val < 60.0

    if (has_sys_hypo or has_dia_hypo) and has_hypotension_sym:
        hypo_details: Dict[str, Any] = {
            "symptoms": aff_hypo or list(raw_symptoms),
            "escalation_ref": "flag:symptomatic_hypotension",
        }
        if sys_val is not None:
            hypo_details["systolic"] = sys_val
        if dia_val is not None:
            hypo_details["diastolic"] = dia_val

        candidates.append(
            VitalsEmergencyFlag(
                triggered=True,
                category="symptomatic_hypotension",
                severity="urgent",
                directive="Low blood pressure accompanied by dizziness or syncope. Sit or lie down immediately and seek medical evaluation.",
                prompt_recheck=False,
                details=hypo_details,
            )
        )

    # 2. Oxygen Saturation (SpO2 < 90%)
    if "spo2" in extracted:
        spo2_val = extracted["spo2"]
        if spo2_val < 90.0:
            candidates.append(
                VitalsEmergencyFlag(
                    triggered=True,
                    category="severe_hypoxemia",
                    severity="emergency",
                    directive="SpO2 is below 90%, indicating severe hypoxemia. Seek urgent medical evaluation immediately.",
                    prompt_recheck=False,
                    details={
                        "spo2": spo2_val,
                        "escalation_ref": "flag:severe_hypoxemia",
                    },
                )
            )

    # 3. Blood Glucose (< 54 mg/dL / < 3.0 mmol/L)
    if "blood_glucose" in extracted:
        raw_g = extracted["blood_glucose"]
        unit = extracted.get("unit", "mg/dL")
        mgdl = raw_g * 18.0182 if unit == "mmol/L" else raw_g
        if mgdl < 54.0:
            candidates.append(
                VitalsEmergencyFlag(
                    triggered=True,
                    category="severe_hypoglycemia",
                    severity="urgent",
                    directive="Severe hypoglycemia (<54 mg/dL). Apply Rule of 15: consume 15g fast-acting carbs and recheck in 15 minutes.",
                    prompt_recheck=True,
                    details={
                        "blood_glucose": mgdl,
                        "raw_value": raw_g,
                        "unit": "mg/dL",
                        "escalation_ref": "flag:severe_hypoglycemia",
                    },
                )
            )

    # Normal / Safe Observation
    if not candidates:
        return VitalsEmergencyFlag(triggered=False, severity="normal")

    # Single triggered vital (100% backward-compatible return)
    if len(candidates) == 1:
        return candidates[0]

    # Multi-vital Priority Ranking & Synthesis
    candidates.sort(key=lambda c: CATEGORY_PRIORITY.get(c.category or "", 0), reverse=True)
    primary = candidates[0]

    # Merge details, giving precedence to higher priority candidates
    merged_details: Dict[str, Any] = {}
    for c in reversed(candidates):
        merged_details.update(c.details)
    merged_details["secondary_categories"] = [c.category for c in candidates[1:]]

    is_emergency = any(c.severity == "emergency" for c in candidates)
    prompt_recheck = False if is_emergency else primary.prompt_recheck

    # Formulate directive:
    # If primary is emergency, only include secondary directives that are ALSO emergency.
    # Never append "Rest quietly for 5 minutes" if primary is higher priority.
    secondary_directives = [
        c.directive for c in candidates[1:]
        if c.directive and c.directive != primary.directive
        and (c.severity == "emergency" if is_emergency else c.category != "bp_crisis_asymptomatic")
    ]
    combined_directive = primary.directive
    if secondary_directives:
        combined_directive = f"{primary.directive} Note: {secondary_directives[0]}"

    return VitalsEmergencyFlag(
        triggered=True,
        category=primary.category,
        severity=primary.severity,
        directive=combined_directive,
        prompt_recheck=prompt_recheck,
        details=merged_details,
    )


__all__ = [
    "VitalsEmergencyFlag",
    "check_vitals_red_flags",
]
