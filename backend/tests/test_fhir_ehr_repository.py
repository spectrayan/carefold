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

"""Integration, migration, isolation, and security tests for the FHIR R4 EHR repository (#282)."""

from __future__ import annotations

import io
import json
import os
import uuid

import alembic.command
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from carefold.config import settings
from carefold.db.base import Base
from carefold.db.models import (
    AuditEventRecord,
    HealthResource,
    HealthResourceCoding,
    HealthResourceReference,
    HealthResourceVersion,
    Profile,
    User,
)
from carefold.db.session import (
    get_pack_alembic_config,
    resolve_health_migrations_dir,
    run_all_migrations,
)
from carefold.fhir import (
    delete_fhir_resource_with_history,
    ensure_canonical_patient_resource,
    get_inbound_references,
    get_outbound_references,
    get_resource_version_history,
    search_resources_by_coding,
    upsert_fhir_resource_with_history,
)
from carefold.importers import (
    commit_import_batch,
    confirm_batch,
    stage_import,
)
from carefold.scope.context import ScopeViolationError, scope_context
from carefold.vault.crypto import decrypt, encrypt
from carefold.vault.dek import compute_aad_binding, get_or_create_dek


@pytest.fixture
async def repo_db_env(tmp_path, monkeypatch):
    """Creates an isolated async SQLite database with two household profiles for repository tests."""
    monkeypatch.setattr(settings, "home_dir", tmp_path)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    user_id = str(uuid.uuid4())
    profile_a_id = str(uuid.uuid4())
    profile_b_id = str(uuid.uuid4())

    async with factory() as session:
        user = User(
            id=user_id,
            email="steward@example.com",
            username="steward_user",
            hashed_password="hashed_password",
            role="steward",
        )
        profile_a = Profile(
            id=profile_a_id,
            user_id=user_id,
            name="Maya Patel",
            relationship="self",
            role="self",
            date_of_birth="1988-11-23",
            is_primary=True,
        )
        profile_b = Profile(
            id=profile_b_id,
            user_id=user_id,
            name="Arjun Patel",
            relationship="spouse",
            role="adult_member",
            date_of_birth="1986-05-14",
            is_primary=False,
        )
        session.add_all([user, profile_a, profile_b])
        await session.commit()

    yield {
        "engine": engine,
        "factory": factory,
        "user_id": user_id,
        "profile_a_id": profile_a_id,
        "profile_b_id": profile_b_id,
    }
    await engine.dispose()


