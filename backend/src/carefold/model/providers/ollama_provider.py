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

"""Concrete Ollama model provider strategy for local and private LLMs.

Supports local OpenAI-compatible endpoint or native Ollama server.
Keyless by default, with automatic fallback from langchain_ollama -> langchain_community -> langchain_openai.
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
    DEFAULT_MODEL_TIMEOUT_SECONDS,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_TEMPERATURE,
    ENV_OLLAMA_URLS,
    PROVIDER_OLLAMA,
)
from carefold.model.providers.base import (
    BaseModelProvider,
    ProviderConfigurationError,
)

logger = logging.getLogger(__name__)

# Known common local Ollama models for listing and defaults
KNOWN_OLLAMA_MODELS: List[str] = [
    DEFAULT_OLLAMA_MODEL,  # "llama3.2"
    "llama3.1",
    "llama3",
    "mistral",
    "phi3",
    "qwen2.5",
    "gemma2",
]


class OllamaProvider(BaseModelProvider):
    """Concrete model provider strategy for local Ollama chat models.

    Key characteristics:
    - Zero API keys required (keyless local execution).
    - Configurable host/base_url via kwargs, environment variables, or defaults.
    - Default model: 'llama3.2'.
    - Handles timeout and streaming configurations.
    - Uses ChatOllama (via langchain_ollama or langchain_community) or ChatOpenAI as fallback.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        host: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        streaming: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialize the Ollama provider strategy.

        Args:
            base_url: Base URL for Ollama endpoint (e.g., 'http://127.0.0.1:11434/v1').
            host: Alternative alias for host / endpoint (e.g., 'http://localhost:11434').
            model: Default model identifier (defaults to 'llama3.2').
            timeout: Request timeout in seconds (defaults to 30.0).
            temperature: Default sampling temperature (defaults to 0.0 for clinical determinism).
            streaming: Whether streaming is enabled by default.
            **kwargs: Extra parameters passed to the underlying LangChain chat model.
        """
        super().__init__(**kwargs)

        # Resolve endpoint with precedence:
        # 1. Explicit base_url or host parameter
        # 2. Server environment variables ($OLLAMA_BASE_URL, $CAREFOLD_OLLAMA_URL)
        # 3. Settings config (if available)
        # 4. DEFAULT_OLLAMA_URL constant
        url = base_url or host or kwargs.get("baseUrl")
        if not url:
            for env_var in ENV_OLLAMA_URLS:
                val = os.getenv(env_var)
                if val and val.strip():
                    url = val.strip()
                    break
        if not url:
            try:
                from carefold.config import settings
                url = settings.ollama_url
            except Exception:
                url = DEFAULT_OLLAMA_URL

        clean_url = str(url).strip().rstrip("/")
        self.base_url: str = clean_url
        self.host: str = clean_url  # Exposed for host-attribute inspections
        self.model: str = model or DEFAULT_OLLAMA_MODEL
        self.timeout: float = timeout if timeout is not None else DEFAULT_MODEL_TIMEOUT_SECONDS
        self.temperature: float = temperature
        self.streaming: bool = streaming
        self.extra_kwargs: Dict[str, Any] = kwargs

    def get_supported_models(self) -> List[str]:
        """Return a list of supported Ollama models, including configured default."""
        models = [self.model]
        for m in KNOWN_OLLAMA_MODELS:
            if m not in models:
                models.append(m)
        return models

    def validate_credentials(self) -> bool:
        """Validate provider configuration.

        Local Ollama requires no API key. Verifies that a non-empty base URL is configured.
        """
        return bool(self.base_url and isinstance(self.base_url, str) and self.base_url.strip())

    def create_model(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        """Instantiate and return a LangChain ChatOllama or ChatOpenAI model targeting Ollama.

        Args:
            model: Model identifier (e.g., 'llama3.2', 'llama3'). Defaults to provider default.
            temperature: Sampling temperature override. Defaults to provider temperature (0.0).
            **kwargs: Additional invocation overrides (timeout, streaming, etc.).

        Returns:
            An instantiated LangChain BaseChatModel instance.
        """
        model_name = model or kwargs.pop("model_name", None) or self.model or DEFAULT_OLLAMA_MODEL
        effective_temp = temperature if temperature is not None else self.temperature
        effective_timeout = kwargs.pop("timeout", self.timeout)
        effective_streaming = kwargs.pop("streaming", self.streaming)

        call_url = kwargs.pop("base_url", kwargs.pop("baseUrl", None))
        effective_base_url = str(call_url).strip().rstrip("/") if call_url and str(call_url).strip() else self.base_url
        call_key = kwargs.pop("api_key", kwargs.pop("apiKey", None))
        effective_api_key = str(call_key).strip() if call_key and str(call_key).strip() else PROVIDER_OLLAMA

        # Merge provider kwargs with call-site kwargs
        merged_kwargs = {**self.extra_kwargs, **kwargs}
        merged_kwargs.pop("base_url", None)
        merged_kwargs.pop("baseUrl", None)
        merged_kwargs.pop("api_key", None)
        merged_kwargs.pop("apiKey", None)

        # 1. Attempt langchain_ollama.ChatOllama
        try:
            from langchain_ollama import ChatOllama
            from pydantic import SecretStr

            if not hasattr(ChatOllama, "model_name"):
                ChatOllama.model_name = property(lambda self: self.model)
            if not hasattr(ChatOllama, "openai_api_base"):
                ChatOllama.openai_api_base = property(
                    lambda self: f"{self.base_url}/v1" if not str(self.base_url).endswith("/v1") else str(self.base_url)
                )
            if not hasattr(ChatOllama, "openai_api_key"):
                ChatOllama.openai_api_key = property(
                    lambda self: getattr(self, "_custom_api_key", SecretStr("ollama"))
                )

            native_url = effective_base_url.removesuffix("/v1").removesuffix("/")
            model_inst = ChatOllama(
                model=model_name,
                base_url=native_url,
                temperature=effective_temp,
                timeout=effective_timeout,
                **merged_kwargs,
            )
            model_inst.__dict__["_custom_api_key"] = SecretStr(effective_api_key)
            return model_inst
        except ImportError:
            pass

        # 2. Attempt langchain_community.chat_models.ChatOllama
        try:
            from langchain_community.chat_models import ChatOllama
            native_url = effective_base_url.removesuffix("/v1").removesuffix("/")
            return ChatOllama(
                model=model_name,
                base_url=native_url,
                temperature=effective_temp,
                timeout=effective_timeout,
                **merged_kwargs,
            )
        except ImportError:
            pass

        # 3. Fallback: ChatOpenAI pointing to Ollama's OpenAI-compatible /v1 endpoint
        try:
            from langchain_openai import ChatOpenAI
            openai_url = effective_base_url if effective_base_url.endswith("/v1") else f"{effective_base_url}/v1"
            return ChatOpenAI(
                model=model_name,
                base_url=openai_url,
                api_key=effective_api_key,
                temperature=effective_temp,
                timeout=effective_timeout,
                streaming=effective_streaming,
                **merged_kwargs,
            )
        except ImportError as err:
            raise ImportError(
                "None of 'langchain-ollama', 'langchain-community', or 'langchain-openai' "
                "are installed. Please install 'langchain-ollama' or 'langchain-openai'."
            ) from err


__all__ = ["OllamaProvider", "KNOWN_OLLAMA_MODELS"]
