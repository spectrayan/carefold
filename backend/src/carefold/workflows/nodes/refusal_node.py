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

"""Standardized clinical refusal formatter and response node (F-29).

Constructs the standardized Carefold safe refusal response containing:
1. Licensed clinician advisory ("doctor", "physician", "clinician")
2. Acute emergency callout ("911")
3. Disarms pending tool calls and completes the conversation turn (`next_step='done'`).
"""

from __future__ import annotations

from typing import Any, Dict
from langchain_core.messages import AIMessage

from carefold.workflows.nodes.base import BaseNode


class RefusalNode(BaseNode):
    """Standardized refusal disclaimer and response formatter."""

    def __init__(self, name: str = "refusal") -> None:
        super().__init__(name=name)

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Formats the standardized refusal disclaimer and terminates execution turn."""
        refusal_reason = state.get("refusal_reason") or "clinical_safety_policy"

        refusal_text = (
            "I am a wellness and care navigation assistant with Carefold, not a licensed medical professional or emergency service. "
            "I cannot diagnose conditions, prescribe medications, or alter medical treatments. "
            "Please consult your doctor, physician, or qualified clinician for clinical advice and treatment questions. "
            "If you are experiencing a medical emergency, please call 911 or contact local emergency services immediately."
        )

        ai_message = AIMessage(content=refusal_text)

        return {
            "messages": [ai_message],
            "output": refusal_text,
            "refusal_message": refusal_text,
            "refusal_reason": refusal_reason,
            "is_refusal": True,
            "refused": True,
            "tool_calls": [],  # Clear all pending tool calls
            "next_step": "done",
        }


__all__ = ["RefusalNode"]
