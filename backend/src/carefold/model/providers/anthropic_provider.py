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

"""Concrete Anthropic model provider strategy.

Provides integration with Anthropic Claude chat models (claude-3-5-sonnet-latest, claude-3-5-haiku).
Supports API key precedence (request kwargs -> constructor -> environment variables),
explicit authentication validation before model construction, and lazy imports.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

try:
    from langchain_core.language_models.chat_models import BaseChatModel
except ImportError:
    BaseChatModel = object  # type: ignore[assignment,misc]

from carefold.constants.models import (
    ANTHROPIC_MODELS,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_MODEL_TIMEOUT_SECONDS,
    DEFAULT_TEMPERATURE,
    ENV_ANTHROPIC_API_KEYS,
    PROVIDER_ANTHROPIC,
)
from carefold.model.factory import (
    MissingApiKeyError,
    resolve_api_key,
)
from carefold.model.providers.base import BaseModelProvider

logger = logging.getLogger(__name__)

# Known Anthropic models for listing
KNOWN_ANTHROPIC_MODELS: List[str] = list(ANTHROPIC_MODELS) + [
    "claude-3-5-sonnet",
    "claude-3-opus-latest",
    "claude-3-opus",
    "claude-3-haiku",
]


class AnthropicProvider(BaseModelProvider):
    """Concrete model provider strategy for Anthropic Claude models.

    Key characteristics:
    - Uses LangChain's ChatAnthropic.
    - Explicitly validates API keys during create_model() to prevent deferred auth errors.
    - Default model: 'claude-3-5-sonnet-latest'.
    - Implements lazy loading to prevent import errors when langchain-anthropic is absent.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        streaming: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialize the Anthropic provider strategy.

        Args:
            api_key: Optional Anthropic API key override.
            base_url: Optional custom Anthropic endpoint URL.
            model: Default model identifier (defaults to 'claude-3-5-sonnet-latest').
            timeout: Request timeout in seconds (defaults to 30.0).
            temperature: Sampling temperature (defaults to 0.0 for clinical determinism).
            streaming: Whether streaming is enabled by default.
            **kwargs: Extra parameters passed to ChatAnthropic.
        """
        super().__init__(**kwargs)
        self.api_key: Optional[str] = api_key.strip() if api_key and api_key.strip() else None
        self.base_url: Optional[str] = base_url.strip().rstrip("/") if base_url and base_url.strip() else None
        self.model: str = model or DEFAULT_ANTHROPIC_MODEL
        self.timeout: float = timeout if timeout is not None else DEFAULT_MODEL_TIMEOUT_SECONDS
        self.temperature: float = temperature
        self.streaming: bool = streaming
        self.extra_kwargs: Dict[str, Any] = kwargs

    def get_supported_models(self) -> List[str]:
        """Return list of supported Anthropic Claude model identifiers."""
        models = [self.model]
        for m in KNOWN_ANTHROPIC_MODELS:
            if m not in models:
                models.append(m)
        return models

    def validate_credentials(self) -> bool:
        """Validate whether a valid Anthropic API key is configured.

        Checks constructor key first, then server environment variables.
        Returns:
            True if an API key is available, False otherwise.
        """
        if self.api_key:
            return True
        for env_var in ENV_ANTHROPIC_API_KEYS:
            val = os.getenv(env_var)
            if val and val.strip():
                return True
        return False

    def create_model(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        """Instantiate and return a LangChain ChatAnthropic model.

        Args:
            model: Model identifier override (defaults to 'claude-3-5-sonnet-latest').
            temperature: Sampling temperature override (defaults to provider temperature).
            **kwargs: Call-site overrides (api_key, base_url, timeout, streaming, etc.).

        Returns:
            An instantiated ChatAnthropic instance.

        Raises:
            ImportError: If langchain-anthropic package is not installed.
            MissingApiKeyError: If no API key is provided or configured in the environment.
        """
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as err:
            raise ImportError(
                "Package 'langchain-anthropic' is required for provider 'anthropic'. "
                "Please install it with 'pip install langchain-anthropic'."
            ) from err

        # 1. Resolve model name
        resolved_model = model or kwargs.pop("model_name", None) or self.model or DEFAULT_ANTHROPIC_MODEL

        # 2. Resolve API key with strict precedence: kwargs -> instance -> env vars
        call_key = kwargs.pop("api_key", kwargs.pop("apiKey", kwargs.pop("anthropic_api_key", None)))
        effective_key = call_key or self.api_key
        if not effective_key:
            effective_key = resolve_api_key(PROVIDER_ANTHROPIC, allow_missing=False)
        if not effective_key or not str(effective_key).strip():
            raise MissingApiKeyError(PROVIDER_ANTHROPIC, list(ENV_ANTHROPIC_API_KEYS))

        # 3. Resolve base URL if custom endpoint used
        call_base_url = kwargs.pop("base_url", kwargs.pop("baseUrl", None))
        effective_base_url = call_base_url or self.base_url

        # 4. Resolve hyperparameters
        effective_temp = temperature if temperature is not None else self.temperature
        effective_timeout = kwargs.pop("timeout", self.timeout)
        effective_streaming = kwargs.pop("streaming", self.streaming)

        extra = {**self.extra_kwargs, **kwargs}
        extra.pop("base_url", None)
        extra.pop("baseUrl", None)
        extra.pop("api_key", None)
        extra.pop("apiKey", None)
        extra.pop("anthropic_api_key", None)
        extra.pop("model", None)
        extra.pop("temperature", None)
        extra.pop("timeout", None)
        extra.pop("streaming", None)

        params: Dict[str, Any] = {
            "model": resolved_model,
            "api_key": effective_key.strip(),
            "temperature": effective_temp,
            "timeout": effective_timeout,
            "streaming": effective_streaming,
            **extra,
        }
        if effective_base_url:
            params["base_url"] = str(effective_base_url).strip().rstrip("/")

        return ChatAnthropic(**params)


__all__ = ["AnthropicProvider", "KNOWN_ANTHROPIC_MODELS"]
