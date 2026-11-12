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

"""Reminders platform shim delegating to yarvelle_core.platform.reminders."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from yarvelle_core.platform.reminders import *  # noqa: F401, F403
import yarvelle_core.platform.reminders as _target_module


def generate_ics_calendar(
    reminders: List[Dict[str, Any]],
    sanitize_sensitive: bool = True,
    app_name: Optional[str] = None,
    *,
    sanitize_phi: Optional[bool] = None,
) -> str:
    effective = sanitize_sensitive if sanitize_phi is None else sanitize_phi
    return _target_module.generate_ics_calendar(reminders, sanitize_sensitive=effective, app_name=app_name)


def __getattr__(name: str) -> Any:
    return getattr(_target_module, name)
