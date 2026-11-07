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

"""Critic and self-correction loop node (F-28).

Increments reflection counter, generates self-correction feedback prompts,
preserves previous output attempts, and enforces strict max_reflections retry ceilings.
"""

from __future__ import annotations

from typing import Any, Dict, List
from carefold.constants.defaults import DEFAULT_MAX_REFLECTIONS
from carefold.workflows.nodes.base import BaseNode


class ReflectionNode(BaseNode):
    """Critic and self-correction loop capped by max retries."""

    def __init__(
        self,
        max_reflections: int = DEFAULT_MAX_REFLECTIONS,
        name: str = "reflection",
    ) -> None:
        super().__init__(name=name)
        self.max_reflections = max_reflections

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluates retry budget and increments reflection count."""
        raw_count = state.get("reflection_count", 0)
        current_count = max(0, int(raw_count))
        max_refl = int(state.get("max_reflections", self.max_reflections))

        # Ceiling check: if max_reflections is 0 or current count reached ceiling
        if max_refl <= 0 or current_count >= max_refl:
            return {
                "reflection_count": current_count,
                "next_step": "done",
                "critique": "Maximum reflection retries reached. Halting self-correction loop.",
                "previous_attempts": list(state.get("previous_attempts", [])),
            }

        new_count = current_count + 1
        previous_attempts = list(state.get("previous_attempts", []))
        if state.get("output"):
            previous_attempts.append(str(state["output"]))

        critique = (
            f"Self-correction directive (Attempt {new_count} of {max_refl}): "
            f"The previous response violated clinical safety guardrails ({state.get('refusal_reason', 'clinical intent')}). "
            f"Please revise your answer to provide wellness and care navigation support only. "
            f"Do not provide medical diagnosis, dosage calculations, or clinical treatment advice."
        )

        next_step = "agent"

        return {
            "reflection_count": new_count,
            "next_step": next_step,
            "critique": critique,
            "previous_attempts": previous_attempts,
        }


__all__ = ["ReflectionNode"]
