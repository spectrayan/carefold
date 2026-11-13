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

"""Automated manifest tool entry resolution and integrity test suite for carefold_health."""

import importlib
from pathlib import Path
import sys
from typing import Any, Dict, List
import pytest
import yaml

from yarvelle_core.engine.tool_registry import ToolSpec


def _find_pack_yaml() -> Path:
    candidates = [
        Path("backend/src/carefold/pack.yaml"),
        Path("src/carefold/pack.yaml"),
        Path(__file__).resolve().parent.parent.parent / "src/carefold/pack.yaml",
        Path(__file__).resolve().parent.parent / "src/carefold/pack.yaml",
        Path(__file__).resolve().parent.parent / "pack.yaml",
    ]
    for c in candidates:
        if c.is_file():
            return c.resolve()
    raise FileNotFoundError(f"Could not locate carefold/pack.yaml. Checked: {candidates}")


@pytest.fixture(scope="module")
def pack_manifest() -> Dict[str, Any]:
    pack_path = _find_pack_yaml()
    with open(pack_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), f"pack.yaml at {pack_path} is not a valid dictionary"
    return data


def test_manifest_declares_exact_17_tools(pack_manifest: Dict[str, Any]):
    tools = pack_manifest.get("provides", {}).get("tools", [])
    assert len(tools) == 173, f"Expected exactly 173 tools declared in pack.yaml, found {len(tools)}"
    assert "ui" not in pack_manifest, "Backend pack.yaml must not contain frontend 'ui' definitions"


def test_all_17_manifest_tool_entries_resolve(pack_manifest: Dict[str, Any]):
    tools = pack_manifest.get("provides", {}).get("tools", [])
    assert len(tools) == 173

    failures: List[str] = []
    resolved_specs: Dict[str, ToolSpec] = {}

    for tool_decl in tools:
        tool_id = tool_decl.get("id")
        entry = tool_decl.get("entry")
        assert tool_id, "Tool declaration missing 'id'"
        assert entry, f"Tool '{tool_id}' missing 'entry'"

        if ":" not in entry:
            failures.append(f"{tool_id}: invalid entry syntax '{entry}', expected 'module:attr'")
            continue

        modname, attr = entry.split(":", 1)

        try:
            mod = importlib.import_module(modname)
        except Exception as exc:
            failures.append(f"{tool_id} ({entry}): failed to import module '{modname}': {type(exc).__name__}: {exc}")
            continue

        if not hasattr(mod, attr):
            failures.append(f"{tool_id} ({entry}): module '{modname}' has no attribute '{attr}'")
            continue

        spec = getattr(mod, attr)
        if not isinstance(spec, ToolSpec):
            failures.append(f"{tool_id} ({entry}): attribute '{attr}' is {type(spec).__name__}, expected ToolSpec")
            continue

        if spec.name != tool_id:
            failures.append(f"{tool_id} ({entry}): ToolSpec.name '{spec.name}' != manifest id '{tool_id}'")

        if not spec.description or not isinstance(spec.description, str) or not spec.description.strip():
            failures.append(f"{tool_id} ({entry}): ToolSpec.description must be a non-empty string")

        if not isinstance(spec.parameters, dict) or spec.parameters.get("type") != "object":
            failures.append(f"{tool_id} ({entry}): ToolSpec.parameters must be a dict with type='object'")

        raw_scopes = tool_decl.get("scopes", {})
        expected_scopes = set()
        if isinstance(raw_scopes, dict):
            for scope_list in raw_scopes.values():
                if isinstance(scope_list, (list, tuple, set)):
                    expected_scopes.update(str(s).strip() for s in scope_list)
        elif isinstance(raw_scopes, (list, tuple, set)):
            expected_scopes.update(str(s).strip() for s in raw_scopes)

        if expected_scopes and not expected_scopes.issubset(spec.scopes):
            failures.append(
                f"{tool_id} ({entry}): manifest scopes {expected_scopes} not subset of ToolSpec.scopes {spec.scopes}"
            )

        expected_egress = tool_decl.get("data_flows", {}).get("egress", [])
        if expected_egress:
            spec_hosts = getattr(spec.data_flows, "allowed_hosts", ())
            for host in expected_egress:
                if host not in spec_hosts:
                    failures.append(
                        f"{tool_id} ({entry}): manifest egress host '{host}' not in ToolSpec allowed_hosts {spec_hosts}"
                    )

        if not callable(spec.executor) and not callable(spec.handler):
            failures.append(f"{tool_id} ({entry}): ToolSpec must have a callable executor or handler")

        resolved_specs[tool_id] = spec

    assert not failures, "Tool entry resolution failures:\n" + "\n".join(f"  - {f}" for f in failures)
    assert len(resolved_specs) == 173, f"Expected 173 resolved tools, got {len(resolved_specs)}"


def test_native_get_health_tool_specs_factory():
    from carefold.tools import get_health_tool_specs

    specs = get_health_tool_specs()
    assert isinstance(specs, list)
    assert len(specs) == 173, f"Expected 173 ToolSpecs from get_health_tool_specs(), got {len(specs)}"

    spec_names = {s.name for s in specs}
    expected_names = {
        "record_vitals",
        "create_appointment",
        "list_appointments",
        "update_appointment_status",
        "generate_prep_pack",
        "create_typed_note",
        "check_preventive_care",
        "update_preventive_status",
        "stage_clinical_import",
        "commit_clinical_import",
        "create_school_form",
        "list_school_forms",
        "withings_latest_vitals",
        "epic_smart_search_records",
        "sync_school_ics",
        "zocdoc_book_appointment",
        "verify_smart_health_card",
        "fhir_search_resources",
        "fhir_get_patient_summary",
        "fhir_get_observation_trends",
    }
    assert expected_names.issubset(spec_names), f"Missing core clinical tools: {expected_names - spec_names}"

    for spec in specs:
        assert isinstance(spec, ToolSpec)
        assert callable(spec.executor) or callable(spec.handler)
        assert "health.clinical" in spec.scopes


def test_isolated_resolution_without_app_main():
    class BlockAppMainMetaPathFinder:
        def find_spec(self, fullname, path, target=None):
            if fullname == "carefold.main" or fullname.startswith("carefold.main."):
                raise ImportError(f"Adversarial test: blocked access to app shell '{fullname}'")
            return None

    finder = BlockAppMainMetaPathFinder()
    sys.meta_path.insert(0, finder)
    try:
        import carefold.tools as cht
        tools = cht.get_health_tool_specs()
        assert len(tools) == 173
        for t in tools:
            assert isinstance(t, ToolSpec)
    finally:
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)

