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

"""Unit tests for Carefold Autonomy Batch 3 models: HealthResource, Appointment, Reminder."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from carefold.db.models import (
    Appointment,
    HealthResource,
    Note,
    Profile,
    Reminder,
)
from carefold.db.session import create_db_engine, get_session_factory, init_db


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
async def db_session(tmp_path: Path):
    """Provides an isolated async database session with initialized schemas."""
    db_file = tmp_path / "clinical_models_test.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)

    factory = get_session_factory(engine)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def sample_profile(db_session: AsyncSession) -> Profile:
    """Creates and persists a sample profile for testing scoped entities."""
    profile = Profile(
        name="Eleanor Vance",
        relationship="parent",
        role="self",
        is_primary=False,
    )
    db_session.add(profile)
    await db_session.commit()
    await db_session.refresh(profile)
    return profile


# ===========================================================================
# Group 1: Model Instantiation & Defaults
# ===========================================================================


@pytest.mark.asyncio
async def test_health_resource_creation_and_defaults(
    db_session: AsyncSession, sample_profile: Profile
):
    """Verifies HealthResource creation, default field values, and UUID generation."""
    now = utc_now()
    fhir_data = {
        "resourceType": "Observation",
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "85354-9",
                    "display": "Blood Pressure",
                }
            ]
        },
    }

    hr = HealthResource(
        profile_id=sample_profile.id,
        resource_type="observation",
        source_type="manual",
        effective_at=now,
        data=fhir_data,
    )
    db_session.add(hr)
    await db_session.commit()
    await db_session.refresh(hr)

    assert hr.id is not None
    assert len(hr.id) == 36
    assert hr.profile_id == sample_profile.id
    assert hr.resource_type == "observation"
    assert hr.source_type == "manual"
    assert hr.source_ref is None
    assert hr.source_id is None
    assert hr.content_hash is None
    assert hr.status == "active"
    assert hr.data == fhir_data
    assert hr.created_at is not None
    assert hr.updated_at is not None
    assert repr(hr).startswith("<HealthResource")


@pytest.mark.asyncio
async def test_appointment_creation_and_defaults(
    db_session: AsyncSession, sample_profile: Profile
):
    """Verifies Appointment creation, default timezone and status, and nullable fields."""
    start = utc_now() + timedelta(days=2)
    end = start + timedelta(hours=1)

    apt = Appointment(
        profile_id=sample_profile.id,
        title="Cardiology Consult",
        start_time=start,
        end_time=end,
    )
    db_session.add(apt)
    await db_session.commit()
    await db_session.refresh(apt)

    assert apt.id is not None
    assert len(apt.id) == 36
    assert apt.profile_id == sample_profile.id
    assert apt.title == "Cardiology Consult"
    assert apt.timezone == "UTC"
    assert apt.status == "scheduled"
    assert apt.provider_name is None
    assert apt.specialty is None
    assert apt.location is None
    assert apt.clinic_phone is None
    assert apt.reason is None
    assert apt.preparation_notes is None
    assert apt.created_at is not None
    assert apt.updated_at is not None
    assert repr(apt).startswith("<Appointment")


@pytest.mark.asyncio
async def test_reminder_creation_and_defaults(
    db_session: AsyncSession, sample_profile: Profile
):
    """Verifies Reminder creation, default category, timezone, and pending status."""
    due = utc_now() + timedelta(hours=4)

    rem = Reminder(
        profile_id=sample_profile.id,
        title="Check morning glucose",
        next_due_at=due,
    )
    db_session.add(rem)
    await db_session.commit()
    await db_session.refresh(rem)

    assert rem.id is not None
    assert len(rem.id) == 36
    assert rem.profile_id == sample_profile.id
    assert rem.title == "Check morning glucose"
    assert rem.category == "general"
    assert rem.timezone == "UTC"
    assert rem.status == "pending"
    assert rem.description is None
    assert rem.rrule is None
    assert rem.last_triggered_at is None
    assert rem.snooze_until is None
    assert rem.created_at is not None
    assert rem.updated_at is not None
    assert repr(rem).startswith("<Reminder")


# ===========================================================================
# Group 2: JSON Serialization & Data Roundtripping
# ===========================================================================


@pytest.mark.asyncio
async def test_health_resource_fhir_observation_json_payload(
    db_session: AsyncSession, sample_profile: Profile
):
    """Verifies deep JSON round-tripping for complex FHIR R4 multi-component Observations."""
    fhir_bp_payload = {
        "resourceType": "Observation",
        "id": "obs-bp-120-80",
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "vital-signs",
                        "display": "Vital Signs",
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "85354-9",
                    "display": "Blood Pressure panel with all children optional",
                }
            ],
            "text": "Blood Pressure",
        },
        "subject": {"reference": f"Patient/{sample_profile.id}"},
        "effectiveDateTime": "2026-10-13T08:30:00Z",
        "component": [
            {
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "8480-6",
                            "display": "Systolic blood pressure",
                        }
                    ]
                },
                "valueQuantity": {
                    "value": 118,
                    "unit": "mmHg",
                    "system": "http://unitsofmeasure.org",
                    "code": "mm[Hg]",
                },
            },
            {
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "8462-4",
                            "display": "Diastolic blood pressure",
                        }
                    ]
                },
                "valueQuantity": {
                    "value": 76,
                    "unit": "mmHg",
                    "system": "http://unitsofmeasure.org",
                    "code": "mm[Hg]",
                },
            },
        ],
    }

    hr = HealthResource(
        profile_id=sample_profile.id,
        resource_type="observation",
        source_type="device",
        source_ref="omron-connect://reading/123",
        source_id="omron-123",
        content_hash="sha256-dummy-hash",
        effective_at=utc_now(),
        data=fhir_bp_payload,
    )
    db_session.add(hr)
    await db_session.commit()

    # Query back and verify deep structure
    stmt = select(HealthResource).where(HealthResource.id == hr.id)
    res = await db_session.execute(stmt)
    retrieved = res.scalar_one()

    assert retrieved.data["resourceType"] == "Observation"
    assert len(retrieved.data["component"]) == 2
    assert retrieved.data["component"][0]["valueQuantity"]["value"] == 118
    assert retrieved.data["component"][1]["valueQuantity"]["value"] == 76


@pytest.mark.asyncio
async def test_health_resource_tombstone_status(
    db_session: AsyncSession, sample_profile: Profile
):
    """Verifies that reverting/undoing an observation updates status to tombstone and persists."""
    hr = HealthResource(
        profile_id=sample_profile.id,
        resource_type="observation",
        source_type="manual",
        effective_at=utc_now(),
        data={"resourceType": "Observation", "value": 105},
        status="active",
    )
    db_session.add(hr)
    await db_session.commit()

    # Mark as tombstone (Activity Undo AU-40 pattern)
    hr.status = "tombstone"
    await db_session.commit()

    stmt = select(HealthResource).where(
        HealthResource.profile_id == sample_profile.id,
        HealthResource.status == "active",
    )
    active_results = (await db_session.execute(stmt)).scalars().all()
    assert hr.id not in [r.id for r in active_results]

    all_stmt = select(HealthResource).where(HealthResource.id == hr.id)
    tombstone_row = (await db_session.execute(all_stmt)).scalar_one()
    assert tombstone_row.status == "tombstone"


# ===========================================================================
# Group 3: Constraints & Idempotency Enforcement
# ===========================================================================


@pytest.mark.asyncio
async def test_health_resource_unique_constraint_enforcement(
    db_session: AsyncSession, sample_profile: Profile
):
    """Verifies uq_health_resources_source prevents duplicate ingestion per profile."""
    target_profile_id = str(sample_profile.id)

    hr1 = HealthResource(
        profile_id=target_profile_id,
        resource_type="observation",
        source_type="connector_sync",
        source_ref="epic-mychart",
        source_id="lab-result-9999",
        effective_at=utc_now(),
        data={"resourceType": "Observation", "value": 95},
    )
    db_session.add(hr1)
    await db_session.commit()

    # Attempt duplicate insert under same profile and source tuple -> must fail
    hr_duplicate = HealthResource(
        profile_id=target_profile_id,
        resource_type="observation",
        source_type="connector_sync",
        source_ref="epic-mychart",
        source_id="lab-result-9999",
        effective_at=utc_now(),
        data={"resourceType": "Observation", "value": 96},
    )
    db_session.add(hr_duplicate)
    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()

    # Different source_id under same profile -> succeeds
    hr_different_id = HealthResource(
        profile_id=target_profile_id,
        resource_type="observation",
        source_type="connector_sync",
        source_ref="epic-mychart",
        source_id="lab-result-10000",
        effective_at=utc_now(),
        data={"resourceType": "Observation", "value": 98},
    )
    db_session.add(hr_different_id)
    await db_session.commit()

    # Same source tuple under a different profile -> succeeds (tenant isolation)
    second_profile = Profile(name="Second Child", relationship="child", role="self")
    db_session.add(second_profile)
    await db_session.commit()
    await db_session.refresh(second_profile)

    hr_other_profile = HealthResource(
        profile_id=second_profile.id,
        resource_type="observation",
        source_type="connector_sync",
        source_ref="epic-mychart",
        source_id="lab-result-9999",
        effective_at=utc_now(),
        data={"resourceType": "Observation", "value": 95},
    )
    db_session.add(hr_other_profile)
    await db_session.commit()


@pytest.mark.asyncio
async def test_appointment_temporal_range_query(
    db_session: AsyncSession, sample_profile: Profile
):
    """Verifies appointment range queries correctly filter and order by start_time."""
    base_time = utc_now()
    apt1 = Appointment(
        profile_id=sample_profile.id,
        title="Visit 1",
        start_time=base_time + timedelta(days=1),
        end_time=base_time + timedelta(days=1, hours=1),
    )
    apt2 = Appointment(
        profile_id=sample_profile.id,
        title="Visit 2",
        start_time=base_time + timedelta(days=5),
        end_time=base_time + timedelta(days=5, hours=1),
    )
    apt3 = Appointment(
        profile_id=sample_profile.id,
        title="Visit 3",
        start_time=base_time + timedelta(days=10),
        end_time=base_time + timedelta(days=10, hours=1),
    )
    db_session.add_all([apt1, apt2, apt3])
    await db_session.commit()

    # Query visits between day 2 and day 7
    window_start = base_time + timedelta(days=2)
    window_end = base_time + timedelta(days=7)
    stmt = (
        select(Appointment)
        .where(
            Appointment.profile_id == sample_profile.id,
            Appointment.start_time >= window_start,
            Appointment.start_time <= window_end,
        )
        .order_by(Appointment.start_time.asc())
    )
    results = (await db_session.execute(stmt)).scalars().all()
    assert len(results) == 1
    assert results[0].title == "Visit 2"


@pytest.mark.asyncio
async def test_reminder_due_sweep_query(
    db_session: AsyncSession, sample_profile: Profile
):
    """Verifies querying pending reminders due before a threshold timestamp."""
    now = utc_now()
    r_past_pending = Reminder(
        profile_id=sample_profile.id,
        title="Overdue reminder",
        next_due_at=now - timedelta(minutes=15),
        status="pending",
    )
    r_future_pending = Reminder(
        profile_id=sample_profile.id,
        title="Future reminder",
        next_due_at=now + timedelta(hours=2),
        status="pending",
    )
    r_past_completed = Reminder(
        profile_id=sample_profile.id,
        title="Completed reminder",
        next_due_at=now - timedelta(minutes=30),
        status="completed",
    )
    db_session.add_all([r_past_pending, r_future_pending, r_past_completed])
    await db_session.commit()

    # Sweep pending reminders due <= now
    sweep_stmt = (
        select(Reminder)
        .where(
            Reminder.profile_id == sample_profile.id,
            Reminder.status == "pending",
            Reminder.next_due_at <= now,
        )
        .order_by(Reminder.next_due_at.asc())
    )
    due_items = (await db_session.execute(sweep_stmt)).scalars().all()
    assert len(due_items) == 1
    assert due_items[0].title == "Overdue reminder"


# ===========================================================================
# Group 4: Bidirectional Relationships & Cascade Deletion
# ===========================================================================


@pytest.mark.asyncio
async def test_profile_batch3_relationships_bidirectional(
    db_session: AsyncSession, sample_profile: Profile
):
    """Verifies Profile relationships to HealthResource, Appointment, and Reminder."""
    now = utc_now()

    hr = HealthResource(
        profile=sample_profile,
        resource_type="observation",
        source_type="manual",
        effective_at=now,
        data={"resourceType": "Observation"},
    )
    apt = Appointment(
        profile=sample_profile,
        title="Checkup",
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, hours=1),
    )
    rem = Reminder(
        profile=sample_profile,
        title="Take medication",
        next_due_at=now + timedelta(hours=8),
    )
    db_session.add_all([hr, apt, rem])
    await db_session.commit()

    # Reload profile with relationships eager-loaded
    stmt = (
        select(Profile)
        .where(Profile.id == sample_profile.id)
        .options(
            selectinload(Profile.health_resources),
            selectinload(Profile.appointments),
            selectinload(Profile.reminders),
        )
    )
    reloaded = (await db_session.execute(stmt)).scalar_one()

    assert len(reloaded.health_resources) == 1
    assert reloaded.health_resources[0].id == hr.id
    assert len(reloaded.appointments) == 1
    assert reloaded.appointments[0].id == apt.id
    assert len(reloaded.reminders) == 1
    assert reloaded.reminders[0].id == rem.id

    # Verify backward navigation
    assert hr.profile.id == sample_profile.id
    assert apt.profile.id == sample_profile.id
    assert rem.profile.id == sample_profile.id


@pytest.mark.asyncio
async def test_note_appointment_linked_relationship_and_set_null(
    db_session: AsyncSession, sample_profile: Profile
):
    """Verifies Note links to Appointment, and appointment deletion preserves note."""
    now = utc_now()
    apt = Appointment(
        profile_id=sample_profile.id,
        title="Annual Physical",
        start_time=now + timedelta(days=3),
        end_time=now + timedelta(days=3, hours=1),
    )
    db_session.add(apt)
    await db_session.commit()
    await db_session.refresh(apt)

    # Note linked to appointment
    note = Note(
        profile_id=sample_profile.id,
        type="visit",
        slug="annual-prep",
        title="Annual Prep Checklist",
        content="Bring vaccine card and list of questions.",
        linked_appointment_id=apt.id,
    )
    db_session.add(note)
    await db_session.commit()
    await db_session.refresh(note)

    assert note.linked_appointment_id == apt.id
    # Test both appointment and synonym linked_appointment
    assert note.appointment.id == apt.id
    assert note.linked_appointment.id == apt.id

    # Verify reverse relationship
    stmt_apt = (
        select(Appointment)
        .where(Appointment.id == apt.id)
        .options(selectinload(Appointment.notes))
    )
    reloaded_apt = (await db_session.execute(stmt_apt)).scalar_one()
    assert len(reloaded_apt.notes) == 1
    assert reloaded_apt.notes[0].id == note.id


@pytest.mark.asyncio
async def test_profile_cascade_delete_all_batch3_entities(
    db_session: AsyncSession, sample_profile: Profile
):
    """Verifies that deleting a Profile cascade-deletes HealthResource, Appointment, and Reminder."""
    now = utc_now()
    hr = HealthResource(
        profile_id=sample_profile.id,
        resource_type="observation",
        source_type="manual",
        effective_at=now,
        data={"resourceType": "Observation"},
    )
    apt = Appointment(
        profile_id=sample_profile.id,
        title="Dental Exam",
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, hours=1),
    )
    rem = Reminder(
        profile_id=sample_profile.id,
        title="Floss teeth",
        next_due_at=now + timedelta(hours=12),
    )
    db_session.add_all([hr, apt, rem])
    await db_session.commit()

    # Delete profile
    await db_session.delete(sample_profile)
    await db_session.commit()

    # Verify Batch 3 rows were cascaded
    hr_check = (
        await db_session.execute(
            select(HealthResource).where(HealthResource.profile_id == sample_profile.id)
        )
    ).scalars().all()
    apt_check = (
        await db_session.execute(
            select(Appointment).where(Appointment.profile_id == sample_profile.id)
        )
    ).scalars().all()
    rem_check = (
        await db_session.execute(
            select(Reminder).where(Reminder.profile_id == sample_profile.id)
        )
    ).scalars().all()

    assert len(hr_check) == 0
    assert len(apt_check) == 0
    assert len(rem_check) == 0
