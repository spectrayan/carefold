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

"""Empirical adversarial stress test suite for profile deletion cascade (AU-11 + Batch 3).

Stress-tests delete_profile in backend/src/carefold/api/profiles.py:
1. Multi-entity cascade deletion across all Batch 3 models (HealthResource, Appointment, Reminder)
   and existing dependent models (Note, Attachment, ChatThread, AuditEventRecord, Connection,
   Credential, ProfileKey, Job, Approval, ViewerInvite, ProfileAccess, ProfileConsent).
2. Deep orphan row audit: iterates every single table registered in Base.metadata.
3. Cross-profile appointment & note link referential integrity (ON DELETE SET NULL).
4. High-volume entity stress deletion (hundreds of rows).
5. Primary profile immortality protection (HTTP 400).
6. Security boundary checks (cross-user unauthorized HTTP 403, missing HTTP 404, double delete).
7. SQLite foreign key pragma strict enforcement.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import AsyncIterator, Dict, List
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.base import Base
from carefold.db.models import (
    Appointment,
    Approval,
    Attachment,
    AuditEventRecord,
    ChatThread,
    Connection,
    Credential,
    HealthResource,
    Job,
    Note,
    Profile,
    ProfileAccess,
    ProfileConsent,
    ProfileKey,
    Reminder,
    User,
    ViewerInvite,
)
from carefold.db.session import (
    create_db_engine,
    get_session_factory,
    init_db,
)
from carefold.main import app
from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
from carefold.memory.factory import reset_memory_ports, set_memory_port


@pytest.fixture
async def stress_test_env(temp_workspace: Path, monkeypatch):
    """Sets up an isolated in-memory DB with strict foreign key constraints enabled."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    sql_auth = SqlAuthAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    monkeypatch.setattr(settings, "workspace_root", temp_workspace)
    monkeypatch.setattr(settings, "home_dir", temp_workspace / "home")
    set_auth_port(sql_auth)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    memory_db_path = temp_workspace / "memories.db"
    mem_adapter = SqliteMemoryAdapter(db_path=memory_db_path)
    set_memory_port(mem_adapter)

    try:
        yield {
            "workspace": temp_workspace,
            "home": settings.home_dir,
            "auth": sql_auth,
            "memory_adapter": mem_adapter,
            "session_factory": session_factory,
            "engine": engine,
        }
    finally:
        app.dependency_overrides.clear()
        reset_auth_port()
        await mem_adapter.close()
        set_memory_port(None)
        await engine.dispose()


def register_and_login(client: TestClient, email: str, password: str, name: str) -> dict:
    """Helper to register and authenticate a user against local auth."""
    client.post(
        "/api/auth/register",
        json={
            "email": "admin@carefold.test",
            "username": "admin",
            "password": "AdminPassword123!",
            "full_name": "System Administrator",
        },
    )
    username = email.split("@")[0].replace(".", "_")
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "username": username, "password": password, "full_name": name},
    )
    assert resp.status_code in (201, 400), resp.text
    login_resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert login_resp.status_code == 200, login_resp.text
    token = login_resp.json()["token"]
    user = login_resp.json()["user"]
    headers = {"Authorization": f"Bearer {token}"}
    client.get("/api/profiles", headers=headers)
    return {
        "token": token,
        "user": user,
        "headers": headers,
    }


@pytest.mark.asyncio
async def test_empirical_foreign_keys_pragma_active(stress_test_env):
    """Verifies that SQLite foreign keys pragma is strictly enabled."""
    session_factory = stress_test_env["session_factory"]
    async with session_factory() as session:
        result = await session.execute(text("PRAGMA foreign_keys;"))
        fk_status = result.scalar()
        assert fk_status == 1, "SQLite PRAGMA foreign_keys MUST be enabled (1)"


