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

"""Unified AgentState schema for Carefold LangGraph workflows.

Implements the central state TypedDict compliant with LangGraph reducer patterns,
supporting multi-agent routing, discrete execution nodes, tool sandboxing,
document extraction dossiers, reflection counters, and safety refusal gating.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional, Sequence, Union
from typing_extensions import TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """Unified state schema across all Carefold workflows and discrete nodes.

    Attributes:
        messages: Chat history with automatic LangGraph message reducer (add_messages).
        thread_id: Conversation session identifier for persistence & checkpointing.
        user_id: User identifier for access control and multi-tenant partitioning.
        current_agent: Active agent identifier (e.g. 'supervisor', 'visit-steward', 'benefits-guide').
        next_step: Target next step / router destination (e.g. 'agent', 'tools', 'refusal', 'reflection', 'done').
        routed_subgraph: Active specialist subgraph if routed (e.g. 'visit-steward', 'benefits-guide', 'extraction').
        document_dossiers: Structured Pydantic extraction dossiers (Insurance, Clinical, Generic).
        tool_traces: Recorded tool invocations, inputs, and sanitization/execution outputs.
        reflection_count: Current self-correction reflection loop iteration count.
        max_reflections: Maximum allowed reflection attempts before fallback/halting.
        is_refusal: Flag indicating whether input or output violated clinical safety guardrails.
        refusal_reason: Categorized safety refusal code (e.g. 'clinical_diagnosis', 'emergency_care').
        safety_metadata: Structured safety classification and policy check details.
        follow_up_suggestions: AI-generated follow-up next question chips.
        error: Standardized error message or code for user-facing graceful response.
        recalled_memories: Episodic and semantic memories recalled from BaseStore in Phase 1.
        memory_context: Formatted memory context injected into system prompt.

        tool_calls: Active or pending tool calls to be processed by ToolNode.
        tool_output: Raw or latest output produced by tool execution.
        sanitized_output: Size-capped and sanitized output produced by ToolValidatorNode.
        is_compliant: Flag indicating whether output passed clinical compliance checks.
        output: Current response generation text before or after guardrailing.
        error_exception: Raw exception instance caught during node execution for ErrorNode recovery.

        agent_id: Backward-compatible alias for current_agent.
        effective_tools: List of authorized tool names for active agent/skills.
        workspace_root: Sandboxed filesystem root for file tools.
        skills_dir: Sandboxed directory for agent skills.
        system_prompt: Dynamically assembled system prompt for current agent.
        refused: Backward-compatible alias for is_refusal.
        refusal_message: Formatted refusal message text.
        audit_events: Accumulated zero-body audit events.
        iteration_count: Tool invocation loop counter.
        turn_tool_events: Real-time tool lifecycle events.
        run_id: Execution run identifier.
        store_bodies: Flag to preserve or redact payload bodies in audit logs.
        record_graph_run_audit: Flag to trigger graph completion run audit event.
        critique: Feedback text generated during reflection loop.
        disclaimer: Added clinical disclaimer text.
        previous_attempts: History of previous response attempts during reflection.
        prompt: Raw prompt input string.
        error_key: Error lookup key in errors.yaml.
        status_code: HTTP status code associated with error.
    """

    # Message history with automatic LangGraph reducer
    messages: Annotated[List[BaseMessage], add_messages]

    # Session and user identifiers
    thread_id: str
    user_id: str

    # Routing and orchestration state
    current_agent: str
    next_step: str
    routed_subgraph: Optional[str]

    # Dossiers and tool execution traces
    document_dossiers: List[Dict[str, Any]]
    tool_traces: List[Dict[str, Any]]

    # Reflection loop control
    reflection_count: int
    max_reflections: int

    # Safety and refusal guardrail fields
    is_refusal: bool
    refusal_reason: Optional[str]
    safety_metadata: Dict[str, Any]
    follow_up_suggestions: List[str]

    # Error recovery
    error: Optional[str]

    # Execution helpers & discrete node payloads
    tool_calls: List[Dict[str, Any]]
    tool_output: Any
    sanitized_output: str
    is_compliant: bool
    output: str
    error_exception: Optional[Any]

    # Engine backward-compatibility fields
    agent_id: str
    effective_tools: List[str]
    workspace_root: str
    skills_dir: str
    system_prompt: Optional[str]
    refused: bool
    refusal_message: Optional[str]
    audit_events: Annotated[List[Dict[str, Any]], operator.add]
    iteration_count: int
    turn_tool_events: Annotated[List[Dict[str, Any]], operator.add]
    run_id: Optional[str]
    store_bodies: Optional[bool]
    record_graph_run_audit: Optional[bool]
    critique: Optional[str]
    disclaimer: Optional[str]
    previous_attempts: List[str]
    prompt: Optional[str]
    error_key: Optional[str]
    status_code: Optional[int]

    # Dynamic on-demand generated skills
    missing_skill: Optional[str]
    missing_skill_description: Optional[str]
    generated_skill: Optional[Dict[str, Any]]
    generated_skills: List[Dict[str, Any]]

    # Context Loading and Safety Gating (R2)
    attachments: List[str]
    notes: List[Dict[str, Any]]
    allow_clinical: bool
    emergency_red_flags: Optional[Dict[str, Any]]
    catalog_summary: Optional[str]
    target_domain: Optional[str]

    # Orchestrator Planning, Generic Provisioning & Multi-Agent Execution (R3-R5)
    execution_plan: Optional[Dict[str, Any]]
    provisioned_references: Dict[str, Any]
    specialist_outputs: Dict[str, Any]

    # Phase 1 Cognitive Memory Recall fields (M3, R3)
    recalled_memories: List[Dict[str, Any]]
    memory_context: Optional[str]


def extract_text_content(item: Any) -> str:
    """Extract plain text string from a message object, dict, or string.

    Args:
        item: BaseMessage instance, dict representation, or primitive string.

    Returns:
        Extracted text string, or empty string if None.
    """
    if item is None:
        return ""
    if isinstance(item, str):
        return item
    if isinstance(item, BaseMessage):
        content = item.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and "text" in part:
                    parts.append(str(part["text"]))
            return " ".join(parts)
        return str(content)
    if isinstance(item, dict):
        if "content" in item:
            return extract_text_content(item["content"])
        if "text" in item:
            return str(item["text"])
    return str(item)


def get_last_user_message(state: AgentState) -> Optional[BaseMessage]:
    """Retrieve the most recent human/user message from state['messages'].

    Handles both BaseMessage instances and raw dicts in the messages sequence.
    """
    messages = state.get("messages", [])
    if not messages:
        return None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg
        if isinstance(msg, dict) and msg.get("role") in ("user", "human"):
            return HumanMessage(content=str(msg.get("content", "")))
        if getattr(msg, "type", "") in ("human", "user"):
            return msg  # type: ignore[return-value]
    return None


def get_last_user_prompt_text(state: AgentState) -> str:
    """Extract plain text from the most recent human/user message in state."""
    msg = get_last_user_message(state)
    if msg is not None:
        return extract_text_content(msg)
    if state.get("prompt"):
        return str(state.get("prompt"))
    messages = state.get("messages", [])
    if messages:
        last = messages[-1]
        return extract_text_content(last)
    return ""


def get_last_message(state: AgentState) -> Optional[BaseMessage]:
    """Retrieve the most recent message from state['messages']."""
    messages = state.get("messages", [])
    if not messages:
        return None
    last = messages[-1]
    if isinstance(last, BaseMessage):
        return last
    if isinstance(last, dict):
        role = last.get("role", "user")
        content = str(last.get("content", ""))
        if role in ("assistant", "ai"):
            return AIMessage(content=content)
        if role == "system":
            return SystemMessage(content=content)
        if role == "tool":
            return ToolMessage(
                content=content,
                tool_call_id=last.get("tool_call_id", "call_default"),
            )
        return HumanMessage(content=content)
    return None


def create_initial_state(
    thread_id: str = "",
    user_id: str = "",
    current_agent: str = "supervisor",
    messages: Optional[Sequence[Union[BaseMessage, Dict[str, Any]]]] = None,
    **kwargs: Any,
) -> AgentState:
    """Create an initialized AgentState dictionary with standard defaults.

    Args:
        thread_id: Thread/session identifier.
        user_id: User identifier.
        current_agent: Initial active agent (default: 'supervisor').
        messages: Initial message sequence or dictionary payloads.
        **kwargs: Additional state overrides.

    Returns:
        Populated AgentState dictionary.
    """
    converted_messages: List[BaseMessage] = []
    if messages:
        for m in messages:
            if isinstance(m, BaseMessage):
                converted_messages.append(m)
            elif isinstance(m, dict):
                role = m.get("role", "user")
                content = str(m.get("content", ""))
                if role in ("user", "human"):
                    converted_messages.append(HumanMessage(content=content))
                elif role in ("assistant", "ai"):
                    converted_messages.append(AIMessage(content=content))
                elif role == "system":
                    converted_messages.append(SystemMessage(content=content))
                elif role == "tool":
                    converted_messages.append(
                        ToolMessage(
                            content=content,
                            tool_call_id=m.get("tool_call_id", "call_default"),
                        )
                    )
                else:
                    converted_messages.append(HumanMessage(content=content))

    state: AgentState = {
        "messages": converted_messages,
        "thread_id": thread_id,
        "user_id": user_id,
        "current_agent": current_agent,
        "agent_id": current_agent,
        "next_step": kwargs.get("next_step", "input_guardrail"),
        "routed_subgraph": kwargs.get("routed_subgraph", None),
        "document_dossiers": kwargs.get("document_dossiers", []),
        "tool_traces": kwargs.get("tool_traces", []),
        "reflection_count": kwargs.get("reflection_count", 0),
        "max_reflections": kwargs.get("max_reflections", 3),
        "is_refusal": kwargs.get("is_refusal", False),
        "refused": kwargs.get("is_refusal", False),
        "refusal_reason": kwargs.get("refusal_reason", None),
        "safety_metadata": kwargs.get("safety_metadata", {}),
        "follow_up_suggestions": kwargs.get("follow_up_suggestions", []),
        "error": kwargs.get("error", None),
        "tool_calls": kwargs.get("tool_calls", []),
        "is_compliant": kwargs.get("is_compliant", False),
        "output": kwargs.get("output", ""),
        "sanitized_output": kwargs.get("sanitized_output", ""),
        "effective_tools": kwargs.get("effective_tools", []),
        "audit_events": kwargs.get("audit_events", []),
        "iteration_count": kwargs.get("iteration_count", 0),
        "turn_tool_events": kwargs.get("turn_tool_events", []),
        "attachments": kwargs.get("attachments", []),
        "notes": kwargs.get("notes", []),
        "allow_clinical": kwargs.get("allow_clinical", False),
        "emergency_red_flags": kwargs.get("emergency_red_flags", None),
        "catalog_summary": kwargs.get("catalog_summary", ""),
        "target_domain": kwargs.get("target_domain", None),
        "execution_plan": kwargs.get("execution_plan", None),
        "provisioned_references": kwargs.get("provisioned_references", {}),
        "specialist_outputs": kwargs.get("specialist_outputs", {}),
        "recalled_memories": kwargs.get("recalled_memories", []),
        "memory_context": kwargs.get("memory_context", None),
    }
    for k, v in kwargs.items():
        if k not in state:
            state[k] = v  # type: ignore[literal-required]
    return state


__all__ = [
    "AgentState",
    "create_initial_state",
    "extract_text_content",
    "get_last_message",
    "get_last_user_message",
    "get_last_user_prompt_text",
]
