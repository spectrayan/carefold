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

"""Test suite for Server-Side Model Configuration & Vault Boundary (AU-15 / S8, Requirement R6).

Verifies:
1. ChatRequestBody deprecates client key/endpoint overrides and strictly returns None.
2. Server-side key and endpoint resolution from environment variables and SettingsPort.
3. validate_model_endpoint blocks SSRF (cloud metadata, link-local, multicast/broadcast, RFC 1918).
4. Canonical cloud provider domain enforcement (OpenAI, Anthropic, Google).
5. Ollama loopback/container DNS permission and remote LAN blocking without allowlist.
6. ModelFactory and providers raise ModelEgressBlockedError when configured with untrusted destinations.
"""

from __future__ import annotations

import os
from typing import Any, Dict
import pytest

from carefold.model.egress import (
    ModelEgressBlockedError,
    validate_model_endpoint,
    CANONICAL_CLOUD_HOSTS,
    DEFAULT_OLLAMA_HOSTS,
    METADATA_IPS,
)
from carefold.model.factory import (
    create_chat_model,
    resolve_api_key,
    resolve_base_url,
    MissingApiKeyError,
    MissingConfigurationError,
)
from carefold.model.providers.custom_provider import CustomProvider
from carefold.model.providers.ollama_provider import OllamaProvider
from carefold.schemas.chat import ChatRequestBody


# ============================================================================
# Group 1: ChatRequestBody Wire Backwards-Compatibility & Deprecation
# ============================================================================

def test_chat_request_body_client_overrides_ignored():
    """Verify legacy client keys and endpoints are accepted on wire but strictly ignored."""
    body = ChatRequestBody(
        prompt="Hello",
        provider="openai",
        model="gpt-4o",
        apiKey="sk-client-secret-12345",
        customEndpoint="http://evil.internal.corp:8080/v1",
    )

    # Wire backwards-compatibility: raw attribute values exist on model instance
    assert body.apiKey == "sk-client-secret-12345"
    assert body.customEndpoint == "http://evil.internal.corp:8080/v1"

    # Vault boundary enforcement: getters strictly return None
    assert body.get_api_key() is None
    assert body.get_custom_endpoint() is None


def test_chat_request_body_alias_variants_ignored():
    """Verify snake_case and camelCase aliases for keys and endpoints all return None."""
    # Test snake_case variants
    body_snake = ChatRequestBody(
        prompt="Hello",
        api_key="sk-snake-key",
        base_url="http://snake-endpoint.com",
    )
    assert body_snake.get_api_key() is None
    assert body_snake.get_custom_endpoint() is None

    # Test baseUrl alias
    body_base = ChatRequestBody(
        prompt="Hello",
        baseUrl="http://base-endpoint.com",
    )
    assert body_base.get_custom_endpoint() is None


def test_chat_request_body_field_deprecation_metadata():
    """Verify client override fields are marked deprecated in schema metadata."""
    fields = ChatRequestBody.model_fields
    assert fields["apiKey"].deprecated is True
    assert fields["api_key"].deprecated is True
    assert fields["customEndpoint"].deprecated is True
    assert fields["baseUrl"].deprecated is True
    assert fields["base_url"].deprecated is True


# ============================================================================
# Group 2: Server-Side API Key & Endpoint Resolution
# ============================================================================

def test_resolve_api_key_server_env_precedence(monkeypatch):
    """Verify server environment variable strictly takes precedence over client key."""
    monkeypatch.setenv("OPENAI_API_KEY", "server-secret-openai-key")
    resolved = resolve_api_key("openai", client_key="client-supplied-ignored-key")
    assert resolved == "server-secret-openai-key"


def test_resolve_api_key_settings_port_precedence(monkeypatch):
    """Verify SettingsPort vault cache strictly takes precedence over environment variables."""
    monkeypatch.setenv("OPENAI_API_KEY", "server-env-openai-key")

    class FakeSettingsPort:
        def __init__(self):
            self._cache: Dict[str, Any] = {
                "models.openai_api_key": "vault-db-openai-key",
            }

    fake_port = FakeSettingsPort()
    resolved = resolve_api_key("openai", client_key="client-ignored", settings_port=fake_port)
    assert resolved == "vault-db-openai-key"


