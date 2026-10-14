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

"""Unit and integration tests for Carefold v1 starter connectors (AU-50, AU-54, AU-55, AU-56)."""

from __future__ import annotations

from fhir.resources.R4B.condition import Condition as FhirCondition
from fhir.resources.R4B.immunization import Immunization as FhirImmunization
from fhir.resources.R4B.medicationrequest import MedicationRequest as FhirMedicationRequest
from fhir.resources.R4B.observation import Observation as FhirObservation
import httpx
import pytest

from connectors import (
    Connector,
    ConnectorRegistry,
    EgressBlockedError,
    ScopedHttp,
    ToolContext,
    get_connector_registry,
    list_starter_manifests,
    load_connector,
)
from connectors.starters import (
    CalDavConnector,
    EpicSmartConnector,
    GoogleCalendarConnector,
    WithingsConnector,
    sanitize_calendar_event_title,
    suggest_free_slots,
)


def test_connector_registry_discovers_all_starter_manifests():
    """Verify ConnectorRegistry discovers and instantiates all 4 built-in starter connectors."""
    registry = ConnectorRegistry()
    manifests = registry.list_manifests()
    manifest_ids = [m.id for m in manifests]
    assert set(manifest_ids) == {"withings", "google-calendar", "caldav", "epic-smart"}

    # Verify helper functions
    assert len(list_starter_manifests()) == 4
    assert get_connector_registry().get_manifest("withings").auth.pkce is True
    assert get_connector_registry().get_manifest("withings").auth.client_source == "byo"
    assert get_connector_registry().get_manifest("withings").trust.trust_level == "trusted"
    assert get_connector_registry().get_manifest("epic-smart").trust.trust_level == "untrusted"

    for cid in ("withings", "google-calendar", "caldav", "epic-smart"):
        connector = load_connector(cid)
        assert isinstance(connector, Connector)
        assert connector.manifest.id == cid


