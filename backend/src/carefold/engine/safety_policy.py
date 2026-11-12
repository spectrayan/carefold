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

"""Domain-neutral SafetyPolicy protocol and registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol, Sequence, Set, runtime_checkable


@dataclass(frozen=True)
class SafetyVerdict:
    """Standardized verdict returned by input and output safety checks."""

    refused: bool
    reason: Optional[str] = None
    safe_response: Optional[str] = None
    category: Optional[str] = None
    is_hard: bool = False


@dataclass
class EmergencyDirective:
    """Directive generated when acute life-threatening emergency symptoms are detected."""

    detected: bool
    category: str
    trigger_phrase: str
    referral_message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detected": self.detected,
            "category": self.category,
            "trigger_phrase": self.trigger_phrase,
            "referral_message": self.referral_message,
        }


@dataclass
class SafetyContext:
    """Contextual metadata passed into safety evaluations."""

    profile_id: Optional[str] = None
    agent_id: Optional[str] = None
    domain: Optional[str] = None
    risk_class: Optional[str] = None
    allow_assist: Optional[bool] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SafetyPolicy(Protocol):
    """Domain-neutral protocol governing pre- and post-execution agent safety."""

    def check_input(
        self, text: Optional[str], ctx: Optional[SafetyContext] = None
    ) -> SafetyVerdict:
        """Evaluates user input for forbidden intents or dangerous instructions."""
        ...

    def check_output(
        self, text: Optional[str], ctx: Optional[SafetyContext] = None
    ) -> SafetyVerdict:
        """Evaluates model generation for policy violations or boundary crossing."""
        ...

    def check_emergency(self, text: Optional[str]) -> Optional[EmergencyDirective]:
        """Checks for acute red flags requiring immediate emergency diversion."""
        ...

    def get_preamble(self, agent: Any, skills: Sequence[Any] = ()) -> str:
        """Generates the mandatory system prompt safety preamble."""
        ...

    def get_refusal_template(self, reason: Optional[str] = None) -> str:
        """Retrieves safe refusal response text for a given refusal reason."""
        ...

    def is_hard_refusal_reason(self, reason: Optional[str]) -> bool:
        """Determines whether a refusal requires complete content suppression (Tier 1)."""
        ...

    def get_forbidden_intents(self) -> Set[str]:
        """Returns registered forbidden intent identifier strings."""
        ...


_DEFAULT_SAFETY_POLICY: Optional[SafetyPolicy] = None


def get_default_safety_policy() -> SafetyPolicy:
    """Resolves default safety policy, falling back to HealthSafetyPolicy if present."""
    global _DEFAULT_SAFETY_POLICY
    if _DEFAULT_SAFETY_POLICY is None:
        try:
            from carefold.safety.policy import HealthSafetyPolicy

            _DEFAULT_SAFETY_POLICY = HealthSafetyPolicy()
        except ImportError:
            _DEFAULT_SAFETY_POLICY = NeutralSafetyPolicy()
    return _DEFAULT_SAFETY_POLICY


def set_default_safety_policy(policy: SafetyPolicy) -> None:
    """Sets global default safety policy."""
    global _DEFAULT_SAFETY_POLICY
    _DEFAULT_SAFETY_POLICY = policy


class NeutralSafetyPolicy:
    """Baseline domain-neutral safety policy (no-op safety rules)."""

    def check_input(self, text: Optional[str], ctx: Optional[SafetyContext] = None) -> SafetyVerdict:
        return SafetyVerdict(refused=False)

    def check_output(self, text: Optional[str], ctx: Optional[SafetyContext] = None) -> SafetyVerdict:
        return SafetyVerdict(refused=False)

    def check_emergency(self, text: Optional[str]) -> Optional[EmergencyDirective]:
        return None

    def get_preamble(self, agent: Any, skills: Sequence[Any] = ()) -> str:
        return ""

    def get_refusal_template(self, reason: Optional[str] = None) -> str:
        return "I cannot fulfill this request as it violates safety guidelines."

    def is_hard_refusal_reason(self, reason: Optional[str]) -> bool:
        return True

    def get_forbidden_intents(self) -> Set[str]:
        return set()


__all__ = [
    "EmergencyDirective",
    "NeutralSafetyPolicy",
    "SafetyContext",
    "SafetyPolicy",
    "SafetyVerdict",
    "get_default_safety_policy",
    "set_default_safety_policy",
]
