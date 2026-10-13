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

"""Empirical adversarial stress harness for Milestone 5 (AU-40):
Activity Timeline queries, multi-tenant profile isolation, profile_id NOT NULL scoping,
chronological ordering, pagination, undoable_only filtering, human-readable description synthesis,
and comprehensive API RBAC permission matrix verification.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict, List
import uuid

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
from carefold.clinical.undo import (
    ActionNotUndoableError,
    AlreadyUndoneError,
    UndoWindowExpiredError,
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
)
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app


def run_async(coro):
    """Executes asynchronous coroutine synchronously."""
    return asyncio.run(coro)


# ============================================================================
# Section 1: Timeline Query & Scoping Stress Tests
# ============================================================================

@pytest.fixture
async def stress_db_session():
    """Provides an isolated AsyncSession with SQLite in-memory database."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
class TestTimelineQueryAndScopingStress:
    """Empirical verification of timeline query isolation, scoping, sorting, and pagination."""

    async def test_multi_tenant_profile_isolation(self, stress_db_session: AsyncSession):
        """Events for Profile A must never leak into Profile B or Profile C's timeline."""
        prof_a = f"prof-a-{uuid.uuid4().hex[:6]}"
        prof_b = f"prof-b-{uuid.uuid4().hex[:6]}"
        prof_c = f"prof-c-{uuid.uuid4().hex[:6]}"

        stress_db_session.add_all([
            Profile(id=prof_a, name="Patient A"),
            Profile(id=prof_b, name="Patient B"),
            Profile(id=prof_c, name="Patient C"),
        ])

        now = datetime.now(timezone.utc)
        # Seed 10 events for A, 5 for B, 3 for C
        events_a = [
            AuditEventRecord(
                id=f"evt-a-{i}",
                profile_id=prof_a,
                principal="user",
                event="tool",
                tool="record_vitals",
                risk="write_local",
                external_ref=f"health_resource:hr-a-{i}",
                ts=now - timedelta(minutes=i),
                detail_redacted=json.dumps({"vitals": {"systolic": 110 + i, "diastolic": 70}}),
            )
            for i in range(10)
        ]
        events_b = [
            AuditEventRecord(
                id=f"evt-b-{i}",
                profile_id=prof_b,
                principal="user",
                event="tool",
                tool="create_appointment",
                risk="write_local",
                external_ref=f"appointment:apt-b-{i}",
                ts=now - timedelta(minutes=i),
                detail_redacted=json.dumps({"title": f"Visit B {i}"}),
            )
            for i in range(5)
        ]
        events_c = [
            AuditEventRecord(
                id=f"evt-c-{i}",
                profile_id=prof_c,
                principal="user",
                event="tool",
                tool="create_reminder",
                risk="write_local",
                external_ref=f"reminder:rem-c-{i}",
                ts=now - timedelta(minutes=i),
                detail_redacted=json.dumps({"title": f"Meds C {i}"}),
            )
            for i in range(3)
        ]
        stress_db_session.add_all(events_a + events_b + events_c)
        await stress_db_session.commit()

        # Query Profile B
        resp_b = await get_profile_activity_timeline(stress_db_session, profile_id=prof_b)
        assert resp_b.total == 5
        assert len(resp_b.items) == 5
        for item in resp_b.items:
            assert item.profile_id == prof_b
            assert item.id.startswith("evt-b-")
            assert not item.id.startswith("evt-a-")
            assert not item.id.startswith("evt-c-")

        # Query Profile A
        resp_a = await get_profile_activity_timeline(stress_db_session, profile_id=prof_a)
        assert resp_a.total == 10
        assert len(resp_a.items) == 10
        for item in resp_a.items:
            assert item.profile_id == prof_a

        # Query Profile C
        resp_c = await get_profile_activity_timeline(stress_db_session, profile_id=prof_c)
        assert resp_c.total == 3
        assert len(resp_c.items) == 3
        for item in resp_c.items:
            assert item.profile_id == prof_c

    async def test_profile_id_not_null_excludes_system_events(self, stress_db_session: AsyncSession):
        """System events without a profile_id (NULL) must be strictly excluded."""
        prof_id = f"prof-target-{uuid.uuid4().hex[:6]}"
        stress_db_session.add(Profile(id=prof_id, name="Target Patient"))

        now = datetime.now(timezone.utc)
        # Profile event
        p_event = AuditEventRecord(
            id="evt-target-1",
            profile_id=prof_id,
            principal="user",
            event="tool",
            tool="record_vitals",
            risk="write_local",
            external_ref="health_resource:hr-1",
            ts=now,
            detail_redacted=json.dumps({"vitals": {"heart_rate": 72}}),
        )
        # Global / System events with profile_id = None
        sys_event_1 = AuditEventRecord(
            id="evt-sys-1",
            profile_id=None,
            principal="system",
            event="run",
            tool="system_cleanup",
            risk="read",
            external_ref=None,
            ts=now,
            detail_redacted="{}",
        )
        sys_event_2 = AuditEventRecord(
            id="evt-sys-2",
            profile_id=None,
            principal="orchestrator",
            event="tool",
            tool="list_agents",
            risk="read",
            external_ref=None,
            ts=now,
            detail_redacted="{}",
        )
        stress_db_session.add_all([p_event, sys_event_1, sys_event_2])
        await stress_db_session.commit()

        resp = await get_profile_activity_timeline(stress_db_session, profile_id=prof_id)
        assert resp.total == 1
        assert len(resp.items) == 1
        assert resp.items[0].id == "evt-target-1"
        assert resp.items[0].profile_id == prof_id

    async def test_chronological_descending_order_precision(self, stress_db_session: AsyncSession):
        """Events must appear in strict chronological descending order (newest first)."""
        prof_id = f"prof-order-{uuid.uuid4().hex[:6]}"
        stress_db_session.add(Profile(id=prof_id, name="Order Patient"))

        base_time = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
        # Insert out of order: t+30s, t+10s, t+60s, t+0s, t+45s
        offsets_sec = [30, 10, 60, 0, 45]
        events = [
            AuditEventRecord(
                id=f"evt-order-{sec}",
                profile_id=prof_id,
                principal="user",
                event="tool",
                tool="record_vitals",
                risk="write_local",
                external_ref=f"health_resource:hr-{sec}",
                ts=base_time + timedelta(seconds=sec),
                detail_redacted=json.dumps({"vitals": {"pulse": 60 + sec}}),
            )
            for sec in offsets_sec
        ]
        stress_db_session.add_all(events)
        await stress_db_session.commit()

        resp = await get_profile_activity_timeline(stress_db_session, profile_id=prof_id)
        assert resp.total == 5
        expected_id_order = ["evt-order-60", "evt-order-45", "evt-order-30", "evt-order-10", "evt-order-0"]
        actual_id_order = [it.id for it in resp.items]
        assert actual_id_order == expected_id_order

    async def test_pagination_limit_offset_slicing(self, stress_db_session: AsyncSession):
        """Limit and offset must correctly slice the result set and calculate has_more."""
        prof_id = f"prof-page-{uuid.uuid4().hex[:6]}"
        stress_db_session.add(Profile(id=prof_id, name="Pagination Patient"))

        base_time = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        total_items = 15
        events = [
            AuditEventRecord(
                id=f"e-{i:02d}",
                profile_id=prof_id,
                principal="user",
                event="tool",
                tool="create_reminder",
                risk="write_local",
                external_ref=f"reminder:r-{i}",
                ts=base_time + timedelta(minutes=i),
                detail_redacted=json.dumps({"title": f"Reminder {i}"}),
            )
            for i in range(total_items)
        ]
        stress_db_session.add_all(events)
        await stress_db_session.commit()

        # Page 1: limit 5, offset 0 -> newest items e-14 .. e-10
        p1 = await get_profile_activity_timeline(stress_db_session, profile_id=prof_id, limit=5, offset=0)
        assert p1.total == 15
        assert len(p1.items) == 5
        assert p1.has_more is True
        assert [it.id for it in p1.items] == ["e-14", "e-13", "e-12", "e-11", "e-10"]

        # Page 2: limit 5, offset 5 -> e-09 .. e-05
        p2 = await get_profile_activity_timeline(stress_db_session, profile_id=prof_id, limit=5, offset=5)
        assert p2.total == 15
        assert len(p2.items) == 5
        assert p2.has_more is True
        assert [it.id for it in p2.items] == ["e-09", "e-08", "e-07", "e-06", "e-05"]

        # Page 3: limit 5, offset 10 -> e-04 .. e-00 (last page)
        p3 = await get_profile_activity_timeline(stress_db_session, profile_id=prof_id, limit=5, offset=10)
        assert p3.total == 15
        assert len(p3.items) == 5
        assert p3.has_more is False
        assert [it.id for it in p3.items] == ["e-04", "e-03", "e-02", "e-01", "e-00"]

        # Beyond total: offset 20
        p_empty = await get_profile_activity_timeline(stress_db_session, profile_id=prof_id, limit=5, offset=20)
        assert p_empty.total == 15
        assert len(p_empty.items) == 0
        assert p_empty.has_more is False

    async def test_undoable_only_filter_strictly_matches_criteria(self, stress_db_session: AsyncSession):
        """undoable_only must return only events meeting all single-click undo requirements."""
        prof_id = f"prof-undoable-{uuid.uuid4().hex[:6]}"
        stress_db_session.add(Profile(id=prof_id, name="Undoable Patient"))

        now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

        # 1. Recent write_local (ELIGIBLE)
        r_elig = AuditEventRecord(
            id="elig-write-local",
            profile_id=prof_id,
            principal="user",
            event="tool",
            tool="record_vitals",
            risk="write_local",
            external_ref="health_resource:hr-1",
            ts=now - timedelta(days=2),
            detail_redacted=json.dumps({"vitals": {"systolic": 120, "diastolic": 80}}),
        )
        # 2. Older than 7 days (INELIGIBLE)
        r_expired = AuditEventRecord(
            id="inelig-expired",
            profile_id=prof_id,
            principal="user",
            event="tool",
            tool="create_appointment",
            risk="write_local",
            external_ref="appointment:apt-1",
            ts=now - timedelta(days=7, seconds=5),
            detail_redacted=json.dumps({"title": "Old Appointment"}),
        )
        # 3. Read risk tier (INELIGIBLE)
        r_read = AuditEventRecord(
            id="inelig-read",
            profile_id=prof_id,
            principal="user",
            event="tool",
            tool="list_reminders",
            risk="read",
            external_ref="reminder:none",
            ts=now - timedelta(hours=2),
            detail_redacted="{}",
        )
        # 4. Already undone event (INELIGIBLE)
        r_undone = AuditEventRecord(
            id="inelig-undone",
            profile_id=prof_id,
            principal="user",
            event="tool",
            tool="create_reminder",
            risk="write_local",
            external_ref="reminder:rem-1",
            ts=now - timedelta(days=1),
            detail_redacted=json.dumps({"title": "Cancelled reminder"}),
        )
        # Undo reversal event referencing inelig-undone
        r_undo_action = AuditEventRecord(
            id="undo-action-1",
            profile_id=prof_id,
            principal="user",
            event="undo",
            tool="undo",
            risk="write_local",
            external_ref="reminder:rem-1",
            ts=now - timedelta(hours=1),
            detail_redacted=json.dumps({"undone_event_id": "inelig-undone"}),
        )
        # 5. Missing external_ref (INELIGIBLE)
        r_no_ref = AuditEventRecord(
            id="inelig-no-ref",
            profile_id=prof_id,
            principal="user",
            event="tool",
            tool="record_vitals",
            risk="write_local",
            external_ref=None,
            ts=now - timedelta(hours=3),
            detail_redacted="{}",
        )

        stress_db_session.add_all([r_elig, r_expired, r_read, r_undone, r_undo_action, r_no_ref])
        await stress_db_session.commit()

        res = await get_profile_activity_timeline(
            stress_db_session,
            profile_id=prof_id,
            undoable_only=True,
            now=now,
        )
        assert len(res.items) == 1
        assert res.items[0].id == "elig-write-local"
        assert res.items[0].undoable is True


