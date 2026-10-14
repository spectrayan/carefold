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

"""Opaque-box E2E test suite for Carefold Autonomy Batch 3 ("Organiser" MVP).

Implements the 4-tier testing methodology per TEST_INFRA.md and PROJECT.md:
- Tier 1: Feature Coverage (>=5 tests per feature group across all inventoried features).
- Tier 2: Boundary & Corner Cases (>=5 per feature for extreme BP, SpO2, glucose, pediatric BMI, snooze, coalescing, undo).
- Tier 3: Cross-Feature Combinations (pairwise interactions across vitals, prep packs, appointments, notes, reminders, undo).
- Tier 4: Real-World Clinical Workload Scenarios (consultation journey, hypertension tracking, pediatric well-child, diabetic crisis).

Adheres to Progressive Testability and Zero Mock production policy.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
from typing import Any, Dict, List
import uuid
from zoneinfo import ZoneInfo

import pytest

from tests.e2e.contracts_clinical_domain import (
    ACUTE_SYMPTOMS,
    HYPOTENSION_SYMPTOMS,
    LOINC_CODES,
    NON_CLINICAL_DISCLAIMER,
    VALID_NOTE_TYPES,
    ActionNotUndoableError,
    EmergencyRedFlag,
    UndoWindowExpiredError,
    advance_rrule_occurrence,
    apply_reminder_snooze,
    calculate_adult_bmi,
    calculate_diurnal_bp_trends,
    calculate_pediatric_bmi_percentile,
    check_vitals_red_flags,
    classify_blood_pressure,
    coalesce_overdue_reminders,
    compile_clinical_prep_pack,
    compile_execution_plan,
    evaluate_post_visit_transitions,
    execute_single_click_undo,
    extract_after_visit_summary,
    generate_how_to_book_drafts,
    generate_ics_calendar,
    init_test_db,
    normalize_fhir_vitals,
)


# ============================================================================
# Pytest Fixtures
# ============================================================================

@pytest.fixture
def test_db() -> sqlite3.Connection:
    """Provides an isolated, in-memory SQLite database with foreign keys enabled."""
    conn = init_test_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def sample_profile(test_db: sqlite3.Connection) -> Dict[str, Any]:
    """Inserts and returns a test patient profile."""
    prof_id = f"prof-{uuid.uuid4().hex[:8]}"
    user_id = f"user-{uuid.uuid4().hex[:8]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    cur = test_db.cursor()
    cur.execute(
        "INSERT INTO profiles (id, user_id, display_name, date_of_birth, gender, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (prof_id, user_id, "Alex Morgan", "1985-06-15", "female", now_iso, now_iso),
    )
    test_db.commit()
    return {"id": prof_id, "user_id": user_id, "display_name": "Alex Morgan"}


# ============================================================================
# TIER 1: FEATURE COVERAGE (F-02 through F-46)
# ============================================================================

class TestTier1DatabaseAndModels:
    """Tier 1: Database persistence, schema constraints, and cascading deletion (F-02 to F-08)."""

    def test_t1_health_resources_unique_constraint_enforcement(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 3: Unique constraint (profile_id, source_type, source_ref, source_id) prevents duplicates."""
        prof_id = sample_profile["id"]
        now = datetime.now(timezone.utc).isoformat()
        cur = test_db.cursor()

        # Insert first record
        r1_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO health_resources (id, profile_id, resource_type, source_type, source_ref, source_id, data, effective_at, recorded_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (r1_id, prof_id, "observation", "device", "omron_bp", "reading_001", "{}", now, now, now, now),
        )
        test_db.commit()

        # Duplicate insert must fail constraint
        r2_id = str(uuid.uuid4())
        with pytest.raises(sqlite3.IntegrityError):
            cur.execute(
                "INSERT INTO health_resources (id, profile_id, resource_type, source_type, source_ref, source_id, data, effective_at, recorded_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (r2_id, prof_id, "observation", "device", "omron_bp", "reading_001", "{}", now, now, now, now),
            )

    def test_t1_appointments_table_persistence_and_fields(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 4: Appointments table persistence with all required metadata fields."""
        prof_id = sample_profile["id"]
        appt_id = str(uuid.uuid4())
        start = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=2, hours=1)).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        cur = test_db.cursor()

        cur.execute(
            "INSERT INTO appointments (id, profile_id, title, provider_name, specialty, location, clinic_phone, start_time, end_time, timezone, status, reason, preparation_notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (appt_id, prof_id, "Cardiology Consult", "Dr. Vance", "Cardiology", "Heart Center Room 302", "555-0192", start, end, "America/New_York", "scheduled", "Palpitations", "Fast 4h before", now, now),
        )
        test_db.commit()

        cur.execute("SELECT title, provider_name, specialty, status FROM appointments WHERE id = ?", (appt_id,))
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "Cardiology Consult"
        assert row[1] == "Dr. Vance"
        assert row[2] == "Cardiology"
        assert row[3] == "scheduled"

    def test_t1_reminders_table_persistence_with_rrule(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 5: Reminders table stores recurrence rules, category, and next_due_at."""
        prof_id = sample_profile["id"]
        rem_id = str(uuid.uuid4())
        due = (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        cur = test_db.cursor()

        cur.execute(
            "INSERT INTO reminders (id, profile_id, title, description, category, rrule, timezone, next_due_at, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rem_id, prof_id, "Take Lisinopril 10mg", "With morning water", "medication", "FREQ=DAILY;INTERVAL=1", "America/New_York", due, "pending", now, now),
        )
        test_db.commit()

        cur.execute("SELECT category, rrule, status FROM reminders WHERE id = ?", (rem_id,))
        row = cur.fetchone()
        assert row[0] == "medication"
        assert row[1] == "FREQ=DAILY;INTERVAL=1"
        assert row[2] == "pending"

    def test_t1_notes_linked_appointment_foreign_key_and_index(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 6: Notes table supports linked_appointment_id FK with ON DELETE SET NULL."""
        prof_id = sample_profile["id"]
        appt_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        cur = test_db.cursor()

        # Create appointment
        cur.execute(
            "INSERT INTO appointments (id, profile_id, title, start_time, end_time, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (appt_id, prof_id, "Visit Note Appt", now, now, now, now),
        )
        # Create note linked to appointment
        note_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO notes (id, profile_id, title, content, type, linked_appointment_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (note_id, prof_id, "Visit Notes", "Discussion on BP meds", "visit", appt_id, now, now),
        )
        test_db.commit()

        # Delete appointment -> note linked_appointment_id becomes NULL
        cur.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
        test_db.commit()

        cur.execute("SELECT linked_appointment_id FROM notes WHERE id = ?", (note_id,))
        row = cur.fetchone()
        assert row is not None
        assert row[0] is None

    def test_t1_profile_deletion_cascade_cleans_batch3_tables(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 8: Deleting profile cascades to health_resources, appointments, reminders, and notes."""
        prof_id = sample_profile["id"]
        now = datetime.now(timezone.utc).isoformat()
        cur = test_db.cursor()

        cur.execute("INSERT INTO health_resources (id, profile_id, resource_type, source_type, data, effective_at, recorded_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), prof_id, "observation", "manual", "{}", now, now, now, now))
        cur.execute("INSERT INTO appointments (id, profile_id, title, start_time, end_time, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), prof_id, "Cascade Appt", now, now, now, now))
        cur.execute("INSERT INTO reminders (id, profile_id, title, next_due_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), prof_id, "Cascade Rem", now, now, now))
        cur.execute("INSERT INTO notes (id, profile_id, title, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), prof_id, "Cascade Note", "Text", now, now))
        test_db.commit()

        # Cascade delete
        cur.execute("DELETE FROM profiles WHERE id = ?", (prof_id,))
        test_db.commit()

        for tbl in ("health_resources", "appointments", "reminders", "notes"):
            cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE profile_id = ?", (prof_id,))
            assert cur.fetchone()[0] == 0

    def test_t1_health_resources_tombstone_status_lifecycle(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 3: health_resources supports active, amended, and tombstone statuses."""
        prof_id = sample_profile["id"]
        r_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        cur = test_db.cursor()

        cur.execute(
            "INSERT INTO health_resources (id, profile_id, resource_type, source_type, data, status, effective_at, recorded_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)",
            (r_id, prof_id, "observation", "manual", "{}", now, now, now, now),
        )
        test_db.commit()

        cur.execute("UPDATE health_resources SET status = 'tombstone' WHERE id = ?", (r_id,))
        test_db.commit()

        cur.execute("SELECT status FROM health_resources WHERE id = ?", (r_id,))
        assert cur.fetchone()[0] == "tombstone"


class TestTier1FhirVitalsNormalization:
    """Tier 1: FHIR R4 Vitals Normalization, LOINC mappings, and unit conversion (F-09, F-20, F-21)."""

    def test_t1_normalize_blood_pressure_loinc_85354_9(self):
        """Feature 9: Normalizes BP panel into LOINC 85354-9 with systolic and diastolic components."""
        raw = {"systolic": 124, "diastolic": 78}
        obs = normalize_fhir_vitals(raw)

        assert obs["resourceType"] == "Observation"
        assert obs["code"]["coding"][0]["code"] == LOINC_CODES["blood_pressure"]
        components = obs["component"]
        assert len(components) == 2
        assert components[0]["code"]["coding"][0]["code"] == LOINC_CODES["systolic"]
        assert components[0]["valueQuantity"]["value"] == 124.0
        assert components[0]["valueQuantity"]["unit"] == "mmHg"
        assert components[1]["code"]["coding"][0]["code"] == LOINC_CODES["diastolic"]
        assert components[1]["valueQuantity"]["value"] == 78.0

    def test_t1_normalize_heart_rate_loinc_8867_4(self):
        """Feature 9: Normalizes heart rate into LOINC 8867-4 in bpm."""
        raw = {"heart_rate": 72}
        obs = normalize_fhir_vitals(raw)

        assert obs["code"]["coding"][0]["code"] == LOINC_CODES["heart_rate"]
        assert obs["valueQuantity"]["value"] == 72.0
        assert obs["valueQuantity"]["unit"] == "bpm"

    def test_t1_normalize_blood_glucose_loinc_2339_0_with_mmol_conversion(self):
        """Feature 9: Normalizes blood glucose and converts mmol/L to mg/dL."""
        raw_mmol = {"blood_glucose": 5.0, "unit": "mmol/L"}
        obs = normalize_fhir_vitals(raw_mmol)

        assert obs["code"]["coding"][0]["code"] == LOINC_CODES["blood_glucose"]
        # 5.0 mmol/L * 18.0182 = ~90.09 mg/dL
        assert round(obs["valueQuantity"]["value"], 1) == 90.1
        assert obs["valueQuantity"]["unit"] == "mg/dL"

    def test_t1_normalize_spo2_loinc_2708_6(self):
        """Feature 9: Normalizes oxygen saturation into LOINC 2708-6 in %."""
        raw = {"spo2": 98.0}
        obs = normalize_fhir_vitals(raw)

        assert obs["code"]["coding"][0]["code"] == LOINC_CODES["oxygen_saturation"]
        assert obs["valueQuantity"]["value"] == 98.0
        assert obs["valueQuantity"]["unit"] == "%"

    def test_t1_normalize_weight_and_height_loinc_with_unit_conversion(self):
        """Feature 9: Normalizes weight (lbs -> kg) and height (inches -> cm)."""
        raw_wt = {"weight": 154.32, "unit": "lbs"}
        obs_wt = normalize_fhir_vitals(raw_wt)
        assert obs_wt["code"]["coding"][0]["code"] == LOINC_CODES["body_weight"]
        assert round(obs_wt["valueQuantity"]["value"], 1) == 70.0  # 154.32 lbs = 70 kg

        raw_ht = {"height": 70.0, "unit": "inches"}
        obs_ht = normalize_fhir_vitals(raw_ht)
        assert obs_ht["code"]["coding"][0]["code"] == LOINC_CODES["body_height"]
        assert round(obs_ht["valueQuantity"]["value"], 1) == 177.8  # 70 in = 177.8 cm


class TestTier1BmiAndPediatricEngine:
    """Tier 1: Adult BMI, pediatric LMS percentiles, and hide_weight privacy toggle (F-10, F-11, F-12)."""

    def test_t1_adult_bmi_metric_and_who_classification(self):
        """Feature 10: Adult BMI formula (kg/m^2) and classification tiers."""
        normal = calculate_adult_bmi(weight_kg=65.0, height_cm=170.0)
        assert normal["bmi"] == 22.5
        assert normal["classification"] == "Normal weight"

        overweight = calculate_adult_bmi(weight_kg=80.0, height_cm=170.0)
        assert overweight["bmi"] == 27.7
        assert overweight["classification"] == "Overweight"

        obese = calculate_adult_bmi(weight_kg=105.0, height_cm=170.0)
        assert obese["bmi"] == 36.3
        assert obese["classification"] == "Obese Class 2"

    def test_t1_adult_bmi_invalid_nonpositive_values_rejected(self):
        """Feature 10: Rejects non-positive weight or height."""
        with pytest.raises(ValueError):
            calculate_adult_bmi(weight_kg=-70.0, height_cm=175.0)
        with pytest.raises(ValueError):
            calculate_adult_bmi(weight_kg=70.0, height_cm=0.0)

    def test_t1_pediatric_bmi_percentile_calculation_for_age_5(self):
        """Feature 11: Calculates CDC LMS pediatric BMI percentile for child aged 5 (60 months)."""
        res = calculate_pediatric_bmi_percentile(
            age_months=60, gender="male", weight_kg=18.5, height_cm=110.0, hide_weight=False
        )
        assert res["suppressed"] is False
        assert res["bmi"] == 15.3
        assert 10.0 <= res["percentile"] <= 90.0
        assert res["classification"] in ("Healthy weight", "Overweight")

    def test_t1_pediatric_bmi_suppression_under_24_months(self):
        """Feature 11: Suppresses BMI calculation for children under 2 years (<24 months)."""
        infant = calculate_pediatric_bmi_percentile(
            age_months=18, gender="female", weight_kg=10.5, height_cm=80.0, hide_weight=False
        )
        assert infant["suppressed"] is True
        assert infant["bmi"] is None
        assert infant["percentile"] is None
        assert "Age under 24 months" in infant["reason"]

    def test_t1_hide_weight_privacy_preference_suppression(self):
        """Feature 12: hide_weight=True suppresses weight and BMI display."""
        res = calculate_pediatric_bmi_percentile(
            age_months=120, gender="female", weight_kg=35.0, height_cm=140.0, hide_weight=True
        )
        assert res["suppressed"] is True
        assert res["weight_hidden"] is True
        assert res["bmi"] is None
        assert "hide_weight" in res["reason"]


class TestTier1DiurnalBloodPressureTrends:
    """Tier 1: Diurnal AM/PM BP moving averages and AHA/ACC 2025 guidelines (F-13, F-21)."""

    def test_t1_diurnal_am_pm_moving_averages_partitioning(self):
        """Feature 13: Partitions readings into AM (05:00-11:59) and PM (12:00-22:00)."""
        now = datetime(2026, 10, 10, 15, 0, 0, tzinfo=timezone.utc)
        readings = [
            {"systolic": 118, "diastolic": 76, "effective_at": "2026-10-09T08:30:00Z"},  # AM
            {"systolic": 122, "diastolic": 78, "effective_at": "2026-10-08T09:15:00Z"},  # AM
            {"systolic": 136, "diastolic": 88, "effective_at": "2026-10-09T18:45:00Z"},  # PM
            {"systolic": 138, "diastolic": 90, "effective_at": "2026-10-08T20:00:00Z"},  # PM
            {"systolic": 110, "diastolic": 70, "effective_at": "2026-10-09T03:00:00Z"},  # Night (excluded)
        ]

        trends = calculate_diurnal_bp_trends(readings, now_dt=now, user_tz="UTC")
        t7 = trends["7_day"]
        assert t7["am"]["count"] == 2
        assert t7["am"]["systolic"] == 120.0
        assert t7["am"]["diastolic"] == 77.0

        assert t7["pm"]["count"] == 2
        assert t7["pm"]["systolic"] == 137.0
        assert t7["pm"]["diastolic"] == 89.0

    def test_t1_aha_acc_2025_normal_classification(self):
        """Feature 13: Normal blood pressure per AHA/ACC 2025 (<120 and <80)."""
        assert classify_blood_pressure(115, 75) == "Normal"

    def test_t1_aha_acc_2025_elevated_classification(self):
        """Feature 13: Elevated blood pressure per AHA/ACC 2025 (120-129 and <80)."""
        assert classify_blood_pressure(125, 78) == "Elevated"

    def test_t1_aha_acc_2025_stage_1_hypertension(self):
        """Feature 13: Stage 1 Hypertension per AHA/ACC 2025 (130-139 or 80-89)."""
        assert classify_blood_pressure(132, 75) == "Stage 1"
        assert classify_blood_pressure(122, 84) == "Stage 1"

    def test_t1_aha_acc_2025_stage_2_hypertension(self):
        """Feature 13: Stage 2 Hypertension per AHA/ACC 2025 (>=140 or >=90)."""
        assert classify_blood_pressure(145, 85) == "Stage 2"
        assert classify_blood_pressure(135, 95) == "Stage 2"


class TestTier1VitalsRedFlagsSafetyEngine:
    """Tier 1: Non-clinical boundary Vitals Red Flags Safety Engine (F-14 to F-19)."""

    def test_t1_hypertensive_crisis_symptomatic_triggers_call_911(self):
        """Feature 15: BP >= 180/120 with acute symptoms triggers non-suppressible 'Call 911' directive."""
        flag = check_vitals_red_flags({"systolic": 195, "diastolic": 125}, reported_symptoms=["chest pain"])
        assert flag.triggered is True
        assert flag.category == "bp_crisis_symptomatic"
        assert flag.severity == "emergency"
        assert "Call 911" in flag.directive

    def test_t1_hypertensive_crisis_asymptomatic_triggers_prompt_recheck(self):
        """Feature 15: BP >= 180/120 without symptoms triggers 5-minute recheck and doctor contact directive."""
        flag = check_vitals_red_flags({"systolic": 185, "diastolic": 115}, reported_symptoms=[])
        assert flag.triggered is True
        assert flag.category == "bp_crisis_asymptomatic"
        assert flag.severity == "urgent"
        assert flag.prompt_recheck is True
        assert "recheck" in flag.directive

    def test_t1_severe_hypoxemia_spo2_under_90_directive(self):
        """Feature 16: SpO2 < 90% triggers severe hypoxemia immediate evaluation directive."""
        flag = check_vitals_red_flags({"spo2": 87.0})
        assert flag.triggered is True
        assert flag.category == "severe_hypoxemia"
        assert flag.severity == "emergency"

    def test_t1_severe_hypoglycemia_glucose_under_54_rule_of_15(self):
        """Feature 17: Glucose < 54 mg/dL triggers Rule of 15 acute directive."""
        flag = check_vitals_red_flags({"blood_glucose": 48.0})
        assert flag.triggered is True
        assert flag.category == "severe_hypoglycemia"
        assert "Rule of 15" in flag.directive

    def test_t1_symptomatic_hypotension_triggers_clinical_referral(self):
        """Feature 18: BP < 90/60 with dizziness or syncope triggers symptomatic hypotension referral."""
        flag = check_vitals_red_flags({"systolic": 84, "diastolic": 56}, reported_symptoms=["dizziness"])
        assert flag.triggered is True
        assert flag.category == "symptomatic_hypotension"
        assert flag.severity == "urgent"

    def test_t1_normal_vitals_trigger_zero_red_flags(self):
        """Feature 14: Normal vitals evaluate cleanly without triggering red flags."""
        flag = check_vitals_red_flags({"systolic": 118, "diastolic": 76, "spo2": 98.0, "blood_glucose": 95.0})
        assert flag.triggered is False
        assert flag.severity == "normal"


class TestTier1AppointmentsScheduling:
    """Tier 1: Appointments booking, structured drafts, and post-visit transitions (F-22 to F-25)."""

    def test_t1_generate_how_to_book_phone_script_and_portal_draft(self):
        """Feature 24: Generates structured phone call script and portal message drafts."""
        drafts = generate_how_to_book_drafts(
            title="Cardiology Consultation",
            provider_name="Dr. Sarah Connor",
            specialty="Cardiology",
            clinic_phone="555-0144",
            reason="Exertional palpitations",
        )
        assert drafts["status"] == "requested"
        assert "Dr. Sarah Connor" in drafts["phone_script"]
        assert "555-0144" in drafts["phone_script"]
        assert "INSURANCE CHECKLIST" in drafts["phone_script"]
        assert "Exertional palpitations" in drafts["portal_draft"]
        assert len(drafts["checklist"]) >= 3

    def test_t1_appointment_creation_sets_requested_status(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 23: Appointments created through assistant default to requested status."""
        cur = test_db.cursor()
        appt_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'requested', ?, ?)",
            (appt_id, sample_profile["id"], "Pediatric Checkup", now, now, now, now),
        )
        test_db.commit()

        cur.execute("SELECT status FROM appointments WHERE id = ?", (appt_id,))
        assert cur.fetchone()[0] == "requested"

    def test_t1_appointment_status_transitions_scheduled_confirmed(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 23: Lifecycle transitions: requested -> scheduled -> confirmed."""
        cur = test_db.cursor()
        appt_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'requested', ?, ?)",
            (appt_id, sample_profile["id"], "Dermatology Visit", now, now, now, now),
        )
        test_db.commit()

        cur.execute("UPDATE appointments SET status = 'confirmed' WHERE id = ?", (appt_id,))
        test_db.commit()

        cur.execute("SELECT status FROM appointments WHERE id = ?", (appt_id,))
        assert cur.fetchone()[0] == "confirmed"

    def test_t1_post_visit_transition_confirmed_to_completed(self):
        """Feature 25: Past confirmed appointments transition to completed status."""
        now = datetime.now(timezone.utc)
        past_appt = {
            "id": "appt-001",
            "title": "Annual Wellness Visit",
            "status": "confirmed",
            "end_time": (now - timedelta(hours=2)).isoformat(),
        }
        future_appt = {
            "id": "appt-002",
            "title": "Future Visit",
            "status": "confirmed",
            "end_time": (now + timedelta(days=2)).isoformat(),
        }

        completed_ids, prompts = evaluate_post_visit_transitions([past_appt, future_appt], current_time=now)
        assert "appt-001" in completed_ids
        assert "appt-002" not in completed_ids

    def test_t1_post_visit_triggers_followup_prompt(self):
        """Feature 25: Completed appointment generates in-app follow-up prompt for after-visit notes."""
        now = datetime.now(timezone.utc)
        past_appt = {
            "id": "appt-cardio",
            "title": "Cardiology Visit",
            "status": "confirmed",
            "end_time": (now - timedelta(minutes=30)).isoformat(),
        }
        completed_ids, prompts = evaluate_post_visit_transitions([past_appt], current_time=now)
        assert len(prompts) == 1
        assert prompts[0]["prompt_type"] == "post_visit_followup"
        assert "visit notes" in prompts[0]["message"]


class TestTier1RemindersRecurrenceEngine:
    """Tier 1: RFC 5545 RRULE expansion, snooze, overdue sweep, and .ics export (F-26 to F-32)."""

    def test_t1_rrule_daily_recurrence_advancement(self):
        """Feature 27: RRULE FREQ=DAILY advances due time by 1 day."""
        base = datetime(2026, 10, 10, 9, 0, 0, tzinfo=timezone.utc)
        next_dt = advance_rrule_occurrence(base, "FREQ=DAILY;INTERVAL=1", "UTC")
        assert next_dt == base + timedelta(days=1)

    def test_t1_rrule_weekly_recurrence_advancement(self):
        """Feature 27: RRULE FREQ=WEEKLY advances due time by 7 days."""
        base = datetime(2026, 10, 10, 9, 0, 0, tzinfo=timezone.utc)
        next_dt = advance_rrule_occurrence(base, "FREQ=WEEKLY;INTERVAL=1", "UTC")
        assert next_dt == base + timedelta(weeks=1)

    def test_t1_reminder_snooze_15m_1h_24h(self):
        """Feature 28: Reminders snooze supports +15m, +1h, and +24h."""
        now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
        rem = {"id": "rem-1", "status": "pending", "next_due_at": now.isoformat()}

        s15 = apply_reminder_snooze(rem, "+15m", now)
        assert s15["status"] == "snoozed"
        assert s15["snooze_until"] == (now + timedelta(minutes=15)).isoformat()

        s1h = apply_reminder_snooze(rem, "+1h", now)
        assert s1h["snooze_until"] == (now + timedelta(hours=1)).isoformat()

        s24h = apply_reminder_snooze(rem, "+24h", now)
        assert s24h["snooze_until"] == (now + timedelta(hours=24)).isoformat()

    def test_t1_overdue_reminders_coalesce_to_missed_after_24h(self):
        """Feature 29: Overdue reminders > 24 hours coalesce into status missed."""
        now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
        overdue_old = {"id": "r1", "status": "pending", "next_due_at": (now - timedelta(hours=26)).isoformat()}
        overdue_recent = {"id": "r2", "status": "pending", "next_due_at": (now - timedelta(hours=5)).isoformat()}

        coalesced = coalesce_overdue_reminders([overdue_old, overdue_recent], current_time=now)
        assert coalesced[0]["status"] == "missed"
        assert coalesced[1]["status"] == "pending"

    def test_t1_export_ics_calendar_with_phi_sanitization(self):
        """Feature 30: Generates RFC 5545 .ics calendar and sanitizes PHI titles."""
        reminders = [{
            "id": "r-oncology",
            "title": "Oncology chemotherapy infusion session",
            "category": "appointment",
            "next_due_at": "2026-10-15T14:00:00Z",
            "description": "Port flush and IV infusion",
        }]

        ics_sanitized = generate_ics_calendar(reminders, sanitize_phi=True)
        assert "BEGIN:VCALENDAR" in ics_sanitized
        assert "BEGIN:VEVENT" in ics_sanitized
        assert "Carefold Appointment Reminder" in ics_sanitized
        assert "chemotherapy" not in ics_sanitized  # PHI stripped

        ics_raw = generate_ics_calendar(reminders, sanitize_phi=False)
        assert "Oncology chemotherapy infusion session" in ics_raw


class TestTier1ExecutionPlanAndPrepPack:
    """Tier 1: ExecutionPlan template compilation and clinical prep pack compilation (F-33 to F-35, F-41)."""

    def test_t1_compile_execution_plan_visit_prep(self):
        """Feature 33: Deterministically compiles ExecutionPlan for visit_prep intent."""
        plan = compile_execution_plan("visit_prep", {"specialty": "Cardiology", "reason": "Arrhythmia"})
        assert plan["intent"] == "visit_prep"
        steps = plan["steps"]
        assert len(steps) == 4
        tools = [s["tool"] for s in steps]
        assert tools == ["search_records", "calculate_trends", "draft_questions", "generate_prep_pack"]

    def test_t1_compile_execution_plan_log_vitals(self):
        """Feature 33: Deterministically compiles ExecutionPlan for log_vitals intent."""
        plan = compile_execution_plan("log_vitals", {"systolic": 130, "diastolic": 85})
        assert plan["intent"] == "log_vitals"
        tools = [s["tool"] for s in plan["steps"]]
        assert tools == ["parse_observation", "check_red_flags", "record_vitals"]

    def test_t1_compile_execution_plan_remind_me(self):
        """Feature 33: Deterministically compiles ExecutionPlan for remind_me intent."""
        plan = compile_execution_plan("remind_me", {"title": "Take Metformin", "time": "08:00"})
        assert plan["intent"] == "remind_me"
        tools = [s["tool"] for s in plan["steps"]]
        assert tools == ["parse_rrule", "create_reminder"]

    def test_t1_clinical_prep_pack_compiler_aggregates_trends_and_questions(self):
        """Feature 34: Aggregates reason, symptoms, vitals trends, and prioritized questions into Markdown."""
        trends = {
            "30_day": {
                "am": {"systolic": 128.5, "diastolic": 82.0, "classification": "Stage 1"},
                "pm": {"systolic": 132.0, "diastolic": 85.0, "classification": "Stage 1"},
            }
        }
        questions = [
            "Should we adjust my blood pressure dosage based on evening readings?",
            "Is it safe to continue high-intensity cardio exercises?",
            "When should I repeat my basic metabolic panel labs?",
        ]
        pack = compile_clinical_prep_pack(
            reason_for_visit="Hypertension Follow-up",
            symptoms=["Mild evening headache", "Fatigue"],
            vitals_trends=trends,
            medications=["Lisinopril 10mg"],
            allergies=["Penicillin"],
            doctor_questions=questions,
            search_excerpts=["Prior visit noted elevated diastolic pressure."],
        )

        md = pack["markdown"]
        assert "# Clinical Visit Preparation Dossier" in md
        assert "Hypertension Follow-up" in md
        assert "128.5/82.0 mmHg (Stage 1)" in md
        assert "Lisinopril 10mg" in md
        assert questions[0] in md
        assert pack["questions_count"] == 3

    def test_t1_prep_pack_compiler_includes_search_excerpts(self):
        """Feature 34: Integrates cognitive search excerpts with attribution."""
        pack = compile_clinical_prep_pack(
            reason_for_visit="Cardiology Review",
            symptoms=[],
            vitals_trends={},
            medications=[],
            allergies=[],
            doctor_questions=["What is the next step?"],
            search_excerpts=["2024 Echocardiogram: Mild aortic root dilation."],
        )
        assert "> 2024 Echocardiogram: Mild aortic root dilation." in pack["markdown"]


class TestTier1TypedNotesAndAfterVisitExtraction:
    """Tier 1: Typed notes (7 categories) and after-visit extraction with citations (F-36 to F-40)."""

    def test_t1_typed_notes_supports_all_seven_categories(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 36: Validates support for all 7 typed note categories."""
        cur = test_db.cursor()
        prof_id = sample_profile["id"]
        now = datetime.now(timezone.utc).isoformat()

        for note_type in VALID_NOTE_TYPES:
            n_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO notes (id, profile_id, title, content, type, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (n_id, prof_id, f"Note {note_type}", "Content", note_type, now, now),
            )
        test_db.commit()

        cur.execute("SELECT COUNT(DISTINCT type) FROM notes WHERE profile_id = ?", (prof_id,))
        assert cur.fetchone()[0] == 7

    def test_t1_notes_linked_to_appointment_id(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 37: Notes link directly to an appointment."""
        cur = test_db.cursor()
        appt_id = str(uuid.uuid4())
        note_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        cur.execute("INSERT INTO appointments (id, profile_id, title, start_time, end_time, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (appt_id, sample_profile["id"], "Cardio Visit", now, now, now, now))
        cur.execute("INSERT INTO notes (id, profile_id, title, content, type, linked_appointment_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (note_id, sample_profile["id"], "Debrief", "Notes", "after_visit", appt_id, now, now))
        test_db.commit()

        cur.execute("SELECT linked_appointment_id FROM notes WHERE id = ?", (note_id,))
        assert cur.fetchone()[0] == appt_id

    def test_t1_after_visit_extraction_diagnoses_with_citations(self):
        """Feature 38: Extracted diagnoses carry line citations [Note Line X]."""
        content = (
            "Visit with Dr. Patel on Oct 10.\n"
            "Diagnosed with mild essential hypertension.\n"
            "Plan to monitor BP daily."
        )
        summary = extract_after_visit_summary(content)
        diagnoses = summary["diagnoses"]
        assert len(diagnoses) == 1
        assert "mild essential hypertension" in diagnoses[0]["text"]
        assert diagnoses[0]["citation"] == "[Note Line 2]"

    def test_t1_after_visit_extraction_medications_with_citations(self):
        """Feature 38: Extracted medication adjustments carry line citations."""
        content = (
            "After visit summary notes:\n"
            "Doctor advised lifestyle modifications.\n"
            "Prescribed Amlodipine 5mg daily in the morning.\n"
            "Stop taking generic over-the-counter decongestants."
        )
        summary = extract_after_visit_summary(content)
        meds = summary["medication_adjustments"]
        assert len(meds) == 1
        assert "Amlodipine 5mg" in meds[0]["text"]
        assert meds[0]["citation"] == "[Note Line 3]"

    def test_t1_after_visit_extraction_includes_mandatory_non_clinical_disclaimer(self):
        """Feature 39: Extracted summaries contain mandatory non-clinical disclaimer."""
        summary = extract_after_visit_summary("Ordered blood work for lipid panel.")
        assert summary["disclaimer"] == NON_CLINICAL_DISCLAIMER


class TestTier1ActivityTimelineAndUndo:
    """Tier 1: Audit logging, 7-day rollback resolution, and search invalidation (F-42 to F-46)."""

    def test_t1_audit_event_logged_for_write_local_action(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 42: Audit event records actor, action, tool, and write_local risk."""
        cur = test_db.cursor()
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp, details) "
            "VALUES (?, ?, 'user', 'create', 'record_vitals', 'write_local', 'health_resource:hr-1', ?, '{}')",
            (e_id, sample_profile["id"], now),
        )
        test_db.commit()

        cur.execute("SELECT action, risk, external_ref FROM audit_events WHERE id = ?", (e_id,))
        row = cur.fetchone()
        assert row[0] == "create"
        assert row[1] == "write_local"
        assert row[2] == "health_resource:hr-1"

    def test_t1_undo_health_resource_sets_tombstone(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 44: Undoing a health resource mutation marks its status as tombstone."""
        cur = test_db.cursor()
        prof_id = sample_profile["id"]
        hr_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO health_resources (id, profile_id, resource_type, source_type, data, status, effective_at, recorded_at, created_at, updated_at) "
                    "VALUES (?, ?, 'observation', 'manual', '{}', 'active', ?, ?, ?, ?)", (hr_id, prof_id, now.isoformat(), now.isoformat(), now.isoformat(), now.isoformat()))
        cur.execute("INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) VALUES (?, ?, 'user', 'record', 'record_vitals', 'write_local', ?, ?)",
                    (e_id, prof_id, f"health_resource:{hr_id}", now.isoformat()))
        test_db.commit()

        res = execute_single_click_undo(test_db, e_id, prof_id, current_time=now + timedelta(hours=1))
        assert res["status"] == "undone"

        cur.execute("SELECT status FROM health_resources WHERE id = ?", (hr_id,))
        assert cur.fetchone()[0] == "tombstone"

    def test_t1_undo_appointment_sets_cancelled(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 44: Undoing an appointment creation sets its status to cancelled."""
        cur = test_db.cursor()
        prof_id = sample_profile["id"]
        appt_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) VALUES (?, ?, 'Checkup', ?, ?, 'scheduled', ?, ?)",
                    (appt_id, prof_id, now.isoformat(), now.isoformat(), now.isoformat(), now.isoformat()))
        cur.execute("INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
                    (e_id, prof_id, f"appointment:{appt_id}", now.isoformat()))
        test_db.commit()

        execute_single_click_undo(test_db, e_id, prof_id, current_time=now + timedelta(hours=2))

        cur.execute("SELECT status FROM appointments WHERE id = ?", (appt_id,))
        assert cur.fetchone()[0] == "cancelled"

    def test_t1_undo_reminder_sets_cancelled(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 44: Undoing a reminder sets its status to cancelled."""
        cur = test_db.cursor()
        prof_id = sample_profile["id"]
        rem_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO reminders (id, profile_id, title, next_due_at, status, created_at, updated_at) VALUES (?, ?, 'Meds', ?, 'pending', ?, ?)",
                    (rem_id, prof_id, now.isoformat(), now.isoformat(), now.isoformat()))
        cur.execute("INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) VALUES (?, ?, 'user', 'create', 'create_reminder', 'write_local', ?, ?)",
                    (e_id, prof_id, f"reminder:{rem_id}", now.isoformat()))
        test_db.commit()

        execute_single_click_undo(test_db, e_id, prof_id, current_time=now + timedelta(minutes=10))

        cur.execute("SELECT status FROM reminders WHERE id = ?", (rem_id,))
        assert cur.fetchone()[0] == "cancelled"

    def test_t1_undo_note_soft_deletes_and_enqueues_search_deletion(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 45: Undoing a note soft-deletes it and enqueues a delete_doc job."""
        cur = test_db.cursor()
        prof_id = sample_profile["id"]
        note_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO notes (id, profile_id, title, content, is_deleted, created_at, updated_at) VALUES (?, ?, 'Title', 'Body', 0, ?, ?)",
                    (note_id, prof_id, now.isoformat(), now.isoformat()))
        cur.execute("INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) VALUES (?, ?, 'user', 'create', 'create_typed_note', 'write_local', ?, ?)",
                    (e_id, prof_id, f"note:{note_id}", now.isoformat()))
        test_db.commit()

        execute_single_click_undo(test_db, e_id, prof_id, current_time=now + timedelta(hours=1))

        cur.execute("SELECT is_deleted FROM notes WHERE id = ?", (note_id,))
        assert cur.fetchone()[0] == 1

        cur.execute("SELECT kind, payload FROM jobs WHERE profile_id = ? AND kind = 'delete_doc'", (prof_id,))
        job = cur.fetchone()
        assert job is not None
        assert note_id in job[1]

    def test_t1_undo_records_audited_reversal_event(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Feature 46: Audited reversal records event='undo', tool='undo'."""
        cur = test_db.cursor()
        prof_id = sample_profile["id"]
        rem_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO reminders (id, profile_id, title, next_due_at, status, created_at, updated_at) VALUES (?, ?, 'Meds', ?, 'pending', ?, ?)",
                    (rem_id, prof_id, now.isoformat(), now.isoformat(), now.isoformat()))
        cur.execute("INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) VALUES (?, ?, 'user', 'create', 'create_reminder', 'write_local', ?, ?)",
                    (e_id, prof_id, f"reminder:{rem_id}", now.isoformat()))
        test_db.commit()

        execute_single_click_undo(test_db, e_id, prof_id, current_time=now + timedelta(minutes=5))

        cur.execute("SELECT action, tool, external_ref FROM audit_events WHERE action = 'undo'", ())
        rev = cur.fetchone()
        assert rev is not None
        assert rev[0] == "undo"
        assert rev[1] == "undo"
        assert rev[2] == f"reminder:{rem_id}"


# ============================================================================
# TIER 2: BOUNDARY & CORNER CASES
# ============================================================================

class TestTier2BoundaryExtremeBloodPressure:
    """Tier 2: Boundary test cases for Hypertensive Crisis and Hypotension thresholds."""

    def test_t2_bp_crisis_exact_boundary_180_120(self):
        """Boundary: Exact 180/120 mmHg triggers Hypertensive Crisis."""
        flag = check_vitals_red_flags({"systolic": 180, "diastolic": 120}, reported_symptoms=[])
        assert flag.triggered is True
        assert flag.category == "bp_crisis_asymptomatic"

    def test_t2_bp_just_below_crisis_179_119_triggers_stage_2(self):
        """Boundary: 179/119 mmHg is below Crisis cutoff and classifies as Stage 2."""
        flag = check_vitals_red_flags({"systolic": 179, "diastolic": 119}, reported_symptoms=[])
        assert flag.triggered is False  # Not crisis red flag
        assert classify_blood_pressure(179, 119) == "Stage 2"

    def test_t2_isolated_systolic_crisis_180_80(self):
        """Boundary: Systolic 180 with normal diastolic 80 triggers crisis."""
        flag = check_vitals_red_flags({"systolic": 180, "diastolic": 80}, reported_symptoms=[])
        assert flag.triggered is True
        assert flag.category == "bp_crisis_asymptomatic"

    def test_t2_isolated_diastolic_crisis_130_120(self):
        """Boundary: Systolic 130 with diastolic 120 triggers crisis."""
        flag = check_vitals_red_flags({"systolic": 130, "diastolic": 120}, reported_symptoms=[])
        assert flag.triggered is True
        assert flag.category == "bp_crisis_asymptomatic"

    def test_t2_hypotension_exact_boundary_90_60_with_dizziness(self):
        """Boundary: Exact 89/59 with dizziness triggers flag; 90/60 does not."""
        flag_below = check_vitals_red_flags({"systolic": 89, "diastolic": 59}, reported_symptoms=["dizziness"])
        assert flag_below.triggered is True
        assert flag_below.category == "symptomatic_hypotension"

        flag_normal = check_vitals_red_flags({"systolic": 90, "diastolic": 60}, reported_symptoms=["dizziness"])
        assert flag_normal.triggered is False

    def test_t2_hypotension_without_symptoms_does_not_trigger_emergency(self):
        """Boundary: Low BP (85/55) without dizziness/syncope does not trigger referral flag."""
        flag = check_vitals_red_flags({"systolic": 85, "diastolic": 55}, reported_symptoms=[])
        assert flag.triggered is False


class TestTier2BoundaryOxygenSaturation:
    """Tier 2: Boundary test cases for SpO2 Hypoxemia (< 90%)."""

    def test_t2_spo2_exact_boundary_89_triggers_severe_hypoxemia(self):
        """Boundary: SpO2 89.9% triggers severe hypoxemia."""
        flag = check_vitals_red_flags({"spo2": 89.9})
        assert flag.triggered is True
        assert flag.category == "severe_hypoxemia"

    def test_t2_spo2_exact_boundary_90_does_not_trigger_severe_hypoxemia(self):
        """Boundary: SpO2 90.0% is at threshold, does not trigger <90% flag."""
        flag = check_vitals_red_flags({"spo2": 90.0})
        assert flag.triggered is False

    def test_t2_spo2_boundary_91_normal(self):
        """Boundary: SpO2 91% does not trigger emergency."""
        flag = check_vitals_red_flags({"spo2": 91.0})
        assert flag.triggered is False

    def test_t2_spo2_profound_hypoxemia_70_percent(self):
        """Boundary: Profound hypoxemia (70%) triggers emergency directive."""
        flag = check_vitals_red_flags({"spo2": 70.0})
        assert flag.triggered is True
        assert flag.severity == "emergency"

    def test_t2_spo2_loinc_normalization_preserves_precision(self):
        """Boundary: Precision of SpO2 value is preserved in FHIR R4 quantity."""
        obs = normalize_fhir_vitals({"spo2": 88.5})
        assert obs["valueQuantity"]["value"] == 88.5


class TestTier2BoundaryBloodGlucose:
    """Tier 2: Boundary test cases for Blood Glucose (< 54 mg/dL)."""

    def test_t2_glucose_exact_boundary_53_triggers_severe_hypoglycemia(self):
        """Boundary: 53.9 mg/dL triggers severe hypoglycemia."""
        flag = check_vitals_red_flags({"blood_glucose": 53.9})
        assert flag.triggered is True
        assert flag.category == "severe_hypoglycemia"

    def test_t2_glucose_exact_boundary_54_does_not_trigger_severe_hypoglycemia(self):
        """Boundary: 54.0 mg/dL is at threshold, does not trigger <54 flag."""
        flag = check_vitals_red_flags({"blood_glucose": 54.0})
        assert flag.triggered is False

    def test_t2_glucose_mmol_conversion_2_9_triggers_severe_hypoglycemia(self):
        """Boundary: 2.9 mmol/L (~52.2 mg/dL) triggers severe hypoglycemia."""
        flag = check_vitals_red_flags({"blood_glucose": 2.9, "unit": "mmol/L"})
        assert flag.triggered is True
        assert flag.category == "severe_hypoglycemia"

    def test_t2_glucose_mmol_conversion_3_1_does_not_trigger(self):
        """Boundary: 3.1 mmol/L (~55.8 mg/dL) does not trigger severe hypoglycemia."""
        flag = check_vitals_red_flags({"blood_glucose": 3.1, "unit": "mmol/L"})
        assert flag.triggered is False

    def test_t2_profound_hypoglycemia_25_mgdl(self):
        """Boundary: Profound hypoglycemia (25 mg/dL) triggers Rule of 15."""
        flag = check_vitals_red_flags({"blood_glucose": 25.0})
        assert flag.triggered is True
        assert flag.prompt_recheck is True


class TestTier2BoundaryChildBmiSuppression:
    """Tier 2: Boundary test cases for Pediatric BMI suppression (< 24 months)."""

    def test_t2_bmi_infant_exact_23_months_is_suppressed(self):
        """Boundary: Exact age 23 months is strictly suppressed."""
        res = calculate_pediatric_bmi_percentile(age_months=23, gender="male", weight_kg=12.0, height_cm=86.0)
        assert res["suppressed"] is True
        assert res["bmi"] is None

    def test_t2_bmi_toddler_exact_24_months_is_calculated(self):
        """Boundary: Exact age 24 months (2nd birthday) calculates BMI and percentile."""
        res = calculate_pediatric_bmi_percentile(age_months=24, gender="female", weight_kg=12.5, height_cm=87.0)
        assert res["suppressed"] is False
        assert res["bmi"] is not None
        assert res["percentile"] is not None

    def test_t2_bmi_infant_0_months_newborn_is_suppressed(self):
        """Boundary: Newborn (0 months) is strictly suppressed."""
        res = calculate_pediatric_bmi_percentile(age_months=0, gender="male", weight_kg=3.5, height_cm=50.0)
        assert res["suppressed"] is True
        assert "Age under 24 months" in res["reason"]

    def test_t2_bmi_adolescent_exact_239_months_pediatric_calculated(self):
        """Boundary: Age 239 months (19 years 11 months) calculates pediatric percentile."""
        res = calculate_pediatric_bmi_percentile(age_months=239, gender="male", weight_kg=70.0, height_cm=175.0)
        assert res["suppressed"] is False
        assert res.get("is_adult") is not True

    def test_t2_bmi_adult_exact_240_months_transitions_to_adult_bmi(self):
        """Boundary: Age 241 months (> 20 years) transitions to adult BMI calculation."""
        res = calculate_pediatric_bmi_percentile(age_months=241, gender="male", weight_kg=75.0, height_cm=178.0)
        assert res["suppressed"] is False
        assert res.get("is_adult") is True


class TestTier2BoundaryReminderSnooze:
    """Tier 2: Boundary test cases for Reminders snooze intervals (+15m, +1h, +24h)."""

    def test_t2_snooze_15m_exact_boundary(self):
        """Boundary: +15m adds exactly 900 seconds."""
        now = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
        r = apply_reminder_snooze({"id": "r"}, "+15m", now)
        due = datetime.fromisoformat(r["snooze_until"])
        assert due - now == timedelta(minutes=15)

    def test_t2_snooze_1h_exact_boundary(self):
        """Boundary: +1h adds exactly 3600 seconds."""
        now = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
        r = apply_reminder_snooze({"id": "r"}, "+1h", now)
        due = datetime.fromisoformat(r["snooze_until"])
        assert due - now == timedelta(hours=1)

    def test_t2_snooze_24h_exact_boundary(self):
        """Boundary: +24h adds exactly 86400 seconds."""
        now = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
        r = apply_reminder_snooze({"id": "r"}, "+24h", now)
        due = datetime.fromisoformat(r["snooze_until"])
        assert due - now == timedelta(hours=24)

    def test_t2_snooze_invalid_interval_rejected(self):
        """Boundary: Negative or unsupported intervals raise ValueError."""
        now = datetime.now(timezone.utc)
        with pytest.raises(ValueError):
            apply_reminder_snooze({"id": "r"}, "-10m", now)
        with pytest.raises(ValueError):
            apply_reminder_snooze({"id": "r"}, "+3d", now)

    def test_t2_snooze_resnooze_updates_snooze_until(self):
        """Boundary: Consecutive snoozes recalculate from current action time."""
        now1 = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
        r = apply_reminder_snooze({"id": "r"}, "+15m", now1)

        now2 = datetime(2026, 10, 10, 8, 10, 0, tzinfo=timezone.utc)
        r2 = apply_reminder_snooze(r, "+1h", now2)
        assert r2["snooze_until"] == (now2 + timedelta(hours=1)).isoformat()


class TestTier2BoundaryOverdueCoalescing:
    """Tier 2: Boundary test cases for > 24 hours missed reminders coalescing."""

    def test_t2_overdue_exact_23h59m_remains_pending(self):
        """Boundary: Reminder overdue by 23h 59m remains pending."""
        now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
        r = {"id": "r", "status": "pending", "next_due_at": (now - timedelta(hours=23, minutes=59)).isoformat()}
        res = coalesce_overdue_reminders([r], current_time=now)
        assert res[0]["status"] == "pending"

    def test_t2_overdue_exact_24h01m_coalesces_to_missed(self):
        """Boundary: Reminder overdue by 24h 1m coalesces to missed."""
        now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
        r = {"id": "r", "status": "pending", "next_due_at": (now - timedelta(hours=24, minutes=1)).isoformat()}
        res = coalesce_overdue_reminders([r], current_time=now)
        assert res[0]["status"] == "missed"

    def test_t2_overdue_snoozed_reminder_uses_snooze_until_for_coalescing(self):
        """Boundary: Snoozed reminder coalescing measures from snooze_until, not next_due_at."""
        now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
        r = {
            "id": "r",
            "status": "snoozed",
            "next_due_at": (now - timedelta(days=5)).isoformat(),
            "snooze_until": (now - timedelta(hours=10)).isoformat(),  # Only 10h overdue
        }
        res = coalesce_overdue_reminders([r], current_time=now)
        assert res[0]["status"] == "snoozed"

    def test_t2_completed_reminder_overdue_by_48h_never_coalesces_to_missed(self):
        """Boundary: Completed reminder is invariant to overdue sweep."""
        now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
        r = {"id": "r", "status": "completed", "next_due_at": (now - timedelta(hours=48)).isoformat()}
        res = coalesce_overdue_reminders([r], current_time=now)
        assert res[0]["status"] == "completed"

    def test_t2_cancelled_reminder_overdue_never_coalesces_to_missed(self):
        """Boundary: Cancelled reminder is invariant to overdue sweep."""
        now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
        r = {"id": "r", "status": "cancelled", "next_due_at": (now - timedelta(hours=72)).isoformat()}
        res = coalesce_overdue_reminders([r], current_time=now)
        assert res[0]["status"] == "cancelled"


class TestTier2BoundarySevenDayUndoLimits:
    """Tier 2: Boundary test cases for 7-day single-click undo limit."""

    def test_t2_undo_within_6_days_23_hours_succeeds(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Boundary: Action at 6 days 23 hours is within 7-day limit and succeeds."""
        cur = test_db.cursor()
        prof_id = sample_profile["id"]
        appt_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        ts = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        now = ts + timedelta(days=6, hours=23)

        cur.execute("INSERT INTO appointments (id, profile_id, title, start_time, end_time, created_at, updated_at) VALUES (?, ?, 'A', ?, ?, ?, ?)",
                    (appt_id, prof_id, ts.isoformat(), ts.isoformat(), ts.isoformat(), ts.isoformat()))
        cur.execute("INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
                    (e_id, prof_id, f"appointment:{appt_id}", ts.isoformat()))
        test_db.commit()

        res = execute_single_click_undo(test_db, e_id, prof_id, current_time=now)
        assert res["status"] == "undone"

    def test_t2_undo_exact_7_days_1_second_rejected(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Boundary: Action at 7 days 1 second raises UndoWindowExpiredError."""
        cur = test_db.cursor()
        prof_id = sample_profile["id"]
        appt_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        ts = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        now = ts + timedelta(days=7, seconds=1)

        cur.execute("INSERT INTO appointments (id, profile_id, title, start_time, end_time, created_at, updated_at) VALUES (?, ?, 'A', ?, ?, ?, ?)",
                    (appt_id, prof_id, ts.isoformat(), ts.isoformat(), ts.isoformat(), ts.isoformat()))
        cur.execute("INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
                    (e_id, prof_id, f"appointment:{appt_id}", ts.isoformat()))
        test_db.commit()

        with pytest.raises(UndoWindowExpiredError):
            execute_single_click_undo(test_db, e_id, prof_id, current_time=now)

    def test_t2_undo_rejects_read_risk_actions(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Boundary: Non-write_local action (risk='read') raises ActionNotUndoableError."""
        cur = test_db.cursor()
        prof_id = sample_profile["id"]
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) VALUES (?, ?, 'user', 'list', 'list_appointments', 'read', 'appointment:none', ?)",
                    (e_id, prof_id, now.isoformat()))
        test_db.commit()

        with pytest.raises(ActionNotUndoableError):
            execute_single_click_undo(test_db, e_id, prof_id, current_time=now)

    def test_t2_undo_rejects_write_network_actions(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Boundary: Action with risk='write_network' raises ActionNotUndoableError."""
        cur = test_db.cursor()
        prof_id = sample_profile["id"]
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) VALUES (?, ?, 'user', 'send', 'send_portal_message', 'write_network', 'portal:1', ?)",
                    (e_id, prof_id, now.isoformat()))
        test_db.commit()

        with pytest.raises(ActionNotUndoableError):
            execute_single_click_undo(test_db, e_id, prof_id, current_time=now)

    def test_t2_undo_idempotent_double_undo_handling(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Boundary: Re-undoing an already cancelled appointment leaves status cancelled."""
        cur = test_db.cursor()
        prof_id = sample_profile["id"]
        appt_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) VALUES (?, ?, 'A', ?, ?, 'scheduled', ?, ?)",
                    (appt_id, prof_id, now.isoformat(), now.isoformat(), now.isoformat(), now.isoformat()))
        cur.execute("INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
                    (e_id, prof_id, f"appointment:{appt_id}", now.isoformat()))
        test_db.commit()

        execute_single_click_undo(test_db, e_id, prof_id, current_time=now)
        # Second invocation
        execute_single_click_undo(test_db, e_id, prof_id, current_time=now + timedelta(seconds=5))

        cur.execute("SELECT status FROM appointments WHERE id = ?", (appt_id,))
        assert cur.fetchone()[0] == "cancelled"


# ============================================================================
# TIER 3: CROSS-FEATURE PAIRWISE INTERACTIONS
# ============================================================================

class TestTier3CrossFeatureCombinations:
    """Tier 3: Pairwise interactions across Batch 3 feature modules."""

    def test_t3_pairwise_vitals_logging_to_prep_pack_compilation(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Pairwise 1: Logged vitals observations feed directly into consultation prep pack trends."""
        prof_id = sample_profile["id"]
        cur = test_db.cursor()
        now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)

        # 1. Log series of blood pressure readings
        readings = [
            {"systolic": 134, "diastolic": 86, "effective_at": (now - timedelta(days=2, hours=4)).isoformat()},  # AM (08:00)
            {"systolic": 138, "diastolic": 88, "effective_at": (now - timedelta(days=1, hours=3)).isoformat()},  # AM (09:00)
            {"systolic": 142, "diastolic": 92, "effective_at": "2026-10-09T18:00:00Z"},  # PM (18:00)
        ]

        for r in readings:
            obs = normalize_fhir_vitals(r)
            cur.execute(
                "INSERT INTO health_resources (id, profile_id, resource_type, source_type, data, effective_at, recorded_at, created_at, updated_at) "
                "VALUES (?, ?, 'observation', 'manual', ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), prof_id, json.dumps(obs), r["effective_at"], r["effective_at"], now.isoformat(), now.isoformat()),
            )
        test_db.commit()

        # 2. Compute trends
        trends = calculate_diurnal_bp_trends(readings, now_dt=now, user_tz="UTC")

        # 3. Compile Prep Pack
        pack = compile_clinical_prep_pack(
            reason_for_visit="Hypertension Check",
            symptoms=["Occasional dizziness"],
            vitals_trends=trends,
            medications=["Lisinopril 10mg"],
            allergies=[],
            doctor_questions=["Do we need to add a diuretic?"],
            search_excerpts=[],
        )

        # 4. Assert prep pack surfaces the AM/PM trend averages
        assert "136.0/87.0 mmHg" in pack["markdown"]  # Average of 134/86 and 138/88
        assert "142.0/92.0 mmHg" in pack["markdown"]

    def test_t3_pairwise_appointment_creation_to_linked_note_and_after_visit_extraction(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Pairwise 2: Appointment creation -> linked note -> after-visit extraction -> reminder scheduling."""
        prof_id = sample_profile["id"]
        cur = test_db.cursor()
        now = datetime.now(timezone.utc)

        # 1. Create appointment
        appt_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) VALUES (?, ?, 'Neurology Visit', ?, ?, 'confirmed', ?, ?)",
            (appt_id, prof_id, now.isoformat(), (now + timedelta(hours=1)).isoformat(), now.isoformat(), now.isoformat()),
        )

        # 2. Create linked after_visit note
        note_id = str(uuid.uuid4())
        note_content = (
            "Neurology consult debrief:\n"
            "Diagnosed with vestibular migraine.\n"
            "Prescribed Topiramate 25mg nightly.\n"
            "Follow up in 8 weeks."
        )
        cur.execute(
            "INSERT INTO notes (id, profile_id, title, content, type, linked_appointment_id, created_at, updated_at) VALUES (?, ?, 'Neuro Visit Notes', ?, 'after_visit', ?, ?, ?)",
            (note_id, prof_id, note_content, appt_id, now.isoformat(), now.isoformat()),
        )
        test_db.commit()

        # 3. Extract after-visit summary
        summary = extract_after_visit_summary(note_content)
        assert len(summary["diagnoses"]) == 1
        assert "vestibular migraine" in summary["diagnoses"][0]["text"]
        assert summary["medication_adjustments"][0]["citation"] == "[Note Line 3]"

        # 4. Schedule follow-up medication reminder
        rem_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO reminders (id, profile_id, title, category, rrule, next_due_at, created_at, updated_at) VALUES (?, ?, 'Take Topiramate 25mg', 'medication', 'FREQ=DAILY;INTERVAL=1', ?, ?, ?)",
            (rem_id, prof_id, (now + timedelta(hours=8)).isoformat(), now.isoformat(), now.isoformat()),
        )
        test_db.commit()

        cur.execute("SELECT title, category FROM reminders WHERE id = ?", (rem_id,))
        rem_row = cur.fetchone()
        assert rem_row[0] == "Take Topiramate 25mg"
        assert rem_row[1] == "medication"

    def test_t3_pairwise_write_local_to_audit_event_and_single_click_undo_search_invalidation(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Pairwise 3: write_local mutation -> audit event -> single-click undo -> search index invalidation & tombstone."""
        prof_id = sample_profile["id"]
        cur = test_db.cursor()
        now = datetime.now(timezone.utc)

        # 1. Create typed note
        note_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO notes (id, profile_id, title, content, type, is_deleted, created_at, updated_at) VALUES (?, ?, 'Symptom Log', 'Mild fever and cough', 'symptom', 0, ?, ?)",
            (note_id, prof_id, now.isoformat(), now.isoformat()),
        )
        # 2. Record audit event
        e_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) VALUES (?, ?, 'user', 'create', 'create_typed_note', 'write_local', ?, ?)",
            (e_id, prof_id, f"note:{note_id}", now.isoformat()),
        )
        test_db.commit()

        # 3. Execute undo
        undo_res = execute_single_click_undo(test_db, e_id, prof_id, current_time=now + timedelta(hours=2))
        assert undo_res["status"] == "undone"

        # 4. Verify note soft-deleted
        cur.execute("SELECT is_deleted FROM notes WHERE id = ?", (note_id,))
        assert cur.fetchone()[0] == 1

        # 5. Verify search deletion job enqueued
        cur.execute("SELECT kind, payload FROM jobs WHERE profile_id = ? AND kind = 'delete_doc'", (prof_id,))
        job_row = cur.fetchone()
        assert job_row is not None
        assert note_id in job_row[1]

    def test_t3_pairwise_vitals_red_flag_to_emergency_escalation_and_audit_logging(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Pairwise 4: Vitals red flag detection logs emergency audit event and directive."""
        prof_id = sample_profile["id"]
        cur = test_db.cursor()
        now = datetime.now(timezone.utc)

        # 1. Acute symptomatic hypertensive crisis
        vitals = {"systolic": 192, "diastolic": 124}
        symptoms = ["chest pain", "shortness of breath"]
        flag = check_vitals_red_flags(vitals, reported_symptoms=symptoms)
        assert flag.triggered is True

        # 2. System logs refusal/emergency audit event
        e_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp, details) VALUES (?, ?, 'system', 'emergency_escalation', 'check_vitals_red_flags', 'write_local', 'flag:bp_crisis_symptomatic', ?, ?)",
            (e_id, prof_id, now.isoformat(), json.dumps({"directive": flag.directive, "severity": flag.severity})),
        )
        test_db.commit()

        cur.execute("SELECT action, details FROM audit_events WHERE id = ?", (e_id,))
        row = cur.fetchone()
        assert row[0] == "emergency_escalation"
        assert "Call 911" in row[1]

    def test_t3_pairwise_appointment_completion_to_post_visit_prompt_and_note_creation(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Pairwise 5: Appointment end_time passing triggers completed status and follow-up note prompt."""
        prof_id = sample_profile["id"]
        cur = test_db.cursor()
        now = datetime.now(timezone.utc)
        appt_id = str(uuid.uuid4())

        # 1. Appointment that ended 10 minutes ago
        start_time = (now - timedelta(hours=1)).isoformat()
        end_time = (now - timedelta(minutes=10)).isoformat()
        cur.execute(
            "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) VALUES (?, ?, 'Primary Care Physical', ?, ?, 'confirmed', ?, ?)",
            (appt_id, prof_id, start_time, end_time, start_time, start_time),
        )
        test_db.commit()

        # 2. Run post-visit sweep
        cur.execute("SELECT id, title, status, end_time FROM appointments WHERE profile_id = ?", (prof_id,))
        rows = cur.fetchall()
        appts = [{"id": r[0], "title": r[1], "status": r[2], "end_time": r[3]} for r in rows]

        completed_ids, prompts = evaluate_post_visit_transitions(appts, current_time=now)
        assert appt_id in completed_ids
        assert len(prompts) == 1

        # 3. Update appointment status in DB
        cur.execute("UPDATE appointments SET status = 'completed' WHERE id = ?", (appt_id,))
        # 4. Create linked note in response to prompt
        note_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO notes (id, profile_id, title, content, type, linked_appointment_id, created_at, updated_at) VALUES (?, ?, 'PCP Debrief', 'Vaccines updated', 'after_visit', ?, ?, ?)",
            (note_id, prof_id, appt_id, now.isoformat(), now.isoformat()),
        )
        test_db.commit()

        cur.execute("SELECT status FROM appointments WHERE id = ?", (appt_id,))
        assert cur.fetchone()[0] == "completed"

    def test_t3_pairwise_rrule_reminder_to_job_runner_snooze_and_overdue_coalescing(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Pairwise 6: RRULE daily reminder triggers, advances, gets snoozed, and coalesces if abandoned."""
        prof_id = sample_profile["id"]
        cur = test_db.cursor()
        t0 = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
        rem_id = str(uuid.uuid4())

        # 1. Schedule daily reminder
        cur.execute(
            "INSERT INTO reminders (id, profile_id, title, category, rrule, next_due_at, status, created_at, updated_at) VALUES (?, ?, 'Log Morning BP', 'vitals', 'FREQ=DAILY;INTERVAL=1', ?, 'pending', ?, ?)",
            (rem_id, prof_id, t0.isoformat(), t0.isoformat(), t0.isoformat()),
        )
        test_db.commit()

        # 2. Reminder fires and user snoozes +1h
        cur.execute("SELECT id, status, next_due_at FROM reminders WHERE id = ?", (rem_id,))
        row = cur.fetchone()
        rem_dict = {"id": row[0], "status": row[1], "next_due_at": row[2]}

        snoozed = apply_reminder_snooze(rem_dict, "+1h", t0)
        cur.execute("UPDATE reminders SET status = ?, snooze_until = ? WHERE id = ?", (snoozed["status"], snoozed["snooze_until"], rem_id))
        test_db.commit()

        # 3. 26 hours later with no user interaction -> overdue coalescing sweep
        t_later = t0 + timedelta(hours=26)
        cur.execute("SELECT id, status, next_due_at, snooze_until FROM reminders WHERE id = ?", (rem_id,))
        row2 = cur.fetchone()
        active_rem = {"id": row2[0], "status": row2[1], "next_due_at": row2[2], "snooze_until": row2[3]}

        coalesced = coalesce_overdue_reminders([active_rem], current_time=t_later)
        assert coalesced[0]["status"] == "missed"


# ============================================================================
# TIER 4: REAL-WORLD CLINICAL WORKLOAD SCENARIOS
# ============================================================================

class TestTier4RealWorldScenarios:
    """Tier 4: End-to-end patient consultation journey, chronic hypertension, pediatric, and diabetic workflows."""

    def test_t4_scenario_end_to_end_patient_consultation_journey(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Scenario 1: Complete patient journey from booking prep to post-visit extraction and calendar export.

        Workflow:
        1. Assistant drafts 'How to Book' script and portal message for cardiologist Dr. House.
        2. Appointment created with status 'requested', later updated to 'confirmed'.
        3. User logs vitals over past week; system synthesizes 7-day AM/PM trends.
        4. Assistant compiles Clinical Visit Prep Pack with doctor questions and past notes.
        5. Appointment end_time passes; post-visit status transitions to 'completed'.
        6. User enters post-visit notes; assistant extracts meds/diagnoses with [Note Line X] citations.
        7. System schedules recurring medication reminder and exports sanitized RFC 5545 .ics calendar.
        """
        prof_id = sample_profile["id"]
        cur = test_db.cursor()
        t_start = datetime(2026, 10, 10, 10, 0, 0, tzinfo=timezone.utc)

        # Step 1 & 2: How to Book draft and appointment creation
        drafts = generate_how_to_book_drafts(
            title="Cardiology Visit",
            provider_name="Dr. Gregory House",
            specialty="Cardiology",
            clinic_phone="555-0199",
            reason="Unexplained syncopal episodes",
        )
        assert drafts["status"] == "requested"

        appt_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO appointments (id, profile_id, title, provider_name, specialty, clinic_phone, start_time, end_time, status, reason, created_at, updated_at) "
            "VALUES (?, ?, 'Cardiology Visit', 'Dr. Gregory House', 'Cardiology', '555-0199', ?, ?, 'confirmed', 'Unexplained syncope', ?, ?)",
            (appt_id, prof_id, t_start.isoformat(), (t_start + timedelta(hours=1)).isoformat(), t_start.isoformat(), t_start.isoformat()),
        )
        test_db.commit()

        # Step 3: Vitals logging & trends
        readings = [
            {"systolic": 118, "diastolic": 76, "effective_at": (t_start - timedelta(days=2)).isoformat()},
            {"systolic": 115, "diastolic": 74, "effective_at": (t_start - timedelta(days=1)).isoformat()},
        ]
        trends = calculate_diurnal_bp_trends(readings, now_dt=t_start, user_tz="UTC")

        # Step 4: Prep Pack compilation
        pack = compile_clinical_prep_pack(
            reason_for_visit="Syncope Evaluation",
            symptoms=["Brief loss of consciousness", "Post-ictal fatigue"],
            vitals_trends=trends,
            medications=["None"],
            allergies=["Penicillin"],
            doctor_questions=["Could this be vasovagal or cardiac related?", "Do I need a 24-hour Holter monitor?"],
            search_excerpts=["2025 ECG: Normal sinus rhythm."],
        )
        assert pack["questions_count"] == 2
        assert "Syncope Evaluation" in pack["markdown"]

        # Step 5: Post-visit transition
        t_visit_end = t_start + timedelta(hours=2)
        cur.execute("SELECT id, title, status, end_time FROM appointments WHERE id = ?", (appt_id,))
        row = cur.fetchone()
        completed_ids, _ = evaluate_post_visit_transitions([{"id": row[0], "title": row[1], "status": row[2], "end_time": row[3]}], current_time=t_visit_end)
        assert appt_id in completed_ids

        cur.execute("UPDATE appointments SET status = 'completed' WHERE id = ?", (appt_id,))
        test_db.commit()

        # Step 6: Post-visit notes & extraction
        note_text = (
            "Visit Summary with Dr. House:\n"
            "Diagnosed with neurocardiogenic syncope.\n"
            "Prescribed Fludrocortisone 0.1mg daily.\n"
            "Ordered tilt table test in 4 weeks.\n"
            "Follow up in 2 months."
        )
        summary = extract_after_visit_summary(note_text)
        assert summary["diagnoses"][0]["citation"] == "[Note Line 2]"
        assert summary["medication_adjustments"][0]["citation"] == "[Note Line 3]"
        assert summary["disclaimer"] == NON_CLINICAL_DISCLAIMER

        # Step 7: Medication reminder and .ics export
        rem_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO reminders (id, profile_id, title, category, rrule, next_due_at, created_at, updated_at) "
            "VALUES (?, ?, 'Take Fludrocortisone 0.1mg', 'medication', 'FREQ=DAILY;INTERVAL=1', ?, ?, ?)",
            (rem_id, prof_id, (t_visit_end + timedelta(hours=14)).isoformat(), t_visit_end.isoformat(), t_visit_end.isoformat()),
        )
        test_db.commit()

        cal_ics = generate_ics_calendar([{
            "id": rem_id,
            "title": "Take Fludrocortisone 0.1mg",
            "category": "medication",
            "next_due_at": (t_visit_end + timedelta(hours=14)).isoformat(),
        }], sanitize_phi=True)

        assert "BEGIN:VCALENDAR" in cal_ics
        assert "Carefold Medication Reminder" in cal_ics
        assert "Fludrocortisone" not in cal_ics  # PHI shielded

    def test_t4_scenario_chronic_hypertension_tracking_with_am_pm_trends(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Scenario 2: Chronic hypertension patient tracking morning vs evening blood pressure with red flag escalation.

        Workflow:
        1. Patient logs readings over 30 days.
        2. AM averages classify as Elevated; PM averages classify as Stage 1.
        3. Sudden acute spike (184/122 with severe back pain) triggers immediate symptomatic crisis directive.
        4. Directive directs patient to Call 911 immediately.
        """
        now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
        readings = [
            # Morning readings (08:00)
            {"systolic": 124, "diastolic": 78, "effective_at": (now - timedelta(days=20, hours=4)).isoformat()},
            {"systolic": 126, "diastolic": 79, "effective_at": (now - timedelta(days=10, hours=4)).isoformat()},
            # Evening readings (19:00)
            {"systolic": 134, "diastolic": 86, "effective_at": (now - timedelta(days=15, hours=-7)).isoformat()},
            {"systolic": 136, "diastolic": 88, "effective_at": (now - timedelta(days=5, hours=-7)).isoformat()},
        ]

        trends = calculate_diurnal_bp_trends(readings, now_dt=now, user_tz="UTC")
        t30 = trends["30_day"]
        assert t30["am"]["classification"] == "Elevated"
        assert t30["pm"]["classification"] == "Stage 1"

        # Acute symptomatic spike
        emergency_reading = {"systolic": 184, "diastolic": 122}
        flag = check_vitals_red_flags(emergency_reading, reported_symptoms=["severe back pain"])
        assert flag.triggered is True
        assert flag.category == "bp_crisis_symptomatic"
        assert flag.severity == "emergency"
        assert "Call 911" in flag.directive

    def test_t4_scenario_pediatric_well_child_visit_with_weight_suppression(self, sample_profile: Dict[str, Any]):
        """Scenario 3: Pediatric well-child visit with clinical BMI suppression (< 24 months) and hide_weight preference.

        Workflow:
        1. 14-month-old infant visits pediatrician.
        2. Weight (10.2 kg) and Height (78 cm) recorded.
        3. Pediatric engine suppresses BMI because child is < 24 months.
        4. Parent updates profile preferences with hide_weight=True.
        5. UI and exports mask weight and BMI values.
        """
        # 14-month-old: Clinical suppression
        res_infant = calculate_pediatric_bmi_percentile(
            age_months=14, gender="female", weight_kg=10.2, height_cm=78.0, hide_weight=False
        )
        assert res_infant["suppressed"] is True
        assert res_infant["bmi"] is None
        assert "under 24 months" in res_infant["reason"]

        # 4-year-old child with hide_weight toggle enabled
        res_hidden = calculate_pediatric_bmi_percentile(
            age_months=48, gender="male", weight_kg=16.0, height_cm=102.0, hide_weight=True
        )
        assert res_hidden["suppressed"] is True
        assert res_hidden["weight_hidden"] is True
        assert res_hidden["bmi"] is None

    def test_t4_scenario_diabetic_crisis_emergency_directive_and_activity_undo_rollback(self, test_db: sqlite3.Connection, sample_profile: Dict[str, Any]):
        """Scenario 4: Diabetic hypoglycemic crisis emergency directive and user typo rollback via single-click undo.

        Workflow:
        1. Patient with Type 1 Diabetes accidentally logs blood glucose as 42 mg/dL (meant 142 mg/dL).
        2. System triggers severe hypoglycemia red flag with Rule of 15 directive.
        3. Audit event recorded for the logged observation.
        4. Patient realizes typo and invokes single-click undo on activity timeline within 7 days.
        5. Observation is marked tombstone, and audited reversal event is recorded.
        6. Patient logs correct reading (142 mg/dL), which evaluates as normal.
        """
        prof_id = sample_profile["id"]
        cur = test_db.cursor()
        now = datetime.now(timezone.utc)

        # 1. Accidental typo: 42 mg/dL
        flag = check_vitals_red_flags({"blood_glucose": 42.0})
        assert flag.triggered is True
        assert flag.category == "severe_hypoglycemia"
        assert "Rule of 15" in flag.directive

        hr_id = str(uuid.uuid4())
        obs = normalize_fhir_vitals({"blood_glucose": 42.0})
        cur.execute(
            "INSERT INTO health_resources (id, profile_id, resource_type, source_type, data, status, effective_at, recorded_at, created_at, updated_at) "
            "VALUES (?, ?, 'observation', 'manual', ?, 'active', ?, ?, ?, ?)",
            (hr_id, prof_id, json.dumps(obs), now.isoformat(), now.isoformat(), now.isoformat(), now.isoformat()),
        )
        e_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) VALUES (?, ?, 'user', 'record', 'record_vitals', 'write_local', ?, ?)",
            (e_id, prof_id, f"health_resource:{hr_id}", now.isoformat()),
        )
        test_db.commit()

        # 4 & 5. Single-click undo within 10 minutes
        undo_res = execute_single_click_undo(test_db, e_id, prof_id, current_time=now + timedelta(minutes=10))
        assert undo_res["status"] == "undone"

        cur.execute("SELECT status FROM health_resources WHERE id = ?", (hr_id,))
        assert cur.fetchone()[0] == "tombstone"

        cur.execute("SELECT action, tool FROM audit_events WHERE action = 'undo'", ())
        assert cur.fetchone() is not None

        # 6. Re-log correct reading (142 mg/dL)
        corrected_flag = check_vitals_red_flags({"blood_glucose": 142.0})
        assert corrected_flag.triggered is False
        assert corrected_flag.severity == "normal"
