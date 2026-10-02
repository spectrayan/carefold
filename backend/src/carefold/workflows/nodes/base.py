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

"""Base class for all discrete Carefold LangGraph workflow nodes.

Enforces Single Responsibility Principle (SOLID) with an abstract `execute`
method and standard `__call__` dunder for LangGraph node compliance.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging
import re
from typing import Any, Dict, Optional, Sequence

from carefold.workflows.state import AgentState, get_last_user_prompt_text

_PATH_REDACT_REGEX = re.compile(
    r"/(?:private/)?(?:Users|home|root|var|etc|tmp)/[^\s,;'\"]+",
    re.IGNORECASE,
)
_SECRET_REDACT_REGEX = re.compile(
    r"(?:api[_-]?key|secret|token|password)[=:\s]+([a-zA-Z0-9_\-]{8,})",
    re.IGNORECASE,
)


def sanitize_log_message(text: str) -> str:
    """Sanitize sensitive file paths and secret tokens from error/log messages.

    Args:
        text: Raw log message text.

    Returns:
        Sanitized message safe for logging.
    """
    if not text:
        return ""
    # Redact nested absolute filesystem paths
    sanitized = _PATH_REDACT_REGEX.sub("[REDACTED_PATH]", text)
    # Redact credential patterns
    sanitized = _SECRET_REDACT_REGEX.sub("[REDACTED_CREDENTIAL]", sanitized)
    # Redact root user folders
    sanitized = re.sub(r"/(?:Users|home)/[^\s,;'\"]+", "[REDACTED_USER_PATH]", sanitized)
    return sanitized


class BaseNode(ABC):
    """Abstract Base Class for discrete LangGraph workflow nodes.

    Subclasses must implement `async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]`
    to produce partial state updates. The `__call__` dunder delegates directly
    to `execute`, allowing instances to be used as LangGraph node functions.

    Attributes:
        name: Unique or descriptive node name for logging and routing.
    """

    def __init__(self, name: Optional[str] = None, **kwargs: Any) -> None:
        """Initialize base node attributes.

        Args:
            name: Optional human-readable node name; defaults to class name.
            **kwargs: Extra parameters ignored by base class for flexible subclassing.
        """
        self.name = name or self.__class__.__name__
        self._logger = logging.getLogger(f"carefold.workflows.nodes.{self.name}")

    @property
    def node_name(self) -> str:
        """Return the effective node name, falling back to class name."""
        return getattr(self, "name", self.__class__.__name__)

    @property
    def logger(self) -> logging.Logger:
        """Return the effective logger instance."""
        return getattr(self, "_logger", None) or logging.getLogger(
            f"carefold.workflows.nodes.{self.node_name}"
        )

    @abstractmethod
    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute node logic against the provided AgentState.

        Args:
            state: Current AgentState mapping.

        Returns:
            Dictionary containing partial state updates to merge into AgentState.
        """
        raise NotImplementedError("Subclasses of BaseNode must implement execute()")

    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke node execution directly, enabling LangGraph node callable interface.

        Args:
            state: Current AgentState mapping.

        Returns:
            Dictionary containing partial state updates.
        """
        return await self.execute(state)

    def validate_state(
        self, state: Any, required_keys: Optional[Sequence[str]] = None
    ) -> Dict[str, Any]:
        """Validate input state dictionary.

        Args:
            state: State object to validate.
            required_keys: Optional sequence of keys that must exist in state.

        Returns:
            Validated state dictionary.

        Raises:
            TypeError: If state is not a dict / mapping.
        """
        if not isinstance(state, dict):
            raise TypeError(
                f"[{self.node_name}] Expected state to be a dictionary, got {type(state).__name__}"
            )
        if required_keys:
            missing = [k for k in required_keys if k not in state]
            if missing:
                self.log_warning(f"State missing expected keys: {missing}")
        return state

    def get_prompt_text(self, state: Dict[str, Any]) -> str:
        """Extract user prompt text from state messages.

        Args:
            state: Current AgentState.

        Returns:
            Extracted prompt string.
        """
        return get_last_user_prompt_text(state)  # type: ignore[arg-type]

    def log_info(self, message: str, **kwargs: Any) -> None:
        """Log informational message with node context."""
        self.logger.info(f"[{self.node_name}] {message}", **kwargs)

    def log_warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message with node context."""
        self.logger.warning(f"[{self.node_name}] {message}", **kwargs)

    def log_debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message with node context."""
        self.logger.debug(f"[{self.node_name}] {message}", **kwargs)

    def log_error(
        self, message: str, exc: Optional[BaseException] = None, **kwargs: Any
    ) -> None:
        """Log error message with sanitized node context and exception details.

        Args:
            message: Error description.
            exc: Optional exception instance to sanitize and log.
            **kwargs: Extra logging arguments.
        """
        clean_msg = sanitize_log_message(str(message))
        if exc:
            clean_exc = sanitize_log_message(f"{type(exc).__name__}: {exc}")
            self.logger.error(
                f"[{self.node_name}] {clean_msg} | Exception: {clean_exc}",
                **kwargs,
            )
        else:
            self.logger.error(f"[{self.node_name}] {clean_msg}", **kwargs)

    def format_error_response(
        self,
        error_message: str,
        next_step: str = "done",
        **additional_fields: Any,
    ) -> Dict[str, Any]:
        """Generate a standardized error dictionary for node output.

        Args:
            error_message: User-facing error message (sanitized).
            next_step: Target next step for routing (default: 'done').
            **additional_fields: Extra fields to include in state update.

        Returns:
            Dictionary suitable for returning from `execute`.
        """
        clean_error = sanitize_log_message(error_message)
        update: Dict[str, Any] = {
            "error": clean_error,
            "next_step": next_step,
        }
        update.update(additional_fields)
        return update

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.node_name!r}>"


__all__ = ["BaseNode", "sanitize_log_message"]
