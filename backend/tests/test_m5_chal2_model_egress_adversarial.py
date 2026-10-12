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

"""Adversarial stress-testing of Model Egress Boundaries & SSRF Blocking (AU-15 / S8, Requirement R6).

Empirically challenges:
1. Cloud metadata endpoint blocking (AWS, Azure, GCP, ECS).
2. Link-local, unspecified, broadcast, and multicast IP blocking.
3. Cloud provider domain spoofing, subdomain hijacking, and prefix attacks.
4. Ollama loopback/container permission vs remote LAN gating.
5. Custom provider host allowlisting vs unlisted private destinations.
6. Absolute SSRF immunity on /api/models with 0 outbound network requests.
7. Factory & Provider constructor fail-closed enforcement.
"""

from __future__ import annotations

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from carefold.main import app
from carefold.model.egress import (
    ModelEgressBlockedError,
    validate_model_endpoint,
    CANONICAL_CLOUD_HOSTS,
    DEFAULT_OLLAMA_HOSTS,
    METADATA_IPS,
)
from carefold.model.factory import (
    create_chat_model,
    ModelFactory,
    resolve_api_key,
    resolve_base_url,
)
from carefold.model.providers.custom_provider import CustomProvider
from carefold.model.providers.ollama_provider import OllamaProvider
from carefold.schemas.chat import ChatRequestBody


# ============================================================================
# Section 1: Cloud Metadata Endpoint Adversarial Blocking
# ============================================================================

@pytest.mark.parametrize("metadata_url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://169.254.169.254:80/latest/meta-data/",
    "http://169.254.169.254:8080/latest/user-data",
    "http://user:pass@169.254.169.254/latest/meta-data/",
    "http://169.254.170.2/v2/metadata",
    "http://169.254.170.2:443/v2/metadata",
    "http://metadata.google.internal/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://metadata.internal/",
    "http://instance-data/latest/meta-data",
])
@pytest.mark.parametrize("provider", ["custom", "ollama", "openai"])
def test_adversarial_metadata_endpoints_blocked_across_providers(provider: str, metadata_url: str):
    """Verify metadata endpoints are strictly blocked across all model providers."""
    with pytest.raises(ModelEgressBlockedError) as exc_info:
        validate_model_endpoint(provider, metadata_url)

    msg = str(exc_info.value).lower()
    assert (
        "metadata" in msg
        or "blocked" in msg
        or "canonical" in msg
        or "not permitted" in msg
        or "internal domain" in msg
    )


def test_adversarial_metadata_ip_cannot_be_bypassed_via_allowed_hosts():
    """Verify that even if an attacker or admin attempts to allowlist metadata IP, it fails closed."""
    malicious_allowed = {"169.254.169.254", "169.254.170.2", "metadata.google.internal"}

    for ip in ["169.254.169.254", "169.254.170.2"]:
        with pytest.raises(ModelEgressBlockedError) as exc:
            validate_model_endpoint("custom", f"http://{ip}/latest/meta-data/", allowed_hosts=malicious_allowed)
        assert "metadata" in str(exc.value).lower()

    with pytest.raises(ModelEgressBlockedError) as exc:
        validate_model_endpoint("custom", "http://metadata.google.internal/", allowed_hosts=malicious_allowed)
    assert "metadata" in str(exc.value).lower()


# ============================================================================
# Section 2: Link-Local, Unspecified, Broadcast & Multicast IP Blocking
# ============================================================================

@pytest.mark.parametrize("prohibited_url, expected_keyword", [
    ("http://169.254.1.1:8080", "link-local"),
    ("http://169.254.100.200:9000/v1", "link-local"),
    ("http://[fe80::1]", "link-local"),
    ("http://[fe80::1]:8080", "link-local"),
    ("http://[fe80::200:5efe:10.0.0.1]:80", "link-local"),
    ("http://0.0.0.0:8000", "unspecified"),
    ("http://0.0.0.0:11434", "unspecified"),
    ("http://[::]:8000", "unspecified"),
    ("http://255.255.255.255", "broadcast"),
    ("http://255.255.255.255:8080", "broadcast"),
    ("http://224.0.0.1:8000", "multicast"),
    ("http://239.255.255.250:1900", "multicast"),
    ("http://[ff02::1]:8000", "multicast"),
])
def test_adversarial_link_local_and_internal_ip_blocking(prohibited_url: str, expected_keyword: str):
    """Verify link-local, broadcast, unspecified, and multicast IPs are unconditionally blocked."""
    with pytest.raises(ModelEgressBlockedError) as exc_info:
        validate_model_endpoint("custom", prohibited_url)

    msg = str(exc_info.value).lower()
    assert expected_keyword in msg or "metadata" in msg or "blocked" in msg


# ============================================================================
# Section 3: Cloud Domain Spoofing & Subdomain Hijacking
# ============================================================================

