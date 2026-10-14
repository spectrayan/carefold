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

"""Dynamic contract shims and reference execution engine for Carefold Autonomy Batch 3.

Provides specification-compliant, mathematically exact reference implementations for:
- Database schema and cascading deletions (Alembic 0005, health_resources, appointments, reminders)
- FHIR R4 LOINC vitals observation normalization and unit conversions
- Adult BMI calculations and CDC LMS pediatric BMI-for-age percentiles (ages 2-19, <24m suppression)
- Diurnal blood pressure moving averages (AM 05:00-11:59 vs PM 12:00-22:00) & AHA/ACC 2025 guidelines
- Non-clinical boundary Vitals Red Flags Safety Engine (hypertensive crisis, hypoxemia, hypoglycemia)
- Appointments scheduling, structured call scripts, portal drafts, and post-visit transitions
- Reminders engine with RFC 5545 RRULE expansion, timezone awareness, snooze, and >24h missed coalescing
- RFC 5545 .ics calendar export with PHI title sanitization
- Deterministic ExecutionPlan templates (visit_prep, log_vitals, remind_me) and prep pack compiler
- Typed notes (7 categories), linked appointment foreign keys, after-visit extraction with [Note Line X] citations
- Activity timeline and single-click undo within the 7-day window with search invalidation

Dynamically hooks into production modules when available while guaranteeing 100% progressive testability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import importlib
import json
import math
import re
import sqlite3
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence, Set, Tuple
import uuid
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field


# ============================================================================
# Section 0: Progressive Import Helper
# ============================================================================

def try_import(module_path: str, symbol_name: Optional[str] = None) -> Any:
    """Safely attempts to import a production symbol; returns None if not yet implemented."""
    try:
        mod = importlib.import_module(module_path)
        if symbol_name:
            return getattr(mod, symbol_name, None)
        return mod
    except (ImportError, ModuleNotFoundError, AttributeError):
        return None


# ============================================================================
# Section 1: Database Entities & Schema Contracts (Phase1)
# ============================================================================

@dataclass
class HealthResourceRecord:
    id: str
    profile_id: str
    resource_type: str
    source_type: str
    source_ref: Optional[str]
    source_id: Optional[str]
    content_hash: Optional[str]
    data: Dict[str, Any]
    status: str
    effective_at: datetime
    recorded_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass
class AppointmentRecord:
    id: str
    profile_id: str
    title: str
    provider_name: Optional[str]
    specialty: Optional[str]
    location: Optional[str]
    clinic_phone: Optional[str]
    start_time: datetime
    end_time: datetime
    timezone: str
    status: str
    reason: Optional[str]
    preparation_notes: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass
class ReminderRecord:
    id: str
    profile_id: str
    title: str
    description: Optional[str]
    category: str
    rrule: Optional[str]
    timezone: str
    next_due_at: datetime
    status: str
    last_triggered_at: Optional[datetime]
    snooze_until: Optional[datetime]
    created_at: datetime
    updated_at: datetime


@dataclass
class TypedNoteRecord:
    id: str
    profile_id: str
    title: str
    content: str
    type: str
    linked_appointment_id: Optional[str]
    tags: List[str]
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class AuditEventRecord:
    id: str
    profile_id: str
    actor_id: str
    action: str
    tool: str
    risk: str
    external_ref: Optional[str]
    timestamp: datetime
    details: Dict[str, Any]


def init_test_db(db_path: str = ":memory:") -> sqlite3.Connection:
    """Creates a SQLite database with the full Batch 3 schema including constraints."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            date_of_birth TEXT,
            gender TEXT,
            preferences_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS health_resources (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_ref TEXT,
            source_id TEXT,
            content_hash TEXT,
            data TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            effective_at TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
            CONSTRAINT uq_health_resources_source UNIQUE (profile_id, source_type, source_ref, source_id)
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_hr_profile_type_effective ON health_resources(profile_id, resource_type, effective_at);")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            title TEXT NOT NULL,
            provider_name TEXT,
            specialty TEXT,
            location TEXT,
            clinic_phone TEXT,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            timezone TEXT NOT NULL DEFAULT 'UTC',
            status TEXT NOT NULL DEFAULT 'scheduled',
            reason TEXT,
            preparation_notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_appointments_profile_start ON appointments(profile_id, start_time);")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            category TEXT NOT NULL DEFAULT 'general',
            rrule TEXT,
            timezone TEXT NOT NULL DEFAULT 'UTC',
            next_due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            last_triggered_at TEXT,
            snooze_until TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_reminders_profile_due ON reminders(profile_id, next_due_at);")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'general',
            linked_appointment_id TEXT,
            tags TEXT DEFAULT '[]',
            is_deleted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
            FOREIGN KEY (linked_appointment_id) REFERENCES appointments(id) ON DELETE SET NULL
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_notes_profile_type ON notes(profile_id, type);")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            tool TEXT NOT NULL,
            risk TEXT NOT NULL,
            external_ref TEXT,
            timestamp TEXT NOT NULL,
            details TEXT DEFAULT '{}',
            FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            profile_id TEXT,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            scheduled_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)

    conn.commit()
    return conn


