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
from tests.fixtures.checkpoint_crypto import (
    raw_checkpoint_rows,
    use_real_checkpoint_key_loader,
    use_test_checkpoint_keyring,
)
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


# ---------------------------------------------------------------------------
# Encryption on by default (F4)
# ---------------------------------------------------------------------------

_CHECKPOINT_PREFIXES = ("CAREFOLD_CHECKPOINT_", "YARVELLE_CORE_CHECKPOINT_")


def _fresh_settings(extra_env: dict) -> str:
    import os
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[3]
    env = {k: v for k, v in os.environ.items() if not k.startswith(_CHECKPOINT_PREFIXES)}
    env.update(extra_env)
    env["PYTHONPATH"] = str(repo_root / "backend" / "src")
    code = (
        "import carefold\n"
        "from yarvelle_core.config import settings as s\n"
        "from carefold.config import settings as cs\n"
        "print(s.checkpoint_encryption, s.checkpoint_plaintext_reads,"
        " s.audit_store_bodies, cs.audit_store_bodies)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True, timeout=120
    )
    return out.stdout.strip().splitlines()[-1]


def test_checkpoint_encryption_is_on_by_default_and_other_defaults_unchanged() -> None:
    """Carefold turns checkpoint encryption on; plaintext reads stay on for migration.

    Audit body storage (a separate setting) keeps its default off.
    """
    assert _fresh_settings({}) == "True True False False"


@pytest.mark.parametrize(
    "name", ["CAREFOLD_CHECKPOINT_ENCRYPTION", "YARVELLE_CORE_CHECKPOINT_ENCRYPTION"]
)
def test_explicit_checkpoint_encryption_opt_out_is_respected(name: str) -> None:
    assert _fresh_settings({name: "false"}).split()[0] == "False"


def test_invalid_carefold_opt_out_value_does_not_disable_encryption() -> None:
    """A typo in CAREFOLD_CHECKPOINT_ENCRYPTION is ignored, not read as 'off'."""
    assert _fresh_settings({"CAREFOLD_CHECKPOINT_ENCRYPTION": "maybe"}).split()[0] == "True"


@pytest.mark.asyncio
async def test_turn_without_vault_key_fails_closed_and_writes_no_plaintext(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Encryption on and no vault key: the turn errors; nothing is written in plaintext."""
    from yarvelle_core.config import settings
    from yarvelle_core.vault import checkpoints as cp
    from yarvelle_core.vault import kek as core_kek

    monkeypatch.setattr(settings, "checkpoint_encryption", True)
    use_real_checkpoint_key_loader(monkeypatch)
    monkeypatch.setattr(core_kek, "HAS_KEYRING", False)  # never the real OS keychain
    for name in ("VAULT_KEK_FILE", "VAULT_PASSPHRASE"):
        monkeypatch.delenv(f"CAREFOLD_{name}", raising=False)
        monkeypatch.delenv(f"YARVELLE_{name}", raising=False)
    cp.reset_checkpoint_keyring_cache()

    events = await _run_turn(temp_workspace, "f4-no-key-thread")

    errors = [e for e in events if e["type"] == "error"]
    assert errors
    # The user is told what to do: configure the vault key or turn encryption off.
    assert any("vault key" in str(e.get("message", "")) for e in errors), errors
    assert not any(e["type"] == "done" and not e.get("error") and e.get("fullText") for e in events)
    db = temp_workspace / "chats" / "checkpoints.db"
    rows = raw_checkpoint_rows(db) if db.is_file() else []
    assert not any(not t.endswith("+aes256gcm") for _, t, _ in rows)
    assert not any(PROMPT.encode() in blob for _, _, blob in rows)


def test_resume_without_vault_key_reports_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resuming with encryption on and no vault key returns the setup message, not a generic error."""
    from yarvelle_core.config import settings
    from yarvelle_core.vault import checkpoints as cp
    from yarvelle_core.vault import kek as core_kek

    from carefold.checkpoint_env import CHECKPOINT_KEY_MISSING_MESSAGE

    monkeypatch.setattr(settings, "checkpoint_encryption", True)
    use_real_checkpoint_key_loader(monkeypatch)
    monkeypatch.setattr(core_kek, "HAS_KEYRING", False)  # never the real OS keychain
    for name in ("VAULT_KEK_FILE", "VAULT_PASSPHRASE"):
        monkeypatch.delenv(f"CAREFOLD_{name}", raising=False)
        monkeypatch.delenv(f"YARVELLE_{name}", raising=False)
    cp.reset_checkpoint_keyring_cache()

    res = TestClient(app).post(
        "/api/chat/resume",
        json={"thread_id": "f4-resume-no-key", "approval_id": "app-1", "decision": "approved"},
    )
    assert res.status_code == 200, res.text
    assert "event: error" in res.text
    assert "checkpoint_key_missing" in res.text
    assert CHECKPOINT_KEY_MISSING_MESSAGE in res.text
    assert "KEK is unavailable" not in res.text  # no internal error detail
