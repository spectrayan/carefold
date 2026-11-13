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

"""Declarative tool specification parity, deduplication, and fail-closed contract tests (#338)."""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from sqlalchemy import select
import yaml

from carefold.engine.tool_registry import create_default_registry
from carefold.models import Appointment, SchoolIcsFeed
from carefold.tools import get_health_tool_spec, get_health_tool_specs
from carefold.tools.connectors import execute_sync_school_ics
from yarvelle_core.connectors.errors import ConnectorNotConfiguredError
from yarvelle_core.engine.tool_exec import TaintFlag, ToolContext, evaluate_policy_gate
from yarvelle_core.schemas.tool_spec import HandlerToolBinding, ToolSetManifest
from yarvelle_core.tools.spec_loader import get_tool_spec_loader, resolve_handler_entrypoint

CAREFOLD_SRC = Path(__file__).resolve().parents[1] / "src" / "carefold"
TOOLS_YAML_DIR = CAREFOLD_SRC / "resources" / "tools"
PACK_YAML_PATH = CAREFOLD_SRC / "pack.yaml"


def test_declarative_tool_yaml_manifests_validate_and_match_pack_yaml_1_to_1() -> None:
    yaml_files = sorted(TOOLS_YAML_DIR.glob("*.yaml"))
    assert len(yaml_files) >= 1, "Expected declarative YAML tool manifests in resources/tools/"

    declarative_by_name: Dict[str, Any] = {}
    for path in yaml_files:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        manifest = ToolSetManifest.model_validate(raw)
        assert manifest.pack_id == "health"
        for spec in manifest.tools:
            assert spec.name not in declarative_by_name, f"Duplicate tool '{spec.name}' in {path}"
            assert spec.pack_id == "health"
            assert isinstance(spec.binding, HandlerToolBinding)
            fn = resolve_handler_entrypoint(spec.binding.entrypoint)
            assert inspect.iscoroutinefunction(fn), (
                f"Handler '{spec.binding.entrypoint}' for '{spec.name}' must be async def"
            )
            declarative_by_name[spec.name] = spec

    assert len(declarative_by_name) == 173

    pack_raw = yaml.safe_load(PACK_YAML_PATH.read_text(encoding="utf-8"))
    pack_tools: List[Dict[str, Any]] = pack_raw["provides"]["tools"]
    pack_ids = [t["id"] for t in pack_tools]
    assert set(pack_ids) == set(declarative_by_name.keys())
    assert len(pack_ids) == 173

    # Verify get_health_tool_specs() returns cached singletons matching declarative specs
    specs_first = get_health_tool_specs()
    specs_second = get_health_tool_specs()
    assert [s.name for s in specs_first] == pack_ids
    for s1, s2 in zip(specs_first, specs_second):
        assert s1 is s2, f"Expected cached ToolSpec instance for '{s1.name}' (no double instantiation)"

    # Verify pack.yaml entry attributes resolve to the exact same declarative ToolSpec instances
    for item in pack_tools:
        mod_name, attr_name = item["entry"].split(":", 1)
        mod = importlib.import_module(mod_name)
        resolved = getattr(mod, attr_name)
        assert resolved is get_health_tool_spec(item["id"])


def test_default_registry_loads_declarative_pack_tools_and_preserves_gate_tiers() -> None:
    registry_src = (CAREFOLD_SRC / "engine" / "tool_registry.py").read_text(encoding="utf-8")
    assert "_PACK_HEALTH" not in registry_src

    loader = get_tool_spec_loader()
    assert "health" in loader.registered_pack_ids()

    reg = create_default_registry()
    for spec in get_health_tool_specs():
        registered = reg.get(spec.name)
        assert registered is not None, f"Missing '{spec.name}' in default registry"
        assert registered.risk_tier == spec.risk_tier
        assert registered.trust == spec.trust
        assert registered.data_flows.allowed_hosts == spec.data_flows.allowed_hosts

    # Verify evaluate_policy_gate enforcement on read vs write_local vs irreversible
    ctx = ToolContext(
        user_id="user-gate-1",
        profile_id="prof-gate-1",
        autonomy="A2",
        taint=TaintFlag(initial=False),
        extra={"granted_scopes": {"health.clinical", "health.*"}},
    )
    list_appts_spec = reg.get("list_appointments")
    assert list_appts_spec is not None
    read_decision = evaluate_policy_gate(ctx, list_appts_spec, {})
    assert read_decision.allowed is True
    assert read_decision.needs_approval is False

    record_vitals_spec = reg.get("record_vitals")
    assert record_vitals_spec is not None
    write_local_decision = evaluate_policy_gate(ctx, record_vitals_spec, {})
    assert write_local_decision.allowed is True
    assert write_local_decision.needs_approval is False

    zocdoc_spec = reg.get("zocdoc_book_appointment")
    assert zocdoc_spec is not None
    irrev_decision = evaluate_policy_gate(ctx, zocdoc_spec, {})
    assert irrev_decision.allowed is False
    assert irrev_decision.needs_approval is True


