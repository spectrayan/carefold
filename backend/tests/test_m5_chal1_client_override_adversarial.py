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

"""Empirical Adversarial Test Suite for Client Override Neutralization & Server Precedence.

Milestone 5 Challenger 1 (m5_18_chal1) Verification Harness.
Validates:
1. Client Key Injection Attempts: ChatRequestBody with client-provided apiKey, api_key,
   customEndpoint, baseUrl, base_url across wire JSON representations strictly returns None
   from get_api_key() and get_custom_endpoint().
2. Server Credential Precedence: When server environment variables are set, resolve_api_key
   always returns the server key regardless of client-supplied values.
3. SettingsPort Precedence: When a setting is present in SettingsPort vault cache/db, it takes
   top priority over server environment variables.
4. Wire Backward Compatibility: Existing client JSON payloads containing legacy override fields
   parse cleanly without Pydantic / HTTP 422 errors.
5. Service-Layer Defense in Depth: Engine service and route handlers neutralize overrides even
   when incoming payloads bypass schema validation.
6. Egress & Anti-SSRF Stress Testing: validate_model_endpoint blocks obfuscated SSRF, cloud
   metadata, link-local, broadcast, multicast, and unauthorized network egress.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict
import pytest
from pydantic import ValidationError

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
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_CUSTOM,
    PROVIDER_OLLAMA,
)
from carefold.schemas.chat import ChatRequestBody


# ============================================================================
# 1. Client Key Injection Attempts & Neutralization
# ============================================================================

class TestClientKeyInjectionNeutralization:
    """Stress tests verifying that client-supplied keys and endpoints are strictly neutralized."""

    @pytest.mark.parametrize("field_name, bad_value", [
        ("apiKey", "sk-proj-attack-vector-12345"),
        ("api_key", "sk-ant-attack-vector-67890"),
        ("customEndpoint", "http://169.254.169.254/latest/meta-data"),
        ("baseUrl", "http://evil-attacker.org:8080/v1"),
        ("base_url", "http://internal-corp-vault.lan:9999"),
    ])
    def test_single_field_injection_neutralized(self, field_name: str, bad_value: str):
        """Verifies individual client override injection yields None from all getters."""
        init_kwargs = {"prompt": "What are the signs of heart attack?", field_name: bad_value}
        body = ChatRequestBody(**init_kwargs)

        assert body.get_api_key() is None, f"get_api_key() failed to neutralize {field_name}"
        assert body.get_custom_endpoint() is None, f"get_custom_endpoint() failed to neutralize {field_name}"

    def test_combined_injection_all_fields(self):
        """Verifies simultaneous injection across all 5 override fields strictly yields None."""
        body = ChatRequestBody(
            prompt="Routine health checkup questions",
            agentId="cardiology-guide",
            provider="openai",
            model="gpt-4o",
            apiKey="sk-client-key-1",
            api_key="sk-client-key-2",
            customEndpoint="http://evil-metadata.com/v1",
            baseUrl="http://evil-base.com/v1",
            base_url="http://evil-base-snake.com/v1",
        )

        assert body.get_api_key() is None
        assert body.get_custom_endpoint() is None

    @pytest.mark.parametrize("payload_json", [
        # camelCase wire representation
        json.dumps({
            "prompt": "Test query",
            "agentId": "visit-steward",
            "apiKey": "sk-evil-wire-key",
            "customEndpoint": "http://169.254.169.254/meta",
        }),
        # snake_case wire representation
        json.dumps({
            "prompt": "Test query",
            "agent_id": "visit-steward",
            "api_key": "sk-evil-snake-key",
            "base_url": "http://metadata.google.internal/",
        }),
        # mixed alias wire representation
        json.dumps({
            "prompt": "Test query",
            "agentId": "visit-steward",
            "apiKey": "key1",
            "api_key": "key2",
            "customEndpoint": "http://evil1.com",
            "baseUrl": "http://evil2.com",
            "base_url": "http://evil3.com",
        }),
        # SQL injection attack in API key
        json.dumps({
            "prompt": "Test query",
            "apiKey": "'; DROP TABLE users; SELECT * FROM credentials; --",
            "baseUrl": "http://sql-attack.lan",
        }),
        # Unicode and special characters
        json.dumps({
            "prompt": "Test query",
            "apiKey": "sk-\u0000\u2620\u2728-special",
            "customEndpoint": "http://\ud83d\ude00.example.com",
        }),
        # Extremely long string
        json.dumps({
            "prompt": "Test query",
            "apiKey": "A" * 15000,
            "baseUrl": "http://very-long-domain" + "x" * 500 + ".com",
        }),
    ])
    def test_wire_json_deserialization_neutralized(self, payload_json: str):
        """Verifies that deserializing raw JSON wire strings completely neutralizes getters."""
        body = ChatRequestBody.model_validate_json(payload_json)
        assert body.get_api_key() is None
        assert body.get_custom_endpoint() is None

    def test_schema_deprecation_metadata_enforced(self):
        """Verifies that all 5 client override fields are explicitly marked deprecated."""
        fields = ChatRequestBody.model_fields
        override_fields = ["apiKey", "api_key", "customEndpoint", "baseUrl", "base_url"]
        for f in override_fields:
            assert f in fields, f"Field {f} missing from ChatRequestBody schema"
            assert fields[f].deprecated is True, f"Field {f} must have deprecated=True"
            desc = str(fields[f].description or "").lower()
            assert "ignored" in desc or "server" in desc, f"Field {f} description must indicate server-side resolution"


# ============================================================================
# 2. Server Credential Precedence over Client-Supplied Keys
# ============================================================================

class TestServerCredentialPrecedence:
    """Stress tests verifying server environment variables strictly take precedence."""

    @pytest.mark.parametrize("provider, env_var, server_key", [
        (PROVIDER_OPENAI, "OPENAI_API_KEY", "sk-server-vault-openai-secret-999"),
        (PROVIDER_ANTHROPIC, "ANTHROPIC_API_KEY", "sk-ant-server-vault-anthropic-secret-888"),
        (PROVIDER_GOOGLE, "GOOGLE_API_KEY", "AIzaSy-server-vault-google-secret-777"),
        (PROVIDER_GOOGLE, "GEMINI_API_KEY", "AIzaSy-server-vault-gemini-secret-666"),
        (PROVIDER_CUSTOM, "CUSTOM_API_KEY", "custom-server-vault-key-555"),
    ])
    def test_server_env_overrides_client_key(
        self, monkeypatch, provider: str, env_var: str, server_key: str
    ):
        """Verifies resolve_api_key unconditionally returns server environment key."""
        # Clear other keys for provider to isolate
        for v in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "CUSTOM_API_KEY"]:
            monkeypatch.delenv(v, raising=False)

        monkeypatch.setenv(env_var, server_key)

        # Attempt override with aggressive client key
        resolved = resolve_api_key(
            provider=provider,
            client_key="sk-client-malicious-override-key",
            allow_missing=False,
        )
        assert resolved == server_key, (
            f"Expected server env key '{server_key}', but got '{resolved}'"
        )

    @pytest.mark.parametrize("provider, env_var, server_key", [
        (PROVIDER_OPENAI, "OPENAI_API_KEY", "sk-server-vault-openai-secret"),
        (PROVIDER_ANTHROPIC, "ANTHROPIC_API_KEY", "sk-ant-server-vault-anthropic"),
        (PROVIDER_GOOGLE, "GOOGLE_API_KEY", "AIzaSy-server-vault-google"),
    ])
    def test_server_env_whitespace_resilience(
        self, monkeypatch, provider: str, env_var: str, server_key: str
    ):
        """Verifies whitespace around server env keys is stripped while client keys remain ignored."""
        monkeypatch.setenv(env_var, f"  {server_key}  \t\n")

        # Client sends various falsy or valid strings
        for client_val in ["client-val", "   ", "", None]:
            resolved = resolve_api_key(provider=provider, client_key=client_val)
            assert resolved == server_key

    def test_server_base_url_overrides_client_endpoint(self, monkeypatch):
        """Verifies resolve_base_url returns server URL and ignores client-supplied endpoints."""
        monkeypatch.setenv("OLLAMA_URL", "http://ollama-internal-cluster:11434///")

        resolved = resolve_base_url(
            provider="ollama",
            client_base_url="http://192.168.1.99:11434",
        )
        assert resolved == "http://ollama-internal-cluster:11434"

    def test_missing_server_credentials_raises_error(self, monkeypatch):
        """Verifies resolve_api_key raises MissingApiKeyError when no server key exists."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(MissingApiKeyError) as exc_info:
            resolve_api_key("openai", client_key=None, allow_missing=False)

        assert "OPENAI_API_KEY" in str(exc_info.value)

    def test_ollama_allows_missing_key(self, monkeypatch):
        """Verifies Ollama provider permits None API key."""
        monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
        resolved = resolve_api_key("ollama", client_key=None, allow_missing=True)
        assert resolved is None


