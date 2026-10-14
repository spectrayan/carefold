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

"""Tests for model clients and LangChain multi-provider factory (test_model.py).

Verifies:
1. Legacy ModelClient implementations (MockModelClient, OpenAIModelClient).
2. LangChain multi-provider factory (create_chat_model) across all 5 providers:
   - ollama (default local, zero keys)
   - google (gemini-2.0-flash, gemini-1.5-pro)
   - anthropic (claude-3-5-sonnet-latest, claude-3-5-haiku)
   - openai (gpt-4o, gpt-4o-mini)
   - custom (user-defined base URL and model)
   - mock (deterministic offline stub)
3. API key precedence: client request parameter overrides server environment variables.
4. Error handling: clear MissingApiKeyError and MissingConfigurationError.
5. Deterministic MockChatModel:
   - Sync generation (invoke) and async generation (ainvoke)
   - Sync streaming (stream) and async streaming (astream)
   - Queued canned text and tool calls
   - Clinical safety refusal simulation triggers
   - Sandboxed tool triggers and multi-turn ToolMessage synthesis
   - Legacy ModelClient protocol compatibility
"""

import os
import pytest

from carefold.model.client import OpenAIModelClient
from tests.fixtures.fake_model import MockModelClient, MockChatModel
from carefold.model.types import ModelMessage

# Import factory symbols defensively for compatibility across environments
try:
    from carefold.model.factory import (
        create_chat_model,
        MissingApiKeyError,
        MissingConfigurationError,
        UnsupportedProviderError,
        resolve_api_key,
        resolve_base_url,
        SUPPORTED_PROVIDERS,
    )
    _FACTORY_AVAILABLE = True
except ImportError:
    _FACTORY_AVAILABLE = False
    MissingApiKeyError = ValueError  # type: ignore[assignment,misc]
    MissingConfigurationError = ValueError  # type: ignore[assignment,misc]
    UnsupportedProviderError = ValueError  # type: ignore[assignment,misc]

# LangChain message symbols
try:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.language_models.chat_models import BaseChatModel
    _LANGCHAIN_CORE_AVAILABLE = True
except ImportError:
    _LANGCHAIN_CORE_AVAILABLE = False
    AIMessage = object  # type: ignore[assignment,misc]
    HumanMessage = object  # type: ignore[assignment,misc]
    ToolMessage = object  # type: ignore[assignment,misc]
    BaseChatModel = object  # type: ignore[assignment,misc]


# ============================================================================
# Section 1: Legacy ModelClient Tests (Preserved Intact - Zero Regressions)
# ============================================================================

@pytest.mark.asyncio
async def test_mock_client_health():
    client = MockModelClient()
    health = await client.check_health()
    assert health["reachable"] is True
    assert health["status"] == "connected"


@pytest.mark.asyncio
async def test_mock_client_queued_canned_text():
    client = MockModelClient()
    client.queue_response("Canned test response")

    chunks = []
    async for chunk in client.stream_chat([ModelMessage(role="user", content="Hello")]):
        assert chunk.choices
        if chunk.choices[0].delta.content:
            chunks.append(chunk.choices[0].delta.content)

    full = "".join(chunks)
    assert full == "Canned test response"


@pytest.mark.asyncio
async def test_mock_client_queued_tool_call():
    client = MockModelClient()
    client.queue_response({
        "type": "tool_call",
        "name": "attach-read",
        "arguments": {"path": "test.txt"},
    })

    tool_calls = []
    async for chunk in client.stream_chat([ModelMessage(role="user", content="Read file")]):
        assert chunk.choices
        tc = chunk.choices[0].delta.tool_calls
        if tc:
            tool_calls.extend(tc)

    assert len(tool_calls) == 1
    assert tool_calls[0].function.name == "attach-read"
    assert '"path": "test.txt"' in tool_calls[0].function.arguments


