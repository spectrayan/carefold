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

"""Docker Compose and Helm deploys give the backend a vault key for encrypted chats.

Checkpoint encryption is on by default and fails closed without a vault key
(KEK). Deploys must supply the key as a mounted file, run in server mode so a
missing key stops startup with a clear message, and never turn encryption off
on their own. Helm checks run only where the ``helm`` binary is installed.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, List

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "deploy" / "docker" / "docker-compose.yml"
COMPOSE_ENV_EXAMPLE = REPO_ROOT / "deploy" / "docker" / ".env.example"
CHART = REPO_ROOT / "deploy" / "helm" / "carefold"
SECRET_FILE = "/run/secrets/carefold_vault_kek"


def _env_map(entries: List[str]) -> Dict[str, str]:
    return dict(e.split("=", 1) if "=" in e else (e, "") for e in entries)


def _compose() -> Dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_compose_backend_reads_the_vault_key_from_a_secret_file() -> None:
    data = _compose()
    backend = data["services"]["backend"]
    env = _env_map(backend["environment"])

    assert env["CAREFOLD_MODE"] == "server"
    assert env["CAREFOLD_VAULT_KEK_FILE"] == SECRET_FILE
    assert "carefold_vault_kek" in backend["secrets"]
    assert data["secrets"]["carefold_vault_kek"] == {"environment": "CAREFOLD_VAULT_KEK"}
    # The key itself never sits in the container environment.
    assert not any("CAREFOLD_VAULT_KEK}" in v or k == "CAREFOLD_VAULT_KEK" for k, v in env.items())


def test_compose_never_turns_checkpoint_encryption_off() -> None:
    for name, service in _compose()["services"].items():
        env = _env_map(service.get("environment") or [])
        for key in ("CAREFOLD_CHECKPOINT_ENCRYPTION", "YARVELLE_CORE_CHECKPOINT_ENCRYPTION"):
            assert key not in env, f"{name} sets {key}; encryption must stay on by default"


def test_compose_env_example_documents_key_generation() -> None:
    text = COMPOSE_ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "\nCAREFOLD_VAULT_KEK=\n" in text  # empty placeholder, never a real key
    assert "openssl rand -hex 32" in text
    assert "deploy/docker/.env" in COMPOSE.read_text(encoding="utf-8")


def test_compose_env_file_is_never_committed_or_baked_into_images() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gitignore
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "**/.env" in dockerignore


def test_helm_values_require_an_existing_secret_and_keep_encryption_on() -> None:
    values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    assert values["checkpoints"]["encryption"] is True
    assert values["vault"] == {"existingSecret": "", "secretKey": "kek"}


helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm binary not installed")


def _helm_template(*sets: str) -> subprocess.CompletedProcess:
    cmd = ["helm", "template", "carefold", str(CHART)]
    for s in sets:
        cmd += ["--set", s]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)


def _deployment(rendered: str) -> Dict[str, Any]:
    docs = [d for d in yaml.safe_load_all(rendered) if d]
    return next(d for d in docs if d["kind"] == "Deployment")


@helm
def test_helm_refuses_to_render_without_a_vault_secret() -> None:
    result = _helm_template()
    assert result.returncode != 0
    assert "vault.existingSecret is required" in result.stderr
    assert "openssl rand -hex 32" in result.stderr


@helm
def test_helm_mounts_the_vault_secret_as_a_read_only_file() -> None:
    result = _helm_template("vault.existingSecret=my-kek")
    assert result.returncode == 0, result.stderr
    pod = _deployment(result.stdout)["spec"]["template"]["spec"]
    container = pod["containers"][0]
    env = {e["name"]: e.get("value") for e in container["env"]}

    assert env["CAREFOLD_CHECKPOINT_ENCRYPTION"] == "true"
    assert env["CAREFOLD_MODE"] == "server"
    assert env["CAREFOLD_VAULT_KEK_FILE"] == "/var/run/secrets/carefold-vault/kek"
    assert not any(e.get("valueFrom") for e in container["env"])  # key is never an env var
    mount = next(m for m in container["volumeMounts"] if m["name"] == "vault-kek")
    assert mount == {"name": "vault-kek", "mountPath": "/var/run/secrets/carefold-vault", "readOnly": True}
    volume = next(v for v in pod["volumes"] if v["name"] == "vault-kek")
    assert volume["secret"]["secretName"] == "my-kek"
    assert volume["secret"]["defaultMode"] == 0o440
    assert volume["secret"]["items"] == [{"key": "kek", "path": "kek"}]


@helm
def test_helm_encryption_opt_out_is_explicit() -> None:
    result = _helm_template("checkpoints.encryption=false")
    assert result.returncode == 0, result.stderr
    container = _deployment(result.stdout)["spec"]["template"]["spec"]["containers"][0]
    env = {e["name"]: e.get("value") for e in container["env"]}
    assert env["CAREFOLD_CHECKPOINT_ENCRYPTION"] == "false"
    assert "CAREFOLD_VAULT_KEK_FILE" not in env
    assert all(m["name"] != "vault-kek" for m in container["volumeMounts"])


@helm
def test_helm_chart_lints_with_a_vault_secret() -> None:
    result = subprocess.run(
        ["helm", "lint", str(CHART), "--set", "vault.existingSecret=my-kek"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# --- startup check ---------------------------------------------------------


def _no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from yarvelle_core.vault import checkpoints as cp

    def _missing(version=None):
        raise cp.CheckpointKeyError("no vault key at /secret/path")

    monkeypatch.setattr(cp, "load_checkpoint_keyring", _missing)


def test_server_mode_without_a_key_stops_startup_with_a_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from yarvelle_core.config import settings

    from carefold.checkpoint_env import CheckpointKeyStartupError, check_checkpoint_key_at_startup

    monkeypatch.setattr(settings, "checkpoint_encryption", True)
    _no_key(monkeypatch)
    with pytest.raises(CheckpointKeyStartupError) as err:
        check_checkpoint_key_at_startup({"CAREFOLD_MODE": "server"})
    message = str(err.value)
    assert "CAREFOLD_VAULT_KEK_FILE" in message and "openssl rand -hex 32" in message
    assert "CAREFOLD_CHECKPOINT_ENCRYPTION=false" in message
    assert "/secret/path" not in message  # fixed text, no paths or key material


def test_local_mode_without_a_key_logs_and_keeps_starting(monkeypatch: pytest.MonkeyPatch) -> None:
    from yarvelle_core.config import settings

    from carefold.checkpoint_env import CHECKPOINT_KEY_MISSING_MESSAGE, check_checkpoint_key_at_startup

    monkeypatch.setattr(settings, "checkpoint_encryption", True)
    _no_key(monkeypatch)
    assert check_checkpoint_key_at_startup({}) == CHECKPOINT_KEY_MISSING_MESSAGE


@pytest.mark.parametrize("encryption", [False, True])
def test_startup_check_passes_when_off_or_keyed(monkeypatch: pytest.MonkeyPatch, encryption: bool) -> None:
    from yarvelle_core.config import settings

    from carefold.checkpoint_env import check_checkpoint_key_at_startup

    monkeypatch.setattr(settings, "checkpoint_encryption", encryption)
    if not encryption:
        _no_key(monkeypatch)  # no key needed when encryption is off
    assert check_checkpoint_key_at_startup({"CAREFOLD_MODE": "server"}) is None


def test_server_mode_startup_reads_the_mounted_key_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real loader in server mode: key file works, a missing file stops startup."""
    from yarvelle_core.config import settings
    from yarvelle_core.vault import checkpoints as cp
    from yarvelle_core.vault import kek as core_kek

    from carefold.checkpoint_env import CheckpointKeyStartupError, check_checkpoint_key_at_startup
    from tests.fixtures.checkpoint_crypto import use_real_checkpoint_key_loader

    use_real_checkpoint_key_loader(monkeypatch)
    monkeypatch.setattr(core_kek, "HAS_KEYRING", False)  # never the OS keychain
    monkeypatch.setattr(settings, "checkpoint_encryption", True)
    monkeypatch.setenv("CAREFOLD_MODE", "server")
    for name in ("VAULT_PASSPHRASE", "VAULT_KEK_FILE"):
        monkeypatch.delenv(f"CAREFOLD_{name}", raising=False)
        monkeypatch.delenv(f"YARVELLE_{name}", raising=False)
    try:
        cp.reset_checkpoint_keyring_cache()
        with pytest.raises(CheckpointKeyStartupError):
            check_checkpoint_key_at_startup(dict(os.environ))

        key_file = tmp_path / "kek"
        key_file.write_text(os.urandom(32).hex() + "\n", encoding="utf-8")
        monkeypatch.setenv("CAREFOLD_VAULT_KEK_FILE", str(key_file))
        cp.reset_checkpoint_keyring_cache()
        assert check_checkpoint_key_at_startup(dict(os.environ)) is None
    finally:
        cp.reset_checkpoint_keyring_cache()
