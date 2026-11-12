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

"""ToolSpecRegistry shim delegating to yarvelle_core and registering MRN-redacted web_search."""

from __future__ import annotations

from dataclasses import replace
from typing import List, Optional, Sequence, Tuple
from yarvelle_core.engine.tool_registry import *  # noqa: F401, F403
import yarvelle_core.engine.tool_registry as _core_tr
from carefold.tools import get_health_tool_specs as _make_health_builtin_specs
from carefold.tools.web_search import execute_web_search as _cf_web_search

HEALTH_TOOL_NAMES: Tuple[str, ...] = tuple(s.name for s in _make_health_builtin_specs())


def create_default_registry(enabled_packs: Optional[Sequence[str]] = None) -> ToolSpecRegistry:
    registry = _core_tr.create_default_registry(enabled_packs=enabled_packs)
    ws = registry.get("web_search")
    if ws is not None:
        registry.register(replace(ws, executor=_cf_web_search), pack_id="core")
    return registry

import yarvelle_core.engine.tool_registry as _yc_mod

def __getattr__(name: str):
    return getattr(_yc_mod, name)
