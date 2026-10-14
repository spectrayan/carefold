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

"""Unit and integration test suite for Activity Timeline Engine and Description Synthesizer (AU-40)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.clinical.activity import (
    compute_is_undoable,
    format_audit_event_as_activity_item,
    get_profile_activity_timeline,
    synthesize_activity_summary,
)
from carefold.db.models import AuditEventRecord, Profile
from carefold.db.session import create_db_engine, get_session_factory, init_db


def run_async(coro):
    """Executes asynchronous coroutine synchronously."""
    return asyncio.run(coro)


# ============================================================================
# Section 1: Domain Synthesis Unit Tests (Pure Functions)
# ============================================================================

class TestActivitySummarySynthesizer:
    """Verifies deterministic synthesis of patient-friendly summaries and descriptions."""

    def test_synthesize_vitals_blood_pressure(self):
        summary, desc = synthesize_activity_summary(
            action="tool",
            tool="record_vitals",
            details={"vitals": {"systolic": 120, "diastolic": 80}},
            external_ref="health_resource:hr-1",
        )
        assert summary == "Logged blood pressure 120/80 mmHg"
        assert desc == "Recorded blood pressure reading of 120/80 mmHg."

    def test_synthesize_vitals_weight_kg_and_lbs(self):
        summary_kg, desc_kg = synthesize_activity_summary(
            action="tool",
            tool="record_vitals",
            details={"vitals": {"weight": 70, "unit": "kg"}},
            external_ref="health_resource:hr-2",
        )
        assert summary_kg == "Recorded weight 70 kg"
        assert desc_kg == "Recorded body weight measurement of 70 kg."

        summary_lbs, desc_lbs = synthesize_activity_summary(
            action="tool",
            tool="record_vitals",
            details={"vitals": {"weight": 154, "unit": "lbs"}},
            external_ref="health_resource:hr-3",
        )
        assert summary_lbs == "Recorded weight 154 lbs"
        assert desc_lbs == "Recorded body weight measurement of 154 lbs."

    def test_synthesize_vitals_heart_rate_glucose_spo2_height(self):
        # Heart rate
        s_hr, d_hr = synthesize_activity_summary(
            action="tool",
            tool="record_vitals",
            details={"vitals": {"heart_rate": 72}},
            external_ref="health_resource:hr-4",
        )
        assert s_hr == "Logged heart rate 72 bpm"
        assert d_hr == "Recorded pulse rate of 72 bpm."

        # Blood Glucose
        s_glu, d_glu = synthesize_activity_summary(
            action="tool",
            tool="record_vitals",
            details={"vitals": {"blood_glucose": 110, "unit": "mg/dL"}},
            external_ref="health_resource:hr-5",
        )
        assert s_glu == "Logged blood glucose 110 mg/dL"
        assert d_glu == "Recorded blood glucose reading of 110 mg/dL."

        # SpO2
        s_spo2, d_spo2 = synthesize_activity_summary(
            action="tool",
            tool="record_vitals",
            details={"vitals": {"spo2": 98}},
            external_ref="health_resource:hr-6",
        )
        assert s_spo2 == "Logged oxygen saturation 98%"
        assert d_spo2 == "Recorded pulse oximetry reading of 98% SpO2."

        # Height
        s_ht, d_ht = synthesize_activity_summary(
            action="tool",
            tool="record_vitals",
            details={"vitals": {"height": 175, "unit": "cm"}},
            external_ref="health_resource:hr-7",
        )
        assert s_ht == "Recorded height 175 cm"
        assert d_ht == "Recorded body height measurement of 175 cm."

    def test_synthesize_vitals_multiple_and_fallback(self):
        # Multiple vitals
        s_multi, d_multi = synthesize_activity_summary(
            action="tool",
            tool="record_vitals",
            details={"vitals": {"systolic": 120, "diastolic": 80, "heart_rate": 72}},
            external_ref="health_resource:hr-8",
        )
        assert "blood pressure 120/80 mmHg" in s_multi
        assert "heart rate 72 bpm" in s_multi
        assert d_multi == "Recorded vital signs observation panel."

        # Fallback when empty
        s_empty, d_empty = synthesize_activity_summary(
            action="tool",
            tool="record_vitals",
            details={},
            external_ref="health_resource:hr-9",
        )
        assert s_empty == "Logged vital signs observation"
        assert d_empty == "Recorded clinical observation in health resources."

    def test_synthesize_vitals_defensive_non_numeric_fallback(self):
        """Advisory 1: Non-numeric vitals strings must not raise ValueError and should fall back gracefully."""
        # Non-numeric string data
        s_bad, d_bad = synthesize_activity_summary(
            action="tool",
            tool="record_vitals",
            details={"vitals": {"systolic": "pending", "diastolic": "high", "heart_rate": "unreadable", "spo2": "err", "weight": "heavy", "height": "tall"}},
            external_ref="health_resource:hr-bad",
        )
        assert s_bad == "Logged vital signs observation"
        assert d_bad == "Recorded clinical observation in health resources."

        # Mixed valid and invalid: valid should still be captured
        s_mixed, d_mixed = synthesize_activity_summary(
            action="tool",
            tool="record_vitals",
            details={"vitals": {"systolic": 125, "diastolic": "pending", "heart_rate": 70}},
            external_ref="health_resource:hr-mixed",
        )
        assert "heart rate 70 bpm" in s_mixed

    def test_synthesize_tool_name_aliases(self):
        """Advisory 2: Tool name aliases (book_appointment, cancel_appointment, complete_reminder, create_clinical_note)."""
        # book_appointment
        s_book, d_book = synthesize_activity_summary(
            action="tool",
            tool="book_appointment",
            details={"provider_name": "Dr. Miller", "specialty": "Dermatology"},
            external_ref="appointment:apt-book",
        )
        assert s_book == "Scheduled appointment with Dr. Miller (Dermatology)"
        assert "booked with Dr. Miller" in d_book

        # cancel_appointment
        s_canc, d_canc = synthesize_activity_summary(
            action="tool",
            tool="cancel_appointment",
            details={"provider_name": "Dr. Miller"},
            external_ref="appointment:apt-canc",
        )
        assert s_canc == "Cancelled appointment with Dr. Miller"
        assert d_canc == "Appointment cancelled."

        # complete_reminder
        s_comp_rem, d_comp_rem = synthesize_activity_summary(
            action="tool",
            tool="complete_reminder",
            details={"title": "Blood Pressure Log"},
            external_ref="reminder:rem-comp",
        )
        assert s_comp_rem == "Completed reminder: Blood Pressure Log"
        assert d_comp_rem == "Reminder marked complete."

        # create_clinical_note
        s_note, d_note = synthesize_activity_summary(
            action="tool",
            tool="create_clinical_note",
            details={"type": "visit", "title": "Checkup Notes"},
            external_ref="note:note-clin",
        )
        assert s_note == "Created visit note: Checkup Notes"
        assert d_note == "Clinical visit note saved."

    def test_synthesize_create_appointment_provider_specialty(self):
        summary, desc = synthesize_activity_summary(
            action="tool",
            tool="create_appointment",
            details={
                "provider_name": "Dr. Sarah Jenkins",
                "specialty": "Cardiology",
                "start_time": "2026-10-20T10:00:00Z",
            },
            external_ref="appointment:apt-1",
        )
        assert summary == "Scheduled appointment with Dr. Sarah Jenkins (Cardiology)"
        assert desc == "Consultation scheduled for 2026-10-20T10:00:00Z."

    def test_synthesize_create_appointment_requested_draft(self):
        summary, desc = synthesize_activity_summary(
            action="tool",
            tool="create_appointment",
            details={
                "provider_name": "Dr. Smith",
                "specialty": "Neurology",
                "status": "requested",
            },
            external_ref="appointment:apt-2",
        )
        assert summary == "Requested appointment with Dr. Smith (Neurology)"
        assert desc == "Draft booking request prepared for scheduling."

    def test_synthesize_update_appointment_status(self):
        s_conf, d_conf = synthesize_activity_summary(
            action="tool",
            tool="update_appointment_status",
            details={"new_status": "confirmed", "previous_status": "requested"},
            external_ref="appointment:apt-3",
        )
        assert s_conf == "Updated appointment status to confirmed"
        assert d_conf == "Appointment status updated from requested to confirmed."

        s_comp, d_comp = synthesize_activity_summary(
            action="tool",
            tool="update_appointment_status",
            details={"new_status": "completed"},
            external_ref="appointment:apt-3",
        )
        assert s_comp == "Updated appointment status to completed"
        assert d_comp == "Encounter marked completed."

        s_canc, d_canc = synthesize_activity_summary(
            action="tool",
            tool="update_appointment_status",
            details={"new_status": "cancelled"},
            external_ref="appointment:apt-3",
        )
        assert s_canc == "Updated appointment status to cancelled"
        assert d_canc == "Appointment cancelled."

    def test_synthesize_create_reminder_medication_and_vitals(self):
        s_med, d_med = synthesize_activity_summary(
            action="tool",
            tool="create_reminder",
            details={"category": "medication", "title": "Lisinopril 10mg"},
            external_ref="reminder:rem-1",
        )
        assert s_med == "Created medication reminder: Lisinopril 10mg"
        assert d_med == "Recurring reminder scheduled for Lisinopril 10mg."

        s_vit, d_vit = synthesize_activity_summary(
            action="tool",
            tool="create_reminder",
            details={"category": "vitals", "title": "Morning BP Check"},
            external_ref="reminder:rem-2",
        )
        assert s_vit == "Created vitals reminder: Morning BP Check"
        assert d_vit == "Reminder scheduled for Morning BP Check."

    def test_synthesize_generate_prep_pack(self):
        summary, desc = synthesize_activity_summary(
            action="tool",
            tool="generate_prep_pack",
            details={"specialty": "Cardiology"},
            external_ref="note:note-1",
        )
        assert summary == "Generated consultation prep pack for Cardiology visit"
        assert desc == "Synthesized clinical questions, vitals trends, and medication history."

    def test_synthesize_create_typed_note(self):
        s_vis, d_vis = synthesize_activity_summary(
            action="tool",
            tool="create_typed_note",
            details={"type": "visit", "title": "Annual Wellness Visit"},
            external_ref="note:note-2",
        )
        assert s_vis == "Created visit note: Annual Wellness Visit"
        assert d_vis == "Clinical visit note saved."

        s_aft, d_aft = synthesize_activity_summary(
            action="tool",
            tool="create_typed_note",
            details={"type": "after_visit", "title": "Post-Encounter Plan"},
            external_ref="note:note-3",
        )
        assert s_aft == "Created after_visit note: Post-Encounter Plan"
        assert d_aft == "Extracted post-encounter summary and next steps."

    def test_synthesize_undo_reversal_descriptions(self):
        s_hr, d_hr = synthesize_activity_summary(
            action="undo",
            tool="undo",
            details={},
            external_ref="health_resource:hr-1",
        )
        assert s_hr == "Reverted action: Logged vitals"
        assert d_hr == "Tombstoned vital signs observation."

        s_apt, d_apt = synthesize_activity_summary(
            action="undo",
            tool="undo",
            details={},
            external_ref="appointment:apt-1",
        )
        assert s_apt == "Reverted action: Scheduled appointment"
        assert d_apt == "Cancelled scheduled appointment."

        s_rem, d_rem = synthesize_activity_summary(
            action="undo",
            tool="undo",
            details={},
            external_ref="reminder:rem-1",
        )
        assert s_rem == "Reverted action: Created reminder"
        assert d_rem == "Cancelled reminder and removed active alerts."

        s_not, d_not = synthesize_activity_summary(
            action="undo",
            tool="undo",
            details={},
            external_ref="note:not-1",
        )
        assert s_not == "Reverted action: Created note"
        assert d_not == "Removed clinical note and purged search index."

        s_rev, d_rev = synthesize_activity_summary(
            action="undo",
            tool="undo",
            details={"reverted_summary": "Scheduled appointment with Dr. Jenkins"},
            external_ref="appointment:apt-1",
        )
        assert s_rev == "Reverted action: Scheduled appointment with Dr. Jenkins"
        assert d_rev == "Rolled back changes and restored previous state."

    def test_synthesize_fallback_graceful_degradation(self):
        s_ref, d_ref = synthesize_activity_summary(
            action="refuse",
            tool=None,
            details={"reason": "Acute stroke symptoms detected"},
            external_ref=None,
        )
        assert s_ref == "Safety boundary refusal: Acute stroke symptoms detected"
        assert d_ref == "Non-clinical boundary triggered emergency escalation."

        s_gen, d_gen = synthesize_activity_summary(
            action="tool",
            tool="custom_tool",
            details={},
            external_ref=None,
        )
        assert s_gen == "Executed custom_tool"
        assert d_gen == "Action executed via custom_tool."


# ============================================================================
# Section 2: Undoability Calculation Logic Tests
# ============================================================================

class TestUndoabilityCalculation:
    """Verifies pure boolean evaluation for compute_is_undoable."""

    def test_undoable_true_for_recent_write_local(self):
        now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
        ts = now - timedelta(days=2)
        is_undoable = compute_is_undoable(
            risk="write_local",
            ts=ts,
            event_id="e-1",
            undone_event_ids=set(),
            tool="record_vitals",
            event="tool",
            external_ref="health_resource:hr-1",
            now=now,
        )
        assert is_undoable is True

    def test_undoable_false_when_older_than_7_days(self):
        now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
        ts = now - timedelta(days=7, seconds=1)
        is_undoable = compute_is_undoable(
            risk="write_local",
            ts=ts,
            event_id="e-2",
            undone_event_ids=set(),
            tool="create_appointment",
            event="tool",
            external_ref="appointment:apt-1",
            now=now,
        )
        assert is_undoable is False

    def test_undoable_false_for_read_or_none_risk(self):
        now = datetime.now(timezone.utc)
        for non_write in ("read", "write_network", "admin", None):
            res = compute_is_undoable(
                risk=non_write,
                ts=now - timedelta(hours=1),
                event_id="e-3",
                undone_event_ids=set(),
                tool="list_appointments",
                event="tool",
                external_ref="appointment:apt-1",
                now=now,
            )
            assert res is False

    def test_undoable_false_for_already_undone_event(self):
        now = datetime.now(timezone.utc)
        res = compute_is_undoable(
            risk="write_local",
            ts=now - timedelta(hours=1),
            event_id="e-4",
            undone_event_ids={"e-4"},
            tool="create_reminder",
            event="tool",
            external_ref="reminder:rem-1",
            now=now,
        )
        assert res is False

    def test_undoable_false_for_undo_event_itself(self):
        now = datetime.now(timezone.utc)
        res = compute_is_undoable(
            risk="write_local",
            ts=now - timedelta(hours=1),
            event_id="e-5",
            undone_event_ids=set(),
            tool="undo",
            event="undo",
            external_ref="appointment:apt-1",
            now=now,
        )
        assert res is False

    def test_undoable_false_for_missing_external_ref(self):
        now = datetime.now(timezone.utc)
        res = compute_is_undoable(
            risk="write_local",
            ts=now - timedelta(hours=1),
            event_id="e-6",
            undone_event_ids=set(),
            tool="record_vitals",
            event="tool",
            external_ref=None,
            now=now,
        )
        assert res is False


# ============================================================================
# Section 3: Database Query & Scoping Integration Tests
# ============================================================================

@pytest.fixture
async def timeline_db_session():
    """Provides an isolated AsyncSession with schema initialized."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    async with session_factory() as session:
        yield session
    await engine.dispose()



