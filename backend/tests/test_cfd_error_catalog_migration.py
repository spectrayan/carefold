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

"""Comprehensive verification suite for Issue #340 (CFD Error Catalog & HTTPException Migration).

Covers:
1. `backend/src/carefold/resources/errors.yaml` `CFD-XXX-YYY` catalog integrity, category/block
   alignment, boolean `retryable`, preservation of the #346 foundation codes, and strict code + slug
   disjointness from `yarvelle_core`'s `YRV-XXX-YYY` catalog.
2. AST scan across `backend/src/carefold/` proving zero `HTTPException` imports/raises in
   Carefold-owned source modules and zero raw internal exception string interpolation on 500 raises.
3. Non-FHIR REST endpoints returning RFC 7807 `ProblemDetails` (`application/problem+json`) with
   `code` and `retryable`, and zero internal exception leak on simulated 500 failures.
4. `/api/v1/fhir/r4/*` routes returning valid HL7 FHIR R4 `OperationOutcome` (`application/fhir+json`)
   containing `CFD-XXX-YYY` coding under `issue[].details.coding` without replacing FHIR media types.
5. REST <-> MCP / Tool error parity: identical `code` and `retryable` metadata across REST routes,
   Carefold tool executors (`execute_tool_call`), and MCP Database Toolbox FHIR operations.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any, Dict

from fastapi.testclient import TestClient
from fhir.resources.R4B.operationoutcome import OperationOutcome as FhirOperationOutcome
import httpx
import pytest
import yaml

import carefold
from carefold.clinical.db_hooks import register_carefold_db_toolbox
from carefold.clinical.school_ics import create_school_ics_feed
from carefold.errors import CarefoldToolError, YarvelleError, register_carefold_error_catalog
from carefold.fhir.operations import FhirOperationError
from carefold.scope.context import scope_context
from carefold.tools.appointments import execute_update_appointment_status
from carefold.tools.connectors import execute_sync_school_ics
from carefold.tools.fhir_tools import execute_fhir_search_resources
from carefold.tools.imports import execute_commit_clinical_import
from carefold.tools.mcp_db_toolbox import get_db_toolbox
from carefold.tools.record_vitals import execute_record_vitals
from yarvelle_core.engine.tool_exec import ToolContext, execute_tool_call
from yarvelle_core.errors import get_error_catalog

CAREFOLD_SRC = Path(carefold.__file__).resolve().parent
ERRORS_YAML_PATH = CAREFOLD_SRC / "resources" / "errors.yaml"
CFD_CODE_RE = re.compile(r"^CFD-([1-9]00)-(\d{3})$")

EXPECTED_CATEGORY_BY_BLOCK = {
    "100": "validation",
    "200": "configuration",
    "300": "auth",
    "400": "vault",
    "500": "storage",
    "600": "connector",
    "700": "mcp_tools",
    "800": "workflow",
    "900": "internal",
}


def _ensure_primary_profile(client: TestClient) -> str:
    # Seed local disabled-auth steward User + primary profile if fresh DB
    client.get("/api/v1/fhir/r4/Observation")
    resp = client.get("/api/v1/profiles")
    assert resp.status_code == 200, resp.text
    items = resp.json()
    if isinstance(items, dict):
        items = items.get("profiles") or items.get("items") or []
    assert items, "Expected primary profile to be provisioned"
    return items[0]["id"]


# ============================================================================
# 1. Catalog Integrity & YRV Disjointness
# ============================================================================


def test_cfd_error_catalog_yaml_uniqueness_and_yrv_disjointness() -> None:
    """`errors.yaml` defines unique `CFD-XXX-YYY` codes disjoint from `YRV-*` codes and slugs."""
    register_carefold_error_catalog()
    raw = yaml.safe_load(ERRORS_YAML_PATH.read_text(encoding="utf-8"))
    assert raw["apiVersion"] == "yarvelle.errors/v1"
    assert raw["prefix"] == "CFD"
    assert raw["type_base_uri"] == "https://errors.carefold.dev"

    entries: Dict[str, Dict[str, Any]] = raw["errors"]
    assert len(entries) >= 35

    seen_codes: set[str] = set()
    catalog = get_error_catalog()
    yrv_codes = {c for c in catalog._by_code if c.startswith("YRV-")}
    yrv_slugs = {
        spec.slug for code, spec in catalog._by_code.items() if code.startswith("YRV-")
    }

    for slug, spec_dict in entries.items():
        code = spec_dict["code"]
        match = CFD_CODE_RE.match(code)
        assert match is not None, f"Invalid CFD code format for slug {slug!r}: {code!r}"
        block = match.group(1)
        assert spec_dict["category"] == EXPECTED_CATEGORY_BY_BLOCK[block], (
            f"{code} ({slug}) category {spec_dict['category']!r} != {EXPECTED_CATEGORY_BY_BLOCK[block]!r}"
        )
        assert code not in seen_codes, f"Duplicate CFD code: {code}"
        seen_codes.add(code)
        assert code not in yrv_codes
        assert slug not in yrv_slugs
        assert isinstance(spec_dict["retryable"], bool)
        assert isinstance(spec_dict["http_status"], int)
        assert catalog.get(code).slug == slug

    # Foundation #346 codes remain intact
    for required_code in (
        "CFD-100-001",
        "CFD-300-001",
        "CFD-300-002",
        "CFD-500-001",
        "CFD-600-001",
        "CFD-800-001",
        "CFD-800-002",
        "CFD-900-001",
    ):
        assert required_code in seen_codes


# ============================================================================
# 2. Static AST Audit: Zero HTTPException & Zero Raw 500 Exception Leaks
# ============================================================================


def test_zero_http_exception_and_zero_500_detail_leak_across_carefold_src() -> None:
    """Every Carefold Python module is free of `HTTPException` and raw 500 `str(err)` detail leaks."""
    http_exc_hits: list[str] = []
    raw_500_detail_hits: list[str] = []

    internal_500_codes = {
        "CFD-900-001",
        "CFD-900-002",
        "CFD-900-003",
        "YRV-800-004",
        "YRV-800-010",
        "YRV-900-001",
    }

    register_carefold_error_catalog()
    catalog = get_error_catalog()
    valid_error_kwargs = {"context", "cause", "detail", "headers", "instance", "catalog"}
    bad_kwarg_hits: list[str] = []
    unresolved_code_hits: list[str] = []

    for py_file in sorted(CAREFOLD_SRC.rglob("*.py")):
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
        rel = py_file.relative_to(CAREFOLD_SRC)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "HTTPException":
                        http_exc_hits.append(f"{rel}:{node.lineno}")
            elif isinstance(node, ast.Name) and node.id == "HTTPException":
                http_exc_hits.append(f"{rel}:{node.lineno}")
            elif isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                if func_name in ("YarvelleError", "CarefoldToolError"):
                    bad_kws = [
                        kw.arg
                        for kw in node.keywords
                        if kw.arg is not None and kw.arg not in valid_error_kwargs
                    ]
                    if bad_kws:
                        bad_kwarg_hits.append(f"{rel}:{node.lineno} ({bad_kws})")
                    if node.args:
                        first_arg = node.args[0]
                        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                            try:
                                catalog.resolve(first_arg.value)
                            except Exception:
                                unresolved_code_hits.append(
                                    f"{rel}:{node.lineno} ({first_arg.value})"
                                )
                            if first_arg.value in internal_500_codes:
                                for kw in node.keywords:
                                    if kw.arg == "detail" and not isinstance(kw.value, ast.Constant):
                                        raw_500_detail_hits.append(
                                            f"{rel}:{node.lineno} ({first_arg.value})"
                                        )

    assert http_exc_hits == [], f"Residual HTTPException usages found: {http_exc_hits}"
    assert bad_kwarg_hits == [], f"Invalid YarvelleError keyword arguments: {bad_kwarg_hits}"
    assert unresolved_code_hits == [], f"Unregistered catalog codes referenced: {unresolved_code_hits}"
    assert raw_500_detail_hits == [], (
        f"Non-constant 500 detail expressions risk leaking internal exception strings: {raw_500_detail_hits}"
    )


# ============================================================================
# 3. Non-FHIR REST RFC 7807 ProblemDetails & Zero 500 Exception Leak
# ============================================================================


def test_non_fhir_rest_endpoints_emit_rfc7807_problem_details(client: TestClient) -> None:
    """Migrated Carefold REST routes return `application/problem+json` with `code` and `retryable`."""
    profile_id = _ensure_primary_profile(client)

    # 1) Unpaired systolic-only vitals -> 400 CFD-100-002
    r_vitals = client.post(
        f"/api/v1/profiles/{profile_id}/vitals",
        json={"vitals": {"systolic": 128.0}},
    )
    assert r_vitals.status_code == 400
    assert r_vitals.headers["content-type"].startswith("application/problem+json")
    body_vitals = r_vitals.json()
    assert body_vitals["code"] == "CFD-100-002"
    assert body_vitals["retryable"] is False
    assert body_vitals["status"] == 400
    assert body_vitals["type"].startswith("https://errors.carefold.dev/")
    assert "Both systolic and diastolic" in body_vitals["detail"]

    # 2) Duplicate vitals source_id -> 409 CFD-500-009
    ok_vitals = client.post(
        f"/api/v1/profiles/{profile_id}/vitals",
        json={
            "vitals": {"heart_rate": 72.0},
            "source_type": "device",
            "source_ref": "withings",
            "source_id": "dup-reading-340",
        },
    )
    assert ok_vitals.status_code == 201, ok_vitals.text
    dup_vitals = client.post(
        f"/api/v1/profiles/{profile_id}/vitals",
        json={
            "vitals": {"heart_rate": 72.0},
            "source_type": "device",
            "source_ref": "withings",
            "source_id": "dup-reading-340",
        },
    )
    assert dup_vitals.status_code == 409
    assert dup_vitals.headers["content-type"].startswith("application/problem+json")
    assert dup_vitals.json()["code"] == "CFD-500-009"
    assert dup_vitals.json()["retryable"] is False

    # 3) Missing appointment -> 404 CFD-500-002
    r_appt = client.get(f"/api/v1/profiles/{profile_id}/appointments/missing-appt-340")
    assert r_appt.status_code == 404
    assert r_appt.headers["content-type"].startswith("application/problem+json")
    assert r_appt.json()["code"] == "CFD-500-002"
    assert r_appt.json()["retryable"] is False

    # 4) Missing import batch -> 404 CFD-500-003
    r_imp = client.get(f"/api/v1/profiles/{profile_id}/imports/missing-batch-340")
    assert r_imp.status_code == 404
    assert r_imp.headers["content-type"].startswith("application/problem+json")
    assert r_imp.json()["code"] == "CFD-500-003"
    assert r_imp.json()["retryable"] is False

    # 5) Invalid note slug -> 400 YRV-100-011
    r_note = client.get("/api/notes/bad$slug!")
    assert r_note.status_code == 400
    assert r_note.headers["content-type"].startswith("application/problem+json")
    assert r_note.json()["code"] == "YRV-100-011"
    assert r_note.json()["retryable"] is False


def test_simulated_500_never_leaks_internal_exception_string(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unhandled 500 errors in Carefold routers sanitize detail and never leak raw exception text."""
    import carefold.routers.prep_pack as prep_pack_router_mod

    profile_id = _ensure_primary_profile(client)
    secret_marker = "SQLITE_INTERNAL_SECRET_TOKEN_998877"

    async def _boom(**_kwargs: Any) -> Dict[str, Any]:
        raise RuntimeError(f"boom: {secret_marker}")

    monkeypatch.setattr(prep_pack_router_mod, "generate_and_persist_prep_pack", _boom)

    resp = client.post(
        f"/api/v1/profiles/{profile_id}/prep-pack",
        json={"specialty": "Cardiology", "visit_reason": "Annual follow-up"},
    )
    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/problem+json")
    payload = resp.json()
    assert payload["code"] == "CFD-900-002"
    assert payload["retryable"] is False
    assert payload["detail"] == "Failed to generate appointment preparation pack."
    assert secret_marker not in resp.text