def test_resolve_api_key_missing_raises_error(monkeypatch):
    """Verify missing server configuration raises MissingApiKeyError with env guidance."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError) as exc_info:
        resolve_api_key("openai", client_key=None)

    assert "OPENAI_API_KEY" in str(exc_info.value)
    assert "openai" in str(exc_info.value)


def test_resolve_base_url_server_env(monkeypatch):
    """Verify resolve_base_url uses server environment variables and strips slashes."""
    monkeypatch.setenv("OLLAMA_URL", "http://ollama-server:11434///")
    resolved = resolve_base_url("ollama", client_base_url="http://client-ignored:9999")
    assert resolved == "http://ollama-server:11434"


def test_resolve_base_url_custom_provider_missing_raises(monkeypatch):
    """Verify custom provider raises MissingConfigurationError when no server URL is set."""
    monkeypatch.delenv("CUSTOM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    with pytest.raises(MissingConfigurationError) as exc_info:
        resolve_base_url("custom", client_base_url=None)

    assert "custom" in str(exc_info.value).lower()


# ============================================================================
# Group 3: validate_model_endpoint SSRF & Prohibited Destinations
# ============================================================================

def test_validate_model_endpoint_blocks_cloud_metadata_ip():
    """Verify AWS/Azure/GCP metadata IP 169.254.169.254 is unconditionally blocked."""
    for ip in METADATA_IPS:
        with pytest.raises(ModelEgressBlockedError) as exc:
            validate_model_endpoint("custom", f"http://{ip}/latest/meta-data/")
        assert "metadata" in str(exc.value).lower()


def test_validate_model_endpoint_blocks_link_local_addresses():
    """Verify IPv4 link-local (169.254.0.0/16) and IPv6 link-local (fe80::/10) are blocked."""
    prohibited = [
        "http://169.254.1.1:8000/v1",
        "http://169.254.250.10:8000/v1",
        "http://[fe80::1]:8000/v1",
    ]
    for url in prohibited:
        with pytest.raises(ModelEgressBlockedError) as exc:
            validate_model_endpoint("custom", url)
        assert "link-local" in str(exc.value).lower() or "metadata" in str(exc.value).lower()


def test_validate_model_endpoint_blocks_broadcast_and_unspecified():
    """Verify broadcast, unspecified, and multicast IP destinations are blocked."""
    blocked_urls = [
        "http://255.255.255.255:8000/v1",
        "http://0.0.0.0:8000/v1",
        "http://[::]:8000/v1",
        "http://224.0.0.1:8000/v1",
        "http://[ff02::1]:8000/v1",
    ]
    for url in blocked_urls:
        with pytest.raises(ModelEgressBlockedError) as exc:
            validate_model_endpoint("custom", url)
        assert any(term in str(exc.value).lower() for term in ("broadcast", "unspecified", "multicast"))


def test_validate_model_endpoint_blocks_private_rfc1918_by_default():
    """Verify private networks (10.x, 172.16.x, 192.168.x) are blocked without allowlist."""
    private_urls = [
        "http://10.0.0.1:8000/v1",
        "http://172.16.0.5:8000/v1",
        "http://192.168.1.100:11434",
    ]
    for url in private_urls:
        with pytest.raises(ModelEgressBlockedError) as exc:
            validate_model_endpoint("custom", url)
        assert "private network" in str(exc.value).lower()


def test_validate_model_endpoint_allows_private_ip_when_allowlisted():
    """Verify private IP is permitted when explicitly present in allowed_hosts."""
    allowed = {"192.168.1.100"}
    res = validate_model_endpoint("custom", "http://192.168.1.100:8000/v1", allowed_hosts=allowed)
    assert res == "http://192.168.1.100:8000/v1"


def test_validate_model_endpoint_blocks_metadata_domain_aliases():
    """Verify cloud metadata domain aliases are blocked."""
    aliases = [
        "http://metadata.google.internal/computeMetadata/v1",
        "http://metadata.internal/v1",
        "http://instance-data/latest/meta-data",
    ]
    for url in aliases:
        with pytest.raises(ModelEgressBlockedError) as exc:
            validate_model_endpoint("custom", url)
        assert "metadata" in str(exc.value).lower() or "internal domain" in str(exc.value).lower()


def test_validate_model_endpoint_prohibits_non_http_schemes():
    """Verify non-HTTP schemes (ftp, file, gopher) are rejected."""
    bad_schemes = [
        "ftp://127.0.0.1:8000/v1",
        "file:///etc/passwd",
        "gopher://localhost:70",
    ]
    for url in bad_schemes:
        with pytest.raises(ModelEgressBlockedError) as exc:
            validate_model_endpoint("custom", url)
        assert "scheme" in str(exc.value).lower()


# ============================================================================
# Group 4: Canonical Cloud Provider Domain Enforcement
# ============================================================================

@pytest.mark.parametrize("provider, canonical_url", [
    ("openai", "https://api.openai.com/v1"),
    ("anthropic", "https://api.anthropic.com"),
    ("google", "https://generativelanguage.googleapis.com"),
])
def test_canonical_cloud_provider_endpoints_permitted(provider: str, canonical_url: str):
    """Verify default canonical endpoints are accepted for cloud providers."""
    res = validate_model_endpoint(provider, canonical_url)
    assert res == canonical_url


@pytest.mark.parametrize("provider, malicious_url", [
    ("openai", "https://evil-openai-proxy.com/v1"),
    ("openai", "http://127.0.0.1:8000/v1"),
    ("anthropic", "https://fake-anthropic.internal/v1"),
    ("google", "https://evil-gemini.com"),
])
def test_mismatched_cloud_provider_hosts_blocked(provider: str, malicious_url: str):
    """Verify cloud providers cannot target arbitrary or proxy hostnames."""
    with pytest.raises(ModelEgressBlockedError) as exc:
        validate_model_endpoint(provider, malicious_url)
    assert "canonical" in str(exc.value).lower()


# ============================================================================
# Group 5: Ollama Loopback & Container Permitted, Remote LAN Blocked
# ============================================================================

@pytest.mark.parametrize("host", sorted(DEFAULT_OLLAMA_HOSTS))
def test_ollama_default_hosts_permitted(host: str):
    """Verify loopback and Docker DNS hosts are permitted for Ollama."""
    url = f"http://[{host}]:11434" if ":" in host else f"http://{host}:11434"
    res = validate_model_endpoint("ollama", url)
    assert res == url


def test_ollama_remote_ip_blocked_without_allowlist():
    """Verify remote Ollama LAN host is blocked by default and permitted via allowlist."""
    remote_url = "http://192.168.1.50:11434"

    # Blocked by default
    with pytest.raises(ModelEgressBlockedError) as exc:
        validate_model_endpoint("ollama", remote_url)
    assert "blocked" in str(exc.value).lower()

    # Permitted with explicit allowed_hosts
    res = validate_model_endpoint("ollama", remote_url, allowed_hosts={"192.168.1.50"})
    assert res == remote_url


# ============================================================================
# Group 6: ModelFactory & Provider Construction Egress Enforcement
# ============================================================================

def test_create_chat_model_blocks_metadata_destination():
    """Verify create_chat_model raises ModelEgressBlockedError when metadata URL configured."""
    with pytest.raises(ModelEgressBlockedError):
        create_chat_model(
            provider="custom",
            base_url="http://169.254.169.254/latest/meta-data/",
            model="gpt-test",
        )


def test_create_chat_model_blocks_private_ip_destination():
    """Verify create_chat_model raises ModelEgressBlockedError for unlisted private network."""
    with pytest.raises(ModelEgressBlockedError):
        create_chat_model(
            provider="custom",
            base_url="http://10.0.0.1:8000/v1",
            model="gpt-test",
        )


def test_create_chat_model_allows_loopback_custom():
    """Verify create_chat_model succeeds for local loopback custom endpoint."""
    model = create_chat_model(
        provider="custom",
        base_url="http://127.0.0.1:8000/v1",
        model="local-test",
    )
    assert model is not None
    assert model.openai_api_base == "http://127.0.0.1:8000/v1"


def test_ollama_provider_blocks_untrusted_host_on_init():
    """Verify OllamaProvider constructor validates base_url against egress policy."""
    with pytest.raises(ModelEgressBlockedError):
        OllamaProvider(base_url="http://169.254.169.254:11434")


def test_custom_provider_blocks_untrusted_host_on_init():
    """Verify CustomProvider constructor validates base_url against egress policy."""
    with pytest.raises(ModelEgressBlockedError):
        CustomProvider(base_url="http://169.254.169.254:8000/v1")


@pytest.mark.asyncio
async def test_api_models_list_models_blocks_untrusted_ollama_endpoint():
    """Verify api/models.py:list_models blocks SSRF to cloud metadata."""
    from carefold.api.models import list_models
    with pytest.raises(ModelEgressBlockedError):
        await list_models(endpoint="http://169.254.169.254:11434")
