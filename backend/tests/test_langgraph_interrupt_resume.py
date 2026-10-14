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

"""Unit and integration tests for LangGraph Interrupt, SSE Events, and Resume Flow (AU-18)."""

import asyncio
import json
import pytest
from typing import Any, Dict

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command

from carefold.constants.api import SSE_EVENT_APPROVAL_REQUIRED
from carefold.engine.tool_exec import (
    ToolContext,
    ToolSpec,
    compute_payload_hash,
)
from carefold.workflows.nodes.tool_node import ToolNode
from tests.e2e_autonomy.contracts import ApprovalStore


@pytest.fixture
def approval_store() -> ApprovalStore:
    return ApprovalStore()


@pytest.mark.asyncio
async def test_langgraph_interrupt_triggers_on_policy_gate(approval_store: ApprovalStore):
    """Asserts that ToolNode triggers interrupt and pauses graph when policy requires approval."""
    node = ToolNode(
        allowed_tools=["schedule_appointment"],
        approval_store=approval_store,
    )

    state = {
        "messages": [],
        "tool_calls": [{
            "id": "call_1",
            "name": "schedule_appointment",
            "args": {"url": "https://clinic.org/book", "date": "2026-10-25"},
        }],
        "profile_id": "prof-1",
        "user_id": "user-1",
        "thread_id": "thread-1",
    }

    builder = StateGraph(Dict[str, Any])
    builder.add_node("tools", node.execute)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)

    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "thread-1", "autonomy": "A1"}}

    custom_events = []
    async for ev in graph.astream_events(state, config=config, version="v2"):
        if ev.get("event") == "on_custom_event":
            custom_events.append(ev)

    # 1. Assert custom event emitted
    assert len(custom_events) == 1
    assert custom_events[0]["name"] == SSE_EVENT_APPROVAL_REQUIRED
    data = custom_events[0]["data"]
    assert data["type"] == SSE_EVENT_APPROVAL_REQUIRED
    assert data["tool_name"] == "schedule_appointment"
    assert data["risk_tier"] == "write_external"

    # 2. Assert graph paused at 'tools'
    graph_state = await graph.aget_state(config)
    assert graph_state.next == ("tools",)
    assert len(graph_state.tasks[0].interrupts) > 0


@pytest.mark.asyncio
async def test_langgraph_resume_consumes_approval_and_completes(approval_store: ApprovalStore):
    """Asserts that resuming with Command(resume=...) executes the tool and transitions status to consumed."""
    node = ToolNode(
        allowed_tools=["schedule_appointment"],
        approval_store=approval_store,
    )

    state = {
        "messages": [],
        "tool_calls": [{
            "id": "call_2",
            "name": "schedule_appointment",
            "args": {"url": "https://clinic.org/book", "date": "2026-10-25"},
        }],
        "profile_id": "prof-2",
        "user_id": "user-2",
        "thread_id": "thread-2",
    }

    builder = StateGraph(Dict[str, Any])
    builder.add_node("tools", node.execute)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)

    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "thread-2", "autonomy": "A1"}}

    # Turn 1: Pause
    async for _ in graph.astream_events(state, config=config, version="v2"):
        pass

    app_id = "app_thread-2_call_2"
    assert approval_store._records[app_id].status == "pending"

    # Steward approves
    approval_store.decide(app_id, "prof-2", "approved", edited_args=None, caller_id="u2", caller_permissions=["manage"])

    # Turn 2: Resume
    resume_cmd = Command(resume={"approval_id": app_id, "decision": "approved"})
    async for _ in graph.astream_events(resume_cmd, config=config, version="v2"):
        pass

    # Assert consumed status
    assert approval_store._records[app_id].status == "consumed"

    # Assert completed graph
    final_st = await graph.aget_state(config)
    assert final_st.next == ()


@pytest.mark.asyncio
async def test_production_db_interrupt_resume_consumes_token():
    """Asserts that ToolNode without test doubles uses SQLite DB, triggers interrupt, and consumes token on resume."""
    from sqlalchemy import select
    from carefold.db.session import get_session_factory, init_db
    from carefold.db.models import Approval, Profile

    await init_db()

    factory = get_session_factory()
    async with factory() as session:
        prof = Profile(id="prof-prod-1", name="Prod Profile")
        session.add(prof)
        await session.commit()

    node = ToolNode(allowed_tools=["schedule_appointment"])  # No approval_store passed!

    state = {
        "messages": [],
        "tool_calls": [{
            "id": "call_prod_1",
            "name": "schedule_appointment",
            "args": {"url": "https://clinic.org/book", "date": "2026-11-01"},
        }],
        "profile_id": "prof-prod-1",
        "user_id": "user-prod-1",
        "thread_id": "thread-prod-1",
    }

    builder = StateGraph(Dict[str, Any])
    builder.add_node("tools", node.execute)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)

    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "thread-prod-1", "autonomy": "A1"}}

    # Turn 1: Pause on interrupt
    async for _ in graph.astream_events(state, config=config, version="v2"):
        pass

    app_id = "app_thread-prod-1_call_prod_1"

    # Verify pending record created in SQLite DB
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(Approval).where(Approval.id == app_id)
        res = await session.execute(stmt)
        record = res.scalar_one_or_none()
        assert record is not None
        assert record.status == "pending"
        # Simulate steward approval
        record.status = "approved"
        await session.commit()

    # Turn 2: Resume with approved token
    resume_cmd = Command(resume={"approval_id": app_id, "decision": "approved"})
    async for _ in graph.astream_events(resume_cmd, config=config, version="v2"):
        pass

    # Verify atomic transition in DB from approved -> consumed
    async with factory() as session:
        stmt = select(Approval).where(Approval.id == app_id)
        res = await session.execute(stmt)
        record_after = res.scalar_one_or_none()
        assert record_after is not None
        assert record_after.status == "consumed"

    # Verify graph completed
    final_st = await graph.aget_state(config)
    assert final_st.next == ()

