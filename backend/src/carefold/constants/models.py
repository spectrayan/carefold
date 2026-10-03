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

"""Carefold model and provider constants.

Defines supported LLM provider names, aliases, default model configurations,
timeouts, and temperature settings.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# ============================================================================
# 1. Provider Identifiers & Sets
# ============================================================================

PROVIDER_OLLAMA: str = "ollama"
PROVIDER_GOOGLE: str = "google"
PROVIDER_ANTHROPIC: str = "anthropic"
PROVIDER_OPENAI: str = "openai"
PROVIDER_CUSTOM: str = "custom"
PROVIDER_MOCK: str = "mock"

# Core production providers
SUPPORTED_PROVIDERS: List[str] = [
    PROVIDER_OLLAMA,
    PROVIDER_GOOGLE,
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    PROVIDER_CUSTOM,
]

# Aliases mapped to canonical provider names
PROVIDER_ALIASES: Dict[str, str] = {
    "ollama": PROVIDER_OLLAMA,
    "google": PROVIDER_GOOGLE,
    "gemini": PROVIDER_GOOGLE,
    "anthropic": PROVIDER_ANTHROPIC,
    "claude": PROVIDER_ANTHROPIC,
    "openai": PROVIDER_OPENAI,
    "custom": PROVIDER_CUSTOM,
    "local": PROVIDER_CUSTOM,
}


# ============================================================================
# 2. Default Model Names
# ============================================================================

DEFAULT_MODEL: str = "llama3.2"
DEFAULT_OLLAMA_MODEL: str = "llama3.2"
DEFAULT_GOOGLE_MODEL: str = "gemini-2.0-flash"
DEFAULT_ANTHROPIC_MODEL: str = "claude-3-5-sonnet-latest"
DEFAULT_OPENAI_MODEL: str = "gpt-4o"
DEFAULT_CUSTOM_MODEL: str = "custom"
DEFAULT_MOCK_MODEL: str = "carefold-mock"

DEFAULT_MODELS: Dict[str, str] = {
    PROVIDER_OLLAMA: DEFAULT_OLLAMA_MODEL,
    PROVIDER_GOOGLE: DEFAULT_GOOGLE_MODEL,
    PROVIDER_ANTHROPIC: DEFAULT_ANTHROPIC_MODEL,
    PROVIDER_OPENAI: DEFAULT_OPENAI_MODEL,
    PROVIDER_CUSTOM: DEFAULT_CUSTOM_MODEL,
}

# Known supported models by provider
GOOGLE_MODELS: Tuple[str, ...] = ("gemini-2.0-flash", "gemini-1.5-pro")
ANTHROPIC_MODELS: Tuple[str, ...] = ("claude-3-5-sonnet-latest", "claude-3-5-haiku")
OPENAI_MODELS: Tuple[str, ...] = ("gpt-4o", "gpt-4o-mini")


# ============================================================================
# 3. Timeouts & Token Limits
# ============================================================================

DEFAULT_TIMEOUT_SECONDS: float = 30.0
DEFAULT_TIMEOUT: float = 30.0  # Alias expected by tests
DEFAULT_MODEL_TIMEOUT_SECONDS: float = 30.0
HEALTH_CHECK_TIMEOUT_SECONDS: float = 2.0
HTTP_CLIENT_TIMEOUT_SECONDS: float = 3.0

# Temperature defaults: E2E tests strictly assert DEFAULT_TEMPERATURE == 0.0 for clinical determinism
DEFAULT_TEMPERATURE: float = 0.0
DEFAULT_DETERMINISTIC_TEMPERATURE: float = 0.0
DEFAULT_CREATIVE_TEMPERATURE: float = 0.2

DEFAULT_MAX_TOKENS: int = 2048


# ============================================================================
# 4. Endpoints & URLs
# ============================================================================

DEFAULT_OLLAMA_URL: str = "http://127.0.0.1:11434/v1"
OLLAMA_MODELS_PATH: str = "/models"
OLLAMA_CHAT_PATH: str = "/chat/completions"


# ============================================================================
# 5. Environment Variable Names
# ============================================================================

ENV_GOOGLE_API_KEYS: Tuple[str, ...] = ("GOOGLE_API_KEY", "GEMINI_API_KEY")
ENV_ANTHROPIC_API_KEYS: Tuple[str, ...] = ("ANTHROPIC_API_KEY",)
ENV_OPENAI_API_KEYS: Tuple[str, ...] = ("OPENAI_API_KEY",)
ENV_CUSTOM_API_KEYS: Tuple[str, ...] = ("CUSTOM_API_KEY", "OPENAI_API_KEY")
ENV_OLLAMA_URLS: Tuple[str, ...] = ("OLLAMA_URL", "OLLAMA_BASE_URL", "CAREFOLD_OLLAMA_URL")
ENV_CUSTOM_URLS: Tuple[str, ...] = ("CUSTOM_BASE_URL", "OPENAI_BASE_URL")
