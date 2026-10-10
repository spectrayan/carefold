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

"""Adversarial Test Suite for LangChain Multi-Provider Model Factory.

Challenges:
1. Client Key Overrides & Process Environment Isolation (no os.environ leak or mutation)
2. Ollama Endpoint Resilience & Dummy Key Handling
3. Custom Endpoint Handling (trailing slashes, scheme preservation, fallback hierarchy)
4. Rapid Provider Switching & Case-Insensitive Aliases
5. Deterministic Offline Behavior with Zero Socket Connections (enforced via socket connection interception)
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import socket
from typing import Any, Dict, List
import pytest

from carefold.model.factory import (
    create_chat_model,
    resolve_api_key,
    resolve_base_url,
    MissingApiKeyError,
    MissingConfigurationError,
    UnsupportedProviderError,
    SUPPORTED_PROVIDERS,
    PROVIDER_ALIASES,
)
from tests.fixtures.fake_model import MockChatModel, MockModelClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


# ============================================================================
# Section 1: Client Key Overrides & Environment Isolation
# ============================================================================

def test_client_keys_strictly_override_env_without_mutation(monkeypatch):
    """Verify client request keys strictly override env vars without leaking or mutating process environment."""
    env_snapshot = {
        "OPENAI_API_KEY": "env-secret-openai-001",
        "ANTHROPIC_API_KEY": "env-secret-anthropic-002",
        "GOOGLE_API_KEY": "env-secret-google-003",
        "GEMINI_API_KEY": "env-secret-gemini-004",
        "CUSTOM_API_KEY": "env-secret-custom-005",
    }
    for k, v in env_snapshot.items():
        monkeypatch.setenv(k, v)

    # 1. OpenAI
    m_openai = create_chat_model(provider="openai", api_key="client-override-openai-999")
    assert m_openai.openai_api_key.get_secret_value() == "client-override-openai-999"
    assert os.environ["OPENAI_API_KEY"] == "env-secret-openai-001"

    # 2. Anthropic
    m_anthropic = create_chat_model(provider="anthropic", api_key="client-override-anthropic-999")
    assert m_anthropic.anthropic_api_key.get_secret_value() == "client-override-anthropic-999"
    assert os.environ["ANTHROPIC_API_KEY"] == "env-secret-anthropic-002"

    # 3. Google
    m_google = create_chat_model(provider="google", api_key="client-override-google-999")
    google_key = m_google.google_api_key.get_secret_value() if hasattr(m_google.google_api_key, "get_secret_value") else str(m_google.google_api_key)
    assert google_key == "client-override-google-999"
    assert os.environ["GOOGLE_API_KEY"] == "env-secret-google-003"
    assert os.environ["GEMINI_API_KEY"] == "env-secret-gemini-004"

    # 4. Custom
    m_custom = create_chat_model(
        provider="custom",
        base_url="http://127.0.0.1:8000/v1",
        api_key="client-override-custom-999",
    )
    assert m_custom.openai_api_key.get_secret_value() == "client-override-custom-999"
    assert os.environ["CUSTOM_API_KEY"] == "env-secret-custom-005"


def test_whitespace_and_empty_key_resilience(monkeypatch):
    """Verify whitespace handling: whitespace-only keys fall back, padded keys get stripped."""
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-openai-env")

    # Padded key should be stripped
    assert resolve_api_key("openai", client_key="  trimmed-key-789  ") == "trimmed-key-789"

    # Empty string or whitespace-only client key should fall back to environment variable
    assert resolve_api_key("openai", client_key="") == "fallback-openai-env"
    assert resolve_api_key("openai", client_key="   ") == "fallback-openai-env"
    assert resolve_api_key("openai", client_key=None) == "fallback-openai-env"


def test_apiKey_camelcase_alias(monkeypatch):
    """Verify camelCase apiKey parameter is honored and takes proper precedence."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    # 1. apiKey alias works when api_key is None
    m1 = create_chat_model(provider="openai", apiKey="camel-case-key-1")
    assert m1.openai_api_key.get_secret_value() == "camel-case-key-1"

    # 2. When both are passed, api_key takes precedence
    m2 = create_chat_model(provider="openai", api_key="snake-case-priority", apiKey="ignored-camel")
    assert m2.openai_api_key.get_secret_value() == "snake-case-priority"