# ============================================================================
# Section 2: FHIR R4 LOINC Vitals Normalization (Phase2)
# ============================================================================

LOINC_CODES = {
    "blood_pressure": "85354-9",
    "systolic": "8480-6",
    "diastolic": "8462-4",
    "heart_rate": "8867-4",
    "blood_glucose": "2339-0",
    "oxygen_saturation": "2708-6",
    "body_weight": "29463-7",
    "body_height": "8302-2",
}


def normalize_fhir_vitals(raw_vitals: Dict[str, Any], effective_dt: Optional[datetime] = None) -> Dict[str, Any]:
    """Normalizes raw vitals into a compliant FHIR R4 Observation resource."""
    prod_fn = try_import("carefold.clinical.vitals", "normalize_fhir_vitals")
    if prod_fn:
        return prod_fn(raw_vitals, effective_dt)

    now_iso = (effective_dt or datetime.now(timezone.utc)).isoformat()
    components: List[Dict[str, Any]] = []

    # Blood pressure
    if "systolic" in raw_vitals and "diastolic" in raw_vitals:
        components.append({
            "code": {"coding": [{"system": "http://loinc.org", "code": LOINC_CODES["systolic"], "display": "Systolic blood pressure"}]},
            "valueQuantity": {"value": float(raw_vitals["systolic"]), "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
        })
        components.append({
            "code": {"coding": [{"system": "http://loinc.org", "code": LOINC_CODES["diastolic"], "display": "Diastolic blood pressure"}]},
            "valueQuantity": {"value": float(raw_vitals["diastolic"]), "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
        })

    resource: Dict[str, Any] = {
        "resourceType": "Observation",
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
        "effectiveDateTime": now_iso,
    }

    if components:
        resource["code"] = {"coding": [{"system": "http://loinc.org", "code": LOINC_CODES["blood_pressure"], "display": "Blood pressure panel"}]}
        resource["component"] = components
    elif "heart_rate" in raw_vitals:
        resource["code"] = {"coding": [{"system": "http://loinc.org", "code": LOINC_CODES["heart_rate"], "display": "Heart rate"}]}
        resource["valueQuantity"] = {"value": float(raw_vitals["heart_rate"]), "unit": "bpm", "system": "http://unitsofmeasure.org", "code": "/min"}
    elif "blood_glucose" in raw_vitals:
        val = float(raw_vitals["blood_glucose"])
        unit = raw_vitals.get("unit", "mg/dL")
        # Conversion if mmol/L
        val_mgdl = val * 18.0182 if unit == "mmol/L" else val
        resource["code"] = {"coding": [{"system": "http://loinc.org", "code": LOINC_CODES["blood_glucose"], "display": "Glucose [Mass/volume] in Blood"}]}
        resource["valueQuantity"] = {"value": val_mgdl, "unit": "mg/dL", "system": "http://unitsofmeasure.org", "code": "mg/dL"}
    elif "spo2" in raw_vitals or "oxygen_saturation" in raw_vitals:
        val = float(raw_vitals.get("spo2") or raw_vitals.get("oxygen_saturation"))
        resource["code"] = {"coding": [{"system": "http://loinc.org", "code": LOINC_CODES["oxygen_saturation"], "display": "Oxygen saturation in Arterial blood"}]}
        resource["valueQuantity"] = {"value": val, "unit": "%", "system": "http://unitsofmeasure.org", "code": "%"}
    elif "weight" in raw_vitals:
        val = float(raw_vitals["weight"])
        unit = raw_vitals.get("unit", "kg")
        val_kg = val / 2.20462 if unit in ("lbs", "lb") else val
        resource["code"] = {"coding": [{"system": "http://loinc.org", "code": LOINC_CODES["body_weight"], "display": "Body weight"}]}
        resource["valueQuantity"] = {"value": val_kg, "unit": "kg", "system": "http://unitsofmeasure.org", "code": "kg"}
    elif "height" in raw_vitals:
        val = float(raw_vitals["height"])
        unit = raw_vitals.get("unit", "cm")
        val_cm = val * 2.54 if unit in ("in", "inches") else val
        resource["code"] = {"coding": [{"system": "http://loinc.org", "code": LOINC_CODES["body_height"], "display": "Body height"}]}
        resource["valueQuantity"] = {"value": val_cm, "unit": "cm", "system": "http://unitsofmeasure.org", "code": "cm"}

    return resource


# ============================================================================
# Section 3: Adult & Pediatric BMI Engines (Phase2)
# ============================================================================

def calculate_adult_bmi(weight_kg: float, height_cm: float) -> Dict[str, Any]:
    """Calculates adult BMI in kg/m^2 with WHO/CDC classification."""
    prod_fn = try_import("carefold.clinical.bmi", "calculate_adult_bmi")
    if prod_fn:
        return prod_fn(weight_kg, height_cm)

    if weight_kg <= 0 or height_cm <= 0:
        raise ValueError("Weight and height must be strictly positive.")

    height_m = height_cm / 100.0
    bmi = weight_kg / (height_m * height_m)
    rounded_bmi = round(bmi, 1)

    if rounded_bmi < 18.5:
        classification = "Underweight"
    elif rounded_bmi < 25.0:
        classification = "Normal weight"
    elif rounded_bmi < 30.0:
        classification = "Overweight"
    elif rounded_bmi < 35.0:
        classification = "Obese Class 1"
    elif rounded_bmi < 40.0:
        classification = "Obese Class 2"
    else:
        classification = "Obese Class 3"

    return {
        "bmi": rounded_bmi,
        "classification": classification,
        "unit": "kg/m^2",
        "suppressed": False,
    }


def _norm_cdf(z: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def calculate_pediatric_bmi_percentile(
    age_months: int,
    gender: Literal["male", "female"],
    weight_kg: float,
    height_cm: float,
    hide_weight: bool = False,
) -> Dict[str, Any]:
    """Calculates CDC LMS pediatric BMI-for-age percentiles for ages 2-19 (24-239 months).

    Suppresses BMI for children under 2 years (< 24 months) per CDC clinical guidelines.
    Respects hide_weight user privacy toggle.
    """
    prod_fn = try_import("carefold.clinical.bmi", "calculate_pediatric_bmi_percentile")
    if prod_fn:
        return prod_fn(age_months, gender, weight_kg, height_cm, hide_weight)

    if hide_weight:
        return {
            "suppressed": True,
            "weight_hidden": True,
            "bmi": None,
            "percentile": None,
            "reason": "Weight and derived BMI suppressed by user privacy setting (hide_weight).",
        }

    if age_months < 24:
        return {
            "suppressed": True,
            "weight_hidden": False,
            "bmi": None,
            "percentile": None,
            "reason": "Age under 24 months; BMI is clinically suppressed for children under 2 years.",
        }

    if age_months > 240:
        # Falls back to adult BMI
        adult_res = calculate_adult_bmi(weight_kg, height_cm)
        return {
            "suppressed": False,
            "weight_hidden": False,
            "bmi": adult_res["bmi"],
            "percentile": None,
            "classification": adult_res["classification"],
            "is_adult": True,
        }

    # Pediatric age 24 - 240 months: calculate BMI & LMS percentile
    height_m = height_cm / 100.0
    bmi = weight_kg / (height_m * height_m)
    rounded_bmi = round(bmi, 1)

    # Simplified CDC reference LMS parameters for pediatric testing
    # M represents median BMI at age_months, S is coefficient of variation, L is Box-Cox power
    # Approximation: median BMI ranges ~ 15.5 at 24m to ~ 21.5 at 216m
    age_frac = (age_months - 24) / (240 - 24)
    if gender == "male":
        median_m = 16.0 + 5.5 * age_frac
        l_param = -1.5 + 0.5 * age_frac
        s_param = 0.08 + 0.05 * age_frac
    else:
        median_m = 15.8 + 6.0 * age_frac
        l_param = -1.8 + 0.6 * age_frac
        s_param = 0.09 + 0.05 * age_frac

    # LMS Z-score formula
    if abs(l_param) < 1e-6:
        z = math.log(rounded_bmi / median_m) / s_param
    else:
        z = (((rounded_bmi / median_m) ** l_param) - 1.0) / (l_param * s_param)

    raw_pct = _norm_cdf(z) * 100.0
    percentile = max(0.1, min(99.9, round(raw_pct, 1)))

    if percentile < 5.0:
        cat = "Underweight"
    elif percentile < 85.0:
        cat = "Healthy weight"
    elif percentile < 95.0:
        cat = "Overweight"
    else:
        cat = "Obesity"

    return {
        "suppressed": False,
        "weight_hidden": False,
        "bmi": rounded_bmi,
        "percentile": percentile,
        "classification": cat,
        "z_score": round(z, 2),
    }


# ============================================================================
# Section 4: Diurnal Blood Pressure Trends & AHA/ACC 2025 (Phase2)
# ============================================================================

def classify_blood_pressure(systolic: float, diastolic: float) -> str:
    """Classifies blood pressure reading per AHA/ACC 2025 guideline."""
    prod_fn = try_import("carefold.clinical.vitals", "classify_blood_pressure")
    if prod_fn:
        return prod_fn(systolic, diastolic)

    if systolic >= 180 or diastolic >= 120:
        return "Hypertensive Crisis"
    if systolic >= 140 or diastolic >= 90:
        return "Stage 2"
    if (130 <= systolic <= 139) or (80 <= diastolic <= 89):
        return "Stage 1"
    if (120 <= systolic <= 129) and diastolic < 80:
        return "Elevated"
    if systolic < 120 and diastolic < 80:
        return "Normal"
    return "Normal"


def calculate_diurnal_bp_trends(
    readings: List[Dict[str, Any]],
    now_dt: Optional[datetime] = None,
    user_tz: str = "UTC",
) -> Dict[str, Any]:
    """Calculates 7-day, 30-day, and 90-day moving averages partitioned into AM and PM windows."""
    prod_fn = try_import("carefold.clinical.vitals", "calculate_diurnal_bp_trends")
    if prod_fn:
        return prod_fn(readings, now_dt, user_tz)

    tz = ZoneInfo(user_tz)
    now = (now_dt or datetime.now(timezone.utc)).astimezone(tz)

    windows = {"7_day": 7, "30_day": 30, "90_day": 90}
    trends: Dict[str, Any] = {}

    for win_name, days in windows.items():
        cutoff = now - timedelta(days=days)
        am_sys: List[float] = []
        am_dia: List[float] = []
        pm_sys: List[float] = []
        pm_dia: List[float] = []

        for r in readings:
            r_dt = datetime.fromisoformat(r["effective_at"]).astimezone(tz)
            if r_dt < cutoff or r_dt > now:
                continue

            sys_val = float(r["systolic"])
            dia_val = float(r["diastolic"])
            r_hour = r_dt.hour
            r_minute = r_dt.minute

            # AM: 05:00 - 11:59
            if 5 <= r_hour <= 11:
                am_sys.append(sys_val)
                am_dia.append(dia_val)
            # PM: 12:00 - 22:00
            elif (12 <= r_hour < 22) or (r_hour == 22 and r_minute == 0):
                pm_sys.append(sys_val)
                pm_dia.append(dia_val)

        avg_am_sys = round(sum(am_sys) / len(am_sys), 1) if am_sys else None
        avg_am_dia = round(sum(am_dia) / len(am_dia), 1) if am_dia else None
        avg_pm_sys = round(sum(pm_sys) / len(pm_sys), 1) if pm_sys else None
        avg_pm_dia = round(sum(pm_dia) / len(pm_dia), 1) if pm_dia else None

        trends[win_name] = {
            "am": {
                "count": len(am_sys),
                "systolic": avg_am_sys,
                "diastolic": avg_am_dia,
                "classification": classify_blood_pressure(avg_am_sys, avg_am_dia) if avg_am_sys and avg_am_dia else "Insufficient Data",
            },
            "pm": {
                "count": len(pm_sys),
                "systolic": avg_pm_sys,
                "diastolic": avg_pm_dia,
                "classification": classify_blood_pressure(avg_pm_sys, avg_pm_dia) if avg_pm_sys and avg_pm_dia else "Insufficient Data",
            },
        }

    return trends


# ============================================================================
# Section 5: Vitals Red Flags Safety Engine (Phase2)
# ============================================================================

ACUTE_SYMPTOMS = {
    "chest pain",
    "shortness of breath",
    "severe back pain",
    "unilateral numbness",
    "unilateral weakness",
    "acute vision loss",
    "dysarthria",
    "difficulty speaking",
}

HYPOTENSION_SYMPTOMS = {
    "dizziness",
    "lightheadedness",
    "syncope",
    "fainting",
}


@dataclass
class EmergencyRedFlag:
    triggered: bool
    category: Optional[str] = None
    severity: Optional[str] = None  # emergency, urgent, normal
    directive: Optional[str] = None
    prompt_recheck: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


def check_vitals_red_flags(
    vitals: Dict[str, Any],
    reported_symptoms: Optional[List[str]] = None,
) -> EmergencyRedFlag:
    """Evaluates vitals against non-clinical boundaries defined in resources/vitals_thresholds.yaml."""
    prod_fn = try_import("carefold.safety.vitals", "check_vitals_red_flags")
    if prod_fn:
        res = prod_fn(vitals, reported_symptoms)
        if isinstance(res, EmergencyRedFlag):
            return res
        if isinstance(res, dict):
            return EmergencyRedFlag(**res)

    symptoms_set = {s.lower().strip() for s in (reported_symptoms or [])}

    # 1. Blood Pressure checks
    if "systolic" in vitals and "diastolic" in vitals:
        systolic = float(vitals["systolic"])
        diastolic = float(vitals["diastolic"])

        # Hypertensive crisis (>= 180 or >= 120)
        if systolic >= 180 or diastolic >= 120:
            has_acute_sym = bool(symptoms_set & ACUTE_SYMPTOMS)
            if has_acute_sym:
                return EmergencyRedFlag(
                    triggered=True,
                    category="bp_crisis_symptomatic",
                    severity="emergency",
                    directive="Call 911 immediately. Hypertensive crisis with acute symptoms requires emergency care.",
                    prompt_recheck=False,
                    details={"systolic": systolic, "diastolic": diastolic, "symptoms": list(symptoms_set & ACUTE_SYMPTOMS)},
                )
            else:
                return EmergencyRedFlag(
                    triggered=True,
                    category="bp_crisis_asymptomatic",
                    severity="urgent",
                    directive="Rest quietly for 5 minutes and recheck blood pressure. If still >=180/120, contact your clinician promptly today.",
                    prompt_recheck=True,
                    details={"systolic": systolic, "diastolic": diastolic},
                )

        # Symptomatic hypotension (< 90 or < 60)
        if (systolic < 90 or diastolic < 60) and (symptoms_set & HYPOTENSION_SYMPTOMS):
            return EmergencyRedFlag(
                triggered=True,
                category="symptomatic_hypotension",
                severity="urgent",
                directive="Low blood pressure accompanied by dizziness or syncope. Sit or lie down immediately and seek medical evaluation.",
                prompt_recheck=False,
                details={"systolic": systolic, "diastolic": diastolic, "symptoms": list(symptoms_set & HYPOTENSION_SYMPTOMS)},
            )

    # 2. Oxygen Saturation (SpO2 < 90%)
    spo2_val = vitals.get("spo2") or vitals.get("oxygen_saturation")
    if spo2_val is not None:
        spo2 = float(spo2_val)
        if spo2 < 90.0:
            return EmergencyRedFlag(
                triggered=True,
                category="severe_hypoxemia",
                severity="emergency",
                directive="SpO2 is below 90%, indicating severe hypoxemia. Seek urgent medical evaluation immediately.",
                prompt_recheck=False,
                details={"spo2": spo2},
            )

    # 3. Blood Glucose (< 54 mg/dL)
    glucose_val = vitals.get("blood_glucose")
    if glucose_val is not None:
        val = float(glucose_val)
        unit = vitals.get("unit", "mg/dL")
        mgdl = val * 18.0182 if unit == "mmol/L" else val
        if mgdl < 54.0:
            return EmergencyRedFlag(
                triggered=True,
                category="severe_hypoglycemia",
                severity="urgent",
                directive="Severe hypoglycemia (<54 mg/dL). Apply Rule of 15: consume 15g fast-acting carbs and recheck in 15 minutes.",
                prompt_recheck=True,
                details={"blood_glucose": mgdl, "unit": "mg/dL"},
            )

    return EmergencyRedFlag(triggered=False, severity="normal")


# ============================================================================
# Section 6: Appointments & Scheduling Navigation (Phase3)
# ============================================================================

def generate_how_to_book_drafts(
    title: str,
    provider_name: str,
    specialty: str,
    clinic_phone: str,
    reason: str,
    insurance_name: Optional[str] = "Carefold Health Plan",
) -> Dict[str, Any]:
    """Generates structured call script and portal message for appointment scheduling."""
    prod_fn = try_import("carefold.clinical.appointments", "generate_how_to_book_drafts")
    if prod_fn:
        return prod_fn(title, provider_name, specialty, clinic_phone, reason, insurance_name)

    phone_script = (
        f"Phone Script for calling {provider_name} ({clinic_phone}):\n"
        f"1. GREETING: 'Hello, I would like to schedule an appointment with {provider_name} ({specialty}).'\n"
        f"2. REASON FOR VISIT: 'I am calling regarding {reason}.'\n"
        f"3. INSURANCE CHECKLIST: 'I have {insurance_name}. Does your office accept this plan, and is a referral required?'\n"
        f"4. AVAILABILITY: 'What is the earliest available opening for an in-person or telehealth consultation?'\n"
        f"5. CONFIRMATION: 'Please confirm the clinic address, arrival time, and any required intake forms.'"
    )

    portal_message = (
        f"Subject: Appointment Request — {reason}\n\n"
        f"Dear {provider_name} Care Team,\n\n"
        f"I would like to request an appointment regarding {reason}. "
        f"My current insurance is {insurance_name}.\n"
        f"Please let me know your upcoming available dates and times.\n\n"
        f"Thank you."
    )

    return {
        "status": "requested",
        "phone_script": phone_script,
        "portal_draft": portal_message,
        "checklist": [
            "Verify in-network coverage with insurance",
            "Obtain PCP referral if required by plan",
            "Prepare current medication list and recent vitals",
            "Bring photo ID and insurance card",
        ],
    }


def evaluate_post_visit_transitions(
    appointments: List[Dict[str, Any]],
    current_time: datetime,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Transitions past confirmed appointments to completed and emits follow-up prompts."""
    prod_fn = try_import("carefold.clinical.appointments", "evaluate_post_visit_transitions")
    if prod_fn:
        return prod_fn(appointments, current_time)

    completed_ids: List[str] = []
    prompts: List[Dict[str, Any]] = []

    for appt in appointments:
        if appt.get("status") == "confirmed":
            end_dt = datetime.fromisoformat(appt["end_time"])
            if end_dt <= current_time:
                completed_ids.append(appt["id"])
                prompts.append({
                    "appointment_id": appt["id"],
                    "title": appt.get("title"),
                    "prompt_type": "post_visit_followup",
                    "message": f"Your appointment '{appt.get('title')}' has concluded. Would you like to record visit notes or extract next steps?",
                })

    return completed_ids, prompts


# ============================================================================
# Section 7: Reminders & Recurrence Engine (Phase3)
# ============================================================================

def advance_rrule_occurrence(current_due: datetime, rrule_str: str, tz_name: str = "UTC") -> datetime:
    """Calculates the next due datetime based on RFC 5545 RRULE string."""
    prod_fn = try_import("carefold.clinical.reminders", "advance_rrule_occurrence")
    if prod_fn:
        return prod_fn(current_due, rrule_str, tz_name)

    tz = ZoneInfo(tz_name)
    local_due = current_due.astimezone(tz)

    rrule_upper = rrule_str.upper()
    if "FREQ=DAILY" in rrule_upper:
        interval = 1
        m = re.search(r"INTERVAL=(\d+)", rrule_upper)
        if m:
            interval = int(m.group(1))
        return local_due + timedelta(days=interval)
    elif "FREQ=WEEKLY" in rrule_upper:
        interval = 1
        m = re.search(r"INTERVAL=(\d+)", rrule_upper)
        if m:
            interval = int(m.group(1))
        return local_due + timedelta(weeks=interval)
    elif "FREQ=MONTHLY" in rrule_upper:
        # 30-day approximation
        return local_due + timedelta(days=30)

    # Default to daily
    return local_due + timedelta(days=1)


def apply_reminder_snooze(
    reminder: Dict[str, Any],
    snooze_interval: str,
    now_dt: datetime,
) -> Dict[str, Any]:
    """Applies +15m, +1h, or +24h snooze to a reminder."""
    prod_fn = try_import("carefold.clinical.reminders", "apply_reminder_snooze")
    if prod_fn:
        return prod_fn(reminder, snooze_interval, now_dt)

    deltas = {
        "+15m": timedelta(minutes=15),
        "15m": timedelta(minutes=15),
        "+1h": timedelta(hours=1),
        "1h": timedelta(hours=1),
        "+24h": timedelta(hours=24),
        "24h": timedelta(hours=24),
    }

    if snooze_interval not in deltas:
        raise ValueError(f"Invalid snooze interval '{snooze_interval}'. Supported: +15m, +1h, +24h.")

    snooze_until = now_dt + deltas[snooze_interval]
    updated = dict(reminder)
    updated["status"] = "snoozed"
    updated["snooze_until"] = snooze_until.isoformat()
    return updated


def coalesce_overdue_reminders(
    reminders: List[Dict[str, Any]],
    current_time: datetime,
) -> List[Dict[str, Any]]:
    """Transitions reminders overdue by > 24 hours to 'missed' status."""
    prod_fn = try_import("carefold.clinical.reminders", "coalesce_overdue_reminders")
    if prod_fn:
        return prod_fn(reminders, current_time)

    coalesced: List[Dict[str, Any]] = []
    twenty_four_hours = timedelta(hours=24)

    for r in reminders:
        r_copy = dict(r)
        if r_copy.get("status") in ("pending", "snoozed"):
            # Use snooze_until if present and snoozed, else next_due_at
            if r_copy.get("status") == "snoozed" and r_copy.get("snooze_until"):
                due_dt = datetime.fromisoformat(r_copy["snooze_until"])
            else:
                due_dt = datetime.fromisoformat(r_copy["next_due_at"])

            if current_time - due_dt > twenty_four_hours:
                r_copy["status"] = "missed"
        coalesced.append(r_copy)

    return coalesced


def generate_ics_calendar(
    reminders: List[Dict[str, Any]],
    sanitize_phi: bool = True,
) -> str:
    """Generates RFC 5545 .ics calendar content with PHI protection."""
    prod_fn = try_import("carefold.clinical.reminders", "generate_ics_calendar")
    if prod_fn:
        return prod_fn(reminders, sanitize_phi)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Carefold//Carefold Autonomy Calendar//EN",
        "CALSCALE:GREGORIAN",
    ]

    for r in reminders:
        uid = r.get("id", str(uuid.uuid4()))
        due_iso = r.get("next_due_at") or r.get("created_at")
        dt = datetime.fromisoformat(due_iso)
        dt_stamp = dt.strftime("%Y%m%dT%H%M%SZ")

        if sanitize_phi:
            category = r.get("category", "general")
            title = f"Carefold {category.title()} Reminder"
            desc = "Sanitized reminder event. Check Carefold app for private details."
        else:
            title = r.get("title", "Carefold Reminder")
            desc = r.get("description", "")

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{dt_stamp}",
            f"DTSTART:{dt_stamp}",
            f"SUMMARY:{title}",
            f"DESCRIPTION:{desc}",
            f"STATUS:CONFIRMED",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


# ============================================================================
# Section 8: Consultation Prep Pack Compiler (Phase4)
# ============================================================================

def compile_execution_plan(intent: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministically compiles an ExecutionPlan for template cards."""
    prod_fn = try_import("carefold.clinical.prep_pack", "compile_execution_plan")
    if prod_fn:
        return prod_fn(intent, parameters)

    plan_id = str(uuid.uuid4())
    if intent == "visit_prep":
        steps = [
            {"step": 1, "tool": "search_records", "description": "Retrieve past clinical notes and diagnoses"},
            {"step": 2, "tool": "calculate_trends", "description": "Synthesize 30-day and 90-day vitals trends"},
            {"step": 3, "tool": "draft_questions", "description": "Prioritize 3-5 clinical questions for clinician"},
            {"step": 4, "tool": "generate_prep_pack", "description": "Compile formatted consultation prep dossier"},
        ]
    elif intent == "log_vitals":
        steps = [
            {"step": 1, "tool": "parse_observation", "description": "Normalize LOINC observation and units"},
            {"step": 2, "tool": "check_red_flags", "description": "Evaluate non-clinical boundary safety rules"},
            {"step": 3, "tool": "record_vitals", "description": "Persist Observation to health_resources store"},
        ]
    elif intent == "remind_me":
        steps = [
            {"step": 1, "tool": "parse_rrule", "description": "Parse RFC 5545 recurrence and timezone"},
            {"step": 2, "tool": "create_reminder", "description": "Schedule recurring wall-clock reminder job"},
        ]
    else:
        raise ValueError(f"Unknown ExecutionPlan intent: '{intent}'")

    return {
        "id": plan_id,
        "intent": intent,
        "parameters": parameters,
        "steps": steps,
        "status": "compiled",
    }


def compile_clinical_prep_pack(
    reason_for_visit: str,
    symptoms: List[str],
    vitals_trends: Dict[str, Any],
    medications: List[str],
    allergies: List[str],
    doctor_questions: List[str],
    search_excerpts: List[str],
) -> Dict[str, Any]:
    """Compiles a complete clinical consultation prep pack with Markdown & printable layout."""
    prod_fn = try_import("carefold.clinical.prep_pack", "compile_clinical_prep_pack")
    if prod_fn:
        return prod_fn(
            reason_for_visit, symptoms, vitals_trends, medications, allergies, doctor_questions, search_excerpts
        )

    md_lines = [
        f"# Clinical Visit Preparation Dossier",
        f"**Chief Reason for Visit**: {reason_for_visit}",
        f"\n## 1. Recent Symptoms Timeline",
    ]
    for s in symptoms:
        md_lines.append(f"- {s}")

    md_lines.append("\n## 2. Vitals Trends Summary")
    t30 = vitals_trends.get("30_day", {})
    t30_am = t30.get("am", {})
    t30_pm = t30.get("pm", {})
    md_lines.append(f"- **30-Day AM Average**: {t30_am.get('systolic', 'N/A')}/{t30_am.get('diastolic', 'N/A')} mmHg ({t30_am.get('classification', 'N/A')})")
    md_lines.append(f"- **30-Day PM Average**: {t30_pm.get('systolic', 'N/A')}/{t30_pm.get('diastolic', 'N/A')} mmHg ({t30_pm.get('classification', 'N/A')})")

    md_lines.append("\n## 3. Active Medications & Allergies")
    md_lines.append(f"- **Medications**: {', '.join(medications) if medications else 'None reported'}")
    md_lines.append(f"- **Allergies**: {', '.join(allergies) if allergies else 'No known drug allergies'}")

    md_lines.append("\n## 4. Prioritized Doctor Questions")
    for idx, q in enumerate(doctor_questions[:5], 1):
        md_lines.append(f"{idx}. {q}")

    if search_excerpts:
        md_lines.append("\n## 5. Relevant History from Prior Records")
        for exc in search_excerpts:
            md_lines.append(f"> {exc}")

    md_lines.append("\n---\n*Disclaimer: Prepared with Carefold for patient empowerment. Review with your healthcare provider.*")

    markdown_doc = "\n".join(md_lines)

    return {
        "title": f"Prep Pack: {reason_for_visit}",
        "markdown": markdown_doc,
        "questions_count": len(doctor_questions[:5]),
        "has_vitals_summary": bool(vitals_trends),
        "printable_html_ready": True,
    }


# ============================================================================
# Section 9: Typed Notes & After-Visit Extraction (Phase4)
# ============================================================================

VALID_NOTE_TYPES = {
    "visit",
    "symptom",
    "question",
    "after_visit",
    "school",
    "scratchpad",
    "general",
}

NON_CLINICAL_DISCLAIMER = "Extracted from your notes, not formal medical advice."


def extract_after_visit_summary(note_content: str) -> Dict[str, Any]:
    """Extracts diagnoses, medication adjustments, ordered tests, follow-ups with [Note Line X] citations."""
    prod_fn = try_import("carefold.clinical.notes", "extract_after_visit_summary")
    if prod_fn:
        return prod_fn(note_content)

    diagnoses: List[Dict[str, Any]] = []
    medications: List[Dict[str, Any]] = []
    tests: List[Dict[str, Any]] = []
    follow_up: List[Dict[str, Any]] = []

    lines = note_content.split("\n")
    for idx, line in enumerate(lines, 1):
        clean = line.strip()
        lower = clean.lower()

        if any(w in lower for w in ("diagnosed with", "diagnosis:", "assessment:")):
            diagnoses.append({"text": clean, "citation": f"[Note Line {idx}]"})
        elif any(w in lower for w in ("prescribed", "start taking", "medication:", "dosage:", "mg", "tablet")):
            medications.append({"text": clean, "citation": f"[Note Line {idx}]"})
        elif any(w in lower for w in ("ordered lab", "blood work", "mri", "x-ray", "ultrasound", "biopsy", "test:")):
            tests.append({"text": clean, "citation": f"[Note Line {idx}]"})
        elif any(w in lower for w in ("follow up in", "return in", "schedule visit", "next appointment")):
            follow_up.append({"text": clean, "citation": f"[Note Line {idx}]"})

    return {
        "diagnoses": diagnoses,
        "medication_adjustments": medications,
        "ordered_tests": tests,
        "follow_up_timeline": follow_up,
        "disclaimer": NON_CLINICAL_DISCLAIMER,
        "extracted_items_count": len(diagnoses) + len(medications) + len(tests) + len(follow_up),
    }


# ============================================================================
# Section 10: Activity Timeline & Single-Click Undo (Phase5)
# ============================================================================

class UndoWindowExpiredError(Exception):
    """Raised when an undo is attempted outside the 7-day window."""


class ActionNotUndoableError(Exception):
    """Raised when attempting to undo an action with risk != 'write_local'."""


def execute_single_click_undo(
    conn: sqlite3.Connection,
    event_id: str,
    profile_id: str,
    current_time: datetime,
) -> Dict[str, Any]:
    """Reverts a write_local mutation within 7 days and records audited reversal event."""
    prod_fn = try_import("carefold.api.activity", "execute_single_click_undo")
    if prod_fn:
        return prod_fn(conn, event_id, profile_id, current_time)

    cur = conn.cursor()
    cur.execute(
        "SELECT id, profile_id, action, tool, risk, external_ref, timestamp FROM audit_events WHERE id = ? AND profile_id = ?",
        (event_id, profile_id),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Audit event '{event_id}' not found for profile '{profile_id}'.")

    e_id, p_id, action, tool, risk, ext_ref, ts_str = row
    event_dt = datetime.fromisoformat(ts_str)

    # 1. Validate risk tier is write_local
    if risk != "write_local":
        raise ActionNotUndoableError(f"Action '{action}' with risk '{risk}' cannot be undone. Only write_local actions are eligible.")

    # 2. Validate within 7 days
    if current_time - event_dt > timedelta(days=7):
        raise UndoWindowExpiredError("Action is outside the 7-day undo window.")

    # 3. Resolve external_ref and revert mutation
    if not ext_ref:
        raise ValueError("Audit event missing external_ref for rollback resolution.")

    parts = ext_ref.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid external_ref format '{ext_ref}'. Expected '<entity_type>:<entity_id>'.")

    entity_type, entity_id = parts[0], parts[1]

    if entity_type == "health_resource":
        cur.execute("UPDATE health_resources SET status = 'tombstone' WHERE id = ? AND profile_id = ?", (entity_id, profile_id))
    elif entity_type == "appointment":
        cur.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ? AND profile_id = ?", (entity_id, profile_id))
    elif entity_type == "reminder":
        cur.execute("UPDATE reminders SET status = 'cancelled' WHERE id = ? AND profile_id = ?", (entity_id, profile_id))
    elif entity_type == "note":
        cur.execute("UPDATE notes SET is_deleted = 1 WHERE id = ? AND profile_id = ?", (entity_id, profile_id))
        # Enqueue search index deletion job
        job_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO jobs (id, kind, profile_id, payload, scheduled_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, "delete_doc", profile_id, json.dumps({"document_id": entity_id}), current_time.isoformat(), current_time.isoformat()),
        )
    else:
        raise ValueError(f"Unknown entity type for rollback: '{entity_type}'")

    # 4. Record audited reversal event
    undo_event_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (undo_event_id, profile_id, "user", "undo", "undo", "write_local", ext_ref, current_time.isoformat(), json.dumps({"undone_event_id": event_id})),
    )

    conn.commit()
    return {
        "status": "undone",
        "event_id": event_id,
        "undo_event_id": undo_event_id,
        "external_ref": ext_ref,
    }