# ============================================================================
# Section 2: Description Synthesis & Edge Case Stress Tests
# ============================================================================

class TestDescriptionSynthesisEdgeCasesStress:
    """Verifies all 7 tool patterns and adversarial edge cases for description synthesis."""

    @pytest.mark.parametrize("tool_name,details,expected_summary_substr", [
        ("record_vitals", {"vitals": {"systolic": 130, "diastolic": 85}}, "Logged blood pressure 130/85 mmHg"),
        ("record_vitals", {"vitals": {"heart_rate": 80}}, "Logged heart rate 80 bpm"),
        ("record_vitals", {"vitals": {"blood_glucose": 95, "unit": "mg/dL"}}, "Logged blood glucose 95 mg/dL"),
        ("record_vitals", {"vitals": {"spo2": 99}}, "Logged oxygen saturation 99%"),
        ("record_vitals", {"vitals": {"weight": 68, "unit": "kg"}}, "Recorded weight 68 kg"),
        ("record_vitals", {"vitals": {"height": 172, "unit": "cm"}}, "Recorded height 172 cm"),
        ("create_appointment", {"provider_name": "Dr. Sarah", "specialty": "Cardiology"}, "Scheduled appointment with Dr. Sarah (Cardiology)"),
        ("create_appointment", {"title": "General Consultation"}, "Scheduled appointment: General Consultation"),
        ("update_appointment_status", {"new_status": "completed"}, "Updated appointment status to completed"),
        ("update_appointment_status", {"new_status": "cancelled"}, "Updated appointment status to cancelled"),
        ("create_reminder", {"category": "medication", "title": "Atorvastatin 20mg"}, "Created medication reminder: Atorvastatin 20mg"),
        ("create_reminder", {"category": "vitals", "title": "Evening BP"}, "Created vitals reminder: Evening BP"),
        ("generate_prep_pack", {"specialty": "Neurology"}, "Generated consultation prep pack for Neurology visit"),
        ("create_typed_note", {"type": "visit", "title": "Cardiology Followup"}, "Created visit note: Cardiology Followup"),
        ("create_typed_note", {"type": "after_visit", "title": "Summary & Meds"}, "Created after_visit note: Summary & Meds"),
        ("undo", {"reverted_summary": "Scheduled appointment with Dr. Sarah"}, "Reverted action: Scheduled appointment with Dr. Sarah"),
    ])
    def test_all_7_tool_patterns_standard_payloads(self, tool_name, details, expected_summary_substr):
        summary, desc = synthesize_activity_summary(
            action="tool" if tool_name != "undo" else "undo",
            tool=tool_name,
            details=details,
            external_ref="appointment:apt-1",
        )
        assert expected_summary_substr in summary
        assert desc is not None and len(desc) > 0

    def test_missing_details_empty_dict_fallback(self):
        """All 7 tools must handle details={} without crashing."""
        tools = [
            "record_vitals",
            "create_appointment",
            "update_appointment_status",
            "create_reminder",
            "generate_prep_pack",
            "create_typed_note",
            "undo",
        ]
        for t in tools:
            s, d = synthesize_activity_summary(
                action="tool" if t != "undo" else "undo",
                tool=t,
                details={},
                external_ref="appointment:1" if t != "undo" else "health_resource:1",
            )
            assert s is not None and len(s) > 0
            assert d is not None and len(d) > 0

    def test_malformed_json_in_audit_record(self):
        """format_audit_event_as_activity_item handles malformed JSON string gracefully."""
        rec = AuditEventRecord(
            id="bad-json-1",
            profile_id="prof-1",
            principal="user",
            event="tool",
            tool="record_vitals",
            risk="write_local",
            external_ref="health_resource:hr-1",
            ts=datetime.now(timezone.utc),
            detail_redacted="{corrupted json string",
        )
        item = format_audit_event_as_activity_item(rec, set())
        assert item.summary == "Logged vital signs observation"
        assert item.description == "Recorded clinical observation in health resources."
        assert item.details == {}

    def test_empty_string_and_none_detail_redacted(self):
        """format_audit_event_as_activity_item handles empty string and None detail_redacted."""
        rec_empty = AuditEventRecord(
            id="empty-str-1",
            profile_id="prof-1",
            principal="user",
            event="tool",
            tool="create_appointment",
            risk="write_local",
            external_ref="appointment:apt-1",
            ts=datetime.now(timezone.utc),
            detail_redacted="",
        )
        item_empty = format_audit_event_as_activity_item(rec_empty, set())
        assert item_empty.summary == "Scheduled appointment: Consultation"

        rec_none = AuditEventRecord(
            id="none-str-1",
            profile_id="prof-1",
            principal="user",
            event="tool",
            tool="create_reminder",
            risk="write_local",
            external_ref="reminder:rem-1",
            ts=datetime.now(timezone.utc),
            detail_redacted=None,
        )
        item_none = format_audit_event_as_activity_item(rec_none, set())
        assert item_none.summary == "Created reminder: Reminder"