@pytest.mark.parametrize("provider, spoofed_url", [
    ("openai", "https://evil-openai.com/v1"),
    ("openai", "https://api.openai.com.attacker.com/v1"),
    ("openai", "https://attacker.com/api.openai.com"),
    ("openai", "https://evil.api.openai.com/v1"),
    ("openai", "http://api.openai.com.evil.org:8080"),
    ("openai", "http://127.0.0.1:8000/v1"),
    ("anthropic", "https://api.anthropic.com.attacker.com"),
    ("anthropic", "https://fake-anthropic.com"),
    ("anthropic", "https://evil.api.anthropic.com"),
    ("anthropic", "http://localhost:8000"),
    ("google", "https://attacker.google.com"),
    ("google", "https://generativelanguage.googleapis.com.attacker.com"),
    ("google", "https://evil-gemini.internal"),
    ("google", "http://127.0.0.1:9000"),
])
def test_adversarial_cloud_domain_spoofing_blocked(provider: str, spoofed_url: str):
    """Verify cloud providers reject domain spoofing, subdomain attacks, and local redirection."""
    with pytest.raises(ModelEgressBlockedError) as exc_info:
        validate_model_endpoint(provider, spoofed_url)

    msg = str(exc_info.value).lower()
    assert "canonical" in msg or "not permitted" in msg


@pytest.mark.parametrize("provider, canonical_url", [
    ("openai", "https://api.openai.com/v1"),
    ("openai", "HTTPS://API.OPENAI.COM/v1"),
    ("anthropic", "https://api.anthropic.com"),
    ("anthropic", "https://API.ANTHROPIC.COM/"),
    ("google", "https://generativelanguage.googleapis.com"),
    ("google", "https://GENERATIVELANGUAGE.GOOGLEAPIS.COM/v1beta"),
])
def test_canonical_cloud_domains_permitted_case_insensitively(provider: str, canonical_url: str):
    """Verify exact canonical cloud domains pass regardless of URL scheme/domain case."""
    res = validate_model_endpoint(provider, canonical_url)
    assert res == canonical_url


# ============================================================================
# Section 4: Ollama Loopback Permitted vs Remote LAN Gating
# ============================================================================

@pytest.mark.parametrize("loopback_url", [
    "http://127.0.0.1:11434",
    "http://127.0.0.1:8000",
    "http://127.0.0.2:11434",
    "http://127.1.2.3:11434",
    "http://localhost:11434",
    "http://localhost:8080",
    "http://[::1]:11434",
    "http://[::1]:9999",
    "http://ollama:11434",
    "http://host.docker.internal:11434",
])
def test_ollama_loopback_and_container_hosts_permitted(loopback_url: str):
    """Verify loopback addresses and Docker container DNS are permitted for Ollama."""
    res = validate_model_endpoint("ollama", loopback_url)
    assert res == loopback_url


@pytest.mark.parametrize("lan_url", [
    "http://192.168.1.1:11434",
    "http://192.168.1.100:11434",
    "http://10.0.0.5:11434",
    "http://10.200.1.1:11434",
    "http://172.16.0.10:11434",
    "http://172.31.255.254:11434",
    "http://[fd00::1]:11434",
])
def test_ollama_remote_lan_blocked_by_default(lan_url: str):
    """Verify non-loopback LAN addresses are blocked by default for Ollama without allowlist."""
    with pytest.raises(ModelEgressBlockedError) as exc_info:
        validate_model_endpoint("ollama", lan_url)

    msg = str(exc_info.value).lower()
    assert "blocked" in msg or "not permitted" in msg


def test_ollama_remote_lan_allowed_with_explicit_allowlist():
    """Verify remote Ollama LAN host is permitted when explicitly configured."""
    target_ip = "192.168.1.150"
    url = f"http://{target_ip}:11434"

    # Blocked without allowlist
    with pytest.raises(ModelEgressBlockedError):
        validate_model_endpoint("ollama", url)

    # Permitted with allowlist
    res = validate_model_endpoint("ollama", url, allowed_hosts={target_ip})
    assert res == url


# ============================================================================
# Section 5: Custom Provider Whitelisted vs Non-Whitelisted Hosts
# ============================================================================

def test_custom_provider_loopback_permitted_by_default():
    """Verify loopback endpoints are permitted by default for custom provider."""
    assert validate_model_endpoint("custom", "http://127.0.0.1:8000/v1") == "http://127.0.0.1:8000/v1"
    assert validate_model_endpoint("custom", "http://localhost:5000") == "http://localhost:5000"
    assert validate_model_endpoint("custom", "http://[::1]:8080/v1") == "http://[::1]:8080/v1"


@pytest.mark.parametrize("private_dest", [
    "http://10.0.0.1:8000/v1",
    "http://172.16.0.1:8000",
    "http://192.168.0.1:8000",
    "http://internal-service.local:8000",
    "http://internal-db.internal:8000",
])
def test_custom_provider_non_whitelisted_internal_destinations_blocked(private_dest: str):
    """Verify custom provider strictly blocks unlisted private IPs and internal domains."""
    with pytest.raises(ModelEgressBlockedError):
        validate_model_endpoint("custom", private_dest)