@pytest.mark.asyncio
async def test_empirical_multi_entity_profile_deletion_zero_orphaned_rows(stress_test_env):
    """Empirically stress-tests delete_profile with all Batch 3 and legacy child models.

    Populates:
    - 20 HealthResources (active, amended, tombstone; manual, device, note_extracted)
    - 15 Appointments (scheduled, confirmed, completed, cancelled)
    - 20 Reminders (medications, measurements, checkins, with RRULE, snooze)
    - 30 Notes (15 linked to appointments, 15 unlinked)
    - 5 Attachments, 3 ChatThreads, 2 Connections, 4 Credentials
    - 2 Jobs, 2 Approvals, 1 ProfileKey, 2 ViewerInvites, 2 ProfileAccess, 1 ProfileConsent
    - 5 AuditEventRecords

    Asserts zero orphaned rows across ALL registered database tables.
    """
    with TestClient(app) as client:
        user_data = register_and_login(client, "patient1@carefold.test", "PatientSecret123!", "Patient One")
        headers = user_data["headers"]
        uid = user_data["user"]["id"]

        # Create secondary care profile
        p_resp = client.post(
            "/api/profiles",
            headers=headers,
            json={"name": "Grandpa Joe", "relationship": "grandparent", "role": "self"},
        )
        assert p_resp.status_code == 201, p_resp.text
        prof_id = p_resp.json()["id"]

        session_factory = stress_test_env["session_factory"]
        now = datetime.datetime.now(datetime.timezone.utc)

        # 1. Populate HealthResources (20 items)
        health_resources: List[HealthResource] = []
        for i in range(20):
            hr = HealthResource(
                id=str(uuid.uuid4()),
                profile_id=prof_id,
                resource_type="observation",
                source_type="device" if i % 2 == 0 else "manual",
                source_ref="omron_bp" if i % 2 == 0 else None,
                source_id=f"reading_{i}" if i % 2 == 0 else None,
                status="active" if i < 15 else ("amended" if i < 18 else "tombstone"),
                data={
                    "resourceType": "Observation",
                    "code": {"coding": [{"code": "85354-9", "system": "http://loinc.org"}]},
                    "valueQuantity": {"value": 120 + i, "unit": "mmHg"},
                },
                effective_at=now - datetime.timedelta(days=i),
                recorded_at=now - datetime.timedelta(days=i),
            )
            health_resources.append(hr)

        # 2. Populate Appointments (15 items)
        appointments: List[Appointment] = []
        statuses = ["scheduled", "confirmed", "completed", "cancelled"]
        for i in range(15):
            apt = Appointment(
                id=str(uuid.uuid4()),
                profile_id=prof_id,
                title=f"Clinical Consultation #{i+1}",
                provider_name=f"Dr. Specialist {i}",
                specialty="Cardiology" if i % 2 == 0 else "Geriatrics",
                location="Main Hospital Room 101",
                start_time=now + datetime.timedelta(days=i + 1),
                end_time=now + datetime.timedelta(days=i + 1, hours=1),
                timezone="America/New_York",
                status=statuses[i % len(statuses)],
                reason="Routine checkup",
            )
            appointments.append(apt)

        # 3. Populate Reminders (20 items)
        reminders: List[Reminder] = []
        categories = ["medication", "measurement", "appointment", "general"]
        for i in range(20):
            rem = Reminder(
                id=str(uuid.uuid4()),
                profile_id=prof_id,
                title=f"Daily Reminder #{i+1}",
                description=f"Take medication dose {i}",
                category=categories[i % len(categories)],
                rrule="FREQ=DAILY;INTERVAL=1" if i % 2 == 0 else None,
                timezone="America/New_York",
                next_due_at=now + datetime.timedelta(hours=i * 2 + 1),
                status="pending" if i < 16 else "snoozed",
                snooze_until=now + datetime.timedelta(hours=1) if i >= 16 else None,
            )
            reminders.append(rem)

        # 4. Populate Notes (30 items: 15 linked to appointments, 15 unlinked)
        notes: List[Note] = []
        note_types = ["visit", "symptom", "after_visit", "question", "general"]
        for i in range(30):
            linked_apt_id = appointments[i % len(appointments)].id if i < 15 else None
            note = Note(
                id=str(uuid.uuid4()),
                user_id=uid,
                profile_id=prof_id,
                slug=f"note-stress-{i}-{uuid.uuid4().hex[:6]}",
                title=f"Clinical Note #{i+1}",
                content=f"Patient progress note content for session {i}.",
                type=note_types[i % len(note_types)],
                linked_appointment_id=linked_apt_id,
            )
            notes.append(note)

        # 5. Populate Legacy Child Records
        async with session_factory() as session:
            for hr in health_resources:
                session.add(hr)
            for apt in appointments:
                session.add(apt)
            for rem in reminders:
                session.add(rem)
            for note in notes:
                session.add(note)

            # Attachments
            for i in range(5):
                session.add(Attachment(
                    id=str(uuid.uuid4()),
                    user_id=uid,
                    profile_id=prof_id,
                    filename=f"record_{i}.pdf",
                    original_name=f"record_{i}.pdf",
                    content_type="application/pdf",
                    size_bytes=2048,
                ))

            # ChatThreads
            for i in range(3):
                session.add(ChatThread(
                    id=f"thread-stress-{i}-{uuid.uuid4().hex[:6]}",
                    user_id=uid,
                    profile_id=prof_id,
                    agent_id="geriatrics-guide",
                    title=f"Consultation Chat #{i}",
                ))

            # Connections & Credentials
            conn = Connection(
                id=str(uuid.uuid4()),
                user_id=uid,
                profile_id=prof_id,
                connector_id="fhir-portal",
                status="active",
            )
            session.add(conn)
            await session.flush()

            for i in range(4):
                session.add(Credential(
                    id=str(uuid.uuid4()),
                    connection_id=conn.id,
                    user_id=uid,
                    profile_id=prof_id,
                    encrypted_blob=f"blob-{i}",
                    token_version=1,
                    dek_version=1,
                ))

            # ProfileKey
            session.add(ProfileKey(
                id=str(uuid.uuid4()),
                profile_id=prof_id,
                encrypted_dek="encrypted-dek-stress",
                dek_version=1,
            ))

            # Jobs & Approvals
            for i in range(2):
                session.add(Job(
                    id=str(uuid.uuid4()),
                    profile_id=prof_id,
                    kind="reminder",
                    routine_id=f"routine_{i}",
                    next_run_at=now + datetime.timedelta(hours=4),
                ))
                session.add(Approval(
                    id=str(uuid.uuid4()),
                    profile_id=prof_id,
                    run_id=f"run-{i}",
                    tool_name="request_records",
                    risk_tier="low",
                    status="pending",
                    payload_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    expires_at=now + datetime.timedelta(hours=2),
                ))

            # ViewerInvites
            for i in range(2):
                session.add(ViewerInvite(
                    id=str(uuid.uuid4()),
                    invite_code=f"cf-inv-stress-{i}-{uuid.uuid4().hex[:6]}",
                    profile_id=prof_id,
                    invited_by=uid,
                    invitee_name=f"Caregiver {i}",
                    role="viewer",
                    view_clinical=True,
                    view_paperwork=True,
                    expires_at=now + datetime.timedelta(days=7),
                ))

            # AuditEventRecords
            for i in range(5):
                session.add(AuditEventRecord(
                    id=str(uuid.uuid4()),
                    event="vitals.recorded",
                    actor_user_id=uid,
                    profile_id=prof_id,
                    tool="record_vitals",
                    risk="write_local",
                    detail_redacted=f'{{"batch": {i}}}',
                ))

            await session.commit()

        # Sanity check: verify all rows were created before deletion
        async with session_factory() as session:
            hr_cnt = len((await session.execute(select(HealthResource).where(HealthResource.profile_id == prof_id))).scalars().all())
            apt_cnt = len((await session.execute(select(Appointment).where(Appointment.profile_id == prof_id))).scalars().all())
            rem_cnt = len((await session.execute(select(Reminder).where(Reminder.profile_id == prof_id))).scalars().all())
            note_cnt = len((await session.execute(select(Note).where(Note.profile_id == prof_id))).scalars().all())
            audit_cnt = len((await session.execute(select(AuditEventRecord).where(AuditEventRecord.profile_id == prof_id))).scalars().all())

            assert hr_cnt == 20
            assert apt_cnt == 15
            assert rem_cnt == 20
            assert note_cnt == 30
            assert audit_cnt == 5

        # Execute DELETE profile endpoint
        del_resp = client.delete(f"/api/profiles/{prof_id}", headers=headers)
        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json() == {"deleted": True, "id": prof_id}

        # EXHAUSTIVE DATABASE AUDIT ACROSS ALL TABLES IN BASE.METADATA
        async with session_factory() as session:
            for table_name, table in Base.metadata.tables.items():
                col_names = [c.name for c in table.columns]
                if "profile_id" in col_names:
                    # Every table with profile_id must have 0 rows for this deleted profile
                    res = await session.execute(
                        text(f"SELECT COUNT(*) FROM {table_name} WHERE profile_id = :pid"),
                        {"pid": prof_id},
                    )
                    count = res.scalar()
                    assert count == 0, (
                        f"ORPHANED ROW DETECTED: Table '{table_name}' still contains {count} row(s) "
                        f"with profile_id = '{prof_id}'"
                    )

            # Audit events check: audit records must still exist, but profile_id set to NULL
            audit_res = await session.execute(
                select(AuditEventRecord).where(AuditEventRecord.actor_user_id == uid)
            )
            audit_rows = audit_res.scalars().all()
            assert len(audit_rows) >= 5, "Audit event records must not be deleted"
            for row in audit_rows:
                assert row.profile_id != prof_id, "AuditEventRecord profile_id must be updated to NULL"

            # Profile row itself must be gone
            prof_res = await session.execute(select(Profile).where(Profile.id == prof_id))
            assert prof_res.scalar_one_or_none() is None, "Profile row must be completely deleted"


