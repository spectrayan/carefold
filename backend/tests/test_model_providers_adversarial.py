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

"""Adversarial Verification Suite for Model Provider Strategies.

Thoroughly stress-tests ModelFactory and provider strategies under adversarial conditions:
1. Rejection of provider="mock" and all case/whitespace variations (must raise UnsupportedProviderError / ValueError).
2. Unknown, empty, whitespace, and non-string providers (None, "", "  ", "unsupported_xyz", numbers, booleans).
3. Case insensitivity and alias resolution ("OLLAMA", "Ollama", "OpEnAi", "Google", "GEMINI", "Claude", etc.).
4. Custom provider base URL normalization (trailing slashes stripped, whitespace stripped, missing base URL errors).
5. Missing credentials for cloud providers (Anthropic, OpenAI, Google) when neither client key nor env var is provided.
6. Strategy interface conformance for all registered providers (BaseModelProvider contract).
7. Production mock purge verification (zero mock files/imports in src/).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List
import pytest

from carefold.constants.models import (
    PROVIDER_ANTHROPIC,
    PROVIDER_CUSTOM,
    PROVIDER_GOOGLE,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    SUPPORTED_PROVIDERS,
)
from carefold.model.factory import (
    ModelFactory,
    MissingApiKeyError,
    MissingConfigurationError,
    UnsupportedProviderError,
    create_chat_model,
    resolve_api_key,
    resolve_base_url,
)
from carefold.model.providers import (
    AnthropicProvider,
    BaseModelProvider,
    CustomProvider,
    GoogleProvider,
    OllamaProvider,
    OpenAIProvider,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderRegistry,
)
from langchain_core.language_models.chat_models import BaseChatModel


# ============================================================================
# Section 1: Provider="mock" Adversarial Rejection
# ============================================================================

@pytest.mark.parametrize("mock_variant", [
    "mock",
    "MOCK",
    "Mock",
    "mOcK",
    "  mock  ",
    "  MOCK  ",
    "offline",
    "OFFLINE",
    "stub",
    "STUB",
])
def test_adversarial_mock_provider_rejected(mock_variant: str):
    """Verify provider='mock' and variants raise UnsupportedProviderError / ValueError."""
    # 1. Via create_chat_model top-level function
    with pytest.raises((UnsupportedProviderError, ValueError)) as exc1:
        create_chat_model(provider=mock_variant)
    assert "Unsupported model provider" in str(exc1.value)

    # 2. Via ModelFactory.create_chat_model
    with pytest.raises((UnsupportedProviderError, ValueError)) as exc2:
        ModelFactory.create_chat_model(provider=mock_variant)
    assert "Unsupported model provider" in str(exc2.value)

    # 3. Via ModelFactory.resolve_provider
    with pytest.raises((UnsupportedProviderError, ValueError)) as exc3:
        ModelFactory.resolve_provider(mock_variant)
    assert "Unsupported model provider" in str(exc3.value)


def test_available_providers_strictly_excludes_mock():
    """Verify get_available_providers() strictly excludes mock, offline, and stub."""
    available = ModelFactory.get_available_providers()
    assert isinstance(available, list)
    for forbidden in ["mock", "offline", "stub"]:
        assert forbidden not in [p.lower() for p in available]
        assert not ProviderRegistry.is_registered(forbidden)


def test_mock_kwargs_stripped_cleanly():
    """Verify legacy mock=True kwargs are purged without crashing or re-enabling mocks."""
    # Passing mock=True should not crash or return a MockChatModel; it returns an Ollama model
    model = create_chat_model(provider="ollama", mock=True, use_mock=True)
    assert not model.__class__.__name__.startswith("Mock")
    assert hasattr(model, "model_name") or hasattr(model, "model")


# ============================================================================
# Section 2: Unknown or Empty Providers
# ============================================================================

def test_provider_none_cleanly_defaults_to_ollama(monkeypatch):
    """Verify passing provider=None defaults cleanly to Ollama."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    model = create_chat_model(provider=None)
    assert model is not None
    model_name = getattr(model, "model_name", getattr(model, "model", None))
    assert model_name == "llama3.2"


@pytest.mark.parametrize("empty_or_blank", [
    "",
    "   ",
    "\t",
    "\n",
    "  \t\n  ",
])
def test_provider_empty_or_whitespace_raises_unsupported(empty_or_blank: str):
    """Verify empty or whitespace strings raise UnsupportedProviderError."""
    with pytest.raises(UnsupportedProviderError) as exc_info:
        create_chat_model(provider=empty_or_blank)
    assert "Unsupported model provider" in str(exc_info.value)