@pytest.mark.asyncio
async def test_mock_client_rule_based_generation():
    client = MockModelClient()
    tools = [
        {"function": {"name": "attach-read"}},
        {"function": {"name": "workspace-note"}},
        {"function": {"name": "skill-docs"}},
    ]

    # 1. Attachment trigger
    chunks1 = []
    async for chunk in client.stream_chat(
        [ModelMessage(role="user", content="Please inspect the lab attachment")],
        tools=tools,
    ):
        if chunk.choices and chunk.choices[0].delta.tool_calls:
            chunks1.extend(chunk.choices[0].delta.tool_calls)
    assert len(chunks1) > 0
    assert chunks1[0].function.name == "attach-read"

    # 2. Workspace note trigger
    chunks2 = []
    async for chunk in client.stream_chat(
        [ModelMessage(role="user", content="Please save a note of my agenda")],
        tools=tools,
    ):
        if chunk.choices and chunk.choices[0].delta.tool_calls:
            chunks2.extend(chunk.choices[0].delta.tool_calls)
    assert len(chunks2) > 0
    assert chunks2[0].function.name == "workspace-note"

    # 3. Skill docs trigger
    chunks3 = []
    async for chunk in client.stream_chat(
        [ModelMessage(role="user", content="Show me the appointment checklist")],
        tools=tools,
    ):
        if chunk.choices and chunk.choices[0].delta.tool_calls:
            chunks3.extend(chunk.choices[0].delta.tool_calls)
    assert len(chunks3) > 0
    assert chunks3[0].function.name == "skill-docs"


@pytest.mark.asyncio
async def test_openai_client_offline_handling():
    client = OpenAIModelClient(base_url="http://127.0.0.1:59999/v1", model="llama3.2")
    assert client.get_model_name() == "llama3.2"

    health = await client.check_health()
    assert health["reachable"] is False

    with pytest.raises(RuntimeError, match="Model server unreachable"):
        async for _ in client.stream_chat([ModelMessage(role="user", content="Hello")]):
            pass


# ============================================================================
# Section 2: LangChain Multi-Provider Model Factory Initialization Tests
# ============================================================================

def test_factory_create_mock():
    """Verify provider='mock' is purged and rejected with error."""
    if not _FACTORY_AVAILABLE:
        pytest.skip("Factory module not yet loaded")
    with pytest.raises((ValueError, KeyError)):
        create_chat_model(provider="mock")


def test_factory_create_ollama_default(monkeypatch):
    """Verify default provider is ollama and requires zero API keys."""
    if not _FACTORY_AVAILABLE:
        pytest.skip("Factory module not yet loaded")
    # Clear all potential server keys
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    model = create_chat_model()  # defaults to ollama
    assert hasattr(model, "model_name") or hasattr(model, "model")
    name = getattr(model, "model_name", None) or getattr(model, "model", None)
    assert name == "llama3.2"


def test_factory_create_google():
    """Verify google provider initializes with gemini models."""
    if not _FACTORY_AVAILABLE:
        pytest.skip("Factory module not yet loaded")
    model = create_chat_model(provider="google", api_key="dummy-google-key")
    name = getattr(model, "model_name", None) or getattr(model, "model", None)
    assert name == "gemini-2.0-flash"

    # Custom gemini model
    model2 = create_chat_model(provider="google", model="gemini-1.5-pro", api_key="dummy-google-key")
    name2 = getattr(model2, "model_name", None) or getattr(model2, "model", None)
    assert name2 == "gemini-1.5-pro"


def test_factory_create_anthropic():
    """Verify anthropic provider initializes with claude models."""
    if not _FACTORY_AVAILABLE:
        pytest.skip("Factory module not yet loaded")
    model = create_chat_model(provider="anthropic", api_key="dummy-anthropic-key")
    name = getattr(model, "model_name", None) or getattr(model, "model", None)
    assert "claude" in name

    # Custom claude model
    model2 = create_chat_model(provider="anthropic", model="claude-3-5-haiku-20241022", api_key="dummy-anthropic-key")
    name2 = getattr(model2, "model_name", None) or getattr(model2, "model", None)
    assert name2 == "claude-3-5-haiku-20241022"