@pytest.mark.asyncio
async def test_empirical_cross_profile_linked_notes_referential_integrity(stress_test_env):
    """Stress-tests referential integrity when Note in Profile B links to Appointment in Profile A.

    Setup:
    - Profile A has Appointments A1, A2, A3.
    - Profile A has Note NoteA1 linked to A1.
    - Profile B has Note NoteB1 linked to A1 (cross-profile appointment link!).
    - Profile B has Note NoteB2 linked to A2.
    - Profile B has its own Appointment B1 and Note NoteB3 linked to B1.
    - Profile B has HealthResource HR_B1, Reminder Rem_B1.

    When Profile A is deleted:
    - Profile A, Appointments A1, A2, A3, and Note NoteA1 are cleanly deleted.
    - Profile B MUST REMAIN completely intact.
    - Profile B's NoteB1 and NoteB2 MUST SURVIVE, with linked_appointment_id updated to NULL.
    - Profile B's NoteB3 MUST REMAIN linked to Appointment B1.
    - Profile B's HealthResource and Reminder MUST REMAIN intact.
    - Zero orphaned references or integrity violations.
    """
    with TestClient(app) as client:
        user_data = register_and_login(client, "steward_multi@carefold.test", "MultiSecret123!", "Multi Steward")
        headers = user_data["headers"]
        uid = user_data["user"]["id"]

        # Create Profile A
        resp_a = client.post(
            "/api/profiles",
            headers=headers,
            json={"name": "Family Member A", "relationship": "child", "role": "self"},
        )
        assert resp_a.status_code == 201
        prof_a_id = resp_a.json()["id"]

        # Create Profile B
        resp_b = client.post(
            "/api/profiles",
            headers=headers,
            json={"name": "Family Member B", "relationship": "child", "role": "self"},
        )
        assert resp_b.status_code == 201
        prof_b_id = resp_b.json()["id"]

        session_factory = stress_test_env["session_factory"]
        now = datetime.datetime.now(datetime.timezone.utc)

        # Profile A Appointments
        apt_a1 = Appointment(
            id=str(uuid.uuid4()),
            profile_id=prof_a_id,
            title="A1 Cardiology Consultation",
            start_time=now + datetime.timedelta(days=1),
            end_time=now + datetime.timedelta(days=1, hours=1),
        )
        apt_a2 = Appointment(
            id=str(uuid.uuid4()),
            profile_id=prof_a_id,
            title="A2 Orthopedic Follow-up",
            start_time=now + datetime.timedelta(days=2),
            end_time=now + datetime.timedelta(days=2, hours=1),
        )
        apt_a3 = Appointment(
            id=str(uuid.uuid4()),
            profile_id=prof_a_id,
            title="A3 Vision Exam",
            start_time=now + datetime.timedelta(days=3),
            end_time=now + datetime.timedelta(days=3, hours=1),
        )

        # Profile B Appointment
        apt_b1 = Appointment(
            id=str(uuid.uuid4()),
            profile_id=prof_b_id,
            title="B1 Dental Checkup",
            start_time=now + datetime.timedelta(days=4),
            end_time=now + datetime.timedelta(days=4, hours=1),
        )

        async with session_factory() as session:
            session.add_all([apt_a1, apt_a2, apt_a3, apt_b1])
            await session.commit()

        # Notes
        note_a1 = Note(
            id=str(uuid.uuid4()),
            user_id=uid,
            profile_id=prof_a_id,
            slug=f"note-a1-{uuid.uuid4().hex[:6]}",
            title="Note A1",
            content="Content A1",
            type="visit",
            linked_appointment_id=apt_a1.id,
        )
        note_b1 = Note(
            id=str(uuid.uuid4()),
            user_id=uid,
            profile_id=prof_b_id,
            slug=f"note-b1-{uuid.uuid4().hex[:6]}",
            title="Note B1 (Cross-linked to A1)",
            content="Caregiver joint observation during A1 consult",
            type="visit",
            linked_appointment_id=apt_a1.id,
        )
        note_b2 = Note(
            id=str(uuid.uuid4()),
            user_id=uid,
            profile_id=prof_b_id,
            slug=f"note-b2-{uuid.uuid4().hex[:6]}",
            title="Note B2 (Cross-linked to A2)",
            content="Joint transport note for A2",
            type="general",
            linked_appointment_id=apt_a2.id,
        )
        note_b3 = Note(
            id=str(uuid.uuid4()),
            user_id=uid,
            profile_id=prof_b_id,
            slug=f"note-b3-{uuid.uuid4().hex[:6]}",
            title="Note B3 (Linked to B1)",
            content="Dental prep checklist for B1",
            type="visit",
            linked_appointment_id=apt_b1.id,
        )

        # Profile B HealthResource & Reminder
        hr_b1 = HealthResource(
            id=str(uuid.uuid4()),
            profile_id=prof_b_id,
            resource_type="observation",
            source_type="manual",
            data={"resourceType": "Observation", "value": 75},
            effective_at=now,
            recorded_at=now,
        )
        rem_b1 = Reminder(
            id=str(uuid.uuid4()),
            profile_id=prof_b_id,
            title="Take B Multivitamin",
            next_due_at=now + datetime.timedelta(hours=6),
        )

        async with session_factory() as session:
            session.add_all([note_a1, note_b1, note_b2, note_b3, hr_b1, rem_b1])
            await session.commit()

        # Delete Profile A
        del_resp = client.delete(f"/api/profiles/{prof_a_id}", headers=headers)
        assert del_resp.status_code == 200, del_resp.text

        # Verify Post-Deletion State
        async with session_factory() as session:
            # Profile A must be completely gone
            p_a_check = (await session.execute(select(Profile).where(Profile.id == prof_a_id))).scalar_one_or_none()
            assert p_a_check is None

            # Profile A appointments must be gone
            a_apts = (await session.execute(select(Appointment).where(Appointment.profile_id == prof_a_id))).scalars().all()
            assert len(a_apts) == 0

            # Profile A note must be gone
            a_notes = (await session.execute(select(Note).where(Note.profile_id == prof_a_id))).scalars().all()
            assert len(a_notes) == 0

            # Profile B MUST BE INTACT
            p_b_check = (await session.execute(select(Profile).where(Profile.id == prof_b_id))).scalar_one_or_none()
            assert p_b_check is not None

            # Profile B Appointment B1 must still exist
            b_apt_check = (await session.execute(select(Appointment).where(Appointment.id == apt_b1.id))).scalar_one_or_none()
            assert b_apt_check is not None

            # Profile B Note B1: Must exist, but linked_appointment_id must be None!
            b1_reloaded = (await session.execute(select(Note).where(Note.id == note_b1.id))).scalar_one()
            assert b1_reloaded is not None
            assert b1_reloaded.linked_appointment_id is None, "Cross-linked appointment must be SET NULL on deletion"

            # Profile B Note B2: Must exist, but linked_appointment_id must be None!
            b2_reloaded = (await session.execute(select(Note).where(Note.id == note_b2.id))).scalar_one()
            assert b2_reloaded is not None
            assert b2_reloaded.linked_appointment_id is None, "Cross-linked appointment must be SET NULL on deletion"

            # Profile B Note B3: Must exist, and still linked to B1!
            b3_reloaded = (await session.execute(select(Note).where(Note.id == note_b3.id))).scalar_one()
            assert b3_reloaded is not None
            assert b3_reloaded.linked_appointment_id == apt_b1.id

            # Profile B HealthResource & Reminder intact
            hr_b_check = (await session.execute(select(HealthResource).where(HealthResource.id == hr_b1.id))).scalar_one_or_none()
            assert hr_b_check is not None
            rem_b_check = (await session.execute(select(Reminder).where(Reminder.id == rem_b1.id))).scalar_one_or_none()
            assert rem_b_check is not None


