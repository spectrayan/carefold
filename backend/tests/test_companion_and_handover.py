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

"""Unit and API integration tests for iOS Companion Pairing/Sync (AU-62) and Teen Handover/Viewer Sections (AU-63)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import AsyncGenerator, Tuple

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from carefold.api.companion import router as companion_router
from carefold.api.deps import get_current_user, get_db
from carefold.api.handover import router as handover_router
from carefold.auth.ports import UserProfile
from carefold.clinical.handover import (
    VALID_VIEWER_SECTIONS,
    check_profile_section_access,
    execute_teen_handover,
    update_viewer_sections,
)
from carefold.companion import (
    CompanionPairingError,
    authenticate_companion_device,
    check_companion_mode_guard,
    complete_companion_pairing,
    ingest_companion_sync,
    initiate_companion_pairing,
    list_companion_reminders,
    revoke_companion_device,
)
from carefold.connectors.lifecycle import grant_connector_consent
from carefold.connectors.oauth import load_connection_tokens, store_connection_tokens
from carefold.db.base import Base
from carefold.db.models import (
    AuditEventRecord,
    CompanionDevice,
    Connection,
    ConsentGrant,
    Credential,
    HealthResource,
    Job,
    Profile,
    ProfileAccess,
    ProfileKey,
    Reminder,
    User,
    utc_now,
)
from carefold.vault import DecryptionError, decrypt_credential, get_or_create_dek


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Creates an isolated in-memory SQLite database session for companion and handover tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_household(
    db_session: AsyncSession,
) -> Tuple[User, User, User, Profile]:
    """Seeds a guardian user, a teen user, a viewer user, and a teen care profile."""
    now = utc_now()
    guardian = User(
        id="user-guardian-1",
        email="guardian@example.com",
        username="guardian",
        hashed_password="hashed-password",
        full_name="Priya Guardian",
        role="steward",
        status="active",
        auth_provider="local",
        created_at=now,
        updated_at=now,
    )
    teen = User(
        id="user-teen-1",
        email="leo@example.com",
        username="leo_teen",
        hashed_password="hashed-password",
        full_name="Leo Teen",
        role="member",
        status="active",
        auth_provider="local",
        created_at=now,
        updated_at=now,
    )
    viewer = User(
        id="user-viewer-1",
        email="grandma@example.com",
        username="grandma",
        hashed_password="hashed-password",
        full_name="Grandma Viewer",
        role="member",
        status="active",
        auth_provider="local",
        created_at=now,
        updated_at=now,
    )
    profile = Profile(
        id="profile-leo-1",
        user_id=guardian.id,
        name="Leo",
        relationship="child",
        role="guardian",
        date_of_birth="2010-05-15",
        is_primary=False,
        created_at=now,
        updated_at=now,
    )
    db_session.add_all([guardian, teen, viewer, profile])
    await db_session.commit()
    return guardian, teen, viewer, profile


# ============================================================================
# Section 1: Mode S Network Guard & QR Companion Pairing (AU-62)
# ============================================================================


@pytest.mark.asyncio
async def test_companion_mode_guard_blocks_disabled_auth_on_non_loopback(
    db_session: AsyncSession,
    seeded_household: Tuple[User, User, User, Profile],
) -> None:
    """Verifies Mode S guard blocks pairing when auth_provider='disabled' and bind_host is non-loopback."""
    guardian, _, _, profile = seeded_household

    with pytest.raises(PermissionError, match="non-loopback"):
        check_companion_mode_guard(auth_provider="disabled", bind_host="0.0.0.0")

    with pytest.raises(PermissionError, match="non-loopback"):
        await initiate_companion_pairing(
            session=db_session,
            user_id=guardian.id,
            profile_id=profile.id,
            device_name="Priya iPhone",
            host="192.168.1.50",
            port=8000,
            cert_fingerprint_sha256="AA:BB:CC:DD:EE:FF",
            auth_provider="disabled",
            bind_host="192.168.1.50",
        )

    # Loopback with disabled auth is permitted
    check_companion_mode_guard(auth_provider="disabled", bind_host="127.0.0.1")
    check_companion_mode_guard(auth_provider="disabled", bind_host="localhost")
    check_companion_mode_guard(auth_provider="disabled", bind_host="::1")

    # Non-loopback with local or oidc auth is permitted
    check_companion_mode_guard(auth_provider="local", bind_host="0.0.0.0")
    check_companion_mode_guard(auth_provider="oidc", bind_host="192.168.1.50")


@pytest.mark.asyncio
async def test_companion_pairing_pinned_tls_and_lifecycle(
    db_session: AsyncSession,
    seeded_household: Tuple[User, User, User, Profile],
) -> None:
    """Verifies QR initiation, pinned TLS fingerprint check, token issuance, ConsentGrant, and revocation."""
    guardian, _, _, profile = seeded_household
    server_fp = "e3:b0:item_four:42:98:fc:1c:14:9a:fb:f4:item_eight:99:6f:b9:24:27:ae:41:e4:64:9b:93:4c:a4:95:99:1b:78:52:b8:55"

    qr_payload = await initiate_companion_pairing(
        session=db_session,
        user_id=guardian.id,
        profile_id=profile.id,
        device_name="Priya iPhone 16 Pro",
        host="192.168.1.25",
        port=8443,
        cert_fingerprint_sha256=server_fp,
        allowed_categories=["vitals", "clinical_records", "reminders"],
        auth_provider="local",
        bind_host="192.168.1.25",
    )
    assert qr_payload["pairing_code"].startswith("cf-pair-")
    assert qr_payload["status"] == "pending_pair"
    device_id = qr_payload["device_id"]

    # Wrong certificate fingerprint must be rejected (MITM protection)
    with pytest.raises(CompanionPairingError, match="fingerprint"):
        await complete_companion_pairing(
            session=db_session,
            device_id=device_id,
            pairing_code=qr_payload["pairing_code"],
            client_cert_fingerprint_sha256="00:11:22:33:44:55:66:77",
        )

    # Wrong pairing code must be rejected
    with pytest.raises(CompanionPairingError, match="Invalid companion pairing code"):
        await complete_companion_pairing(
            session=db_session,
            device_id=device_id,
            pairing_code="cf-pair-wrong-code",
            client_cert_fingerprint_sha256=server_fp,
        )

    # Matching code + fingerprint succeeds
    paired = await complete_companion_pairing(
        session=db_session,
        device_id=device_id,
        pairing_code=qr_payload["pairing_code"],
        client_cert_fingerprint_sha256=server_fp.upper(),
    )
    assert paired["status"] == "active"
    assert paired["device_token"].startswith("cf-ios-")

    # Re-using the single-use pairing code must fail
    with pytest.raises(CompanionPairingError):
        await complete_companion_pairing(
            session=db_session,
            device_id=device_id,
            pairing_code=qr_payload["pairing_code"],
            client_cert_fingerprint_sha256=server_fp,
        )

    # Verify ConsentGrant was created for ios-companion
    cg_res = await db_session.execute(
        select(ConsentGrant).where(
            ConsentGrant.profile_id == profile.id,
            ConsentGrant.connector_id == "ios-companion",
        )
    )
    cg = cg_res.scalar_one_or_none()
    assert cg is not None
    assert cg.status == "active"
    assert cg.purpose == "companion_sync"
    assert set(cg.categories) == {"vitals", "clinical_records", "reminders"}

    # Authenticate with bearer token and verify cross-profile isolation
    auth_dev = await authenticate_companion_device(
        session=db_session,
        profile_id=profile.id,
        device_token=paired["device_token"],
    )
    assert auth_dev.id == device_id

    with pytest.raises(CompanionPairingError, match="scoped to profile"):
        await authenticate_companion_device(
            session=db_session,
            profile_id="other-profile-id",
            device_token=paired["device_token"],
        )

    # Revoke companion device
    revoked_dev = await revoke_companion_device(
        session=db_session,
        profile_id=profile.id,
        device_id=device_id,
        actor_user_id=guardian.id,
    )
    assert revoked_dev.status == "revoked"
    assert revoked_dev.token_hash is None

    await db_session.refresh(cg)
    assert cg.status == "revoked"

    with pytest.raises(CompanionPairingError):
        await authenticate_companion_device(
            session=db_session,
            profile_id=profile.id,
            device_token=paired["device_token"],
        )


# ============================================================================
# Section 2: HealthKit Observations, HKClinicalRecords & Reminders (AU-62)
# ============================================================================


@pytest.mark.asyncio
async def test_companion_sync_observations_clinical_records_and_red_flags(
    db_session: AsyncSession,
    seeded_household: Tuple[User, User, User, Profile],
) -> None:
    """Verifies HealthKit observation sync, AU-32 vitals red flags, HKClinicalRecord provenance, and PHI-safe reminders."""
    guardian, _, _, profile = seeded_household
    fp = "aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99:aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99"

    init_res = await initiate_companion_pairing(
        session=db_session,
        user_id=guardian.id,
        profile_id=profile.id,
        device_name="Leo iPhone",
        host="127.0.0.1",
        port=8000,
        cert_fingerprint_sha256=fp,
    )
    await complete_companion_pairing(
        session=db_session,
        device_id=init_res["device_id"],
        pairing_code=init_res["pairing_code"],
        client_cert_fingerprint_sha256=fp,
    )
    dev_res = await db_session.execute(
        select(CompanionDevice).where(CompanionDevice.id == init_res["device_id"])
    )
    device = dev_res.scalar_one()

    observations = [
        {
            "id": "hk-bp-1",
            "systolic": 186,
            "diastolic": 124,
            "effective_at": "2026-10-12T08:30:00Z",
        },
        {
            "id": "hk-spo2-1",
            "spo2": 87.0,
            "effective_at": "2026-10-12T08:35:00Z",
        },
    ]
    clinical_records = [
        {
            "resourceType": "Condition",
            "id": "cond-asthma-1",
            "code": {"text": "Mild intermittent childhood asthma"},
            "recordedDate": "2026-09-15",
        },
        {
            "resourceType": "Immunization",
            "id": "imm-flu-2026",
            "status": "completed",
            "vaccineCode": {"text": "Influenza, seasonal, injectable"},
            "occurrenceDateTime": "2026-10-01",
        },
    ]

    sync_result = await ingest_companion_sync(
        session=db_session,
        device=device,
        observations=observations,
        clinical_records=clinical_records,
    )
    assert sync_result["upserted_observations"] == 2
    assert sync_result["upserted_clinical_records"] == 2
    assert len(sync_result["red_flags"]) == 2
    flag_categories = {f["category"] for f in sync_result["red_flags"]}
    assert "bp_crisis_asymptomatic" in flag_categories
    assert "severe_hypoxemia" in flag_categories

    # Verify HKClinicalRecord provenance and untrusted tagging
    cond_hr_res = await db_session.execute(
        select(HealthResource).where(
            HealthResource.profile_id == profile.id,
            HealthResource.source_type == "companion",
            HealthResource.source_id == "Condition:cond-asthma-1",
        )
    )
    cond_hr = cond_hr_res.scalar_one()
    assert cond_hr.data["trust"] == "untrusted"
    assert cond_hr.data["source_display"] == "From iOS Health Records (Leo iPhone), 2026-09-15"

    # Seed a medication reminder containing sensitive PHI in title/description
    sensitive_reminder = Reminder(
        id="rem-sensitive-1",
        profile_id=profile.id,
        title="Take Albuterol HFA 90mcg 2 puffs for asthma",
        description="Prescribed by Dr. Patel for acute bronchospasm",
        category="medication",
        rrule="FREQ=DAILY;INTERVAL=1",
        timezone="America/Chicago",
        next_due_at=datetime.now(timezone.utc) + timedelta(hours=2),
        status="pending",
    )
    db_session.add(sensitive_reminder)
    await db_session.commit()

    reminders_payload = await list_companion_reminders(session=db_session, device=device)
    assert len(reminders_payload) == 1
    rem_item = reminders_payload[0]
    assert rem_item["phi_redacted"] is True
    assert rem_item["title"] == "Carefold Medication Reminder"
    assert "Albuterol" not in rem_item["title"]
    assert "Albuterol" not in rem_item["body"]
    assert "bronchospasm" not in rem_item["description"]


@pytest.mark.asyncio
async def test_companion_category_scoping_enforced(
    db_session: AsyncSession,
    seeded_household: Tuple[User, User, User, Profile],
) -> None:
    """Verifies a companion device scoped only to 'vitals' cannot sync clinical_records or poll reminders."""
    guardian, _, _, profile = seeded_household
    fp = "11:22:33:44:55:66:77:88:99:00:aa:bb:cc:dd:ee:ff:11:22:33:44:55:66:77:88:99:00:aa:bb:cc:dd:ee:ff"

    init_res = await initiate_companion_pairing(
        session=db_session,
        user_id=guardian.id,
        profile_id=profile.id,
        device_name="Vitals-Only Watch Phone",
        host="127.0.0.1",
        port=8000,
        cert_fingerprint_sha256=fp,
        allowed_categories=["vitals"],
    )
    await complete_companion_pairing(
        session=db_session,
        device_id=init_res["device_id"],
        pairing_code=init_res["pairing_code"],
        client_cert_fingerprint_sha256=fp,
    )
    dev_res = await db_session.execute(
        select(CompanionDevice).where(CompanionDevice.id == init_res["device_id"])
    )
    device = dev_res.scalar_one()

    with pytest.raises(CompanionPairingError, match="clinical_records"):
        await ingest_companion_sync(
            session=db_session,
            device=device,
            clinical_records=[{"resourceType": "Condition", "code": {"text": "Allergy"}}],
        )

    with pytest.raises(CompanionPairingError, match="reminders"):
        await list_companion_reminders(session=db_session, device=device)


# ============================================================================
# Section 3: Granular Viewer Section Scoping & Teen Handover (AU-63)
# ============================================================================


@pytest.mark.asyncio
async def test_granular_viewer_section_scoping(
    db_session: AsyncSession,
    seeded_household: Tuple[User, User, User, Profile],
) -> None:
    """Verifies granular viewer section permissions (E12.3) including 'connections' scoping and fallbacks."""
    guardian, _, viewer, profile = seeded_household

    # Owner always has access to all sections
    for sec in VALID_VIEWER_SECTIONS:
        assert await check_profile_section_access(db_session, profile, guardian.id, sec) is True

    # Unshared user has no access
    assert await check_profile_section_access(db_session, profile, viewer.id, "vitals") is False

    # Grant explicit sections ['appointments', 'reminders', 'connections'] to viewer
    grant = await update_viewer_sections(
        session=db_session,
        profile_id=profile.id,
        target_user_id=viewer.id,
        allowed_sections=["appointments", "reminders", "connections"],
        grantor_user_id=guardian.id,
    )
    assert grant.allowed_sections == ["appointments", "reminders", "connections"]

    assert await check_profile_section_access(db_session, profile, viewer.id, "appointments") is True
    assert await check_profile_section_access(db_session, profile, viewer.id, "reminders") is True
    assert await check_profile_section_access(db_session, profile, viewer.id, "connections") is True
    assert await check_profile_section_access(db_session, profile, viewer.id, "vitals") is False
    assert await check_profile_section_access(db_session, profile, viewer.id, "notes") is False

    # Invalid section name raises ValueError
    with pytest.raises(ValueError, match="Invalid viewer section"):
        await update_viewer_sections(
            session=db_session,
            profile_id=profile.id,
            target_user_id=viewer.id,
            allowed_sections=["vitals", "unknown_section"],
            grantor_user_id=guardian.id,
        )


@pytest.mark.asyncio
async def test_teen_handover_dek_rotation_and_credential_reencryption(
    db_session: AsyncSession,
    seeded_household: Tuple[User, User, User, Profile],
) -> None:
    """Verifies Teen Connection Handover (E12.4) keeps/revokes connections, rotates DEK, and re-encrypts tokens."""
    guardian, teen, _, profile = seeded_household
    test_kek = os.urandom(32)
    now = utc_now()

    # Create two active connections on the teen's profile under guardian stewardship
    conn_keep = Connection(
        id="conn-keep-withings",
        user_id=guardian.id,
        profile_id=profile.id,
        connector_id="withings",
        status="active",
        label="Withings Smart Scale",
        created_at=now,
        updated_at=now,
    )
    conn_revoke = Connection(
        id="conn-revoke-epic",
        user_id=guardian.id,
        profile_id=profile.id,
        connector_id="epic-smart",
        status="active",
        label="Pediatric Portal",
        created_at=now,
        updated_at=now,
    )
    db_session.add_all([conn_keep, conn_revoke])
    await db_session.flush()

    await grant_connector_consent(
        session=db_session,
        profile_id=profile.id,
        connector_id="withings",
        categories=["vitals"],
        scopes=["user.metrics"],
        allowed_hosts=["wbsapi.withings.net"],
        granted_by_user_id=guardian.id,
        connection_id=conn_keep.id,
    )
    await grant_connector_consent(
        session=db_session,
        profile_id=profile.id,
        connector_id="epic-smart",
        categories=["clinical_records"],
        scopes=["patient/Patient.read"],
        allowed_hosts=["fhir.epic.com"],
        granted_by_user_id=guardian.id,
        connection_id=conn_revoke.id,
    )

    # Schedule a sync job on conn_revoke to verify 4-step revoke cascade cancels it
    revoke_job = Job(
        id="job-sync-revoke-1",
        profile_id=profile.id,
        connection_id=conn_revoke.id,
        kind="sync",
        payload="{}",
        next_run_at=now,
        status="pending",
    )
    db_session.add(revoke_job)
    await db_session.commit()

    # Store encrypted credentials for both connections under initial DEK (version 1)
    keep_tokens = {"access_token": "withings-secret-access", "refresh_token": "withings-secret-refresh"}
    revoke_tokens = {"access_token": "epic-secret-access", "refresh_token": "epic-secret-refresh"}

    await store_connection_tokens(
        session=db_session,
        profile_id=profile.id,
        connection_id=conn_keep.id,
        user_id=guardian.id,
        token_payload=keep_tokens,
        kek=test_kek,
    )
    await store_connection_tokens(
        session=db_session,
        profile_id=profile.id,
        connection_id=conn_revoke.id,
        user_id=guardian.id,
        token_payload=revoke_tokens,
        kek=test_kek,
    )

    old_dek, old_dek_version = await get_or_create_dek(db_session, profile.id, test_kek)
    assert old_dek_version == 1

    # Execute teen handover: keep conn_keep, revoke conn_revoke
    handover_res = await execute_teen_handover(
        session=db_session,
        profile_id=profile.id,
        teen_user_id=teen.id,
        connection_decisions={
            conn_keep.id: "keep",
            conn_revoke.id: "revoke",
        },
        actor_user_id=guardian.id,
        kek=test_kek,
    )

    assert handover_res["profile_id"] == profile.id
    assert handover_res["new_steward_user_id"] == teen.id
    assert handover_res["new_dek_version"] == 2
    assert handover_res["kept_connections"] == [conn_keep.id]
    assert handover_res["revoked_connections"] == [conn_revoke.id]

    # 1. Verify Profile ownership and ProfileAccess promoted to teen
    await db_session.refresh(profile)
    assert profile.user_id == teen.id
    assert profile.role == "self"

    teen_access_res = await db_session.execute(
        select(ProfileAccess).where(
            ProfileAccess.profile_id == profile.id,
            ProfileAccess.user_id == teen.id,
        )
    )
    teen_access = teen_access_res.scalar_one()
    assert teen_access.role == "self"
    assert teen_access.access_level == "manage"

    # 2. Verify revoked connection underwent 4-step cascade
    await db_session.refresh(conn_revoke)
    assert conn_revoke.status == "revoked"
    rev_cred_res = await db_session.execute(
        select(Credential).where(Credential.connection_id == conn_revoke.id)
    )
    assert rev_cred_res.scalar_one_or_none() is None

    # 3. Verify ProfileKey DEK rotated to version 2 and kept credential re-encrypted with new DEK + new AAD
    new_dek, new_dek_version = await get_or_create_dek(db_session, profile.id, test_kek)
    assert new_dek_version == 2
    assert new_dek != old_dek

    keep_cred_res = await db_session.execute(
        select(Credential).where(Credential.connection_id == conn_keep.id)
    )
    keep_cred = keep_cred_res.scalar_one()
    assert keep_cred.dek_version == 2
    assert keep_cred.aad_binding == f"{profile.id}|{conn_keep.id}|2"
    assert keep_cred.user_id == teen.id

    # Old DEK must fail to decrypt the re-encrypted credential
    with pytest.raises(DecryptionError):
        decrypt_credential(
            old_dek,
            keep_cred.encrypted_blob,
            profile.id,
            conn_keep.id,
            1,
        )

    # Loading via load_connection_tokens with rotated DEK succeeds and returns exact tokens
    decrypted_tokens, _ = await load_connection_tokens(
        session=db_session,
        profile_id=profile.id,
        connection_id=conn_keep.id,
        kek=test_kek,
    )
    assert decrypted_tokens == keep_tokens

    # 4. Verify AuditEventRecord written for teen_handover
    audit_res = await db_session.execute(
        select(AuditEventRecord).where(
            AuditEventRecord.profile_id == profile.id,
            AuditEventRecord.event == "teen_handover",
        )
    )
    audit_row = audit_res.scalar_one_or_none()
    assert audit_row is not None
    assert audit_row.risk == "irreversible"


# ============================================================================
# Section 4: FastAPI REST Endpoint Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_companion_and_handover_rest_endpoints(
    db_session: AsyncSession,
    seeded_household: Tuple[User, User, User, Profile],
) -> None:
    """Verifies the REST endpoints in api/companion.py and api/handover.py end-to-end."""
    guardian, teen, viewer, profile = seeded_household

    app = FastAPI()
    app.include_router(companion_router, prefix="/api/v1")
    app.include_router(handover_router, prefix="/api/v1")

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    def _override_get_user() -> UserProfile:
        return UserProfile(
            id=guardian.id,
            email=guardian.email,
            username=guardian.username,
            full_name=guardian.full_name,
            role=guardian.role,
            status=guardian.status,
            auth_provider=guardian.auth_provider,
            created_at=guardian.created_at,
            updated_at=guardian.updated_at,
        )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_user

    fp = "aa:11:bb:22:cc:33:dd:44:ee:55:ff:66:00:77:88:99:aa:11:bb:22:cc:33:dd:44:ee:55:ff:66:00:77:88:99"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # 1. Initiate pairing
        r_init = await client.post(
            f"/api/v1/profiles/{profile.id}/companion/pair/initiate",
            json={
                "device_name": "Priya iPhone",
                "host": "127.0.0.1",
                "port": 8000,
                "cert_fingerprint_sha256": fp,
                "allowed_categories": ["vitals", "clinical_records", "reminders"],
            },
        )
        assert r_init.status_code == 201
        init_data = r_init.json()
        device_id = init_data["device_id"]

        # 2. Complete pairing
        r_comp = await client.post(
            f"/api/v1/profiles/{profile.id}/companion/pair/complete",
            json={
                "device_id": device_id,
                "pairing_code": init_data["pairing_code"],
                "client_cert_fingerprint_sha256": fp,
            },
        )
        assert r_comp.status_code == 200
        comp_data = r_comp.json()
        device_token = comp_data["device_token"]

        # 3. Sync using companion bearer token
        r_sync = await client.post(
            f"/api/v1/profiles/{profile.id}/companion/sync",
            headers={"Authorization": f"Bearer {device_token}"},
            json={
                "observations": [{"id": "obs-gluc-1", "blood_glucose": 49.0, "unit": "mg/dL"}],
                "clinical_records": [
                    {
                        "resourceType": "AllergyIntolerance",
                        "id": "allergy-peanut",
                        "code": {"text": "Peanut allergy"},
                        "recordedDate": "2026-08-20",
                    }
                ],
            },
        )
        assert r_sync.status_code == 200
        sync_body = r_sync.json()
        assert sync_body["upserted_observations"] == 1
        assert sync_body["upserted_clinical_records"] == 1
        assert sync_body["red_flags"][0]["category"] == "severe_hypoglycemia"

        # 4. List devices & poll reminders
        r_devs = await client.get(f"/api/v1/profiles/{profile.id}/companion/devices")
        assert r_devs.status_code == 200
        assert r_devs.json()["total"] == 1

        r_rems = await client.get(
            f"/api/v1/profiles/{profile.id}/companion/reminders",
            headers={"Authorization": f"Bearer {device_token}"},
        )
        assert r_rems.status_code == 200

        # 5. Update & get viewer sections
        r_put_sec = await client.put(
            f"/api/v1/profiles/{profile.id}/access/{viewer.id}/sections",
            json={"allowed_sections": ["vitals", "appointments"]},
        )
        assert r_put_sec.status_code == 200
        assert r_put_sec.json()["allowed_sections"] == ["vitals", "appointments"]

        r_get_sec = await client.get(
            f"/api/v1/profiles/{profile.id}/access/{viewer.id}/sections",
        )
        assert r_get_sec.status_code == 200
        assert r_get_sec.json()["allowed_sections"] == ["vitals", "appointments"]

        # 6. Execute teen handover
        r_handover = await client.post(
            f"/api/v1/profiles/{profile.id}/handover",
            json={
                "teen_user_id": teen.id,
                "connection_decisions": {},
            },
        )
        assert r_handover.status_code == 200
        assert r_handover.json()["new_steward_user_id"] == teen.id

        # 7. Delete/revoke companion device
        # Switch user to new steward (teen) after handover
        app.dependency_overrides[get_current_user] = lambda: UserProfile(
            id=teen.id,
            email=teen.email,
            username=teen.username,
            full_name=teen.full_name,
            role=teen.role,
            status=teen.status,
            auth_provider=teen.auth_provider,
            created_at=teen.created_at,
            updated_at=teen.updated_at,
        )
        r_del = await client.delete(
            f"/api/v1/profiles/{profile.id}/companion/devices/{device_id}",
        )
        assert r_del.status_code == 200
        assert r_del.json()["revoked"] is True
