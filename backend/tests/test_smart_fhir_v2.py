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

"""Unit and integration tests for SMART on FHIR v2 client & persistent EHR sync (#286)."""

from __future__ import annotations

import os
from pathlib import Path
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.connectors.lifecycle import get_connector_manifest, grant_connector_consent
from carefold.connectors.oauth import (
    SMART_V1_CLINICAL_SCOPES,
    SMART_V2_CLINICAL_SCOPES,
    build_smart_authorization_url,
    discover_smart_configuration,
    generate_pkce_pair,
    load_connection_tokens,
    redact_smart_auth_secrets,
    store_connection_tokens,
)
from carefold.connectors.smart_fhir import SmartUntrustedResult
from carefold.connectors.sync import run_connection_sync
from carefold.db.models import Connection, Credential, Profile, User
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.engine.tool_exec import TaintFlag, UntrustedResult
from carefold.models.health import (
    HealthResource,
    HealthResourceCoding,
    HealthResourceReference,
    HealthResourceVersion,
)
from yarvelle_core.connectors.base import ToolContext
from yarvelle_core.connectors.errors import EgressBlockedError
from yarvelle_core.connectors.http import ScopedHttp
from carefold.connectors.starters.ehr_smart_v2 import (
    AthenahealthConnector,
    CmsBlueButtonConnector,
    OracleHealthConnector,
)
from carefold.connectors.starters.epic_smart import EpicSmartConnector


@pytest.fixture
async def smart_db(tmp_path: Path):
    """Provides an isolated SQLite database initialized with full schema for SMART v2 sync tests."""
    db_file = tmp_path / "smart_fhir_v2_test.db"
    engine = create_db_engine(f"sqlite+aiosqlite:///{db_file.resolve()}")
    await init_db(engine)
    factory = get_session_factory(engine)

    user_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    async with factory() as session:
        user = User(
            id=user_id,
            email="smart-v2@carefold.local",
            username="smart_v2_user",
            hashed_password="hashed_password",
            role="steward",
        )
        profile = Profile(
            id=profile_id,
            user_id=user_id,
            name="Elena Rostova",
            relationship="self",
            role="owner",
            date_of_birth="1985-06-15",
            is_primary=True,
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


@pytest.mark.asyncio
async def test_discover_smart_configuration_well_known_and_capability_statement_fallback():
    """Verifies .well-known/smart-configuration discovery, /metadata CapabilityStatement fallback, and PKCE S256 check."""
    base_url = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"

    # 1. Standard .well-known/smart-configuration response
    well_known_payload = {
        "authorization_endpoint": "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize",
        "token_endpoint": "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token",
        "revocation_endpoint": "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/revoke",
        "capabilities": [
            "launch-standalone",
            "client-public",
            "sso-openid-connect",
            "context-standalone-patient",
            "permission-v2",
            "permission-patient",
        ],
        "scopes_supported": list(SMART_V2_CLINICAL_SCOPES),
        "code_challenge_methods_supported": ["S256"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
    }

    mock_wk_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json=well_known_payload)
            if req.url.path.endswith("/.well-known/smart-configuration")
            else httpx.Response(404)
        )
    )
    http_wk = ScopedHttp(allowed_hosts=["fhir.epic.com"], client=mock_wk_client)

    cfg = await discover_smart_configuration(base_url, http_wk)
    assert cfg.discovery_source == "well-known"
    assert cfg.authorization_endpoint == well_known_payload["authorization_endpoint"]
    assert cfg.token_endpoint == well_known_payload["token_endpoint"]
    assert cfg.supports_pkce_s256 is True
    assert cfg.supports_smart_v2_scopes is True
    assert "patient/Observation.rs" in cfg.negotiate_scopes()

    # 2. Fallback to /metadata CapabilityStatement when .well-known returns 404
    capability_statement = {
        "resourceType": "CapabilityStatement",
        "status": "active",
        "fhirVersion": "4.0.1",
        "rest": [
            {
                "mode": "server",
                "security": {
                    "extension": [
                        {
                            "url": "http://fhir-registry.smarthealthit.org/StructureDefinition/oauth-uris",
                            "extension": [
                                {
                                    "url": "authorize",
                                    "valueUri": "https://fhir.epic.com/legacy-oauth2/authorize",
                                },
                                {
                                    "url": "token",
                                    "valueUri": "https://fhir.epic.com/legacy-oauth2/token",
                                },
                            ],
                        },
                        {
                            "url": "http://fhir-registry.smarthealthit.org/StructureDefinition/capabilities",
                            "valueCode": "launch-standalone",
                        },
                    ]
                },
            }
        ],
    }

    def fallback_handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/.well-known/smart-configuration"):
            return httpx.Response(404, json={"issue": "not found"})
        if req.url.path.endswith("/metadata"):
            return httpx.Response(200, json=capability_statement)
        return httpx.Response(500)

    mock_fb_client = httpx.AsyncClient(transport=httpx.MockTransport(fallback_handler))
    http_fb = ScopedHttp(allowed_hosts=["fhir.epic.com"], client=mock_fb_client)

    fb_cfg = await discover_smart_configuration(base_url, http_fb)
    assert fb_cfg.discovery_source == "capability-statement"
    assert fb_cfg.authorization_endpoint == "https://fhir.epic.com/legacy-oauth2/authorize"
    assert fb_cfg.token_endpoint == "https://fhir.epic.com/legacy-oauth2/token"
    assert fb_cfg.supports_pkce_s256 is True
    assert "launch-standalone" in fb_cfg.capabilities

    # 3. Fail closed when server explicitly omits S256 from code_challenge_methods_supported
    insecure_wk = dict(well_known_payload, code_challenge_methods_supported=["plain"])
    mock_bad_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=insecure_wk))
    )
    http_bad = ScopedHttp(allowed_hosts=["fhir.epic.com"], client=mock_bad_client)
    with pytest.raises(ValueError, match="S256"):
        await discover_smart_configuration(base_url, http_bad)


