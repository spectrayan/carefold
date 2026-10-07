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

"""Automated tests for unified start script and default non-conflicting ports."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from unittest.mock import patch

import pytest

from carefold.constants import defaults as def_const
from carefold.main import run as run_server


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_start_script_exists_and_executable():
    """Verify scripts/start.sh exists, is executable, and has valid bash syntax."""
    script_path = REPO_ROOT / "scripts" / "start.sh"
    assert script_path.exists(), "scripts/start.sh must exist"
    assert os.access(script_path, os.X_OK), "scripts/start.sh must be executable"

    content = script_path.read_text(encoding="utf-8")
    assert "Copyright 2026 Spectrayan" in content, "Must contain Spectrayan copyright header"
    assert "Apache License, Version 2.0" in content, "Must contain Apache-2.0 license declaration"

    # Syntax validation using bash -n
    result = subprocess.run(
        ["bash", "-n", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"bash -n failed: {result.stderr}"


def test_root_start_symlink():
    """Verify root start.sh is a valid symbolic link targeting scripts/start.sh."""
    symlink_path = REPO_ROOT / "start.sh"
    assert symlink_path.is_symlink(), "Root start.sh must be a symbolic link"
    target = os.readlink(symlink_path)
    assert target == "scripts/start.sh" or target.endswith("scripts/start.sh")
    assert symlink_path.resolve().exists(), "Symlink target must exist"


def test_start_script_help_output():
    """Verify scripts/start.sh help outputs expected commands, options, and ports."""
    script_path = REPO_ROOT / "scripts" / "start.sh"
    result = subprocess.run(
        [str(script_path), "help"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert result.returncode == 0
    clean_stdout = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert "Usage: ./scripts/start.sh" in clean_stdout
    assert "all" in clean_stdout
    assert "start" in clean_stdout
    assert "stop" in clean_stdout
    assert "status" in clean_stdout
    assert "backend" in clean_stdout
    assert "web" in clean_stdout
    assert "8010" in clean_stdout
    assert "3010" in clean_stdout


def test_start_script_status():
    """Verify scripts/start.sh status renders service status table."""
    script_path = REPO_ROOT / "scripts" / "start.sh"
    result = subprocess.run(
        [str(script_path), "status"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert result.returncode == 0
    clean_stdout = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert "Carefold Service Status" in clean_stdout
    assert "Backend API" in clean_stdout
    assert "Web UI" in clean_stdout
    assert "8010" in clean_stdout
    assert "3010" in clean_stdout


def test_backend_port_defaults_and_cors():
    """Verify backend default port is 8010 and CORS origins include 3010 and 8010."""
    assert def_const.DEFAULT_PORT == 8010
    expected_origins = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3010",
        "http://127.0.0.1:3010",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8010",
        "http://127.0.0.1:8010",
    )
    for origin in expected_origins:
        assert origin in def_const.DEFAULT_CORS_ORIGINS


def test_backend_run_respects_env_ports(monkeypatch):
    """Verify main.run() inspects CAREFOLD_BACKEND_PORT and PORT environment variables."""
    mock_calls = []

    def fake_run(app_path, host, port, reload):
        mock_calls.append({"app": app_path, "host": host, "port": port, "reload": reload})

    with patch("uvicorn.run", side_effect=fake_run):
        # Default with no env vars
        monkeypatch.delenv("CAREFOLD_BACKEND_PORT", raising=False)
        monkeypatch.delenv("PORT", raising=False)
        monkeypatch.delenv("CAREFOLD_BACKEND_HOST", raising=False)
        monkeypatch.delenv("HOST", raising=False)
        run_server()
        assert mock_calls[-1]["port"] == 8010
        assert mock_calls[-1]["host"] == def_const.DEFAULT_HOST

        # Override with CAREFOLD_BACKEND_PORT
        monkeypatch.setenv("CAREFOLD_BACKEND_PORT", "8055")
        run_server()
        assert mock_calls[-1]["port"] == 8055

        # Override with PORT fallback
        monkeypatch.delenv("CAREFOLD_BACKEND_PORT", raising=False)
        monkeypatch.setenv("PORT", "8066")
        run_server()
        assert mock_calls[-1]["port"] == 8066

        # Override host
        monkeypatch.setenv("CAREFOLD_BACKEND_HOST", "127.0.0.2")
        run_server()
        assert mock_calls[-1]["host"] == "127.0.0.2"


def test_package_json_scripts():
    """Verify root package.json and apps/web/package.json declare non-conflicting default ports."""
    root_pkg_path = REPO_ROOT / "package.json"
    root_pkg = json.loads(root_pkg_path.read_text(encoding="utf-8"))
    assert "start" in root_pkg["scripts"]
    assert "bash scripts/start.sh" in root_pkg["scripts"]["start"]
    assert "--port 8010" in root_pkg["scripts"]["dev:backend"]

    web_pkg_path = REPO_ROOT / "apps" / "web" / "package.json"
    web_pkg = json.loads(web_pkg_path.read_text(encoding="utf-8"))
    assert "--port 3010" in web_pkg["scripts"]["dev"]
    assert "--port 3010" in web_pkg["scripts"]["start"]
