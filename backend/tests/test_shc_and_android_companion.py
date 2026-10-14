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

"""Unit and integration tests for SMART Health Cards, FHIR-Converter Sidecar (AU-77), and Android Health Connect Companion (AU-75)."""

from __future__ import annotations

import base64
import json
from typing import Any, AsyncGenerator, Dict, Tuple

from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from carefold.api.companion import router as companion_router
from carefold.api.deps import get_current_user, get_db
from carefold.auth.ports import UserProfile
from carefold.companion import (
    CompanionPairingError,
    authenticate_companion_device,
    check_companion_mode_guard,
    complete_companion_pairing,
    ingest_companion_sync,
    initiate_companion_pairing,
    revoke_companion_device,
)
from carefold.config import settings
from carefold.db.base import Base
from carefold.db.models import (
    AuditEventRecord,
    CompanionDevice,
    ConsentGrant,
    HealthResource,
    ImportBatch,
    Profile,
    User,
    utc_now,
)
from carefold.importers import (
    commit_import_batch,
    convert_clinical_payload_to_fhir,
    create_signed_shc_jws,
    detect_import_format,
    encode_shc_qr_uri,
    export_public_jwk,
    stage_import,
    verify_and_parse_smart_health_card,
)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Creates an isolated in-memory SQLite database session for AU-75 and AU-77 tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_profiles(
    db_session: AsyncSession,
) -> Tuple[User, Profile, Profile]:
    """Seeds a steward user and two isolated care profiles."""
    now = utc_now()
    steward = User(
        id="user-steward-au75",
        email="steward@example.com",
        username="steward_au75",
        hashed_password="hashed-password",
        full_name="Maya Steward",
        role="steward",
        status="active",
        auth_provider="local",
        created_at=now,
        updated_at=now,
    )
    primary_profile = Profile(
        id="profile-maya-1",
        user_id=steward.id,
        name="Maya",
        relationship="self",
        role="owner",
        date_of_birth="1988-09-12",
        is_primary=True,
        created_at=now,
        updated_at=now,
    )
    secondary_profile = Profile(
        id="profile-aria-2",
        user_id=steward.id,
        name="Aria",
        relationship="child",
        role="guardian",
        date_of_birth="2018-04-03",
        is_primary=False,
        created_at=now,
        updated_at=now,
    )
    db_session.add_all([steward, primary_profile, secondary_profile])
    await db_session.commit()
    return steward, primary_profile, secondary_profile


def _sample_shc_vc_payload() -> Dict[str, Any]:
    """Builds a standard W3C / HL7 SMART Health Card verifiable credential payload."""
    return {
        "iss": "https://smarthealth.cards/examples/issuer",
        "nbf": 1700000000,
        "vc": {
            "type": [
                "https://smarthealth.cards#health-card",
                "https://smarthealth.cards#immunization",
                "https://smarthealth.cards#covid19",
            ],
            "credentialSubject": {
                "fhirVersion": "4.0.1",
                "fhirBundle": {
                    "resourceType": "Bundle",
                    "type": "collection",
                    "entry": [
                        {
                            "fullUrl": "resource:0",
                            "resource": {
                                "resourceType": "Patient",
                                "name": [{"family": "Anyperson", "given": ["John"]}],
                                "birthDate": "1988-09-12",
                            },
                        },
                        {
                            "fullUrl": "resource:1",
                            "resource": {
                                "resourceType": "Immunization",
                                "id": "shc-imm-covid-1",
                                "status": "completed",
                                "vaccineCode": {
                                    "coding": [
                                        {
                                            "system": "http://hl7.org/fhir/sid/cvx",
                                            "code": "208",
                                            "display": "COVID-19, mRNA, LNP-S, PF, 30 mcg/0.3 mL dose",
                                        }
                                    ],
                                    "text": "COVID-19 mRNA Vaccine",
                                },
                                "patient": {"reference": "resource:0"},
                                "occurrenceDateTime": "2026-01-15",
                                "lotNumber": "EL9262",
                            },
                        },
                        {
                            "fullUrl": "resource:2",
                            "resource": {
                                "resourceType": "Immunization",
                                "id": "shc-imm-mmr-1",
                                "status": "completed",
                                "vaccineCode": {
                                    "coding": [
                                        {
                                            "system": "http://hl7.org/fhir/sid/cvx",
                                            "code": "03",
                                            "display": "MMR",
                                        }
                                    ],
                                    "text": "MMR Vaccine",
                                },
                                "patient": {"reference": "resource:0"},
                                "occurrenceDateTime": "2025-06-10",
                            },
                        },
                        {
                            "fullUrl": "resource:3",
                            "resource": {
                                "resourceType": "Observation",
                                "id": "shc-obs-titer-1",
                                "status": "final",
                                "code": {
                                    "coding": [
                                        {
                                            "system": "http://loinc.org",
                                            "code": "94504-8",
                                            "display": "SARS-CoV-2 Ab Panel",
                                        }
                                    ],
                                    "text": "SARS-CoV-2 Antibody Panel",
                                },
                                "subject": {"reference": "resource:0"},
                                "effectiveDateTime": "2026-02-01",
                                "valueString": "Reactive",
                            },
                        },
                    ],
                },
            },
        },
    }


