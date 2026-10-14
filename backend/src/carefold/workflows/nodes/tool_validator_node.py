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

"""Tool output sanitizer and size/format validator (F-26).

Cleans ANSI escape sequences and dangerous control characters, enforces size
ceilings (max_chars), validates JSON formatting, and flags malformed outputs.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from carefold.constants.defaults import MAX_TOOL_OUTPUT_CHARS
from carefold.workflows.nodes.base import BaseNode


class ToolValidatorNode(BaseNode):
    """Sanitizes dangerous escapes and enforces size ceilings on tool outputs."""

    _ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
    _NULL_BYTE_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

    def __init__(
        self,
        max_chars: int = MAX_TOOL_OUTPUT_CHARS,
        name: str = "tool_validator",
    ) -> None:
        super().__init__(name=name)
        self.max_chars = max_chars

    async def execute(
        self,
        state: Dict[str, Any],
        *,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Sanitizes and truncates tool output if necessary."""
        raw_val = state.get("tool_output", "")
        if isinstance(raw_val, (dict, list)):
            text = json.dumps(raw_val)
        else:
            text = str(raw_val or "")

        # 1. Strip dangerous ANSI control sequences and unprintable control bytes
        cleansed = self._ANSI_ESCAPE_RE.sub("", text)
        cleansed = self._NULL_BYTE_RE.sub("", cleansed)

        # 2. Enforce character ceiling
        truncated = False
        if len(cleansed) > self.max_chars:
            truncated = True
            suffix = "\n... [truncated]"
            cleansed = cleansed[: self.max_chars] + suffix

        # 3. JSON structure validation
        is_valid_json: Optional[bool] = None
        stripped = cleansed.strip()
        if (stripped.startswith("{") and stripped.endswith("}")) or (
            stripped.startswith("[") and stripped.endswith("]")
        ):
            try:
                json.loads(stripped)
                is_valid_json = True
            except Exception:
                is_valid_json = False

        return {
            "sanitized_output": cleansed,
            "tool_output": cleansed,
            "is_valid": is_valid_json is not False,
            "validation_metadata": {
                "truncated": truncated,
                "original_length": len(text),
                "sanitized_length": len(cleansed),
                "is_valid_json": is_valid_json,
            },
            "next_step": "agent",
        }


__all__ = ["ToolValidatorNode"]