@pytest.mark.asyncio
async def test_withings_connector_fetch_and_map_fhir_observations():
    """Verify WithingsConnector converts raw measuregrps (BP 122/78, HR 68, Weight 72.5 kg) into valid FHIR Observations."""
    connector = WithingsConnector()
    ctx = ToolContext(user_id="user-withings-1", profile_id="profile-withings-1")

    withings_payload = {
        "status": 0,
        "body": {
            "updatetime": 1728840000,
            "more": 0,
            "measuregrps": [
                {
                    "grpid": 9001,
                    "date": 1728835200,
                    "measures": [
                        {"value": 72500, "type": 1, "unit": -3},  # 72.5 kg weight
                        {"value": 122, "type": 10, "unit": 0},    # 122 mmHg systolic
                        {"value": 78, "type": 9, "unit": 0},      # 78 mmHg diastolic
                        {"value": 68, "type": 11, "unit": 0},     # 68 bpm heart rate
                        {"value": 98, "type": 54, "unit": 0},     # 98 % SpO2
                    ],
                }
            ],
        },
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "wbsapi.withings.net"
        assert "action=getmeas" in str(request.url)
        return httpx.Response(200, json=withings_payload)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    http = ScopedHttp.from_data_flow(connector.manifest.data_flows, client=mock_client)

    page = await connector.fetch(ctx, stream="measures", cursor="1728800000", http=http)
    assert page.stream == "measures"
    assert page.next_cursor == "1728840000"
    assert len(page.records) == 1

    records = connector.map(page)
    # Expect 4 observations: Weight (29463-7), HR (8867-4), SpO2 (2708-6), and BP Panel (85354-9)
    assert len(records) == 4
    by_loinc = {}
    for rec in records:
        assert rec.record_type == "Observation"
        assert rec.profile_id == "profile-withings-1"
        validated = FhirObservation.model_validate(rec.data)
        loinc_code = validated.code.coding[0].code
        by_loinc[loinc_code] = validated

    assert set(by_loinc.keys()) == {"29463-7", "8867-4", "2708-6", "85354-9"}
    assert float(by_loinc["29463-7"].valueQuantity.value) == 72.5
    assert by_loinc["29463-7"].valueQuantity.unit == "kg"
    assert float(by_loinc["8867-4"].valueQuantity.value) == 68.0
    assert float(by_loinc["2708-6"].valueQuantity.value) == 98.0

    bp_obs = by_loinc["85354-9"]
    comp_by_loinc = {c.code.coding[0].code: float(c.valueQuantity.value) for c in bp_obs.component}
    assert comp_by_loinc == {"8480-6": 122.0, "8462-4": 78.0}

    # Verify withings_latest_vitals tool spec and execution
    tools = connector.tools()
    assert len(tools) == 1
    vital_tool = tools[0]
    assert vital_tool.name == "withings_latest_vitals"
    assert vital_tool.risk_tier == "read"
    assert vital_tool.trust == "trusted"
    assert "wbsapi.withings.net" in vital_tool.data_flows
    tool_result = await vital_tool.handler(ctx, {"limit": 5})
    assert tool_result["count"] == 4


@pytest.mark.asyncio
async def test_calendar_connectors_free_slots_phi_stripping_and_tools():
    """Verify GoogleCalendarConnector/CalDavConnector slot calculation, PHI stripping, and write_external tool."""
    gcal = GoogleCalendarConnector()
    caldav = CalDavConnector()
    ctx = ToolContext(user_id="user-cal-1", profile_id="profile-cal-1")

    busy_events = {
        "items": [
            {
                "id": "busy-morning",
                "status": "confirmed",
                "start": {"dateTime": "2026-10-14T09:00:00Z"},
                "end": {"dateTime": "2026-10-14T10:00:00Z"},
                "summary": "Team Standup",
            },
            {
                "id": "busy-midday",
                "status": "confirmed",
                "start": {"dateTime": "2026-10-14T10:30:00Z"},
                "end": {"dateTime": "2026-10-14T11:30:00Z"},
                "summary": "Project Sync",
            },
        ],
        "nextSyncToken": "sync-tok-123",
    }

    def mock_gcal_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.googleapis.com"
        return httpx.Response(200, json=busy_events)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_gcal_handler))
    http = ScopedHttp.from_data_flow(gcal.manifest.data_flows, client=mock_client)

    page = await gcal.fetch(ctx, stream="events", cursor=None, http=http)
    mapped_busy = gcal.map(page)
    assert len(mapped_busy) == 2
    assert all(r.record_type == "schedule_slot" for r in mapped_busy)

    # Compute free 30-min slots between 09:00 and 12:00 UTC on 2026-10-14
    slots = suggest_free_slots(
        busy_windows=mapped_busy,
        window_start="2026-10-14T09:00:00Z",
        window_end="2026-10-14T12:00:00Z",
        duration_minutes=30,
    )
    assert len(slots) == 2
    assert slots[0]["start"] == "2026-10-14T10:00:00+00:00"
    assert slots[0]["end"] == "2026-10-14T10:30:00+00:00"
    assert slots[1]["start"] == "2026-10-14T11:30:00+00:00"
    assert slots[1]["end"] == "2026-10-14T12:00:00+00:00"
    assert "Suggested times that fit my calendar. Nothing booked" in slots[0]["summary"]

    # Verify PHI stripping from calendar titles
    raw_phi_title = "Cardiology follow-up for Atrial Fibrillation & Eliquis 5mg adjustment"
    assert sanitize_calendar_event_title(raw_phi_title) == "Medical Appointment"
    assert sanitize_calendar_event_title(raw_phi_title, strip_phi=False) == raw_phi_title
    assert sanitize_calendar_event_title("Clinic Visit", strip_phi=True) == "Clinic Visit"

    # Verify tools on both GoogleCalendarConnector and CalDavConnector
    for conn in (gcal, caldav):
        tools_by_name = {t.name: t for t in conn.tools()}
        assert set(tools_by_name.keys()) == {"calendar_suggest_slots", "calendar_create_event"}

        suggest_tool = tools_by_name["calendar_suggest_slots"]
        assert suggest_tool.risk_tier == "read"
        assert suggest_tool.trust == "trusted"

        create_tool = tools_by_name["calendar_create_event"]
        assert create_tool.risk_tier == "write_external"
        assert create_tool.trust == "trusted"

        created = await create_tool.handler(
            ctx,
            {
                "title": "Oncology infusion for stage II lymphoma",
                "start": "2026-10-14T10:00:00Z",
                "end": "2026-10-14T10:30:00Z",
                "event_id": "evt987",
            },
        )
        assert created["status"] == "created"
        assert created["external_ref"] == "calendar_event:evt987"
        assert created["title"] == "Medical Appointment"