def test_concurrent_multi_client_isolation(monkeypatch):
    """Stress test: 20 concurrent threads instantiating models with different keys must not cross-contaminate."""
    monkeypatch.setenv("OPENAI_API_KEY", "server-static-key")

    def worker(thread_idx: int) -> Dict[str, str]:
        client_key = f"key-thread-{thread_idx}"
        model = create_chat_model(provider="openai", api_key=client_key)
        extracted_key = model.openai_api_key.get_secret_value()
        env_val = os.environ.get("OPENAI_API_KEY", "")
        return {
            "thread_idx": thread_idx,
            "expected_key": client_key,
            "extracted_key": extracted_key,
            "env_val": env_val,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 20
    for r in results:
        assert r["extracted_key"] == r["expected_key"], f"Thread {r['thread_idx']} suffered key cross-contamination!"
        assert r["env_val"] == "server-static-key", f"Thread {r['thread_idx']} mutated os.environ!"


# ============================================================================
# Section 2: Ollama Endpoint Resilience & Dummy Key Handling
# ============================================================================

def test_ollama_resilience_with_dummy_key():
    """Verify Ollama initializes gracefully when an explicit dummy key is provided."""
    model = create_chat_model(provider="ollama", api_key="dummy-ollama-token-xyz")
    assert model.openai_api_key.get_secret_value() == "dummy-ollama-token-xyz"
    assert model.model_name == "llama3.2"


def test_ollama_zero_keys_does_not_leak_server_openai_key(monkeypatch):
    """Verify that when OPENAI_API_KEY is present in env, Ollama default does NOT leak it."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-super-secret-openai-key")

    model = create_chat_model(provider="ollama")
    # Ollama uses dummy key "ollama" and must NOT use server OPENAI_API_KEY
    assert model.openai_api_key.get_secret_value() == "ollama"
    assert model.openai_api_key.get_secret_value() != "sk-live-super-secret-openai-key"


def test_ollama_completely_isolated_env(monkeypatch):
    """Verify Ollama initializes cleanly when all environment variables are absent."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("CAREFOLD_OLLAMA_URL", raising=False)

    model = create_chat_model(provider="ollama")
    assert model.model_name == "llama3.2"
    assert model.openai_api_base == "http://127.0.0.1:11434/v1"
    assert model.openai_api_key.get_secret_value() == "ollama"


def test_ollama_base_url_resolution_hierarchy(monkeypatch):
    """Verify Ollama base URL precedence: client_base_url > OLLAMA_BASE_URL > CAREFOLD_OLLAMA_URL > default."""
    # Level 4: Default
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("CAREFOLD_OLLAMA_URL", raising=False)
    assert resolve_base_url("ollama") == "http://127.0.0.1:11434/v1"

    # Level 3: CAREFOLD_OLLAMA_URL
    monkeypatch.setenv("CAREFOLD_OLLAMA_URL", "http://carefold-ollama:11434/v1")
    assert resolve_base_url("ollama") == "http://carefold-ollama:11434/v1"

    # Level 2: OLLAMA_BASE_URL overrides CAREFOLD_OLLAMA_URL
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://explicit-ollama:11434/v1")
    assert resolve_base_url("ollama") == "http://explicit-ollama:11434/v1"

    # Level 1: client_base_url overrides all env vars
    assert resolve_base_url("ollama", client_base_url="http://client-ollama:11434/v1") == "http://client-ollama:11434/v1"


# ============================================================================
# Section 3: Custom Endpoint Handling
# ============================================================================

def test_custom_endpoint_trailing_slashes():
    """Verify custom base URL with multiple trailing slashes is stripped properly."""
    u1 = resolve_base_url("custom", "http://localhost:8000/v1/")
    assert u1 == "http://localhost:8000/v1"

    u2 = resolve_base_url("custom", "http://localhost:8000/v1///")
    assert u2 == "http://localhost:8000/v1"

    model = create_chat_model(provider="custom", base_url="http://localhost:8000/v1///")
    assert model.openai_api_base == "http://localhost:8000/v1"


def test_custom_endpoint_without_protocol():
    """Verify custom base URL provided without protocol is accepted and stripped cleanly."""
    u = resolve_base_url("custom", "localhost:8000/v1/")
    assert u == "localhost:8000/v1"

    model = create_chat_model(provider="custom", base_url="localhost:8000/v1/")
    assert model.openai_api_base == "localhost:8000/v1"


def test_custom_endpoint_base_url_env_hierarchy(monkeypatch):
    """Verify custom provider base URL fallback: client_base_url > CUSTOM_BASE_URL > OPENAI_BASE_URL."""
    monkeypatch.delenv("CUSTOM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    # Missing configuration raises error
    with pytest.raises(MissingConfigurationError):
        resolve_base_url("custom")

    # OPENAI_BASE_URL fallback
    monkeypatch.setenv("OPENAI_BASE_URL", "http://openai-compat:8080/v1")
    assert resolve_base_url("custom") == "http://openai-compat:8080/v1"

    # CUSTOM_BASE_URL overrides OPENAI_BASE_URL
    monkeypatch.setenv("CUSTOM_BASE_URL", "http://custom-server:9000/v1")
    assert resolve_base_url("custom") == "http://custom-server:9000/v1"

    # client_base_url overrides all
    assert resolve_base_url("custom", "http://client-specified:7000/v1") == "http://client-specified:7000/v1"


def test_custom_endpoint_dummy_key_default(monkeypatch):
    """Verify custom provider defaults to dummy 'custom' key when neither client key nor env key is set."""
    monkeypatch.delenv("CUSTOM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert resolve_api_key("custom", client_key=None) == "custom"
    model = create_chat_model(provider="custom", base_url="http://localhost:8000/v1")
    assert model.openai_api_key.get_secret_value() == "custom"


# ============================================================================
# Section 4: Provider Switching & Aliases
# ============================================================================

def test_rapid_provider_switching_loop():
    """Stress test: rapidly switch across all supported providers 50 times in a single thread."""
    providers_and_configs = [
        ("ollama", {"base_url": "http://127.0.0.1:11434/v1"}),
        ("openai", {"api_key": "dummy-openai-key"}),
        ("google", {"api_key": "dummy-google-key"}),
        ("anthropic", {"api_key": "dummy-anthropic-key"}),
        ("custom", {"base_url": "http://localhost:8000/v1", "api_key": "dummy-custom-key"}),
    ]

    for cycle in range(10):
        for prov, cfg in providers_and_configs:
            model = create_chat_model(provider=prov, **cfg)
            assert hasattr(model, "model_name") or hasattr(model, "model")


def test_case_insensitive_aliases():
    """Verify alias normalization across case variations and mock rejection."""
    with pytest.raises((ValueError, KeyError)):
        create_chat_model(provider="MOCK")
    with pytest.raises((ValueError, KeyError)):
        create_chat_model(provider="Offline")
    with pytest.raises((ValueError, KeyError)):
        create_chat_model(provider="STUB")

    # Gemini alias -> Google
    m_gem = create_chat_model(provider="GEMINI", api_key="dummy-gemini-key")
    assert hasattr(m_gem, "google_api_key")

    # Claude alias -> Anthropic
    m_claude = create_chat_model(provider="Claude", api_key="dummy-claude-key")
    assert hasattr(m_claude, "anthropic_api_key")

    # Local alias -> Custom
    m_local = create_chat_model(provider="Local", base_url="http://localhost:8000/v1")
    assert m_local.openai_api_base == "http://localhost:8000/v1"


def test_unsupported_provider_rejection():
    """Verify rejection of unknown or invalid providers with descriptive error."""
    for bad in ["cohere", "mistral", "huggingface", "azure", "invalid-provider-xyz"]:
        with pytest.raises(UnsupportedProviderError) as exc_info:
            create_chat_model(provider=bad)
        assert "Unsupported model provider" in str(exc_info.value)
        assert "ollama" in str(exc_info.value)


def test_provider_empty_and_none_defaults_to_ollama():
    """Verify None provider falls back to ollama, and empty string raises UnsupportedProviderError."""
    m_none = create_chat_model(provider=None)
    assert m_none.model_name == "llama3.2"

    with pytest.raises(UnsupportedProviderError) as exc_empty:
        create_chat_model(provider="")
    assert "Unsupported model provider" in str(exc_empty.value)


# ============================================================================
# Section 5: Deterministic Offline Behavior (Zero Socket Activity Verification)
# ============================================================================

@pytest.mark.asyncio
async def test_offline_mock_zero_socket_activity(monkeypatch):
    """Empirical verification: MockChatModel executes 100% offline without making any network socket connections.
    
    We monkeypatch socket.socket.connect to raise RuntimeError if ANY outbound network call is attempted.
    """
    orig_connect = socket.socket.connect

    def forbidden_connect(self, *args, **kwargs):
        raise RuntimeError(f"VIOLATION: Outbound network connection attempted in offline mode: {args} {kwargs}")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)

    model = MockChatModel(model_name="offline-deterministic")

    # 1. Sync invoke
    res1 = model.invoke([HumanMessage(content="Hello assistant")])
    assert "wellness goals" in res1.content

    # 2. Async ainvoke
    res2 = await model.ainvoke([HumanMessage(content="Hello async assistant")])
    assert "wellness goals" in res2.content

    # 3. Sync stream
    chunks1 = list(model.stream([HumanMessage(content="Hello streaming assistant")]))
    assert len(chunks1) > 0
    full1 = "".join(c.content for c in chunks1)
    assert "wellness goals" in full1

    # 4. Async astream
    chunks2 = []
    async for c in model.astream([HumanMessage(content="Hello async streaming assistant")]):
        chunks2.append(c.content)
    assert len(chunks2) > 0
    assert "wellness goals" in "".join(chunks2)

    # 5. Canned response queue
    model.queue_response("Offline canned verification payload")
    res_canned = await model.ainvoke([HumanMessage(content="ignored prompt")])
    assert res_canned.content == "Offline canned verification payload"

    # 6. Safety Refusal Simulation Triggers
    refusal_checks = [
        ("Do I have clinical depression or heart failure?", "congestive heart failure"),
        ("What dosage of sertraline 500mg should I take?", "500mg of Sertraline twice daily"),
        ("Should I skip the emergency room?", "Do not go to the emergency room"),
        ("Can I stop taking insulin?", "Stop taking your insulin immediately"),
        ("Will my insurance cover 100%?", "cannot guarantee coverage"),
        ("Calculate my score for the phq-9 depression questionnaire", "cannot administer the PHQ-9"),
    ]
    for prompt, expected_substr in refusal_checks:
        r = model.invoke([HumanMessage(content=prompt)])
        assert expected_substr in r.content, f"Refusal simulation failed for: {prompt}"

    # 7. Bound Tools Sandboxing
    tools = [
        {"name": "attach-read", "description": "Reads attachment"},
        {"name": "workspace-note", "description": "Saves note"},
        {"name": "skill-docs", "description": "Reads doc"},
    ]
    bound = model.bind_tools(tools)

    tool_checks = [
        ("Inspect the blood work lab report attachment", "attach-read"),
        ("Please save a note of my agenda", "workspace-note"),
        ("Show me the visit checklist", "skill-docs"),
    ]
    for prompt, expected_tool in tool_checks:
        r = bound.invoke([HumanMessage(content=prompt)])
        assert len(r.tool_calls) == 1
        assert r.tool_calls[0]["name"] == expected_tool

    # 8. ToolMessage Follow-up Synthesis
    history = [
        HumanMessage(content="Read the blood work document"),
        AIMessage(content="", tool_calls=[{"name": "attach-read", "args": {"path": "blood_work.txt"}, "id": "call_1"}]),
        ToolMessage(content="Platelet count: normal, Glucose: 95 mg/dL", tool_call_id="call_1"),
    ]
    r_followup = model.invoke(history)
    assert "reviewed the information from the tool" in r_followup.content

    # 9. Health Check
    health = await model.check_health()
    assert health["reachable"] is True
    assert health["status"] == "connected"

    # 10. Legacy MockModelClient Compatibility
    legacy = MockModelClient()
    h_leg = await legacy.check_health()
    assert h_leg["reachable"] is True


def test_offline_golden_eval_deterministic_reproducibility():
    """Verify that MockChatModel returns strictly identical outputs for identical prompts across multiple runs."""
    model = MockChatModel()
    prompt = "How can you help me prepare for my visit?"

    outputs = [model.invoke([HumanMessage(content=prompt)]).content for _ in range(10)]
    assert len(set(outputs)) == 1, "MockChatModel output was non-deterministic!"
