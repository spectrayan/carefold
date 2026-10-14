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

"""Unit and integration tests for Gmail Read-Only MCP, Email Drafts, School ICS Feeds, and IIS PDF Imports (AU-59, AU-60, AU-61)."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from carefold.api.deps import get_current_user, get_db
from carefold.api.email_drafts import router as email_and_school_router
from carefold.auth.ports import UserProfile
from carefold.clinical.email_drafts import (
    NO_AUTO_SEND_NOTICE,
    build_mailto_uri,
    create_email_draft,
    execute_create_email_draft,
    export_draft_as_eml,
)
from carefold.clinical.school_ics import (
    create_school_ics_feed,
    sync_school_ics_feed,
)
from carefold.config import settings
from carefold.connectors.gmail_mcp import (
    ALLOWED_GMAIL_LABELS,
    confirm_gmail_staged_item,
    parse_gmail_messages_to_staged_items,
    stage_gmail_extractions,
)
from carefold.db.base import Base
from carefold.db.models import (
    Appointment,
    AuditEventRecord,
    EmailDraft,
    HealthResource,
    ImportBatch,
    Profile,
    Reminder,
    SchoolIcsFeed,
    User,
)
from carefold.engine.tool_exec import TaintFlag, ToolContext
from carefold.importers import (
    commit_import_batch,
    detect_import_format,
    parse_iis_immunisation_text,
    stage_import,
)

SAMPLE_GMAIL_MESSAGES = [
    {
        "id": "gmail-msg-101",
        "labels": ["appointments", "INBOX"],
        "from": "Pediatric Cardiology <scheduling@citygeneral.org>",
        "subject": "Appointment Confirmation: Pediatric Cardiology Visit",
        "snippet": "Confirmed visit with Dr. Anita Rao on 2026-10-22 at 10:30 AM.",
        "body": (
            "Hello,\nYour child's appointment with Dr. Anita Rao at City General Cardiology "
            "is confirmed for 2026-10-22 at 10:30 AM.\nLocation: Building B, Suite 400."
        ),
        "location": "Building B, Suite 400",
    },
    {
        "id": "gmail-msg-102",
        "labels": ["school-summaries"],
        "from": "Oakridge Elementary Nurse <nurse@oakridgeschool.edu>",
        "subject": "Annual School Physical & Immunization Form Reminder",
        "snippet": "Guardian summary: Please submit updated immunization form by 11/05/2026.",
        "body": "Dear Guardian, please return the completed school health form by 11/05/2026.",
    },
    {
        "id": "gmail-msg-103",
        "labels": ["promotions"],
        "from": "Newsletter <news@example.com>",
        "subject": "Weekly Store Coupons",
        "snippet": "Save 20% this weekend.",
    },
]

SAMPLE_SCHOOL_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Oakridge Elementary//School Calendar//EN
BEGIN:VEVENT
UID:oakridge-nurse-screening-2026@oakridgeschool.edu
DTSTART:20261028T133000Z
DTEND:20261028T143000Z
SUMMARY:Fall Vision & Hearing Screening
LOCATION:School Health Office
DESCRIPTION:Annual elementary vision and hearing screening day.
END:VEVENT
BEGIN:VEVENT
UID:oakridge-early-dismissal-2026@oakridgeschool.edu
DTSTART;VALUE=DATE:20261104
SUMMARY:Parent-Teacher Conferences Early Dismissal
LOCATION:Oakridge Elementary Campus
DESCRIPTION:Half-day schedule for parent-teacher conferences.
END:VEVENT
END:VCALENDAR
"""

SAMPLE_IIS_CERTIFICATE_TEXT = """
STATE IMMUNIZATION INFORMATION SYSTEM (IIS) OFFICIAL CERTIFICATE
Patient Name: Leo Patel
DOB: 2018-05-14

Vaccine                  Administration Date     Lot / Notes
-----------------------------------------------------------------
DTaP                     2018-07-15              Lot A102
DTaP                     11/18/2018              Lot B204
MMR                      2019-05-20              Dose 1
IPV                      05/20/2019              Dose 3
HepB                     2018-05-15              Birth Dose
Varicella                2019-05-20              Dose 1
PCV13                    2018-09-16              Dose 2
Influenza                10/01/2025              Seasonal Injectable
COVID-19                 2025-10-15              Pediatric Booster
"""


