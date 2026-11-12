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

from carefold.constants.defaults import DEFAULT_FORBIDDEN_INTENTS
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


class _HealthSafetyPolicyMeta(type):
    """Recognizes a GuardedSafetyPolicy wrapping HealthSafetyPolicy as an instance."""

    def __instancecheck__(cls, instance: Any) -> bool:
        if super().__instancecheck__(instance):
            return True
        base = getattr(instance, "__dict__", {}).get("base") if hasattr(instance, "__dict__") else None
        return base is not None and super().__instancecheck__(base)


class HealthSafetyPolicy(metaclass=_HealthSafetyPolicyMeta):
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


def adapt_legacy_core_turn_kwargs(
    service: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    core_service_cls: Any,
) -> tuple[dict[str, Any], Optional[list[dict[str, Any]]]]:
    """Bridges allow_assist -> allow_clinical and assist gating when running on yarvelle-core 0.2.4."""
    import inspect

    params = inspect.signature(core_service_cls.execute_turn).parameters
    if "allow_assist" in params:
        return kwargs, None

    adapted = dict(kwargs)
    if "allow_assist" in adapted and "allow_clinical" not in adapted:
        adapted["allow_clinical"] = bool(adapted["allow_assist"])

    allow_flag = adapted.get("allow_assist", adapted.get("allow_clinical", True))
    adapted.pop("allow_assist", None)
    agent_id = adapted.get("agent_id") if "agent_id" in adapted else (args[3] if len(args) > 3 else None)
    if not allow_flag and agent_id:
        try:
            from yarvelle_core.constants.api import SSE_EVENT_ERROR
            from yarvelle_core.loaders.agent_loader import find_agent_dir, load_agent

            ws_root = getattr(service, "workspace_root", None)
            if ws_root is not None:
                agent_dir = find_agent_dir(ws_root / "agents", str(agent_id))
                if agent_dir is not None:
                    agent, _, _ = load_agent(agent_dir, ws_root / "skills")
                    rc = getattr(agent.risk_class, "value", str(agent.risk_class))
                    if rc == "assist":
                        err_msg = (
                            f"Agent '{agent_id}' is classified as assist. "
                            "Execution is forbidden without explicit consent (allow_assist=True)."
                        )
                        return adapted, [{"type": SSE_EVENT_ERROR, "message": err_msg}]
        except Exception:
            pass

    return adapted, None


def adapt_legacy_core_chat_request(request: Any, core_service_cls: Any) -> Any:
    """Bridges raw dict chat requests carrying allow_assist onto yarvelle-core 0.2.4."""
    import inspect

    if not isinstance(request, dict):
        return request
    if "allow_assist" in inspect.signature(core_service_cls.execute_turn).parameters:
        return request
    if "allow_assist" in request and "allow_clinical" not in request:
        return {**request, "allow_clinical": bool(request["allow_assist"])}
    return request


__all__ = [
    "HealthSafetyPolicy",
    "CarefoldHealthSafetyPolicy",
    "adapt_legacy_core_chat_request",
    "adapt_legacy_core_turn_kwargs",
]

