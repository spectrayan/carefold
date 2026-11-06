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

"""Test-only checkpoint keys: never touch the real OS keychain or vault.

``use_test_checkpoint_keyring`` turns core checkpoint encryption on with a
random per-test key by replacing core's keyring loader. Nothing here reads a
real KEK; tests that exercise KEK resolution itself patch the keyring backend
off explicitly.
"""

from __future__ import annotations

import os
from typing import Optional

import pytest


from yarvelle_core.vault import checkpoints as _cp  # noqa: E402

# Core's real loader (vault KEK -> keyring), captured before any test patches it.
_REAL_LOAD_CHECKPOINT_KEYRING = _cp.load_checkpoint_keyring


def use_real_checkpoint_key_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo the throwaway key for tests of real KEK resolution.

    Callers must also keep the OS keychain out (core ``kek.HAS_KEYRING`` False);
    the test session already forces the keyring null backend.
    """
    monkeypatch.setattr(_cp, "load_checkpoint_keyring", _REAL_LOAD_CHECKPOINT_KEYRING)
    _cp.reset_checkpoint_keyring_cache()


def install_test_checkpoint_keyring(
    monkeypatch: pytest.MonkeyPatch,
    *,
    kek: Optional[bytes] = None,
    version: int = 1,
):
    """Make core's checkpoint keyring a throwaway test key; settings untouched."""
    from yarvelle_core.vault import checkpoints as cp

    keyring = cp.CheckpointKeyring.from_kek(kek if kek is not None else os.urandom(32), version)
    monkeypatch.setattr(cp, "load_checkpoint_keyring", lambda version=None: keyring)
    cp.reset_checkpoint_keyring_cache()
    return keyring


def use_test_checkpoint_keyring(
    monkeypatch: pytest.MonkeyPatch,
    *,
    encryption: bool = True,
    plaintext_reads: bool = True,
    kek: Optional[bytes] = None,
    version: int = 1,
):
    """Set checkpoint encryption settings and a throwaway key; returns the keyring."""
    from yarvelle_core.config import settings

    monkeypatch.setattr(settings, "checkpoint_encryption", encryption)
    monkeypatch.setattr(settings, "checkpoint_plaintext_reads", plaintext_reads)
    monkeypatch.setattr(settings, "checkpoint_key_version", version)
    return install_test_checkpoint_keyring(monkeypatch, kek=kek, version=version)


def raw_checkpoint_rows(db_path) -> list:
    """(table, type, blob) for every serialized row, read straight from SQLite."""
    import sqlite3

    rows = []
    with sqlite3.connect(str(db_path)) as conn:
        for table, column in (("checkpoints", "checkpoint"), ("writes", "value")):
            for type_tag, blob in conn.execute(f"SELECT type, {column} FROM {table}"):  # noqa: S608
                if type_tag is not None:
                    rows.append((table, type_tag, bytes(blob or b"")))
    return rows


__all__ = [
    "install_test_checkpoint_keyring",
    "raw_checkpoint_rows",
    "use_real_checkpoint_key_loader",
    "use_test_checkpoint_keyring",
]
