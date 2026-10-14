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

"""Unit, tool, and REST API tests for Preventive Care & Immunisation Engine (AU-36)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from carefold.api.deps import get_db
from carefold.api.preventive import router as preventive_router
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.clinical.preventive import (
    ADULT_FRAMING,
    DEFAULT_ADULT_AGE_MONTHS,
    PEDIATRIC_FRAMING,
    calculate_age_months,
    create_preventive_action,
    evaluate_preventive_care,
    get_profile_schedule_source,
    load_preventive_rules,
    set_profile_schedule_source,
    update_preventive_record,
    validate_preventive_rule,
)
from carefold.config import settings
from carefold.db.models import (
    Appointment,
    AuditEventRecord,
    HealthResource,
    Note,
    PreventiveRecord,
    Profile,
    ProfileAccess,
    Reminder,
)
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.engine.tool_exec import ToolContext
from carefold.loaders.skill_loader import load_skill
from carefold.main import app
from carefold.tools.preventive import (
    execute_check_preventive_care,
    execute_update_preventive_status,
)


def run_async(coro):
    return asyncio.run(coro)


def _ensure_preventive_router_mounted():
    routes = [getattr(r, "path", "") for r in app.routes]
    if not any("/preventive" in p for p in routes):
        app.include_router(preventive_router, prefix="/api")


# ============================================================================
# Section 1: Skill Pack & Cited YAML Rule Validation Tests
# ============================================================================


def test_preventive_skill_manifest_and_yaml_rules_load():
    """Verifies skills/preventive-care/SKILL.md and both YAML rule packs load with full citations."""
    repo_root = Path(__file__).resolve().parents[2]
    skill_dir = repo_root / "skills" / "preventive-care"
    manifest = load_skill(skill_dir)
    assert manifest.id == "preventive-care"
    assert manifest.risk_class.value == "clinical_assist"

    rules = load_preventive_rules(skills_dir=repo_root / "skills")
    assert len(rules) >= 20

    adult_rules = [r for r in rules if r["target_age_min_months"] >= 216]
    peds_rules = [r for r in rules if r["target_age_min_months"] < 216]
    assert len(adult_rules) >= 8
    assert len(peds_rules) >= 12

    aap_only = [r for r in rules if r["schedule_variant"] == "aap_2026"]
    cdc_only = [r for r in rules if r["schedule_variant"] == "cdc"]
    assert len(aap_only) >= 1
    assert len(cdc_only) >= 1

    for rule in rules:
        assert rule["source"]
        assert rule["citation_url"].startswith("https://")
        assert rule["reviewed_by"]
        assert rule["reviewed_at"] == "2026-10-13"
        assert len(rule["codes"]) >= 1


def test_validate_preventive_rule_rejects_missing_citations():
    """Verifies that rules lacking source, citation_url, reviewed_by, or reviewed_at raise ValueError."""
    valid_rule = {
        "id": "test-rule-1",
        "title": "Test Screening",
        "category": "screening",
        "target_age_min_months": 240,
        "target_age_max_months": 600,
        "sex": "any",
        "schedule_variant": "all",
        "interval_months": 12,
        "codes": ["1234-5"],
        "clinical_summary": "Routine screening. Discuss with your clinician.",
        "source": "USPSTF",
        "citation_url": "https://www.uspreventiveservicestaskforce.org/",
        "reviewed_by": "Carefold Clinical Safety Working Group",
        "reviewed_at": "2026-10-13",
    }
    validated = validate_preventive_rule(valid_rule)
    assert validated["id"] == "test-rule-1"

    for field_name in ("source", "citation_url", "reviewed_by", "reviewed_at"):
        broken = dict(valid_rule)
        broken[field_name] = ""
        with pytest.raises(ValueError, match=field_name):
            validate_preventive_rule(broken)


# ============================================================================
# Section 2: Domain Service Evaluation & Schedule Source Tests
# ============================================================================


@pytest.fixture
def preventive_db_env(monkeypatch):
    """Provides an isolated in-memory database and session factory for preventive care tests."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    run_async(init_db(engine))
    session_factory = get_session_factory(engine)
    monkeypatch.setattr("carefold.tools.preventive.get_session_factory", lambda: session_factory)
    return {"session_factory": session_factory}


def test_calculate_age_months_defaults_to_35_years_when_none():
    """Verifies missing date_of_birth defaults to 420 months (35 years)."""
    assert calculate_age_months(None) == DEFAULT_ADULT_AGE_MONTHS
    assert calculate_age_months("") == DEFAULT_ADULT_AGE_MONTHS

    ref = datetime(2026, 10, 13, tzinfo=timezone.utc)
    assert calculate_age_months("2025-10-13", reference_date=ref) == 12
    assert calculate_age_months("2016-10-13", reference_date=ref) == 120