def test_custom_provider_whitelisted_hosts_permitted():
    """Verify custom provider allows private host when explicitly present in allowed_hosts."""
    allowed = {"192.168.1.200", "my-private-model.internal"}

    assert validate_model_endpoint(
        "custom", "http://192.168.1.200:8000/v1", allowed_hosts=allowed
    ) == "http://192.168.1.200:8000/v1"

    assert validate_model_endpoint(
        "custom", "http://my-private-model.internal:8000/v1", allowed_hosts=allowed
    ) == "http://my-private-model.internal:8000/v1"


# ============================================================================
# Section 6: Model Listing SSRF Protection (/api/models)
# ============================================================================

@pytest.mark.parametrize("malicious_endpoint", [
    "http://169.254.169.254/latest/meta-data/",
    "http://169.254.170.2/v2/metadata",
    "http://metadata.google.internal/",
    "http://169.254.1.1:8080",
    "http://[fe80::1]",
    "http://0.0.0.0:8000",
    "http://255.255.255.255",
    "http://192.168.1.100:11434",
    "http://10.0.0.1:11434",
])
def test_api_models_ssrf_protection_prevents_outbound_http(malicious_endpoint: str):
    """Verify calling /api/models with malicious Ollama endpoint blocks BEFORE outbound HTTP call."""
    client = TestClient(app, raise_server_exceptions=True)

    with patch("httpx.AsyncClient.get") as mock_http_get:
        with pytest.raises(ModelEgressBlockedError):
            client.get("/api/models", params={"provider": "ollama", "endpoint": malicious_endpoint})

        # CRITICAL ASSERTION: No socket/HTTP connection initiated
        assert not mock_http_get.called, f"Outbound HTTP was called for malicious destination {malicious_endpoint}!"


def test_api_models_safe_loopback_reaches_http_layer():
    """Verify calling /api/models with legitimate loopback endpoint passes egress gate."""
    from unittest.mock import AsyncMock, MagicMock
    client = TestClient(app, raise_server_exceptions=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [{"name": "llama3:latest", "details": {"parameter_size": "8B"}}]
    }

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_resp)) as mock_http_get:
        resp = client.get("/api/models", params={"provider": "ollama", "endpoint": "http://127.0.0.1:11434"})
        assert resp.status_code == 200
        assert mock_http_get.called is True
        data = resp.json()
        assert data["provider"] == "ollama"
        assert len(data["models"]) == 1
        assert data["models"][0]["id"] == "llama3:latest"


# ============================================================================
# Section 7: Prohibited URL Schemes & Parser Boundary Defense
# ============================================================================

@pytest.mark.parametrize("prohibited_scheme_url", [
    "ftp://127.0.0.1:11434/v1",
    "file:///etc/passwd",
    "gopher://127.0.0.1:11434",
    "javascript:alert(1)",
    "data:text/html,<html>",
    "ldap://127.0.0.1:389",
])
def test_prohibited_url_schemes_blocked(prohibited_scheme_url: str):
    """Verify non-HTTP(S) schemes are rejected immediately."""
    with pytest.raises(ModelEgressBlockedError) as exc_info:
        validate_model_endpoint("custom", prohibited_scheme_url)
    assert "scheme" in str(exc_info.value).lower()


@pytest.mark.parametrize("empty_or_malformed", [
    "",
    "   ",
    "http://",
    "https://",
    "http://:8080",
])
def test_empty_or_malformed_urls_blocked(empty_or_malformed: str):
    """Verify empty or host-less URLs raise ModelEgressBlockedError."""
    with pytest.raises(ModelEgressBlockedError):
        validate_model_endpoint("custom", empty_or_malformed)


# ============================================================================
# Section 8: ModelFactory & Provider Constructor Integration Defense
# ============================================================================

def test_model_factory_create_chat_model_fails_closed_on_metadata():
    """Verify ModelFactory.create_chat_model blocks metadata before instantiating provider."""
    with pytest.raises(ModelEgressBlockedError):
        create_chat_model(
            provider="custom",
            base_url="http://169.254.169.254/latest/meta-data/",
            model="gpt-4o",
        )


def test_ollama_provider_init_fails_closed_on_untrusted_host():
    """Verify OllamaProvider constructor independently blocks untrusted hosts."""
    with pytest.raises(ModelEgressBlockedError):
        OllamaProvider(base_url="http://169.254.169.254:11434")

    with pytest.raises(ModelEgressBlockedError):
        OllamaProvider(base_url="http://192.168.1.100:11434")


def test_custom_provider_init_fails_closed_on_untrusted_host():
    """Verify CustomProvider constructor independently blocks untrusted hosts."""
    with pytest.raises(ModelEgressBlockedError):
        CustomProvider(base_url="http://169.254.170.2/v2/metadata")

    with pytest.raises(ModelEgressBlockedError):
        CustomProvider(base_url="http://10.0.0.1:8000/v1")
