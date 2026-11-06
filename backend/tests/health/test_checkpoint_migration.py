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

"""Checkpoint migration to encryption at rest, and restored-thread compatibility.

A golden-schema checkpoint DB in the pre-F2 (legacy forked engine) state shape
is written plaintext, as installs before F4 wrote it. ``carefold.checkpoints``
must migrate it without losing history: same threads, same messages, legacy
threads still resume. Keys are throwaway test keys or a temp KEK file; the
real OS keychain is never consulted. All content is synthetic.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import empty_checkpoint
import pytest

from tests.fixtures.checkpoint_crypto import raw_checkpoint_rows, use_test_checkpoint_keyring
from tests.fixtures.fake_model import MockModelClient

LEGACY_THREAD = "f4-golden-legacy-thread"
LEGACY_PROMPT = "Synthetic golden legacy question about coinsurance"

# Channel set written by the pre-F2 Carefold engine (8b3538b); lacks the core
# 0.2 channels explicit_agent, guardrail_flags, orchestration_notices,
# provenance, route_decision, routed_subgraph and turn_id.
LEGACY_CHANNELS = {
    "agent_id": "benefits-coordinator",
    "current_agent": "benefits-coordinator",
    "allow_clinical": True,
    "attachments": [],
    "audit_events": [],
    "disclaimer": None,
    "document_dossiers": [],
    "effective_tools": [],
    "emergency_red_flags": [],
    "error": None,
    "execution_plan": None,
    "follow_up_suggestions": ["Synthetic follow-up?"],
    "is_compliant": True,
    "is_refusal": False,
    "iteration_count": 1,
    "next_step": None,
    "notes": [],
    "output": "Synthetic golden legacy answer.",
    "refused": False,
    "reflection_count": 0,
    "specialist_outputs": {},
    "thread_id": LEGACY_THREAD,
}


def _write_golden_legacy_db(db_path: Path) -> None:
    """Plaintext checkpoint DB with one legacy-shaped thread (two messages)."""
    from yarvelle_core.vault.checkpoints import PlaintextCheckpointSerializer

    from carefold.engine.graph import create_sqlite_saver

    saver = create_sqlite_saver(db_path, serde=PlaintextCheckpointSerializer())
    try:
        ckpt = empty_checkpoint()
        values = dict(LEGACY_CHANNELS)
        values["messages"] = [
            HumanMessage(content=LEGACY_PROMPT, id="legacy-h1"),
            AIMessage(content="Synthetic golden legacy answer.", id="legacy-a1"),
        ]
        ckpt["channel_values"] = values
        version = saver.get_next_version(None, None)  # same version format the saver writes
        ckpt["channel_versions"] = {k: version for k in values}
        config = {"configurable": {"thread_id": LEGACY_THREAD, "checkpoint_ns": ""}}
        saver.put(config, ckpt, {"source": "loop", "step": 1}, ckpt["channel_versions"])
    finally:
        saver.conn.close()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cli(argv: list[str], capsys: pytest.CaptureFixture) -> tuple[int, dict]:
    from carefold.checkpoints import main

    code = main(argv + ["--json"])
    out = capsys.readouterr().out
    return code, json.loads(out) if out.strip().startswith("{") else {"raw": out}


@pytest.fixture
def golden_db(tmp_path: Path) -> Path:
    db = tmp_path / "chats" / "checkpoints.db"
    _write_golden_legacy_db(db)
    return db


def test_verify_reports_threads_and_messages_without_content(
    golden_db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    use_test_checkpoint_keyring(monkeypatch)
    code, report = _cli(["verify", "--db", str(golden_db)], capsys)

    assert code == 0
    assert report["ok"] is True
    assert report["threads"][LEGACY_THREAD]["messages"] == 2
    assert LEGACY_PROMPT not in json.dumps(report)


def test_encrypt_migrates_legacy_db_without_losing_history(
    golden_db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    keyring = use_test_checkpoint_keyring(monkeypatch)
    _, before = _cli(["verify", "--db", str(golden_db)], capsys)

    code, report = _cli(["encrypt", "--db", str(golden_db)], capsys)

    assert code == 0, report
    assert report["migration"]["plaintext_rows"] > 0
    assert report["migration"]["rows_changed"] == report["migration"]["plaintext_rows"]
    assert report["after"]["threads"] == before["threads"]  # same threads, counts, digests
    assert report["active_key_id"] == keyring.active.key_id
    backup = Path(report["migration"]["backup_path"])
    assert backup.is_file() and LEGACY_PROMPT.encode() in backup.read_bytes()  # plaintext pre-migration copy
    rows = raw_checkpoint_rows(golden_db)
    assert rows and all(t.endswith("+aes256gcm") for _, t, _ in rows)
    assert LEGACY_PROMPT.encode() not in golden_db.read_bytes()

    # After migration plaintext reads can be switched off and every thread still loads.
    from yarvelle_core.config import settings

    monkeypatch.setattr(settings, "checkpoint_plaintext_reads", False)
    code, after = _cli(["verify", "--db", str(golden_db)], capsys)
    assert code == 0 and after["threads"] == before["threads"]


@pytest.mark.asyncio
async def test_migrated_legacy_thread_resumes_with_history(
    golden_db: Path, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A legacy thread, migrated to encrypted rows, takes a new turn and keeps its history."""
    from carefold.checkpoints import main
    from carefold.engine.runner import execute_agent_run

    use_test_checkpoint_keyring(monkeypatch)
    assert main(["encrypt", "--db", str(golden_db), "--json"]) == 0
    capsys.readouterr()

    model = MockModelClient()
    model.queue_response("Synthetic resumed answer.")
    events = [
        ev
        async for ev in execute_agent_run(
            agent_id="benefits-coordinator",
            prompt="Synthetic follow-up after migration",
            thread_id=LEGACY_THREAD,
            model_client=model,
            workspace_root=temp_workspace,
            checkpointer_db_path=golden_db,
        )
    ]
    assert any(e["type"] == "done" for e in events), [e.get("type") for e in events]
    assert not any(e["type"] == "error" for e in events)

    code, report = _cli(["verify", "--db", str(golden_db)], capsys)
    assert code == 0
    assert report["threads"][LEGACY_THREAD]["messages"] == 4
    assert all(t.endswith("+aes256gcm") for _, t, _ in raw_checkpoint_rows(golden_db))


