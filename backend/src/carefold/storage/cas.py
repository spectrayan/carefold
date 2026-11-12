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

"""CAS storage shim forwarding legacy carefold_home keyword arguments to yarvelle_core.storage.cas."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Optional, Tuple
from yarvelle_core.storage.cas import *  # noqa: F401, F403
import yarvelle_core.storage.cas as _cas

def get_cas_path(yarvelle_home: Optional[Path] = None, *args: Any, carefold_home: Optional[Path] = None, **kw: Any) -> Path:
    return _cas.get_cas_path(yarvelle_home or carefold_home, *args, **kw)

def resolve_cas_path(yarvelle_home: Optional[Path] = None, *args: Any, carefold_home: Optional[Path] = None, **kw: Any) -> Path:
    return _cas.resolve_cas_path(yarvelle_home or carefold_home, *args, **kw)

def cas_file_exists(yarvelle_home: Optional[Path] = None, *args: Any, carefold_home: Optional[Path] = None, **kw: Any) -> bool:
    return _cas.cas_file_exists(yarvelle_home or carefold_home, *args, **kw)

def store_cas_file(content: bytes, yarvelle_home: Optional[Path] = None, *args: Any, carefold_home: Optional[Path] = None, **kw: Any) -> Tuple[Path, str, bool]:
    return _cas.store_cas_file(content, yarvelle_home or carefold_home, *args, **kw)

def read_cas_file(yarvelle_home: Optional[Path] = None, *args: Any, carefold_home: Optional[Path] = None, **kw: Any) -> bytes:
    return _cas.read_cas_file(yarvelle_home or carefold_home, *args, **kw)

def __getattr__(name: str) -> Any:
    return getattr(_cas, name)