def test_pkce_s256_verification_and_smart_v2_granular_scopes_in_manifests():
    """Verifies PKCE S256 challenge enforcement, scope negotiation, and SMART v2 .rs scopes in manifests."""
    for connector_id in ("epic-smart", "oracle-health", "athenahealth"):
        manifest = get_connector_manifest(connector_id)
        assert manifest is not None
        scopes = set(manifest.auth.scopes)
        # Must include SMART v2 .rs granular scopes and backward-compatible v1 .read scopes
        assert set(SMART_V2_CLINICAL_SCOPES).issubset(scopes)
        assert "patient/Observation.read" in scopes
        assert "patient/Condition.read" in scopes

    verifier, challenge = generate_pkce_pair()
    connector = EpicSmartConnector()
    from carefold.connectors.smart_fhir import SmartConfiguration

    smart_cfg = SmartConfiguration(
        fhir_base_url=connector._base_url,
        authorization_endpoint="https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize",
        token_endpoint="https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token",
        capabilities=("permission-v2",),
        scopes_supported=SMART_V2_CLINICAL_SCOPES,
        code_challenge_methods_supported=("S256",),
    )

    auth_url = connector.build_authorization_url(
        smart_config=smart_cfg,
        client_id="carefold-local-client",
        redirect_uri="http://127.0.0.1:8000/api/v1/oauth/callback",
        state="signed-state-123",
        code_challenge=challenge,
        code_verifier=verifier,
    )
    assert "code_challenge_method=S256" in auth_url
    assert f"code_challenge={challenge}" in auth_url
    assert "aud=https%3A%2F%2Ffhir.epic.com" in auth_url
    assert "patient%2FCondition.rs" in auth_url
    assert "patient%2FObservation.rs" in auth_url

    # Mismatched PKCE verifier must fail closed before launching OAuth flow
    with pytest.raises(ValueError, match="code_verifier does not match"):
        build_smart_authorization_url(
            smart_config=smart_cfg,
            client_id="carefold-local-client",
            redirect_uri="http://127.0.0.1:8000/api/v1/oauth/callback",
            state="signed-state-123",
            code_challenge=challenge,
            code_verifier=verifier + "-tampered",
        )

    # Legacy v1 server scope fallback negotiation (.rs -> .read)
    legacy_cfg = SmartConfiguration(
        fhir_base_url=connector._base_url,
        authorization_endpoint="https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize",
        token_endpoint="https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token",
        capabilities=("permission-patient",),
        scopes_supported=SMART_V1_CLINICAL_SCOPES,
        code_challenge_methods_supported=("S256",),
    )
    negotiated_v1 = legacy_cfg.negotiate_scopes(SMART_V2_CLINICAL_SCOPES)
    assert "patient/Observation.read" in negotiated_v1
    assert "patient/Condition.read" in negotiated_v1