# ============================================================================
# 4. FHIR R4 OperationOutcome Preservation + CFD Coding
# ============================================================================


def test_fhir_r4_routes_preserve_operation_outcome_and_embed_cfd_code(
    client: TestClient,
) -> None:
    """`/api/v1/fhir/r4/*` errors stay valid FHIR R4 `OperationOutcome` (`application/fhir+json`) with `CFD-*` coding."""
    # 1) 404 Not Found on FHIR Patient read
    r_404 = client.get("/api/v1/fhir/r4/Patient/nonexistent-patient-340")
    assert r_404.status_code == 404
    assert r_404.headers["content-type"].startswith("application/fhir+json")
    outcome_404 = r_404.json()
    assert outcome_404["resourceType"] == "OperationOutcome"
    FhirOperationOutcome.model_validate(outcome_404)
    codings_404 = outcome_404["issue"][0]["details"]["coding"]
    assert any(
        c.get("system") == "https://errors.carefold.dev" and c.get("code") == "CFD-500-001"
        for c in codings_404
    )

    # 2) 428 Confirmation Required on unconfirmed FHIR write -> CFD-700-001
    profile_id = _ensure_primary_profile(client)
    r_428 = client.post(
        "/api/v1/fhir/r4/Observation",
        json={
            "resourceType": "Observation",
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
            "subject": {"reference": f"Patient/{profile_id}"},
        },
    )
    assert r_428.status_code == 428
    assert r_428.headers["content-type"].startswith("application/fhir+json")
    outcome_428 = r_428.json()
    FhirOperationOutcome.model_validate(outcome_428)
    codings_428 = outcome_428["issue"][0]["details"]["coding"]
    assert any(
        c.get("system") == "https://errors.carefold.dev" and c.get("code") == "CFD-700-001"
        for c in codings_428
    )

    # 3) 422 Unprocessable FHIR resource payload -> CFD-100-013, and 400 unsupported type -> CFD-100-001
    r_422 = client.post(
        "/api/v1/fhir/r4/Observation",
        headers={"X-Carefold-Confirm": "true"},
        json={"resourceType": "Condition"},
    )
    assert r_422.status_code == 422
    assert r_422.headers["content-type"].startswith("application/fhir+json")
    outcome_422 = r_422.json()
    FhirOperationOutcome.model_validate(outcome_422)
    codings_422 = outcome_422["issue"][0]["details"]["coding"]
    assert any(
        c.get("system") == "https://errors.carefold.dev" and c.get("code") == "CFD-100-013"
        for c in codings_422
    )

    r_400 = client.get("/api/v1/fhir/r4/Observation?_cursor=invalid-cursor-token")
    assert r_400.status_code == 400
    assert r_400.headers["content-type"].startswith("application/fhir+json")
    outcome_400 = r_400.json()
    FhirOperationOutcome.model_validate(outcome_400)
    codings_400 = outcome_400["issue"][0]["details"]["coding"]
    assert any(
        c.get("system") == "https://errors.carefold.dev" and c.get("code") == "CFD-100-001"
        for c in codings_400
    )

    # 4) Rate limit FhirOperationError carries retryable=True & CFD-600-002
    rate_err = FhirOperationError(
        status_code=429,
        diagnostics="Rate limit exceeded",
        issue_code="throttled",
    )
    assert rate_err.error_code == "CFD-600-002"
    assert rate_err.retryable is True