# ============================================================================
# Section 3: RBAC Matrix Verification Stress Tests
# ============================================================================

@pytest.fixture
def rbac_env(monkeypatch):
    """Sets up an isolated database and users with distinct RBAC permissions."""
    async def _setup():
        engine = create_db_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = get_session_factory(engine)
        auth_adapter = SqlAuthAdapter(session_factory=session_factory)

        monkeypatch.setattr(settings, "auth_provider", "local")
        set_auth_port(auth_adapter)

        # 1. Alice (manage access)
        alice = await auth_adapter.register_user(
            email="alice@rbac.test",
            username="alice",
            password="AlicePassword123!",
            full_name="Alice Manage",
            role="member",
            auth_provider="local",
        )
        alice_session = await auth_adapter.create_session(alice.id)

        # 2. Charlie (view_clinical access)
        charlie = await auth_adapter.register_user(
            email="charlie@rbac.test",
            username="charlie",
            password="CharliePassword123!",
            full_name="Charlie Clinician",
            role="member",
            auth_provider="local",
        )
        charlie_session = await auth_adapter.create_session(charlie.id)

        # 3. Dan (view_paperwork access)
        dan = await auth_adapter.register_user(
            email="dan@rbac.test",
            username="dan",
            password="DanPassword123!",
            full_name="Dan Paperwork",
            role="member",
            auth_provider="local",
        )
        dan_session = await auth_adapter.create_session(dan.id)

        # 4. Eve (foreign user - zero access)
        eve = await auth_adapter.register_user(
            email="eve@rbac.test",
            username="eve",
            password="EvePassword123!",
            full_name="Eve Foreign",
            role="member",
            auth_provider="local",
        )
        eve_session = await auth_adapter.create_session(eve.id)

        profile_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        appt_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with session_factory() as session:
            session.add(Profile(id=profile_id, user_id=alice.id, name="Target Profile"))
            session.add(ProfileAccess(profile_id=profile_id, user_id=charlie.id, access_level="view_clinical"))
            session.add(ProfileAccess(profile_id=profile_id, user_id=dan.id, access_level="view_paperwork"))

            # Seed an appointment and undoable audit event
            session.add(
                Appointment(
                    id=appt_id,
                    profile_id=profile_id,
                    title="Cardiology Visit",
                    start_time=now,
                    end_time=now + timedelta(hours=1),
                    status="scheduled",
                )
            )
            session.add(
                AuditEventRecord(
                    id=event_id,
                    profile_id=profile_id,
                    principal="user",
                    event="tool",
                    tool="create_appointment",
                    risk="write_local",
                    external_ref=f"appointment:{appt_id}",
                    ts=now,
                    detail_redacted=json.dumps({"title": "Cardiology Visit"}),
                )
            )
            await session.commit()

        return {
            "engine": engine,
            "session_factory": session_factory,
            "profile_id": profile_id,
            "event_id": event_id,
            "appt_id": appt_id,
            "tokens": {
                "manage": alice_session.token,
                "view_clinical": charlie_session.token,
                "view_paperwork": dan_session.token,
                "no_access": eve_session.token,
            },
        }

    env = run_async(_setup())

    async def _override_get_db():
        async with env["session_factory"]() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    yield env
    app.dependency_overrides.pop(get_db, None)
    reset_auth_port()
    run_async(env["engine"].dispose())


