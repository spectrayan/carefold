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

"""Container ports, Carefold's home and env names line up across the image, Compose and Helm.

The chart used to listen on 8080 while the image serves 8000 (probes failed),
set CAREFOLD_DATA (read by nothing), passed model settings under names the
backend does not read, and left carefold.db in the container's home instead of
the /data volume. Helm checks run only where the ``helm`` binary is installed.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Dict, List

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "deploy" / "docker" / "Dockerfile"
COMPOSE = REPO_ROOT / "deploy" / "docker" / "docker-compose.yml"
CHART = REPO_ROOT / "deploy" / "helm" / "carefold"
BACKEND_SRC = REPO_ROOT / "backend" / "src"


def _stage(name: str) -> str:
    text = DOCKERFILE.read_text(encoding="utf-8")
    start = re.search(rf"^FROM \S+ AS {re.escape(name)}$", text, re.M)
    assert start, name
    nxt = re.search(r"^FROM ", text[start.end():], re.M)
    return text[start.start(): start.end() + nxt.start()] if nxt else text[start.start():]


def _known_env_names() -> set[str]:
    """CAREFOLD_* names the backend reads: Settings fields plus names read from os.environ."""
    from carefold.config import Settings

    names = {f"CAREFOLD_{f.upper()}" for f in Settings.model_fields}
    for path in BACKEND_SRC.rglob("*.py"):
        names.update(re.findall(r"[\"'](CAREFOLD_[A-Z0-9_]+)[\"']", path.read_text(encoding="utf-8")))
    # Core settings read with the app's env prefix (yarvelle_core identity).
    from yarvelle_core.config import Settings as CoreSettings

    names.update(f"CAREFOLD_{f.upper()}" for f in CoreSettings.model_fields)
    names.update({"CAREFOLD_VAULT_KEK_FILE", "CAREFOLD_VAULT_PASSPHRASE", "CAREFOLD_MODE"})
    return names


@pytest.mark.parametrize("stage", ["backend", "all-in-one"])
def test_image_puts_carefold_home_on_the_data_volume(stage: str) -> None:
    block = _stage(stage)
    assert "CAREFOLD_HOME=/data" in block
    assert "CAREFOLD_DATA" not in block
    assert "EXPOSE 8000" in block
    assert "--port 8000" in block or "--port\", \"8000\"" in block


def test_compose_backend_home_is_the_data_volume() -> None:
    backend = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["backend"]
    env = dict(e.split("=", 1) for e in backend["environment"])
    assert env["CAREFOLD_HOME"] == "/data"
    assert any(v.endswith(":/data") for v in backend["volumes"])


def test_compose_backend_env_names_are_read_by_the_backend() -> None:
    backend = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["backend"]
    names = {e.split("=", 1)[0] for e in backend["environment"] if e.startswith("CAREFOLD_")}
    assert names - _known_env_names() == set()


helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm binary not installed")


def _render(*sets: str) -> List[Dict[str, Any]]:
    cmd = ["helm", "template", "carefold", str(CHART), "--set", "vault.existingSecret=my-kek"]
    for s in sets:
        cmd += ["--set", s]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def _kind(docs: List[Dict[str, Any]], kind: str) -> Dict[str, Any]:
    return next(d for d in docs if d["kind"] == kind)


def _container(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _kind(docs, "Deployment")["spec"]["template"]["spec"]["containers"][0]


@helm
def test_helm_listens_and_probes_on_the_port_the_image_serves() -> None:
    docs = _render()
    container = _container(docs)
    ports = {p["name"]: p["containerPort"] for p in container["ports"]}
    assert ports == {"http": 8000}
    for probe in ("readinessProbe", "livenessProbe"):
        assert container[probe]["httpGet"] == {"path": "/api/health", "port": "http"}
    service_ports = _kind(docs, "Service")["spec"]["ports"]
    assert [(p["name"], p["targetPort"]) for p in service_ports] == [("http", "http")]


@helm
def test_helm_can_expose_the_all_in_one_web_ui() -> None:
    docs = _render("container.webPort=3000")
    ports = {p["name"]: p["containerPort"] for p in _container(docs)["ports"]}
    assert ports == {"http": 8000, "web": 3000}
    service = {p["name"]: (p["port"], p["targetPort"]) for p in _kind(docs, "Service")["spec"]["ports"]}
    assert service == {"http": (8080, "http"), "web": (3000, "web")}


@helm
def test_helm_home_is_the_mounted_data_volume() -> None:
    container = _container(_render())
    env = {e["name"]: e.get("value") for e in container["env"]}
    mounts = {m["name"]: m["mountPath"] for m in container["volumeMounts"]}
    assert env["CAREFOLD_HOME"] == mounts["data"] == "/data"
    assert "CAREFOLD_DATA" not in env


@helm
def test_helm_model_settings_use_the_backend_names() -> None:
    container = _container(_render("model.baseUrl=http://ollama:11434/v1", "model.name=qwen3"))
    env = {e["name"]: e.get("value") for e in container["env"]}
    assert env["CAREFOLD_OLLAMA_URL"] == "http://ollama:11434/v1"
    assert env["CAREFOLD_DEFAULT_MODEL"] == "qwen3"
    assert {"CAREFOLD_MODEL_BASE_URL", "CAREFOLD_MODEL"}.isdisjoint(env)


@helm
def test_helm_env_names_are_read_by_the_backend() -> None:
    container = _container(_render("container.webPort=3000"))
    names = {e["name"] for e in container["env"] if e["name"].startswith("CAREFOLD_")}
    assert names - _known_env_names() == set()


def test_helm_env_reaches_backend_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The names the chart sets resolve to the intended backend settings."""
    from carefold.config import Settings

    monkeypatch.setenv("CAREFOLD_HOME", str(tmp_path))
    monkeypatch.setenv("CAREFOLD_OLLAMA_URL", "http://ollama:11434/v1")
    monkeypatch.setenv("CAREFOLD_DEFAULT_MODEL", "qwen3")
    for var in ("OLLAMA_URL", "OLLAMA_BASE_URL", "CAREFOLD_HOME_DIR", "CAREFOLD_DATABASE_URL", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.ollama_url == "http://ollama:11434/v1"
    assert s.default_model == "qwen3"
    assert s.get_home_dir() == tmp_path.resolve()
    assert s.get_database_url().endswith(f"{tmp_path.resolve()}/{s.db_filename}")
