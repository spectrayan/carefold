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

"""Re-export safety package components."""

from carefold.safety.template import SAFE_REFUSAL_TEMPLATE
from carefold.safety.classifier import (
    COMMON_CONDITIONS,
    DISCLAIMER_CLAUSES,
    HARD_REFUSAL_PREFIXES,
    REFUSAL_PATTERNS,
    SafetyCheckResult,
    check_safety_refusal,
    is_hard_refusal_reason,
)
from carefold.safety.prompt import build_safety_preamble
from carefold.safety.emergency import EmergencyFlag, check_emergency_red_flags
from carefold.safety.vitals import VitalsEmergencyFlag, check_vitals_red_flags

__all__ = [
    "SAFE_REFUSAL_TEMPLATE",
    "COMMON_CONDITIONS",
    "DISCLAIMER_CLAUSES",
    "HARD_REFUSAL_PREFIXES",
    "REFUSAL_PATTERNS",
    "SafetyCheckResult",
    "check_safety_refusal",
    "is_hard_refusal_reason",
    "build_safety_preamble",
    "EmergencyFlag",
    "check_emergency_red_flags",
    "VitalsEmergencyFlag",
    "check_vitals_red_flags",
]

