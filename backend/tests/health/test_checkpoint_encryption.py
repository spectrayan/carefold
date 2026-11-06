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

"""Checkpoint encryption at rest in Carefold: every checkpoint reader decrypts.

Uses a throwaway test key (tests/fixtures/checkpoint_crypto.py); never the
real vault or OS keychain. Content is synthetic.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from carefold.engine.runner import execute_agent_run
from carefold.main import app
from tests.fixtures.checkpoint_crypto import raw_checkpoint_rows, use_test_checkpoint_keyring
from tests.fixtures.fake_model import MockModelClient

PROMPT = "Synthetic F4 prompt about a plan deductible"


async def _run_turn(ws: Path, thread_id: str, prompt: str = PROMPT, answer: str = "Synthetic F4 answer.") -> list:
    model = MockModelClient()
    model.queue_response(answer)
    events = []
    async for ev in execute_agent_run(
        agent_id="benefits-coordinator",
        prompt=prompt,
        thread_id=thread_id,
        model_client=model,
        workspace_root=ws,
    ):
        events.append(ev)
    return events


@pytest.mark.asyncio
async def test_thread_history_endpoint_reads_encrypted_checkpoints(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A thread written encrypted is restored by GET /api/chat/threads/{id}."""
    use_test_checkpoint_keyring(monkeypatch)
    thread_id = "f4-encrypted-history-thread"

    events = await _run_turn(temp_workspace, thread_id)
    assert any(e["type"] == "done" for e in events)

    rows = raw_checkpoint_rows(temp_workspace / "chats" / "checkpoints.db")
    assert rows and all(t.endswith("+aes256gcm") for _, t, _ in rows)
    assert not any(PROMPT.encode() in blob for _, _, blob in rows)

    res = TestClient(app).get(f"/api/chat/threads/{thread_id}")
    assert res.status_code == 200, res.text
    msgs = res.json()["messages"]
    assert [m["role"] for m in msgs][:2] == ["user", "assistant"]
    assert PROMPT in msgs[0]["content"]


def test_carefold_saver_factories_follow_checkpoint_encryption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """carefold.engine.graph savers use core's encryption-aware serializer."""
    from yarvelle_core.vault.checkpoints import EncryptedCheckpointSerializer

    from carefold.engine.graph import create_sqlite_saver

    use_test_checkpoint_keyring(monkeypatch)
    saver = create_sqlite_saver(tmp_path / "chats" / "checkpoints.db")
    try:
        assert isinstance(saver.serde, EncryptedCheckpointSerializer)
    finally:
        saver.conn.close()
