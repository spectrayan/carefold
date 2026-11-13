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

"""Regression tests for multi-agent chat concatenation, middle disclaimers, and Markdown preservation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
import pytest

from carefold.engine.response_synthesizer import (
    CAREFOLD_CANONICAL_DISCLAIMER,
    CarefoldResponseSynthesizerNode,
    deduplicate_middle_disclaimers,
    strip_safe_reference_preamble,
)
from carefold.engine.runtime import create_execution_service

REPO_ROOT = Path(__file__).resolve().parents[2]


class _SequencedStreamingChatModel(BaseChatModel):
    """Deterministic fake chat model emitting exact AIMessage steps (including tool_calls + async streaming chunks)."""

    steps: List[AIMessage]
    cursor: int = 0

    @property
    def _llm_type(self) -> str:
        return "sequenced-streaming-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> BaseChatModel:
        return self

    def _next_message(self, run_manager: Any = None) -> AIMessage:
        meta = getattr(run_manager, "metadata", None) or {}
        if meta.get("langgraph_node") == "suggestion":
            return AIMessage(content="[]")
        if self.cursor >= len(self.steps):
            return self.steps[-1]
        msg = self.steps[self.cursor]
        self.cursor += 1
        return msg

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next_message(run_manager))])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next_message(run_manager))])

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ):
        import json

        msg = self._next_message(run_manager)
        calls = getattr(msg, "tool_calls", None) or []
        chunk = AIMessageChunk(
            content=msg.content,
            tool_call_chunks=[
                {
                    "name": tc["name"],
                    "args": json.dumps(tc["args"]),
                    "id": tc["id"],
                    "index": idx,
                    "type": "tool_call_chunk",
                }
                for idx, tc in enumerate(calls)
            ],
        )
        gen_chunk = ChatGenerationChunk(message=chunk)
        if run_manager is not None and isinstance(msg.content, str) and msg.content:
            await run_manager.on_llm_new_token(msg.content, chunk=gen_chunk)
        yield gen_chunk


@pytest.mark.asyncio
async def test_main_agent_preamble_and_two_specialists_never_concatenate_middle_disclaimer(
    tmp_path: Path,
    temp_workspace: Path,
) -> None:
    """Pre-delegation preamble + specialist disclaimers must never concatenate onto the final synthesized reply."""
    preamble_with_disclaimer = (
        "Let me check with your cardiology and prescription cost coordinators right away.\n\n"
        "*Disclaimer: Carefold provides educational health navigation and administrative preparation, "
        "not medical diagnosis or treatment.*"
    )
    specialist_1 = (
        "Cardiology prep: Bring a 14-day home blood pressure log and list of current beta-blockers.\n\n"
        "*Disclaimer: Carefold provides educational health navigation, not medical diagnosis.*"
    )
    specialist_2 = (
        "Pharmacy cost prep: Ask whether a 90-day preferred formulary tier or mail-order copay applies.\n\n"
        "DISCLAIMER: Carefold is an educational and administrative navigation companion, not a licensed healthcare provider."
    )
    synthesized_final = (
        "**Coordinated Cardiology & Prescription Checklist:**\n"
        "- Bring your 14-day home blood pressure log for your cardiologist.\n"
        "- Ask your doctor and plan about 90-day preferred formulary mail-order pricing.\n\n"
        "*Disclaimer: Carefold provides educational health navigation and administrative preparation, "
        "not medical diagnosis or treatment. Always consult a licensed clinician before making clinical decisions.*"
    )

    model = _SequencedStreamingChatModel(
        steps=[
            AIMessage(
                content=preamble_with_disclaimer,
                tool_calls=[
                    {
                        "id": "call_heart_1",
                        "name": "task",
                        "args": {
                            "subagent_type": "heart-care-coordinator",
                            "description": "Prepare cardiology blood pressure questions.",
                        },
                    },
                    {
                        "id": "call_rx_2",
                        "name": "task",
                        "args": {
                            "subagent_type": "prescription-cost-coordinator",
                            "description": "Prepare formulary cost comparison questions.",
                        },
                    },
                ],
            ),
            AIMessage(content=specialist_1),
            AIMessage(content=specialist_2),
            AIMessage(content=synthesized_final),
        ]
    )

    svc = create_execution_service(
        workspace_root=temp_workspace,
        db_path=tmp_path / "checkpoints.db",
    )
    events = [
        ev
        async for ev in svc.execute_turn(
            thread_id="concat-reg-1",
            prompt="Help me prepare for my cardiology visit and lower my blood pressure medication copay.",
            agent_id="orchestrator",
            model=model,
        )
    ]

    completed_tasks = {
        (ev.get("agent_id"), ev.get("state"))
        for ev in events
        if ev.get("type") == "task_status"
    }
    assert ("heart-care-coordinator", "completed") in completed_tasks
    assert ("prescription-cost-coordinator", "completed") in completed_tasks

    done = next(ev for ev in events if ev.get("type") == "done")
    full_text = str(done["fullText"])
    token_text = "".join(str(ev.get("content") or "") for ev in events if ev.get("type") == "token")

    # 1. Pre-tool_calls preamble + middle disclaimer must not be concatenated ahead of Call 2.
    assert "Let me check with your cardiology" not in full_text
    assert full_text == token_text
    # 2. Leading Markdown bold must not be stripped into broken `Coordinated ...:**`.
    assert full_text.startswith("**Coordinated Cardiology & Prescription Checklist:**")
    # 3. Raw specialist outputs must not leak directly, and only one trailing disclaimer exists.
    assert full_text.lower().count("disclaimer:") == 1
    assert "yarvelle" not in full_text.lower()


@pytest.mark.asyncio
async def test_main_agent_empty_post_delegation_reply_synthesizes_specialists_without_middle_disclaimer(
    tmp_path: Path,
    temp_workspace: Path,
) -> None:
    """When a local reasoning model returns empty content on Call 2 after task tool calls, specialist outputs are synthesized cleanly."""
    specialist_1 = (
        "Endocrinology prep: Bring recent TSH, free T4, and A1c lab results.\n\n"
        "*Disclaimer: Carefold provides educational health navigation, not medical diagnosis.*"
    )
    specialist_2 = (
        "Benefits prep: Confirm whether lab panels use in-network quest/labcorp deductible tiers.\n\n"
        "DISCLAIMER: Carefold is an educational and administrative navigation companion, not a licensed healthcare provider."
    )

    model = _SequencedStreamingChatModel(
        steps=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_endo_1",
                        "name": "task",
                        "args": {
                            "subagent_type": "diabetes-thyroid-coordinator",
                            "description": "Prepare thyroid and A1c lab review questions.",
                        },
                    },
                    {
                        "id": "call_ben_2",
                        "name": "task",
                        "args": {
                            "subagent_type": "benefits-coordinator",
                            "description": "Check in-network lab deductible questions.",
                        },
                    },
                ],
            ),
            AIMessage(content=specialist_1),
            AIMessage(content=specialist_2),
            AIMessage(content=""),
        ]
    )

    svc = create_execution_service(
        workspace_root=temp_workspace,
        db_path=tmp_path / "checkpoints.db",
    )
    events = [
        ev
        async for ev in svc.execute_turn(
            thread_id="concat-empty-final-2",
            prompt="Prepare questions for my endocrinology visit and check how my insurance deductible applies to labs.",
            agent_id="orchestrator",
            model=model,
        )
    ]

    done = next(ev for ev in events if ev.get("type") == "done")
    full_text = str(done["fullText"])
    assert "TSH, free T4, and A1c" in full_text
    assert "in-network" in full_text
    assert full_text.rstrip().endswith(CAREFOLD_CANONICAL_DISCLAIMER)
    assert full_text.lower().count("disclaimer:") == 1
    assert "yarvelle" not in full_text.lower()


@pytest.mark.asyncio
async def test_degraded_response_synthesizer_strips_constituent_disclaimers_between_listed_agents() -> None:
    """Degraded CarefoldResponseSynthesizerNode listing >=2 specialists strips middle disclaimers and keeps one footer."""
    node = CarefoldResponseSynthesizerNode(
        agent_titles={
            "heart-care-coordinator": "Heart Care Coordinator",
            "benefits-coordinator": "Benefits Coordinator",
        }
    )
    state = {
        "thread_id": "degraded-multi-agent-synth",
        "prompt": "Help me coordinate cardiology questions and out-of-pocket costs.",
        "messages": [HumanMessage(content="Help me coordinate cardiology questions and out-of-pocket costs.")],
        "specialist_outputs": {
            "heart-care-coordinator": (
                "Ask about ambulatory blood pressure monitoring.\n\n"
                "*Disclaimer: Carefold provides educational health navigation and administrative preparation, "
                "not medical diagnosis or treatment.*"
            ),
            "benefits-coordinator": (
                "Verify prior authorization rules for cardiac monitoring devices.\n\n"
                "NOTE: I am not a licensed physician. Please consult your doctor before changing care plans."
            ),
        },
    }
    result = await node.execute(state)
    output = str(result["output"])

    heart_idx = output.index("**Heart Care Coordinator:**")
    benefits_idx = output.index("**Benefits Coordinator:**")
    between = output[heart_idx:benefits_idx]

    assert "disclaimer" not in between.lower()
    assert "not a licensed" not in between.lower()
    assert output.rstrip().endswith(CAREFOLD_CANONICAL_DISCLAIMER)
    assert output.lower().count("disclaimer:") == 1
    assert "yarvelle" not in output.lower()


def test_deduplicate_middle_disclaimers_and_safe_reference_preamble() -> None:
    """In-the-middle disclaimers are deduplicated to the footer and leading **Bold** Markdown stays intact."""
    middle_concat = (
        "**Heart Care Section:**\nReview home blood pressure trends.\n\n"
        "*Disclaimer: Carefold provides educational health navigation, not medical diagnosis.*\n\n"
        "**Prescription Cost Section:**\nCompare 90-day generic copay tiers.\n\n"
        "*Disclaimer: Carefold provides educational health navigation, not medical diagnosis.*"
    )
    cleaned = deduplicate_middle_disclaimers(middle_concat)
    assert cleaned.startswith("**Heart Care Section:**")
    assert "**Prescription Cost Section:**" in cleaned
    assert cleaned.lower().count("disclaimer:") == 1
    assert cleaned.index("Disclaimer:") > cleaned.index("**Prescription Cost Section:**")

    assert strip_safe_reference_preamble("**Missing:** Medication names and doses.") == (
        "**Missing:** Medication names and doses."
    )
    assert strip_safe_reference_preamble(
        "Based on the provided reference document, ask your clinician about fasting labs."
    ) == "Ask your clinician about fasting labs."
