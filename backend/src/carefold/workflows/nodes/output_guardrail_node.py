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

"""Output refusal guardrail and compliance disclaimer node (F-27).

Inspects generated model completion. If clinical advice or prohibited intent
is detected, sets refusal flag and routes to self-correction reflection.
Appends compliance disclaimers to valid responses.
"""

from __future__ import annotations

from typing import Any, Dict, List
from langchain_core.messages import AIMessage

from carefold.resources.loader import get_resource_loader
from carefold.safety.classifier import check_safety_refusal, is_hard_refusal_reason
from carefold.workflows.nodes.base import BaseNode


class OutputGuardrailNode(BaseNode):
    """Verifies output safety and appends compliance disclaimers."""

    def __init__(self, name: str = "output_guardrail") -> None:
        super().__init__(name=name)

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Checks output text against clinical refusal boundaries."""
        output_text = state.get("output", "")
        if not output_text:
            messages: List[Any] = state.get("messages", [])
            for m in reversed(messages):
                msg_type = getattr(m, "type", "")
                if msg_type in ("human", "user") or (isinstance(m, dict) and m.get("role") in ("user", "human")):
                    break
                if isinstance(m, AIMessage) and getattr(m, "content", ""):
                    output_text = str(getattr(m, "content", "") or "")
                    break
                elif isinstance(m, dict) and m.get("role") in ("assistant", "ai") and m.get("content"):
                    output_text = str(m.get("content", ""))
                    break

        safety_check = check_safety_refusal(output_text)

        # Safety refusal gate
        if safety_check.refused:
            reason = safety_check.reason or "forbidden_intent:medical_prohibited"
            is_hard = is_hard_refusal_reason(reason)
            return {
                "is_refusal": True,
                "refused": True,
                "refusal_reason": reason,
                "boundary_warning": not is_hard,
                "boundary_reason": reason if not is_hard else None,
                "next_step": "reflection",
                "is_compliant": False,
                "compliance_metadata": {
                    "compliant": False,
                    "reason": reason,
                    "boundary_warning": not is_hard,
                },
            }

        # Tier 2 (Soft Clinical Boundary Notice) and Compliant Output:
        # Preserve full output text, clean robotic preambles, and append compliance disclaimer.
        import re
        pattern = r"^(?:(?:\*|_){0,2}(?:(?:Based on|According to|From) (?:the )?(?:provided )?reference (?:document|guide|material|checklist|information|docs?)(?: provided)?)[,:]?(?:\*|_){0,2}[,:]?\s*)"
        cleaned_output = re.sub(pattern, "", output_text.lstrip(), flags=re.IGNORECASE).lstrip("*_ \t")
        if cleaned_output and cleaned_output != output_text:
            cleaned_output = cleaned_output[0].upper() + cleaned_output[1:] if len(cleaned_output) > 1 else cleaned_output.upper()
            output_text = cleaned_output

        # Appends standard compliance disclaimer
        loader = get_resource_loader()
        header_text = loader.get_disclaimer_header_text()
        disclaimer_clause = f"\n\n*Disclaimer: {header_text}*"

        final_output = output_text
        if header_text and header_text.lower() not in output_text.lower():
            final_output = f"{output_text}{disclaimer_clause}"

        boundary_warning = bool(safety_check.refused and not is_hard_refusal_reason(safety_check.reason))
        boundary_reason = safety_check.reason if boundary_warning else None

        return {
            "is_refusal": False,
            "refused": False,
            "boundary_warning": boundary_warning,
            "boundary_reason": boundary_reason,
            "is_compliant": True,
            "output": final_output,
            "compliance_disclaimer": header_text,
            "disclaimer": header_text,
            "compliance_metadata": {
                "compliant": True,
                "has_disclaimer": True,
                "boundary_warning": boundary_warning,
                "boundary_reason": boundary_reason,
            },
            "next_step": "suggestion",
        }



__all__ = ["OutputGuardrailNode"]
