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

"""The main agent is reminded to delegate again on follow-up turns (fake model, no network).

Carefold sets the reminder in pack.yaml (``orchestration.delegation.reminder``);
yarvelle-core >= 0.2.3 adds it to the model's copy of the latest user message.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

import yaml
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
import pytest
from yarvelle_core.engine.orchestration.reminder import main_agent_messages, reminder_from_spec

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "carefold"
REMINDER_MD = PACKAGE_ROOT / "resources" / "prompts" / "orchestrator" / "delegation_reminder.md"
FOLLOW_UP_REMINDER = REMINDER_MD.read_text(encoding="utf-8").strip()

T1 = "Synthetic question: what should we ask about the new medicine at the visit?"
T2 = "Synthetic follow-up: which cost options should we check with the plan first?"


def _pack_reminder() -> Any:
    import carefold

    orch = carefold.get_pack().orchestration
    assert orch is not None and orch.delegation is not None
    return orch.delegation.reminder


def test_pack_sets_a_follow_up_reminder_in_both_twins() -> None:
    reminder = _pack_reminder()
    assert reminder is not None
    assert reminder.when == "follow_up"
    assert reminder.text.strip() == FOLLOW_UP_REMINDER
    assert 0 < len(FOLLOW_UP_REMINDER) <= 2000
    data = yaml.safe_load((PACKAGE_ROOT / "pack.yaml").read_text(encoding="utf-8"))
    yaml_reminder = data["orchestration"]["delegation"]["reminder"]
    assert yaml_reminder["when"] == "follow_up"
    assert yaml_reminder["text"].strip() == FOLLOW_UP_REMINDER


def _model_view(messages: List[Any]) -> List[Any]:
    return main_agent_messages(messages, {}, reminder_from_spec(_pack_reminder()))


def test_first_turn_gets_no_reminder() -> None:
    messages = [HumanMessage(content=T1)]
    assert _model_view(messages) == messages


def test_follow_up_gets_the_reminder_on_a_copy() -> None:
    last = HumanMessage(content=T2, id="h2")
    messages = [HumanMessage(content=T1), AIMessage(content="Earlier answer."), last]
    out = _model_view(messages)
    assert out[-1].content == f"{T2}\n\n{FOLLOW_UP_REMINDER}"
    assert out[-1].id == "h2"
    assert out[:-1] == messages[:-1]
    assert last.content == T2 and messages[-1] is last


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [SystemMessage(content="s"), HumanMessage(content=T1)],
        [HumanMessage(content=T1), AIMessage(content="a")],
        [HumanMessage(content=T1), AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1"}]),
         ToolMessage(content="r", tool_call_id="1")],
    ],
    ids=["empty", "first-turn", "ends-with-ai", "ends-with-tool"],
)
def test_no_reminder_unless_the_user_spoke_last_after_a_reply(messages: List[Any]) -> None:
    assert _model_view(messages) == messages


def _service(tmp_path: Path, workspace: Path) -> Any:
    import carefold.schemas.manifest  # noqa: F401  registers clinical AgentDomain
    from carefold.engine.runtime import create_execution_service

    return create_execution_service(db_path=str(tmp_path / "checkpoints.db"), workspace_root=workspace)


@pytest.mark.asyncio
async def test_follow_up_turn_shows_the_reminder_to_the_model_but_does_not_save_it(
    tmp_path: Path, temp_workspace: Path
) -> None:
    from yarvelle_core.engine.graph import create_sqlite_saver
    from yarvelle_core.testing.orch_eval.fake import ScriptedFakeChatModel
    from yarvelle_core.testing.orch_eval.schema import FakeMainStep, FakeScript

    calls: List[List[Any]] = []

    class _Inputs(BaseCallbackHandler):
        def on_chat_model_start(self, serialized, messages, **kwargs):  # type: ignore[override]
            calls.append(list(messages[0]))

    def main_calls(prompt: str) -> List[List[Any]]:
        # Main-agent calls end on the user's turn message (subagents get a task brief).
        out = []
        for msgs in calls:
            humans = [m for m in msgs if isinstance(m, HumanMessage)]
            if humans and str(humans[-1].content).startswith(prompt):
                out.append(msgs)
        return out

    def script(answer: str) -> FakeScript:
        # Shipped personas carry no fake persona marker, so every call takes the
        # main script in order: hand-off, the specialist's reply, the final answer.
        return FakeScript(
            main=[
                FakeMainStep(task=["benefits-coordinator"]),
                FakeMainStep(answer="Synthetic specialist note: compare the plan's tiers."),
                FakeMainStep(answer=answer),
            ]
        )

    svc = _service(tmp_path, temp_workspace)
    model = ScriptedFakeChatModel()
    model.callbacks = [_Inputs()]
    thread = "follow-up-reminder-thread"

    async def run(turn: int, prompt: str, answer: str) -> list:
        model.load_turn(turn, script(answer))
        events = [e async for e in svc.execute_turn(thread_id=thread, prompt=prompt, agent_id=None, model=model)]
        assert "error" not in [e.get("type") for e in events], events
        assert next(e for e in events if e.get("type") == "done")["fullText"] == answer
        assert ("benefits-coordinator", "completed") in {
            (e.get("agent_id"), e.get("state")) for e in events if e.get("type") == "task_status"
        }
        return events

    await run(1, T1, "Synthetic first answer.")
    first = main_calls(T1)
    assert first, "main agent never ran on turn 1"
    assert all(FOLLOW_UP_REMINDER not in str(m.content) for msgs in first for m in msgs)

    calls.clear()
    await run(2, T2, "Synthetic second answer.")
    second = main_calls(T2)
    assert second, "main agent never ran on turn 2"
    last_human = [m for m in second[0] if isinstance(m, HumanMessage)][-1]
    assert last_human.content == f"{T2}\n\n{FOLLOW_UP_REMINDER}"
    # The earlier turn is still in front of the model.
    assert any(isinstance(m, HumanMessage) and m.content == T1 for m in second[0])

    saver = create_sqlite_saver(tmp_path / "checkpoints.db")
    try:
        saved = saver.get_tuple({"configurable": {"thread_id": thread, "checkpoint_ns": ""}}).checkpoint[
            "channel_values"
        ]["messages"]
    finally:
        saver.conn.close()
    humans = [m.content for m in saved if isinstance(m, HumanMessage)]
    assert humans == [T1, T2]
    assert all(FOLLOW_UP_REMINDER not in str(m.content) for m in saved)
    assert saved[-1].content == "Synthetic second answer."
