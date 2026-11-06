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

"""Core vault identity under Carefold: checkpoint keys come from the Carefold vault.

Core reads neutral identity settings (``<PREFIX>_VAULT_SALT``, keyring service
and alt user name). Carefold must supply the values its existing vault was
created with, or core would derive a different KEK (passphrase path) and a
different checkpoint key (HKDF salt) than Carefold's own vault.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

_IDENTITY_VARS = (
    "CAREFOLD_VAULT_SALT",
    "YARVELLE_VAULT_SALT",
    "CAREFOLD_KEYRING_SERVICE",
    "YARVELLE_KEYRING_SERVICE",
    "CAREFOLD_KEYRING_ALT_USERNAME",
    "YARVELLE_KEYRING_ALT_USERNAME",
)


def _run_fresh(code: str, extra_env: dict | None = None) -> str:
    env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_VARS}
    env["PYTHONPATH"] = str(REPO_ROOT / "backend" / "src")
    env.update(extra_env or {})
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True, timeout=120
    )
    return out.stdout.strip().splitlines()[-1]


def test_core_vault_identity_matches_carefold_vault_after_import() -> None:
    """A fresh interpreter importing carefold gives core the Carefold vault identity."""
    code = (
        "import carefold\n"
        "from yarvelle_core import identity\n"
        "from carefold.vault.kek import DEFAULT_ARGON2_SALT\n"
        "print(identity.vault_salt() == DEFAULT_ARGON2_SALT,"
        " identity.keyring_service() == 'carefold_vault',"
        " identity.keyring_alt_username() == 'carefold_kek')\n"
    )
    assert _run_fresh(code) == "True True True"


def test_operator_vault_salt_override_still_wins() -> None:
    """An explicit CAREFOLD_VAULT_SALT is not overwritten by the Carefold default."""
    code = (
        "import carefold\n"
        "from yarvelle_core import identity\n"
        "print(identity.vault_salt() == b'f4-test-salt-16b')\n"
    )
    assert _run_fresh(code, {"CAREFOLD_VAULT_SALT": "f4-test-salt-16b"}) == "True"


def test_core_passphrase_kek_matches_carefold_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same passphrase -> same KEK in core and Carefold vaults (no OS keychain access)."""
    import carefold  # noqa: F401
    from yarvelle_core.vault import kek as core_kek

    from carefold.vault import kek as cf_kek

    monkeypatch.delenv("CAREFOLD_VAULT_SALT", raising=False)
    monkeypatch.delenv("CAREFOLD_VAULT_KEK_FILE", raising=False)
    monkeypatch.setattr(core_kek, "HAS_KEYRING", False)
    monkeypatch.setattr(cf_kek, "HAS_KEYRING", False)
    passphrase = "f4 synthetic test passphrase"

    core_value = core_kek.resolve_kek(mode="local", passphrase=passphrase)
    carefold_value = cf_kek.resolve_kek(mode="local", passphrase=passphrase)

    assert core_value == carefold_value