@pytest.mark.asyncio
async def test_multi_page_bundle_next_link_pagination_and_scoped_http_ssrf_blocking():
    """Verifies multi-page Bundle.link[relation='next'] traversal and ScopedHttp host allowlist blocking."""
    connector = EpicSmartConnector()
    ctx = ToolContext(user_id="u-page-1", profile_id="p-page-1")

    pages = {
        "page1": {
            "resourceType": "Bundle",
            "type": "searchset",
            "link": [
                {
                    "relation": "self",
                    "url": "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Observation?_count=50",
                },
                {
                    "relation": "next",
                    "url": "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Observation?_page=2",
                },
            ],
            "entry": [
                {
                    "resource": {
                        "resourceType": "Observation",
                        "id": "obs-p1",
                        "status": "final",
                        "effectiveDateTime": "2026-10-01T08:00:00Z",
                        "code": {
                            "coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "HbA1c"}],
                            "text": "HbA1c",
                        },
                        "valueQuantity": {"value": 6.1, "unit": "%"},
                    }
                }
            ],
        },
        "page2": {
            "resourceType": "Bundle",
            "type": "searchset",
            "link": [
                {
                    "relation": "next",
                    "url": "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Observation?_page=3",
                }
            ],
            "entry": [
                {
                    "resource": {
                        "resourceType": "Observation",
                        "id": "obs-p2",
                        "status": "final",
                        "effectiveDateTime": "2026-10-02T08:00:00Z",
                        "code": {
                            "coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "HbA1c"}],
                            "text": "HbA1c",
                        },
                        "valueQuantity": {"value": 5.9, "unit": "%"},
                    }
                }
            ],
        },
        "page3": {
            "resourceType": "Bundle",
            "type": "searchset",
            "link": [],
            "entry": [
                {
                    "resource": {
                        "resourceType": "Observation",
                        "id": "obs-p3",
                        "status": "final",
                        "effectiveDateTime": "2026-10-03T08:00:00Z",
                        "code": {
                            "coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "HbA1c"}],
                            "text": "HbA1c",
                        },
                        "valueQuantity": {"value": 5.7, "unit": "%"},
                    }
                }
            ],
        },
    }

    def multi_page_handler(req: httpx.Request) -> httpx.Response:
        q = str(req.url.query)
        if "_page=2" in q:
            return httpx.Response(200, json=pages["page2"])
        if "_page=3" in q:
            return httpx.Response(200, json=pages["page3"])
        return httpx.Response(200, json=pages["page1"])

    client = httpx.AsyncClient(transport=httpx.MockTransport(multi_page_handler))
    http = ScopedHttp.from_data_flow(connector.manifest.data_flows, client=client)

    # Full traversal across all 3 pages
    full_page = await connector.fetch(ctx, stream="Observation", cursor=None, http=http)
    assert len(full_page.records) == 3
    assert [r["id"] for r in full_page.records] == ["obs-p1", "obs-p2", "obs-p3"]
    assert full_page.has_more is False
    assert full_page.next_cursor is None
    assert full_page.metadata["pages_fetched"] == 3

    # Bounded traversal with max_pages=2 stops safely and returns next_cursor for page 3
    bounded_page = await connector.fetch(
        ctx, stream="Observation", cursor=None, http=http, max_pages=2
    )
    assert len(bounded_page.records) == 2
    assert [r["id"] for r in bounded_page.records] == ["obs-p1", "obs-p2"]
    assert bounded_page.has_more is True
    assert bounded_page.next_cursor == (
        "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Observation?_page=3"
    )

    # Resuming from bounded_page.next_cursor fetches page 3
    resumed_page = await connector.fetch(
        ctx, stream="Observation", cursor=bounded_page.next_cursor, http=http
    )
    assert len(resumed_page.records) == 1
    assert resumed_page.records[0]["id"] == "obs-p3"
    assert resumed_page.has_more is False

    # SSRF / Open-Redirect defense: Bundle.link[relation="next"] pointing to un-allowlisted host is blocked
    evil_next_bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "link": [
            {
                "relation": "next",
                "url": "https://evil-exfil.example.com/fhir/Observation?_page=2",
            }
        ],
        "entry": pages["page1"]["entry"],
    }
    evil_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=evil_next_bundle))
    )
    evil_http = ScopedHttp.from_data_flow(connector.manifest.data_flows, client=evil_client)
    with pytest.raises(EgressBlockedError) as exc_info:
        await connector.fetch(ctx, stream="Observation", cursor=None, http=evil_http)
    assert "evil-exfil.example.com" in str(exc_info.value)


