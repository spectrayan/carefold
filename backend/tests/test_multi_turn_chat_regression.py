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

"""Regression tests for multi-turn chat state reset, tool iteration counter reset,
and preventing ResponseSynthesizerNode from repeating previous turn responses."""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Union
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import MemorySaver
import pytest

from carefold.engine.service import AgentExecutionService
from carefold.workflows.nodes.agent_execution_node import AgentExecutionNode
from carefold.workflows.nodes.output_guardrail_node import OutputGuardrailNode
from carefold.workflows.nodes.response_synthesizer_node import ResponseSynthesizerNode


class _MultiTurnToolCallingModel(BaseChatModel):
    """Deterministic multi-turn chat model that invokes a tool before answering each turn."""

    turn_counter: int = 0

    @property
    def _llm_type(self) -> str:
        return "multi-turn-test-model"

    def bind_tools(self, tools: Sequence[Union[dict, type, Any]], **kwargs: Any) -> Any:
        return self

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        # Find the last non-system message
        last_msg = messages[-1] if messages else HumanMessage(content="")
        last_human = next(
            (m for m in reversed(messages) if isinstance(m, HumanMessage)),
            HumanMessage(content=""),
        )
        prompt_text = str(last_human.content)

        # If the last message is a HumanMessage, emit a tool call first
        if isinstance(last_msg, HumanMessage):
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": "skill-docs",
                                    "args": {
                                        "skill_id": "cardiology-prep",
                                        "doc": "cardiology_visit_checklist.md",
                                    },
                                    "id": f"call_{abs(hash(prompt_text)) % 10000}",
                                    "type": "tool_call",
                                }
                            ],
                        )
                    )
                ]
            )

        # After ToolMessage, return a distinct answer specific to the latest HumanMessage
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content=f"Distinct cardiology response for: {prompt_text}"
                    )
                )
            ]
        )


@pytest.mark.asyncio
async def test_multi_turn_chat_resets_iteration_count_and_returns_distinct_responses() -> None:
    """Verifies that subsequent turns in the same thread reset iteration_count and never repeat Turn 1's output."""
    checkpointer = MemorySaver()
    model = _MultiTurnToolCallingModel()
    service = AgentExecutionService(model=model, checkpointer=checkpointer)
    thread_id = "thread-cardiology-multi-turn-test"

    prompts = [
        "What questions should I ask my cardiologist about palpitations?",
        "How should I track my home blood pressure readings before the visit?",
        "What prior test results should I bring to my cardiology appointment?",
    ]
    done_texts: List[str] = []
    client_history: List[dict] = []

    for p in prompts:
        client_history.append({"role": "user", "content": p})
        turn_done_text = ""
        async for ev in service.execute_turn(
            thread_id=thread_id,
            prompt=p,
            agent_id="cardiology-guide",
            messages=list(client_history),
            allow_clinical=True,
            user_id="user-1",
            profile_id="profile-1",
        ):
            if ev.get("type") == "done":
                turn_done_text = ev.get("fullText", "")
        assert turn_done_text, f"Expected non-empty response for prompt: {p}"
        assert f"Distinct cardiology response for: {p}" in turn_done_text
        done_texts.append(turn_done_text)
        client_history.append({"role": "assistant", "content": turn_done_text})

    # All 3 turns must have distinct responses
    assert len(set(done_texts)) == 3


def test_response_synthesizer_does_not_reuse_previous_turn_ai_message() -> None:
    """Verifies that ResponseSynthesizerNode stops scanning backwards at the current turn's HumanMessage."""
    state = {
        "output": "",
        "specialist_outputs": {},
        "messages": [
            HumanMessage(content="First question"),
            AIMessage(content="First turn answer that must not be repeated"),
            HumanMessage(content="Second question"),
            AIMessage(content="", tool_calls=[{"name": "skill-docs", "args": {}, "id": "c1"}]),
        ],
    }
    synthesized = ResponseSynthesizerNode.synthesize_response(state)
    assert "First turn answer that must not be repeated" not in synthesized


@pytest.mark.asyncio
async def test_output_guardrail_does_not_reuse_previous_turn_ai_message() -> None:
    """Verifies that OutputGuardrailNode stops scanning backwards at the current turn's HumanMessage."""
    node = OutputGuardrailNode()
    state = {
        "output": "",
        "messages": [
            HumanMessage(content="First question"),
            AIMessage(content="First turn answer that must not be repeated"),
            HumanMessage(content="Second question"),
            AIMessage(content="", tool_calls=[{"name": "skill-docs", "args": {}, "id": "c1"}]),
        ],
    }
    res = await node.execute(state)
    assert "First turn answer that must not be repeated" not in res["output"]
