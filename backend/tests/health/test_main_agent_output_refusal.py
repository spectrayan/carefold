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

"""A main-agent answer refused by the output guardrail ends in a safe reply.

Regression: the reflection retry sent the turn to the agent node with
``current_agent="main-agent"``, which is not a registered agent, so the user
saw "Unknown or unregistered agent ID: 'main-agent'".
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import carefold.schemas.manifest  # noqa: F401  registers clinical AgentDomain
from carefold.engine.runtime import create_execution_service
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE
from carefold.workflows.nodes.reflection_node import ReflectionNode
from yarvelle_core.engine.orchestration.runtime import MAIN_AGENT_ID
from yarvelle_core.testing.orch_eval.fake import ScriptedFakeChatModel
from yarvelle_core.testing.orch_eval.schema import FakeMainStep, FakeScript

UNSAFE_ANSWER = "You have asthma, take 500mg amoxicillin."


def _reply_text(result: Dict[str, Any]) -> str:
    messages: List[Any] = result.get("messages") or []
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content:
            return str(message.content)
    return str(result.get("output") or "")


async def _run_unsafe_main_agent_turn() -> Dict[str, Any]:
    svc = create_execution_service()
    model = ScriptedFakeChatModel()
    model.load_turn(1, FakeScript(main=[FakeMainStep(answer=UNSAFE_ANSWER)]))
    graph = svc._build_orchestrated_graph(model, None, None)
    return await graph.ainvoke(
        {"messages": [HumanMessage(content="What should we ask about her blood pressure medicine?")]},
        config={"configurable": {"thread_id": "main-agent-output-refusal"}},
    )


@pytest.mark.asyncio
async def test_refused_main_agent_answer_never_surfaces_unknown_agent_error() -> None:
    result = await _run_unsafe_main_agent_turn()
    reply = _reply_text(result)
    assert "Unknown or unregistered agent" not in reply
    assert "main-agent" not in reply
    assert not result.get("error")


@pytest.mark.asyncio
async def test_refused_main_agent_answer_gets_the_safe_refusal() -> None:
    result = await _run_unsafe_main_agent_turn()
    reply = _reply_text(result)
    assert UNSAFE_ANSWER not in reply
    assert SAFE_REFUSAL_TEMPLATE in reply


@pytest.mark.asyncio
async def test_reflection_does_not_retry_a_main_agent_answer() -> None:
    out = await ReflectionNode(max_reflections=2).execute(
        {"current_agent": MAIN_AGENT_ID, "refusal_reason": "forbidden_intent:medical_prohibited", "output": UNSAFE_ANSWER}
    )
    assert out["next_step"] == "refusal"
    assert out["reflection_count"] == 0


@pytest.mark.asyncio
async def test_reflection_still_retries_a_specialist_answer() -> None:
    out = await ReflectionNode(max_reflections=2).execute(
        {"current_agent": "heart-care-coordinator", "refusal_reason": "forbidden_intent:medical_prohibited", "output": UNSAFE_ANSWER}
    )
    assert out["next_step"] == "agent"
    assert out["reflection_count"] == 1
