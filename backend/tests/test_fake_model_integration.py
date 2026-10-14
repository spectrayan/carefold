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

"""Integration tests verifying fake and mock chat model doubles and defensive graph binding."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel

from carefold.engine.graph import create_agent_graph, CLOSED_TOOL_DEFINITIONS
from carefold.model.types import ModelMessage
from tests.fixtures.fake_model import FakeChatModel, FakeListChatModel, MockChatModel


class RaisingChatModel(BaseChatModel):
    """ChatModel whose bind_tools raises NotImplementedError for defensive testing."""

    model_name: str = "raising-test"

    @property
    def _llm_type(self) -> str:
        return "raising-chat-model"

    def bind_tools(self, *args, **kwargs):
        raise NotImplementedError("bind_tools not implemented on this provider")

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.outputs import ChatGeneration, ChatResult
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="fallback response"))])


class ModelWithoutBindTools:
    """Model that does not implement bind_tools."""

    def invoke(self, *args, **kwargs):
        return AIMessage(content="no bind tools response")


def test_fake_list_chat_model_bind_tools():
    """Verify FakeListChatModel binds tools and executes properly."""
    fake = FakeListChatModel(responses=["Test response 1", "Test response 2"])
    tool_defs = list(CLOSED_TOOL_DEFINITIONS.values())
    bound = fake.bind_tools(tool_defs)
    assert bound is not None

    res1 = bound.invoke([HumanMessage(content="Hello")])
    assert res1.content == "Test response 1"

    res2 = bound.invoke([HumanMessage(content="World")])
    assert res2.content == "Test response 2"


def test_fake_chat_model_bind_tools():
    """Verify FakeChatModel binds tools and executes properly."""
    fake = FakeChatModel()
    tool_defs = list(CLOSED_TOOL_DEFINITIONS.values())
    bound = fake.bind_tools(tool_defs)
    assert bound is not None

    res = bound.invoke([HumanMessage(content="Hello")])
    assert res is not None
    assert isinstance(res.content, str)


def test_create_agent_graph_with_fake_list_chat_model():
    """Verify create_agent_graph accepts FakeListChatModel without NotImplementedError."""
    fake = FakeListChatModel(responses=["I am your carefold assistant."])
    graph = create_agent_graph(fake)
    assert graph is not None


@pytest.mark.asyncio
async def test_agent_graph_execution_with_fake_list_chat_model():
    """Verify execution of compiled agent graph using FakeListChatModel."""
    fake = FakeListChatModel(responses=["Deductible is $500."])
    graph = create_agent_graph(fake)

    result = await graph.ainvoke({
        "messages": [HumanMessage(content="What is my deductible?")],
        "agent_id": "benefits-explainer",
    })

    assert "messages" in result
    assert len(result["messages"]) >= 2
    assert result["messages"][-1].content == "Deductible is $500."


def test_create_agent_graph_defensive_not_implemented():
    """Verify create_agent_graph defensively handles models raising NotImplementedError on bind_tools."""
    raising_model = RaisingChatModel()
    graph = create_agent_graph(raising_model)
    assert graph is not None


def test_create_agent_graph_defensive_missing_bind_tools():
    """Verify create_agent_graph defensively handles models without bind_tools."""
    model = ModelWithoutBindTools()
    graph = create_agent_graph(model)
    assert graph is not None


def test_mock_chat_model_call_recording_lifecycle():
    """Verify MockChatModel records calls and tracks call_count across all invocation methods."""
    mock = MockChatModel()
    assert mock.call_count == 0
    assert len(mock.calls) == 0

    # 1. Synchronous invoke
    res_inv = mock.invoke([HumanMessage(content="Hello there")])
    assert mock.call_count == 1
    assert len(mock.calls) == 1
    assert mock.calls[0]["tools"] is None
    assert mock.calls[0]["response"] == res_inv
    assert any("Hello there" in getattr(m, "content", "") for m in mock.calls[0]["messages"])

    # 2. Synchronous stream
    chunks = list(mock.stream([HumanMessage(content="Stream message")]))
    assert mock.call_count == 2
    assert len(mock.calls) == 2
    assert len(chunks) > 0

    # 3. Call clearing
    mock.calls.clear()
    assert mock.call_count == 0
    assert len(mock.calls) == 0

    # 4. Call setting
    mock.calls = [{"messages": [], "tools": None, "response": None}]
    assert mock.call_count == 1
    mock.calls = []
    assert mock.call_count == 0


@pytest.mark.asyncio
async def test_mock_chat_model_async_call_recording():
    """Verify MockChatModel records calls during asynchronous generation and streaming."""
    mock = MockChatModel()

    # 1. ainvoke
    res_async = await mock.ainvoke([HumanMessage(content="Async message")])
    assert mock.call_count == 1
    assert mock.calls[0]["response"] == res_async

    # 2. astream
    achunks = [c async for c in mock.astream([HumanMessage(content="Async stream message")])]
    assert mock.call_count == 2
    assert len(achunks) > 0

    # 3. stream_chat adapter
    schunks = [
        c async for c in mock.stream_chat([
            ModelMessage(role="user", content="Stream chat adapter message")
        ])
    ]
    assert mock.call_count == 3
    assert len(schunks) > 0


def test_mock_chat_model_bound_tools_call_recording():
    """Verify MockChatModel records tool definitions when invoked via bound_tools."""
    mock = MockChatModel()
    tool_defs = [{"type": "function", "function": {"name": "sample_tool", "parameters": {}}}]
    bound = mock.bind_tools(tool_defs)

    bound.invoke([HumanMessage(content="Call with tools")])
    assert mock.call_count == 1
    assert mock.calls[0]["tools"] is not None
    assert len(mock.calls[0]["tools"]) == 1
    assert mock.calls[0]["tools"][0]["function"]["name"] == "sample_tool"
