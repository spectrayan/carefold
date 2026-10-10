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

"""Adversarial stress and penetration test suite for Carefold model factory and MockChatModel.

Evaluates 6 challenge dimensions:
1. Concurrent invocations (multi-threaded, multi-task asyncio, racing queue pops).
2. Malformed parameters (types, boundaries, missing, extra kwargs).
3. Invalid provider strings (unknown, injection, unicode homoglyphs, null bytes, casing).
4. Tool call binding structures (Pydantic models, @tool, dicts, malformed, multimodal messages).
5. Streaming cancellation (generator aclose, early break, CancelledError injection).
6. Response queueing exhaustion (underflow, mixed types, non-standard items, priority over rules).
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import pytest
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from carefold.model.factory import (
    create_chat_model,
    resolve_api_key,
    resolve_base_url,
    MissingApiKeyError,
    MissingConfigurationError,
    UnsupportedProviderError,
    ModelFactoryError,
    SUPPORTED_PROVIDERS,
    PROVIDER_ALIASES,
)
from tests.fixtures.fake_model import MockChatModel, MockModelClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
from langchain_core.tools import tool


# ============================================================================
# Section 1: Concurrent Invocations
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_ainvoke_queue_integrity():
    """Verify that 50 concurrent ainvoke calls against a shared MockChatModel
    each receive exactly one unique queued response with zero duplicate pops
    and zero lost responses."""
    model = MockChatModel()
    count = 50
    expected_responses = [f"response_{i}" for i in range(count)]
    for resp in expected_responses:
        model.queue_response(resp)

    async def worker(idx: int):
        await asyncio.sleep(0.001 * (idx % 5))
        res = await model.ainvoke([HumanMessage(content=f"prompt {idx}")])
        return res.content

    tasks = [asyncio.create_task(worker(i)) for i in range(count)]
    results = await asyncio.gather(*tasks)

    assert len(results) == count
    assert set(results) == set(expected_responses)
    assert len(model._queued_responses) == 0


def test_concurrent_multithreaded_sync_invoke():
    """Verify thread-safety of MockChatModel under concurrent ThreadPoolExecutor calls."""
    model = MockChatModel()
    count = 40
    expected_responses = [f"thread_response_{i}" for i in range(count)]
    for resp in expected_responses:
        model.queue_response(resp)

    def worker(idx: int):
        res = model.invoke([HumanMessage(content=f"thread prompt {idx}")])
        return res.content

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(worker, range(count)))

    assert len(results) == count
    assert set(results) == set(expected_responses)
    assert len(model._queued_responses) == 0


@pytest.mark.asyncio
async def test_concurrent_astream_interleaving():
    """Verify multiple concurrent astream calls do not cross-contaminate tokens."""
    model = MockChatModel()
    model.queue_response("Alpha bravo charlie delta")
    model.queue_response("One two three four")

    async def consume_stream():
        collected = []
        async for chunk in model.astream([HumanMessage(content="stream test")]):
            collected.append(chunk.content)
        return "".join(collected)

    res1, res2 = await asyncio.gather(consume_stream(), consume_stream())
    results_set = {res1, res2}
    assert results_set == {"Alpha bravo charlie delta", "One two three four"}


def test_concurrent_factory_instantiations():
    """Verify concurrent model factory instantiation across threads."""
    def factory_worker(idx: int):
        p = ["ollama", "ollama", "custom"][idx % 3]
        if p == "custom":
            return create_chat_model(provider=p, base_url="http://localhost:8000/v1", model="test-m")
        return create_chat_model(provider=p)

    with ThreadPoolExecutor(max_workers=10) as executor:
        models = list(executor.map(factory_worker, range(30)))

    assert len(models) == 30
    assert all(m is not None for m in models)


# ============================================================================
# Section 2: Malformed Parameters & Boundary Edge Cases
# ============================================================================

def test_malformed_temperature_boundaries():
    """Verify temperature boundary conditions (negative, extreme, non-numeric)."""
    m_neg = create_chat_model(provider="ollama", temperature=-1.5)
    assert m_neg.temperature == -1.5

    m_high = create_chat_model(provider="ollama", temperature=999.0)
    assert m_high.temperature == 999.0

    with pytest.raises((TypeError, ValueError)):
        create_chat_model(provider="ollama", temperature="boiling")  # type: ignore[arg-type]


def test_malformed_timeout():
    """Verify timeout with zero and negative values."""
    m_zero = create_chat_model(provider="ollama", timeout=0.0)
    assert m_zero is not None

    m_neg = create_chat_model(provider="ollama", timeout=-5.0)
    assert m_neg is not None


def test_custom_provider_malformed_base_url():
    """Verify custom provider handling of empty, whitespace, and missing base_url."""
    with pytest.raises((MissingConfigurationError, ValueError)):
        create_chat_model(provider="custom", base_url="   ", model="test")

    with pytest.raises((MissingConfigurationError, ValueError)):
        create_chat_model(provider="custom", base_url=None, model="test")


def test_whitespace_api_key_resolution():
    """Verify API key resolution with whitespace-only key falls back or raises."""
    with pytest.raises((MissingApiKeyError, ValueError)):
        resolve_api_key("openai", client_key="   \t  ")


# ============================================================================
# Section 3: Invalid Provider Strings & Adversarial Names
# ============================================================================

@pytest.mark.parametrize("invalid_provider", [
    "cohere",
    "mistral",
    "deepseek",
    "bedrock",
    "azure",
    "huggingface",
    "llama",
    "../../etc/passwd",
    "provider; DROP TABLE users;--",
    "${OPENAI_API_KEY}",
    "%s%s%s%d",
    "\x00nullbyte",
    "a" * 5000,
    "mоck",   # Cyrillic 'о' homoglyph
    "орenai", # Cyrillic 'о' and 'р'
    "   ",    # Whitespace provider
    "mock",
    "stub",
    "offline",
])
def test_invalid_providers(invalid_provider: str):
    """Verify that all unsupported, adversarial, injection, and homoglyph provider names
    are cleanly rejected with UnsupportedProviderError."""
    with pytest.raises(UnsupportedProviderError) as exc:
        create_chat_model(provider=invalid_provider)
    assert "Unsupported model provider" in str(exc.value)


@pytest.mark.parametrize("provider_input, expected_normalized", [
    ("OLLAMA", "ollama"),
    ("  ollama  ", "ollama"),
    ("Google", "google"),
    ("GEMINI", "google"),
    ("gemini  ", "google"),
    ("ANTHROPIC", "anthropic"),
    ("Claude", "anthropic"),
    ("OpenAI", "openai"),
    ("LOCAL", "custom"),
])
def test_valid_provider_normalization_and_aliases(provider_input: str, expected_normalized: str):
    """Verify provider casing and aliases normalize correctly."""
    normalized = PROVIDER_ALIASES.get(provider_input.strip().lower())
    assert normalized == expected_normalized


# ============================================================================
# Section 4: Tool Call Binding Structures
# ============================================================================

class SampleToolInput(BaseModel):
    query: str = Field(description="Search query")
    max_results: int = Field(default=5, description="Max items")


def test_bind_tools_with_pydantic_schema():
    """Verify bind_tools accepts Pydantic BaseModel schemas."""
    model = MockChatModel()
    bound = model.bind_tools([SampleToolInput])
    assert bound is not None
    # Verify json serializable
    tools = bound.kwargs.get("tools")
    assert isinstance(tools, list)
    assert tools[0]["function"]["name"] == "SampleToolInput"
    assert "query" in tools[0]["function"]["parameters"]["properties"]


def test_bind_tools_with_raw_callable():
    """Verify bind_tools accepts plain callable functions."""
    def plain_function(x: int) -> int:
        """A plain function."""
        return x * 2

    model = MockChatModel()
    bound = model.bind_tools([plain_function])
    assert bound is not None
    tools = bound.kwargs.get("tools")
    assert tools[0]["function"]["name"] == "plain_function"


def test_bind_tools_with_empty_and_malformed_dicts():
    """Verify bind_tools with empty or malformed dict definitions does not crash."""
    model = MockChatModel()
    bound = model.bind_tools([
        {},
        {"name": "test_tool"},
        {"type": "function", "function": {}},
        {"type": "function", "function": {"name": ""}},
    ])
    res = bound.invoke([HumanMessage(content="Hello")])
    assert res is not None
    assert isinstance(res, AIMessage)


def test_invoke_with_empty_messages_list():
    """Verify invoke with an empty messages list returns default response without crashing."""
    model = MockChatModel()
    res = model.invoke([])
    assert isinstance(res, AIMessage)
    assert len(res.content) > 0


# ============================================================================
# Section 5: Streaming Cancellation
# ============================================================================

@pytest.mark.asyncio
async def test_astream_early_break():
    """Verify early break from astream does not leak resources or lock the model."""
    model = MockChatModel()
    model.queue_response("First Second Third Fourth Fifth Sixth Seventh Eighth")

    consumed_tokens = []
    async for chunk in model.astream([HumanMessage(content="Tell me a story")]):
        consumed_tokens.append(chunk.content)
        if len(consumed_tokens) >= 3:
            break

    assert len(consumed_tokens) == 3
    next_res = await model.ainvoke([HumanMessage(content="Hello again")])
    assert isinstance(next_res, AIMessage)


@pytest.mark.asyncio
async def test_astream_aclose_explicit():
    """Verify explicit aclose() on async stream generator."""
    model = MockChatModel()
    model.queue_response("One Two Three Four Five")

    gen = model.astream([HumanMessage(content="Stream test")])
    first_chunk = await anext(gen)
    assert first_chunk is not None

    await gen.aclose()

    res = await model.ainvoke([HumanMessage(content="Next call")])
    assert isinstance(res, AIMessage)


@pytest.mark.asyncio
async def test_astream_cancelled_error():
    """Verify injecting asyncio.CancelledError into consumer task leaves model healthy."""
    model = MockChatModel()
    model.queue_response("Testing cancellation injection token stream")

    async def streaming_task():
        tokens = []
        async for chunk in model.astream([HumanMessage(content="Hello")]):
            tokens.append(chunk.content)
            await asyncio.sleep(0.01)
        return tokens

    task = asyncio.create_task(streaming_task())
    await asyncio.sleep(0.005)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    res = await model.ainvoke([HumanMessage(content="Healthy?")])
    assert isinstance(res, AIMessage)


def test_sync_stream_early_break():
    """Verify early break from sync stream generator."""
    model = MockChatModel()
    model.queue_response("One two three four five six")

    chunks = []
    for chunk in model.stream([HumanMessage(content="test")]):
        chunks.append(chunk.content)
        if len(chunks) == 2:
            break

    assert len(chunks) == 2
    res = model.invoke([HumanMessage(content="test 2")])
    assert isinstance(res, AIMessage)


# ============================================================================
# Section 6: Response Queueing Exhaustion
# ============================================================================

def test_queue_exhaustion_falls_back_to_rules():
    """Verify that when queued responses are exhausted, the model smoothly
    falls back to rule-based evaluation without crashing."""
    model = MockChatModel()
    model.queue_response("Only queued item")

    # 1. First call uses queue
    res1 = model.invoke([HumanMessage(content="Do I have heart failure?")])
    assert res1.content == "Only queued item"

    # 2. Second call should fall back to rule-based evaluation
    res2 = model.invoke([HumanMessage(content="Do I have heart failure?")])
    assert "congestive heart failure" in res2.content

    # 3. Third call with conversational prompt falls back to default response
    res3 = model.invoke([HumanMessage(content="Hello!")])
    assert "assist you with organizing your wellness goals" in res3.content


def test_queue_priority_over_refusal_and_tool_rules():
    """Verify queued responses strictly override both safety refusal rules
    and tool call triggers (critical for testing custom responses)."""
    model = MockChatModel()
    model.queue_response("Benign reassurance response")

    res = model.invoke([HumanMessage(content="diagnose my condition please")])
    assert res.content == "Benign reassurance response"


def test_queue_supports_aimessage_instance():
    """Verify queuing an already-instantiated AIMessage object directly."""
    model = MockChatModel()
    custom_msg = AIMessage(
        content="Direct AIMessage",
        additional_kwargs={"custom_field": "xyz"},
    )
    model.queue_response(custom_msg)

    res = model.invoke([HumanMessage(content="Hi")])
    assert res.content == "Direct AIMessage"
    assert res.additional_kwargs.get("custom_field") == "xyz"


def test_queue_tool_call_with_json_string_arguments():
    """Verify queued tool call with arguments as a JSON string is parsed into dict."""
    model = MockChatModel()
    model.queue_response({
        "type": "tool_call",
        "name": "attach-read",
        "arguments": json.dumps({"path": "summary.pdf"}),
        "id": "call_123",
    })

    res = model.invoke([HumanMessage(content="Read summary")])
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0]["name"] == "attach-read"
    assert res.tool_calls[0]["args"] == {"path": "summary.pdf"}
    assert res.tool_calls[0]["id"] == "call_123"


def test_queue_tool_call_with_dict_arguments():
    """Verify queued tool call with arguments already as dict."""
    model = MockChatModel()
    model.queue_response({
        "name": "workspace-note",
        "arguments": {"title": "my-note", "content": "body"},
    })

    res = model.invoke([HumanMessage(content="Save note")])
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0]["name"] == "workspace-note"
    assert res.tool_calls[0]["args"] == {"title": "my-note", "content": "body"}


def test_queue_stress_1000_items():
    """High-volume queue stress test: queue and pop 1,000 items in FIFO order."""
    model = MockChatModel()
    count = 1000
    for i in range(count):
        model.queue_response(f"item_{i}")

    assert len(model._queued_responses) == count

    for i in range(count):
        res = model.invoke([HumanMessage(content=f"call {i}")])
        assert res.content == f"item_{i}"

    assert len(model._queued_responses) == 0


# ============================================================================
# ============================================================================
# Section 7: Verified Defect Remediations
# ============================================================================

def test_defect_fixed_multimodal_list_content_handling():
    """FIXED DEFECT 1: MockChatModel safely handles multimodal list content in
    invoke, ainvoke, stream, and astream without crashing, correctly extracting text
    and firing deterministic rules."""
    model = MockChatModel()
    complex_msg = HumanMessage(
        content=[
            {"type": "text", "text": "Can I stop taking insulin?"},
            {"type": "image_url", "image_url": {"url": "http://example.com/img.png"}},
        ]  # type: ignore[arg-type]
    )

    # 1. Synchronous invoke extracts text and triggers medication violation rule
    res = model.invoke([complex_msg])
    assert res.content == "Stop taking your insulin immediately."

    # 2. Synchronous stream yields word chunks without splitting error
    stream_chunks = [c.content for c in model.stream([complex_msg])]
    assert "".join(stream_chunks) == "Stop taking your insulin immediately."

    # 3. Queued response with list content in stream
    model.queue_response(AIMessage(content=[{"type": "text", "text": "Queued answer block"}]))
    q_chunks = [c.content for c in model.stream([HumanMessage(content="test")])]
    assert "".join(q_chunks) == "Queued answer block"

    # 4. Empty and image-only multimodal content gracefully returns default response
    empty_list_res = model.invoke([HumanMessage(content=[])])
    assert "assist you with organizing your wellness goals" in empty_list_res.content

    image_only_res = model.invoke([HumanMessage(content=[{"type": "image_url", "url": "..."}])])
    assert "assist you with organizing your wellness goals" in image_only_res.content


@pytest.mark.asyncio
async def test_defect_fixed_multimodal_list_content_async():
    """FIXED DEFECT 1 (Async): MockChatModel safely handles multimodal list content in
    ainvoke and astream without crashing."""
    model = MockChatModel()
    complex_msg = HumanMessage(
        content=[
            {"type": "text", "text": "Can I stop taking insulin?"},
            {"type": "image_url", "image_url": {"url": "http://example.com/img.png"}},
        ]  # type: ignore[arg-type]
    )

    # 1. Async invocation
    res = await model.ainvoke([complex_msg])
    assert res.content == "Stop taking your insulin immediately."

    # 2. Async streaming
    astream_chunks = [c.content async for c in model.astream([complex_msg])]
    assert "".join(astream_chunks) == "Stop taking your insulin immediately."

    # 3. Async streaming with queued list-content AIMessage
    model.queue_response(AIMessage(content=[{"type": "text", "text": "Async queued answer"}]))
    aq_chunks = [c.content async for c in model.astream([HumanMessage(content="test")])]
    assert "".join(aq_chunks) == "Async queued answer"


# Alias for backwards compatibility
test_defect_reproduction_multimodal_list_content_crash = test_defect_fixed_multimodal_list_content_handling


def test_defect_fixed_bind_tools_pydantic_class_serialization():
    """FIXED DEFECT 2: MockChatModel.bind_tools converts Pydantic ModelMetaclass
    into JSON-serializable dict schema when given LangChain @tool, preventing JSON serialization crash."""
    @tool
    def blood_work_inspector(patient_id: str) -> str:
        """Inspects lab results."""
        return f"Lab for {patient_id}"

    model = MockChatModel()
    bound = model.bind_tools([blood_work_inspector])
    tools_param = bound.kwargs.get("tools", [])

    # The parameters field contains a dictionary schema, not a class type
    assert len(tools_param) == 1
    raw_params = tools_param[0]["function"]["parameters"]
    assert isinstance(raw_params, dict)
    assert not isinstance(raw_params, type)
    assert "patient_id" in raw_params.get("properties", {})

    # Attempting to JSON-serialize tools succeeds without TypeError
    dumped = json.dumps(tools_param)
    assert "blood_work_inspector" in dumped
    assert "patient_id" in dumped


# Alias for backwards compatibility
test_defect_reproduction_bind_tools_pydantic_class_serialization_failure = test_defect_fixed_bind_tools_pydantic_class_serialization


def test_defect_fixed_falsy_provider_inconsistency():
    """FIXED DEFECT 3: create_chat_model cleanly rejects falsy and non-string
    provider inputs with UnsupportedProviderError instead of silently defaulting or crashing.
    Location: backend/src/carefold/model/factory.py:213."""
    # provider="" raises UnsupportedProviderError instead of defaulting to Ollama
    with pytest.raises(UnsupportedProviderError) as exc_empty:
        create_chat_model(provider="")
    assert "Unsupported model provider" in str(exc_empty.value)

    # provider=False raises UnsupportedProviderError instead of defaulting to Ollama
    with pytest.raises(UnsupportedProviderError) as exc_false:
        create_chat_model(provider=False)  # type: ignore[arg-type]
    assert "Unsupported model provider 'False'" in str(exc_false.value)

    # provider="   " raises UnsupportedProviderError
    with pytest.raises(UnsupportedProviderError) as exc_ws:
        create_chat_model(provider="   ")
    assert "Unsupported model provider" in str(exc_ws.value)

    # provider=123 raises UnsupportedProviderError instead of crashing with AttributeError
    with pytest.raises(UnsupportedProviderError) as exc_int:
        create_chat_model(provider=123)  # type: ignore[arg-type]
    assert "Unsupported model provider '123'" in str(exc_int.value)

    # provider=None cleanly defaults to Ollama
    model_none = create_chat_model(provider=None)
    assert model_none is not None
    assert getattr(model_none, "model_name", getattr(model_none, "model", None)) == "llama3.2"


# Alias for backwards compatibility
test_defect_reproduction_falsy_provider_inconsistency = test_defect_fixed_falsy_provider_inconsistency


def test_defect_fixed_non_standard_queued_item_wrapped():
    """FIXED DEFECT 4: MockChatModel._evaluate_rules safely wraps non-standard queued items
    (such as int, boolean, or sequence) into AIMessage(content=str(item)) instead of dropping them."""
    model = MockChatModel()
    model.queue_response(99999)  # Queuing an integer or non-message object

    assert len(model._queued_responses) == 1
    res = model.invoke([HumanMessage(content="Hello")])

    # The queued integer was consumed and converted to AIMessage content
    assert len(model._queued_responses) == 0
    assert res.content == "99999"

    # Streaming test for non-standard item
    model.queue_response(12345)
    chunks = [c.content for c in model.stream([HumanMessage(content="Hello")])]
    assert "".join(chunks) == "12345"


# Alias for backwards compatibility
test_defect_reproduction_non_standard_queued_item_silently_dropped = test_defect_fixed_non_standard_queued_item_wrapped
