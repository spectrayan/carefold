# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Test suite verifying Docker Compose environment variable alignment with backend configuration.

Guards against Issue #69:
- Compose setting OLLAMA_URL instead of CAREFOLD_OLLAMA_URL
- Compose setting CAREFOLD_WORKSPACE instead of CAREFOLD_WORKSPACE_ROOT on backend
- Compose setting unused CAREFOLD_DATA instead of CAREFOLD_AUDIT_LOG_PATH on backend
- Web service missing CAREFOLD_WORKSPACE
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Dict, List
import pytest
import yaml

from carefold.config import Settings
from carefold.model.factory import resolve_base_url


def _get_compose_path() -> Path:
    """Find docker/docker-compose.yml relative to repo root or backend root."""
    cwd = Path.cwd().resolve()
    candidates = [
        cwd / "docker" / "docker-compose.yml",
        cwd.parent / "docker" / "docker-compose.yml",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError("docker/docker-compose.yml not found")


def _parse_compose_env_list(env_list: List[str]) -> Dict[str, str]:
    """Parse Docker Compose environment list items into key-value pairs (using default values)."""
    env_map: Dict[str, str] = {}
    for entry in env_list:
        if "=" in entry:
            k, v = entry.split("=", 1)
            # Match interpolation default: ${VAR:-default_val}
            m = re.match(r"^\$\{[^:]+:-([^}]*)\}$", v)
            if m:
                env_map[k] = m.group(1)
            elif v.startswith("${") and v.endswith("}"):
                env_map[k] = ""
            else:
                env_map[k] = v
        else:
            env_map[entry] = ""
    return env_map


def test_docker_compose_backend_env_contract():
    """Verify docker/docker-compose.yml backend environment variables match backend expected keys.

    Guards against:
    - OLLAMA_URL being set instead of canonical CAREFOLD_OLLAMA_URL
    - CAREFOLD_WORKSPACE being set on backend instead of CAREFOLD_WORKSPACE_ROOT
    - Unused CAREFOLD_DATA being set on backend instead of CAREFOLD_AUDIT_LOG_PATH
    - Web service missing CAREFOLD_WORKSPACE
    """
    compose_path = _get_compose_path()
    data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    assert "services" in data, "services key missing in docker-compose.yml"
    assert "backend" in data["services"], "backend service missing in docker-compose.yml"
    assert "web" in data["services"], "web service missing in docker-compose.yml"

    backend_service = data["services"]["backend"]
    assert "environment" in backend_service, "backend service missing environment definition"

    backend_env_list = backend_service["environment"]
    backend_env_map = _parse_compose_env_list(backend_env_list)
    raw_backend_keys = set(backend_env_map.keys())

    # 1. Canonical Ollama URL
    assert "CAREFOLD_OLLAMA_URL" in raw_backend_keys, (
        "docker-compose.yml backend service must define CAREFOLD_OLLAMA_URL to reach Ollama container"
    )
    assert "OLLAMA_URL" not in raw_backend_keys, (
        "Obsolete OLLAMA_URL in docker-compose.yml backend service must be replaced by CAREFOLD_OLLAMA_URL"
    )
    assert backend_env_map["CAREFOLD_OLLAMA_URL"] == "http://ollama:11434/v1"

    # 2. Workspace root
    assert "CAREFOLD_WORKSPACE_ROOT" in raw_backend_keys, (
        "docker-compose.yml backend service must define CAREFOLD_WORKSPACE_ROOT=/app"
    )
    assert "CAREFOLD_WORKSPACE" not in raw_backend_keys, (
        "docker-compose.yml backend service must not use CAREFOLD_WORKSPACE (web-only setting); use CAREFOLD_WORKSPACE_ROOT"
    )
    assert backend_env_map["CAREFOLD_WORKSPACE_ROOT"] == "/app"

    # 3. Audit log path
    assert "CAREFOLD_AUDIT_LOG_PATH" in raw_backend_keys, (
        "docker-compose.yml backend service must define CAREFOLD_AUDIT_LOG_PATH=/data/audit.jsonl to persist audit logs on carefold-data volume"
    )
    assert "CAREFOLD_DATA" not in raw_backend_keys, (
        "docker-compose.yml backend service must not use unused CAREFOLD_DATA; use CAREFOLD_AUDIT_LOG_PATH"
    )
    assert backend_env_map["CAREFOLD_AUDIT_LOG_PATH"] == "/data/audit.jsonl"

    # 4. Web service workspace
    web_service = data["services"]["web"]
    assert "environment" in web_service, "web service missing environment definition"
    web_env_list = web_service["environment"]
    web_env_map = _parse_compose_env_list(web_env_list)
    assert "CAREFOLD_WORKSPACE" in web_env_map, (
        "docker-compose.yml web service must define CAREFOLD_WORKSPACE=/app"
    )
    assert web_env_map["CAREFOLD_WORKSPACE"] == "/app"


def test_docker_compose_backend_settings_resolution(monkeypatch):
    """Verify backend Settings correctly resolves configuration when given Compose environment."""
    compose_path = _get_compose_path()
    data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    env_list = data["services"]["backend"]["environment"]
    env_map = _parse_compose_env_list(env_list)

    # Clean existing environment variables that could interfere
    for var in [
        "CAREFOLD_WORKSPACE",
        "CAREFOLD_WORKSPACE_ROOT",
        "CAREFOLD_DATA",
        "CAREFOLD_AUDIT_LOG_PATH",
        "OLLAMA_URL",
        "OLLAMA_BASE_URL",
        "CAREFOLD_OLLAMA_URL",
    ]:
        monkeypatch.delenv(var, raising=False)

    for k, v in env_map.items():
        monkeypatch.setenv(k, v)

    settings = Settings()

    # Settings must resolve Ollama URL to http://ollama:11434/v1
    assert settings.ollama_url == "http://ollama:11434/v1"
    assert resolve_base_url("ollama") == "http://ollama:11434/v1"

    # Settings must resolve audit log path to /data/audit.jsonl
    assert settings.get_audit_log_path() == Path("/data/audit.jsonl")


def test_ollama_url_resolution_with_carefold_ollama_url(monkeypatch):
    """Verify CAREFOLD_OLLAMA_URL environment variable properly sets settings.ollama_url and resolve_base_url."""
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("CAREFOLD_OLLAMA_URL", "http://ollama:11434/v1")

    settings = Settings()
    assert settings.ollama_url == "http://ollama:11434/v1"
    assert resolve_base_url("ollama") == "http://ollama:11434/v1"
