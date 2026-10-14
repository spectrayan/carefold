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

"""Unit, privacy, and concurrency tests for JSONL audit logger."""

import asyncio
import json
from pathlib import Path
import pytest

from carefold.audit.logger import get_recent_audit_events, record_audit
from carefold.audit.redaction import redact_audit_event
from carefold.schemas.audit import AuditEvent


def test_zero_body_redaction_policy():
    event = AuditEvent(
        agent_id="visit-steward",
        event="run",
        allowed=True,
        prompt="Sensitive user symptom: chest pain and anxiety",
        completion="Please consult emergency services immediately.",
    )

    # Default policy: store_bodies=False
    redacted = redact_audit_event(event, store_bodies=False)
    assert "prompt" not in redacted
    assert "completion" not in redacted
    assert redacted["agent_id"] == "visit-steward"
    assert redacted["event"] == "run"

    # Explicit override: store_bodies=True
    unredacted = redact_audit_event(event, store_bodies=True)
    assert unredacted.get("prompt") == "Sensitive user symptom: chest pain and anxiety"
    assert unredacted.get("completion") == "Please consult emergency services immediately."


@pytest.mark.asyncio
async def test_record_audit_writes_valid_jsonl(temp_workspace: Path):
    log_file = temp_workspace / "logs" / "test_audit.jsonl"

    ev1 = AuditEvent(
        agent_id="visit-steward",
        event="run",
        allowed=True,
        duration_ms=45.2,
        prompt="My secret query",
    )
    ev2 = AuditEvent(
        agent_id="visit-steward",
        event="refuse",
        allowed=False,
        reason="forbidden_intent:diagnose",
        duration_ms=12.1,
    )

    await record_audit(ev1, log_path=log_file, store_bodies=False)
    await record_audit(ev2, log_path=log_file, store_bodies=False)

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    # Verify each line is valid JSON
    entry1 = json.loads(lines[0])
    entry2 = json.loads(lines[1])

    assert entry1["agent_id"] == "visit-steward"
    assert entry1["event"] == "run"
    assert "prompt" not in entry1  # Redacted!

    assert entry2["agent_id"] == "visit-steward"
    assert entry2["event"] == "refuse"
    assert entry2["reason"] == "forbidden_intent:diagnose"


@pytest.mark.asyncio
async def test_audit_concurrency_lock(temp_workspace: Path):
    log_file = temp_workspace / "logs" / "concurrent_audit.jsonl"
    count = 25

    async def log_item(idx: int):
        ev = AuditEvent(
            agent_id=f"agent-{idx}",
            event="tool",
            tool="attach-read",
            allowed=True,
            duration_ms=float(idx),
        )
        await record_audit(ev, log_path=log_file, store_bodies=False)

    # Run 25 parallel appends
    await asyncio.gather(*(log_item(i) for i in range(count)))

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == count

    # Every single line must be valid, uncorrupted JSON
    agent_ids = set()
    for line in lines:
        data = json.loads(line)
        agent_ids.add(data["agent_id"])

    assert len(agent_ids) == count


@pytest.mark.asyncio
async def test_get_recent_audit_events(temp_workspace: Path):
    log_file = temp_workspace / "logs" / "query_audit.jsonl"

    for i in range(10):
        ev = AuditEvent(
            agent_id="agent-a" if i % 2 == 0 else "agent-b",
            event="run" if i < 5 else "refuse",
            allowed=True if i < 5 else False,
            duration_ms=float(i),
        )
        await record_audit(ev, log_path=log_file, store_bodies=False)

    # 1. Total and limit
    total, events = await get_recent_audit_events(log_path=log_file, limit=5)
    assert total == 10
    assert len(events) == 5

    # Newest first
    assert events[0].duration_ms == 9.0

    # 2. Filter by agent_id
    total_a, events_a = await get_recent_audit_events(log_path=log_file, agent_id="agent-a")
    assert total_a == 5
    assert all(e.agent_id == "agent-a" for e in events_a)

    # 3. Filter by event
    total_refuse, events_refuse = await get_recent_audit_events(log_path=log_file, event="refuse")
    assert total_refuse == 5
    assert all(e.event == "refuse" for e in events_refuse)
