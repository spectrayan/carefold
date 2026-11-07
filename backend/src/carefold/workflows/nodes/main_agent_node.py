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

"""Main agent node that keeps delegating on follow-up turns.

Core puts the pack's delegation guidance only in the main agent's system
prompt, at the top of the conversation. On a follow-up turn the latest
question sits under the whole earlier exchange, and local models (seen with
glm-4.7-flash) answer it from the earlier reply instead of asking the
specialist again, even when the guidance says to.

This node adds a short reminder to the copy of the latest user message the
main agent reads on follow-up turns. The reminder goes into the user message
rather than a mid-conversation system message, because some providers only
accept system text at the start. Nothing is saved: the checkpoint keeps the
user's own words, and the main agent's new messages are stored as usual.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from yarvelle_core.workflows.nodes.main_agent_node import MainAgentNode

FOLLOW_UP_REMINDER = (
    "(Follow-up in an ongoing conversation. Apply the rules under \"When to hand work to "
    "specialists\" to this new message: if it asks for facts, options or advice in a "
    "specialist's area, call the task tool for that specialist again and give it the earlier "
    "context, even if an earlier reply already covered the topic. Reply without a task call "
    "only if the message is just thanks or a greeting, or asks you to repeat or clarify your "
    "own wording.)"
)


def is_follow_up(messages: Sequence[BaseMessage]) -> bool:
    """True when the turn's last message is from the user and an earlier reply exists."""
    if not messages or not isinstance(messages[-1], HumanMessage):
        return False
    return any(isinstance(m, AIMessage) for m in messages[:-1])


def _with_reminder(message: HumanMessage, reminder: str) -> HumanMessage:
    content = message.content
    if isinstance(content, str):
        new_content: Any = f"{content}\n\n{reminder}"
    else:
        new_content = [*list(content), {"type": "text", "text": reminder}]
    return message.model_copy(update={"content": new_content})


def follow_up_messages(messages: Sequence[BaseMessage], reminder: str = FOLLOW_UP_REMINDER) -> List[BaseMessage]:
    """Messages for the main agent: the latest user message carries the reminder on a follow-up."""
    out = list(messages)
    if reminder and is_follow_up(out):
        out[-1] = _with_reminder(out[-1], reminder)
    return out


class CarefoldMainAgentNode(MainAgentNode):
    """Core's main agent node, reminded to delegate on follow-up turns."""

    def __init__(self, *args: Any, follow_up_reminder: str = FOLLOW_UP_REMINDER, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.follow_up_reminder = follow_up_reminder

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        messages = list(state.get("messages") or [])
        if not is_follow_up(messages):
            return await super().execute(state)
        # Same message count, so core still stores only the agent's new messages.
        view = dict(state)
        view["messages"] = follow_up_messages(messages, self.follow_up_reminder)
        return await super().execute(view)


__all__ = ["FOLLOW_UP_REMINDER", "CarefoldMainAgentNode", "follow_up_messages", "is_follow_up"]