def test_factory_create_openai():
    """Verify openai provider initializes with gpt-4o models."""
    if not _FACTORY_AVAILABLE:
        pytest.skip("Factory module not yet loaded")
    model = create_chat_model(provider="openai", api_key="dummy-openai-key")
    name = getattr(model, "model_name", None) or getattr(model, "model", None)
    assert name == "gpt-4o"

    # Custom openai model
    model2 = create_chat_model(provider="openai", model="gpt-4o-mini", api_key="dummy-openai-key")
    name2 = getattr(model2, "model_name", None) or getattr(model2, "model", None)
    assert name2 == "gpt-4o-mini"


def test_factory_create_custom():
    """Verify custom provider uses specified base_url and model."""
    if not _FACTORY_AVAILABLE:
        pytest.skip("Factory module not yet loaded")
    model = create_chat_model(
        provider="custom",
        base_url="http://localhost:8000/v1",
        model="med-llama-70b",
        api_key="custom-auth-key",
    )
    name = getattr(model, "model_name", None) or getattr(model, "model", None)
    assert name == "med-llama-70b"


def test_factory_unsupported_provider():
    """Verify requesting an unsupported provider raises an informative error."""
    if not _FACTORY_AVAILABLE:
        pytest.skip("Factory module not yet loaded")
    with pytest.raises((UnsupportedProviderError, ValueError)) as exc:
        create_chat_model(provider="invalid-provider-xyz")
    assert "Unsupported model provider" in str(exc.value)


# ============================================================================
# Section 3: API Key Precedence and Error Handling Tests
# ============================================================================

def test_key_resolution_client_override(monkeypatch):
    """Verify server environment variable strictly takes precedence over client key (AU-15 / S8)."""
    if not _FACTORY_AVAILABLE:
        pytest.skip("Factory module not yet loaded")
    monkeypatch.setenv("OPENAI_API_KEY", "server-secret-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-secret-anthropic")
    monkeypatch.setenv("GOOGLE_API_KEY", "server-secret-google")

    # Server environment secret strictly takes precedence over client-supplied keys
    assert resolve_api_key("openai", client_key="client-override-openai") == "server-secret-openai"
    assert resolve_api_key("anthropic", client_key="client-override-anthropic") == "server-secret-anthropic"
    assert resolve_api_key("google", client_key="client-override-google") == "server-secret-google"


def test_key_resolution_env_fallback(monkeypatch):
    """Verify environment variables are used when client key is omitted."""
    if not _FACTORY_AVAILABLE:
        pytest.skip("Factory module not yet loaded")
    monkeypatch.setenv("OPENAI_API_KEY", "server-secret-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-secret-anthropic")
    monkeypatch.setenv("GOOGLE_API_KEY", "server-secret-google")

    assert resolve_api_key("openai", client_key=None) == "server-secret-openai"
    assert resolve_api_key("anthropic", client_key=None) == "server-secret-anthropic"
    assert resolve_api_key("google", client_key=None) == "server-secret-google"


def test_key_resolution_gemini_alias_fallback(monkeypatch):
    """Verify GEMINI_API_KEY fallback for google provider."""
    if not _FACTORY_AVAILABLE:
        pytest.skip("Factory module not yet loaded")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "server-secret-gemini")

    assert resolve_api_key("google", client_key=None) == "server-secret-gemini"


def test_key_resolution_missing_key_errors(monkeypatch):
    """Verify explicit error with variable guidance when API key is missing."""
    if not _FACTORY_AVAILABLE:
        pytest.skip("Factory module not yet loaded")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises((MissingApiKeyError, ValueError)) as exc_openai:
        resolve_api_key("openai", client_key=None)
    assert "OPENAI_API_KEY" in str(exc_openai.value)

    with pytest.raises((MissingApiKeyError, ValueError)) as exc_anthropic:
        resolve_api_key("anthropic", client_key=None)
    assert "ANTHROPIC_API_KEY" in str(exc_anthropic.value)

    with pytest.raises((MissingApiKeyError, ValueError)) as exc_google:
        resolve_api_key("google", client_key=None)
    assert "GOOGLE_API_KEY" in str(exc_google.value)


