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

"""Carefold's document types reach core's merged routing patterns.

Carefold registers its routing patterns through core's native pack resources
(``ResourceLoader.register_pack`` with ``routing_hints.patterns_resource``).
The types must be visible even when core built its merged view before
Carefold loaded, and must be matched before core's generic fallback. Each
check runs in a fresh interpreter because the registration happens at import
time.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

EXPECTED = ["insurance", "clinical", "generic"]

_PROBE = """
import json
from yarvelle_core.resources.loader import get_resource_loader
{warm}
import carefold  # noqa: F401
print(json.dumps(list(get_resource_loader().get_routing_patterns()["dossier_types"])))
"""


def _run(code: str) -> object:
    out = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def _dossier_types(warm_core_cache_first: bool) -> list:
    warm = "get_resource_loader().get_routing_patterns()" if warm_core_cache_first else ""
    return _run(_PROBE.format(warm=warm))


@pytest.mark.parametrize("warm_core_cache_first", [False, True], ids=["cold", "core-cache-built-first"])
def test_carefold_document_types_are_in_core_merged_patterns(warm_core_cache_first: bool) -> None:
    types = _dossier_types(warm_core_cache_first)
    for name in EXPECTED:
        assert name in types, types


def test_carefold_document_types_keep_their_order() -> None:
    """Specific types are tried before the generic fallback."""
    types = _dossier_types(False)
    assert [t for t in types if t in EXPECTED] == EXPECTED


_NATIVE_PROBE = """
import json
from pathlib import Path
import yaml
import carefold
from yarvelle_core.resources.loader import get_resource_loader
loader = get_resource_loader()
pack = carefold.get_pack()
own = yaml.safe_load((Path(carefold.__file__).parent / "resources" / "routing_patterns.yaml").read_text())
print(json.dumps({
    "manifest_is_file": bool(pack.manifest_path) and Path(pack.manifest_path).is_file(),
    "core_raw_types": list(loader.load_yaml("routing_patterns.yaml")["dossier_types"]),
    "pack_types": list(loader.load_pack_yaml("health", "resources/routing_patterns.yaml")["dossier_types"]),
    "merged": loader.get_routing_patterns()["dossier_types"],
    "own": own["dossier_types"],
}))
"""


def test_document_types_come_from_native_pack_resources() -> None:
    """Registration goes through core's pack API; core's own file is untouched."""
    got = _run(_NATIVE_PROBE)
    assert got["manifest_is_file"] is True
    assert got["core_raw_types"] == ["generic"]
    assert [t for t in got["pack_types"] if t in EXPECTED] == EXPECTED
    for name in ("insurance", "clinical"):
        assert got["merged"][name] == got["own"][name]
