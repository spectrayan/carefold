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

"""Concrete Google Gemini model provider strategy.

Provides integration with Google Gemini chat models (gemini-2.0-flash, gemini-1.5-pro).
Supports API key precedence (request kwargs -> constructor -> environment variables)
and lazy imports for optional cloud packages.
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
    DEFAULT_GOOGLE_MODEL,
    DEFAULT_MODEL_TIMEOUT_SECONDS,
    DEFAULT_TEMPERATURE,
    ENV_GOOGLE_API_KEYS,
    GOOGLE_MODELS,
    PROVIDER_GOOGLE,
)
from carefold.model.factory import (
    MissingApiKeyError,
    resolve_api_key,
)
from carefold.model.providers.base import BaseModelProvider

logger = logging.getLogger(__name__)

# Known Google Gemini models for listing
KNOWN_GOOGLE_MODELS: List[str] = list(GOOGLE_MODELS) + [
    "gemini-1.5-flash",
    "gemini-1.0-pro",
]


class GoogleProvider(BaseModelProvider):
    """Concrete model provider strategy for Google Gemini chat models.

    Key characteristics:
    - Uses LangChain's ChatGoogleGenerativeAI from langchain-google-genai.
    - Resolves credentials from kwargs ('api_key', 'apiKey', 'google_api_key'), constructor,
      or environment variables ($GOOGLE_API_KEY, $GEMINI_API_KEY).
    - Default model: 'gemini-2.0-flash'.
    - Implements lazy loading to prevent import errors when langchain-google-genai is absent.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        streaming: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialize the Google Gemini provider strategy.

        Args:
            api_key: Optional Google API key override.
            model: Default model identifier (defaults to 'gemini-2.0-flash').
            timeout: Request timeout in seconds (defaults to 30.0).
            temperature: Sampling temperature (defaults to 0.0 for clinical determinism).
            streaming: Whether streaming is enabled by default.
            **kwargs: Extra parameters passed to ChatGoogleGenerativeAI.
        """
        super().__init__(**kwargs)
        self.api_key: Optional[str] = api_key.strip() if api_key and api_key.strip() else None
        self.model: str = model or DEFAULT_GOOGLE_MODEL
        self.timeout: float = timeout if timeout is not None else DEFAULT_MODEL_TIMEOUT_SECONDS
        self.temperature: float = temperature
        self.streaming: bool = streaming
        self.extra_kwargs: Dict[str, Any] = kwargs

    def get_supported_models(self) -> List[str]:
        """Return list of supported Google Gemini model identifiers."""
        models = [self.model]
        for m in KNOWN_GOOGLE_MODELS:
            if m not in models:
                models.append(m)
        return models

    def validate_credentials(self) -> bool:
        """Validate whether a valid Google API key is configured.

        Checks constructor key first, then server environment variables ($GOOGLE_API_KEY, $GEMINI_API_KEY).
        Returns:
            True if an API key is available, False otherwise.
        """
        if self.api_key:
            return True
        for env_var in ENV_GOOGLE_API_KEYS:
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
        """Instantiate and return a LangChain ChatGoogleGenerativeAI model.

        Args:
            model: Model identifier override (defaults to 'gemini-2.0-flash').
            temperature: Sampling temperature override (defaults to provider temperature).
            **kwargs: Call-site overrides (api_key, google_api_key, timeout, streaming, etc.).

        Returns:
            An instantiated ChatGoogleGenerativeAI instance.

        Raises:
            ImportError: If langchain-google-genai package is not installed.
            MissingApiKeyError: If no API key is provided or configured in the environment.
        """
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as err:
            raise ImportError(
                "Package 'langchain-google-genai' is required for provider 'google'. "
                "Please install it with 'pip install langchain-google-genai'."
            ) from err

        # 1. Resolve model name
        resolved_model = model or kwargs.pop("model_name", None) or self.model or DEFAULT_GOOGLE_MODEL

        # 2. Resolve API key with strict precedence: kwargs -> instance -> env vars
        call_key = kwargs.pop("api_key", kwargs.pop("apiKey", kwargs.pop("google_api_key", None)))
        effective_key = call_key or self.api_key
        if not effective_key:
            effective_key = resolve_api_key(PROVIDER_GOOGLE, allow_missing=False)
        if not effective_key or not str(effective_key).strip():
            raise MissingApiKeyError(PROVIDER_GOOGLE, list(ENV_GOOGLE_API_KEYS))

        # 3. Resolve hyperparameters
        effective_temp = temperature if temperature is not None else self.temperature
        effective_timeout = kwargs.pop("timeout", self.timeout)
        effective_streaming = kwargs.pop("streaming", self.streaming)

        extra = {**self.extra_kwargs, **kwargs}
        extra.pop("api_key", None)
        extra.pop("apiKey", None)
        extra.pop("google_api_key", None)
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

        return ChatGoogleGenerativeAI(**params)


__all__ = ["GoogleProvider", "KNOWN_GOOGLE_MODELS"]