# ============================================================================
# 5. REST <-> MCP / Tool Error Code & Retryable Parity
# ============================================================================


@pytest.mark.asyncio
async def test_rest_and_mcp_tool_error_code_and_retryable_parity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool executors and MCP DB Toolbox surface the exact same `code` and `retryable` as REST."""
    import carefold.db.session as db_session_mod

    steward_user_id = "00000000-0000-0000-0000-000000000001"
    profile_id = _ensure_primary_profile(client)
    ctx = ToolContext(
        user_id=steward_user_id,
        profile_id=profile_id,
        run_id="run-parity-340",
        autonomy="A3",
        agent_id="care-coordinator",
        effective_tools=[
            "record_vitals",
            "update_appointment_status",
            "commit_clinical_import",
            "sync_school_ics",
            "fhir_search_resources",
        ],
    )

    # Case A: Vitals unpaired systolic BP -> CFD-100-002, retryable=False
    rest_vitals = client.post(
        f"/api/v1/profiles/{profile_id}/vitals",
        json={"vitals": {"systolic": 130.0}},
    ).json()
    tool_vitals = await execute_record_vitals({"vitals_data": {"systolic": 130.0}}, ctx)
    assert tool_vitals.success is False
    assert tool_vitals.error_code == rest_vitals["code"] == "CFD-100-002"
    assert tool_vitals.retryable == rest_vitals["retryable"] is False

    # Case B: Missing appointment update -> CFD-500-002, retryable=False
    rest_appt = client.patch(
        f"/api/v1/profiles/{profile_id}/appointments/missing-appt-parity",
        json={"status": "confirmed"},
    ).json()
    tool_appt = await execute_update_appointment_status(
        {"appointment_id": "missing-appt-parity", "status": "confirmed"},
        ctx,
    )
    assert tool_appt.success is False
    assert tool_appt.error_code == rest_appt["code"] == "CFD-500-002"
    assert tool_appt.retryable == rest_appt["retryable"] is False

    # Case C: Missing clinical import batch commit -> CFD-500-003, retryable=False
    rest_imp = client.post(
        f"/api/v1/profiles/{profile_id}/imports/missing-batch-parity/commit",
        json={},
    ).json()
    with pytest.raises(CarefoldToolError) as imp_exc:
        await execute_commit_clinical_import({"batch_id": "missing-batch-parity"}, ctx)
    assert imp_exc.value.code == rest_imp["code"] == "CFD-500-003"
    assert imp_exc.value.retryable == rest_imp["retryable"] is False

    # Also verify `execute_tool_call` preserves `error_code` and `retryable` on ToolResult!
    from carefold.tools import SPEC_COMMIT_CLINICAL_IMPORT

    exec_res = await execute_tool_call(
        ctx,
        SPEC_COMMIT_CLINICAL_IMPORT,
        {"batch_id": "missing-batch-parity"},
    )
    assert exec_res.success is False
    assert exec_res.error_code == "CFD-500-003"
    assert exec_res.retryable is False

    # Case D: School ICS upstream HTTP failure -> CFD-600-003, retryable=True on both REST and Tool
    factory = db_session_mod.get_session_factory()
    async with factory() as session:
        feed = await create_school_ics_feed(
            session=session,
            profile_id=profile_id,
            label="Lincoln Elementary",
            feed_url="https://calendar.example.edu/lincoln.ics",
            actor_user_id=steward_user_id,
        )
        feed_id = feed.id

    import carefold.clinical.school_ics as school_ics_mod

    async def _upstream_timeout(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        raise httpx.ConnectTimeout("upstream school server timed out")

    monkeypatch.setattr(school_ics_mod, "sync_school_ics_feed", _upstream_timeout)

    rest_ics = client.post(
        f"/api/v1/profiles/{profile_id}/school-ics/{feed_id}/sync",
        json={},
    )
    assert rest_ics.status_code == 502
    rest_ics_body = rest_ics.json()
    assert rest_ics_body["code"] == "CFD-600-003"
    assert rest_ics_body["retryable"] is True

    with pytest.raises(CarefoldToolError) as ics_exc:
        await execute_sync_school_ics({"feed_id": feed_id}, ctx)
    assert ics_exc.value.code == rest_ics_body["code"] == "CFD-600-003"
    assert ics_exc.value.retryable == rest_ics_body["retryable"] is True

    # Case E: FHIR MCP DB Toolbox & Coordinator Tool parity -> CFD-500-001 / CFD-100-001
    register_carefold_db_toolbox()
    toolbox = get_db_toolbox()
    mcp_ctx = SimpleNamespace(
        profile_id=profile_id,
        user_id=steward_user_id,
        agent_id="db-operator",
        run_id="run-mcp-340",
        granted_scopes={"health.clinical": "read"},
    )
    with scope_context(
        "health.clinical",
        granted_scopes={"health.clinical"},
        profile_id=profile_id,
        actor=f"profile:{profile_id}",
    ):
        mcp_404 = await toolbox.execute_tool(
            "fhir_read_resource",
            {"resource_type": "Observation", "resource_id": "missing-obs-340"},
            mcp_ctx,
        )
        fhir_tool_400 = await execute_fhir_search_resources(
            {"resource_type": "InvalidResourceType"},
            ctx,
        )
    assert mcp_404["status"] == "error"
    assert mcp_404["code"] == "CFD-500-001"
    assert mcp_404["retryable"] is False
    assert mcp_404["error"]["code"] == "CFD-500-001"
    assert mcp_404["error"]["retryable"] is False
    assert fhir_tool_400.success is False
    assert fhir_tool_400.error_code == "CFD-100-001"
    assert fhir_tool_400.retryable is False
    assert fhir_tool_400._as_dict()["code"] == "CFD-100-001"
    assert fhir_tool_400._as_dict()["retryable"] is False
