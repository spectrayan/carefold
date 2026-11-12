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

"""Re-export shim delegating to yarvelle_core.resources.loader."""

from __future__ import annotations

import threading
from yarvelle_core.resources.loader import *  # noqa: F401, F403
import yarvelle_core.resources.loader as _yc_loader
from carefold.clinical.host_bridges import CarefoldResourceLoader as ResourceLoader

_LOADER_LOCK = threading.Lock()
_LOADER_INSTANCE: ResourceLoader | None = None


def get_resource_loader() -> ResourceLoader:
    global _LOADER_INSTANCE
    if _LOADER_INSTANCE is None:
        with _LOADER_LOCK:
            if _LOADER_INSTANCE is None:
                _LOADER_INSTANCE = ResourceLoader()
    return _LOADER_INSTANCE


def __getattr__(name: str):
    return getattr(_yc_loader, name)
