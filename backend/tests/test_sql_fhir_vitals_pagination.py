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

"""Performance-contract and regression tests for SQL-pushed FHIR R4 & Vitals pagination (#341).

Verifies against a 500-Observation dataset (plus multi-version FHIR history) that:
1. `POST /profiles/{id}/vitals` and `record_vitals` populate `HealthResourceCoding` rows
   including blood-pressure component LOINC codes (`8480-6`, `8462-4`).
2. `list_profile_vitals` (`limit=20, offset=40` and `loinc_code="8480-6"`) pushes filtering,
   `SELECT COUNT(*)`, and `LIMIT/OFFSET` into SQL, materializing only the requested page rows
   (never all 500 rows) while preserving `_is_weight_hidden` privacy masking.
3. `fhir/operations.py` (`handle_fhir_read_resource`, `handle_fhir_search_resources`,
   `handle_fhir_resource_history`, `handle_fhir_patient_everything`, `handle_fhir_patient_summary`,
   `handle_fhir_upsert_resource`) materialize only bounded rows via SQL predicates.
4. `tools/fhir_tools.py` (`fhir_search_resources`, `fhir_get_patient_summary`,
   `fhir_get_observation_trends`) materialize only bounded rows and preserve untrusted taint.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict, Iterator, List, Optional, Set
import uuid

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from carefold.engine.tool_exec import TaintFlag, UntrustedResult
from carefold.fhir.operations import (
    FhirExecutionContext,
    handle_fhir_patient_everything,
    handle_fhir_patient_summary,
    handle_fhir_read_resource,
    handle_fhir_resource_history,
    handle_fhir_search_resources,
    handle_fhir_upsert_resource,
    reset_fhir_rate_limits_and_idempotency_cache,
)
from carefold.fhir.sql_pushdown import build_observation_coding_rows
from carefold.models.health import (
    HealthResource,
    HealthResourceCoding,
    HealthResourceVersion,
)
from carefold.routers.vitals import (
    VitalMeasurements,
    VitalsCreateRequest,
    create_profile_vitals,
    list_profile_vitals,
    set_profile_preference,
)
from carefold.scope.context import scope_context
from carefold.tools.fhir_tools import (
    execute_fhir_get_observation_trends,
    execute_fhir_get_patient_summary,
    execute_fhir_search_resources,
)
from carefold.tools.record_vitals import execute_record_vitals
from yarvelle_core.auth.ports import UserProfile
from yarvelle_core.config import settings
from yarvelle_core.db.base import Base
from yarvelle_core.db.models import Profile, User


@dataclass
class _DummyToolCtx:
    profile_id: Optional[str] = None
    user_id: Optional[str] = None
    session_factory: Any = None
    scopes: Optional[Set[str]] = None
    taint: TaintFlag = field(default_factory=lambda: TaintFlag(False))


@contextmanager
def _count_orm_loads(*models: Any) -> Iterator[Dict[str, int]]:
    """Counts SQLAlchemy ORM instance materializations per model class."""
    counts: Dict[str, int] = {m.__name__: 0 for m in models}
    listeners: List[Any] = []

    for model in models:
        name = model.__name__

        def _on_load(_target: Any, _context: Any, _name: str = name) -> None:
            counts[_name] += 1

        event.listen(model, "load", _on_load)
        listeners.append((model, _on_load))

    try:
        yield counts
    finally:
        for model, fn in listeners:
            event.remove(model, "load", fn)


@pytest.fixture
async def large_chart_env(tmp_path, monkeypatch):
    """Seeds an isolated SQLite DB with 500 Observation rows (BP, HR, Weight, Labs) + 25 history versions."""
    reset_fhir_rate_limits_and_idempotency_cache()
    monkeypatch.setattr(settings, "home_dir", tmp_path)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    user_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    base_ts = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)

    async with factory() as session:
        user = User(
            id=user_id,
            email="perf341@carefold.test",
            username="perf341_user",
            hashed_password="hashed_password",
            role="steward",
        )
        profile = Profile(
            id=profile_id,
            user_id=user_id,
            name="Perf Test Patient",
            relationship="self",
            is_primary=True,
        )
        set_profile_preference(profile_id, "hide_weight", False)
        session.add_all([user, profile])
        await session.flush()

        hr_rows: List[HealthResource] = []
        coding_rows: List[HealthResourceCoding] = []

        # Seed 500 Observations:
        # - i % 5 == 0 (100 rows): Blood pressure panel (85354-9 + components 8480-6 & 8462-4)
        # - i % 5 == 1 (100 rows): Heart rate (8867-4), every 10th untrusted import
        # - i % 5 == 2 (100 rows): Body weight (29463-7)
        # - i % 5 in (3, 4) (200 rows): Lab observation Hemoglobin A1c (4548-4), category="laboratory"
        for i in range(500):
            rid = f"obs-row-{i:04d}"
            logical_id = f"logical-obs-{i:04d}"
            eff_dt = base_ts + timedelta(hours=i)
            eff_iso = eff_dt.isoformat().replace("+00:00", "Z")
            source_type = "import" if (i % 5 == 1 and i % 10 == 1) else "manual"

            if i % 5 == 0:
                fhir_data: Dict[str, Any] = {
                    "resourceType": "Observation",
                    "id": logical_id,
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
                                "display": "Blood pressure panel with all children optional",
                            }
                        ]
                    },
                    "effectiveDateTime": eff_iso,
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
                            "valueQuantity": {"value": 115 + (i % 20), "unit": "mmHg"},
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
                            "valueQuantity": {"value": 75 + (i % 10), "unit": "mmHg"},
                        },
                    ],
                }
            elif i % 5 == 1:
                fhir_data = {
                    "resourceType": "Observation",
                    "id": logical_id,
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
                                "code": "8867-4",
                                "display": "Heart rate",
                            }
                        ]
                    },
                    "effectiveDateTime": eff_iso,
                    "valueQuantity": {"value": 68 + (i % 15), "unit": "/min"},
                }
                if source_type == "import":
                    fhir_data["_carefold_provenance"] = {
                        "trust": "untrusted",
                        "source_display": "External Portal Import",
                    }
            elif i % 5 == 2:
                fhir_data = {
                    "resourceType": "Observation",
                    "id": logical_id,
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
                                "code": "29463-7",
                                "display": "Body weight",
                            }
                        ]
                    },
                    "effectiveDateTime": eff_iso,
                    "valueQuantity": {"value": 72.5, "unit": "kg"},
                }
            else:
                fhir_data = {
                    "resourceType": "Observation",
                    "id": logical_id,
                    "status": "final",
                    "category": [
                        {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                    "code": "laboratory",
                                    "display": "Laboratory",
                                }
                            ]
                        }
                    ],
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": "4548-4",
                                "display": "Hemoglobin A1c/Hemoglobin.total in Blood",
                            }
                        ]
                    },
                    "effectiveDateTime": eff_iso,
                    "valueQuantity": {"value": 5.4, "unit": "%"},
                }

            hr_rows.append(
                HealthResource(
                    id=rid,
                    profile_id=profile_id,
                    resource_type="observation",
                    source_type=source_type,
                    source_id=f"Observation:{logical_id}",
                    status="active",
                    scope="health.clinical",
                    data=fhir_data,
                    effective_at=eff_dt,
                    recorded_at=eff_dt,
                    updated_at=eff_dt,
                )
            )
            # Leave the final 5 rows unindexed in health_resource_codings to test SQL JSON fallback!
            if i < 495:
                coding_rows.extend(
                    build_observation_coding_rows(
                        resource_id=rid,
                        profile_id=profile_id,
                        fhir_data=fhir_data,
                        resource_type="Observation",
                        scope="health.clinical",
                    )
                )

        session.add_all(hr_rows)
        session.add_all(coding_rows)

        # Seed 25 version snapshots on obs-row-0000 (logical-obs-0000)
        ver_rows: List[HealthResourceVersion] = []
        for v_num in range(1, 26):
            snap = dict(hr_rows[0].data)
            snap["meta"] = {"versionId": str(v_num)}
            ver_rows.append(
                HealthResourceVersion(
                    id=str(uuid.uuid4()),
                    resource_id="obs-row-0000",
                    profile_id=profile_id,
                    resource_type="Observation",
                    version_id=v_num,
                    operation="create" if v_num == 1 else "update",
                    content_hash=f"{v_num:064x}",
                    fhir_json=snap,
                    scope="health.clinical",
                )
            )
        session.add_all(ver_rows)
        await session.commit()

    try:
        yield {
            "engine": engine,
            "factory": factory,
            "user_id": user_id,
            "profile_id": profile_id,
        }
    finally:
        await engine.dispose()


def _make_user_profile(user_id: str) -> UserProfile:
    now = datetime.now(timezone.utc)
    return UserProfile(
        id=user_id,
        email="perf341@carefold.test",
        username="perf341_user",
        role="steward",
        status="active",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_vitals_write_paths_populate_coding_index(large_chart_env):
    """Both POST /profiles/{id}/vitals and record_vitals index top-level and component LOINC codes."""
    factory = large_chart_env["factory"]
    profile_id = large_chart_env["profile_id"]
    user_id = large_chart_env["user_id"]

    async with factory() as session:
        profile = (await session.execute(select(Profile).where(Profile.id == profile_id))).scalar_one()
        user_profile = _make_user_profile(user_id)
        created = await create_profile_vitals(
            profile_id=profile_id,
            payload=VitalsCreateRequest(
                vitals=VitalMeasurements(systolic=122, diastolic=78),
            ),
            profile=profile,
            db=session,
            user=user_profile,
        )
        created_hr = await create_profile_vitals(
            profile_id=profile_id,
            payload=VitalsCreateRequest(
                vitals=VitalMeasurements(heart_rate=64),
            ),
            profile=profile,
            db=session,
            user=user_profile,
        )
        await session.commit()

        codings = list(
            (
                await session.execute(
                    select(HealthResourceCoding).where(
                        HealthResourceCoding.resource_id.in_([created.id, created_hr.id])
                    )
                )
            ).scalars().all()
        )
        codes_set = {c.code for c in codings}
        assert "85354-9" in codes_set
        assert "8480-6" in codes_set
        assert "8462-4" in codes_set
        assert "8867-4" in codes_set

    # Verify record_vitals tool write path also populates HealthResourceCoding
    ctx = _DummyToolCtx(
        profile_id=profile_id,
        user_id=user_id,
        session_factory=factory,
        scopes={"health.clinical"},
    )
    with scope_context("health.clinical"):
        tool_res = await execute_record_vitals(
            {"vitals_data": {"systolic": 118, "diastolic": 76}},
            ctx,
        )
    assert tool_res.success is True
    rec_id = tool_res.output["resource_id"]
    async with factory() as session:
        tool_codings = list(
            (
                await session.execute(
                    select(HealthResourceCoding).where(HealthResourceCoding.resource_id == rec_id)
                )
            ).scalars().all()
        )
        tool_codes_set = {c.code for c in tool_codings}
        assert "8480-6" in tool_codes_set
        assert "8462-4" in tool_codes_set


@pytest.mark.asyncio
async def test_list_profile_vitals_sql_pushdown_and_weight_masking(large_chart_env):
    """list_profile_vitals loads <= limit ORM rows out of 500 and preserves component LOINC & weight masking."""
    factory = large_chart_env["factory"]
    profile_id = large_chart_env["profile_id"]
    user_id = large_chart_env["user_id"]
    user_profile = _make_user_profile(user_id)

    # 1. Unfiltered page (limit=20, offset=40) out of 500 rows -> loads <= 20 HealthResource instances
    async with factory() as session:
        profile = (await session.execute(select(Profile).where(Profile.id == profile_id))).scalar_one()
        with _count_orm_loads(HealthResource) as loads:
            resp = await list_profile_vitals(
                profile_id=profile_id,
                resource_type="observation",
                loinc_code=None,
                start_date=None,
                end_date=None,
                status_filter="active",
                limit=20,
                offset=40,
                profile=profile,
                db=session,
                user=user_profile,
            )
        assert resp.total == 500
        assert len(resp.items) == 20
        assert loads["HealthResource"] == 20

    # 2. Component LOINC filter (8480-6 systolic BP: 100 total rows across indexed + unindexed fallback)
    async with factory() as session:
        profile = (await session.execute(select(Profile).where(Profile.id == profile_id))).scalar_one()
        with _count_orm_loads(HealthResource) as loads:
            bp_resp = await list_profile_vitals(
                profile_id=profile_id,
                resource_type="observation",
                loinc_code="8480-6",
                start_date=None,
                end_date=None,
                status_filter="active",
                limit=10,
                offset=0,
                profile=profile,
                db=session,
                user=user_profile,
            )
        assert bp_resp.total == 100
        assert len(bp_resp.items) == 10
        assert loads["HealthResource"] == 10
        # Newest BP row is index 495 (unindexed fallback row!) -> proves fallback + index both work!
        assert bp_resp.items[0].id == "obs-row-0495"

    # 3. Privacy suppression (_is_weight_hidden) masks weight values without full-table scan
    set_profile_preference(profile_id, "hide_weight", True)
    try:
        async with factory() as session:
            profile = (await session.execute(select(Profile).where(Profile.id == profile_id))).scalar_one()
            with _count_orm_loads(HealthResource) as loads:
                wt_resp = await list_profile_vitals(
                    profile_id=profile_id,
                    resource_type="observation",
                    loinc_code="29463-7",
                    start_date=None,
                    end_date=None,
                    status_filter="active",
                    limit=5,
                    offset=0,
                    profile=profile,
                    db=session,
                    user=user_profile,
                )
            assert wt_resp.total == 100
            assert len(wt_resp.items) == 5
            assert loads["HealthResource"] == 5
            assert wt_resp.items[0].data["weight_hidden"] is True
            assert wt_resp.items[0].data["valueQuantity"]["value"] is None
    finally:
        set_profile_preference(profile_id, "hide_weight", False)


@pytest.mark.asyncio
async def test_fhir_operations_sql_pushdown_on_500_rows(large_chart_env):
    """FHIR R4 read, search, _history, $everything, $summary, and upsert materialize only bounded rows."""
    factory = large_chart_env["factory"]
    profile_id = large_chart_env["profile_id"]
    user_id = large_chart_env["user_id"]

    def _make_ctx(*, confirmed: bool = False) -> FhirExecutionContext:
        return FhirExecutionContext(
            profile_id=profile_id,
            user_id=user_id,
            scopes=frozenset({"health.clinical", "health.paperwork"}),
            base_url="http://localhost:8000/api/v1/fhir/r4",
            confirmed=confirmed,
            taint_flag=TaintFlag(False),
        )

    # 1. Read single resource -> loads exactly 1 HealthResource row
    async with factory() as session:
        with _count_orm_loads(HealthResource) as loads:
            read_res = await handle_fhir_read_resource(
                session,
                _make_ctx(),
                {"resource_type": "Observation", "id": "logical-obs-0250"},
            )
        assert read_res["resource"]["id"] == "logical-obs-0250"
        assert loads["HealthResource"] == 1

    # 2. Search Observations with code=8480-6, category=vital-signs, _count=12 -> loads 12 rows, total=100
    async with factory() as session:
        with _count_orm_loads(HealthResource) as loads:
            search_res = await handle_fhir_search_resources(
                session,
                _make_ctx(),
                {
                    "resource_type": "Observation",
                    "code": "http://loinc.org|8480-6",
                    "category": "vital-signs",
                    "_count": 12,
                },
            )
        assert search_res["total"] == 100
        assert len(search_res["entry"]) == 12
        assert loads["HealthResource"] == 12

    # 3. Search HR (8867-4) propagates taint when untrusted imported record lands in page
    async with factory() as session:
        ctx_taint = _make_ctx()
        with _count_orm_loads(HealthResource) as loads:
            hr_search = await handle_fhir_search_resources(
                session,
                ctx_taint,
                {"resource_type": "Observation", "code": "8867-4", "_count": 10},
            )
        assert hr_search["total"] == 100
        assert len(hr_search["entry"]) == 10
        assert loads["HealthResource"] == 10
        assert ctx_taint.taint_flag.is_tainted is True

    # 4. _history?_count=5 on 25-version resource -> loads 1 HealthResource + 5 HealthResourceVersion rows
    async with factory() as session:
        with _count_orm_loads(HealthResource, HealthResourceVersion) as loads:
            hist_res = await handle_fhir_resource_history(
                session,
                _make_ctx(),
                {"resource_type": "Observation", "id": "logical-obs-0000", "_count": 5},
            )
        assert hist_res["total"] == 25
        assert len(hist_res["entry"]) == 5
        assert loads["HealthResource"] == 1
        assert loads["HealthResourceVersion"] == 5

    # 5. Patient/$everything?_count=15 -> loads <= 16 HealthResource rows (1 canonical Patient + 15 page rows)
    async with factory() as session:
        with _count_orm_loads(HealthResource) as loads:
            everything_res = await handle_fhir_patient_everything(
                session,
                _make_ctx(),
                {"patient_id": profile_id, "_count": 15},
            )
        assert everything_res["total"] >= 500
        assert len(everything_res["entry"]) == 15
        assert loads["HealthResource"] <= 17

    # 6. Patient/$summary with limit_per_section=10 -> bounded section loads (<< 500 rows)
    async with factory() as session:
        with _count_orm_loads(HealthResource) as loads:
            ips_res = await handle_fhir_patient_summary(
                session,
                _make_ctx(),
                {"patient_id": profile_id, "limit_per_section": 10},
            )
        assert ips_res["resourceType"] == "Bundle"
        assert ips_res["type"] == "document"
        assert loads["HealthResource"] <= 25

    # 7. Upsert update on existing logical ID checks If-Match via SQL lookup without scanning 500 rows
    async with factory() as session:
        with _count_orm_loads(HealthResource) as loads:
            up_res = await handle_fhir_upsert_resource(
                session,
                _make_ctx(confirmed=True),
                {
                    "resource_type": "Observation",
                    "resource_id": "logical-obs-0100",
                    "resource": {
                        "resourceType": "Observation",
                        "id": "logical-obs-0100",
                        "status": "final",
                        "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
                        "valueQuantity": {"value": 71, "unit": "/min"},
                    },
                },
            )
        assert up_res["resource"]["id"] == "logical-obs-0100"
        assert loads["HealthResource"] <= 5


@pytest.mark.asyncio
async def test_fhir_mcp_tools_sql_pushdown_and_taint_preservation(large_chart_env):
    """MCP chart query tools load only bounded SQL rows out of 500 and preserve UntrustedResult taint."""
    factory = large_chart_env["factory"]
    profile_id = large_chart_env["profile_id"]
    user_id = large_chart_env["user_id"]

    # 1. fhir_search_resources(limit=15, category="laboratory") -> loads <= 15 rows out of 500
    ctx1 = _DummyToolCtx(
        profile_id=profile_id,
        user_id=user_id,
        session_factory=factory,
        scopes={"health.clinical"},
    )
    with scope_context("health.clinical"):
        with _count_orm_loads(HealthResource) as loads:
            res1 = await execute_fhir_search_resources(
                {"resource_type": "Observation", "category": "laboratory", "limit": 15},
                ctx1,
            )
    assert res1.success is True
    assert res1.output["count"] == 15
    assert loads["HealthResource"] <= 15

    # 2. fhir_get_observation_trends(loinc_or_code="8867-4", limit=12) -> loads <= 12 rows & taints result
    ctx2 = _DummyToolCtx(
        profile_id=profile_id,
        user_id=user_id,
        session_factory=factory,
        scopes={"health.clinical"},
    )
    with scope_context("health.clinical"):
        with _count_orm_loads(HealthResource) as loads:
            res2 = await execute_fhir_get_observation_trends(
                {"loinc_or_code": "8867-4", "limit": 12},
                ctx2,
            )
    assert res2.success is True
    assert res2.taint is True
    assert isinstance(res2.untrusted_result, UntrustedResult)
    assert ctx2.taint.is_tainted is True
    assert res2.output["count"] == 12
    assert loads["HealthResource"] <= 12

    # 3. fhir_get_patient_summary(limit_per_section=10) -> loads <= 20 rows out of 500
    ctx3 = _DummyToolCtx(
        profile_id=profile_id,
        user_id=user_id,
        session_factory=factory,
        scopes={"health.clinical"},
    )
    with scope_context("health.clinical"):
        with _count_orm_loads(HealthResource) as loads:
            res3 = await execute_fhir_get_patient_summary(
                {"limit_per_section": 10},
                ctx3,
            )
    expected_out = res3.value.output if isinstance(res3, UntrustedResult) else res3.output
    assert len(expected_out["recent_labs_and_vitals"]) == 10
    assert loads["HealthResource"] <= 20