def test_evaluate_adult_and_pediatric_schedules(preventive_db_env):
    """Verifies adult USPSTF screening evaluation and pediatric AAP vs CDC schedule switching."""
    session_factory = preventive_db_env["session_factory"]
    now = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)

    async def _scenario():
        async with session_factory() as session:
            # 1. Adult 52yo profile (DOB 1974-05-01)
            adult = Profile(
                id=str(uuid.uuid4()),
                name="Adult Patient",
                relationship="self",
                role="self",
                date_of_birth="1974-05-01",
                created_at=now,
                updated_at=now,
            )
            # 2. Child 10yo profile (DOB 2016-05-01 -> ~125 months)
            child = Profile(
                id=str(uuid.uuid4()),
                name="Child Patient",
                relationship="child",
                role="guardian",
                date_of_birth="2016-05-01",
                created_at=now,
                updated_at=now,
            )
            session.add_all([adult, child])
            await session.commit()

            # Evaluate adult female vs male
            res_female = await evaluate_preventive_care(
                session, adult, sex="female", reference_date=now
            )
            assert res_female["is_pediatric"] is False
            female_ids = {i["rule_id"] for i in res_female["items"]}
            assert "uspstf-colorectal-screening" in female_ids
            assert "uspstf-breast-cancer-mammography" in female_ids
            assert "uspstf-cervical-cancer-screening" in female_ids
            assert all(i["framing"] == ADULT_FRAMING for i in res_female["items"])

            res_male = await evaluate_preventive_care(
                session, adult, sex="male", reference_date=now
            )
            male_ids = {i["rule_id"] for i in res_male["items"]}
            assert "uspstf-colorectal-screening" in male_ids
            assert "uspstf-breast-cancer-mammography" not in male_ids
            assert "uspstf-cervical-cancer-screening" not in male_ids

            # Evaluate 10yo child under default aap_2026 vs cdc
            res_aap = await evaluate_preventive_care(
                session, child, reference_date=now
            )
            assert res_aap["is_pediatric"] is True
            assert res_aap["schedule_source"] == "aap_2026"
            aap_ids = {i["rule_id"] for i in res_aap["items"]}
            assert "peds-hpv-aap-early" in aap_ids
            assert "peds-hpv-cdc-routine" not in aap_ids
            assert all(i["framing"] == PEDIATRIC_FRAMING for i in res_aap["items"])

            # Switch profile preference to CDC
            await set_profile_schedule_source(session, child.id, "cdc", actor_user_id="user-1")
            stored_source = await get_profile_schedule_source(session, child.id)
            assert stored_source == "cdc"

            res_cdc = await evaluate_preventive_care(
                session, child, reference_date=now
            )
            assert res_cdc["schedule_source"] == "cdc"
            cdc_ids = {i["rule_id"] for i in res_cdc["items"]}
            assert "peds-hpv-aap-early" not in cdc_ids

    run_async(_scenario())