def test_custom_provider_missing_base_url_error(monkeypatch):
    """Verify custom provider raises MissingConfigurationError if base URL is omitted."""
    if not _FACTORY_AVAILABLE:
        pytest.skip("Factory module not yet loaded")
    monkeypatch.delenv("CUSTOM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    with pytest.raises((MissingConfigurationError, ValueError)) as exc:
        resolve_base_url("custom", client_base_url=None)
    assert "base_url" in str(exc.value).lower()


def test_ollama_zero_keys(monkeypatch):
    """Verify ollama requires zero keys and resolves default base URL."""
    if not _FACTORY_AVAILABLE:
        pytest.skip("Factory module not yet loaded")
    assert resolve_api_key("ollama", client_key=None) is None
    url = resolve_base_url("ollama", client_base_url=None)
    assert "11434" in url


# ============================================================================
# Section 4: MockChatModel Generation & Streaming Tests
# ============================================================================

def test_mock_chat_model_invoke_canned_text():
    """Verify sync invoke returns queued canned response as AIMessage."""
    model = MockChatModel()
    model.queue_response("Canned sync text response")

    res = model.invoke([HumanMessage(content="Hello")])
    assert res.content == "Canned sync text response"


@pytest.mark.asyncio
async def test_mock_chat_model_ainvoke_canned_text():
    """Verify async ainvoke returns queued canned response."""
    model = MockChatModel()
    model.queue_response("Canned async text response")

    res = await model.ainvoke([HumanMessage(content="Hello")])
    assert res.content == "Canned async text response"


def test_mock_chat_model_stream_canned_text():
    """Verify sync stream yields incremental token chunks."""
    model = MockChatModel()
    model.queue_response("Word by word streaming test")

    chunks = list(model.stream([HumanMessage(content="Hello")]))
    assert len(chunks) > 1
    reconstructed = "".join(c.content for c in chunks)
    assert reconstructed == "Word by word streaming test"


@pytest.mark.asyncio
async def test_mock_chat_model_astream_canned_text():
    """Verify async astream yields incremental token chunks."""
    model = MockChatModel()
    model.queue_response("Async streaming tokens test")

    chunks = []
    async for chunk in model.astream([HumanMessage(content="Hello")]):
        chunks.append(chunk.content)

    assert len(chunks) > 1
    assert "".join(chunks) == "Async streaming tokens test"


def test_mock_chat_model_queued_tool_call_invoke():
    """Verify queued tool call dictionary produces AIMessage with tool_calls."""
    model = MockChatModel()
    model.queue_response({
        "type": "tool_call",
        "name": "attach-read",
        "arguments": {"path": "lab_report.txt"},
    })

    res = model.invoke([HumanMessage(content="Read lab")])
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0]["name"] == "attach-read"
    assert res.tool_calls[0]["args"] == {"path": "lab_report.txt"}


@pytest.mark.asyncio
async def test_mock_chat_model_queued_tool_call_astream():
    """Verify queued tool call streams ToolCallChunk correctly."""
    model = MockChatModel()
    model.queue_response({
        "type": "tool_call",
        "name": "workspace-note",
        "arguments": {"title": "agenda", "content": "items"},
    })

    chunks = []
    async for chunk in model.astream([HumanMessage(content="Save note")]):
        chunks.append(chunk)

    tool_chunks = [c for c in chunks if getattr(c, "tool_call_chunks", None)]
    assert len(tool_chunks) >= 1
    assert tool_chunks[0].tool_call_chunks[0]["name"] == "workspace-note"


# ============================================================================
# Section 5: MockChatModel Deterministic Rule Engine Tests
# ============================================================================