class TestRBACMatrixVerificationStress:
    """Rigorous verification of the RBAC access control matrix across all roles."""

    def test_unauthenticated_returns_401(self, rbac_env):
        """Calls without token must return HTTP 401."""
        client = TestClient(app)
        pid = rbac_env["profile_id"]
        eid = rbac_env["event_id"]

        r_get = client.get(f"/api/profiles/{pid}/activity")
        assert r_get.status_code == 401, f"Expected 401 on GET, got {r_get.status_code}"

        r_post = client.post(f"/api/profiles/{pid}/activity/{eid}/undo")
        assert r_post.status_code == 401, f"Expected 401 on POST, got {r_post.status_code}"

    def test_view_paperwork_forbidden_403_on_both_endpoints(self, rbac_env):
        """view_paperwork role must receive HTTP 403 on both GET activity and POST undo."""
        client = TestClient(app)
        pid = rbac_env["profile_id"]
        eid = rbac_env["event_id"]
        token = rbac_env["tokens"]["view_paperwork"]

        r_get = client.get(
            f"/api/profiles/{pid}/activity",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r_get.status_code == 403, f"Expected 403 on GET for view_paperwork, got {r_get.status_code}"

        r_post = client.post(
            f"/api/profiles/{pid}/activity/{eid}/undo",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r_post.status_code == 403, f"Expected 403 on POST for view_paperwork, got {r_post.status_code}"

    def test_view_clinical_allowed_for_get_forbidden_for_post_undo(self, rbac_env):
        """view_clinical role is allowed for GET activity (HTTP 200) but forbidden for POST undo (HTTP 403)."""
        client = TestClient(app)
        pid = rbac_env["profile_id"]
        eid = rbac_env["event_id"]
        token = rbac_env["tokens"]["view_clinical"]

        # GET activity allowed
        r_get = client.get(
            f"/api/profiles/{pid}/activity",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r_get.status_code == 200, f"Expected 200 on GET for view_clinical, got {r_get.status_code}"
        data = r_get.json()
        assert data["profile_id"] == pid
        assert len(data["items"]) >= 1

        # POST undo forbidden
        r_post = client.post(
            f"/api/profiles/{pid}/activity/{eid}/undo",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r_post.status_code == 403, f"Expected 403 on POST for view_clinical, got {r_post.status_code}"

    def test_manage_role_allowed_for_both_get_and_post_undo(self, rbac_env):
        """manage role is permitted for both GET activity (HTTP 200) and POST undo (HTTP 200)."""
        client = TestClient(app)
        pid = rbac_env["profile_id"]
        eid = rbac_env["event_id"]
        token = rbac_env["tokens"]["manage"]

        # GET activity allowed
        r_get = client.get(
            f"/api/profiles/{pid}/activity",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r_get.status_code == 200, f"Expected 200 on GET for manage, got {r_get.status_code}"

        # POST undo allowed
        r_post = client.post(
            f"/api/profiles/{pid}/activity/{eid}/undo",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r_post.status_code == 200, f"Expected 200 on POST for manage, got {r_post.status_code}"
        data = r_post.json()
        assert data["status"] == "undone"
        assert data["event_id"] == eid

    def test_foreign_user_forbidden_403_on_both_endpoints(self, rbac_env):
        """User with no access grants receives HTTP 403 on both endpoints."""
        client = TestClient(app)
        pid = rbac_env["profile_id"]
        eid = rbac_env["event_id"]
        token = rbac_env["tokens"]["no_access"]

        r_get = client.get(
            f"/api/profiles/{pid}/activity",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r_get.status_code == 403, f"Expected 403 on GET for no_access, got {r_get.status_code}"

        r_post = client.post(
            f"/api/profiles/{pid}/activity/{eid}/undo",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r_post.status_code == 403, f"Expected 403 on POST for no_access, got {r_post.status_code}"

    def test_nonexistent_profile_returns_404(self, rbac_env):
        """Requests for a non-existent profile UUID return HTTP 404."""
        client = TestClient(app)
        token = rbac_env["tokens"]["manage"]
        bogus_pid = str(uuid.uuid4())
        eid = rbac_env["event_id"]

        r_get = client.get(
            f"/api/profiles/{bogus_pid}/activity",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r_get.status_code == 404, f"Expected 404 on GET for nonexistent profile, got {r_get.status_code}"

        r_post = client.post(
            f"/api/profiles/{bogus_pid}/activity/{eid}/undo",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r_post.status_code == 404, f"Expected 404 on POST for nonexistent profile, got {r_post.status_code}"