def test_health_resource_matching_and_override_actions(preventive_db_env):
    """Verifies HealthResource code matching, PreventiveRecord status overrides, and 1-click actions."""
    session_factory = preventive_db_env["session_factory"]
    now = datetime.now(timezone.utc)

    async def _scenario():
        async with session_factory() as session:
            prof = Profile(
                id=str(uuid.uuid4()),
                name="Screening Patient",
                relationship="self",
                role="self",
                date_of_birth="1975-01-15",
                created_at=now,
                updated_at=now,
            )
            session.add(prof)

            # Add an active HealthResource matching colorectal screening code 45378
            hr = HealthResource(
                id=str(uuid.uuid4()),
                profile_id=prof.id,
                resource_type="observation",
                source_type="manual",
                data={"code": {"coding": [{"code": "45378", "display": "Colonoscopy"}]}},
                status="active",
                effective_at=now - timedelta(days=60),
                recorded_at=now,
            )
            session.add(hr)
            await session.commit()

            eval_res = await evaluate_preventive_care(session, prof, reference_date=now)
            by_id = {i["rule_id"]: i for i in eval_res["items"]}
            assert by_id["uspstf-colorectal-screening"]["status"] == "completed"
            assert by_id["uspstf-colorectal-screening"]["matched_resource_id"] == hr.id

            # Override hypertension screening to declined
            rec = await update_preventive_record(
                session,
                profile_id=prof.id,
                rule_id="uspstf-hypertension-screening",
                status="declined",
                notes="Monitoring with home cuff",
                actor_user_id="user-1",
            )
            assert rec.status == "declined"

            # Convert diabetes screening into a Reminder
            rem_action = await create_preventive_action(
                session,
                profile_id=prof.id,
                rule_id="uspstf-diabetes-screening",
                action_type="reminder",
                actor_user_id="user-1",
            )
            assert rem_action["action_type"] == "reminder"
            assert rem_action["external_ref"].startswith("reminder:")

            # Convert lipid screening into a prep question (no appointment -> creates Note)
            note_action = await create_preventive_action(
                session,
                profile_id=prof.id,
                rule_id="uspstf-lipid-statin-prevention",
                action_type="prep_question",
                actor_user_id="user-1",
            )
            assert note_action["action_type"] == "prep_question"
            assert note_action["note_id"] is not None
            assert note_action["external_ref"].startswith("note:")

            # Create an upcoming appointment and convert lung screening into appointment prep_notes
            appt = Appointment(
                id=str(uuid.uuid4()),
                profile_id=prof.id,
                title="Annual Wellness Visit",
                start_time=now + timedelta(days=5),
                end_time=now + timedelta(days=5, hours=1),
                status="scheduled",
                created_at=now,
                updated_at=now,
            )
            session.add(appt)
            await session.commit()

            appt_action = await create_preventive_action(
                session,
                profile_id=prof.id,
                rule_id="uspstf-lung-cancer-ldct",
                action_type="prep_question",
                appointment_id=appt.id,
                actor_user_id="user-1",
            )
            assert appt_action["appointment_id"] == appt.id
            assert "Lung Cancer" in appt_action["preparation_notes"]

            # Verify AuditEventRecord entries were persisted
            audits = (
                await session.execute(
                    select(AuditEventRecord).where(AuditEventRecord.profile_id == prof.id)
                )
            ).scalars().all()
            assert len(audits) >= 4

    run_async(_scenario())


# ============================================================================
# Section 3: Tool Execution & Fail-Closed Security Tests
# ============================================================================


