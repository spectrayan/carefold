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

"""Base model provider abstract base class and provider exception hierarchy.

Defines the strategy interface for all Carefold model providers
(Ollama, Google, Anthropic, OpenAI, Custom) and standard provider errors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging
from typing import Any, Dict, List, Optional

try:
    from langchain_core.language_models.chat_models import BaseChatModel
except ImportError:
    BaseChatModel = object  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


# ============================================================================
# Provider Exceptions Hierarchy
# ============================================================================

class ProviderError(Exception):
    """Base exception for all model provider errors."""
    pass


class ProviderConfigurationError(ProviderError, ValueError):
    """Raised when provider configuration parameters (e.g. base_url) are missing or invalid."""
    pass


class ProviderAuthenticationError(ProviderError, ValueError):
    """Raised when credentials / API keys required by a provider are missing or invalid."""
    pass


class UnsupportedModelError(ProviderError, ValueError):
    """Raised when an unsupported or unrecognized model is requested from a provider."""
    pass


# ============================================================================
# Base Model Provider Abstract Class
# ============================================================================

class BaseModelProvider(ABC):
    """Abstract Strategy interface for Carefold LLM chat model providers.

    Subclasses must implement:
    - create_model: Instantiates and returns a configured BaseChatModel.
    - get_supported_models: Returns a list of supported model name identifiers.
    - validate_credentials: Validates that required credentials or connection endpoints exist.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Stores arbitrary provider-level configuration options."""
        self._provider_kwargs: Dict[str, Any] = kwargs

    @abstractmethod
    def create_model(
        self,
        model: str,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> BaseChatModel:
        """Instantiate and return a LangChain BaseChatModel for this provider.

        Args:
            model: Model identifier or name.
            temperature: Sampling temperature (defaults to 0.0 for clinical determinism).
            **kwargs: Additional provider-specific parameters (e.g., timeout, streaming,
                     headers, max_tokens).

        Returns:
            An instantiated and configured BaseChatModel instance.

        Raises:
            ProviderConfigurationError: If required configuration (e.g. base_url) is missing.
            ProviderAuthenticationError: If required credentials / API keys are missing.
        """
        ...

    @abstractmethod
    def get_supported_models(self) -> List[str]:
        """Return a list of known or supported model identifiers for this provider."""
        ...

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Validate whether the required credentials or endpoint configurations are present.

        Returns:
            True if credentials / configurations are present and valid, False otherwise.
            This method should not raise exceptions for missing credentials; it safely returns False.
        """
        ...


__all__ = [
    "BaseModelProvider",
    "ProviderError",
    "ProviderConfigurationError",
    "ProviderAuthenticationError",
    "UnsupportedModelError",
]
