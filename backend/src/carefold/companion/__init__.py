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

"""iOS Companion Pairing, Pinned TLS Verification, and HealthKit/ClinicalRecord Sync package (AU-62)."""

from carefold.companion.pairing import (
    DEFAULT_COMPANION_CATEGORIES,
    LOOPBACK_HOSTS,
    VALID_COMPANION_CATEGORIES,
    CompanionPairingError,
    authenticate_companion_device,
    check_companion_mode_guard,
    complete_companion_pairing,
    initiate_companion_pairing,
    revoke_companion_device,
)
from carefold.companion.sync import (
    SUPPORTED_CLINICAL_RECORD_TYPES,
    evaluate_vitals_red_flags,
    ingest_companion_sync,
    list_companion_reminders,
)

__all__ = [
    "LOOPBACK_HOSTS",
    "DEFAULT_COMPANION_CATEGORIES",
    "VALID_COMPANION_CATEGORIES",
    "SUPPORTED_CLINICAL_RECORD_TYPES",
    "CompanionPairingError",
    "check_companion_mode_guard",
    "initiate_companion_pairing",
    "complete_companion_pairing",
    "authenticate_companion_device",
    "revoke_companion_device",
    "evaluate_vitals_red_flags",
    "ingest_companion_sync",
    "list_companion_reminders",
]