@pytest.fixture
async def batch6_stream2_env(tmp_path, monkeypatch):
    """Creates an isolated in-memory SQLite DB and CAS directory for Stream 2 tests."""
    monkeypatch.setattr(settings, "home_dir", tmp_path)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    user_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    async with factory() as session:
        user = User(
            id=user_id,
            email="steward@example.com",
            username="family_steward",
            hashed_password="hashed_password",
            role="steward",
        )
        profile = Profile(
            id=profile_id,
            user_id=user_id,
            name="Leo Patel",
            relationship="child",
            role="guardian",
            date_of_birth="2018-05-14",
            is_primary=False,
        )
        session.add_all([user, profile])
        await session.commit()

    yield {
        "engine": engine,
        "factory": factory,
        "user_id": user_id,
        "profile_id": profile_id,
    }
    await engine.dispose()


def test_parse_gmail_messages_filters_by_label_and_marks_untrusted():
    """Verifies Gmail MCP parser enforces ALLOWED_GMAIL_LABELS and extracts staged candidates."""
    assert "appointments" in ALLOWED_GMAIL_LABELS
    assert "school-summaries" in ALLOWED_GMAIL_LABELS

    with pytest.raises(ValueError, match="Unsupported Gmail label filter"):
        parse_gmail_messages_to_staged_items(SAMPLE_GMAIL_MESSAGES, label_filter="spam")

    appt_parsed = parse_gmail_messages_to_staged_items(
        SAMPLE_GMAIL_MESSAGES,
        label_filter="appointments",
    )
    assert appt_parsed["format"] == "gmail_mcp"
    assert len(appt_parsed["records"]) == 1
    appt_item = appt_parsed["records"][0]
    assert appt_item["record_type"] == "appointment_candidate"
    assert appt_item["trust"] == "untrusted"
    assert appt_item["source_display"] == "From Gmail (gmail-msg-101), 2026-10-22"
    assert "Dr. Anita Rao" in appt_item["provider_name"]
    assert appt_item["specialty"] == "Cardiology"

    school_parsed = parse_gmail_messages_to_staged_items(
        SAMPLE_GMAIL_MESSAGES,
        label_filter="school-summaries",
    )
    assert len(school_parsed["records"]) == 1
    school_item = school_parsed["records"][0]
    assert school_item["record_type"] == "school_todo_candidate"
    assert school_item["trust"] == "untrusted"
    assert school_item["source_display"] == "From Gmail (gmail-msg-102), 2026-11-05"
    assert school_item["category"] == "prep"


@pytest.mark.asyncio
async def test_stage_and_confirm_gmail_extractions_workflow(batch6_stream2_env):
    """Verifies E9.2 & E11.4: Gmail candidates are staged first and materialized only upon confirmation."""
    factory = batch6_stream2_env["factory"]
    profile_id = batch6_stream2_env["profile_id"]
    user_id = batch6_stream2_env["user_id"]

    async with factory() as session:
        # 1. Stage appointment message -> zero Appointments exist before confirmation
        batch_appt = await stage_gmail_extractions(
            session=session,
            profile_id=profile_id,
            messages=SAMPLE_GMAIL_MESSAGES,
            label_filter="appointments",
        )
        assert batch_appt.status == "staged"
        assert batch_appt.format == "gmail_mcp"

        appts_before = (
            await session.execute(select(Appointment).where(Appointment.profile_id == profile_id))
        ).scalars().all()
        assert len(appts_before) == 0

        # 2. Confirm item 0 -> creates confirmed Appointment and AuditEventRecord
        confirm_res = await confirm_gmail_staged_item(
            session=session,
            profile_id=profile_id,
            batch_id=batch_appt.id,
            item_index=0,
            actor_user_id=user_id,
        )
        assert confirm_res["confirmed"] is True
        assert confirm_res["entity_type"] == "appointment"

        appts_after = (
            await session.execute(select(Appointment).where(Appointment.profile_id == profile_id))
        ).scalars().all()
        assert len(appts_after) == 1
        assert appts_after[0].status == "confirmed"
        assert appts_after[0].specialty == "Cardiology"

        # 3. Stage and confirm school summary message -> creates Reminder(category='prep')
        batch_school = await stage_gmail_extractions(
            session=session,
            profile_id=profile_id,
            messages=SAMPLE_GMAIL_MESSAGES,
            label_filter="school-summaries",
        )
        confirm_school = await confirm_gmail_staged_item(
            session=session,
            profile_id=profile_id,
            batch_id=batch_school.id,
            item_index=0,
            actor_user_id=user_id,
        )
        assert confirm_school["entity_type"] == "reminder"

        reminders = (
            await session.execute(select(Reminder).where(Reminder.profile_id == profile_id))
        ).scalars().all()
        assert len(reminders) == 1
        assert reminders[0].category == "prep"

        audits = (
            await session.execute(
                select(AuditEventRecord).where(
                    AuditEventRecord.profile_id == profile_id,
                    AuditEventRecord.tool == "confirm_gmail_staged_item",
                )
            )
        ).scalars().all()
        assert len(audits) == 2