# ============================================================================
# Section 1: SMART Health Card JWS ES256 Verifier & QR Decoder (AU-77)
# ============================================================================


def test_shc_es256_jws_verification_with_trusted_jwks() -> None:
    """Verifies P-256 ES256 JWS signature against trusted JWKS and extracts Immunization and Observation resources."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    jwk = export_public_jwk(private_key, kid="issuer-key-2026")
    trusted_jwks = {"keys": [jwk]}

    vc_payload = _sample_shc_vc_payload()
    compact_jws = create_signed_shc_jws(vc_payload, private_key=private_key, kid="issuer-key-2026")
    shc_container = json.dumps({"verifiableCredential": [compact_jws]})

    result = verify_and_parse_smart_health_card(
        shc_container,
        trusted_jwks=trusted_jwks,
        source_name="State Vaccine Wallet",
    )

    assert result["format"] == "smart_health_card"
    assert result["issuer"] == "https://smarthealth.cards/examples/issuer"
    assert result["verification_status"] == "verified"

    records = result["records"]
    assert len(records) == 3

    imm_codes = {r["code"] for r in records if r["resource_type"] == "Immunization"}
    assert imm_codes == {"208", "03"}

    obs_records = [r for r in records if r["resource_type"] == "Observation"]
    assert len(obs_records) == 1
    assert obs_records[0]["code"] == "94504-8"

    for rec in records:
        assert rec["trust"] == "untrusted"
        assert "From State Vaccine Wallet (https://smarthealth.cards/examples/issuer, verified)" in rec["source_display"]


def test_shc_numeric_qr_uri_decoding_and_verification() -> None:
    """Verifies numeric shc:/... QR URI encoding/decoding and ES256 signature verification."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    trusted_jwks = {"keys": [export_public_jwk(private_key, kid="qr-key-1")]}

    compact_jws = create_signed_shc_jws(_sample_shc_vc_payload(), private_key=private_key, kid="qr-key-1")
    qr_uri = encode_shc_qr_uri(compact_jws)
    assert qr_uri.startswith("shc:/")
    assert qr_uri[5:].isdigit()

    assert detect_import_format("qr_scan.txt", qr_uri) == "smart_health_card"

    parsed = verify_and_parse_smart_health_card(qr_uri, trusted_jwks=trusted_jwks)
    assert parsed["verification_status"] == "verified"
    assert parsed["summary"]["counts_by_type"] == {"Immunization": 2, "Observation": 1}


