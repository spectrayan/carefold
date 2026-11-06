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

"""Health SafetyPolicy implementation wrapping Carefold clinical safety modules."""

from __future__ import annotations

from typing import Any, Optional, Sequence, Set

from yarvelle_core.constants.defaults import DEFAULT_FORBIDDEN_INTENTS
from yarvelle_core.engine.safety_policy import (
    EmergencyDirective,
    SafetyContext,
    SafetyPolicy,
    SafetyVerdict,
)
from carefold.safety.classifier import check_safety_refusal, is_hard_refusal_reason
from carefold.safety.emergency import check_emergency_red_flags
from carefold.safety.prompt import build_safety_preamble
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE


class HealthSafetyPolicy:
    """Adapts Carefold clinical safety classifiers to the domain-neutral SafetyPolicy protocol."""

    def check_input(
        self, text: Optional[str], ctx: Optional[SafetyContext] = None
    ) -> SafetyVerdict:
        res = check_safety_refusal(text)
        return SafetyVerdict(
            refused=res.refused,
            reason=res.reason,
            safe_response=res.safe_response or SAFE_REFUSAL_TEMPLATE,
            is_hard=is_hard_refusal_reason(res.reason) if res.refused else False,
        )

    def check_output(
        self, text: Optional[str], ctx: Optional[SafetyContext] = None
    ) -> SafetyVerdict:
        res = check_safety_refusal(text)
        return SafetyVerdict(
            refused=res.refused,
            reason=res.reason,
            safe_response=res.safe_response or SAFE_REFUSAL_TEMPLATE,
            is_hard=is_hard_refusal_reason(res.reason) if res.refused else False,
        )

    def check_emergency(self, text: Optional[str]) -> Optional[EmergencyDirective]:
        flag = check_emergency_red_flags(text or "")
        if flag is None:
            return None
        return EmergencyDirective(
            detected=True,
            category=flag.category,
            trigger_phrase=flag.trigger_phrase,
            referral_message=flag.referral_message,
        )

    def check_flags(
        self, text: Optional[str], ctx: Optional[SafetyContext] = None
    ) -> list[str]:
        """Non-refusing flags for pack fixed routes (``red_flag`` → triage-auditor).

        Reuses the health-pack emergency red-flag detector so acute clinical
        urgency raises ``red_flag`` for orchestration before any model call.
        """
        del ctx  # reserved for future scoped flagging
        if check_emergency_red_flags(text or "") is not None:
            return ["red_flag"]
        return []

    def get_preamble(self, agent: Any, skills: Sequence[Any] = ()) -> str:
        return build_safety_preamble(agent, skills)

    def get_refusal_template(self, reason: Optional[str] = None) -> str:
        return SAFE_REFUSAL_TEMPLATE

    def is_hard_refusal_reason(self, reason: Optional[str]) -> bool:
        return is_hard_refusal_reason(reason)

    def get_forbidden_intents(self) -> Set[str]:
        return set(DEFAULT_FORBIDDEN_INTENTS)


CarefoldHealthSafetyPolicy = HealthSafetyPolicy

__all__ = [
    "HealthSafetyPolicy",
    "CarefoldHealthSafetyPolicy",
]