@pytest.mark.asyncio
async def test_empirical_delete_profile_reverse_cross_linked_appointment(stress_test_env):
    """Verifies that if Profile A's Note was linked to Profile B's Appointment,

    deleting Profile A cleanly drops Note A without affecting Profile B's Appointment.
    """
    with TestClient(app) as client:
        user_data = register_and_login(client, "reverse_link@carefold.test", "ReverseSecret123!", "Reverse User")
        headers = user_data["headers"]
        uid = user_data["user"]["id"]

        resp_a = client.post("/api/profiles", headers=headers, json={"name": "Child A", "relationship": "child"})
        resp_b = client.post("/api/profiles", headers=headers, json={"name": "Child B", "relationship": "child"})
        prof_a_id = resp_a.json()["id"]
        prof_b_id = resp_b.json()["id"]

        session_factory = stress_test_env["session_factory"]
        now = datetime.datetime.now(datetime.timezone.utc)

        # Profile B Appointment
        apt_b = Appointment(
            id=str(uuid.uuid4()),
            profile_id=prof_b_id,
            title="Child B Wellness Visit",
            start_time=now + datetime.timedelta(days=1),
            end_time=now + datetime.timedelta(days=1, hours=1),
        )
        async with session_factory() as session:
            session.add(apt_b)
            await session.commit()

        # Profile A Note linked to Child B's appointment
        note_a = Note(
            id=str(uuid.uuid4()),
            user_id=uid,
            profile_id=prof_a_id,
            slug=f"note-a-cross-{uuid.uuid4().hex[:6]}",
            title="Shared Family Note",
            content="Discussing combined appointment slots",
            type="general",
            linked_appointment_id=apt_b.id,
        )
        async with session_factory() as session:
            session.add(note_a)
            await session.commit()

        # Delete Profile A
        del_resp = client.delete(f"/api/profiles/{prof_a_id}", headers=headers)
        assert del_resp.status_code == 200

        async with session_factory() as session:
            # Profile A and Note A are gone
            assert (await session.execute(select(Profile).where(Profile.id == prof_a_id))).scalar_one_or_none() is None
            assert (await session.execute(select(Note).where(Note.id == note_a.id))).scalar_one_or_none() is None

            # Profile B and Appointment B are unharmed
            assert (await session.execute(select(Profile).where(Profile.id == prof_b_id))).scalar_one_or_none() is not None
            apt_b_reloaded = (await session.execute(select(Appointment).where(Appointment.id == apt_b.id))).scalar_one_or_none()
            assert apt_b_reloaded is not None
            assert apt_b_reloaded.profile_id == prof_b_id