@pytest.mark.asyncio
class TestTimelineQueryIntegration:
    """Verifies database timeline querying, profile scoping, ordering, and pagination."""

    async def test_timeline_query_strictly_scoped_by_profile_id(self, timeline_db_session: AsyncSession):
        now = datetime.now(timezone.utc)
        p1_id = f"prof-{uuid.uuid4().hex[:8]}"
        p2_id = f"prof-{uuid.uuid4().hex[:8]}"

        # Seed profile 1 and 2 records
        timeline_db_session.add(Profile(id=p1_id, name="Patient One"))
        timeline_db_session.add(Profile(id=p2_id, name="Patient Two"))

        rec1 = AuditEventRecord(
            id=str(uuid.uuid4()),
            profile_id=p1_id,
            principal="user",
            event="tool",
            tool="record_vitals",
            risk="write_local",
            external_ref="health_resource:hr-1",
            ts=now,
            detail_redacted=json.dumps({"vitals": {"systolic": 120, "diastolic": 80}}),
        )
        rec2 = AuditEventRecord(
            id=str(uuid.uuid4()),
            profile_id=p2_id,
            principal="user",
            event="tool",
            tool="create_appointment",
            risk="write_local",
            external_ref="appointment:apt-1",
            ts=now,
            detail_redacted=json.dumps({"title": "Checkup"}),
        )
        timeline_db_session.add_all([rec1, rec2])
        await timeline_db_session.commit()

        # Query profile 1
        resp1 = await get_profile_activity_timeline(timeline_db_session, profile_id=p1_id)
        assert resp1.total == 1
        assert len(resp1.items) == 1
        assert resp1.items[0].id == rec1.id
        assert resp1.items[0].profile_id == p1_id
        assert resp1.items[0].summary == "Logged blood pressure 120/80 mmHg"

        # Query profile 2
        resp2 = await get_profile_activity_timeline(timeline_db_session, profile_id=p2_id)
        assert resp2.total == 1
        assert len(resp2.items) == 1
        assert resp2.items[0].id == rec2.id
        assert resp2.items[0].profile_id == p2_id

    async def test_timeline_chronological_descending_order(self, timeline_db_session: AsyncSession):
        p_id = f"prof-{uuid.uuid4().hex[:8]}"
        timeline_db_session.add(Profile(id=p_id, name="Test Patient"))

        base_time = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        recs = [
            AuditEventRecord(
                id=f"e-{i}",
                profile_id=p_id,
                principal="user",
                event="tool",
                tool="record_vitals",
                risk="write_local",
                external_ref=f"health_resource:hr-{i}",
                ts=base_time + timedelta(hours=i),
                detail_redacted=json.dumps({"vitals": {"heart_rate": 60 + i}}),
            )
            for i in range(5)
        ]
        timeline_db_session.add_all(recs)
        await timeline_db_session.commit()

        resp = await get_profile_activity_timeline(timeline_db_session, profile_id=p_id)
        assert resp.total == 5
        # Verify descending order (newest first: e-4, e-3, e-2, e-1, e-0)
        assert [it.id for it in resp.items] == ["e-4", "e-3", "e-2", "e-1", "e-0"]

    async def test_timeline_pagination_limit_and_offset(self, timeline_db_session: AsyncSession):
        p_id = f"prof-{uuid.uuid4().hex[:8]}"
        timeline_db_session.add(Profile(id=p_id, name="Test Patient"))

        base_time = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        recs = [
            AuditEventRecord(
                id=f"e-page-{i}",
                profile_id=p_id,
                principal="user",
                event="tool",
                tool="record_vitals",
                risk="write_local",
                external_ref=f"health_resource:hr-{i}",
                ts=base_time + timedelta(minutes=i),
                detail_redacted="{}",
            )
            for i in range(10)
        ]
        timeline_db_session.add_all(recs)
        await timeline_db_session.commit()

        # Page 1 (limit=3, offset=0)
        page1 = await get_profile_activity_timeline(timeline_db_session, profile_id=p_id, limit=3, offset=0)
        assert page1.total == 10
        assert len(page1.items) == 3
        assert page1.has_more is True
        assert page1.items[0].id == "e-page-9"

        # Page 2 (limit=3, offset=3)
        page2 = await get_profile_activity_timeline(timeline_db_session, profile_id=p_id, limit=3, offset=3)
        assert len(page2.items) == 3
        assert page2.has_more is True
        assert page2.items[0].id == "e-page-6"

        # Last page (limit=3, offset=9)
        last_page = await get_profile_activity_timeline(timeline_db_session, profile_id=p_id, limit=3, offset=9)
        assert len(last_page.items) == 1
        assert last_page.has_more is False
        assert last_page.items[0].id == "e-page-0"

    async def test_timeline_filters_by_tool_and_event(self, timeline_db_session: AsyncSession):
        p_id = f"prof-{uuid.uuid4().hex[:8]}"
        timeline_db_session.add(Profile(id=p_id, name="Test Patient"))
        now = datetime.now(timezone.utc)

        r_tool1 = AuditEventRecord(
            id="t-1",
            profile_id=p_id,
            principal="user",
            event="tool",
            tool="record_vitals",
            risk="write_local",
            external_ref="health_resource:hr-1",
            ts=now,
            detail_redacted="{}",
        )
        r_tool2 = AuditEventRecord(
            id="t-2",
            profile_id=p_id,
            principal="user",
            event="tool",
            tool="create_appointment",
            risk="write_local",
            external_ref="appointment:apt-1",
            ts=now,
            detail_redacted="{}",
        )
        r_refuse = AuditEventRecord(
            id="t-3",
            profile_id=p_id,
            principal="system",
            event="refuse",
            tool=None,
            risk=None,
            external_ref=None,
            ts=now,
            detail_redacted="{}",
        )
        timeline_db_session.add_all([r_tool1, r_tool2, r_refuse])
        await timeline_db_session.commit()

        # Filter by tool
        tool_resp = await get_profile_activity_timeline(timeline_db_session, profile_id=p_id, tool="record_vitals")
        assert tool_resp.total == 1
        assert tool_resp.items[0].id == "t-1"

        # Filter by event
        event_resp = await get_profile_activity_timeline(timeline_db_session, profile_id=p_id, event="refuse")
        assert event_resp.total == 1
        assert event_resp.items[0].id == "t-3"

    async def test_timeline_undoable_only_filter(self, timeline_db_session: AsyncSession):
        p_id = f"prof-{uuid.uuid4().hex[:8]}"
        timeline_db_session.add(Profile(id=p_id, name="Test Patient"))
        now = datetime.now(timezone.utc)

        # 1. Eligible write_local (recent)
        r_elig = AuditEventRecord(
            id="elig-1",
            profile_id=p_id,
            principal="user",
            event="tool",
            tool="record_vitals",
            risk="write_local",
            external_ref="health_resource:hr-1",
            ts=now - timedelta(days=1),
            detail_redacted="{}",
        )
        # 2. Expired write_local (> 7 days)
        r_exp = AuditEventRecord(
            id="exp-1",
            profile_id=p_id,
            principal="user",
            event="tool",
            tool="record_vitals",
            risk="write_local",
            external_ref="health_resource:hr-2",
            ts=now - timedelta(days=8),
            detail_redacted="{}",
        )
        # 3. Read risk (ineligible)
        r_read = AuditEventRecord(
            id="read-1",
            profile_id=p_id,
            principal="user",
            event="tool",
            tool="list_appointments",
            risk="read",
            external_ref="appointment:none",
            ts=now - timedelta(hours=1),
            detail_redacted="{}",
        )
        timeline_db_session.add_all([r_elig, r_exp, r_read])
        await timeline_db_session.commit()

        undoable_resp = await get_profile_activity_timeline(
            timeline_db_session,
            profile_id=p_id,
            undoable_only=True,
            now=now,
        )
        assert undoable_resp.total == 1
        assert len(undoable_resp.items) == 1
        assert undoable_resp.items[0].id == "elig-1"
        assert undoable_resp.items[0].undoable is True
