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

"""ResourceLoader shim defaulting resources_dir to Carefold pack resources."""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import yarvelle_core.resources.loader as _yc_mod
from yarvelle_core.resources.loader import FALLBACK_DOSSIER_TYPE, RefusalPattern, ResourceLoader as _CoreResourceLoader  # noqa: F401

_DEFAULT_RESOURCES_DIR = Path(__file__).resolve().parent
_LOADER_SINGLETON: Optional["ResourceLoader"] = None

class ResourceLoader(_CoreResourceLoader):
    def __init__(self, resources_dir: Optional[Path] = None) -> None:
        super().__init__(resources_dir=resources_dir or _DEFAULT_RESOURCES_DIR)

def get_resource_loader() -> ResourceLoader:
    global _LOADER_SINGLETON
    if _LOADER_SINGLETON is None:
        _LOADER_SINGLETON = ResourceLoader()
    return _LOADER_SINGLETON

def __getattr__(name: str):
    return getattr(_yc_mod, name)