# ============================================================================
# 3. SettingsPort Precedence over Environment Variables & Client Keys
# ============================================================================

class TestSettingsPortVaultPrecedence:
    """Stress tests verifying SettingsPort cache takes top priority over environment variables."""

    class MockVaultSettingsPort:
        """Test double simulating SettingsPort cache layer."""
        def __init__(self, cache_dict: Dict[str, Any]):
            self._cache: Dict[str, Any] = cache_dict

        def get_setting(self, key: str) -> Optional[Any]:
            return self._cache.get(key)

    @pytest.mark.parametrize("provider, setting_key, env_var, vault_key, env_key", [
        (
            PROVIDER_OPENAI,
            "models.openai_api_key",
            "OPENAI_API_KEY",
            "vault-db-encrypted-openai-token-001",
            "env-fallback-openai-token",
        ),
        (
            PROVIDER_ANTHROPIC,
            "models.anthropic_api_key",
            "ANTHROPIC_API_KEY",
            "vault-db-encrypted-anthropic-token-002",
            "env-fallback-anthropic-token",
        ),
        (
            PROVIDER_GOOGLE,
            "models.google_api_key",
            "GOOGLE_API_KEY",
            "vault-db-encrypted-google-token-003",
            "env-fallback-google-token",
        ),
        (
            PROVIDER_CUSTOM,
            "models.custom_api_key",
            "CUSTOM_API_KEY",
            "vault-db-encrypted-custom-token-004",
            "env-fallback-custom-token",
        ),
    ])
    def test_settings_port_beats_environment_variables(
        self,
        monkeypatch,
        provider: str,
        setting_key: str,
        env_var: str,
        vault_key: str,
        env_key: str,
    ):
        """Verifies SettingsPort cache takes top priority over environment variables."""
        monkeypatch.setenv(env_var, env_key)

        vault = self.MockVaultSettingsPort({setting_key: vault_key})
        resolved = resolve_api_key(
            provider=provider,
            client_key="client-attack-key",
            settings_port=vault,
        )

        assert resolved == vault_key, (
            f"SettingsPort vault key '{vault_key}' should precede env key '{env_key}'"
        )

    @pytest.mark.parametrize("alias_key", [
        "models.openai_api_key",
        "models.openai.api_key",
        "openai_api_key",
    ])
    def test_settings_port_recognizes_alias_key_patterns(self, monkeypatch, alias_key: str):
        """Verifies various naming conventions in SettingsPort are properly recognized."""
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        vault = self.MockVaultSettingsPort({alias_key: "vault-alias-key"})

        resolved = resolve_api_key(
            provider="openai",
            client_key="client-key",
            settings_port=vault,
        )
        assert resolved == "vault-alias-key"

    def test_settings_port_empty_string_falls_back_to_env(self, monkeypatch):
        """Verifies an empty or whitespace value in SettingsPort falls back to env variable."""
        monkeypatch.setenv("OPENAI_API_KEY", "env-openai-fallback-key")
        vault = self.MockVaultSettingsPort({"models.openai_api_key": "   "})

        resolved = resolve_api_key(
            provider="openai",
            client_key="client-key",
            settings_port=vault,
        )
        assert resolved == "env-openai-fallback-key"

    def test_settings_port_base_url_precedence(self, monkeypatch):
        """Verifies SettingsPort endpoint takes precedence over OLLAMA_URL environment variable."""
        monkeypatch.setenv("OLLAMA_URL", "http://env-ollama:11434")
        vault = self.MockVaultSettingsPort({"models.ollama_url": "http://vault-ollama:11434"})

        resolved = resolve_base_url(
            provider="ollama",
            client_base_url="http://client-ollama:11434",
            settings_port=vault,
        )
        assert resolved == "http://vault-ollama:11434"


