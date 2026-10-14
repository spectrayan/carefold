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

"""Carefold model provider strategies and central registry.

Provides the Strategy pattern interface (BaseModelProvider), provider exceptions,
central ProviderRegistry, and concrete strategy implementations:
- OllamaProvider: Local Ollama chat models.
- CustomProvider: OpenAI-compatible custom endpoints.
- GoogleProvider: Google Gemini models via langchain-google-genai.
- AnthropicProvider: Anthropic Claude models via langchain-anthropic.
- OpenAIProvider: OpenAI models via langchain-openai.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Type

from carefold.constants.models import (
    PROVIDER_ANTHROPIC,
    PROVIDER_CUSTOM,
    PROVIDER_GOOGLE,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
)
from carefold.model.providers.base import (
    BaseModelProvider,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderError,
    UnsupportedModelError,
)
from carefold.model.providers.anthropic_provider import (
    AnthropicProvider,
    KNOWN_ANTHROPIC_MODELS,
)
from carefold.model.providers.custom_provider import CustomProvider
from carefold.model.providers.google_provider import (
    GoogleProvider,
    KNOWN_GOOGLE_MODELS,
)
from carefold.model.providers.ollama_provider import (
    KNOWN_OLLAMA_MODELS,
    OllamaProvider,
)
from carefold.model.providers.openai_provider import (
    KNOWN_OPENAI_MODELS,
    OpenAIProvider,
)


class ProviderRegistry:
    """Central registry mapping canonical provider identifiers to concrete strategy classes."""

    _registry: Dict[str, Type[BaseModelProvider]] = {
        PROVIDER_OLLAMA: OllamaProvider,
        PROVIDER_GOOGLE: GoogleProvider,
        PROVIDER_ANTHROPIC: AnthropicProvider,
        PROVIDER_OPENAI: OpenAIProvider,
        PROVIDER_CUSTOM: CustomProvider,
    }

    @classmethod
    def register(cls, name: str, provider_cls: Type[BaseModelProvider]) -> None:
        """Register or override a provider strategy class."""
        cls._registry[name.strip().lower()] = provider_cls

    @classmethod
    def get(cls, name: str) -> Optional[Type[BaseModelProvider]]:
        """Retrieve a provider strategy class by canonical name."""
        return cls._registry.get(name.strip().lower())

    @classmethod
    def list_providers(cls) -> List[str]:
        """List all currently registered canonical provider identifiers."""
        return list(cls._registry.keys())

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """Check if a provider identifier is registered."""
        return name.strip().lower() in cls._registry


# Direct mapping for rapid lookup
PROVIDER_CLASSES: Dict[str, Type[BaseModelProvider]] = ProviderRegistry._registry


__all__ = [
    # Base interface & exceptions
    "BaseModelProvider",
    "ProviderError",
    "ProviderConfigurationError",
    "ProviderAuthenticationError",
    "UnsupportedModelError",
    # Registry
    "ProviderRegistry",
    "PROVIDER_CLASSES",
    # Concrete providers
    "OllamaProvider",
    "CustomProvider",
    "GoogleProvider",
    "AnthropicProvider",
    "OpenAIProvider",
    # Model catalogues
    "KNOWN_OLLAMA_MODELS",
    "KNOWN_GOOGLE_MODELS",
    "KNOWN_ANTHROPIC_MODELS",
    "KNOWN_OPENAI_MODELS",
]
