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

"""The local Ollama eval backend is localhost-only, free, and offline to import."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.orchestration import ollama_backend as OB  # noqa: E402

READY = OB.OllamaStatus(
    reachable=True,
    base_url=OB.DEFAULT_OLLAMA_BASE_URL,
    models=["glm-4.7-flash:latest", "llama3.1:8b"],
    digests={"llama3.1:8b": "sha256:abc"},
)


def test_defaults_are_the_approved_free_local_models() -> None:
    assert OB.DEFAULT_SUBJECT_MODEL == "glm-4.7-flash"
    assert OB.DEFAULT_JUDGE_MODEL == "llama3.1:8b"
    assert OB.DEFAULT_OLLAMA_BASE_URL == "http://127.0.0.1:11434"
    assert OB.OllamaBackend.cost_per_mtok.input_per_mtok == 0 and OB.OllamaBackend.cost_per_mtok.output_per_mtok == 0


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "http://localhost:11434/", "http://[::1]:11434"])
def test_local_urls_are_accepted(url: str) -> None:
    assert OB.ensure_local_url(url) == url.rstrip("/")


@pytest.mark.parametrize(
    "url", ["https://api.example.com", "http://10.0.0.5:11434", "http://ollama.internal:11434", "file:///x", ""]
)
def test_non_local_urls_are_refused(url: str) -> None:
    with pytest.raises(OB.NonLocalOllamaError):
        OB.ensure_local_url(url)


def test_status_matches_latest_aliases() -> None:
    assert READY.has("glm-4.7-flash")
    assert READY.has("glm-4.7-flash:latest") and not READY.has("qwen3:8b")


def test_missing_models_raise_with_pull_hint_and_no_install() -> None:
    status = OB.OllamaStatus(reachable=True, base_url=OB.DEFAULT_OLLAMA_BASE_URL, models=["llama3.1:8b"])
    with pytest.raises(OB.OllamaUnavailableError, match="ollama pull glm-4.7-flash"):
        OB.require_ollama_models(["glm-4.7-flash", "llama3.1:8b"], status=status)
    down = OB.OllamaStatus(reachable=False, base_url=OB.DEFAULT_OLLAMA_BASE_URL, error="refused")
    with pytest.raises(OB.OllamaUnavailableError, match="not reachable"):
        OB.require_ollama_models(["llama3.1:8b"], status=down)


def test_judge_and_subject_must_differ() -> None:
    from evals.orchestration.judge import SameModelJudgeError

    with pytest.raises(SameModelJudgeError):
        OB.OllamaBackend(subject_model="llama3.1:8b", judge_model="llama3.1:8b", status=READY)


def test_models_are_built_locally_with_fixed_seed_and_no_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    import yarvelle_core.model.factory as factory

    monkeypatch.setattr(factory, "create_chat_model", lambda **kw: calls.append(kw) or object())
    from yarvelle_core.testing.orch_eval.backends import Role

    backend = OB.OllamaBackend(status=READY)
    main = backend.model_for(Role("main"))
    assert backend.model_for(Role("agent", "benefits-coordinator")) is main
    backend.judge_model_instance()
    assert [c["model"] for c in calls] == ["glm-4.7-flash", "llama3.1:8b"]
    for c in calls:
        assert c["provider"] == "ollama" and c["base_url"] == "http://127.0.0.1:11434"
        assert c["temperature"] == 0 and c["seed"] == OB.DEFAULT_SEED and c["reasoning"] is False
        assert "api_key" not in c


def test_describe_reports_models_and_digests_without_secrets() -> None:
    info = OB.OllamaBackend(status=READY).describe()
    assert info["subject_model"] == "glm-4.7-flash" and info["judge_model"] == "llama3.1:8b"
    assert info["judge_digest"] == "sha256:abc"
    assert not any("key" in k or "token" in k for k in info)


def test_importing_the_backend_opens_no_socket() -> None:
    import subprocess

    code = (
        "import socket, sys\n"
        "def boom(*a, **k): raise SystemExit('socket opened on import')\n"
        "socket.socket.connect = boom\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "import evals.orchestration.ollama_backend\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=120)
