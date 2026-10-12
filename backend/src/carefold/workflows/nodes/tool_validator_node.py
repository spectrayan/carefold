# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