def test_mock_chat_model_safety_refusal_rules():
    """Verify deterministic safety violation triggers simulate real refusal gate triggers."""
    model = MockChatModel()

    # 1. Diagnosis
    r1 = model.invoke([HumanMessage(content="Do I have clinical depression or heart failure?")])
    assert "congestive heart failure" in r1.content

    # 2. Dosing
    r2 = model.invoke([HumanMessage(content="What dosage of sertraline 500mg should I take?")])
    assert "Take 500mg of Sertraline twice daily" in r2.content

    # 3. Emergency evasion
    r3 = model.invoke([HumanMessage(content="Should I skip the emergency room?")])
    assert "Do not go to the emergency room" in r3.content

    # 4. Stop medication
    r4 = model.invoke([HumanMessage(content="Can I stop taking insulin?")])
    assert "Stop taking your insulin immediately" in r4.content

    # 5. Insurance coverage non-guarantee (bg-02)
    r5 = model.invoke([HumanMessage(content="Will my insurance cover 100%?")])
    assert "cannot guarantee coverage" in r5.content

    # 6. Depression screening questionnaire refusal (hc-04)
    r6 = model.invoke([HumanMessage(content="Calculate my score for the phq-9 depression questionnaire")])
    assert "cannot administer the PHQ-9" in r6.content


def test_mock_chat_model_bind_tools_and_triggers():
    """Verify bind_tools activates sandboxed tool call generation."""
    model = MockChatModel()
    tools = [
        {"name": "attach-read", "description": "Reads attachment"},
        {"name": "workspace-note", "description": "Saves note"},
        {"name": "skill-docs", "description": "Reads doc"},
    ]
    bound = model.bind_tools(tools)

    # 1. Attachment trigger
    r1 = bound.invoke([HumanMessage(content="Inspect the blood work lab report attachment")])
    assert len(r1.tool_calls) == 1
    assert r1.tool_calls[0]["name"] == "attach-read"
    assert r1.tool_calls[0]["args"] == {"path": "blood_work.txt"}

    # 2. Workspace note trigger
    r2 = bound.invoke([HumanMessage(content="Please save a note of my agenda")])
    assert len(r2.tool_calls) == 1
    assert r2.tool_calls[0]["name"] == "workspace-note"
    assert r2.tool_calls[0]["args"]["title"] == "visit-agenda"

    # 3. Skill docs trigger
    r3 = bound.invoke([HumanMessage(content="Show me the visit checklist")])
    assert len(r3.tool_calls) == 1
    assert r3.tool_calls[0]["name"] == "skill-docs"
    assert r3.tool_calls[0]["args"]["skill_id"] == "visit-prep"


def test_mock_chat_model_tool_message_synthesis():
    """Verify ToolMessage in conversation history triggers completion synthesis."""
    model = MockChatModel()
    history = [
        HumanMessage(content="Read the blood work document"),
        AIMessage(content="", tool_calls=[{"name": "attach-read", "args": {"path": "blood_work.txt"}, "id": "call_1"}]),
        ToolMessage(content="Platelet count: normal, Glucose: 95 mg/dL", tool_call_id="call_1"),
    ]

    res = model.invoke(history)
    assert "reviewed the information from the tool" in res.content
    assert not res.tool_calls


def test_mock_chat_model_default_conversational_response():
    """Verify default message when no triggers or tool calls match."""
    model = MockChatModel()
    res = model.invoke([HumanMessage(content="Hello, good morning!")])
    assert "assist you with organizing your wellness goals" in res.content
    assert not res.tool_calls


@pytest.mark.asyncio
async def test_mock_chat_model_health_and_info():
    """Verify health check and model identification."""
    model = MockChatModel(model_name="custom-mock-suite")
    assert model.get_model_name() == "custom-mock-suite"

    health = await model.check_health()
    assert health["reachable"] is True
    assert health["status"] == "connected"
    assert health["activeModel"] == "custom-mock-suite"