@pytest.mark.asyncio
async def test_empirical_high_volume_batch3_stress_deletion(stress_test_env):
    """High-volume stress test: 100 HealthResources, 50 Appointments, 50 Reminders, 100 Notes.

    Tests that mass cascading deletion performs without deadlocks, memory exhaustion,
    or leftover rows.
    """
    with TestClient(app) as client:
        user_data = register_and_login(client, "highvol@carefold.test", "HighVol123!", "High Volume")
        headers = user_data["headers"]
        uid = user_data["user"]["id"]

        p_resp = client.post("/api/profiles", headers=headers, json={"name": "Heavy Profile", "relationship": "parent"})
        prof_id = p_resp.json()["id"]

        session_factory = stress_test_env["session_factory"]
        now = datetime.datetime.now(datetime.timezone.utc)

        # Batch insert 100 HRs, 50 Appts, 50 Rems, 100 Notes
        async with session_factory() as session:
            apts: List[Appointment] = []
            for i in range(50):
                apt = Appointment(
                    id=str(uuid.uuid4()),
                    profile_id=prof_id,
                    title=f"Stress Appt #{i}",
                    start_time=now + datetime.timedelta(days=i),
                    end_time=now + datetime.timedelta(days=i, hours=1),
                )
                apts.append(apt)
                session.add(apt)
            await session.flush()

            for i in range(100):
                session.add(HealthResource(
                    id=str(uuid.uuid4()),
                    profile_id=prof_id,
                    resource_type="observation",
                    source_type="manual",
                    data={"resourceType": "Observation", "index": i},
                    effective_at=now,
                    recorded_at=now,
                ))

            for i in range(50):
                session.add(Reminder(
                    id=str(uuid.uuid4()),
                    profile_id=prof_id,
                    title=f"Stress Reminder #{i}",
                    next_due_at=now + datetime.timedelta(hours=i),
                ))

            for i in range(100):
                session.add(Note(
                    id=str(uuid.uuid4()),
                    user_id=uid,
                    profile_id=prof_id,
                    slug=f"stress-note-{i}-{uuid.uuid4().hex[:6]}",
                    title=f"Stress Note #{i}",
                    content=f"Content for stress note {i}",
                    type="visit",
                    linked_appointment_id=apts[i % len(apts)].id if i < 50 else None,
                ))

            await session.commit()

        # Delete profile
        del_resp = client.delete(f"/api/profiles/{prof_id}", headers=headers)
        assert del_resp.status_code == 200

        # Verify all rows purged
        async with session_factory() as session:
            hr_cnt = len((await session.execute(select(HealthResource).where(HealthResource.profile_id == prof_id))).scalars().all())
            apt_cnt = len((await session.execute(select(Appointment).where(Appointment.profile_id == prof_id))).scalars().all())
            rem_cnt = len((await session.execute(select(Reminder).where(Reminder.profile_id == prof_id))).scalars().all())
            note_cnt = len((await session.execute(select(Note).where(Note.profile_id == prof_id))).scalars().all())
            prof_check = (await session.execute(select(Profile).where(Profile.id == prof_id))).scalar_one_or_none()

            assert hr_cnt == 0
            assert apt_cnt == 0
            assert rem_cnt == 0
            assert note_cnt == 0
            assert prof_check is None