@pytest.mark.parametrize("unknown_provider", [
    "unsupported_xyz",
    "cohere",
    "mistral",
    "deepseek",
    "bedrock",
    "azure",
    "llama",
    "gpt-4o",  # model passed as provider
    "../../etc/passwd",
    "provider; DROP TABLE users;--",
    "\x00nullbyte",
])
def test_provider_unknown_strings_raise_unsupported(unknown_provider: str):
    """Verify unknown and hostile provider strings raise UnsupportedProviderError."""
    with pytest.raises(UnsupportedProviderError) as exc_info:
        create_chat_model(provider=unknown_provider)
    assert "Unsupported model provider" in str(exc_info.value)
    # Error message must list valid supported providers
    assert "ollama" in str(exc_info.value)


@pytest.mark.parametrize("non_string_provider", [
    123,
    3.14,
    False,
    True,
    ["ollama"],
    {"provider": "ollama"},
])
def test_provider_non_string_types_raise_unsupported(non_string_provider: Any):
    """Verify non-string provider types raise UnsupportedProviderError without uncaught exceptions."""
    with pytest.raises(UnsupportedProviderError) as exc_info:
        create_chat_model(provider=non_string_provider)  # type: ignore[arg-type]
    assert "Unsupported model provider" in str(exc_info.value)


# ============================================================================
# Section 3: Case Insensitivity & Aliases
# ============================================================================

@pytest.mark.parametrize("cased_provider, expected_canonical", [
    ("OLLAMA", "ollama"),
    ("Ollama", "ollama"),
    ("oLLaMa", "ollama"),
    ("  OLLAMA  ", "ollama"),
    ("OPENAI", "openai"),
    ("OpenAI", "openai"),
    ("OpEnAi", "openai"),
    ("  OpenAI  ", "openai"),
    ("GOOGLE", "google"),
    ("Google", "google"),
    ("gOoGlE", "google"),
    ("GEMINI", "google"),
    ("Gemini", "google"),
    ("  gemini  ", "google"),
    ("ANTHROPIC", "anthropic"),
    ("Anthropic", "anthropic"),
    ("CLAUDE", "anthropic"),
    ("Claude", "anthropic"),
    ("  claude  ", "anthropic"),
    ("CUSTOM", "custom"),
    ("Custom", "custom"),
    ("LOCAL", "custom"),
    ("Local", "custom"),
    ("  local  ", "custom"),
])
def test_case_insensitivity_and_alias_resolution(cased_provider: str, expected_canonical: str):
    """Verify case variations and aliases resolve to the expected canonical provider."""
    resolved = ModelFactory.resolve_provider(cased_provider)
    assert resolved == expected_canonical


def test_case_insensitive_instantiation():
    """Verify create_chat_model succeeds with mixed casing and aliases."""
    # Ollama
    m1 = create_chat_model(provider="OLLAMA")
    assert hasattr(m1, "model_name") or hasattr(m1, "model")

    # OpenAI
    m2 = create_chat_model(provider="OpEnAi", api_key="dummy-openai-key")
    assert hasattr(m2, "openai_api_key")

    # Google via Gemini alias
    m3 = create_chat_model(provider="GeMiNi", api_key="dummy-gemini-key")
    assert hasattr(m3, "google_api_key")

    # Anthropic via Claude alias
    m4 = create_chat_model(provider="CLAUDE", api_key="dummy-claude-key")
    assert hasattr(m4, "anthropic_api_key")

    # Custom via Local alias
    m5 = create_chat_model(provider="Local", base_url="http://localhost:8000/v1")
    assert m5.openai_api_base == "http://localhost:8000/v1"


# ============================================================================
# Section 4: Custom Provider Base URL Normalization
# ============================================================================

@pytest.mark.parametrize("raw_url, expected_normalized", [
    ("http://localhost:8000/v1/", "http://localhost:8000/v1"),
    ("http://localhost:8000/v1///", "http://localhost:8000/v1"),
    ("http://localhost:8000/v1/////////////////", "http://localhost:8000/v1"),
    ("  http://localhost:8000/v1/  ", "http://localhost:8000/v1"),
    ("  http://localhost:8000/v1///  ", "http://localhost:8000/v1"),
    ("http://custom-host:9000/", "http://custom-host:9000"),
    ("https://api.custom.ai:443/v1/", "https://api.custom.ai:443/v1"),
])
def test_custom_provider_base_url_normalization(raw_url: str, expected_normalized: str):
    """Verify trailing slashes and padding are stripped from base_url."""
    # 1. Via resolve_base_url
    assert resolve_base_url("custom", raw_url) == expected_normalized

    # 2. Via create_chat_model
    model = create_chat_model(provider="custom", base_url=raw_url)
    assert model.openai_api_base == expected_normalized