def test_shc_tampered_payload_or_signature_raises_value_error() -> None:
    """Verifies that tampering with the JWS payload or signature raises ValueError during verification."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    wrong_key = ec.generate_private_key(ec.SECP256R1())
    trusted_jwks = {"keys": [export_public_jwk(private_key, kid="shc-key-1")]}
    wrong_jwks = {"keys": [export_public_jwk(wrong_key, kid="shc-key-1")]}

    compact_jws = create_signed_shc_jws(_sample_shc_vc_payload(), private_key=private_key, kid="shc-key-1")
    header_b64, payload_b64, sig_b64 = compact_jws.split(".")

    # 1. Tamper with signature bytes
    sig_raw = bytearray(
        base64.urlsafe_b64decode(sig_b64 + "=" * ((4 - len(sig_b64) % 4) % 4))
    )
    sig_raw[0] ^= 0xFF
    tampered_sig_b64 = base64.urlsafe_b64encode(bytes(sig_raw)).rstrip(b"=").decode("ascii")
    tampered_jws = f"{header_b64}.{payload_b64}.{tampered_sig_b64}"

    with pytest.raises(ValueError, match="signature verification failed"):
        verify_and_parse_smart_health_card(tampered_jws, trusted_jwks=trusted_jwks)

    # 2. Verify against wrong issuer public key
    with pytest.raises(ValueError, match="signature verification failed"):
        verify_and_parse_smart_health_card(compact_jws, trusted_jwks=wrong_jwks)


@pytest.mark.asyncio
async def test_shc_stage_and_commit_import_workflow(
    db_session: AsyncSession,
    seeded_profiles: Tuple[User, Profile, Profile],
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies staging and committing a .smart-health-card file through stage_import and commit_import_batch."""
    monkeypatch.setattr(settings, "home_dir", tmp_path)
    steward, primary_profile, _ = seeded_profiles

    private_key = ec.generate_private_key(ec.SECP256R1())
    trusted_jwks = {"keys": [export_public_jwk(private_key, kid="shc-key-stage")]}
    compact_jws = create_signed_shc_jws(_sample_shc_vc_payload(), private_key=private_key, kid="shc-key-stage")
    shc_file_json = json.dumps({"verifiableCredential": [compact_jws]})

    batch: ImportBatch = await stage_import(
        session=db_session,
        profile_id=primary_profile.id,
        filename="immunizations.smart-health-card",
        content=shc_file_json,
        user_id=steward.id,
        trusted_jwks=trusted_jwks,
    )

    assert batch.format == "smart_health_card"
    assert batch.status == "staged"
    summary = json.loads(batch.summary_json)
    assert summary["verification_status"] == "verified"
    assert summary["issuer"] == "https://smarthealth.cards/examples/issuer"
    assert summary["total_records"] == 3

    # Ensure zero HealthResource rows exist prior to commit (Review-Before-Save invariant)
    pre_res = await db_session.execute(
        select(HealthResource).where(HealthResource.profile_id == primary_profile.id)
    )
    assert list(pre_res.scalars().all()) == []

    commit_result = await commit_import_batch(
        session=db_session,
        profile_id=primary_profile.id,
        batch_id=batch.id,
        actor_user_id=steward.id,
    )
    assert commit_result["status"] == "committed"
    assert commit_result["committed_count"] == 3

    post_res = await db_session.execute(
        select(HealthResource).where(HealthResource.profile_id == primary_profile.id)
    )
    saved_resources = list(post_res.scalars().all())
    assert len(saved_resources) == 3
    saved_types = {r.resource_type for r in saved_resources}
    assert saved_types == {"Immunization", "Observation"}


# ============================================================================
# Section 2: FHIR-Converter Sidecar Adapter & HL7v2 Parser (AU-77)
# ============================================================================


