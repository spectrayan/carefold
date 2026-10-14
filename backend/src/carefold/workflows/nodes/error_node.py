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

"""Graceful error recovery and standardized response formatting node (F-32).

Catches runtime exceptions, cleanses stack traces and filesystem paths to prevent
information disclosure, maps to standard error codes via errors.yaml, and formats
a safe user-facing error response.
"""

from __future__ import annotations

import re
from typing import Any, Dict

from carefold.resources.loader import get_resource_loader
from carefold.workflows.nodes.base import BaseNode


class ErrorNode(BaseNode):
    """Graceful error recovery and standardized response formatting."""

    _PATH_CLEANSE_RE = re.compile(
        r"(/Users/[^\s:,'\"\)]+|/home/[^\s:,'\"\)]+|/[a-zA-Z0-9_\-\.]+(?:/[a-zA-Z0-9_\-\.]+)+|[A-Za-z]:\\[^\s:,'\"\)]+)",
        re.IGNORECASE,
    )
    _TRACE_CLEANSE_RE = re.compile(r'File\s+"[^"]+",\s+line\s+\d+,\s+in\s+\w+')

    def __init__(self, name: str = "error") -> None:
        super().__init__(name=name)

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Catches and sanitizes runtime errors."""
        raw_exc = state.get("error_exception")
        raw_err = state.get("error")

        if raw_exc is not None:
            err_msg = str(raw_exc)
        elif raw_err is not None:
            err_msg = str(raw_err)
        else:
            err_msg = "An unexpected internal error occurred."

        # Sanitize filesystem paths and stack traces
        sanitized = self._PATH_CLEANSE_RE.sub("[REDACTED_PATH]", err_msg)
        sanitized = self._TRACE_CLEANSE_RE.sub("[REDACTED_TRACE]", sanitized)
        sanitized = re.sub(r"/(?:Users|home)/[^\s,;'\"]+", "[REDACTED_PATH]", sanitized)

        # Standard error lookup from errors.yaml
        loader = get_resource_loader()
        error_key = state.get("error_key", "internal_error")
        user_message = loader.format_error(error_key, detail=sanitized)
        status_code = loader.get_error_status_code(error_key)

        return {
            "error": sanitized,
            "error_message": user_message,
            "status_code": status_code,
            "output": user_message,
            "messages": [
                {
                    "role": "assistant",
                    "content": f"I apologize, but an issue occurred while processing your request: {user_message}",
                }
            ],
            "next_step": "done",
        }


__all__ = ["ErrorNode"]
