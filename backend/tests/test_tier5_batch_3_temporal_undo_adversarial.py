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

"""Tier 5 White-Box Adversarial Stress Test Suite for Carefold Autonomy Batch 3 (AU-33, AU-34, AU-35, AU-40).

Conducts rigorous white-box stress testing across:
1. Consultation Prep Pack Compiler & ExecutionPlan interface (AU-33, AU-34):
   - 5-section Markdown dossier compilation and empty fallbacks
   - Doctor question clamping (max 5) and prioritization hierarchy (user -> vitals -> specialty)
   - Multi-tenant fail-closed scoping on appointment linking
   - ExecutionPlan dict-subscripting (__getitem__, __contains__, get, to_dict)
2. Typed Notes & After-Visit Extraction Engine (AU-35):
   - 7 canonical categories validation and legacy mapping rules
   - 1-indexed [Note Line X] source line citations across multi-line/blank-line notes
   - Prescription dosage unit parsing vs strict OTC remedy exclusion
   - Mandatory non-clinical disclaimer attachment
   - Background index_doc search synchronization job enqueuing
3. Single-Click Undo Engine (AU-40):
   - Microsecond boundary precision on strict 7-day undo window
   - write_local risk tier invariant enforcement (failing closed on read/write_network/admin)
   - Entity rollback resolution across all 4 types (health_resource, appointment, reminder, note)
   - Search index invalidation (delete_doc job) on note undo
   - Anti-recursion protection preventing undoing of undo reversals
   - Idempotency handling (idempotent=True vs idempotent=False)
   - Malformed external_ref validation
   - Cross-profile isolation on undo operations
4. Activity Timeline Engine & Synthesizer:
   - Defensive _safe_float and graceful degradation on malformed/garbage telemetry
   - Natural language synthesis across all 7 tool categories
5. REST API RBAC & Multi-Tenant Isolation:
   - Full RBAC matrix: manage, view_clinical, view_paperwork, unauthenticated
   - Cross-profile appointment linkage prevention on note and prep pack creation
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
import sqlite3
from typing import Any, Dict, List, Optional
import uuid

from fastapi import status
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.clinical.activity import (
    compute_is_undoable,
    format_audit_event_as_activity_item,
    get_profile_activity_timeline,
    synthesize_activity_summary,
)
from carefold.clinical.notes import (
    NON_CLINICAL_DISCLAIMER as NOTES_DISCLAIMER,
    NoteType,
    VALID_NOTE_TYPES,
    extract_after_visit_summary,
    validate_note_type,
)
from carefold.clinical.prep_pack import (
    NON_CLINICAL_DISCLAIMER as PREP_DISCLAIMER,
    compile_clinical_prep_pack,
    compile_execution_plan,
    generate_and_persist_prep_pack,
    synthesize_doctor_questions,
)
from carefold.clinical.undo import (
    ActionNotUndoableError,
    AlreadyUndoneError,
    EntityNotFoundError,
    InvalidExternalRefError,
    UndoWindowExpiredError,
    _resolve_action_not_undoable_error,
    _resolve_undo_window_expired_error,
    execute_single_click_undo,
    execute_single_click_undo_async,
)
from carefold.config import settings
from carefold.db.models import (
    Appointment,
    AuditEventRecord,
    HealthResource,
    Job,
    Note,
    Profile,
    ProfileAccess,
    Reminder,
    User,
)
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app
from carefold.schemas.notes import TypedNoteCreateRequest
from carefold.schemas.plan import AgentTask, ExecutionMode, ExecutionPlan


def run_async(coro):
    """Executes asynchronous coroutine synchronously."""
    return asyncio.run(coro)


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def sync_sqlite_db() -> sqlite3.Connection:
    """In-memory SQLite connection configured with the audit, clinical, and job schemas."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE audit_events (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            tool TEXT NOT NULL,
            risk TEXT NOT NULL,
            external_ref TEXT,
            timestamp TEXT NOT NULL,
            details TEXT DEFAULT '{}'
        );
    """)
    cur.execute("""
        CREATE TABLE health_resources (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            status TEXT NOT NULL,
            data TEXT NOT NULL,
            effective_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE appointments (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            title TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'scheduled',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE reminders (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            title TEXT NOT NULL,
            next_due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE notes (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            profile_id TEXT,
            payload TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)

    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
async def async_db_session():
    """Provides an isolated AsyncSession with all SQLAlchemy models initialized."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def rbac_api_env(monkeypatch):
    """Sets up an isolated in-memory DB, SQL auth provider, and test users/profiles for RBAC testing."""
    async def _setup():
        engine = create_db_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = get_session_factory(engine)
        auth_adapter = SqlAuthAdapter(session_factory=session_factory)

        monkeypatch.setattr(settings, "auth_provider", "local")
        set_auth_port(auth_adapter)

        # 1. Alice (Profile Owner, full 'manage' access)
        alice = await auth_adapter.register_user(
            email="alice@adversarial.test",
            username="alice_adv",
            password="AlicePassword123!",
            full_name="Alice Owner",
            role="member",
            auth_provider="local",
        )
        alice_session = await auth_adapter.create_session(alice.id)

        # 2. Charlie (Clinician, 'view_clinical' access only)
        charlie = await auth_adapter.register_user(
            email="charlie@adversarial.test",
            username="charlie_adv",
            password="CharliePassword123!",
            full_name="Charlie Clinician",
            role="member",
            auth_provider="local",
        )
        charlie_session = await auth_adapter.create_session(charlie.id)

        # 3. Dan (Biller, 'view_paperwork' access only)
        dan = await auth_adapter.register_user(
            email="dan@adversarial.test",
            username="dan_adv",
            password="DanPassword123!",
            full_name="Dan Paperwork",
            role="member",
            auth_provider="local",
        )
        dan_session = await auth_adapter.create_session(dan.id)

        # 4. Eve (Attacker, zero permissions on Alice's profile)
        eve = await auth_adapter.register_user(
            email="eve@adversarial.test",
            username="eve_adv",
            password="EvePassword123!",
            full_name="Eve Attacker",
            role="member",
            auth_provider="local",
        )
        eve_session = await auth_adapter.create_session(eve.id)

        profile_alice_id = str(uuid.uuid4())
        profile_eve_id = str(uuid.uuid4())

        async with session_factory() as session:
            prof_a = Profile(id=profile_alice_id, user_id=alice.id, name="Alice Profile")
            session.add(prof_a)

            prof_e = Profile(id=profile_eve_id, user_id=eve.id, name="Eve Profile")
            session.add(prof_e)

            session.add(ProfileAccess(profile_id=profile_alice_id, user_id=charlie.id, access_level="view_clinical"))
            session.add(ProfileAccess(profile_id=profile_alice_id, user_id=dan.id, access_level="view_paperwork"))

            await session.commit()

        return {
            "engine": engine,
            "session_factory": session_factory,
            "profile_alice_id": profile_alice_id,
            "profile_eve_id": profile_eve_id,
            "alice": alice,
            "alice_token": alice_session.token,
            "charlie": charlie,
            "charlie_token": charlie_session.token,
            "dan": dan,
            "dan_token": dan_session.token,
            "eve": eve,
            "eve_token": eve_session.token,
        }

    env = run_async(_setup())

    async def _override_get_db():
        async with env["session_factory"]() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    yield env
    app.dependency_overrides.pop(get_db, None)


# ============================================================================
# Section 1: Consultation Prep Pack & ExecutionPlan Invariants (AU-33, AU-34)
# ============================================================================

def test_adv_prep_pack_five_sections_and_mandatory_disclaimer():
    """Adversarial Test 1: Verifies compile_clinical_prep_pack synthesizes all 5 sections and the mandatory disclaimer."""
    dossier = compile_clinical_prep_pack(
        reason_for_visit="Hypertension Re-evaluation",
        symptoms=["Occasional dizziness upon standing", "Morning headaches"],
        vitals_trends={
            "30_day": {
                "am": {"systolic": 142, "diastolic": 92, "classification": "Stage 2"},
                "pm": {"systolic": 136, "diastolic": 86, "classification": "Stage 1"},
            },
            "90_day": {
                "am": {"systolic": 140, "diastolic": 90, "classification": "Stage 2"},
                "pm": {"systolic": 134, "diastolic": 84, "classification": "Stage 1"},
            },
        },
        medications=["Lisinopril 10mg", "Amlodipine 5mg"],
        allergies=["Penicillin"],
        doctor_questions=["Should we adjust my dosage?", "Is home monitoring twice daily sufficient?"],
        search_excerpts=["Past echocardiogram showed normal ejection fraction.", "History of essential hypertension."],
        specialty="Cardiology",
        provider_name="Dr. Gregory House",
        appointment_date="2026-10-20T09:00:00Z",
    )

    md = dossier["markdown"]
    assert "# Clinical Visit Preparation Dossier" in md
    assert "**Chief Reason for Visit**: Hypertension Re-evaluation" in md
    assert "**Provider**: Dr. Gregory House (Cardiology)" in md
    assert "**Scheduled Date**: 2026-10-20T09:00:00Z" in md

    # All 5 sections verified
    assert "## 1. Recent Symptoms Timeline" in md
    assert "- Occasional dizziness upon standing" in md
    assert "## 2. Vitals Trends Summary" in md
    assert "142/92 mmHg (Stage 2)" in md
    assert "## 3. Active Medications & Allergies" in md
    assert "Lisinopril 10mg, Amlodipine 5mg" in md
    assert "Penicillin" in md
    assert "## 4. Prioritized Doctor Questions" in md
    assert "1. Should we adjust my dosage?" in md
    assert "## 5. Relevant History from Prior Records" in md
    assert "> Past echocardiogram showed normal ejection fraction." in md

    # Disclaimer attached
    assert PREP_DISCLAIMER in md
    assert dossier["questions_count"] == 2
    assert dossier["has_vitals_summary"] is True


def test_adv_prep_pack_empty_vitals_symptoms_fallbacks():
    """Adversarial Test 2: Verifies robust fallbacks for zero symptoms, zero vitals, zero meds, and zero excerpts."""
    dossier = compile_clinical_prep_pack(
        reason_for_visit="Annual Wellness Checkup",
        symptoms=[],
        vitals_trends={},
        medications=[],
        allergies=[],
        doctor_questions=[],
        search_excerpts=[],
    )

    md = dossier["markdown"]
    assert "## 1. Recent Symptoms Timeline" in md
    assert "- No recent acute symptoms reported." in md
    assert "## 2. Vitals Trends Summary" in md
    assert "- No recent vitals recorded." in md
    assert "## 3. Active Medications & Allergies" in md
    assert "- **Medications**: None reported" in md
    assert "- **Allergies**: No known drug allergies" in md
    assert "## 4. Prioritized Doctor Questions" in md
    assert "1. What are my primary treatment goals and next steps?" in md
    assert "## 5. Relevant History from Prior Records" not in md  # Omitted when no excerpts
    assert PREP_DISCLAIMER in md
    assert dossier["has_vitals_summary"] is False


def test_adv_prep_pack_doctor_question_clamping_and_priority():
    """Adversarial Test 3: Verifies question clamping strictly clamps to max 5 questions and prioritizes user questions."""
    user_questions = [
        "User Q1: Why do my ankles swell?",
        "User Q2: Can I reduce my water pill?",
        "User Q3: Is salt substitute safe?",
        "User Q4: Should I get a treadmill test?",
        "User Q5: How often should I check kidney function?",
        "User Q6: Overflow question that should be clamped",
        "User Q7: Second overflow question",
    ]
    trends = {
        "30_day": {
            "am": {"classification": "Stage 2"},
            "pm": {"classification": "Stage 2"},
        }
    }

    questions = synthesize_doctor_questions(
        specialty="Cardiology",
        vitals_trends=trends,
        custom_questions=user_questions,
    )

    # Must be strictly clamped to 5
    assert len(questions) == 5
    # User questions must have taken all 5 spots; overflow dropped
    assert questions == user_questions[:5]
    assert "User Q6: Overflow question that should be clamped" not in questions


def test_adv_prep_pack_synthesize_doctor_questions_vitals_abnormalities():
    """Adversarial Test 4: Verifies vitals abnormalities generate prioritized doctor questions ahead of specialty banks."""
    trends = {
        "30_day": {
            "am": {"classification": "Hypertensive Crisis"},
            "pm": {"classification": "Stage 2"},
        }
    }

    questions = synthesize_doctor_questions(
        specialty="Cardiology",
        vitals_trends=trends,
        custom_questions=["Should I stop taking caffeine?"],
    )

    assert len(questions) <= 5
    assert questions[0] == "Should I stop taking caffeine?"  # User question 1st
    assert "My home blood pressure readings have been elevated in recent logs." in questions[1]  # Vitals Q 2nd
    # Remaining slots filled from cardiology bank
    assert any("target blood pressure range" in q for q in questions[2:])


def test_adv_prep_pack_specialty_question_bank_exhaustion_and_general_fallback():
    """Adversarial Test 5: Verifies that when specialty questions are fewer than 3, general bank fills up to minimum 3."""
    questions = synthesize_doctor_questions(
        specialty="gastro",
        vitals_trends=None,
        custom_questions=[],
    )

    assert len(questions) == 3
    assert any("food and symptom journal" in q for q in questions)
    assert any("dietary modifications" in q for q in questions)
    assert any("diagnostic tests" in q for q in questions)


@pytest.mark.asyncio
async def test_adv_prep_pack_cross_profile_appointment_linking_rejected(async_db_session: AsyncSession):
    """Adversarial Test 6: Verifies multi-tenant fail-closed scoping rejects linking appointment belonging to another profile."""
    prof_victim = Profile(id=str(uuid.uuid4()), name="Victim Profile")
    prof_attacker = Profile(id=str(uuid.uuid4()), name="Attacker Profile")
    async_db_session.add_all([prof_victim, prof_attacker])

    now = datetime.now(timezone.utc)
    appt_victim = Appointment(
        id=str(uuid.uuid4()),
        profile_id=prof_victim.id,
        title="Victim Oncology Consult",
        start_time=now,
        end_time=now + timedelta(hours=1),
        status="scheduled",
        created_at=now,
        updated_at=now,
    )
    async_db_session.add(appt_victim)
    await async_db_session.commit()

    # Attacker attempts to compile prep pack for their profile linking victim's appointment
    with pytest.raises(ValueError) as exc_info:
        await generate_and_persist_prep_pack(
            session=async_db_session,
            profile_id=prof_attacker.id,
            appointment_id=appt_victim.id,
        )
    assert "not found for profile" in str(exc_info.value)


@pytest.mark.asyncio
async def test_adv_prep_pack_non_existent_appointment_or_empty_profile_raises(async_db_session: AsyncSession):
    """Adversarial Test 7: Verifies fail-closed ValueError on non-existent appointment or empty profile_id."""
    prof = Profile(id=str(uuid.uuid4()), name="Valid Profile")
    async_db_session.add(prof)
    await async_db_session.commit()

    # Non-existent appointment
    with pytest.raises(ValueError) as exc:
        await generate_and_persist_prep_pack(
            session=async_db_session,
            profile_id=prof.id,
            appointment_id="non-existent-uuid",
        )
    assert "not found for profile" in str(exc.value)

    # Empty profile_id
    with pytest.raises(ValueError) as exc_empty:
        await generate_and_persist_prep_pack(
            session=async_db_session,
            profile_id="   ",
        )
    assert "profile_id must be a non-empty string" in str(exc_empty.value)


def test_adv_execution_plan_dict_subscripting_and_membership():
    """Adversarial Test 8: Verifies ExecutionPlan dict subscripting (__getitem__, __contains__, get, to_dict)."""
    plan = compile_execution_plan(
        intent="visit_prep",
        parameters={"specialty": "Cardiology", "appointment_id": "appt-99"},
    )

    # 1. __getitem__ access
    assert plan["intent"] == "visit_prep"
    assert plan["status"] == "compiled"
    assert plan["mode"] == "pipeline"  # Enum serialized to string value
    assert len(plan["steps"]) == 4
    assert len(plan["tasks"]) == 4

    # 2. Key error on non-existent key
    with pytest.raises(KeyError):
        _ = plan["non_existent_property"]

    # 3. __contains__ membership
    assert "intent" in plan
    assert "steps" in plan
    assert "tasks" in plan
    assert "mode" in plan
    assert "unknown_key_xyz" not in plan

    # 4. .get() method
    assert plan.get("intent") == "visit_prep"
    assert plan.get("missing_key", "default_val") == "default_val"
    assert plan.get("mode") == "pipeline"

    # 5. to_dict serialization
    d = plan.to_dict()
    assert isinstance(d, dict)
    assert d["intent"] == "visit_prep"
    assert d["mode"] == "pipeline"
    assert len(d["steps"]) == 4


def test_adv_execution_plan_invalid_intent_raises_value_error():
    """Adversarial Test 9: Verifies compile_execution_plan fails closed on arbitrary/invalid intent."""
    with pytest.raises(ValueError) as exc_info:
        compile_execution_plan("malicious_unsupported_intent")
    assert "Unknown ExecutionPlan intent" in str(exc_info.value)


def test_adv_execution_plan_task_alias_synchronization():
    """Adversarial Test 10: Verifies AgentTask synchronizes instructions/task_description and depends_on/dependencies."""
    task1 = AgentTask(agent_id="test-agent", task_description="Perform ECG analysis")
    assert task1.instructions == "Perform ECG analysis"

    task2 = AgentTask(agent_id="test-agent", instructions="Check telemetry logs")
    assert task2.task_description == "Check telemetry logs"

    task3 = AgentTask(agent_id="test-agent", dependencies=["task_a", "task_b"])
    assert task3.depends_on == ["task_a", "task_b"]

    task4 = AgentTask(agent_id="test-agent", depends_on=["task_c"])
    assert task4.dependencies == ["task_c"]


# ============================================================================
# Section 2: Typed Notes & After-Visit Extraction Engine (AU-35)
# ============================================================================

def test_adv_typed_notes_canonical_categories_and_legacy_rejection():
    """Adversarial Test 11: Verifies 7 canonical note categories and strict fail-closed rejection of non-canonical types."""
    assert len(VALID_NOTE_TYPES) == 7
    canonical_list = ["visit", "symptom", "question", "after_visit", "school", "scratchpad", "general"]
    for cat in canonical_list:
        assert cat in VALID_NOTE_TYPES
        assert validate_note_type(cat) == cat
        assert validate_note_type(cat.upper()) == cat
        assert validate_note_type(f"  {cat}  ") == cat

    # Non-canonical types must be rejected
    invalid_types = ["soap", "h&p", "billing", "operative", "", "   "]
    for bad in invalid_types:
        with pytest.raises(ValueError):
            validate_note_type(bad, allow_legacy=False)

    # Legacy mappings rejected when allow_legacy=False
    with pytest.raises(ValueError):
        validate_note_type("clinical_prep", allow_legacy=False)
    with pytest.raises(ValueError):
        validate_note_type("visit_summary", allow_legacy=False)

    # Legacy mappings mapped when allow_legacy=True
    assert validate_note_type("clinical_prep", allow_legacy=True) == "question"
    assert validate_note_type("visit_summary", allow_legacy=True) == "after_visit"


def test_adv_after_visit_extraction_one_indexed_line_citations_with_blank_lines():
    """Adversarial Test 12: Verifies exact 1-indexed [Note Line X] line citations across arbitrary interleaved blank lines."""
    note_content = (
        "\n"                                                           # Line 1: blank
        "Clinic Encounter Notes - 2026-10-13\n"                        # Line 2
        "\n"                                                           # Line 3: blank
        "Diagnosis: Chronic obstructive pulmonary disease\n"           # Line 4: Diagnosis
        "\n"                                                           # Line 5: blank
        "Prescribed albuterol 90 mcg inhaler\n"                        # Line 6: Medication
        "\n"                                                           # Line 7: blank
        "Ordered test: Spirometry with bronchodilator responsiveness\n" # Line 8: Test
        "Follow up in 6 weeks with pulmonary clinic\n"                 # Line 9: Follow-up
        "Reminder: Bring symptom diary to next visit\n"                # Line 10: Reminder
        "\n"                                                           # Line 11: blank
    )

    summary = extract_after_visit_summary(note_content)

    assert len(summary["diagnoses"]) == 1
    assert summary["diagnoses"][0]["citation"] == "[Note Line 4]"
    assert "Chronic obstructive pulmonary disease" in summary["diagnoses"][0]["text"]

    assert len(summary["medication_adjustments"]) == 1
    assert summary["medication_adjustments"][0]["citation"] == "[Note Line 6]"
    assert "albuterol 90 mcg" in summary["medication_adjustments"][0]["text"]

    assert len(summary["ordered_tests"]) == 1
    assert summary["ordered_tests"][0]["citation"] == "[Note Line 8]"

    assert len(summary["follow_up_timeline"]) == 1
    assert summary["follow_up_timeline"][0]["citation"] == "[Note Line 9]"

    assert len(summary["recommended_reminders"]) == 1
    assert summary["recommended_reminders"][0]["citation"] == "[Note Line 10]"

    assert summary["disclaimer"] == NOTES_DISCLAIMER
    assert summary["extracted_items_count"] == 5


def test_adv_after_visit_extraction_prescription_units_vs_otc_exclusion():
    """Adversarial Test 13: Verifies dosage unit parsing for prescriptions while strictly excluding generic OTC remedies."""
    note_content = (
        "Prescribed atorvastatin 20 mg daily at bedtime\n"
        "Increased metoprolol succinate to 50 mg tablets once daily\n"
        "Start taking over-the-counter ibuprofen 400 mg for minor muscle aches\n"
        "Take OTC acetaminophen 500mg as needed for fever\n"
        "Recommend over-the-counter multivitamin daily\n"
    )

    summary = extract_after_visit_summary(note_content)
    meds = summary["medication_adjustments"]

    # Exactly the 2 prescriptions should be captured
    assert len(meds) == 2
    med_texts = [m["text"] for m in meds]
    assert any("atorvastatin 20 mg" in t for t in med_texts)
    assert any("metoprolol succinate to 50 mg" in t for t in med_texts)

    # OTC remedies must be completely excluded
    for t in med_texts:
        assert "over-the-counter" not in t.lower()
        assert "otc" not in t.lower()
        assert "ibuprofen" not in t.lower()
        assert "acetaminophen" not in t.lower()


@pytest.mark.asyncio
async def test_adv_typed_note_creation_enqueues_index_job(async_db_session: AsyncSession):
    """Adversarial Test 14: Verifies generate_and_persist_prep_pack commits Note and enqueues index_doc job with idempotency key."""
    prof = Profile(id=str(uuid.uuid4()), name="Indexing Test Profile")
    async_db_session.add(prof)
    await async_db_session.commit()

    res = await generate_and_persist_prep_pack(
        session=async_db_session,
        profile_id=prof.id,
        visit_reason="Diabetic Neuropathy Evaluation",
    )

    note_id = res["note_id"]
    note_stmt = select(Note).where(Note.id == note_id)
    saved_note = (await async_db_session.execute(note_stmt)).scalar_one_or_none()
    assert saved_note is not None
    assert saved_note.type == "visit"

    # Verify search index job enqueued
    job_stmt = select(Job).where(Job.profile_id == prof.id, Job.kind == "index_doc")
    jobs = (await async_db_session.execute(job_stmt)).scalars().all()
    assert len(jobs) >= 1
    job = jobs[0]
    payload = json.loads(job.payload)
    assert payload["document_id"] == note_id
    assert payload["doc_type"] == "note"
    assert "index:note:" in job.idempotency_key


# ============================================================================
# Section 3: Single-Click Undo Engine — Temporal & Risk Invariants (AU-40)
# ============================================================================

def test_adv_undo_exact_microsecond_boundary_precision_sync(sync_sqlite_db: sqlite3.Connection):
    """Adversarial Test 15: Verifies strict microsecond boundary on 7-day undo window in synchronous SQLite engine."""
    cur = sync_sqlite_db.cursor()
    prof_id = "prof-boundary"
    appt_pass_id = str(uuid.uuid4())
    appt_fail_id = str(uuid.uuid4())
    event_pass_id = str(uuid.uuid4())
    event_fail_id = str(uuid.uuid4())

    now = datetime(2026, 10, 13, 12, 0, 0, 0, tzinfo=timezone.utc)
    ts_exact_7d = now - timedelta(days=7)                           # Exactly 7 days old: ALLOWED
    ts_expired_1us = now - timedelta(days=7, microseconds=1)        # 7 days + 1 microsecond: EXPIRED

    cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Boundary Patient')", (prof_id,))
    cur.execute(
        "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) "
        "VALUES (?, ?, 'Appt Pass', ?, ?, 'scheduled', ?, ?)",
        (appt_pass_id, prof_id, now.isoformat(), now.isoformat(), now.isoformat(), now.isoformat()),
    )
    cur.execute(
        "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) "
        "VALUES (?, ?, 'Appt Fail', ?, ?, 'scheduled', ?, ?)",
        (appt_fail_id, prof_id, now.isoformat(), now.isoformat(), now.isoformat(), now.isoformat()),
    )

    cur.execute(
        "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
        "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
        (event_pass_id, prof_id, f"appointment:{appt_pass_id}", ts_exact_7d.isoformat()),
    )
    cur.execute(
        "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
        "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
        (event_fail_id, prof_id, f"appointment:{appt_fail_id}", ts_expired_1us.isoformat()),
    )
    sync_sqlite_db.commit()

    # 1. Exactly 7 days old must SUCCEED
    res_pass = execute_single_click_undo(sync_sqlite_db, event_pass_id, prof_id, current_time=now)
    assert res_pass["status"] == "undone"

    # 2. 7 days + 1 microsecond must FAIL with UndoWindowExpiredError
    with pytest.raises((UndoWindowExpiredError, _resolve_undo_window_expired_error())) as exc_info:
        execute_single_click_undo(sync_sqlite_db, event_fail_id, prof_id, current_time=now)
    assert "7-day undo window" in str(exc_info.value)


@pytest.mark.asyncio
async def test_adv_undo_exact_microsecond_boundary_precision_async(async_db_session: AsyncSession):
    """Adversarial Test 16: Verifies strict microsecond boundary on 7-day undo window in asynchronous SQLAlchemy engine."""
    prof = Profile(id=str(uuid.uuid4()), name="Async Boundary Patient")
    async_db_session.add(prof)

    now = datetime(2026, 10, 13, 12, 0, 0, 0, tzinfo=timezone.utc)
    ts_exact_7d = now - timedelta(days=7)
    ts_expired_1us = now - timedelta(days=7, microseconds=1)

    appt_pass = Appointment(
        id=str(uuid.uuid4()), profile_id=prof.id, title="Pass", start_time=now, end_time=now, created_at=now, updated_at=now
    )
    appt_fail = Appointment(
        id=str(uuid.uuid4()), profile_id=prof.id, title="Fail", start_time=now, end_time=now, created_at=now, updated_at=now
    )
    async_db_session.add_all([appt_pass, appt_fail])

    event_pass = AuditEventRecord(
        id=str(uuid.uuid4()),
        profile_id=prof.id,
        event="create_appointment",
        tool="create_appointment",
        risk="write_local",
        decision="allow",
        external_ref=f"appointment:{appt_pass.id}",
        ts=ts_exact_7d,
    )
    event_fail = AuditEventRecord(
        id=str(uuid.uuid4()),
        profile_id=prof.id,
        event="create_appointment",
        tool="create_appointment",
        risk="write_local",
        decision="allow",
        external_ref=f"appointment:{appt_fail.id}",
        ts=ts_expired_1us,
    )
    async_db_session.add_all([event_pass, event_fail])
    await async_db_session.commit()

    # 1. Exactly 7 days: SUCCEEDS
    res_pass = await execute_single_click_undo_async(
        async_db_session, event_pass.id, prof.id, current_time=now
    )
    assert res_pass["status"] == "undone"

    # 2. 7 days + 1 us: EXPIRED
    with pytest.raises((UndoWindowExpiredError, _resolve_undo_window_expired_error())):
        await execute_single_click_undo_async(
            async_db_session, event_fail.id, prof.id, current_time=now
        )


def test_adv_undo_risk_tier_invariants_strictly_fail_closed_sync(sync_sqlite_db: sqlite3.Connection):
    """Adversarial Test 17: Verifies synchronous undo rejects all non-write_local risk tiers (read, write_network, admin)."""
    cur = sync_sqlite_db.cursor()
    prof_id = "prof-risk"
    cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Risk Patient')", (prof_id,))
    now = datetime.now(timezone.utc)

    non_eligible_risks = ["read", "write_network", "admin", "write_cloud", "unknown"]
    for risk_tier in non_eligible_risks:
        e_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'test_action', 'test_tool', ?, 'appointment:none', ?)",
            (e_id, prof_id, risk_tier, now.isoformat()),
        )
        sync_sqlite_db.commit()

        with pytest.raises((ActionNotUndoableError, _resolve_action_not_undoable_error())) as exc_info:
            execute_single_click_undo(sync_sqlite_db, e_id, prof_id, current_time=now)
        assert "cannot be undone" in str(exc_info.value) or "write_local" in str(exc_info.value)


@pytest.mark.asyncio
async def test_adv_undo_risk_tier_invariants_strictly_fail_closed_async(async_db_session: AsyncSession):
    """Adversarial Test 18: Verifies asynchronous undo rejects all non-write_local risk tiers."""
    prof = Profile(id=str(uuid.uuid4()), name="Risk Patient Async")
    async_db_session.add(prof)
    now = datetime.now(timezone.utc)

    for risk_tier in ["read", "write_network", "admin"]:
        e_id = str(uuid.uuid4())
        rec = AuditEventRecord(
            id=e_id,
            profile_id=prof.id,
            event="test_action",
            tool="test_tool",
            risk=risk_tier,
            decision="allow",
            external_ref="appointment:none",
            ts=now,
        )
        async_db_session.add(rec)
    await async_db_session.commit()

    for risk_tier in ["read", "write_network", "admin"]:
        # Find record
        stmt = select(AuditEventRecord).where(AuditEventRecord.profile_id == prof.id, AuditEventRecord.risk == risk_tier)
        rec = (await async_db_session.execute(stmt)).scalar_one()
        with pytest.raises((ActionNotUndoableError, _resolve_action_not_undoable_error())):
            await execute_single_click_undo_async(async_db_session, rec.id, prof.id, current_time=now)


def test_adv_undo_anti_recursion_cannot_undo_an_undo(sync_sqlite_db: sqlite3.Connection):
    """Adversarial Test 19: Verifies anti-recursion invariant: attempting to undo an undo event raises ActionNotUndoableError."""
    cur = sync_sqlite_db.cursor()
    prof_id = "prof-anti-rec"
    cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Anti-Rec Patient')", (prof_id,))
    now = datetime.now(timezone.utc)
    undo_e_id = str(uuid.uuid4())

    cur.execute(
        "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
        "VALUES (?, ?, 'user', 'undo', 'undo', 'write_local', 'appointment:none', ?)",
        (undo_e_id, prof_id, now.isoformat()),
    )
    sync_sqlite_db.commit()

    with pytest.raises((ActionNotUndoableError, _resolve_action_not_undoable_error())) as exc_info:
        execute_single_click_undo(sync_sqlite_db, undo_e_id, prof_id, current_time=now)
    assert "Cannot undo a previous undo reversal" in str(exc_info.value)


@pytest.mark.asyncio
async def test_adv_undo_idempotency_behavior(async_db_session: AsyncSession):
    """Adversarial Test 20: Verifies idempotent=True returns metadata and idempotent=False raises AlreadyUndoneError."""
    prof = Profile(id=str(uuid.uuid4()), name="Idempotency Patient")
    now = datetime.now(timezone.utc)
    appt = Appointment(id=str(uuid.uuid4()), profile_id=prof.id, title="Appt", start_time=now, end_time=now, created_at=now, updated_at=now)
    rec = AuditEventRecord(
        id=str(uuid.uuid4()),
        profile_id=prof.id,
        event="create_appointment",
        tool="create_appointment",
        risk="write_local",
        decision="allow",
        external_ref=f"appointment:{appt.id}",
        ts=now,
    )
    async_db_session.add_all([prof, appt, rec])
    await async_db_session.commit()

    # First undo: SUCCEEDS
    res1 = await execute_single_click_undo_async(async_db_session, rec.id, prof.id, current_time=now)
    assert res1["status"] == "undone"

    # Second undo with idempotent=True: SUCCEEDS without error
    res2 = await execute_single_click_undo_async(async_db_session, rec.id, prof.id, current_time=now, idempotent=True)
    assert res2["status"] == "undone"
    assert res2.get("idempotent") is True

    # Third undo with idempotent=False: RAISES AlreadyUndoneError
    with pytest.raises(AlreadyUndoneError) as exc_info:
        await execute_single_click_undo_async(async_db_session, rec.id, prof.id, current_time=now, idempotent=False)
    assert "already been undone" in str(exc_info.value)


def test_adv_undo_malformed_external_ref_raises_invalid_ref(sync_sqlite_db: sqlite3.Connection):
    """Adversarial Test 21: Verifies malformed external_ref formats fail closed with InvalidExternalRefError."""
    cur = sync_sqlite_db.cursor()
    prof_id = "prof-malformed"
    cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Malformed Patient')", (prof_id,))
    now = datetime.now(timezone.utc)

    bad_refs = ["", "   ", "missingcolon", ":only_id", "only_type:", None]
    for bad in bad_refs:
        e_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
            (e_id, prof_id, bad, now.isoformat()),
        )
        sync_sqlite_db.commit()

        with pytest.raises(InvalidExternalRefError):
            execute_single_click_undo(sync_sqlite_db, e_id, prof_id, current_time=now)


# ============================================================================
# Section 4: Rollback Resolution Across All 4 Entity Types (AU-40)
# ============================================================================

@pytest.mark.asyncio
async def test_adv_undo_rollback_all_four_entity_types(async_db_session: AsyncSession):
    """Adversarial Test 22: Verifies state rollback fidelity across health_resource, appointment, reminder, and note."""
    prof = Profile(id=str(uuid.uuid4()), name="Multi-Entity Patient")
    now = datetime.now(timezone.utc)

    # 1. HealthResource
    hr = HealthResource(
        id=str(uuid.uuid4()),
        profile_id=prof.id,
        resource_type="observation",
        source_type="manual",
        status="active",
        data={"systolic": 130, "diastolic": 85},
        effective_at=now,
        recorded_at=now,
        created_at=now,
        updated_at=now,
    )
    hr_event = AuditEventRecord(
        id=str(uuid.uuid4()), profile_id=prof.id, event="record_vitals", tool="record_vitals", risk="write_local",
        decision="allow", external_ref=f"health_resource:{hr.id}", ts=now
    )

    # 2. Appointment
    appt = Appointment(
        id=str(uuid.uuid4()), profile_id=prof.id, title="Routine Visit", start_time=now, end_time=now,
        status="scheduled", created_at=now, updated_at=now
    )
    appt_event = AuditEventRecord(
        id=str(uuid.uuid4()), profile_id=prof.id, event="create_appointment", tool="create_appointment", risk="write_local",
        decision="allow", external_ref=f"appointment:{appt.id}", ts=now
    )

    # 3. Reminder
    rem = Reminder(
        id=str(uuid.uuid4()), profile_id=prof.id, title="Take Meds", next_due_at=now, status="pending",
        created_at=now, updated_at=now
    )
    rem_event = AuditEventRecord(
        id=str(uuid.uuid4()), profile_id=prof.id, event="create_reminder", tool="create_reminder", risk="write_local",
        decision="allow", external_ref=f"reminder:{rem.id}", ts=now
    )

    # 4. Note
    note = Note(
        id=str(uuid.uuid4()), profile_id=prof.id, slug=f"note-{uuid.uuid4().hex[:6]}", title="Encounter Note",
        content="Patient discussed asthma.", type="visit", created_at=now, updated_at=now
    )
    note_event = AuditEventRecord(
        id=str(uuid.uuid4()), profile_id=prof.id, event="create_typed_note", tool="create_typed_note", risk="write_local",
        decision="allow", external_ref=f"note:{note.id}", ts=now
    )

    async_db_session.add_all([prof, hr, hr_event, appt, appt_event, rem, rem_event, note, note_event])
    await async_db_session.commit()

    # Revert 1: HealthResource -> tombstone
    await execute_single_click_undo_async(async_db_session, hr_event.id, prof.id, current_time=now)
    hr_check = (await async_db_session.execute(select(HealthResource).where(HealthResource.id == hr.id))).scalar_one()
    assert hr_check.status == "tombstone"

    # Revert 2: Appointment -> cancelled
    await execute_single_click_undo_async(async_db_session, appt_event.id, prof.id, current_time=now)
    appt_check = (await async_db_session.execute(select(Appointment).where(Appointment.id == appt.id))).scalar_one()
    assert appt_check.status == "cancelled"

    # Revert 3: Reminder -> cancelled
    await execute_single_click_undo_async(async_db_session, rem_event.id, prof.id, current_time=now)
    rem_check = (await async_db_session.execute(select(Reminder).where(Reminder.id == rem.id))).scalar_one()
    assert rem_check.status == "cancelled"

    # Revert 4: Note -> deleted & delete_doc job enqueued
    await execute_single_click_undo_async(async_db_session, note_event.id, prof.id, current_time=now)
    note_check = (await async_db_session.execute(select(Note).where(Note.id == note.id))).scalar_one_or_none()
    assert note_check is None

    del_job_stmt = select(Job).where(Job.profile_id == prof.id, Job.kind == "delete_doc")
    del_job = (await async_db_session.execute(del_job_stmt)).scalar_one_or_none()
    assert del_job is not None
    job_payload = json.loads(del_job.payload)
    assert job_payload["document_id"] == note.id


@pytest.mark.asyncio
async def test_adv_undo_cross_profile_isolation_fail_closed(async_db_session: AsyncSession):
    """Adversarial Test 23: Verifies Profile B cannot undo Profile A's event, and Profile A's state remains intact."""
    prof_a = Profile(id=str(uuid.uuid4()), name="Profile A")
    prof_b = Profile(id=str(uuid.uuid4()), name="Profile B")
    now = datetime.now(timezone.utc)

    appt_a = Appointment(
        id=str(uuid.uuid4()), profile_id=prof_a.id, title="Appt A", start_time=now, end_time=now,
        status="scheduled", created_at=now, updated_at=now
    )
    event_a = AuditEventRecord(
        id=str(uuid.uuid4()), profile_id=prof_a.id, event="create_appointment", tool="create_appointment",
        risk="write_local", decision="allow", external_ref=f"appointment:{appt_a.id}", ts=now
    )
    async_db_session.add_all([prof_a, prof_b, appt_a, event_a])
    await async_db_session.commit()

    # Profile B attempts to undo Profile A's audit event
    with pytest.raises(EntityNotFoundError) as exc_info:
        await execute_single_click_undo_async(async_db_session, event_a.id, prof_b.id, current_time=now)
    assert "not found for profile" in str(exc_info.value)

    # Verify Profile A's appointment remains scheduled
    appt_check = (await async_db_session.execute(select(Appointment).where(Appointment.id == appt_a.id))).scalar_one()
    assert appt_check.status == "scheduled"


# ============================================================================
# Section 5: Synthesizer Defensiveness & REST API RBAC Isolation
# ============================================================================

def test_adv_activity_synthesizer_defensive_garbage_payloads():
    """Adversarial Test 24: Verifies synthesize_activity_summary does not crash on malformed/garbage vitals and tool inputs."""
    # Garbage non-numeric vitals
    summary, desc = synthesize_activity_summary(
        action="tool",
        tool="record_vitals",
        details={"vitals": {"systolic": "invalid_str", "diastolic": None, "heart_rate": []}},
        external_ref="health_resource:hr-bad",
    )
    assert "Logged vital signs observation" in summary
    assert "Recorded clinical observation" in desc

    # All tool categories synthesize without throwing
    tools = [
        ("undo", {"reverted_summary": "Logged vitals"}, "health_resource:1"),
        ("create_appointment", {"title": "Cardio Consult", "provider_name": "Dr. Smith", "specialty": "Cardiology"}, "appointment:1"),
        ("cancel_appointment", {"title": "Cardio Consult"}, "appointment:1"),
        ("update_appointment_status", {"new_status": "completed"}, "appointment:1"),
        ("create_reminder", {"title": "Lisinopril", "category": "medication"}, "reminder:1"),
        ("generate_prep_pack", {"specialty": "Cardiology"}, "note:1"),
        ("create_typed_note", {"title": "Discharge Summary", "type": "after_visit"}, "note:1"),
        ("refuse", {"reason": "BP Crisis detected"}, None),
        ("run", {"agent_id": "cardiology-guide"}, None),
    ]

    for tool_name, det, ext_ref in tools:
        s, d = synthesize_activity_summary(
            action=tool_name,
            tool=tool_name,
            details=det,
            external_ref=ext_ref,
        )
        assert len(s) > 0
        assert len(d) > 0


def test_adv_api_rbac_manage_vs_view_clinical_vs_view_paperwork(rbac_api_env):
    """Adversarial Test 25: Verifies complete REST API RBAC enforcement matrix across manage, view_clinical, view_paperwork, and unauthenticated."""
    client = TestClient(app)
    env = rbac_api_env
    prof_id = env["profile_alice_id"]

    # 1. Alice (manage): Full access to timeline
    res_alice = client.get(
        f"/api/profiles/{prof_id}/activity",
        headers={"Authorization": f"Bearer {env['alice_token']}"},
    )
    assert res_alice.status_code == status.HTTP_200_OK

    # 2. Charlie (view_clinical): Can read timeline, but forbidden from mutating undo
    res_charlie_get = client.get(
        f"/api/profiles/{prof_id}/activity",
        headers={"Authorization": f"Bearer {env['charlie_token']}"},
    )
    assert res_charlie_get.status_code == status.HTTP_200_OK

    res_charlie_undo = client.post(
        f"/api/profiles/{prof_id}/activity/any-event-id/undo",
        headers={"Authorization": f"Bearer {env['charlie_token']}"},
    )
    assert res_charlie_undo.status_code == status.HTTP_403_FORBIDDEN
    assert "management permissions required" in res_charlie_undo.json()["detail"]

    # Charlie forbidden from POST /prep-pack (requires manage)
    res_charlie_prep = client.post(
        f"/api/profiles/{prof_id}/prep-pack",
        json={"visit_reason": "General Checkup"},
        headers={"Authorization": f"Bearer {env['charlie_token']}"},
    )
    assert res_charlie_prep.status_code == status.HTTP_403_FORBIDDEN

    # 3. Dan (view_paperwork): Forbidden from inspecting clinical activity timeline
    res_dan = client.get(
        f"/api/profiles/{prof_id}/activity",
        headers={"Authorization": f"Bearer {env['dan_token']}"},
    )
    assert res_dan.status_code == status.HTTP_403_FORBIDDEN
    assert "clinical view permissions required" in res_dan.json()["detail"]

    # 4. Eve (unauthorized external user): 403 Forbidden
    res_eve = client.get(
        f"/api/profiles/{prof_id}/activity",
        headers={"Authorization": f"Bearer {env['eve_token']}"},
    )
    assert res_eve.status_code == status.HTTP_403_FORBIDDEN

    # 5. Unauthenticated: 401 Unauthorized
    res_unauth = client.get(f"/api/profiles/{prof_id}/activity")
    assert res_unauth.status_code == status.HTTP_401_UNAUTHORIZED


def test_adv_api_cross_profile_appointment_linkage_forbidden(rbac_api_env):
    """Adversarial Test 26: Verifies linking an appointment belonging to another profile in POST /profiles/{id}/notes fails with HTTP 400."""
    client = TestClient(app)
    env = rbac_api_env
    prof_alice = env["profile_alice_id"]
    prof_eve = env["profile_eve_id"]

    # Create an appointment in Eve's profile
    now = datetime.now(timezone.utc)
    appt_eve_id = str(uuid.uuid4())

    async def _insert_foreign_appt():
        async with env["session_factory"]() as s:
            appt = Appointment(
                id=appt_eve_id,
                profile_id=prof_eve,
                title="Eve Private Appointment",
                start_time=now,
                end_time=now + timedelta(hours=1),
                status="scheduled",
                created_at=now,
                updated_at=now,
            )
            s.add(appt)
            await s.commit()

    run_async(_insert_foreign_appt())

    # Alice attempts to create a note in Alice's profile linking Eve's appointment
    res = client.post(
        f"/api/profiles/{prof_alice}/notes",
        json={
            "title": "Cross-Profile Link Attack",
            "content": "Trying to link foreign appointment.",
            "type": "visit",
            "linked_appointment_id": appt_eve_id,
        },
        headers={"Authorization": f"Bearer {env['alice_token']}"},
    )

    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Security violation" in res.json()["detail"]
    assert "does not belong to profile" in res.json()["detail"]


@pytest.mark.asyncio
async def test_adv_activity_timeline_pagination_and_undoable_filter(async_db_session: AsyncSession):
    """Adversarial Test 27: Verifies get_profile_activity_timeline pagination offsets, limits, and undoable_only filtering."""
    prof = Profile(id=str(uuid.uuid4()), name="Pagination Patient")
    now = datetime.now(timezone.utc)

    # Insert 10 events: 5 within 7 days write_local, 5 older than 7 days
    for i in range(10):
        is_fresh = (i % 2 == 0)
        ts = now - timedelta(days=2) if is_fresh else now - timedelta(days=10)
        risk = "write_local" if is_fresh else "read"
        ext_ref = f"appointment:appt-{i}" if is_fresh else None

        rec = AuditEventRecord(
            id=str(uuid.uuid4()),
            profile_id=prof.id,
            event=f"event_{i}",
            tool="tool_test",
            risk=risk,
            decision="allow",
            external_ref=ext_ref,
            ts=ts,
        )
        async_db_session.add(rec)
    async_db_session.add(prof)
    await async_db_session.commit()

    # 1. Total query limit 5
    res_page1 = await get_profile_activity_timeline(
        db=async_db_session,
        profile_id=prof.id,
        limit=5,
        offset=0,
        now=now,
    )
    assert len(res_page1.items) == 5
    assert res_page1.total == 10
    assert res_page1.has_more is True

    # 2. Undoable only filter
    res_undoable = await get_profile_activity_timeline(
        db=async_db_session,
        profile_id=prof.id,
        limit=20,
        offset=0,
        undoable_only=True,
        now=now,
    )
    # Exactly the 5 fresh write_local items with external_ref are returned
    assert len(res_undoable.items) == 5
    for item in res_undoable.items:
        assert item.undoable is True
