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

"""Free local Ollama backend for the Carefold health evals.

Subject (main and every agent) and judge are separate local models, built
through core's model factory with temperature 0, a fixed seed, and reasoning
off. Only loopback URLs are accepted, so a run can never reach a hosted or
paid endpoint. Importing this module never opens a socket; availability is
probed on demand and missing models are reported, never pulled.

Mirrors the Ollama backend design on yarvelle-core main (not in the released
0.2.0).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import json
from typing import Any, Dict, List, Optional, Sequence
import urllib.error
from urllib.parse import urlsplit
import urllib.request

from yarvelle_core.testing.orch_eval.backends import FREE, CostTable, Role

from .judge import assert_distinct_models

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_SUBJECT_MODEL = "glm-4.7-flash"
DEFAULT_JUDGE_MODEL = "llama3.1:8b"
DEFAULT_SEED = 7
DEFAULT_TEMPERATURE = 0.0
_LOCAL_HOSTS = {"localhost"}


class OllamaUnavailableError(RuntimeError):
    """Raised when the Ollama daemon or a required model is not available."""


class NonLocalOllamaError(ValueError):
    """Raised for an Ollama URL that is not on this machine."""


def ensure_local_url(url: str) -> str:
    """Returns url without a trailing slash, or raises if it is not loopback."""
    parts = urlsplit((url or "").strip())
    host = (parts.hostname or "").lower()
    local = host in _LOCAL_HOSTS
    if not local and host:
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
    if parts.scheme not in ("http", "https") or not local:
        raise NonLocalOllamaError(f"health evals only talk to a local Ollama (loopback URL), not {url!r}")
    return url.strip().rstrip("/")


@dataclass(frozen=True)
class OllamaStatus:
    reachable: bool
    base_url: str
    models: List[str] = field(default_factory=list)
    digests: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None

    def has(self, name: str) -> bool:
        aliases = {name, name[: -len(":latest")] if name.endswith(":latest") else f"{name}:latest"}
        return any(m in aliases for m in self.models)


def probe_ollama(base_url: str = DEFAULT_OLLAMA_BASE_URL, timeout_s: float = 2.0) -> OllamaStatus:
    """Asks the local daemon for its tags. Never raises; reports in the status."""
    base_url = ensure_local_url(base_url)
    try:
        with urllib.request.urlopen(base_url + "/api/tags", timeout=timeout_s) as resp:  # noqa: S310 - loopback only
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as err:
        return OllamaStatus(reachable=False, base_url=base_url, error=f"{type(err).__name__}: {err}")
    models: List[str] = []
    digests: Dict[str, str] = {}
    for entry in payload.get("models") or []:
        name = str(entry.get("name") or "")
        if name:
            models.append(name)
            if entry.get("digest"):
                digests[name] = str(entry["digest"])
                digests.setdefault(name.removesuffix(":latest"), str(entry["digest"]))
    return OllamaStatus(reachable=True, base_url=base_url, models=models, digests=digests)


def require_ollama_models(
    required: Sequence[str], *, base_url: str = DEFAULT_OLLAMA_BASE_URL, status: Optional[OllamaStatus] = None
) -> OllamaStatus:
    """Returns a live status, or raises with a clear message (never pulls models)."""
    status = status or probe_ollama(base_url)
    if not status.reachable:
        raise OllamaUnavailableError(
            f"Ollama is not reachable at {status.base_url}: {status.error or 'unknown error'}. "
            "Start Ollama, or run with --backend fake."
        )
    missing = [m for m in required if not status.has(m)]
    if missing:
        raise OllamaUnavailableError(
            f"Ollama is up but missing model(s): {', '.join(missing)}. To add them yourself: "
            + "; ".join(f"ollama pull {m}" for m in missing)
        )
    return status


class OllamaBackend:
    """Eval backend: one local subject model for main and agents, one local judge."""

    name = "ollama"
    cost_per_mtok: CostTable = FREE

    def __init__(
        self,
        *,
        subject_model: str = DEFAULT_SUBJECT_MODEL,
        judge_model: str = DEFAULT_JUDGE_MODEL,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        seed: int = DEFAULT_SEED,
        temperature: float = DEFAULT_TEMPERATURE,
        status: Optional[OllamaStatus] = None,
    ) -> None:
        assert_distinct_models(subject_model, judge_model)
        self.subject_model = subject_model
        self.judge_model = judge_model
        self.base_url = ensure_local_url(base_url)
        self.seed = seed
        self.temperature = temperature
        self._status = require_ollama_models((subject_model, judge_model), base_url=self.base_url, status=status)
        self._models: Dict[str, Any] = {}

    def _build(self, key: str, name: str) -> Any:
        if key not in self._models:
            from yarvelle_core.model import factory

            self._models[key] = factory.create_chat_model(
                provider="ollama",
                model=name,
                base_url=self.base_url,
                temperature=self.temperature,
                streaming=True,
                seed=self.seed,
                reasoning=False,
            )
        return self._models[key]

    def model_for(self, role: Role) -> Any:
        if role.kind == "judge":
            return self.judge_model_instance()
        return self._build("subject", self.subject_model)

    def judge_model_instance(self) -> Any:
        return self._build("judge", self.judge_model)

    def describe(self) -> dict[str, Any]:
        return {
            "backend": "ollama",
            "base_url": self.base_url,
            "subject_model": self.subject_model,
            "judge_model": self.judge_model,
            "subject_digest": self._status.digests.get(self.subject_model),
            "judge_digest": self._status.digests.get(self.judge_model),
            "temperature": self.temperature,
            "seed": self.seed,
            "reasoning": False,
        }


__all__ = [
    "DEFAULT_JUDGE_MODEL",
    "DEFAULT_OLLAMA_BASE_URL",
    "DEFAULT_SEED",
    "DEFAULT_SUBJECT_MODEL",
    "NonLocalOllamaError",
    "OllamaBackend",
    "OllamaStatus",
    "OllamaUnavailableError",
    "ensure_local_url",
    "probe_ollama",
    "require_ollama_models",
]