@pytest.mark.asyncio
async def test_fhir_converter_hl7v2_local_fallback_and_sidecar_transport() -> None:
    """Verifies HL7v2 MSH/PID/OBX/RXA conversion into FHIR R4 Observation and Immunization resources."""
    hl7v2_message = (
        "MSH|^~\\&|LAB|GENERAL_HOSP|CAREFOLD|LOCAL|20260322091500||ORU^R01|MSG1001|P|2.5.1\r"
        "PID|1||MRN-998877^^^HOSP^MR||PATEL^MAYA||19880912|F\r"
        "OBX|1|NM|4548-4^Hemoglobin A1c^LN||5.6|%^^UCUM|4.0-5.6|N|||F|||20260322091500\r"
        "OBX|2|NM|8480-6^Systolic blood pressure^LN||122|mm[Hg]^mmHg^UCUM|90-120|N|||F|||20260322091500\r"
        "RXA|0|1|20260310|20260310|208^COVID-19, mRNA, LNP-S, PF^CVX|0.3|mL^^UCUM||||||||LOT-PF-99||PFR^Pfizer|||CP\r"
    )

    # 1. Local fallback conversion
    converted = await convert_clinical_payload_to_fhir(hl7v2_message, input_type="hl7v2")
    assert converted["converter_mode"] == "local_fallback"
    assert converted["bundle"]["resourceType"] == "Bundle"
    assert converted["patient"]["name"][0]["family"] == "PATEL"

    records = converted["records"]
    assert len(records) == 3
    assert converted["summary"]["counts_by_type"] == {"Observation": 2, "Immunization": 1}

    imm_rec = next(r for r in records if r["resource_type"] == "Immunization")
    assert imm_rec["code"] == "208"
    assert imm_rec["data"]["lotNumber"] == "LOT-PF-99"
    assert imm_rec["trust"] == "untrusted"

    # 2. Sidecar HTTP transport conversion with loopback guard
    def _mock_sidecar_handler(request: Request) -> Response:
        assert request.url.path == "/api/convert"
        body = json.loads(request.content.decode("utf-8"))
        assert body["input_type"] == "hl7v2"
        return Response(
            status_code=200,
            json={
                "fhirResource": converted["bundle"],
            },
        )

    sidecar_res = await convert_clinical_payload_to_fhir(
        hl7v2_message,
        input_type="hl7v2",
        sidecar_url="http://127.0.0.1:8080",
        transport=MockTransport(_mock_sidecar_handler),
    )
    assert sidecar_res["converter_mode"] == "sidecar"
    assert len(sidecar_res["records"]) == 3

    # 3. Non-loopback sidecar URL must be rejected (SSRF protection)
    with pytest.raises(ValueError, match="not in the loopback allowlist"):
        await convert_clinical_payload_to_fhir(
            hl7v2_message,
            input_type="hl7v2",
            sidecar_url="https://external-converter.example.com",
        )


# ============================================================================
# Section 3: Android Health Connect Companion Pairing & Sync (AU-75)
# ============================================================================