@pytest.mark.asyncio
async def test_epic_smart_connector_validates_uscdi_fhir_and_marks_untrusted():
    """Verify EpicSmartConnector validates USCDI FHIR R4 resources and attaches untrusted provenance."""
    connector = EpicSmartConnector()
    ctx = ToolContext(user_id="user-epic-1", profile_id="profile-epic-1")

    stream_names = [s.name for s in connector.streams()]
    assert stream_names == [
        "Condition",
        "MedicationRequest",
        "AllergyIntolerance",
        "Immunization",
        "Observation",
        "Encounter",
        "DocumentReference",
    ]

    sample_bundles = {
        "Condition": {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Condition",
                        "id": "cond-htn-1",
                        "recordedDate": "2026-09-15",
                        "code": {
                            "coding": [
                                {
                                    "system": "http://snomed.info/sct",
                                    "code": "38341003",
                                    "display": "Essential hypertension",
                                }
                            ],
                            "text": "Essential hypertension",
                        },
                        "subject": {"reference": "Patient/pat-1"},
                    }
                }
            ],
        },
        "MedicationRequest": {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "MedicationRequest",
                        "id": "medreq-lisinopril-1",
                        "status": "active",
                        "intent": "order",
                        "authoredOn": "2026-09-16",
                        "medicationCodeableConcept": {"text": "Lisinopril 10 MG Oral Tablet"},
                        "subject": {"reference": "Patient/pat-1"},
                    }
                }
            ],
        },
        "Immunization": {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Immunization",
                        "id": "imm-flu-1",
                        "status": "completed",
                        "occurrenceDateTime": "2026-10-01",
                        "vaccineCode": {"text": "Influenza, seasonal, injectable"},
                        "patient": {"reference": "Patient/pat-1"},
                    }
                }
            ],
        },
        "Observation": {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Observation",
                        "id": "obs-a1c-1",
                        "status": "final",
                        "effectiveDateTime": "2026-10-05T08:30:00Z",
                        "code": {
                            "coding": [
                                {
                                    "system": "http://loinc.org",
                                    "code": "4548-4",
                                    "display": "Hemoglobin A1c/Hemoglobin.total in Blood",
                                }
                            ],
                            "text": "Hemoglobin A1c",
                        },
                        "valueQuantity": {"value": 5.8, "unit": "%"},
                    }
                }
            ],
        },
    }

    def mock_epic_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "fhir.epic.com"
        rtype = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=sample_bundles[rtype])

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_epic_handler))
    http = ScopedHttp.from_data_flow(connector.manifest.data_flows, client=mock_client)

    validators = {
        "Condition": FhirCondition,
        "MedicationRequest": FhirMedicationRequest,
        "Immunization": FhirImmunization,
        "Observation": FhirObservation,
    }

    for stream_name, model_cls in validators.items():
        page = await connector.fetch(ctx, stream=stream_name, cursor=None, http=http)
        records = connector.map(page)
        assert len(records) == 1
        rec = records[0]
        assert rec.record_type == stream_name
        assert rec.data["trust"] == "untrusted"
        assert rec.data["source_display"].startswith("From Epic SMART, 2026-")
        validated_model = model_cls.model_validate(rec.data["fhir_resource"])
        assert validated_model.id is not None

    tools = connector.tools()
    assert len(tools) == 1
    assert tools[0].name == "epic_smart_search_records"
    assert tools[0].trust == "untrusted"
    assert tools[0].risk_tier == "read"
    search_res = await tools[0].handler(ctx, {"query": "hypertension"})
    assert search_res["count"] == 1
    assert search_res["trust"] == "untrusted"


@pytest.mark.asyncio
async def test_scoped_http_blocks_unallowlisted_hosts_across_all_starters():
    """Verify ScopedHttp blocks outbound requests to any un-allowlisted host for all 4 starters."""
    for connector_id in ("withings", "google-calendar", "caldav", "epic-smart"):
        connector = load_connector(connector_id)
        http = ScopedHttp.from_data_flow(connector.manifest.data_flows)
        try:
            with pytest.raises(EgressBlockedError):
                await http.get("https://evil-exfil.example.com/steal")
            with pytest.raises(EgressBlockedError):
                await http.get("http://169.254.169.254/latest/meta-data/")
        finally:
            await http.aclose()