def test_alembic_migration_0002_sqlite_and_postgresql_ddl():
    """Verifies health_0002_fhir_ehr_repository upgrade/downgrade on SQLite and offline PostgreSQL DDL."""
    # 1. SQLite upgrade -> downgrade -> upgrade verification
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        run_all_migrations(conn, enabled_packs=["health"])
        conn.commit()

        insp = inspect(conn)
        tables = set(insp.get_table_names())
        for tbl in (
            "health_resource_versions",
            "health_resource_codings",
            "health_resource_references",
        ):
            assert tbl in tables
            col_names = {c["name"] for c in insp.get_columns(tbl)}
            assert "profile_id" in col_names
            assert "scope" in col_names

        ver_uqs = {uq["name"] for uq in insp.get_unique_constraints("health_resource_versions")}
        assert "uq_health_resource_versions_resource_version" in ver_uqs

        cod_uqs = {uq["name"] for uq in insp.get_unique_constraints("health_resource_codings")}
        assert "uq_health_resource_codings_res_path_sys_code" in cod_uqs

        ref_uqs = {uq["name"] for uq in insp.get_unique_constraints("health_resource_references")}
        assert "uq_health_resource_references_edge" in ref_uqs

        # Downgrade to health_0001_baseline and verify clean removal
        mig_dir = resolve_health_migrations_dir()
        cfg_health = get_pack_alembic_config(mig_dir, connection=conn, version_table="alembic_version_health")
        alembic.command.downgrade(cfg_health, "health_0001_baseline")
        conn.commit()

        tables_down = set(inspect(conn).get_table_names())
        assert "health_resource_versions" not in tables_down
        assert "health_resource_codings" not in tables_down
        assert "health_resource_references" not in tables_down
        assert "health_resources" in tables_down

        # Re-upgrade to head
        alembic.command.upgrade(cfg_health, "head")
        conn.commit()
        tables_up = set(inspect(conn).get_table_names())
        assert "health_resource_versions" in tables_up
        assert "health_resource_codings" in tables_up
        assert "health_resource_references" in tables_up

    # 2. PostgreSQL dialect DDL compilation check (upgrade and downgrade)
    mig_dir = resolve_health_migrations_dir()
    cfg = Config()
    cfg.set_main_option("script_location", str(mig_dir))
    script = ScriptDirectory.from_config(cfg)

    pg_up_buf = io.StringIO()

    def _upgrade_pg(rev, context):
        return script._upgrade_revs("health_0002_fhir_ehr_repository", "health_0001_baseline")

    with EnvironmentContext(
        cfg,
        script,
        fn=_upgrade_pg,
        as_sql=True,
        starting_rev="health_0001_baseline",
        destination_rev="health_0002_fhir_ehr_repository",
    ) as env_ctx:
        env_ctx.configure(
            dialect_name="postgresql",
            output_buffer=pg_up_buf,
            version_table="alembic_version_health",
        )
        with env_ctx.begin_transaction():
            env_ctx.run_migrations()

    pg_up_sql = pg_up_buf.getvalue()
    assert "CREATE TABLE health_resource_versions" in pg_up_sql
    assert "CREATE TABLE health_resource_codings" in pg_up_sql
    assert "CREATE TABLE health_resource_references" in pg_up_sql
    assert "TIMESTAMP WITH TIME ZONE" in pg_up_sql
    assert "BOOLEAN DEFAULT false NOT NULL" in pg_up_sql

    pg_down_buf = io.StringIO()

    def _downgrade_pg(rev, context):
        return script._downgrade_revs("health_0001_baseline", "health_0002_fhir_ehr_repository")

    with EnvironmentContext(
        cfg,
        script,
        fn=_downgrade_pg,
        as_sql=True,
        starting_rev="health_0002_fhir_ehr_repository",
        destination_rev="health_0001_baseline",
    ) as env_ctx:
        env_ctx.configure(
            dialect_name="postgresql",
            output_buffer=pg_down_buf,
            version_table="alembic_version_health",
        )
        with env_ctx.begin_transaction():
            env_ctx.run_migrations()

    pg_down_sql = pg_down_buf.getvalue()
    assert "DROP TABLE health_resource_references" in pg_down_sql
    assert "DROP TABLE health_resource_codings" in pg_down_sql
    assert "DROP TABLE health_resource_versions" in pg_down_sql


