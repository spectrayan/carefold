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

"""Built-in starter connectors for Carefold (Withings, Google Calendar, CalDAV, Epic SMART)."""

from connectors.starters.calendar import (
    CalDavConnector,
    GoogleCalendarConnector,
    sanitize_calendar_event_title,
    suggest_free_slots,
)
from connectors.starters.epic_smart import EpicSmartConnector
from connectors.starters.withings import WithingsConnector

__all__ = [
    "CalDavConnector",
    "EpicSmartConnector",
    "GoogleCalendarConnector",
    "WithingsConnector",
    "sanitize_calendar_event_title",
    "suggest_free_slots",
]