def test_zero_duplicate_toolspec_declarations_and_zero_unprefixed_connector_imports() -> None:
    # 1. Zero ToolSpec(...) calls anywhere in carefold/tools/*.py
    for py_file in sorted((CAREFOLD_SRC / "tools").glob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                callee = node.func
                func_name = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", "")
                assert func_name != "ToolSpec", (
                    f"{py_file.name} must not construct inline ToolSpec(...); declare in resources/tools/*.yaml"
                )

    # 2. Starter connector modules are thin re-export shims (<35 lines) and duplicate manifests dir is gone
    starters_dir = CAREFOLD_SRC / "connectors" / "starters"
    assert (starters_dir / "manifests").is_dir()
    assert not (CAREFOLD_SRC / "connectors" / "manifests").exists()
    for shim_name in (
        "calendar.py",
        "ehr_smart_v2.py",
        "epic_smart.py",
        "wearables_v2.py",
        "withings.py",
        "zocdoc.py",
    ):
        shim_path = starters_dir / shim_name
        lines = shim_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) < 35, f"Expected thin shim for {shim_name}, got {len(lines)} lines"
        assert "ToolSpec(" not in shim_path.read_text(encoding="utf-8")

    # 3. Connector tools matching pack tools reuse declarative specs without drift
    from carefold.connectors.epic_smart import EpicSmartConnector
    from carefold.connectors.withings import WithingsConnector
    from carefold.connectors.zocdoc import ZocdocConnector

    w_tool = WithingsConnector().tools()[0]
    assert w_tool.description == get_health_tool_spec("withings_latest_vitals").description
    e_tool = EpicSmartConnector().tools()[0]
    assert e_tool.description == get_health_tool_spec("epic_smart_search_records").description
    z_book = next(t for t in ZocdocConnector().tools() if t.name == "zocdoc_book_appointment")
    assert z_book.description == get_health_tool_spec("zocdoc_book_appointment").description

    # 4. Zero unprefixed `from connectors...` or `import connectors...` anywhere in carefold/
    for py_file in sorted(CAREFOLD_SRC.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert node.module != "connectors" and not node.module.startswith("connectors."), (
                    f"Unprefixed connector import '{node.module}' in {py_file}"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "connectors" and not alias.name.startswith("connectors."), (
                        f"Unprefixed connector import '{alias.name}' in {py_file}"
                    )


@pytest.mark.asyncio
async def test_sync_school_ics_invokes_real_domain_sync_and_fails_closed(
    async_db_session_factory: Any,
    profile_factory: Any,
) -> None:
    # Fail closed when profile_id or feed_id is missing
    with pytest.raises(ValueError, match="profile_id"):
        await execute_sync_school_ics({"feed_id": "feed-1"}, ctx=None)

    with pytest.raises(ValueError, match="feed_id"):
        await execute_sync_school_ics(
            {},
            ctx=SimpleNamespace(profile_id="prof-1", session_factory=async_db_session_factory),
        )

    profile = await profile_factory(
        profile_id="prof-ics-338",
        name="Leo Child",
        relationship="child",
    )
    async with async_db_session_factory() as session:
        feed = SchoolIcsFeed(
            id="feed-ics-338",
            profile_id=profile.id,
            label="Oak Elementary Nurse Calendar",
            feed_url="https://calendar.oakschool.edu/health.ics",
        )
        session.add(feed)
        await session.commit()

    # Fail closed when feed_id belongs to a different / nonexistent feed
    with pytest.raises(ValueError, match="not found"):
        await execute_sync_school_ics(
            {"feed_id": "nonexistent-feed"},
            ctx=SimpleNamespace(profile_id="prof-ics-338", session_factory=async_db_session_factory),
        )

    sample_ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Oak School//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:vision-screening-2026@oakschool.edu\r\n"
        "DTSTART:20261015T140000Z\r\n"
        "DTEND:20261015T150000Z\r\n"
        "SUMMARY:Annual School Vision Screening\r\n"
        "LOCATION:Nurse Office\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    result = await execute_sync_school_ics(
        {"feed_id": "feed-ics-338", "raw_ics_content": sample_ics},
        ctx=SimpleNamespace(profile_id="prof-ics-338", session_factory=async_db_session_factory),
    )
    assert result["feed_id"] == "feed-ics-338"
    assert result["created_count"] == 1

    async with async_db_session_factory() as session:
        rows = (
            await session.execute(
                select(Appointment).where(Appointment.profile_id == "prof-ics-338")
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].title == "Annual School Vision Screening"


@pytest.mark.asyncio
async def test_gmail_tools_fail_closed_when_mcp_connector_unconfigured() -> None:
    reg = create_default_registry()
    ctx = SimpleNamespace(profile_id="prof-gmail-338", user_id="user-gmail-338")

    for tool_name in ("gmail_list_messages", "gmail_send_message"):
        spec = reg.get(tool_name)
        assert spec is not None and spec.executor is not None
        with pytest.raises(ConnectorNotConfiguredError):
            await spec.executor({"label": "appointments"}, ctx)