@pytest.mark.asyncio
async def test_version_ordering_content_hash_stability_and_tombstone_lifecycle(repo_db_env):
    """Verifies monotonic version snapshots (1, 2, 3), stable content_hash, and delete tombstone history."""
    factory = repo_db_env["factory"]
    profile_id = repo_db_env["profile_a_id"]
    user_id = repo_db_env["user_id"]

    obs_v1 = {
        "resourceType": "Observation",
        "id": "obs-ldl-1",
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "13457-7",
                    "display": "Cholesterol in LDL [Mass/volume] in Serum or Plasma by calculation",
                }
            ],
            "text": "LDL Cholesterol",
        },
        "subject": {"reference": f"Patient/{profile_id}"},
        "effectiveDateTime": "2026-03-01T08:30:00Z",
        "valueQuantity": {"value": 112.0, "unit": "mg/dL"},
    }

    async with factory() as session:
        # 1. Initial create -> version 1
        hr1, ver1, created1 = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="Observation",
            fhir_data=obs_v1,
            source_type="file",
            source_ref="batch-1",
            source_id="Observation:obs-ldl-1",
            actor_user_id=user_id,
        )
        await session.commit()

        assert created1 is True
        assert ver1.version_id == 1
        assert ver1.operation == "create"
        assert hr1.data["meta"]["versionId"] == "1"
        assert ver1.fhir_json["meta"]["versionId"] == "1"
        hash_v1 = hr1.content_hash

        # 2. Re-upsert identical clinical payload -> version 2, identical canonical content_hash
        hr2, ver2, created2 = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="Observation",
            fhir_data=obs_v1,
            source_type="file",
            source_ref="batch-1",
            source_id="Observation:obs-ldl-1",
            actor_user_id=user_id,
        )
        await session.commit()

        assert created2 is False
        assert hr2.id == hr1.id
        assert ver2.version_id == 2
        assert ver2.operation == "update"
        assert hr2.data["meta"]["versionId"] == "2"
        assert hr2.content_hash == hash_v1
        assert ver2.content_hash == hash_v1

        # 3. Update clinical value (112.0 -> 94.0 mg/dL) -> version 3, new content_hash
        obs_v3 = dict(obs_v1, valueQuantity={"value": 94.0, "unit": "mg/dL"})
        hr3, ver3, created3 = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="Observation",
            fhir_data=obs_v3,
            source_type="file",
            source_ref="batch-1",
            source_id="Observation:obs-ldl-1",
            actor_user_id=user_id,
        )
        await session.commit()

        assert created3 is False
        assert ver3.version_id == 3
        assert ver3.operation == "update"
        assert hr3.data["meta"]["versionId"] == "3"
        assert hr3.content_hash != hash_v1

        # Active coding search finds the resource
        found = await search_resources_by_coding(
            session, profile_id, system="http://loinc.org", code="13457-7"
        )
        assert [r.id for r in found] == [hr1.id]

        # 4. Delete resource -> version 4 (operation="delete", status="tombstone")
        del_ver = await delete_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_id=hr1.id,
            actor_user_id=user_id,
        )
        await session.commit()

        assert del_ver is not None
        assert del_ver.version_id == 4
        assert del_ver.operation == "delete"

        # Active coding search no longer returns tombstoned resource
        found_after_del = await search_resources_by_coding(
            session, profile_id, system="http://loinc.org", code="13457-7"
        )
        assert found_after_del == []

        # Full immutable version history (1, 2, 3, 4) remains intact and ordered
        history = await get_resource_version_history(session, profile_id, hr1.id)
        assert [v.version_id for v in history] == [1, 2, 3, 4]
        assert [v.operation for v in history] == ["create", "update", "update", "delete"]
        assert history[0].fhir_json["valueQuantity"]["value"] == 112.0
        assert history[2].fhir_json["valueQuantity"]["value"] == 94.0


@pytest.mark.asyncio
async def test_transaction_rollback_atomicity_leaves_zero_orphan_rows(repo_db_env):
    """Verifies that rolling back a transaction mid-upsert leaves zero rows across all 4 tables."""
    factory = repo_db_env["factory"]
    profile_id = repo_db_env["profile_a_id"]

    async with factory() as session:
        await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="Condition",
            fhir_data={
                "resourceType": "Condition",
                "id": "cond-rollback-1",
                "code": {
                    "coding": [{"system": "http://snomed.info/sct", "code": "38341003", "display": "Hypertension"}]
                },
                "subject": {"reference": f"Patient/{profile_id}"},
            },
            source_type="file",
            source_ref="rollback-batch",
            source_id="Condition:cond-rollback-1",
        )
        # Simulate failure before commit and roll back
        await session.rollback()

    async with factory() as verify_session:
        for model_cls in (
            HealthResource,
            HealthResourceVersion,
            HealthResourceCoding,
            HealthResourceReference,
        ):
            rows = (
                await verify_session.execute(
                    select(model_cls).where(model_cls.profile_id == profile_id)
                )
            ).scalars().all()
            assert rows == [], f"Expected zero rows in {model_cls.__tablename__} after rollback"