# ============================================================================
# 4. Wire Backward Compatibility & HTTP Parsing
# ============================================================================

class TestWireBackwardCompatibility:
    """Verifies existing client JSON payloads parse cleanly without HTTP 422 errors."""

    def test_legacy_payload_with_all_overrides_parses_without_error(self):
        """Ensures legacy payload with all deprecated keys parses into valid ChatRequestBody."""
        payload = {
            "prompt": "Hello Doctor, I have mild shortness of breath.",
            "agentId": "pulmonology-guide",
            "provider": "ollama",
            "model": "llama3.2:3b",
            "apiKey": "sk-legacy-client-key",
            "api_key": "sk-legacy-snake-key",
            "customEndpoint": "http://localhost:11434",
            "baseUrl": "http://localhost:11434",
            "base_url": "http://localhost:11434",
            "threadId": "thread_abc123",
            "profileId": "profile_xyz789",
            "allow_clinical": False,
        }

        # Validate with Pydantic model
        body = ChatRequestBody.model_validate(payload)
        assert body.prompt == "Hello Doctor, I have mild shortness of breath."
        assert body.get_agent_id() == "pulmonology-guide"
        assert body.get_thread_id() == "thread_abc123"
        assert body.get_profile_id() == "profile_xyz789"
        assert body.get_provider() == "ollama"

        # Deprecated raw fields still exist on object for backward compatibility
        assert body.apiKey == "sk-legacy-client-key"
        assert body.customEndpoint == "http://localhost:11434"

        # But getters strictly return None
        assert body.get_api_key() is None
        assert body.get_custom_endpoint() is None

    def test_minimal_payload_parses_cleanly(self):
        """Verifies minimal payload without overrides succeeds and supplies defaults."""
        payload = {"prompt": "Quick question"}
        body = ChatRequestBody.model_validate(payload)
        assert body.prompt == "Quick question"
        assert body.get_provider() == "ollama"
        assert body.get_api_key() is None
        assert body.get_custom_endpoint() is None

    def test_invalid_types_still_raise_validation_error(self):
        """Verifies genuine validation errors (e.g. non-string prompt) still raise ValidationError."""
        with pytest.raises(ValidationError):
            ChatRequestBody.model_validate({"prompt": None})