@pytest.mark.asyncio
async def test_email_drafts_no_send_mailto_eml_and_tool_handler(batch6_stream2_env):
    """Verifies AU-60 / E9.3: local email draft creation, RFC 6068 mailto:, RFC 5322 .eml, and tool fail-closed check."""
    factory = batch6_stream2_env["factory"]
    profile_id = batch6_stream2_env["profile_id"]
    user_id = batch6_stream2_env["user_id"]

    async with factory() as session:
        draft = await create_email_draft(
            session=session,
            profile_id=profile_id,
            subject="Records Request for Leo Patel",
            body="Hello Records Department,\nPlease provide a copy of the 2026 visit summary.",
            recipient="records@citygeneral.org",
            category="appointment",
            created_by_user_id=user_id,
        )
        assert draft.status == "draft"
        assert draft.category == "appointment"

        mailto = build_mailto_uri(draft)
        assert mailto.startswith("mailto:records@citygeneral.org?subject=")
        assert "Records%20Request%20for%20Leo%20Patel" in mailto
        assert "&body=" in mailto

        eml = export_draft_as_eml(draft)
        assert "X-Unsent: 1" in eml
        assert "To: records@citygeneral.org" in eml
        assert "Subject: Records Request for Leo Patel" in eml
        assert 'Content-Type: text/plain; charset="utf-8"' in eml
        assert "Carefold never sends emails automatically in v1" in eml

        audits = (
            await session.execute(
                select(AuditEventRecord).where(
                    AuditEventRecord.profile_id == profile_id,
                    AuditEventRecord.tool == "create_email_draft",
                )
            )
        ).scalars().all()
        assert len(audits) == 1
        assert audits[0].external_ref == f"email_draft:{draft.id}"
        assert audits[0].risk == "write_local"

    # Fail-closed when ToolContext or profile_id is missing
    with pytest.raises(ValueError, match="profile_id"):
        await execute_create_email_draft({"subject": "Test", "body": "Body"}, ctx=None)

    ctx = ToolContext(
        user_id=user_id,
        profile_id=profile_id,
        taint=TaintFlag(False),
        extra={"session_factory": factory},
    )
    tool_res = await execute_create_email_draft(
        {
            "recipient": "nurse@oakridgeschool.edu",
            "subject": "Updated Immunization Certificate",
            "body": "Attached is Leo's updated immunization certificate.",
            "category": "school",
        },
        ctx=ctx,
    )
    assert tool_res["auto_send"] is False
    assert tool_res["notice"] == NO_AUTO_SEND_NOTICE
    assert tool_res["mailto_uri"].startswith("mailto:nurse@oakridgeschool.edu?")