def test_verify_fails_clearly_when_plaintext_reads_are_off_before_migration(
    golden_db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    use_test_checkpoint_keyring(monkeypatch, plaintext_reads=False)
    code, report = _cli(["verify", "--db", str(golden_db)], capsys)

    assert code == 1
    assert report["ok"] is False
    assert "plaintext" in report["threads"][LEGACY_THREAD]["error"].lower()


def test_wrong_key_cannot_read_and_leaves_db_unchanged(
    golden_db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    use_test_checkpoint_keyring(monkeypatch)
    assert _cli(["encrypt", "--db", str(golden_db)], capsys)[0] == 0
    digest = _sha(golden_db)

    use_test_checkpoint_keyring(monkeypatch)  # a different random key
    code, report = _cli(["verify", "--db", str(golden_db)], capsys)
    assert code == 1 and report["ok"] is False
    code, report = _cli(["decrypt", "--db", str(golden_db)], capsys)
    assert code == 1
    assert _sha(golden_db) == digest


def test_missing_vault_key_fails_closed_without_touching_db(
    golden_db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """No keyring entry, KEK file or passphrase: clear error, DB untouched, no backup."""
    from yarvelle_core.vault import checkpoints as cp
    from yarvelle_core.vault import kek as core_kek

    monkeypatch.setattr(core_kek, "HAS_KEYRING", False)  # never the real OS keychain
    for name in ("VAULT_KEK_FILE", "VAULT_PASSPHRASE"):
        monkeypatch.delenv(f"CAREFOLD_{name}", raising=False)
        monkeypatch.delenv(f"YARVELLE_{name}", raising=False)
    cp.reset_checkpoint_keyring_cache()
    digest = _sha(golden_db)

    from carefold.checkpoints import main

    code = main(["encrypt", "--db", str(golden_db)])
    err = capsys.readouterr().err

    assert code == 1
    assert "vault key" in err.lower()
    assert _sha(golden_db) == digest
    assert not list(golden_db.parent.glob("*.bak-*"))


def test_kek_file_roundtrip_uses_carefold_vault_identity(
    golden_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Real key path: KEK file -> Carefold-salted checkpoint key -> encrypt -> decrypt."""
    from yarvelle_core.config import settings
    from yarvelle_core.vault import checkpoints as cp
    from yarvelle_core.vault import kek as core_kek

    from carefold.vault.kek import DEFAULT_ARGON2_SALT

    kek = os.urandom(32)
    kek_file = tmp_path / "test-kek.bin"
    kek_file.write_bytes(kek)
    monkeypatch.setattr(core_kek, "HAS_KEYRING", False)
    monkeypatch.delenv("CAREFOLD_VAULT_SALT", raising=False)
    monkeypatch.setenv("CAREFOLD_VAULT_KEK_FILE", str(kek_file))
    monkeypatch.setattr(settings, "checkpoint_encryption", True)
    monkeypatch.setattr(settings, "checkpoint_plaintext_reads", True)
    cp.reset_checkpoint_keyring_cache()
    try:
        _, before = _cli(["verify", "--db", str(golden_db)], capsys)
        code, report = _cli(["encrypt", "--db", str(golden_db)], capsys)
        assert code == 0
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF

        expected = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=DEFAULT_ARGON2_SALT, info=b"checkpoints|v1"
        ).derive(kek)
        assert report["active_key_id"] == cp.checkpoint_key_id(expected, 1)

        code, report = _cli(["decrypt", "--db", str(golden_db)], capsys)
        assert code == 0
        with sqlite3.connect(str(golden_db)) as conn:
            types = {t for (t,) in conn.execute("SELECT type FROM checkpoints")}
        assert types == {"msgpack"}
        monkeypatch.setattr(settings, "checkpoint_encryption", False)
        _, after = _cli(["verify", "--db", str(golden_db)], capsys)
        assert after["threads"] == before["threads"]
    finally:
        cp.reset_checkpoint_keyring_cache()
