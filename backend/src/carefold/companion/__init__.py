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

"""iOS Companion Pairing, Pinned TLS Verification, and HealthKit/ClinicalRecord Sync package (AU-62)."""

from carefold.companion.pairing import (
    DEFAULT_COMPANION_CATEGORIES,
    LOOPBACK_HOSTS,
    VALID_COMPANION_CATEGORIES,
    VALID_COMPANION_PLATFORMS,
    CompanionPairingError,
    authenticate_companion_device,
    check_companion_mode_guard,
    complete_companion_pairing,
    initiate_companion_pairing,
    revoke_companion_device,
)
from carefold.companion.sync import (
    SUPPORTED_CLINICAL_RECORD_TYPES,
    SUPPORTED_HEALTH_CONNECT_RECORD_TYPES,
    evaluate_vitals_red_flags,
    ingest_companion_sync,
    list_companion_reminders,
)

__all__ = [
    "LOOPBACK_HOSTS",
    "DEFAULT_COMPANION_CATEGORIES",
    "VALID_COMPANION_CATEGORIES",
    "VALID_COMPANION_PLATFORMS",
    "SUPPORTED_CLINICAL_RECORD_TYPES",
    "SUPPORTED_HEALTH_CONNECT_RECORD_TYPES",
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