@pytest.mark.asyncio
async def test_school_ics_feed_validation_and_vevent_sync(batch6_stream2_env):
    """Verifies AU-61 / E4.4: webcal:// normalization, SSRF/file:// rejection, and VEVENT Appointment upsert."""
    factory = batch6_stream2_env["factory"]
    profile_id = batch6_stream2_env["profile_id"]
    user_id = batch6_stream2_env["user_id"]

    async with factory() as session:
        # Reject file:// and private/loopback IP URLs
        with pytest.raises(ValueError, match="file://"):
            await create_school_ics_feed(
                session=session,
                profile_id=profile_id,
                label="Bad File Feed",
                feed_url="file:///etc/passwd",
            )

        with pytest.raises(ValueError, match="private or loopback"):
            await create_school_ics_feed(
                session=session,
                profile_id=profile_id,
                label="Loopback Feed",
                feed_url="https://127.0.0.1/calendar.ics",
            )

        # Normalize webcal:// to https://
        feed = await create_school_ics_feed(
            session=session,
            profile_id=profile_id,
            label="Oakridge Elementary Calendar",
            feed_url="webcal://calendar.oakridgeschool.edu/elementary.ics",
            actor_user_id=user_id,
        )
        assert feed.feed_url == "https://calendar.oakridgeschool.edu/elementary.ics"
        assert feed.status == "active"

        # First sync creates 2 school calendar Appointments
        sync_res1 = await sync_school_ics_feed(
            session=session,
            profile_id=profile_id,
            feed_id=feed.id,
            raw_ics_content=SAMPLE_SCHOOL_ICS,
        )
        assert sync_res1["events_synced"] == 2
        assert sync_res1["created_count"] == 2
        assert sync_res1["updated_count"] == 0

        # Second sync with same ICS updates existing Appointments idempotently
        sync_res2 = await sync_school_ics_feed(
            session=session,
            profile_id=profile_id,
            feed_id=feed.id,
            raw_ics_content=SAMPLE_SCHOOL_ICS,
        )
        assert sync_res2["events_synced"] == 2
        assert sync_res2["created_count"] == 0
        assert sync_res2["updated_count"] == 2

        school_appts = (
            await session.execute(
                select(Appointment).where(
                    Appointment.profile_id == profile_id,
                    Appointment.specialty == "School Calendar",
                )
            )
        ).scalars().all()
        assert len(school_appts) == 2
        titles = {a.title for a in school_appts}
        assert "Fall Vision & Hearing Screening" in titles
        assert "Parent-Teacher Conferences Early Dismissal" in titles


@pytest.mark.asyncio
async def test_iis_immunisation_pdf_parser_and_stage_commit_integration(batch6_stream2_env):
    """Verifies AU-61 / E11.3: IIS immunisation certificate parsing, FHIR Immunization validation, and AU-38 staging."""
    parsed = parse_iis_immunisation_text(
        SAMPLE_IIS_CERTIFICATE_TEXT,
        source_name="California CAIR2 Registry PDF",
    )
    assert parsed["format"] == "iis_pdf"
    records = parsed["records"]
    assert len(records) == 9

    vaccines = [r["vaccine_name"] for r in records]
    assert vaccines.count("DTaP") == 2
    assert "MMR" in vaccines
    assert "IPV" in vaccines
    assert "HepB" in vaccines
    assert "Varicella" in vaccines
    assert "PCV13" in vaccines
    assert "Influenza" in vaccines
    assert "COVID-19" in vaccines

    for rec in records:
        assert rec["resource_type"] == "Immunization"
        assert rec["trust"] == "untrusted"
        assert rec["source_display"].startswith("From California CAIR2 Registry PDF, ")
        assert rec["data"]["resourceType"] == "Immunization"
        assert rec["data"]["status"] == "completed"

    assert detect_import_format("cair2_certificate.pdf", SAMPLE_IIS_CERTIFICATE_TEXT) == "iis_pdf"

    factory = batch6_stream2_env["factory"]
    profile_id = batch6_stream2_env["profile_id"]
    user_id = batch6_stream2_env["user_id"]

    async with factory() as session:
        batch = await stage_import(
            session=session,
            profile_id=profile_id,
            filename="cair2_certificate.pdf",
            content=SAMPLE_IIS_CERTIFICATE_TEXT,
            source_name="California CAIR2 Registry PDF",
            fmt="iis_pdf",
            user_id=user_id,
        )
        assert batch.status == "staged"
        assert batch.format == "iis_pdf"

        commit_res = await commit_import_batch(
            session=session,
            profile_id=profile_id,
            batch_id=batch.id,
            actor_user_id=user_id,
        )
        assert commit_res["status"] == "committed"
        assert commit_res["committed_count"] == 9

        imm_rows = (
            await session.execute(
                select(HealthResource).where(
                    HealthResource.profile_id == profile_id,
                    HealthResource.resource_type == "Immunization",
                )
            )
        ).scalars().all()
        assert len(imm_rows) == 9