@pytest.mark.asyncio
async def test_persistent_sync_cross_portal_deduplication_encrypted_tokens_and_secret_redaction(
    smart_db,
):
    """Verifies persistent sync into health_resources/codings/references/versions, cross-portal dedup, and encrypted tokens."""
    factory = smart_db["factory"]
    user_id = smart_db["user_id"]
    profile_id = smart_db["profile_id"]
    kek = os.urandom(32)

    shared_condition_bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-htn-portal",
                    "clinicalStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                "code": "active",
                            }
                        ]
                    },
                    "recordedDate": "2026-09-15",
                    "onsetDateTime": "2026-09-15",
                    "code": {
                        "coding": [
                            {
                                "system": "urn:oid:2.16.840.1.113883.6.96",
                                "code": "38341003",
                                "display": "Essential hypertension",
                            }
                        ],
                        "text": "Essential hypertension",
                    },
                    "subject": {"reference": "Patient/external-pat-99"},
                }
            }
        ],
    }

    async with factory() as session:
        # 1. Create Epic SMART connection & store encrypted OAuth tokens in Vault
        conn_epic = Connection(
            id=str(uuid.uuid4()),
            user_id=user_id,
            profile_id=profile_id,
            connector_id="epic-smart",
            status="pending_auth",
        )
        conn_oracle = Connection(
            id=str(uuid.uuid4()),
            user_id=user_id,
            profile_id=profile_id,
            connector_id="oracle-health",
            status="pending_auth",
        )
        session.add_all([conn_epic, conn_oracle])
        await session.commit()

        epic_manifest = get_connector_manifest("epic-smart")
        oracle_manifest = get_connector_manifest("oracle-health")
        assert epic_manifest is not None and oracle_manifest is not None

        secret_access_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.super_secret_epic_access_token"
        secret_refresh_token = "rt_epic_rotating_secret_998877"

        cred = await store_connection_tokens(
            session=session,
            profile_id=profile_id,
            connection_id=conn_epic.id,
            user_id=user_id,
            token_payload={
                "access_token": secret_access_token,
                "refresh_token": secret_refresh_token,
                "expires_in": 3600,
                "scope": " ".join(SMART_V2_CLINICAL_SCOPES),
            },
            kek=kek,
        )
        # Ensure raw SQLite column stores ciphertext only, never plaintext tokens
        raw_cred = (
            await session.execute(select(Credential).where(Credential.id == cred.id))
        ).scalar_one()
        assert secret_access_token not in raw_cred.encrypted_blob
        assert secret_refresh_token not in raw_cred.encrypted_blob

        loaded_tokens, ver = await load_connection_tokens(
            session=session,
            profile_id=profile_id,
            connection_id=conn_epic.id,
            kek=kek,
        )
        assert ver == 1
        assert loaded_tokens["access_token"] == secret_access_token

        await grant_connector_consent(
            session=session,
            profile_id=profile_id,
            connector_id="epic-smart",
            categories=list(epic_manifest.categories),
            scopes=list(epic_manifest.auth.scopes),
            allowed_hosts=list(epic_manifest.data_flows.allowed_hosts),
            granted_by_user_id=user_id,
            connection_id=conn_epic.id,
        )
        await grant_connector_consent(
            session=session,
            profile_id=profile_id,
            connector_id="oracle-health",
            categories=list(oracle_manifest.categories),
            scopes=list(oracle_manifest.auth.scopes),
            allowed_hosts=list(oracle_manifest.data_flows.allowed_hosts),
            granted_by_user_id=user_id,
            connection_id=conn_oracle.id,
        )

        # 2. Run sync for Epic SMART (Portal 1)
        def epic_mock(req: httpx.Request) -> httpx.Response:
            if req.url.path.endswith("/Condition"):
                return httpx.Response(200, json=shared_condition_bundle)
            return httpx.Response(200, json={"resourceType": "Bundle", "entry": []})

        epic_http_client = httpx.AsyncClient(transport=httpx.MockTransport(epic_mock))
        epic_sync = await run_connection_sync(
            session=session,
            connection_id=conn_epic.id,
            connector=EpicSmartConnector(),
            http_client=epic_http_client,
            kek=kek,
        )
        assert epic_sync.status == "succeeded"
        assert epic_sync.records_upserted == 1

        # 3. Run sync for Oracle Health (Portal 2) with the same Condition -> must deduplicate!
        def oracle_mock(req: httpx.Request) -> httpx.Response:
            if req.url.path.endswith("/Condition"):
                return httpx.Response(200, json=shared_condition_bundle)
            return httpx.Response(200, json={"resourceType": "Bundle", "entry": []})

        oracle_http_client = httpx.AsyncClient(transport=httpx.MockTransport(oracle_mock))
        oracle_sync = await run_connection_sync(
            session=session,
            connection_id=conn_oracle.id,
            connector=OracleHealthConnector(),
            http_client=oracle_http_client,
            kek=kek,
        )
        assert oracle_sync.status == "succeeded"
        assert oracle_sync.records_upserted == 1

        # Verify single deduplicated Condition row in health_resources with versionId == "2"
        hr_rows = list(
            (
                await session.execute(
                    select(HealthResource).where(
                        HealthResource.profile_id == profile_id,
                        HealthResource.resource_type == "Condition",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(hr_rows) == 1
        cond_hr = hr_rows[0]
        assert cond_hr.data["meta"]["versionId"] == "2"
        # OID urn:oid:2.16.840.1.113883.6.96 was normalized to http://snomed.info/sct by #283
        assert cond_hr.data["code"]["coding"][0]["system"] == "http://snomed.info/sct"
        assert cond_hr.data["code"]["coding"][0]["code"] == "38341003"
        # Subject reference was bound to Patient/{profile_id}
        assert cond_hr.data["subject"]["reference"] == f"Patient/{profile_id}"

        # Verify health_resource_versions has version 1 (create) and version 2 (merge)
        versions = list(
            (
                await session.execute(
                    select(HealthResourceVersion)
                    .where(HealthResourceVersion.resource_id == cond_hr.id)
                    .order_by(HealthResourceVersion.version_id.asc())
                )
            )
            .scalars()
            .all()
        )
        assert [v.version_id for v in versions] == [1, 2]
        assert [v.operation for v in versions] == ["create", "merge"]

        # Verify health_resource_codings indexed the SNOMED code
        codings = list(
            (
                await session.execute(
                    select(HealthResourceCoding).where(
                        HealthResourceCoding.resource_id == cond_hr.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any(
            c.system == "http://snomed.info/sct" and c.code == "38341003" for c in codings
        )

        # Verify health_resource_references indexed the Patient reference
        refs = list(
            (
                await session.execute(
                    select(HealthResourceReference).where(
                        HealthResourceReference.source_resource_id == cond_hr.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any(
            r.target_type == "Patient" and r.target_id == profile_id for r in refs
        )

        # 4. Simulate process restart: instantiate fresh connector instances with empty _indexed_records
        fresh_epic = EpicSmartConnector()
        fresh_oracle = OracleHealthConnector()
        fresh_athena = AthenahealthConnector()
        fresh_cms = CmsBlueButtonConnector()
        assert len(fresh_epic._indexed_records) == 0

        taint = TaintFlag(initial=False)
        ctx = ToolContext(user_id=user_id, profile_id=profile_id)
        object.__setattr__(ctx, "taint", taint)

        for conn_instance in (fresh_epic, fresh_oracle, fresh_athena):
            tool_spec = conn_instance.tools()[0]
            res = await tool_spec.handler(
                ctx, {"query": "hypertension", "session": session}
            )
            assert isinstance(res, UntrustedResult)
            assert isinstance(res, SmartUntrustedResult)
            assert res.taint is True
            assert res["count"] == 1
            assert res["trust"] == "untrusted"
            assert "hypertension" in res["records"][0]["code_display"].lower()
            assert res["records"][0]["source_display"].startswith("From ")

        assert taint.is_tainted is True

        # Also verify CMS Blue Button persistence & tool query across restart
        cms_page_bundle = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "ExplanationOfBenefit",
                        "id": "eob-persisted-1",
                        "status": "active",
                        "created": "2026-10-12",
                        "billablePeriod": {"start": "2026-10-10", "end": "2026-10-10"},
                        "provider": {"display": "Stanford Cardiovascular Health"},
                        "total": [
                            {
                                "category": {"text": "Submitted Amount"},
                                "amount": {"value": 310.0, "currency": "USD"},
                            }
                        ],
                    }
                }
            ],
        }
        cms_client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json=cms_page_bundle))
        )
        cms_http = ScopedHttp.from_data_flow(fresh_cms.manifest.data_flows, client=cms_client)
        cms_page = await fresh_cms.fetch(ctx, stream="ExplanationOfBenefit", cursor=None, http=cms_http)
        cms_mapped = fresh_cms.map(cms_page)
        await fresh_cms.persist_records(session, profile_id=profile_id, records=cms_mapped)
        await session.commit()

        restarted_cms = CmsBlueButtonConnector()
        assert len(restarted_cms._indexed_records) == 0
        cms_res = await restarted_cms.tools()[0].handler(
            ctx, {"query": "Stanford", "session": session}
        )
        assert isinstance(cms_res, UntrustedResult)
        assert cms_res["count"] == 1
        assert cms_res["records"][0]["provider_display"] == "Stanford Cardiovascular Health"

    # 5. Verify secret redaction helper never leaks tokens or verifiers in logs/errors
    leaked_msg = (
        f"HTTP 401 with Authorization: Bearer {secret_access_token} "
        f"and refresh_token={secret_refresh_token}&code_verifier=pkce_secret_verifier_99"
    )
    redacted_msg = redact_smart_auth_secrets(leaked_msg)
    assert secret_access_token not in redacted_msg
    assert secret_refresh_token not in redacted_msg
    assert "pkce_secret_verifier_99" not in redacted_msg
    assert "[REDACTED]" in redacted_msg
