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

"""Carefold checkpoint encryption: status, migration and restore verification.

Usage::

    python -m carefold.checkpoints status|encrypt|decrypt|verify [--db PATH] [--json]

Importing ``carefold`` first gives core the Carefold vault identity, so the
checkpoint key is derived from the same vault KEK as the rest of Carefold
(running core's own ``yarvelle-core checkpoints`` without Carefold would use
core's neutral identity and a different key).

``encrypt`` checks every thread before and after the migration: the same
threads must load with the same message counts and message digests, or the
command fails and the plaintext backup written next to the database is kept.
``verify`` reports per thread only counts and digests, never message content.
Settings: CAREFOLD_CHECKPOINT_ENCRYPTION, CAREFOLD_CHECKPOINT_PLAINTEXT_READS,
CAREFOLD_CHECKPOINT_KEY_VERSION (vault key: OS keyring, CAREFOLD_VAULT_KEK_FILE
or CAREFOLD_VAULT_PASSPHRASE).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Sequence

import carefold  # noqa: F401  (Carefold identity and checkpoint settings for core)


@dataclass
class ThreadCheck:
    """Latest checkpoint of one thread: loads or not, message count and digest."""

    messages: int = 0
    digest: Optional[str] = None
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"messages": self.messages, "digest": self.digest}
        if self.error:
            out["error"] = self.error
        return out


@dataclass
class VerifyReport:
    """Every thread in a checkpoint DB checked with the active serializer."""

    db_path: str
    threads: Dict[str, ThreadCheck] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(t.error is None for t in self.threads.values())

    def summary(self) -> Dict[str, Dict[str, Any]]:
        return {tid: t.as_dict() for tid, t in sorted(self.threads.items())}

    def as_dict(self) -> Dict[str, Any]:
        return {"db_path": self.db_path, "ok": self.ok, "threads": self.summary()}


def default_checkpoint_db() -> Path:
    """The checkpoint DB the chat runtime and thread history use."""
    from carefold.config import settings
    from carefold.engine.graph import resolve_checkpointer_path

    db_path = resolve_checkpointer_path()
    if not db_path.is_file() and settings.workspace_root:
        ws_db = resolve_checkpointer_path(settings.workspace_root)
        if ws_db.is_file():
            return ws_db
    return db_path


def _thread_keys(db_path: Path) -> List[tuple]:
    uri = f"file:{db_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "checkpoints" not in names:
            return []
        return list(
            conn.execute(
                "SELECT DISTINCT thread_id, checkpoint_ns FROM checkpoints ORDER BY thread_id, checkpoint_ns"
            )
        )


def _digest(messages: Sequence[Any]) -> str:
    canon = [[getattr(m, "type", ""), getattr(m, "id", None), str(getattr(m, "content", ""))] for m in messages]
    return hashlib.sha256(json.dumps(canon, sort_keys=True).encode("utf-8")).hexdigest()


def verify_checkpoint_threads(db_path: Path) -> VerifyReport:
    """Load the latest checkpoint of every thread with the configured serializer."""
    from yarvelle_core.engine.graph import create_sqlite_saver

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"Checkpoint database not found: {path}")
    report = VerifyReport(db_path=str(path))
    keys = _thread_keys(path)
    if not keys:
        return report
    saver = create_sqlite_saver(path)
    try:
        for thread_id, ns in keys:
            label = thread_id if not ns else f"{thread_id}|{ns}"
            check = ThreadCheck()
            try:
                tup = saver.get_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ns}})
                values = (tup.checkpoint or {}).get("channel_values", {}) if tup else {}
                messages = list(values.get("messages") or [])
                check.messages = len(messages)
                check.digest = _digest(messages)
            except Exception as exc:  # report per thread; never print content
                check.error = f"{type(exc).__name__}: {exc}"
            report.threads[label] = check
    finally:
        saver.conn.close()
    return report


def _print(payload: Dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {json.dumps(value) if isinstance(value, (dict, list)) else value}")


def _run(args: argparse.Namespace) -> int:
    from yarvelle_core.vault.checkpoints import (
        checkpoint_db_status,
        decrypt_checkpoint_db,
        encrypt_checkpoint_db,
        load_checkpoint_keyring,
    )
    from yarvelle_core.vault.errors import VaultError

    db_path = Path(args.db).expanduser() if args.db else default_checkpoint_db()
    try:
        if args.action == "verify":
            report = verify_checkpoint_threads(db_path)
            _print(report.as_dict(), args.json)
            return 0 if report.ok else 1

        keyring = load_checkpoint_keyring(args.key_version)
        if args.action == "status":
            status = checkpoint_db_status(db_path, keyring)
            _print({**status.as_dict(), "active_key_id": keyring.active.key_id}, args.json)
            return 0

        before = verify_checkpoint_threads(db_path)
        if not before.ok and args.action == "encrypt":
            # Rows that cannot be read now cannot be re-encrypted safely.
            _print({"error": "some threads do not load; nothing changed", "before": before.as_dict()}, args.json)
            return 1
        migrate = encrypt_checkpoint_db if args.action == "encrypt" else decrypt_checkpoint_db
        result = migrate(db_path, keyring, dry_run=args.dry_run, backup=not args.no_backup)
        payload: Dict[str, Any] = {
            "migration": result.as_dict(),
            "active_key_id": keyring.active.key_id,
            "before": before.as_dict(),
        }
        if args.dry_run or args.action == "decrypt":
            _print(payload, args.json)
            return 0
        after = verify_checkpoint_threads(db_path)
        payload["after"] = after.as_dict()
        payload["history_preserved"] = after.ok and after.summary() == before.summary()
        _print(payload, args.json)
        if not payload["history_preserved"]:
            print(
                "Error: threads differ after migration; keep the backup "
                f"({result.backup_path}) and restore it before using the database.",
                file=sys.stderr,
            )
            return 1
        return 0
    except (VaultError, FileNotFoundError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m carefold.checkpoints",
        description="Carefold checkpoint encryption: status, encrypt, decrypt, verify.",
    )
    parser.add_argument("action", choices=("status", "encrypt", "decrypt", "verify"))
    parser.add_argument("--db", default=None, help="Checkpoint database (default: the chat runtime's)")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing")
    parser.add_argument("--no-backup", action="store_true", help="Skip the backup copy written before changes")
    parser.add_argument("--key-version", type=int, default=None, help="Active key version")
    parser.add_argument("--json", action="store_true", help="Print a JSON report")
    return _run(parser.parse_args(list(argv) if argv is not None else None))


__all__ = ["ThreadCheck", "VerifyReport", "default_checkpoint_db", "main", "verify_checkpoint_threads"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