@pytest.mark.asyncio
async def test_cross_profile_and_cross_scope_isolation_and_reference_graph(repo_db_env):
    """Verifies profile isolation, health.clinical vs health.paperwork ScopeContext isolation, and reference graph."""
    factory = repo_db_env["factory"]
    profile_a = repo_db_env["profile_a_id"]
    profile_b = repo_db_env["profile_b_id"]
    user_id = repo_db_env["user_id"]

    bundle_payload = json.dumps({
        "resourceType": "Bundle",
        "id": "bundle-ehr-graph-282",
        "type": "collection",
        "entry": [
            {
                "fullUrl": "urn:uuid:aaaa1111-1111-4111-8111-111111111111",
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-source-maya",
                    "identifier": [{"system": "http://hospital.example.org/mrn", "value": "MRN-7788"}],
                    "name": [{"family": "Patel", "given": ["Maya"]}],
                    "birthDate": "1988-11-23",
                },
            },
            {
                "fullUrl": "urn:uuid:bbbb2222-2222-4222-8222-222222222222",
                "resource": {
                    "resourceType": "Encounter",
                    "id": "enc-cardio-1",
                    "status": "finished",
                    "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
                    "type": [
                        {
                            "coding": [
                                {"system": "http://www.ama-assn.org/go/cpt", "code": "99214", "display": "Office visit"}
                            ]
                        }
                    ],
                    "subject": {"reference": "urn:uuid:aaaa1111-1111-4111-8111-111111111111"},
                    "period": {"start": "2026-03-10T09:00:00Z"},
                },
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-bp-1",
                    "status": "final",
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": "85354-9", "display": "Blood pressure panel"}]
                    },
                    "subject": {"reference": "urn:uuid:aaaa1111-1111-4111-8111-111111111111"},
                    "encounter": {"reference": "urn:uuid:bbbb2222-2222-4222-8222-222222222222"},
                    "effectiveDateTime": "2026-03-10T09:15:00Z",
                    "component": [
                        {
                            "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic BP"}]},
                            "valueQuantity": {"value": 122, "unit": "mmHg"},
                        },
                        {
                            "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic BP"}]},
                            "valueQuantity": {"value": 78, "unit": "mmHg"},
                        },
                    ],
                },
            },
            {
                "resource": {
                    "resourceType": "DiagnosticReport",
                    "id": "diag-cardio-1",
                    "status": "final",
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": "24331-1", "display": "Lipid panel"}]
                    },
                    "subject": {"reference": "Patient/pat-source-maya"},
                    "encounter": {"reference": "Encounter/enc-cardio-1"},
                    "result": [{"reference": "Observation/obs-bp-1"}],
                    "effectiveDateTime": "2026-03-10T10:00:00Z",
                },
            },
            {
                "resource": {
                    "resourceType": "Coverage",
                    "id": "cov-ppo-1",
                    "status": "active",
                    "type": {
                        "coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "HIP"}]
                    },
                    "beneficiary": {"reference": "Patient/pat-source-maya"},
                    "payor": [{"display": "Aetna Health"}],
                },
            },
            {
                "resource": {
                    "resourceType": "ExplanationOfBenefit",
                    "id": "eob-ppo-1",
                    "status": "active",
                    "type": {
                        "coding": [{"system": "http://terminology.hl7.org/CodeSystem/claim-type", "code": "professional"}]
                    },
                    "use": "claim",
                    "patient": {"reference": "Patient/pat-source-maya"},
                    "created": "2026-03-12T00:00:00Z",
                    "insurer": {"display": "Aetna Health"},
                    "provider": {"display": "City General"},
                    "outcome": "complete",
                    "insurance": [{"focal": True, "coverage": {"reference": "Coverage/cov-ppo-1"}}],
                },
            },
        ],
    })

    async with factory() as session:
        batch = await stage_import(
            session=session,
            profile_id=profile_a,
            filename="ehr_graph.json",
            content=bundle_payload,
            source_name="City General EHR",
            user_id=user_id,
        )
        commit_res = await confirm_batch(
            session=session,
            profile_id=profile_a,
            batch_id=batch.id,
            actor_user_id=user_id,
        )
        # 6 bundle resources + 1 synthesized Provenance = 7 committed resources
        assert commit_res["committed_count"] == 7
        assert len(commit_res["version_ids"]) == 7

        # 1. Verify Profile B sees ZERO resources, versions, codings, or references from Profile A
        b_codings = await search_resources_by_coding(session, profile_b, code="8480-6")
        assert b_codings == []
        b_inbound = await get_inbound_references(session, profile_b, target_type="Patient")
        assert b_inbound == []

        # 2. Verify multi-coding index on Observation component (8480-6 and 8462-4 both find obs-bp-1)
        bp_by_sys = await search_resources_by_coding(
            session, profile_a, system="http://loinc.org", code="8480-6"
        )
        bp_by_dia = await search_resources_by_coding(
            session, profile_a, system="http://loinc.org", code="8462-4"
        )
        assert len(bp_by_sys) == 1
        assert bp_by_sys[0].id == bp_by_dia[0].id
        obs_hr = bp_by_sys[0]

        # 3. Verify intra-batch reference graph linking (DiagnosticReport -> Observation & Encounter -> Patient)
        diag_list = await search_resources_by_coding(
            session, profile_a, system="http://loinc.org", code="24331-1"
        )
        assert len(diag_list) == 1
        diag_hr = diag_list[0]

        diag_out_refs = await get_outbound_references(session, profile_a, diag_hr.id)
        refs_by_field = {r.reference_field: r for r in diag_out_refs}
        assert refs_by_field["result"].target_type == "Observation"
        assert refs_by_field["result"].target_id == "obs-bp-1"
        assert refs_by_field["result"].target_resource_id == obs_hr.id

        # Patient reference points to canonical Patient/{profile_a} and resolves target_resource_id to the Patient row
        pat_hr = (
            await session.execute(
                select(HealthResource).where(
                    HealthResource.profile_id == profile_a,
                    HealthResource.resource_type == "Patient",
                )
            )
        ).scalar_one()
        assert pat_hr.data["id"] == profile_a
        assert refs_by_field["subject"].target_type == "Patient"
        assert refs_by_field["subject"].target_id == profile_a
        assert refs_by_field["subject"].target_resource_id == pat_hr.id

        # Inbound references to Patient/{profile_a} include Encounter, Observation, DiagnosticReport, Coverage, EOB
        inbound_to_pat = await get_inbound_references(
            session, profile_a, target_type="Patient", target_id=profile_a
        )
        inbound_source_types = {r.source_type for r in inbound_to_pat}
        assert {
            "Encounter",
            "Observation",
            "DiagnosticReport",
            "Coverage",
            "ExplanationOfBenefit",
        }.issubset(inbound_source_types)

        # 4. Verify ScopeContext isolation: health.clinical vs health.paperwork
        with scope_context(
            scope="health.clinical",
            active_scopes=frozenset({"health.clinical"}),
            granted_scopes=frozenset({"health.clinical"}),
        ):
            clin_resources = (
                await session.execute(
                    select(HealthResource).where(HealthResource.profile_id == profile_a)
                )
            ).scalars().all()
            clin_types = {r.resource_type for r in clin_resources}
            assert "Observation" in clin_types
            assert "DiagnosticReport" in clin_types
            assert "Coverage" not in clin_types
            assert "ExplanationOfBenefit" not in clin_types

            # Searching paperwork coding 'HIP' under health.clinical returns empty
            hip_in_clinical = await search_resources_by_coding(session, profile_a, code="HIP")
            assert hip_in_clinical == []

            # Attempting to write a Coverage (health.paperwork) resource while restricted to health.clinical raises ScopeViolationError
            with pytest.raises(ScopeViolationError):
                await upsert_fhir_resource_with_history(
                    session,
                    profile_id=profile_a,
                    resource_type="Coverage",
                    fhir_data={
                        "resourceType": "Coverage",
                        "id": "cov-forbidden",
                        "status": "active",
                        "beneficiary": {"reference": f"Patient/{profile_a}"},
                        "payor": [{"display": "Payor"}],
                    },
                )
            await session.rollback()

        with scope_context(
            scope="health.paperwork",
            active_scopes=frozenset({"health.paperwork"}),
            granted_scopes=frozenset({"health.paperwork"}),
        ):
            pw_resources = (
                await session.execute(
                    select(HealthResource).where(HealthResource.profile_id == profile_a)
                )
            ).scalars().all()
            pw_types = {r.resource_type for r in pw_resources}
            assert pw_types == {"Coverage", "ExplanationOfBenefit"}

            # Searching clinical LOINC 8480-6 under health.paperwork returns empty
            bp_in_paperwork = await search_resources_by_coding(session, profile_a, code="8480-6")
            assert bp_in_paperwork == []

            # Searching paperwork coding 'HIP' under health.paperwork succeeds
            hip_in_paperwork = await search_resources_by_coding(session, profile_a, code="HIP")
            assert len(hip_in_paperwork) == 1
            assert hip_in_paperwork[0].resource_type == "Coverage"