def test_custom_provider_missing_base_url_raises(monkeypatch):
    """Verify custom provider raises configuration error when base_url is absent or empty."""
    monkeypatch.delenv("CUSTOM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    # 1. base_url=None
    with pytest.raises((MissingConfigurationError, ProviderConfigurationError, ValueError)):
        create_chat_model(provider="custom", base_url=None)

    # 2. base_url=""
    with pytest.raises((MissingConfigurationError, ProviderConfigurationError, ValueError)):
        create_chat_model(provider="custom", base_url="")

    # 3. base_url="   "
    with pytest.raises((MissingConfigurationError, ProviderConfigurationError, ValueError)):
        create_chat_model(provider="custom", base_url="   ")

    # 4. Direct CustomProvider class
    p = CustomProvider(base_url=None)
    assert p.validate_credentials() is False
    with pytest.raises(ProviderConfigurationError):
        p.create_model()


# ============================================================================
# Section 5: Missing Credentials for Cloud Providers
# ============================================================================

def test_missing_credentials_cloud_providers(monkeypatch):
    """Verify MissingApiKeyError is raised when credentials are missing for cloud providers."""
    # Ensure no environment variables are present
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # 1. OpenAI without key
    with pytest.raises((MissingApiKeyError, ValueError)) as exc_openai:
        create_chat_model(provider="openai")
    assert "OPENAI_API_KEY" in str(exc_openai.value)
    assert "openai" in str(exc_openai.value).lower()

    # 2. Anthropic without key
    with pytest.raises((MissingApiKeyError, ValueError)) as exc_anthropic:
        create_chat_model(provider="anthropic")
    assert "ANTHROPIC_API_KEY" in str(exc_anthropic.value)
    assert "anthropic" in str(exc_anthropic.value).lower()

    # 3. Google without key
    with pytest.raises((MissingApiKeyError, ValueError)) as exc_google:
        create_chat_model(provider="google")
    assert "GOOGLE_API_KEY" in str(exc_google.value)
    assert "google" in str(exc_google.value).lower()


@pytest.mark.parametrize("falsy_key", ["", "   ", "\t"])
def test_whitespace_and_empty_keys_raise_missing(monkeypatch, falsy_key: str):
    """Verify empty or whitespace-only keys do not satisfy authentication requirements."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises((MissingApiKeyError, ValueError)):
        create_chat_model(provider="openai", api_key=falsy_key)

    with pytest.raises((MissingApiKeyError, ValueError)):
        create_chat_model(provider="anthropic", api_key=falsy_key)

    with pytest.raises((MissingApiKeyError, ValueError)):
        create_chat_model(provider="google", api_key=falsy_key)


def test_provider_validate_credentials_contract(monkeypatch):
    """Verify validate_credentials() returns boolean and does not raise exceptions."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # Without keys: must return False
    assert OpenAIProvider(api_key=None).validate_credentials() is False
    assert AnthropicProvider(api_key=None).validate_credentials() is False
    assert GoogleProvider(api_key=None).validate_credentials() is False

    # With keys: must return True
    assert OpenAIProvider(api_key="sk-test").validate_credentials() is True
    assert AnthropicProvider(api_key="sk-test").validate_credentials() is True
    assert GoogleProvider(api_key="sk-test").validate_credentials() is True

    # Ollama is keyless: validate_credentials() checks base_url
    assert OllamaProvider().validate_credentials() is True


# ============================================================================
# Section 6: Provider Strategy Interface Conformance
# ============================================================================

def test_all_registered_providers_conform_to_strategy_interface():
    """Verify all providers in ProviderRegistry subclass BaseModelProvider and implement the contract."""
    for name in ProviderRegistry.list_providers():
        provider_cls = ProviderRegistry.get(name)
        assert provider_cls is not None, f"Provider {name} returned None class"
        assert issubclass(provider_cls, BaseModelProvider), f"Provider {name} does not subclass BaseModelProvider"

        # Instantiate instance
        inst = provider_cls()
        assert hasattr(inst, "create_model")
        assert hasattr(inst, "get_supported_models")
        assert hasattr(inst, "validate_credentials")

        # get_supported_models returns non-empty list of strings
        models = inst.get_supported_models()
        assert isinstance(models, list), f"{name}.get_supported_models() must return a list"
        assert len(models) > 0, f"{name}.get_supported_models() returned empty list"
        assert all(isinstance(m, str) for m in models), f"{name}.get_supported_models() must contain strings"

        # validate_credentials returns boolean
        val = inst.validate_credentials()
        assert isinstance(val, bool), f"{name}.validate_credentials() must return a boolean"


# ============================================================================
# Section 7: Production Mock Purge Verification
# ============================================================================

def test_production_mock_file_deleted():
    """Verify backend/src/carefold/model/mock.py does not exist."""
    mock_file = Path("/Users/bharatjoshi/git/carefold/backend/src/carefold/model/mock.py")
    assert not mock_file.exists(), f"Production mock file still exists: {mock_file}"


def test_zero_mock_references_in_production_src():
    """Verify no MockChatModel or MockModelClient references exist in backend/src/carefold/."""
    src_dir = Path("/Users/bharatjoshi/git/carefold/backend/src/carefold")
    violations: List[str] = []

    for py_file in src_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        if "MockChatModel" in content:
            violations.append(f"{py_file}: contains MockChatModel")
        if "MockModelClient" in content:
            violations.append(f"{py_file}: contains MockModelClient")

    assert not violations, f"Found mock references in production code:\n" + "\n".join(violations)
