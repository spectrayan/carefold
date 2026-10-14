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

"""Unit and integration tests for Carefold Batch 7 v2 connectors, SMART scheduling, Zocdoc booking, and Gmail approved send (AU-71, AU-72, AU-73, AU-74, AU-76)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

from fastapi import FastAPI
from fhir.resources.R4B.condition import Condition as FhirCondition
from fhir.resources.R4B.coverage import Coverage as FhirCoverage
from fhir.resources.R4B.explanationofbenefit import (
    ExplanationOfBenefit as FhirExplanationOfBenefit,
)
from fhir.resources.R4B.observation import Observation as FhirObservation
import httpx
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from carefold.api.coordinated import router as coordinated_router
from carefold.api.deps import get_current_user, get_db
from carefold.audit.hash_chain import append_chained_audit_event
from carefold.auth.ports import UserProfile
from carefold.clinical.email_drafts import create_email_draft
from carefold.clinical.smart_scheduling import discover_smart_scheduling_slots
from carefold.config import settings
from carefold.connectors.gmail_mcp import (
    execute_gmail_send_message,
    prepare_gmail_send_approval_payload,
)
from carefold.db.base import Base
from carefold.db.models import (
    Appointment,
    Approval,
    AuditEventRecord,
    EmailDraft,
    Profile,
    User,
    utc_now,
)
from carefold.engine.tool_exec import (
    TaintFlag,
    ToolContext as EngineToolContext,
    ToolSpec as EngineToolSpec,
    evaluate_policy_gate,
)
from connectors.base import Connector, ToolContext as ConnectorToolContext
from connectors.http import ScopedHttp
from connectors.manifest import ConnectorManifest
from connectors.starters.ehr_smart_v2 import (
    AthenahealthConnector,
    CmsBlueButtonConnector,
    OracleHealthConnector,
)
from connectors.starters.wearables_v2 import (
    GoogleHealthConnector,
    MicrosoftGraphCalendarConnector,
    OuraConnector,
)
from connectors.starters.zocdoc import (
    ZocdocConnector,
    prepare_zocdoc_booking_payload,
)


@pytest.fixture
async def batch7_stream2_env(tmp_path, monkeypatch):
    """Creates an isolated in-memory SQLite database for Batch 7 Stream 2 tests."""
    monkeypatch.setattr(settings, "home_dir", tmp_path)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    user_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    now = utc_now()
    async with factory() as session:
        user = User(
            id=user_id,
            email="steward-v2@example.com",
            username="steward_v2",
            hashed_password="hashed_password",
            role="steward",
        )
        profile = Profile(
            id=profile_id,
            user_id=user_id,
            name="Maya Patel",
            relationship="self",
            role="owner",
            date_of_birth="1986-04-12",
            is_primary=True,
        )
        appt = Appointment(
            id=str(uuid.uuid4()),
            profile_id=profile_id,
            title="Existing Dental Checkup",
            provider_name="Dr. Lee",
            specialty="Dentistry",
            start_time=datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 10, 25, 11, 0, tzinfo=timezone.utc),
            status="confirmed",
            created_at=now,
            updated_at=now,
        )
        session.add_all([user, profile, appt])
        await session.commit()

    yield {
        "engine": engine,
        "factory": factory,
        "user_id": user_id,
        "profile_id": profile_id,
    }
    await engine.dispose()


@pytest.mark.asyncio
async def test_zocdoc_connector_and_irreversible_policy_gate_under_a2():
    """Verifies ZocdocConnector, prepare_zocdoc_booking_payload, and A2 policy gate approval enforcement (AU-71)."""
    connector = ZocdocConnector()
    assert isinstance(connector, Connector)
    assert connector.manifest.id == "zocdoc"
    assert connector.manifest.auth.pkce is True
    assert connector.manifest.trust.trust_level == "untrusted"
    assert connector.manifest.data_flows.allowed_hosts == ["api.zocdoc.com"]

    preview = prepare_zocdoc_booking_payload(
        profile_id="prof-zocdoc-1",
        provider_id="prov-cardio-99",
        provider_name="Dr. Elena Vance",
        specialty="Cardiology",
        slot_id="slot-20261025-1400",
        start_time="2026-10-25T14:00:00Z",
        insurance_carrier="Aetna PPO",
    )
    assert preview["risk_tier"] == "irreversible"
    assert preview["requires_approval"] is True
    assert preview["tool_name"] == "zocdoc_book_appointment"
    assert len(preview["payload_hash"]) == 64

    tools_by_name = {t.name: t for t in connector.tools()}
    assert set(tools_by_name.keys()) == {"zocdoc_search_providers", "zocdoc_book_appointment"}

    search_tool = tools_by_name["zocdoc_search_providers"]
    book_tool = tools_by_name["zocdoc_book_appointment"]
    assert search_tool.risk_tier == "read"
    assert search_tool.trust == "untrusted"
    assert book_tool.risk_tier == "irreversible"
    assert book_tool.trust == "untrusted"

    # Prove policy gate requires explicit human approval for zocdoc_book_appointment even under A2 autonomy with full consent
    engine_ctx = EngineToolContext(
        user_id="user-zocdoc-1",
        profile_id="prof-zocdoc-1",
        autonomy="A2",
        taint=TaintFlag(initial=False),
    )
    engine_book_spec = EngineToolSpec(
        name=book_tool.name,
        description=book_tool.description,
        parameters=book_tool.parameters,
        risk_tier="irreversible",
        trust="untrusted",
        data_flows=book_tool.data_flows,
    )
    gate_decision = evaluate_policy_gate(
        ctx=engine_ctx,
        spec=engine_book_spec,
        args=preview["args"],
        consents={"external_write_consent": True, "guardian_consent": True},
        age_band="adult",
    )
    assert gate_decision.decision == "needs_approval"

    # Test fetch, map, search, and book handler
    conn_ctx = ConnectorToolContext(user_id="user-zocdoc-1", profile_id="prof-zocdoc-1")
    zocdoc_payload = {
        "providers": [
            {
                "id": "prov-cardio-99",
                "name": "Dr. Elena Vance",
                "specialty": "Cardiology",
                "location": "200 Heart Way, Suite 300",
                "in_network_carriers": ["Aetna PPO", "BlueCross"],
                "slots": [{"slot_id": "slot-20261025-1400", "start_time": "2026-10-25T14:00:00Z"}],
            }
        ]
    }
    mock_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=zocdoc_payload))
    )
    http = ScopedHttp.from_data_flow(connector.manifest.data_flows, client=mock_client)

    page = await connector.fetch(conn_ctx, stream="providers", cursor=None, http=http)
    mapped = connector.map(page)
    assert len(mapped) == 1
    assert mapped[0].data["trust"] == "untrusted"
    assert mapped[0].data["source_display"].startswith("From Zocdoc, ")

    search_res = await search_tool.handler(conn_ctx, {"specialty": "cardiology", "insurance_carrier": "aetna"})
    assert search_res["count"] == 1

    book_res = await book_tool.handler(
        conn_ctx,
        {
            "provider_id": "prov-cardio-99",
            "provider_name": "Dr. Elena Vance",
            "specialty": "Cardiology",
            "slot_id": "slot-20261025-1400",
            "start_time": "2026-10-25T14:00:00Z",
            "booking_id": "bk901",
        },
    )
    assert book_res["status"] == "confirmed"
    assert book_res["external_ref"] == "zocdoc_booking:bk901"
    assert book_res["risk_tier"] == "irreversible"


def test_discover_smart_scheduling_slots_filters_free_and_marks_calendar_conflicts():
    """Verifies HL7 SMART Scheduling Links discovery filters free FHIR Slots and marks busy calendar conflicts (AU-72)."""
    manifest_payload = {
        "schedules": [
            {
                "resourceType": "Schedule",
                "id": "sched-cardio-1",
                "actor": [{"display": "Dr. Marcus Sterling", "reference": "Location/loc-main"}],
                "specialty": [{"text": "Cardiology"}],
            },
            {
                "resourceType": "Schedule",
                "id": "sched-derm-1",
                "actor": [{"display": "Dr. Priya Nair"}],
                "specialty": [{"text": "Dermatology"}],
            },
        ],
        "locations": [
            {"id": "loc-main", "name": "Metro Heart Institute"},
        ],
        "slots": [
            {
                "resourceType": "Slot",
                "id": "slot-free-conflict",
                "schedule": {"reference": "Schedule/sched-cardio-1"},
                "status": "free",
                "start": "2026-10-25T10:15:00Z",
                "end": "2026-10-25T10:45:00Z",
                "booking_url": "https://scheduling.metroheart.org/book/slot-free-conflict",
            },
            {
                "resourceType": "Slot",
                "id": "slot-free-open",
                "schedule": {"reference": "Schedule/sched-cardio-1"},
                "status": "free",
                "start": "2026-10-25T14:00:00Z",
                "end": "2026-10-25T14:30:00Z",
                "extension": [
                    {
                        "url": "http://fhir-registry.smarthealthit.org/StructureDefinition/booking-deep-link",
                        "valueUrl": "https://scheduling.metroheart.org/book/slot-free-open",
                    }
                ],
            },
            {
                "resourceType": "Slot",
                "id": "slot-busy-1",
                "schedule": {"reference": "Schedule/sched-cardio-1"},
                "status": "busy",
                "start": "2026-10-25T15:00:00Z",
                "end": "2026-10-25T15:30:00Z",
            },
            {
                "resourceType": "Slot",
                "id": "slot-derm-free",
                "schedule": {"reference": "Schedule/sched-derm-1"},
                "status": "free",
                "start": "2026-10-25T16:00:00Z",
                "end": "2026-10-25T16:30:00Z",
            },
        ],
    }

    busy_windows = [
        {"start": "2026-10-25T10:00:00Z", "end": "2026-10-25T11:00:00Z"},
    ]

    cardio_slots = discover_smart_scheduling_slots(
        manifest_payload=manifest_payload,
        specialty_filter="Cardiology",
        busy_windows=busy_windows,
    )
    assert len(cardio_slots) == 2
    by_id = {s["slot_id"]: s for s in cardio_slots}
    assert "slot-busy-1" not in by_id
    assert "slot-derm-free" not in by_id

    assert by_id["slot-free-conflict"]["fits_calendar"] is False
    assert by_id["slot-free-conflict"]["provider_name"] == "Dr. Marcus Sterling"
    assert by_id["slot-free-conflict"]["location"] == "Metro Heart Institute"
    assert by_id["slot-free-conflict"]["source"] == "smart_scheduling_links"

    assert by_id["slot-free-open"]["fits_calendar"] is True
    assert by_id["slot-free-open"]["booking_url"] == "https://scheduling.metroheart.org/book/slot-free-open"


@pytest.mark.asyncio
async def test_oracle_health_athenahealth_and_cms_blue_button_connectors():
    """Verifies OracleHealthConnector, AthenahealthConnector, and CmsBlueButtonConnector FHIR R4B validation and untrusted provenance (AU-73)."""
    oracle = OracleHealthConnector()
    athena = AthenahealthConnector()
    cms = CmsBlueButtonConnector()

    assert oracle.manifest.id == "oracle-health"
    assert oracle.manifest.trust.trust_level == "untrusted"
    assert athena.manifest.id == "athenahealth"
    assert athena.manifest.trust.trust_level == "untrusted"
    assert cms.manifest.id == "cms-blue-button"
    assert cms.manifest.trust.trust_level == "untrusted"

    ctx = ConnectorToolContext(user_id="user-ehr-1", profile_id="prof-ehr-1")

    condition_bundle = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-101",
                    "recordedDate": "2026-10-02",
                    "code": {"text": "Type 2 diabetes mellitus"},
                    "subject": {"reference": "Patient/pat-1"},
                }
            }
        ],
    }

    for conn, expected_prefix in (
        (oracle, "From Oracle Health, 2026-10-02"),
        (athena, "From athenahealth, 2026-10-02"),
    ):
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json=condition_bundle))
        )
        http = ScopedHttp.from_data_flow(conn.manifest.data_flows, client=client)
        page = await conn.fetch(ctx, stream="Condition", cursor=None, http=http)
        mapped = conn.map(page)
        assert len(mapped) == 1
        rec = mapped[0]
        assert rec.data["trust"] == "untrusted"
        assert rec.data["source_display"] == expected_prefix
        validated_cond = FhirCondition.model_validate(rec.data["fhir_resource"])
        assert validated_cond.id == "cond-101"

        tool_res = await conn.tools()[0].handler(ctx, {"query": "diabetes"})
        assert tool_res["count"] == 1
        assert tool_res["trust"] == "untrusted"

    # Test CMS Blue Button 2.0 ExplanationOfBenefit & Coverage
    cms_bundles = {
        "ExplanationOfBenefit": {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "ExplanationOfBenefit",
                        "id": "eob-medicare-501",
                        "status": "active",
                        "created": "2026-10-10",
                        "billablePeriod": {"start": "2026-10-05", "end": "2026-10-05"},
                        "provider": {"display": "Bay Area Cardiology Associates"},
                        "total": [
                            {
                                "category": {"text": "Submitted Amount"},
                                "amount": {"value": 245.50, "currency": "USD"},
                            }
                        ],
                    }
                }
            ],
        },
        "Coverage": {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Coverage",
                        "id": "cov-part-b-1",
                        "status": "active",
                        "subscriberId": "MBI-998877",
                        "period": {"start": "2026-01-01"},
                        "beneficiary": {"reference": "Patient/pat-1"},
                        "payor": [{"display": "CMS Medicare Part B"}],
                    }
                }
            ],
        },
    }

    def mock_cms_handler(request: httpx.Request) -> httpx.Response:
        rtype = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=cms_bundles[rtype])

    cms_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_cms_handler))
    cms_http = ScopedHttp.from_data_flow(cms.manifest.data_flows, client=cms_client)

    eob_page = await cms.fetch(ctx, stream="ExplanationOfBenefit", cursor=None, http=cms_http)
    eob_records = cms.map(eob_page)
    assert len(eob_records) == 1
    eob_rec = eob_records[0]
    assert eob_rec.data["trust"] == "untrusted"
    assert eob_rec.data["source_display"] == "From CMS Blue Button 2.0, 2026-10-05"
    assert eob_rec.data["claim_total"] == 245.50
    assert eob_rec.data["provider_display"] == "Bay Area Cardiology Associates"
    validated_eob = FhirExplanationOfBenefit.model_validate(eob_rec.data["fhir_resource"])
    assert validated_eob.id == "eob-medicare-501"

    cov_page = await cms.fetch(ctx, stream="Coverage", cursor=None, http=cms_http)
    cov_records = cms.map(cov_page)
    assert len(cov_records) == 1
    cov_rec = cov_records[0]
    assert cov_rec.data["trust"] == "untrusted"
    assert cov_rec.data["payor_display"] == "CMS Medicare Part B"
    validated_cov = FhirCoverage.model_validate(cov_rec.data["fhir_resource"])
    assert validated_cov.id == "cov-part-b-1"


@pytest.mark.asyncio
async def test_oura_google_health_and_microsoft_graph_connectors():
    """Verifies OuraConnector, GoogleHealthConnector, and MicrosoftGraphCalendarConnector (AU-74)."""
    oura = OuraConnector()
    ghealth = GoogleHealthConnector()
    msgraph = MicrosoftGraphCalendarConnector()

    assert oura.manifest.trust.trust_level == "trusted"
    assert ghealth.manifest.trust.trust_level == "trusted"
    assert msgraph.manifest.trust.trust_level == "trusted"

    ctx = ConnectorToolContext(user_id="user-wear-1", profile_id="prof-wear-1")

    # 1. Oura Ring daily summary -> RHR (8867-4), HRV (80404-7), Sleep (93832-4)
    oura_payload = {
        "data": [
            {
                "id": "2026-10-13",
                "day": "2026-10-13",
                "resting_heart_rate": 54,
                "hrv_ms": 62,
                "sleep_duration_hours": 7.8,
                "sleep_score": 88,
                "readiness_score": 85,
            }
        ]
    }
    oura_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=oura_payload))
    )
    oura_http = ScopedHttp.from_data_flow(oura.manifest.data_flows, client=oura_client)
    oura_page = await oura.fetch(ctx, stream="daily_summaries", cursor=None, http=oura_http)
    oura_records = oura.map(oura_page)
    assert len(oura_records) == 3

    oura_by_loinc = {}
    for rec in oura_records:
        obs = FhirObservation.model_validate(rec.data)
        oura_by_loinc[obs.code.coding[0].code] = obs
    assert set(oura_by_loinc.keys()) == {"8867-4", "80404-7", "93832-4"}
    assert float(oura_by_loinc["8867-4"].valueQuantity.value) == 54.0
    assert float(oura_by_loinc["80404-7"].valueQuantity.value) == 62.0

    # 2. Google Health daily metrics -> Steps (41950-7), HR (8867-4), Weight (29463-7)
    ghealth_payload = {
        "records": [
            {
                "id": "2026-10-13",
                "day": "2026-10-13",
                "steps": 9420,
                "heart_rate_avg": 71,
                "heart_rate_min": 56,
                "heart_rate_max": 134,
                "weight_kg": 68.4,
            }
        ]
    }
    ghealth_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=ghealth_payload))
    )
    ghealth_http = ScopedHttp.from_data_flow(ghealth.manifest.data_flows, client=ghealth_client)
    ghealth_page = await ghealth.fetch(ctx, stream="daily_metrics", cursor=None, http=ghealth_http)
    ghealth_records = ghealth.map(ghealth_page)
    assert len(ghealth_records) == 3

    ghealth_by_loinc = {}
    for rec in ghealth_records:
        obs = FhirObservation.model_validate(rec.data)
        ghealth_by_loinc[obs.code.coding[0].code] = obs
    assert set(ghealth_by_loinc.keys()) == {"41950-7", "8867-4", "29463-7"}
    assert float(ghealth_by_loinc["41950-7"].valueQuantity.value) == 9420.0
    assert float(ghealth_by_loinc["29463-7"].valueQuantity.value) == 68.4
    assert len(ghealth_by_loinc["8867-4"].component) == 2

    # 3. Microsoft Graph Calendar -> suggest slots & sanitized create event
    msgraph_payload = {
        "value": [
            {
                "id": "outlook-evt-1",
                "showAs": "busy",
                "start": {"dateTime": "2026-10-14T09:00:00Z"},
                "end": {"dateTime": "2026-10-14T10:30:00Z"},
            }
        ]
    }
    msgraph_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=msgraph_payload))
    )
    msgraph_http = ScopedHttp.from_data_flow(msgraph.manifest.data_flows, client=msgraph_client)
    msgraph_page = await msgraph.fetch(ctx, stream="events", cursor=None, http=msgraph_http)
    msgraph_busy = msgraph.map(msgraph_page)
    assert len(msgraph_busy) == 1

    ms_tools = {t.name: t for t in msgraph.tools()}
    assert set(ms_tools.keys()) == {"msgraph_suggest_slots", "msgraph_create_event"}
    assert ms_tools["msgraph_suggest_slots"].risk_tier == "read"
    assert ms_tools["msgraph_create_event"].risk_tier == "write_external"

    slots_res = await ms_tools["msgraph_suggest_slots"].handler(
        ctx,
        {
            "window_start": "2026-10-14T09:00:00Z",
            "window_end": "2026-10-14T11:30:00Z",
            "duration_minutes": 30,
        },
    )
    assert len(slots_res["slots"]) == 2
    assert slots_res["slots"][0]["start"] == "2026-10-14T10:30:00+00:00"

    create_res = await ms_tools["msgraph_create_event"].handler(
        ctx,
        {
            "title": "Neurology consultation for migraine prophylaxis",
            "start": "2026-10-14T10:30:00Z",
            "end": "2026-10-14T11:00:00Z",
            "event_id": "m365-101",
        },
    )
    assert create_res["external_ref"] == "msgraph_event:m365-101"
    assert create_res["title"] == "Medical Appointment"


@pytest.mark.asyncio
async def test_gmail_send_message_requires_explicit_approval_and_updates_draft(batch7_stream2_env):
    """Verifies gmail_send_message blocks unapproved sends with PermissionError and succeeds when approved (AU-76)."""
    factory = batch7_stream2_env["factory"]
    profile_id = batch7_stream2_env["profile_id"]
    user_id = batch7_stream2_env["user_id"]

    # Verify google_workspace_gmail.yaml manifest declares gmail_send_message as irreversible
    gmail_manifest_path = (
        Path(__file__).resolve().parents[2]
        / "libs"
        / "connectors"
        / "connectors"
        / "starters"
        / "manifests"
        / "google_workspace_gmail.yaml"
    )
    gmail_manifest = ConnectorManifest.from_yaml(gmail_manifest_path)
    mcp_tools = {t.name: t for t in gmail_manifest.mcp_tools}
    assert "gmail_list_messages" in mcp_tools
    assert "gmail_send_message" in mcp_tools
    assert mcp_tools["gmail_send_message"].risk_tier == "irreversible"

    async with factory() as session:
        draft = await create_email_draft(
            session=session,
            profile_id=profile_id,
            recipient="referrals@metroheart.org",
            subject="Cardiology Referral Packet",
            body="Please find attached the referral notes for Maya Patel.",
            category="appointment",
            created_by_user_id=user_id,
        )

        prepared = prepare_gmail_send_approval_payload(
            draft_id=draft.id,
            recipient=draft.recipient or "",
            subject=draft.subject,
            body=draft.body,
        )
        assert prepared["risk_tier"] == "irreversible"
        assert prepared["requires_approval"] is True

        # 1. Missing approval_id -> PermissionError
        with pytest.raises(PermissionError, match="irreversible"):
            await execute_gmail_send_message(
                session=session,
                profile_id=profile_id,
                draft_id=draft.id,
                approval_id=None,
                actor_user_id=user_id,
            )

        # 2. Pending (unapproved) Approval -> PermissionError
        now = utc_now()
        approval = Approval(
            id=str(uuid.uuid4()),
            profile_id=profile_id,
            run_id="run-gmail-send-1",
            tool_name="gmail_send_message",
            args_redacted=prepared["args_redacted"],
            payload_hash=prepared["payload_hash"],
            destination_hosts=prepared["destination_hosts"],
            risk_tier="irreversible",
            status="pending",
            expires_at=now + timedelta(hours=12),
            created_at=now,
        )
        session.add(approval)
        await session.commit()

        with pytest.raises(PermissionError, match="irreversible"):
            await execute_gmail_send_message(
                session=session,
                profile_id=profile_id,
                draft_id=draft.id,
                approval_id=approval.id,
                actor_user_id=user_id,
            )

        # 3. Approve record and execute send -> succeeds and updates draft
        approval.status = "approved"
        approval.decided_at = utc_now()
        approval.decided_by = user_id
        await session.commit()

        receipt = await execute_gmail_send_message(
            session=session,
            profile_id=profile_id,
            draft_id=draft.id,
            approval_id=approval.id,
            actor_user_id=user_id,
        )
        assert receipt["status"] == "sent_via_approved_mcp"
        assert receipt["external_message_id"].startswith("gmail-msg-")
        assert receipt["risk_tier"] == "irreversible"

        await session.refresh(draft)
        assert draft.status == "sent_via_approved_mcp"
        assert draft.sent_at is not None
        assert draft.external_message_id == receipt["external_message_id"]

        audits = (
            await session.execute(
                select(AuditEventRecord).where(
                    AuditEventRecord.profile_id == profile_id,
                    AuditEventRecord.tool == "gmail_send_message",
                )
            )
        ).scalars().all()
        assert len(audits) == 1
        assert audits[0].risk == "irreversible"
        assert audits[0].decision == "allow"


@pytest.mark.asyncio
async def test_coordinated_v2_fastapi_endpoints(batch7_stream2_env):
    """Verifies all endpoints in carefold.api.coordinated."""
    factory = batch7_stream2_env["factory"]
    profile_id = batch7_stream2_env["profile_id"]
    user_id = batch7_stream2_env["user_id"]

    app = FastAPI()
    app.include_router(coordinated_router)

    async def _override_get_db():
        async with factory() as session:
            yield session

    async def _override_user():
        now = datetime.now(timezone.utc)
        return UserProfile(
            id=user_id,
            email="steward-v2@example.com",
            username="steward_v2",
            role="steward",
            status="active",
            created_at=now,
            updated_at=now,
        )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. POST /profiles/{profile_id}/scheduling/smart-slots
        smart_resp = await client.post(
            f"/profiles/{profile_id}/scheduling/smart-slots",
            json={
                "specialty_filter": "Cardiology",
                "manifest_payload": {
                    "schedules": [
                        {
                            "resourceType": "Schedule",
                            "id": "sched-1",
                            "actor": [{"display": "Dr. Vance"}],
                            "specialty": [{"text": "Cardiology"}],
                        }
                    ],
                    "slots": [
                        {
                            "resourceType": "Slot",
                            "id": "slot-conflict-appt",
                            "schedule": {"reference": "Schedule/sched-1"},
                            "status": "free",
                            "start": "2026-10-25T10:15:00Z",
                            "end": "2026-10-25T10:45:00Z",
                        },
                        {
                            "resourceType": "Slot",
                            "id": "slot-clear-appt",
                            "schedule": {"reference": "Schedule/sched-1"},
                            "status": "free",
                            "start": "2026-10-25T13:00:00Z",
                            "end": "2026-10-25T13:30:00Z",
                        },
                    ],
                },
            },
        )
        assert smart_resp.status_code == 200
        smart_data = smart_resp.json()
        assert smart_data["total"] == 2
        slots_by_id = {s["slot_id"]: s for s in smart_data["slots"]}
        assert slots_by_id["slot-conflict-appt"]["fits_calendar"] is False
        assert slots_by_id["slot-clear-appt"]["fits_calendar"] is True

        # 2. POST /profiles/{profile_id}/scheduling/zocdoc-preview
        zocdoc_resp = await client.post(
            f"/profiles/{profile_id}/scheduling/zocdoc-preview",
            json={
                "provider_id": "prov-10",
                "provider_name": "Dr. Vance",
                "specialty": "Cardiology",
                "slot_id": "slot-clear-appt",
                "start_time": "2026-10-25T13:00:00Z",
                "insurance_carrier": "BlueCross",
            },
        )
        assert zocdoc_resp.status_code == 200
        zocdoc_data = zocdoc_resp.json()
        assert zocdoc_data["risk_tier"] == "irreversible"
        assert zocdoc_data["approval_status"] == "pending"
        assert zocdoc_data["approval_id"]

        # 3. POST /profiles/{profile_id}/email-drafts/{draft_id}/send
        async with factory() as session:
            draft = await create_email_draft(
                session=session,
                profile_id=profile_id,
                recipient="clinic@metroheart.org",
                subject="Pre-visit Records",
                body="Sending pre-visit lab summary.",
                category="appointment",
                created_by_user_id=user_id,
            )
            draft_id = draft.id

        # Without approval_id -> creates pending approval
        send_pending_resp = await client.post(
            f"/profiles/{profile_id}/email-drafts/{draft_id}/send",
            json={},
        )
        assert send_pending_resp.status_code == 200
        pending_data = send_pending_resp.json()
        assert pending_data["status"] == "needs_approval"
        approval_id = pending_data["approval_id"]

        # Approve in DB and call send with approval_id
        async with factory() as session:
            appr = (
                await session.execute(select(Approval).where(Approval.id == approval_id))
            ).scalar_one()
            appr.status = "approved"
            await session.commit()

        send_exec_resp = await client.post(
            f"/profiles/{profile_id}/email-drafts/{draft_id}/send",
            json={"approval_id": approval_id},
        )
        assert send_exec_resp.status_code == 200
        assert send_exec_resp.json()["status"] == "sent_via_approved_mcp"

        # 4. GET /profiles/{profile_id}/audit/verify
        async with factory() as session:
            await append_chained_audit_event(
                session,
                profile_id=profile_id,
                tool="zocdoc_search_providers",
                risk="read",
                decision="allow",
                payload_hash="abc123",
            )
            await session.commit()

        verify_resp = await client.get(f"/profiles/{profile_id}/audit/verify")
        assert verify_resp.status_code == 200
        assert verify_resp.json()["valid"] is True
        assert verify_resp.json()["checked_count"] >= 1

        # 5. GET /system/service-descriptors
        svc_resp = await client.get("/system/service-descriptors")
        assert svc_resp.status_code == 200
        assert svc_resp.json()["total"] == 3

        # 6. GET /connectors/v2-catalog
        cat_resp = await client.get("/connectors/v2-catalog")
        assert cat_resp.status_code == 200
        cat_data = cat_resp.json()
        assert cat_data["total"] == 7
        assert set(cat_data["connector_ids"]) == {
            "zocdoc",
            "oracle-health",
            "athenahealth",
            "cms-blue-button",
            "oura",
            "google-health",
            "microsoft-graph",
        }
