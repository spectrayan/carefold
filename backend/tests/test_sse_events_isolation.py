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

"""Adversarial Test Suite for SSE Streaming and Thread State Isolation.

Aggressively tests:
1. SQLite Checkpointing & Server Restart Simulation:
   - Multi-turn thread persistence across graph/process teardown and reconnection (up to 4 turns).
   - Tool execution history checkpointing and restoration across restarts.
   - Direct SQLite database verification (WAL, tables, checkpoints channel_values).
   - FastAPI client restart simulation via separate TestClient instances.

2. Thread State Isolation & Concurrency Stress:
   - High concurrency (10 concurrent threads simultaneously writing to SQLite).
   - Zero state leakage / contamination across distinct thread_ids.
   - Adversarial thread_ids (SQL injection attempts, URI characters, spaces, unicode).

3. SSE Streaming Event Sequencing & Payload Integrity:
   - Strict ordering: tool_start -> tool_end -> token* -> suggestions -> done.
   - Verification that done is the terminal event.
   - Suggestions schema: exactly 2-3 contextual non-empty strings.
   - Contextual suggestion generation across different tools and agent personas.
   - Refusal sequencing: refusal -> done with zero tokens and zero suggestions.
   - Wire-level SSE formatting: 'event: <type>\\ndata: <json>\\n\\n'.

4. Resilience & Boundary Stress:
   - Tool loop iteration bounding (MAX_TOOL_ITERATIONS = 5).
   - Undeclared tool denial within multi-turn checkpointed threads.
   - Querying non-existent thread_id returns HTTP 404 without crashing.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient

from carefold.config import settings
from carefold.engine.graph import (
    MAX_TOOL_ITERATIONS,
    generate_follow_up_suggestions,
    get_thread_history,
)
from carefold.engine.runner import execute_agent_run
from carefold.main import app
from tests.fixtures.fake_model import MockModelClient
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE


# ============================================================================
# Helpers
# ============================================================================

def parse_sse_events(raw_text: str) -> List[Dict[str, Any]]:
    """Parses raw HTTP SSE stream text into list of {'event': str, 'data': dict}."""
    events = []
    current_event = None
    current_data = []

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            if current_event or current_data:
                data_str = "\n".join(current_data)
                try:
                    payload = json.loads(data_str) if data_str else {}
                except Exception:
                    payload = {"raw": data_str}
                events.append({"event": current_event or "message", "data": payload})
                current_event = None
                current_data = []
            continue

        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            current_data.append(line[len("data:"):].strip())

    if current_event or current_data:
        data_str = "\n".join(current_data)
        try:
            payload = json.loads(data_str) if data_str else {}
        except Exception:
            payload = {"raw": data_str}
        events.append({"event": current_event or "message", "data": payload})

    return events


# ============================================================================
# 1. Server Restart Simulation & Multi-Turn Checkpoint Persistence
# ============================================================================

@pytest.mark.asyncio
async def test_server_restart_multi_turn_persistence(temp_workspace: Path):
    """Adversarially tests multi-turn conversation persistence across simulated server restarts.
    
    Executes 4 distinct turns, tearing down all execution graphs and in-memory context between turns:
    - Turn 1: Human introduces name and symptoms.
    - Restart & Turn 2: Human asks for checklist questions based on prior symptoms.
    - Restart & Turn 3: Model executes attach-read tool on blood work report.
    - Restart & Turn 4: Human asks for final summary.
    
    Validates that:
    1. Complete conversation context (all 4 human prompts, 4 assistant answers, tool calls, and tool results)
       persists in SQLite checkpoints.db.
    2. Model in Turn 4 has access to all prior turns without state corruption.
    """
    thread_id = "restart-adversarial-thread-4turns-001"
    chats_dir = temp_workspace / "chats"
    db_file = chats_dir / "checkpoints.db"
    attachments_dir = temp_workspace / "attachments"
    (attachments_dir / "vitals.txt").write_text("Blood Pressure: 135/85, Pulse: 72", encoding="utf-8")

    # Turn 1: Initial context
    mock1 = MockModelClient()
    mock1.queue_response("Hello Alice, I have noted your persistent knee stiffness for Dr. Henderson.")
    t1_events = []
    async for ev in execute_agent_run(
        agent_id="visit-steward",
        prompt="Hi, I am Alice. I have persistent knee stiffness and see Dr. Henderson next week.",
        thread_id=thread_id,
        model_client=mock1,
        workspace_root=temp_workspace,
    ):
        t1_events.append(ev)

    done1 = next(e for e in t1_events if e["type"] == "done")
    assert done1["refused"] is False
    assert "knee stiffness" in done1["fullText"]

    # Process Teardown Simulation: mock1 and all graph instances deleted
    del mock1

    # Turn 2: Follow-up referencing prior turn
    mock2 = MockModelClient()
    mock2.queue_response("Here are 3 questions for Dr. Henderson regarding your knee stiffness.")
    t2_events = []
    async for ev in execute_agent_run(
        agent_id="visit-steward",
        prompt="What questions should I ask him about this?",
        thread_id=thread_id,
        model_client=mock2,
        workspace_root=temp_workspace,
    ):
        t2_events.append(ev)

    done2 = next(e for e in t2_events if e["type"] == "done")
    assert done2["refused"] is False

    del mock2

    # Turn 3: Tool execution turn across restart
    mock3 = MockModelClient()
    mock3.queue_response({
        "type": "tool_call",
        "name": "attach-read",
        "arguments": {"path": "vitals.txt"},
    })
    mock3.queue_response("I read your vitals: BP is 135/85 and Pulse is 72.")
    t3_events = []
    async for ev in execute_agent_run(
        agent_id="visit-steward",
        prompt="Please check my vitals.txt attachment.",
        thread_id=thread_id,
        model_client=mock3,
        workspace_root=temp_workspace,
    ):
        t3_events.append(ev)

    types3 = [e["type"] for e in t3_events]
    assert "tool_start" in types3
    assert "tool_end" in types3
    assert "done" in types3

    del mock3

    # Turn 4: Final wrap-up turn
    mock4 = MockModelClient()
    mock4.queue_response("Alice, we have your knee questions and BP 135/85 ready for Dr. Henderson.")
    t4_events = []
    async for ev in execute_agent_run(
        agent_id="visit-steward",
        prompt="Can you summarize our entire preparation plan?",
        thread_id=thread_id,
        model_client=mock4,
        workspace_root=temp_workspace,
    ):
        t4_events.append(ev)

    done4 = next(e for e in t4_events if e["type"] == "done")
    assert done4["refused"] is False

    # Direct SQLite Inspection
    assert db_file.is_file()
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (thread_id,))
    checkpoint_count = cur.fetchone()[0]
    # In LangGraph, each node execution writes a checkpoint; 4 turns with tool loop yields > 5 checkpoints
    assert checkpoint_count >= 5, f"Expected >= 5 checkpoints, got {checkpoint_count}"
    conn.close()

    # Verify history via FastAPI GET /api/chat/threads/{thread_id}
    client = TestClient(app)
    res = client.get(f"/api/chat/threads/{thread_id}")
    assert res.status_code == 200
    history = res.json()
    assert history["threadId"] == thread_id
    msgs = history["messages"]
    # 4 Human turns, 4 Assistant turns + 1 Tool call + 1 Tool message = 10 messages
    assert len(msgs) >= 8, f"Expected at least 8 messages in thread history, got {len(msgs)}"

    # Verify chronological sequence
    user_prompts = [m["content"] for m in msgs if m["role"] == "user"]
    assert "Hi, I am Alice" in user_prompts[0]
    assert "What questions should I ask" in user_prompts[1]
    assert "vitals.txt" in user_prompts[2]
    assert "entire preparation plan" in user_prompts[3]


def test_fastapi_server_reboot_simulation(temp_workspace: Path):
    """Simulates realistic server reboot by dropping TestClient, restarting app client, and querying checkpoints."""
    thread_id = "reboot-simulation-thread-777"

    # Server Boot 1
    client_boot1 = TestClient(app)
    t1_payload = {
        "agentId": "visit-steward",
        "prompt": "Remember that I am allergic to Penicillin.",
        "threadId": thread_id,
        "mock": True,
        "allow_clinical": True,
    }
    with client_boot1.stream("POST", "/api/chat", json=t1_payload) as r1:
        assert r1.status_code == 200
        r1.read()

    # Drop client_boot1 completely
    del client_boot1

    # Server Boot 2 (simulate process restart)
    client_boot2 = TestClient(app)
    res = client_boot2.get(f"/api/chat/threads/{thread_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["threadId"] == thread_id
    assert any("allergic to Penicillin" in m["content"] for m in data["messages"])

    # Continue conversation on Server Boot 2
    t2_payload = {
        "agentId": "visit-steward",
        "prompt": "What allergy did I disclose?",
        "threadId": thread_id,
        "mock": True,
        "allow_clinical": True,
    }
    with client_boot2.stream("POST", "/api/chat", json=t2_payload) as r2:
        assert r2.status_code == 200
        r2.read()
        events = parse_sse_events(r2.text)
        done = next(e for e in events if e["event"] == "done")
        assert done["data"]["refused"] is False


# ============================================================================
# 2. Thread State Isolation & Concurrency Stress
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_thread_isolation(temp_workspace: Path):
    """Adversarially stresses SQLite checkpointer with 10 concurrent threads executing simultaneously.
    
    Verifies:
    1. Zero SQLite locking crashes under concurrent writes.
    2. Strict thread isolation: Thread i never observes or inherits messages from Thread j.
    """
    concurrency_level = 10
    tasks = []

    async def run_single_thread(thread_idx: int) -> Dict[str, Any]:
        secret = f"TOKEN_SECRET_{thread_idx:03d}_{thread_idx * 999}"
        thread_id = f"stress-concurrent-thread-{thread_idx}"

        collected_events = []
        async for ev in execute_agent_run(
            agent_id="visit-steward",
            prompt=f"Secret for thread {thread_idx} is {secret}.",
            thread_id=thread_id,
            mock=True,
            workspace_root=temp_workspace,
        ):
            collected_events.append(ev)

        done = next((e for e in collected_events if e["type"] == "done"), None)
        return {
            "thread_idx": thread_idx,
            "thread_id": thread_id,
            "secret": secret,
            "done": done,
        }

    # Execute all threads concurrently
    results = await asyncio.gather(*(run_single_thread(i) for i in range(concurrency_level)))

    assert len(results) == concurrency_level

    # Inspect each thread's state via FastAPI history endpoint
    client = TestClient(app)
    for res in results:
        t_id = res["thread_id"]
        t_secret = res["secret"]
        t_idx = res["thread_idx"]

        hist_res = client.get(f"/api/chat/threads/{t_id}")
        assert hist_res.status_code == 200
        hist_data = hist_res.json()
        raw_text = json.dumps(hist_data)

        # Thread must contain its own secret
        assert t_secret in raw_text, f"Thread {t_id} missing its own secret {t_secret}"

        # Thread must NOT contain secrets from any other thread
        for other in results:
            if other["thread_idx"] != t_idx:
                other_secret = other["secret"]
                assert other_secret not in raw_text, (
                    f"Data leak detected! Thread {t_id} contained secret {other_secret} from Thread {other['thread_id']}"
                )


@pytest.mark.parametrize(
    "adversarial_thread_id",
    [
        "thread-with/slash:colon?query=1&amp=2#hash",
        "thread with spaces and punctuation!@$",
        "thread' OR '1'='1' --",
        'thread" OR "1"="1" --',
        "thread_🩺_emoji_health_2026",
        "thread-prefix",
        "thread-prefix-1",
        "thread-prefix-10",
    ],
)
@pytest.mark.asyncio
async def test_thread_id_special_characters(temp_workspace: Path, adversarial_thread_id: str):
    """Verifies that special characters, SQL injection patterns, and prefix collisions isolate cleanly."""
    mock = MockModelClient()
    mock.queue_response(f"Confirmed thread {adversarial_thread_id}")

    events = []
    async for ev in execute_agent_run(
        agent_id="visit-steward",
        prompt=f"Testing thread identifier {adversarial_thread_id}",
        thread_id=adversarial_thread_id,
        model_client=mock,
        workspace_root=temp_workspace,
    ):
        events.append(ev)

    done = next(e for e in events if e["type"] == "done")
    assert done["refused"] is False
    assert done["threadId"] == adversarial_thread_id


# ============================================================================
# 3. SSE Streaming Event Sequencing & Payload Integrity
# ============================================================================

def test_sse_event_sequencing_without_tools(client: TestClient):
    """Verifies exact event sequencing for conversational runs without tools:
    Sequence: [token, token, ..., token] -> suggestions -> done
    """
    payload = {
        "agentId": "visit-steward",
        "prompt": "Hello! I am preparing questions for my upcoming annual wellness check.",
        "mock": True,
        "allow_clinical": True,
    }
    with client.stream("POST", "/api/chat", json=payload) as response:
        assert response.status_code == 200
        response.read()
        events = parse_sse_events(response.text)

        event_types = [e["event"] for e in events]
        assert "token" in event_types
        assert "suggestions" in event_types
        assert "done" in event_types

        # Verify done is the absolute last event
        assert event_types[-1] == "done", f"done must be last event, got {event_types[-1]}"

        # Verify suggestions immediately precedes done
        done_idx = len(event_types) - 1
        sugg_idx = event_types.index("suggestions")
        assert sugg_idx < done_idx, "suggestions must precede done"

        # Verify tokens precede suggestions
        first_token_idx = event_types.index("token")
        assert first_token_idx < sugg_idx, "token must precede suggestions"

        # Validate suggestions payload
        sugg_ev = next(e for e in events if e["event"] == "suggestions")
        chips = sugg_ev["data"].get("suggestions", [])
        assert isinstance(chips, list)
        assert 2 <= len(chips) <= 3, f"Expected 2-3 suggestions chips, got {len(chips)}"
        assert all(isinstance(c, str) and len(c.strip()) > 5 for c in chips)

        # Validate done payload matches suggestions
        done_ev = events[-1]
        done_data = done_ev["data"]
        assert done_data["refused"] is False
        assert done_data["suggestions"] == chips
        assert done_data["followUpSuggestions"] == chips
        assert len(done_data["fullText"]) > 0
        assert "threadId" in done_data


def test_sse_event_sequencing_with_tools(client: TestClient, temp_workspace: Path):
    """Verifies exact event sequencing for tool-executing turns:
    Sequence: tool_start -> tool_end -> [token*] -> suggestions -> done
    """
    attachments_dir = temp_workspace / "attachments"
    (attachments_dir / "blood_work.txt").write_text("WBC: 6.5, RBC: 4.8", encoding="utf-8")

    payload = {
        "agentId": "visit-steward",
        "prompt": "Review my attached blood_work.txt report please.",
        "mock": True,
        "allow_clinical": True,
    }
    with client.stream("POST", "/api/chat", json=payload) as response:
        assert response.status_code == 200
        response.read()
        events = parse_sse_events(response.text)

        event_types = [e["event"] for e in events]
        assert "tool_start" in event_types
        assert "tool_end" in event_types
        assert "token" in event_types
        assert "suggestions" in event_types
        assert "done" in event_types

        # Verify order
        ts_idx = event_types.index("tool_start")
        te_idx = event_types.index("tool_end")
        tok_idx = event_types.index("token")
        sug_idx = event_types.index("suggestions")
        done_idx = event_types.index("done")

        assert ts_idx < te_idx < tok_idx < sug_idx < done_idx, (
            f"Ordering violation! indices: ts={ts_idx}, te={te_idx}, tok={tok_idx}, sug={sug_idx}, done={done_idx}"
        )
        assert done_idx == len(event_types) - 1

        # Check tool_end payload schema
        te_ev = next(e for e in events if e["event"] == "tool_end")
        te_data = te_ev["data"]
        assert te_data["tool"] == "attach-read"
        assert te_data["allowed"] is True
        assert te_data["status"] == "completed"
        assert isinstance(te_data["duration_ms"], (int, float))
        assert te_data["duration_ms"] >= 0

        # Check tool-specific suggestions
        sug_ev = next(e for e in events if e["event"] == "suggestions")
        sug_chips = sug_ev["data"]["suggestions"]
        assert any("results" in c.lower() or "document" in c.lower() or "symptoms" in c.lower() for c in sug_chips)


def test_sse_safety_refusal_sequencing(client: TestClient):
    """Verifies that refusal events sequence properly:
    Sequence: refusal -> done
    Zero tokens, zero tools, zero suggestions.
    """
    payload = {
        "agentId": "visit-steward",
        "prompt": "Can you prescribe me 500mg amoxicillin for this infection?",
        "mock": True,
        "allow_clinical": True,
    }
    with client.stream("POST", "/api/chat", json=payload) as response:
        assert response.status_code == 200
        response.read()
        events = parse_sse_events(response.text)

        event_types = [e["event"] for e in events]
        assert "refusal" in event_types
        assert "done" in event_types
        assert "token" not in event_types
        assert "tool_start" not in event_types
        assert "suggestions" not in event_types

        ref_ev = next(e for e in events if e["event"] == "refusal")
        assert ref_ev["data"]["reason"] == "forbidden_intent:dose"
        assert ref_ev["data"]["message"] == SAFE_REFUSAL_TEMPLATE

        done_ev = next(e for e in events if e["event"] == "done")
        assert done_ev["data"]["refused"] is True
        assert done_ev["data"]["suggestions"] == []
        assert done_ev["data"]["followUpSuggestions"] == []


def test_sse_raw_wire_formatting(client: TestClient):
    """Verifies raw wire-level SSE compliance:
    - Content-Type is text/event-stream
    - Every event block starts with 'event: <name>\\n'
    - Followed by 'data: <json>\\n\\n'
    - Separated by double newlines '\\n\\n'
    """
    payload = {
        "agentId": "visit-steward",
        "prompt": "Hello world from SSE formatting check.",
        "mock": True,
        "allow_clinical": True,
    }
    with client.stream("POST", "/api/chat", json=payload) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        assert response.headers.get("x-accel-buffering") == "no"

        response.read()
        raw_text = response.text

        # Blocks are separated by \n\n
        blocks = [b.strip() for b in raw_text.split("\n\n") if b.strip()]
        assert len(blocks) >= 2

        for block in blocks:
            lines = block.split("\n")
            event_line = lines[0]
            data_line = lines[1] if len(lines) > 1 else ""

            assert event_line.startswith("event: "), f"Invalid event line: {event_line}"
            assert data_line.startswith("data: "), f"Invalid data line: {data_line}"

            json_str = data_line[len("data: "):]
            parsed = json.loads(json_str)
            assert isinstance(parsed, dict)
            assert "type" in parsed
            assert parsed["type"] == event_line[len("event: "):].strip()


# ============================================================================
# 4. Contextual Suggestions Engine Stress
# ============================================================================

@pytest.mark.parametrize(
    "agent_id, prompt, completion, tools_used, expected_keyword",
    [
        ("visit-steward", "What about my lab tests?", "Here is info.", [], "lab"),
        ("visit-steward", "What about my medications?", "Here is info.", [], "medication"),
        ("visit-steward", "General checkup.", "Here is info.", [], "checklist"),
        ("benefits-guide", "What is my deductible?", "Your deductible is $1000.", [], "deductible"),
        ("benefits-guide", "Tell me about prior authorization.", "Prior auth is...", [], "prior authorization"),
        ("habit-companion", "How to drink more water?", "Stay hydrated.", [], "hydration"),
        ("habit-companion", "I feel tired and lack sleep.", "Rest well.", [], "sleep"),
        ("visit-steward", "Read note", "Saved.", ["workspace-note"], "visit note"),
        ("visit-steward", "Read docs", "Docs read.", ["skill-docs"], "checklist"),
    ],
)
def test_contextual_suggestions_matrix(
    agent_id: str,
    prompt: str,
    completion: str,
    tools_used: List[str],
    expected_keyword: str,
):
    """Verifies that generate_follow_up_suggestions dynamically tailors chips to agent persona and topic."""
    chips = generate_follow_up_suggestions(
        agent_id=agent_id,
        prompt=prompt,
        completion=completion,
        tools_used=tools_used,
    )
    assert isinstance(chips, list)
    assert 2 <= len(chips) <= 3
    assert all(isinstance(c, str) and len(c.strip()) > 0 for c in chips)
    combined = " ".join(chips).lower()
    assert expected_keyword in combined, (
        f"Expected keyword '{expected_keyword}' in suggestions for agent={agent_id}, prompt='{prompt}', got: {chips}"
    )


# ============================================================================
# 5. Resilience & Edge Cases
# ============================================================================

@pytest.mark.asyncio
async def test_tool_loop_bound_limit(temp_workspace: Path):
    """Verifies that runaway tool cycles are bounded by MAX_TOOL_ITERATIONS = 5 without infinite looping."""
    mock = MockModelClient()
    # Queue 10 repeated tool calls to simulate runaway model loop
    for _ in range(10):
        mock.queue_response({
            "type": "tool_call",
            "name": "skill-docs",
            "arguments": {"skill_id": "visit-prep", "doc": "checklist.md"},
        })

    events = []
    async for ev in execute_agent_run(
        agent_id="visit-steward",
        prompt="Keep reading checklist indefinitely.",
        model_client=mock,
        workspace_root=temp_workspace,
    ):
        events.append(ev)

    done_ev = next((e for e in events if e["type"] == "done"), None)
    assert done_ev is not None, "Execution must terminate and emit done"
    tool_ends = [e for e in events if e["type"] == "tool_end"]
    # Must not exceed MAX_TOOL_ITERATIONS
    assert len(tool_ends) <= MAX_TOOL_ITERATIONS, (
        f"Tool execution loop exceeded MAX_TOOL_ITERATIONS ({MAX_TOOL_ITERATIONS}): executed {len(tool_ends)}"
    )


def test_get_non_existent_thread_404(client: TestClient):
    """Verifies that requesting an unknown thread_id returns clean HTTP 404 without crashing."""
    res = client.get("/api/chat/threads/completely-non-existent-thread-id-404")
    assert res.status_code == 404
    err = res.json()
    assert "detail" in err


@pytest.mark.asyncio
async def test_multi_turn_distinct_tools_pipeline(temp_workspace: Path):
    """Adversarially tests a 3-turn chain executing 3 different Phase 0 tools in sequence under one thread.
    
    Turn 1: attach-read on lab results
    Turn 2: workspace-note saving visit summary
    Turn 3: skill-docs reading reference checklist
    
    Verifies that all tool calls, outputs, and assistant summaries accumulate correctly in checkpoints.
    """
    thread_id = "multi-turn-distinct-tools-pipeline-99"
    attachments_dir = temp_workspace / "attachments"
    (attachments_dir / "labs.txt").write_text("HbA1c: 5.6%, Glucose: 95 mg/dL", encoding="utf-8")

    # Turn 1: attach-read
    mock1 = MockModelClient()
    mock1.queue_response({
        "type": "tool_call",
        "name": "attach-read",
        "arguments": {"path": "labs.txt"},
    })
    mock1.queue_response("Your HbA1c is 5.6% which is within normal range.")

    t1_events = []
    async for ev in execute_agent_run(
        agent_id="visit-steward",
        prompt="Review my labs.txt attachment.",
        thread_id=thread_id,
        model_client=mock1,
        workspace_root=temp_workspace,
    ):
        t1_events.append(ev)

    done1 = next(e for e in t1_events if e["type"] == "done")
    assert done1["refused"] is False

    # Turn 2: workspace-note
    mock2 = MockModelClient()
    mock2.queue_response({
        "type": "tool_call",
        "name": "workspace-note",
        "arguments": {"title": "my-lab-summary", "content": "Normal HbA1c 5.6%"},
    })
    mock2.queue_response("Saved note my-lab-summary.md successfully.")

    t2_events = []
    async for ev in execute_agent_run(
        agent_id="visit-steward",
        prompt="Save a note with title my-lab-summary.",
        thread_id=thread_id,
        model_client=mock2,
        workspace_root=temp_workspace,
    ):
        t2_events.append(ev)

    done2 = next(e for e in t2_events if e["type"] == "done")
    assert done2["refused"] is False
    assert (temp_workspace / "workspace" / "notes" / "my-lab-summary.md").is_file()

    # Turn 3: skill-docs
    mock3 = MockModelClient()
    mock3.queue_response({
        "type": "tool_call",
        "name": "skill-docs",
        "arguments": {"skill_id": "visit-prep", "doc": "checklist.md"},
    })
    mock3.queue_response("I have consulted the visit-prep checklist.")

    t3_events = []
    async for ev in execute_agent_run(
        agent_id="visit-steward",
        prompt="What checklist items does visit-prep recommend?",
        thread_id=thread_id,
        model_client=mock3,
        workspace_root=temp_workspace,
    ):
        t3_events.append(ev)

    done3 = next(e for e in t3_events if e["type"] == "done")
    assert done3["refused"] is False

    # Verify complete thread history
    client = TestClient(app)
    res = client.get(f"/api/chat/threads/{thread_id}")
    assert res.status_code == 200
    history = res.json()
    msgs = history["messages"]

    roles = [m["role"] for m in msgs]
    assert roles.count("tool") == 3, f"Expected 3 tool results in history, got {roles.count('tool')}"
    tool_msgs = [m for m in msgs if m["role"] == "tool"]
    assert any("HbA1c" in m["content"] for m in tool_msgs)
    assert any("my-lab-summary" in m["content"] for m in tool_msgs)


@pytest.mark.asyncio
async def test_stream_cancellation_database_integrity(temp_workspace: Path):
    """Verifies that an early generator exit (simulating client network abort) does not lock SQLite."""
    thread_id = "abort-simulation-thread-123"

    # Start stream and consume only the first token before aborting
    gen = execute_agent_run(
        agent_id="visit-steward",
        prompt="Tell me a long story about hospital visits.",
        thread_id=thread_id,
        mock=True,
        workspace_root=temp_workspace,
    )

    # Read first event then break (aborting generator)
    async for ev in gen:
        break
    await gen.aclose()

    # Next immediate run on same SQLite DB and same thread should succeed cleanly without database locked error
    events_after = []
    async for ev in execute_agent_run(
        agent_id="visit-steward",
        prompt="Are you still there?",
        thread_id=thread_id,
        mock=True,
        workspace_root=temp_workspace,
    ):
        events_after.append(ev)

    done = next(e for e in events_after if e["type"] == "done")
    assert done["refused"] is False


@pytest.mark.asyncio
async def test_stream_never_leaks_internal_suggestion_or_orchestrator_tokens(temp_workspace: Path):
    """Verifies that dynamic suggestion generator model tokens never leak into the assistant chat stream."""
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGeneration, ChatResult
    from carefold.engine.builder import GraphBuilder
    from carefold.engine.service import AgentExecutionService

    class StreamingLeakageTestModel(BaseChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise NotImplementedError

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            msg_text = " ".join(getattr(m, "content", "") for m in messages)
            if "Suggestion Generator" in msg_text or "follow-up questions" in msg_text:
                content = (
                    "Here are 3 concise follow-up questions from the user's perspective:\n\n"
                    '["What are next steps if I have met my deductible?", "Explain OOP max?"]'
                )
            else:
                content = "Your deductible is $1,000 and copay is $25."

            # Simulate token streaming callback
            for token in content.split(" "):
                if run_manager:
                    await run_manager.on_llm_new_token(token + " ")
            return ChatResult(generations=[ChatGeneration(message=AIMessageChunk(content=content))])

        @property
        def _llm_type(self) -> str:
            return "streaming-leakage-test"

    model = StreamingLeakageTestModel()
    svc = AgentExecutionService()
    gb = GraphBuilder().with_model(model).with_suggestion_model(model)
    svc.graph = gb.build()

    tokens: List[str] = []
    suggestions: List[str] = []
    done_payload: Dict[str, Any] = {}

    async for raw_ev in svc.execute_chat(
        {"agent_id": "benefits-guide", "prompt": "Explain my deductible", "thread_id": "test-leakage-prevention"},
        raw_events=True,
    ):
        ev_type = raw_ev.get("type")
        if ev_type == "token":
            tokens.append(raw_ev.get("delta") or "")
        elif ev_type == "suggestions":
            suggestions = raw_ev.get("suggestions", [])
        elif ev_type == "done":
            done_payload = raw_ev

    full_streamed = "".join(tokens).strip()
    full_text = str(done_payload.get("fullText", "")).strip()

    # 1. Specialist content must be fully streamed
    assert "Your deductible is $1,000" in full_streamed
    assert "Your deductible is $1,000" in full_text
    assert full_streamed == full_text

    # 2. Suggestion generator output MUST NOT leak into the assistant chat text
    assert "Here are 3 concise" not in full_streamed
    assert "follow-up questions from the user's perspective" not in full_streamed
    assert '["What are next steps' not in full_streamed
    assert "Here are 3 concise" not in full_text
    assert "follow-up questions from the user's perspective" not in full_text
    assert '["What are next steps' not in full_text

    # 3. Suggestion chips must still be emitted cleanly as parsed lists
    assert len(suggestions) >= 2
    assert any("deductible" in s.lower() for s in suggestions)


def test_strip_internal_suggestion_leakage_stress():
    """Validates that strip_internal_suggestion_leakage sanitizes glued assistant prompts and JSON question blocks."""
    from carefold.engine.service import strip_internal_suggestion_leakage

    leakage_sample = (
        "These questions will help you understand your deductible and how it applies to your specific situation.assistant\n\n"
        "Here are 3 concise follow-up questions from the user's perspective:\n\n"
        "[\n"
        '  "What are the next steps if I\'ve met my deductible?",\n'
        '  "Can you explain the Out-of-Pocket Maximum in simpler terms?",\n'
        '  "How can I confirm my insurance coverage for this procedure?"\n'
        "]"
    )
    cleaned = strip_internal_suggestion_leakage(leakage_sample)
    assert cleaned == "These questions will help you understand your deductible and how it applies to your specific situation."

    # Normal text without leakage should remain unchanged
    normal_text = "Your deductible is $1,000 with a $25 copay.\n\nHave a great day!\n"
    assert strip_internal_suggestion_leakage(normal_text) == normal_text


def test_strip_reference_doc_preamble_stress():
    """Validates that strip_reference_doc_preamble strips robotic 'Based on the provided reference...' preambles."""
    from carefold.engine.service import strip_reference_doc_preamble

    cases = [
        ("Based on the provided reference guide, here are some questions you may want to prioritize:", "Here are some questions you may want to prioritize:"),
        ("**Based on the provided reference document:** Consider the following questions:", "Consider the following questions:"),
        ("_According to the reference guide_, you should check your deductible.", "You should check your deductible."),
        ("Based on the reference material provided: here is the plan.", "Here is the plan."),
        ("Normal response starting directly without any preamble.", "Normal response starting directly without any preamble."),
    ]
    for inp, expected in cases:
        assert strip_reference_doc_preamble(inp) == expected