@pytest.mark.asyncio
async def test_no_plaintext_phi_leak_in_indexes_or_audit_and_dek_compatibility(repo_db_env):
    """Verifies free-text narrative PHI never leaks into coding/reference indexes or audit logs, and tests DEK compatibility."""
    factory = repo_db_env["factory"]
    profile_id = repo_db_env["profile_a_id"]
    user_id = repo_db_env["user_id"]

    sensitive_narrative = "SENSITIVE_NOTE_SSN_999_88_7777_MAYA_PATEL_PRIVATE_DIARY"
    sensitive_display_name = "Dr. Secret Clinician Private Display"

    bundle = json.dumps({
        "resourceType": "Bundle",
        "id": "bundle-phi-boundary",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-phi-check",
                    "status": "final",
                    "code": {
                        "coding": [
                            {"system": "http://loinc.org", "code": "29463-7", "display": "Body Weight"}
                        ],
                        "text": sensitive_narrative,
                    },
                    "subject": {
                        "reference": f"Patient/{profile_id}",
                        "display": sensitive_display_name,
                    },
                    "valueString": sensitive_narrative,
                    "text": {
                        "status": "generated",
                        "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{sensitive_narrative}</div>',
                    },
                }
            }
        ],
    })

    async with factory() as session:
        batch = await stage_import(
            session=session,
            profile_id=profile_id,
            filename="phi_check.json",
            content=bundle,
            source_name="Portal",
            user_id=user_id,
        )
        await commit_import_batch(
            session=session,
            profile_id=profile_id,
            batch_id=batch.id,
            actor_user_id=user_id,
        )

        # 1. Inspect all HealthResourceCoding rows: must NOT contain sensitive_narrative
        codings = (
            await session.execute(
                select(HealthResourceCoding).where(HealthResourceCoding.profile_id == profile_id)
            )
        ).scalars().all()
        assert len(codings) == 1
        coding_dump = json.dumps([
            {"path": c.element_path, "system": c.system, "code": c.code, "display": c.display}
            for c in codings
        ])
        assert sensitive_narrative not in coding_dump
        assert sensitive_display_name not in coding_dump

        # 2. Inspect all HealthResourceReference rows: must NOT contain sensitive_display_name
        refs = (
            await session.execute(
                select(HealthResourceReference).where(HealthResourceReference.profile_id == profile_id)
            )
        ).scalars().all()
        ref_dump = json.dumps([
            {"field": r.reference_field, "target_type": r.target_type, "target_id": r.target_id, "raw": r.raw_reference}
            for r in refs
        ])
        assert sensitive_narrative not in ref_dump
        assert sensitive_display_name not in ref_dump

        # 3. Inspect AuditEventRecord: detail_redacted must NOT contain sensitive_narrative
        audits = (
            await session.execute(
                select(AuditEventRecord).where(AuditEventRecord.profile_id == profile_id)
            )
        ).scalars().all()
        assert len(audits) == 1
        assert sensitive_narrative not in (audits[0].detail_redacted or "")
        assert sensitive_display_name not in (audits[0].detail_redacted or "")

        # 4. Verify canonical Patient anchor helper and DEK envelope encryption compatibility
        anchor = await ensure_canonical_patient_resource(session, profile_id, actor_user_id=user_id)
        await session.commit()
        assert anchor.resource_type == "Patient"
        assert anchor.data["id"] == profile_id

        kek = os.urandom(32)
        dek, dek_version = await get_or_create_dek(session, profile_id, kek)
        aad = compute_aad_binding(profile_id, f"HealthResource:{anchor.id}", dek_version)
        plaintext_bytes = json.dumps(anchor.data, sort_keys=True).encode("utf-8")
        ciphertext = encrypt(dek, plaintext_bytes, aad=aad)
        assert sensitive_narrative.encode("utf-8") not in ciphertext
        assert b"Maya Patel" not in ciphertext
        decrypted = json.loads(decrypt(dek, ciphertext, aad=aad).decode("utf-8"))
        assert decrypted["id"] == profile_id