@pytest.mark.asyncio
async def test_email_drafts_gmail_and_school_ics_rest_endpoints(batch6_stream2_env):
    """Verifies all REST endpoints in carefold.api.email_drafts."""
    factory = batch6_stream2_env["factory"]
    profile_id = batch6_stream2_env["profile_id"]
    user_id = batch6_stream2_env["user_id"]

    app = FastAPI()
    app.include_router(email_and_school_router)

    async def _override_get_db():
        async with factory() as session:
            yield session

    async def _override_user():
        now = datetime.now(timezone.utc)
        return UserProfile(
            id=user_id,
            email="steward@example.com",
            username="family_steward",
            role="steward",
            status="active",
            created_at=now,
            updated_at=now,
        )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. POST & GET & EML & DELETE /email-drafts
        create_draft_resp = await client.post(
            f"/profiles/{profile_id}/email-drafts",
            json={
                "recipient": "billing@citygeneral.org",
                "subject": "Itemized Bill Request",
                "body": "Please send an itemized statement for date of service 2026-10-01.",
                "category": "insurance",
            },
        )
        assert create_draft_resp.status_code == 201
        draft_json = create_draft_resp.json()
        draft_id = draft_json["id"]
        assert draft_json["auto_send"] is False

        list_drafts_resp = await client.get(f"/profiles/{profile_id}/email-drafts")
        assert list_drafts_resp.status_code == 200
        assert list_drafts_resp.json()["total"] >= 1

        eml_resp = await client.get(f"/profiles/{profile_id}/email-drafts/{draft_id}/eml")
        assert eml_resp.status_code == 200
        assert "X-Unsent: 1" in eml_resp.json()["eml"]

        del_draft_resp = await client.delete(f"/profiles/{profile_id}/email-drafts/{draft_id}")
        assert del_draft_resp.status_code == 200
        assert del_draft_resp.json()["deleted"] is True

        # 2. POST /gmail/stage & POST /gmail/batches/{batch_id}/confirm/{item_index}
        stage_gmail_resp = await client.post(
            f"/profiles/{profile_id}/gmail/stage",
            json={
                "messages": SAMPLE_GMAIL_MESSAGES,
                "label_filter": "appointments",
            },
        )
        assert stage_gmail_resp.status_code == 201
        g_batch = stage_gmail_resp.json()
        g_batch_id = g_batch["id"]
        assert len(g_batch["staged_records"]) == 1

        confirm_gmail_resp = await client.post(
            f"/profiles/{profile_id}/gmail/batches/{g_batch_id}/confirm/0"
        )
        assert confirm_gmail_resp.status_code == 200
        assert confirm_gmail_resp.json()["confirmed"] is True

        # 3. POST, GET, SYNC, DELETE /school-ics
        create_ics_resp = await client.post(
            f"/profiles/{profile_id}/school-ics",
            json={
                "label": "Oakridge District Calendar",
                "feed_url": "webcal://district.oakridgeschool.edu/calendar.ics",
            },
        )
        assert create_ics_resp.status_code == 201
        feed_id = create_ics_resp.json()["id"]

        list_ics_resp = await client.get(f"/profiles/{profile_id}/school-ics")
        assert list_ics_resp.status_code == 200
        assert list_ics_resp.json()["total"] >= 1

        sync_ics_resp = await client.post(
            f"/profiles/{profile_id}/school-ics/{feed_id}/sync",
            json={"raw_ics_content": SAMPLE_SCHOOL_ICS},
        )
        assert sync_ics_resp.status_code == 200
        assert sync_ics_resp.json()["events_synced"] == 2

        del_ics_resp = await client.delete(f"/profiles/{profile_id}/school-ics/{feed_id}")
        assert del_ics_resp.status_code == 200
        assert del_ics_resp.json()["deleted"] is True
