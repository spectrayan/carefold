# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