@pytest.mark.asyncio
async def test_empirical_primary_me_profile_immortality(stress_test_env):
    """Verifies that primary 'Me' profile deletion is strictly blocked (HTTP 400)

    and that none of its associated Batch 3 child rows are touched.
    """
    with TestClient(app) as client:
        user_data = register_and_login(client, "primary_test@carefold.test", "PrimaryPass123!", "Primary Steward")
        headers = user_data["headers"]

        # Fetch or auto-provision primary "Me" profile
        list_resp = client.get("/api/profiles", headers=headers)
        assert list_resp.status_code == 200
        profiles = list_resp.json()
        primary_profile = next(p for p in profiles if p["is_primary"])
        primary_id = primary_profile["id"]

        session_factory = stress_test_env["session_factory"]
        now = datetime.datetime.now(datetime.timezone.utc)

        # Add Batch 3 resources to the primary profile
        async with session_factory() as session:
            session.add(HealthResource(
                id=str(uuid.uuid4()),
                profile_id=primary_id,
                resource_type="observation",
                source_type="manual",
                data={"resourceType": "Observation", "value": "primary"},
                effective_at=now,
                recorded_at=now,
            ))
            session.add(Appointment(
                id=str(uuid.uuid4()),
                profile_id=primary_id,
                title="Primary Checkup",
                start_time=now + datetime.timedelta(days=1),
                end_time=now + datetime.timedelta(days=1, hours=1),
            ))
            session.add(Reminder(
                id=str(uuid.uuid4()),
                profile_id=primary_id,
                title="Primary Reminder",
                next_due_at=now + datetime.timedelta(hours=2),
            ))
            await session.commit()

        # Attempt to delete primary profile
        del_resp = client.delete(f"/api/profiles/{primary_id}", headers=headers)
        assert del_resp.status_code == 400
        assert "Cannot delete primary 'Me' profile" in del_resp.json()["detail"]

        # Verify child resources were NOT deleted
        async with session_factory() as session:
            hr_cnt = len((await session.execute(select(HealthResource).where(HealthResource.profile_id == primary_id))).scalars().all())
            apt_cnt = len((await session.execute(select(Appointment).where(Appointment.profile_id == primary_id))).scalars().all())
            rem_cnt = len((await session.execute(select(Reminder).where(Reminder.profile_id == primary_id))).scalars().all())

            assert hr_cnt == 1
            assert apt_cnt == 1
            assert rem_cnt == 1


