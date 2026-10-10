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

"""Comprehensive unit and integration tests for carefold.workflows package.

Covers:
- AgentState schema and convenience helper functions
- BaseNode abstract contract, callable dunder, and log sanitization
- All 11 discrete nodes (InputGuardrail, Supervisor, Agent, Tool, ToolValidator,
  OutputGuardrail, Reflection, Refusal, Suggestion, Audit, Error)
- Specialist Supervisor Subgraph compilation, routing, and transitions
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from carefold.config import settings
from carefold.workflows import (
    AgentState,
    BaseNode,
    create_initial_state,
    extract_text_content,
    get_last_message,
    get_last_user_message,
    get_last_user_prompt_text,
)
from carefold.workflows.nodes import (
    AgentNode,
    AuditNode,
    ErrorNode,
    InputGuardrailNode,
    OutputGuardrailNode,
    ReflectionNode,
    RefusalNode,
    SuggestionNode,
    SupervisorNode,
    ToolNode,
    ToolValidatorNode,
)
from carefold.workflows.subgraphs import (
    build_supervisor_subgraph,
    create_supervisor_subgraph,
    route_specialist_return,
    route_supervisor,
)
from tests.fixtures.fake_model import FakeListChatModel


# ============================================================================
# 1. AgentState & Helper Functions
# ============================================================================

def test_agent_state_helper_extract_text_content():
    assert extract_text_content(None) == ""
    assert extract_text_content("sample string") == "sample string"
    assert extract_text_content(HumanMessage(content="hello world")) == "hello world"
    assert extract_text_content(HumanMessage(content=[{"text": "part 1"}, {"text": "part 2"}])) == "part 1 part 2"
    assert extract_text_content({"content": "nested text"}) == "nested text"
    assert extract_text_content({"text": "direct text"}) == "direct text"


def test_agent_state_helpers_message_retrieval():
    msg1 = HumanMessage(content="First message")
    msg2 = AIMessage(content="Second message")
    state = create_initial_state(
        thread_id="t-100",
        user_id="u-200",
        messages=[msg1, msg2],
    )

    last_user = get_last_user_message(state)
    assert last_user is not None
    assert last_user.content == "First message"

    last_msg = get_last_message(state)
    assert last_msg is not None
    assert last_msg.content == "Second message"

    prompt_text = get_last_user_prompt_text(state)
    assert prompt_text == "First message"


def test_create_initial_state_defaults_and_dict_conversion():
    state = create_initial_state(
        thread_id="thread-xyz",
        user_id="user-xyz",
        messages=[
            {"role": "user", "content": "Howdy"},
            {"role": "assistant", "content": "Welcome"},
            {"role": "system", "content": "System directive"},
            {"role": "tool", "content": "Tool result", "tool_call_id": "c1"},
        ],
    )
    assert state["thread_id"] == "thread-xyz"
    assert state["user_id"] == "user-xyz"
    assert len(state["messages"]) == 4
    assert isinstance(state["messages"][0], HumanMessage)
    assert isinstance(state["messages"][1], AIMessage)
    assert isinstance(state["messages"][2], SystemMessage)
    assert isinstance(state["messages"][3], ToolMessage)


# ============================================================================
# 2. BaseNode Interface
# ============================================================================

def test_base_node_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        BaseNode()


@pytest.mark.asyncio
async def test_base_node_subclass_execution_and_validation():
    class DummyNode(BaseNode):
        async def execute(self, state):
            self.validate_state(state, required_keys=["expected_key"])
            self.log_info("Executing dummy node")
            self.log_warning("Dummy warning")
            self.log_debug("Dummy debug")
            return {"result": "ok"}

    node = DummyNode()
    assert node.node_name == "DummyNode"
    assert repr(node) == "<DummyNode name='DummyNode'>"

    # Direct async __call__
    out = await node({"expected_key": "val"})
    assert out == {"result": "ok"}

    # Invalid state type
    with pytest.raises(TypeError):
        await node("invalid state string")  # type: ignore


def test_base_node_format_error_response():
    class TestNode(BaseNode):
        async def execute(self, state):
            return self.format_error_response("Failed on /Users/developer/secret.txt")

    node = TestNode()
    res = node.format_error_response("Failed on /Users/developer/secret.txt", next_step="error")
    assert "/Users/developer" not in res["error"]
    assert res["next_step"] == "error"


# ============================================================================
# 3. Discrete Nodes Unit Tests
# ============================================================================

@pytest.mark.asyncio
async def test_input_guardrail_node_safe_and_unsafe():
    node = InputGuardrailNode()

    # Safe prompt
    safe_out = await node.execute({"messages": [HumanMessage(content="What are my copay amounts?")]})
    assert safe_out["is_refusal"] is False
    assert safe_out["next_step"] == "supervisor"

    # Unsafe prompt (clinical diagnosis)
    unsafe_out = await node.execute({"messages": [HumanMessage(content="Diagnose my chest pain and shortness of breath.")]})
    assert unsafe_out["is_refusal"] is True
    assert unsafe_out["refused"] is True
    assert unsafe_out["next_step"] == "refusal"
    assert "diagnose" in unsafe_out["refusal_reason"]


@pytest.mark.asyncio
async def test_supervisor_node_intent_classification():
    node = SupervisorNode()

    # Benefits
    out_b = await node.execute({"messages": [HumanMessage(content="What is my in-network deductible?")]})
    assert out_b["routed_subgraph"] == "benefits-guide"

    # Visit
    out_v = await node.execute({"messages": [HumanMessage(content="Help me prepare a checklist for my doctor appointment")]})
    assert out_v["routed_subgraph"] == "visit-steward"

    # Habit
    out_h = await node.execute({"messages": [HumanMessage(content="Track my water intake habit")]})
    assert out_h["routed_subgraph"] == "habit-companion"

    # Extraction
    out_e = await node.execute({"messages": [HumanMessage(content="Extract this uploaded pdf dossier")]})
    assert out_e["routed_subgraph"] == "document-extractor"


@pytest.mark.asyncio
async def test_agent_node_execution():
    fake = FakeListChatModel(responses=["I can help review your health plan coverage."])
    node = AgentNode(model=fake)

    state = {
        "messages": [HumanMessage(content="Hello")],
        "current_agent": "benefits-guide",
    }
    out = await node.execute(state)
    assert "messages" in out
    assert out["output"] == "I can help review your health plan coverage."
    assert out["next_step"] == "output_guardrail"


@pytest.mark.asyncio
async def test_tool_node_allow_list_enforcement():
    node = ToolNode(allowed_tools=["workspace-note"])

    # Disallowed tool
    denied_state = {
        "tool_calls": [{"name": "system-exec-hack", "args": {}}],
    }
    out_denied = await node.execute(denied_state)
    assert len(out_denied["tool_traces"]) == 1
    assert out_denied["tool_traces"][0]["allowed"] is False
    assert out_denied["next_step"] == "tool_validator"


@pytest.mark.asyncio
async def test_tool_validator_node_truncation_and_cleansing():
    node = ToolValidatorNode(max_chars=20)
    dirty_output = "\x1b[32m" + "A" * 50 + "\x1b[0m"
    out = await node.execute({"tool_output": dirty_output})

    assert "\x1b" not in out["sanitized_output"]
    assert out["validation_metadata"]["truncated"] is True
    assert len(out["sanitized_output"]) <= 40


@pytest.mark.asyncio
async def test_output_guardrail_node_disclaimer_and_refusal():
    node = OutputGuardrailNode()

    # Compliant output appends disclaimer
    compliant_out = await node.execute({"output": "Your copay is $20 for in-network office visits."})
    assert compliant_out["is_compliant"] is True
    assert "disclaimer" in compliant_out["output"].lower()
    assert compliant_out["next_step"] == "suggestion"

    # Non-compliant hard violation routes to reflection
    non_compliant_out = await node.execute({"output": "You have asthma, take 500mg amoxicillin."})
    assert non_compliant_out["is_refusal"] is True
    assert non_compliant_out["next_step"] == "reflection"


@pytest.mark.asyncio
async def test_output_guardrail_node_two_tier_boundary_warning():
    """Verifies that Tier 2 diagnostic boundaries tag boundary_warning while routing to reflection."""
    node = OutputGuardrailNode()

    # Soft boundary violation (diagnostic assertion without prescription/dosing)
    output_text = "These symptoms suggest you have asthma. Here is an appointment preparation checklist."
    res = await node.execute({"output": output_text})

    assert res["is_refusal"] is True
    assert res["refused"] is True
    assert res["boundary_warning"] is True
    assert res["boundary_reason"] == "forbidden_intent:diagnose"
    assert res["next_step"] == "reflection"



@pytest.mark.asyncio
async def test_reflection_node_retry_loop_budget():
    node = ReflectionNode(max_reflections=2)

    # Iteration 1: below ceiling
    step1 = await node.execute({"reflection_count": 0, "max_reflections": 2, "output": "Attempt 1"})
    assert step1["reflection_count"] == 1
    assert step1["next_step"] == "agent"
    assert "Attempt 1" in step1["previous_attempts"]

    # Iteration 2: reaches ceiling
    step2 = await node.execute({"reflection_count": 2, "max_reflections": 2})
    assert step2["reflection_count"] == 2
    assert step2["next_step"] == "done"


@pytest.mark.asyncio
async def test_refusal_node_standard_output():
    node = RefusalNode()
    out = await node.execute({"refusal_reason": "dosing", "tool_calls": ["some_tool"]})

    assert out["is_refusal"] is True
    assert out["tool_calls"] == []
    assert out["next_step"] == "done"
    assert "911" in out["output"]
    assert "doctor" in out["output"].lower()


@pytest.mark.asyncio
async def test_suggestion_node_suppression_and_generation():
    node = SuggestionNode()

    # Suppressed on refusal
    suppressed = await node.execute({"is_refusal": True})
    assert suppressed["follow_up_suggestions"] == []
    assert suppressed["next_step"] == "done"

    # Generated on safe turn
    active = await node.execute({
        "current_agent": "visit-steward",
        "messages": [HumanMessage(content="Questions to ask my doctor")],
        "output": "Here are 3 questions.",
    })
    assert isinstance(active["follow_up_suggestions"], list)
    assert len(active["follow_up_suggestions"]) <= 4


@pytest.mark.asyncio
async def test_audit_node_logs_with_dual_timestamps(tmp_path: Path, monkeypatch):
    log_file = tmp_path / "test_audit.jsonl"
    monkeypatch.setattr(settings, "audit_log_path", log_file)

    node = AuditNode()
    out = await node.execute({"thread_id": "thread-999", "current_agent": "visit-steward"})
    assert out["audit_logged"] is True
    assert log_file.exists()

    last_line = json.loads(log_file.read_text().splitlines()[-1])
    assert "timestamp" in last_line
    assert "ts" in last_line


@pytest.mark.asyncio
async def test_error_node_cleanses_paths():
    node = ErrorNode()
    out = await node.execute({
        "error_exception": RuntimeError("Leak on /Users/secret/confidential/repo.py line 123"),
    })
    assert out["next_step"] == "done"
    assert "/Users/secret" not in out["error"]
    assert "[REDACTED_PATH]" in out["error"]


# ============================================================================
# 4. Supervisor Subgraph Tests
# ============================================================================

def test_supervisor_subgraph_compilation_and_routing():
    fake = FakeListChatModel(responses=["Benefits guidance", "Visit prep advice"])
    subgraph = build_supervisor_subgraph(model=fake)
    assert subgraph is not None

    # Routing helpers
    assert route_supervisor({"routed_subgraph": "benefits-guide"}) == "benefits_guide"
    assert route_supervisor({"routed_subgraph": "visit-steward"}) == "visit_steward"
    assert route_supervisor({"routed_subgraph": "document-extractor"}) == "document_extractor"
    assert route_supervisor({"routed_subgraph": "habit-companion"}) == "habit_companion"
    assert route_supervisor({"routed_subgraph": "unknown-specialist"}) == "generalist"

    # Return transition
    assert route_specialist_return({"next_step": "supervisor"}) == "supervisor_node"
    assert route_specialist_return({"requires_supervisor": True}) == "supervisor_node"
    assert route_specialist_return({"next_step": "done"}) == "__end__"
