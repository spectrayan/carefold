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

Core 0.2.1 caches the merged routing patterns separately from the raw
``routing_patterns.yaml``. Carefold must add its document types in a way that
the merged view sees, even when core built that view before Carefold loaded.
Each check runs in a fresh interpreter because the registration happens at
import time.
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


def _dossier_types(warm_core_cache_first: bool) -> list:
    warm = "get_resource_loader().get_routing_patterns()" if warm_core_cache_first else ""
    out = subprocess.run(
        [sys.executable, "-c", _PROBE.format(warm=warm)],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("warm_core_cache_first", [False, True], ids=["cold", "core-cache-built-first"])
def test_carefold_document_types_are_in_core_merged_patterns(warm_core_cache_first: bool) -> None:
    types = _dossier_types(warm_core_cache_first)
    for name in EXPECTED:
        assert name in types, types


def test_carefold_document_types_keep_their_order() -> None:
    """Specific types are tried before the generic fallback."""
    types = _dossier_types(False)
    assert [t for t in types if t in EXPECTED] == EXPECTED