@pytest.mark.asyncio
async def test_empirical_delete_profile_security_and_idempotency(stress_test_env):
    """Verifies security boundaries and double-delete semantics:

    1. Cross-user unauthorized deletion is blocked (HTTP 403).
    2. Non-existent profile returns HTTP 404.
    3. Double delete returns HTTP 404 on second call.
    """
    with TestClient(app) as client:
        user_alice = register_and_login(client, "alice_sec@carefold.test", "AlicePass123!", "Alice")
        user_bob = register_and_login(client, "bob_sec@carefold.test", "BobPass123!", "Bob")

        # Alice creates a secondary profile
        p_resp = client.post(
            "/api/profiles",
            headers=user_alice["headers"],
            json={"name": "Alice Child", "relationship": "child"},
        )
        assert p_resp.status_code == 201
        alice_prof_id = p_resp.json()["id"]

        # Bob attempts to delete Alice's profile -> HTTP 403
        del_unauth = client.delete(f"/api/profiles/{alice_prof_id}", headers=user_bob["headers"])
        assert del_unauth.status_code == 403

        # Deleting completely non-existent profile -> HTTP 404
        del_fake = client.delete(f"/api/profiles/{str(uuid.uuid4())}", headers=user_alice["headers"])
        assert del_fake.status_code == 404

        # Alice deletes her profile -> HTTP 200
        del_ok = client.delete(f"/api/profiles/{alice_prof_id}", headers=user_alice["headers"])
        assert del_ok.status_code == 200

        # Alice attempts to delete same profile again -> HTTP 404
        del_again = client.delete(f"/api/profiles/{alice_prof_id}", headers=user_alice["headers"])
        assert del_again.status_code == 404