def test_preventive_tools_fail_closed_and_execution(preventive_db_env):
    """Verifies check_preventive_care and update_preventive_status fail closed without profile_id."""
    session_factory = preventive_db_env["session_factory"]
    now = datetime.now(timezone.utc)

    # 1. Fail-closed checks
    res_none = run_async(execute_check_preventive_care({}, None))
    assert res_none.success is False
    assert "Security violation" in res_none.error

    res_upd_none = run_async(execute_update_preventive_status({"rule_id": "uspstf-diabetes-screening", "status": "completed"}, None))
    assert res_upd_none.success is False
    assert "Security violation" in res_upd_none.error

    # 2. Create profile and execute tools
    prof_id = str(uuid.uuid4())

    async def _seed():
        async with session_factory() as session:
            session.add(
                Profile(
                    id=prof_id,
                    name="Tool Test Patient",
                    relationship="self",
                    role="self",
                    date_of_birth="1980-06-15",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

    run_async(_seed())
    ctx = ToolContext(profile_id=prof_id, user_id="user-1")

    check_res = run_async(execute_check_preventive_care({"schedule_source": "aap_2026"}, ctx))
    assert check_res.success is True
    assert check_res["schedule_source"] == "aap_2026"
    assert len(check_res["items"]) >= 3

    upd_res = run_async(
        execute_update_preventive_status(
            {
                "rule_id": "uspstf-hypertension-screening",
                "status": "completed",
                "notes": "Checked at clinic 118/76",
            },
            ctx,
        )
    )
    assert upd_res.success is True
    assert upd_res["status"] == "completed"
    assert upd_res["external_ref"].startswith("preventive_record:")


# ============================================================================
# Section 4: REST API & Access Control Tests
# ============================================================================


@pytest.fixture
def preventive_api_env(monkeypatch):
    """Sets up an isolated FastAPI test environment with RBAC users for preventive care endpoints."""
    _ensure_preventive_router_mounted()

    async def _setup():
        engine = create_db_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = get_session_factory(engine)
        auth_adapter = SqlAuthAdapter(session_factory=session_factory)

        monkeypatch.setattr(settings, "auth_provider", "local")
        set_auth_port(auth_adapter)

        alice = await auth_adapter.register_user(
            email="alice_prev@test.local",
            username="alice_prev",
            password="Password123!",
            full_name="Alice Steward",
            role="member",
            auth_provider="local",
        )
        alice_session = await auth_adapter.create_session(alice.id)

        charlie = await auth_adapter.register_user(
            email="charlie_prev@test.local",
            username="charlie_prev",
            password="Password123!",
            full_name="Charlie Viewer",
            role="member",
            auth_provider="local",
        )
        charlie_session = await auth_adapter.create_session(charlie.id)

        dan = await auth_adapter.register_user(
            email="dan_prev@test.local",
            username="dan_prev",
            password="Password123!",
            full_name="Dan Paperwork",
            role="member",
            auth_provider="local",
        )
        dan_session = await auth_adapter.create_session(dan.id)

        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            prof = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Leo Child",
                relationship="child",
                role="guardian",
                date_of_birth="2016-06-01",
                is_primary=False,
                created_at=now,
                updated_at=now,
            )
            session.add(prof)
            session.add(
                ProfileAccess(
                    id=str(uuid.uuid4()),
                    profile_id=prof.id,
                    user_id=charlie.id,
                    access_level="view_clinical",
                    granted_by=alice.id,
                    granted_at=now,
                )
            )
            session.add(
                ProfileAccess(
                    id=str(uuid.uuid4()),
                    profile_id=prof.id,
                    user_id=dan.id,
                    access_level="view_paperwork",
                    granted_by=alice.id,
                    granted_at=now,
                )
            )
            await session.commit()
            return {
                "session_factory": session_factory,
                "profile_id": prof.id,
                "alice_token": alice_session.token,
                "charlie_token": charlie_session.token,
                "dan_token": dan_session.token,
            }

    env_data = run_async(_setup())
    session_factory = env_data["session_factory"]

    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield env_data
    finally:
        app.dependency_overrides.pop(get_db, None)
        reset_auth_port()


def test_preventive_rest_api_lifecycle_and_permissions(preventive_api_env):
    """Tests GET/PATCH/PUT/POST preventive care API endpoints and RBAC permissions."""
    client = TestClient(app)
    prof_id = preventive_api_env["profile_id"]
    alice_h = {"Authorization": f"Bearer {preventive_api_env['alice_token']}"}
    charlie_h = {"Authorization": f"Bearer {preventive_api_env['charlie_token']}"}
    dan_h = {"Authorization": f"Bearer {preventive_api_env['dan_token']}"}

    # 1. GET preventive checklist (Alice & Charlie allowed; Dan blocked)
    res_get = client.get(f"/api/profiles/{prof_id}/preventive", headers=alice_h)
    assert res_get.status_code == 200
    body = res_get.json()
    assert body["is_pediatric"] is True
    assert body["schedule_source"] == "aap_2026"
    assert any(i["rule_id"] == "peds-hpv-aap-early" for i in body["items"])

    res_charlie = client.get(f"/api/profiles/{prof_id}/preventive", headers=charlie_h)
    assert res_charlie.status_code == 200

    res_dan = client.get(f"/api/profiles/{prof_id}/preventive", headers=dan_h)
    assert res_dan.status_code == 403

    # 2. PUT preventive-settings to switch schedule_source to 'cdc'
    put_res = client.put(
        f"/api/profiles/{prof_id}/preventive-settings",
        json={"schedule_source": "cdc"},
        headers=alice_h,
    )
    assert put_res.status_code == 200
    assert put_res.json()["schedule_source"] == "cdc"

    # Charlie (view_clinical) cannot PUT settings
    charlie_put = client.put(
        f"/api/profiles/{prof_id}/preventive-settings",
        json={"schedule_source": "aap_2026"},
        headers=charlie_h,
    )
    assert charlie_put.status_code == 403

    # 3. PATCH rule status
    patch_res = client.patch(
        f"/api/profiles/{prof_id}/preventive/peds-influenza-annual",
        json={"status": "completed", "notes": "Flu shot given at fall clinic"},
        headers=alice_h,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "completed"
    assert patch_res.json()["external_ref"].startswith("preventive_record:")

    # 4. POST 1-click action conversion (reminder & prep_question)
    act_rem = client.post(
        f"/api/profiles/{prof_id}/preventive/peds-influenza-annual/action",
        json={"action_type": "reminder"},
        headers=alice_h,
    )
    assert act_rem.status_code == 201
    assert act_rem.json()["action_type"] == "reminder"
    assert act_rem.json()["reminder_id"]

    act_q = client.post(
        f"/api/profiles/{prof_id}/preventive/peds-influenza-annual/action",
        json={"action_type": "prep_question"},
        headers=alice_h,
    )
    assert act_q.status_code == 201
    assert act_q.json()["action_type"] == "prep_question"
    assert act_q.json()["note_id"]
