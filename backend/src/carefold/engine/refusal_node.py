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

"""Refusal node that emits Carefold SAFE_REFUSAL_TEMPLATE."""

from __future__ import annotations

from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage

from carefold.safety.emergency import EMERGENCY_REFERRAL_MESSAGE
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE
from yarvelle_core.workflows.nodes.base import BaseNode


def _is_emergency(state: Dict[str, Any], reason: str) -> bool:
    return bool(state.get("emergency_red_flags")) or str(reason).startswith("emergency_red_flag")


class CarefoldRefusalNode(BaseNode):
    """Terminates the turn with Carefold's safe-refusal template."""

    def __init__(self, name: str = "refusal") -> None:
        super().__init__(name=name)

    async def __call__(self, state: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        return await self.execute(state, **kwargs)

    async def execute(self, state: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        del kwargs
        refusal_reason = state.get("refusal_reason") or "safety_policy"
        if _is_emergency(state, refusal_reason):
            # The emergency referral leads (it names 911 and 988), followed by
            # the standard template so clients still find it.
            referral = state.get("refusal_message") or EMERGENCY_REFERRAL_MESSAGE
            if "911" not in referral or "988" not in referral:
                referral = EMERGENCY_REFERRAL_MESSAGE
            refusal_text = f"{referral}\n\n{SAFE_REFUSAL_TEMPLATE}"
        else:
            refusal_text = state.get("refusal_message") or SAFE_REFUSAL_TEMPLATE
            # Prefer the Carefold template for API/eval compatibility.
            if SAFE_REFUSAL_TEMPLATE not in refusal_text:
                refusal_text = SAFE_REFUSAL_TEMPLATE
        ai_message = AIMessage(content=refusal_text)
        return {
            "messages": [ai_message],
            "output": refusal_text,
            "refusal_message": refusal_text,
            "refusal_reason": refusal_reason,
            "is_refusal": True,
            "refused": True,
            "tool_calls": [],
            "next_step": "done",
        }


__all__ = ["CarefoldRefusalNode"]
