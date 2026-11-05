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

"""Backward-compatibility re-export shim for yarvelle_core.platform.reminders."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yarvelle_core.platform.reminders import *  # noqa: F401, F403
from yarvelle_core.platform.reminders import (
    SNOOZE_DELTAS,
    WEEKDAY_MAP,
    advance_rrule_occurrence,
    apply_reminder_snooze,
    coalesce_overdue_reminders,
    generate_ics_calendar as _generate_ics_calendar,
    handle_reminder_job,
)


def generate_ics_calendar(
    reminders: List[Dict[str, Any]],
    sanitize_phi: bool = True,
    app_name: Optional[str] = None,
) -> str:
    """Carefold-branded RFC 5545 export (defaults product_name to Carefold)."""
    if app_name is None:
        from carefold.config import settings

        app_name = settings.product_name
    return _generate_ics_calendar(reminders, sanitize_phi=sanitize_phi, app_name=app_name)


__all__ = [
    "SNOOZE_DELTAS",
    "WEEKDAY_MAP",
    "advance_rrule_occurrence",
    "apply_reminder_snooze",
    "coalesce_overdue_reminders",
    "generate_ics_calendar",
    "handle_reminder_job",
]