# ============================================================================
# 5. Service & Route Layer Defense in Depth
# ============================================================================

class TestServiceLayerDefenseInDepth:
    """Verifies that engine service and route layers enforce server-side model resolution."""

    @pytest.mark.asyncio
    async def test_stream_chat_neutralizes_dict_payload(self):
        """Verifies stream_chat strips api_key and base_url from raw dict inputs."""
        from carefold.engine.service import AgentExecutionService

        service = AgentExecutionService()

        # Capture execute_turn call kwargs by monkeypatching
        captured_kwargs: Dict[str, Any] = {}

        async def fake_execute_turn(*args, **kwargs):
            captured_kwargs.update(kwargs)
            captured_kwargs["args"] = args
            yield {"type": "token", "delta": "ok"}

        service.execute_turn = fake_execute_turn

        dict_request = {
            "agent_id": "visit-steward",
            "prompt": "Test service defense",
            "api_key": "sk-attack-raw-dict-key",
            "base_url": "http://evil-raw-dict-url.lan",
        }

        events = []
        async for ev in service.execute_chat(dict_request, raw_events=True):
            events.append(ev)

        assert captured_kwargs.get("api_key") is None, (
            "Service layer must enforce api_key=None from raw dict request"
        )
        assert captured_kwargs.get("base_url") is None, (
            "Service layer must enforce base_url=None from raw dict request"
        )

    @pytest.mark.asyncio
    async def test_stream_chat_neutralizes_pydantic_payload(self):
        """Verifies stream_chat strips api_key and base_url from ChatRequestBody inputs."""
        from carefold.engine.service import AgentExecutionService

        service = AgentExecutionService()

        captured_kwargs: Dict[str, Any] = {}

        async def fake_execute_turn(*args, **kwargs):
            captured_kwargs.update(kwargs)
            captured_kwargs["args"] = args
            yield {"type": "token", "delta": "ok"}

        service.execute_turn = fake_execute_turn

        pydantic_request = ChatRequestBody(
            prompt="Test service defense with model",
            agentId="visit-steward",
            apiKey="sk-attack-pydantic-key",
            baseUrl="http://evil-pydantic-url.lan",
        )

        events = []
        async for ev in service.execute_chat(pydantic_request, raw_events=True):
            events.append(ev)

        assert captured_kwargs.get("api_key") is None, (
            "Service layer must enforce api_key=None from ChatRequestBody"
        )
        assert captured_kwargs.get("base_url") is None, (
            "Service layer must enforce base_url=None from ChatRequestBody"
        )