@pytest.mark.asyncio
async def test_android_companion_pairing_daily_aggregation_red_flags_and_isolation(
    db_session: AsyncSession,
    seeded_profiles: Tuple[User, Profile, Profile],
) -> None:
    """Verifies Android Health Connect pairing, Mode S guard, daily step/HR aggregation, BP red flags, and profile isolation."""
    steward, primary_profile, secondary_profile = seeded_profiles

    # 1. Mode S network guard blocks non-loopback when auth_provider == 'disabled'
    with pytest.raises(PermissionError, match="non-loopback"):
        check_companion_mode_guard(auth_provider="disabled", bind_host="0.0.0.0")

    # 2. Initiate Android companion pairing
    fingerprint = "sha256:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99"
    initiated = await initiate_companion_pairing(
        session=db_session,
        user_id=steward.id,
        profile_id=primary_profile.id,
        device_name="Pixel 9 Pro (Health Connect)",
        host="127.0.0.1",
        port=8000,
        cert_fingerprint_sha256=fingerprint,
        platform="android",
    )
    assert initiated["platform"] == "android"
    assert initiated["connector_id"] == "android-companion"
    assert initiated["status"] == "pending_pair"

    # 3. Complete pairing and verify android-companion ConsentGrant + cf-android- token
    completed = await complete_companion_pairing(
        session=db_session,
        device_id=initiated["device_id"],
        pairing_code=initiated["pairing_code"],
        client_cert_fingerprint_sha256=fingerprint,
    )
    assert completed["platform"] == "android"
    assert completed["connector_id"] == "android-companion"
    assert completed["device_token"].startswith("cf-android-")

    grant_res = await db_session.execute(
        select(ConsentGrant).where(
            ConsentGrant.profile_id == primary_profile.id,
            ConsentGrant.connector_id == "android-companion",
        )
    )
    grant = grant_res.scalar_one_or_none()
    assert grant is not None
    assert grant.status == "active"

    # 4. Verify cross-profile isolation (token scoped to primary_profile rejected for secondary_profile)
    with pytest.raises(CompanionPairingError, match="scoped to profile"):
        await authenticate_companion_device(
            session=db_session,
            profile_id=secondary_profile.id,
            device_token=completed["device_token"],
        )

    device = await authenticate_companion_device(
        session=db_session,
        profile_id=primary_profile.id,
        device_token=completed["device_token"],
    )

    # 5. Ingest Android Health Connect records:
    #    - 3 high-frequency StepsRecord slices on 2026-03-22 -> must aggregate into 1 daily Observation (8500 steps)
    #    - 2 high-frequency HeartRateRecord batches on 2026-03-22 -> must aggregate into 1 daily Observation (avg 75.0 bpm)
    #    - 1 hypertensive crisis BloodPressureRecord (186/124 mmHg) -> triggers AU-32 vitals red flag
    #    - 1 WeightRecord (70.4 kg)
    #    - 1 MedicalResource (Immunization)
    hc_records = [
        {
            "recordType": "StepsRecord",
            "startTime": "2026-03-22T08:00:00Z",
            "endTime": "2026-03-22T10:00:00Z",
            "count": 3200,
        },
        {
            "recordType": "StepsRecord",
            "startTime": "2026-03-22T12:00:00Z",
            "endTime": "2026-03-22T14:00:00Z",
            "count": 2800,
        },
        {
            "recordType": "StepsRecord",
            "startTime": "2026-03-22T17:00:00Z",
            "endTime": "2026-03-22T19:00:00Z",
            "count": 2500,
        },
        {
            "recordType": "HeartRateRecord",
            "startTime": "2026-03-22T09:00:00Z",
            "samples": [
                {"time": "2026-03-22T09:00:00Z", "beatsPerMinute": 70},
                {"time": "2026-03-22T09:05:00Z", "beatsPerMinute": 80},
            ],
        },
        {
            "recordType": "BloodPressureRecord",
            "id": "hc-bp-crisis-1",
            "time": "2026-03-22T10:30:00Z",
            "systolic": {"inMillimetersOfMercury": 186.0},
            "diastolic": {"inMillimetersOfMercury": 124.0},
        },
        {
            "recordType": "WeightRecord",
            "id": "hc-weight-1",
            "time": "2026-03-22T07:30:00Z",
            "weight": {"inKilograms": 70.4},
        },
        {
            "recordType": "MedicalResource",
            "id": "hc-medres-imm-1",
            "fhirResource": {
                "resourceType": "Immunization",
                "id": "hc-imm-tdap-1",
                "status": "completed",
                "vaccineCode": {
                    "coding": [{"system": "http://hl7.org/fhir/sid/cvx", "code": "115", "display": "Tdap"}],
                    "text": "Tdap Vaccine",
                },
                "occurrenceDateTime": "2026-01-20",
            },
        },
    ]

    sync_res = await ingest_companion_sync(
        session=db_session,
        device=device,
        health_connect_records=hc_records,
    )

    # 4 observations expected: 1 daily Steps + 1 daily HR + 1 BP + 1 Weight
    assert sync_res["platform"] == "android"
    assert sync_res["upserted_observations"] == 4
    assert sync_res["upserted_clinical_records"] == 1
    assert len(sync_res["red_flags"]) == 1
    assert sync_res["red_flags"][0]["triggered"] is True

    # Verify stored HealthResource rows and Android Health Connect provenance
    hr_stmt = select(HealthResource).where(
        HealthResource.profile_id == primary_profile.id,
        HealthResource.source_type == "companion",
    )
    hr_rows = list((await db_session.execute(hr_stmt)).scalars().all())
    assert len(hr_rows) == 5

    by_source_id = {row.source_id: row for row in hr_rows}
    steps_row = by_source_id["Observation:hc-steps-2026-03-22"]
    assert steps_row.data["valueQuantity"]["value"] == 8500
    assert (
        steps_row.data["source_display"]
        == "From Android Health Connect (Pixel 9 Pro (Health Connect)), 2026-03-22"
    )

    hr_row = by_source_id["Observation:hc-hr-2026-03-22"]
    assert hr_row.data["valueQuantity"]["value"] == 75.0

    imm_row = by_source_id["Immunization:hc-medres-imm-1"]
    assert imm_row.data["trust"] == "untrusted"
    assert (
        imm_row.data["source_display"]
        == "From Android Health Connect (Pixel 9 Pro (Health Connect)), 2026-01-20"
    )

    # 6. Revoke Android companion device and verify ConsentGrant is revoked
    revoked_dev = await revoke_companion_device(
        session=db_session,
        profile_id=primary_profile.id,
        device_id=device.id,
        actor_user_id=steward.id,
    )
    assert revoked_dev.status == "revoked"

    with pytest.raises(CompanionPairingError, match="Invalid or revoked"):
        await authenticate_companion_device(
            session=db_session,
            profile_id=primary_profile.id,
            device_token=completed["device_token"],
        )