@pytest.mark.asyncio
async def test_patient_mismatch_quarantine_and_multi_patient_rejection(repo_db_env):
    """Verifies wrong-patient entries are quarantined and never committed, and repository rejects unverified patient refs."""
    factory = repo_db_env["factory"]
    profile_a = repo_db_env["profile_a_id"]
    profile_b = repo_db_env["profile_b_id"]
    user_id = repo_db_env["user_id"]

    # Bundle with 2 distinct Patient entries -> ambiguous multi-patient bundle
    multi_patient_bundle = json.dumps({
        "resourceType": "Bundle",
        "id": "bundle-ambiguous-patients",
        "type": "collection",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "pat-1", "name": [{"family": "One"}]}},
            {"resource": {"resourceType": "Patient", "id": "pat-2", "name": [{"family": "Two"}]}},
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-ambig-1",
                    "status": "final",
                    "code": {"coding": [{"system": "http://loinc.org", "code": "29463-7"}]},
                    "subject": {"reference": "Patient/pat-1"},
                }
            },
        ],
    })

    async with factory() as session:
        batch = await stage_import(
            session=session,
            profile_id=profile_a,
            filename="ambiguous.json",
            content=multi_patient_bundle,
            source_name="Portal",
            user_id=user_id,
        )
        summary_data = json.loads(batch.summary_json)
        assert summary_data["clinical_records"] == 0
        assert summary_data["quarantined_count"] == 3
        with pytest.raises(ValueError, match="ambiguous multiple patient identities"):
            await confirm_batch(
                session=session,
                profile_id=profile_a,
                batch_id=batch.id,
                actor_user_id=user_id,
            )

        # Direct repository call with wrong expected_patient_id raises ValueError
        with pytest.raises(ValueError, match="unverified patient"):
            await upsert_fhir_resource_with_history(
                session,
                profile_id=profile_a,
                resource_type="Observation",
                fhir_data={
                    "resourceType": "Observation",
                    "id": "obs-wrong-patient",
                    "status": "final",
                    "code": {"coding": [{"system": "http://loinc.org", "code": "29463-7"}]},
                    "subject": {"reference": f"Patient/{profile_b}"},
                },
                expected_patient_id=profile_a,
                strict_patient_matching=True,
            )