# ============================================================================
# 6. Egress Destination Security & Anti-SSRF Stress Testing
# ============================================================================

class TestEgressAntiSSRFStress:
    """Stress tests validating anti-SSRF protections and canonical host enforcement."""

    @pytest.mark.parametrize("scheme", ["ftp", "file", "gopher", "dict", "javascript", "data"])
    def test_prohibited_schemes_rejected(self, scheme: str):
        """Verifies any non-http/https scheme raises ModelEgressBlockedError."""
        url = f"{scheme}://127.0.0.1:8000/v1"
        with pytest.raises(ModelEgressBlockedError) as exc_info:
            validate_model_endpoint("custom", url)
        assert "scheme" in str(exc_info.value).lower()

    @pytest.mark.parametrize("metadata_url", [
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.169.254:80/latest/meta-data/",
        "http://169.254.169.254:8080/computeMetadata/v1",
        "http://169.254.170.2/v2/metadata",
        "http://metadata.google.internal/computeMetadata/v1",
        "http://metadata.internal/meta-data",
        "http://instance-data/latest/meta-data",
    ])
    def test_cloud_metadata_unconditionally_blocked(self, metadata_url: str):
        """Verifies cloud metadata IPs and internal domain aliases are unconditionally blocked."""
        with pytest.raises(ModelEgressBlockedError):
            validate_model_endpoint("custom", metadata_url)

    @pytest.mark.parametrize("ip_target", [
        "255.255.255.255",  # IPv4 broadcast
        "0.0.0.0",          # IPv4 unspecified
        "::",               # IPv6 unspecified
        "224.0.0.1",        # IPv4 multicast
        "239.255.255.250",  # SSDP multicast
        "ff02::1",          # IPv6 all nodes multicast
        "169.254.1.1",      # IPv4 link-local
        "169.254.200.50",   # IPv4 link-local
        "fe80::1",          # IPv6 link-local
    ])
    def test_special_ip_targets_unconditionally_blocked(self, ip_target: str):
        """Verifies link-local, broadcast, multicast, and unspecified destinations are blocked."""
        url = f"http://[{ip_target}]:8000/v1" if ":" in ip_target else f"http://{ip_target}:8000/v1"
        with pytest.raises(ModelEgressBlockedError):
            validate_model_endpoint("custom", url)

    @pytest.mark.parametrize("private_ip", [
        "10.0.0.1",
        "10.255.255.254",
        "172.16.0.1",
        "172.31.255.254",
        "192.168.0.1",
        "192.168.1.100",
    ])
    def test_private_networks_blocked_without_allowlist(self, private_ip: str):
        """Verifies RFC 1918 private IPs are blocked unless explicitly in allowed_hosts."""
        url = f"http://{private_ip}:11434"
        with pytest.raises(ModelEgressBlockedError) as exc_info:
            validate_model_endpoint("ollama", url)
        assert "not permitted" in str(exc_info.value).lower() or "blocked" in str(exc_info.value).lower()

        # Permitted when explicitly included in allowed_hosts
        res = validate_model_endpoint("ollama", url, allowed_hosts={private_ip})
        assert res == url

    @pytest.mark.parametrize("provider, malicious_url", [
        ("openai", "https://api.openai.com.attacker.com/v1"),
        ("openai", "https://evil-openai.org/v1"),
        ("openai", "https://proxy.internal.openai.com/v1"),
        ("anthropic", "https://anthropic.attacker.org/v1"),
        ("anthropic", "https://api.anthropic.com.fake/v1"),
        ("google", "https://generativelanguage.googleapis.com.evil.com"),
        ("google", "https://fake-google-gemini.com"),
    ])
    def test_cloud_provider_hostname_spoofing_blocked(self, provider: str, malicious_url: str):
        """Verifies subdomain or domain spoofing attacks against cloud providers are blocked."""
        with pytest.raises(ModelEgressBlockedError) as exc_info:
            validate_model_endpoint(provider, malicious_url)
        assert "does not match canonical host" in str(exc_info.value).lower()

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "ollama", "host.docker.internal"])
    def test_default_ollama_hosts_permitted(self, host: str):
        """Verifies standard loopback and Docker container hostnames are allowed for Ollama."""
        url = f"http://[{host}]:11434" if ":" in host else f"http://{host}:11434"
        assert validate_model_endpoint("ollama", url) == url
