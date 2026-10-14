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

"""Concrete Custom model provider strategy for OpenAI-compatible endpoints.

Supports arbitrary local or remote OpenAI-compatible servers (vLLM, LMStudio,
LocalAI, llama.cpp, LiteLLM) via langchain_openai.ChatOpenAI.
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
    DEFAULT_CUSTOM_MODEL,
    DEFAULT_MODEL_TIMEOUT_SECONDS,
    DEFAULT_TEMPERATURE,
    ENV_CUSTOM_API_KEYS,
    ENV_CUSTOM_URLS,
    PROVIDER_CUSTOM,
)
from carefold.model.providers.base import (
    BaseModelProvider,
    ProviderConfigurationError,
)

logger = logging.getLogger(__name__)


class CustomProvider(BaseModelProvider):
    """Concrete model provider strategy for OpenAI-compatible custom endpoints.

    Key characteristics:
    - Targets user-specified base_url (vLLM, LMStudio, self-hosted LLM endpoints).
    - Accepts custom headers (e.g. authentication or routing headers).
    - Resolves API key from parameter, env vars, or defaults to dummy 'custom' key
      for keyless local OpenAI-compatible endpoints.
    - Raises ProviderConfigurationError if base_url is missing when creating a model.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        streaming: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialize the Custom provider strategy.

        Args:
            base_url: OpenAI-compatible endpoint URL (e.g., 'http://localhost:8000/v1').
            api_key: Optional API key. Defaults to env var or 'custom' dummy key if omitted.
            model: Default model identifier (defaults to 'custom').
            headers: Optional HTTP headers dictionary to include with requests.
            timeout: Request timeout in seconds (defaults to 30.0).
            temperature: Sampling temperature (defaults to 0.0 for clinical determinism).
            streaming: Whether streaming is enabled by default.
            **kwargs: Extra parameters passed to the underlying LangChain chat model.
        """
        super().__init__(**kwargs)

        # Resolve base_url:
        # Precedence: 1. explicit parameter -> 2. $CUSTOM_BASE_URL -> 3. $OPENAI_BASE_URL
        resolved_url = base_url or kwargs.get("baseUrl")
        if not resolved_url:
            for env_var in ENV_CUSTOM_URLS:
                val = os.getenv(env_var)
                if val and val.strip():
                    resolved_url = val.strip()
                    break

        if resolved_url and str(resolved_url).strip():
            raw_url = str(resolved_url).strip().rstrip("/")
            from carefold.model.egress import validate_model_endpoint
            self.base_url = validate_model_endpoint(PROVIDER_CUSTOM, raw_url)
        else:
            self.base_url = None

        # Resolve api_key:
        # Precedence: 1. explicit parameter -> 2. $CUSTOM_API_KEY -> 3. $OPENAI_API_KEY -> 4. 'custom' dummy
        resolved_key = api_key or kwargs.get("apiKey")
        if not resolved_key:
            for env_var in ENV_CUSTOM_API_KEYS:
                val = os.getenv(env_var)
                if val and val.strip():
                    resolved_key = val.strip()
                    break

        self.api_key: Optional[str] = resolved_key.strip() if (resolved_key and str(resolved_key).strip()) else None

        self.model: str = model or DEFAULT_CUSTOM_MODEL
        self.headers: Dict[str, str] = dict(headers) if headers else {}
        self.timeout: float = timeout if timeout is not None else DEFAULT_MODEL_TIMEOUT_SECONDS
        self.temperature: float = temperature
        self.streaming: bool = streaming
        self.extra_kwargs: Dict[str, Any] = kwargs

    def get_supported_models(self) -> List[str]:
        """Return supported model identifiers for this custom endpoint."""
        return [self.model, "custom", "default"]

    def validate_credentials(self) -> bool:
        """Validate whether the custom endpoint has a valid base_url configured.

        Returns:
            True if base_url is a non-empty string, False otherwise.
        """
        return bool(self.base_url and isinstance(self.base_url, str) and self.base_url.strip())

    def create_model(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        """Instantiate and return a LangChain ChatOpenAI instance targeting the custom endpoint.

        Args:
            model: Model identifier override. Defaults to provider default.
            temperature: Sampling temperature override. Defaults to provider temperature (0.0).
            **kwargs: Call-site overrides (base_url, api_key, headers, timeout, streaming, etc.).

        Returns:
            Configured LangChain ChatOpenAI instance.

        Raises:
            ProviderConfigurationError: If base_url is missing, empty, or whitespace-only.
            ImportError: If langchain-openai is not installed.
        """
        # Resolve effective base_url with call-site override
        raw_url = kwargs.pop("base_url", kwargs.pop("baseUrl", self.base_url))
        if not raw_url or not str(raw_url).strip():
            raise ProviderConfigurationError(
                "Base URL for custom provider is required. "
                "Please specify 'base_url' (or 'baseUrl') in the request settings "
                "or set the $CUSTOM_BASE_URL environment variable on the server."
            )
        effective_base_url = str(raw_url).strip().rstrip("/")

        # Resolve effective API key: call-site override -> instance key -> 'custom' dummy
        raw_key = kwargs.pop("api_key", kwargs.pop("apiKey", self.api_key))
        effective_api_key = raw_key.strip() if (raw_key and str(raw_key).strip()) else "custom"

        resolved_model = model or kwargs.pop("model_name", None) or self.model or DEFAULT_CUSTOM_MODEL
        effective_temp = temperature if temperature is not None else self.temperature
        effective_timeout = kwargs.pop("timeout", self.timeout)
        effective_streaming = kwargs.pop("streaming", self.streaming)

        # Merge headers: instance headers + call-site headers override
        call_headers = kwargs.pop("headers", None)
        effective_headers = {**self.headers}
        if call_headers and isinstance(call_headers, dict):
            effective_headers.update(call_headers)

        try:
            from langchain_openai import ChatOpenAI
        except ImportError as err:
            raise ImportError(
                "Package 'langchain-openai' is required for CustomProvider. "
                "Please install it with 'pip install langchain-openai'."
            ) from err

        openai_kwargs: Dict[str, Any] = {
            "model": resolved_model,
            "base_url": effective_base_url,
            "api_key": effective_api_key,
            "temperature": effective_temp,
            "timeout": effective_timeout,
            "streaming": effective_streaming,
        }
        if effective_headers:
            openai_kwargs["default_headers"] = effective_headers

        extra = {**self.extra_kwargs, **kwargs}
        extra.pop("base_url", None)
        extra.pop("baseUrl", None)
        extra.pop("api_key", None)
        extra.pop("apiKey", None)
        extra.pop("model", None)
        extra.pop("temperature", None)
        extra.pop("timeout", None)
        extra.pop("streaming", None)
        openai_kwargs.update(extra)

        return ChatOpenAI(**openai_kwargs)


__all__ = ["CustomProvider"]
