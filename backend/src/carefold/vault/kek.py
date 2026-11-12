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

"""KEK shim preserving Carefold Argon2id salt and carefold_vault keyring service name."""

from __future__ import annotations

from typing import Dict, Literal, Optional
from yarvelle_core.vault.kek import HAS_KEYRING, KekProvider, derive_argon2id_kek, get_kek, keyring, resolve_kek as _core_resolve_kek  # noqa: F401

DEFAULT_ARGON2_SALT = b"carefold_kek_sal"
KEYRING_SERVICE_NAME = "carefold_vault"


def resolve_kek(mode: Literal["local", "server"] = "local", keyring_store: Optional[Dict[str, str]] = None, kek_file_path: Optional[str] = None, passphrase: Optional[str] = None) -> bytes:
    store = dict(keyring_store) if keyring_store is not None else None
    if store is not None and "carefold_kek" in store and "kek_master" not in store:
        store["kek_master"] = store["carefold_kek"]
    elif store is None and mode == "local":
        raw = (keyring.get_password(KEYRING_SERVICE_NAME, "kek_master") or keyring.get_password(KEYRING_SERVICE_NAME, "carefold_kek")) if (HAS_KEYRING and keyring is not None) else None
        store = {"kek_master": raw} if raw is not None else {}
    return _core_resolve_kek(mode=mode, keyring_store=store, kek_file_path=kek_file_path, passphrase=passphrase)

import yarvelle_core.vault.kek as _yc_mod

def __getattr__(name: str):
    return getattr(_yc_mod, name)