@pytest.mark.asyncio
async def test_android_companion_rest_api_endpoints(
    db_session: AsyncSession,
    seeded_profiles: Tuple[User, Profile, Profile],
) -> None:
    """Verifies the FastAPI REST endpoints for Android companion pairing and Health Connect sync."""
    steward, primary_profile, _ = seeded_profiles

    app = FastAPI()
    app.include_router(companion_router)

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def _override_user() -> UserProfile:
        return UserProfile(
            id=steward.id,
            email=steward.email,
            username=steward.username,
            full_name=steward.full_name,
            role="steward",
            status="active",
            auth_provider="local",
            created_at=steward.created_at,
            updated_at=steward.updated_at,
        )

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user

    fp = "sha256:11:22:33:44:55:66:77:88:99:00:AA:BB:CC:DD:EE:FF:11:22:33:44:55:66:77:88:99:00:AA:BB:CC:DD:EE:FF"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        init_resp = await client.post(
            f"/profiles/{primary_profile.id}/companion/pair/initiate",
            json={
                "device_name": "Galaxy S25 Ultra",
                "platform": "android",
                "host": "127.0.0.1",
                "port": 8000,
                "cert_fingerprint_sha256": fp,
            },
        )
        assert init_resp.status_code == 201
        init_body = init_resp.json()
        assert init_body["platform"] == "android"

        comp_resp = await client.post(
            f"/profiles/{primary_profile.id}/companion/pair/complete",
            json={
                "device_id": init_body["device_id"],
                "pairing_code": init_body["pairing_code"],
                "client_cert_fingerprint_sha256": fp,
            },
        )
        assert comp_resp.status_code == 200
        token = comp_resp.json()["device_token"]
        assert token.startswith("cf-android-")

        sync_resp = await client.post(
            f"/profiles/{primary_profile.id}/companion/sync",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "health_connect_records": [
                    {
                        "recordType": "OxygenSaturationRecord",
                        "time": "2026-03-22T11:00:00Z",
                        "percentage": {"value": 98.0},
                    },
                    {
                        "recordType": "SleepSessionRecord",
                        "startTime": "2026-03-21T23:00:00Z",
                        "endTime": "2026-03-22T06:30:00Z",
                    },
                ]
            },
        )
        assert sync_resp.status_code == 200
        sync_body = sync_resp.json()
        assert sync_body["platform"] == "android"
        assert sync_body["upserted_observations"] == 2

    audit_res = await db_session.execute(
        select(AuditEventRecord).where(AuditEventRecord.profile_id == primary_profile.id)
    )
    assert len(list(audit_res.scalars().all())) >= 3
