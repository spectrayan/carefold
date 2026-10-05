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

"""Pytest configuration and shared fixtures."""

import os
from pathlib import Path
import shutil
import tempfile
import pytest
from fastapi.testclient import TestClient

from carefold.config import settings
from carefold.main import app
from tests.fixtures.fake_model import (
    FakeChatModel,
    FakeListChatModel,
    MockChatModel,
    MockModelClient,
)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Returns repository root directory."""
    return Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def temp_workspace(tmp_path: Path, repo_root: Path):
    """Sets up an isolated test workspace with agents, skills, attachments, and logs."""
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True)

    # Copy bundled agents and skills from repo root if they exist
    repo_agents = repo_root / "agents"
    repo_skills = repo_root / "skills"

    if repo_agents.is_dir():
        shutil.copytree(repo_agents, ws / "agents")
    else:
        (ws / "agents").mkdir()

    if repo_skills.is_dir():
        shutil.copytree(repo_skills, ws / "skills")
    else:
        (ws / "skills").mkdir()

    (ws / "attachments").mkdir()
    (ws / "logs").mkdir()
    (ws / "workspace" / "notes").mkdir(parents=True)

    # Override settings for tests
    old_root = settings.workspace_root
    old_log = settings.audit_log_path
    old_store = settings.audit_store_bodies

    settings.workspace_root = ws
    settings.audit_log_path = ws / "logs" / "audit.jsonl"
    settings.audit_store_bodies = False

    yield ws

    settings.workspace_root = old_root
    settings.audit_log_path = old_log
    settings.audit_store_bodies = old_store


@pytest.fixture
def client(temp_workspace: Path) -> TestClient:
    """Returns a FastAPI TestClient configured with test workspace."""
    return TestClient(app)


@pytest.fixture
def mock_client() -> MockModelClient:
    """Returns a deterministic MockModelClient."""
    return MockModelClient()


@pytest.fixture
def fake_llm() -> FakeListChatModel:
    """Returns a deterministic LangChain FakeListChatModel."""
    return FakeListChatModel(responses=["Hello, I am a helpful clinical assistant."])


@pytest.fixture
def fake_chat_model() -> FakeChatModel:
    """Returns a configurable FakeChatModel."""
    return FakeChatModel()


def pytest_runtest_setup(item):
    """Enforce that tests marked with 'ollama' are strictly skipped unless CAREFOLD_RUN_OLLAMA_TESTS is set."""
    if item.get_closest_marker("ollama"):
        if not os.getenv("CAREFOLD_RUN_OLLAMA_TESTS"):
            pytest.skip("Live Ollama tests run on-demand only (set CAREFOLD_RUN_OLLAMA_TESTS=1)")


@pytest.fixture(autouse=True)
def default_test_model_client(request: pytest.FixtureRequest, monkeypatch):
    """Provides a deterministic MockChatModel default when tests execute agent runs without a live LLM."""
    if request.node.get_closest_marker("ollama") and os.getenv("CAREFOLD_RUN_OLLAMA_TESTS"):
        return

    import carefold.engine.runner as runner_mod
    monkeypatch.setattr(runner_mod, "create_chat_model", lambda *args, **kwargs: MockChatModel())


@pytest.fixture
def live_ollama_client():
    """Provides an authenticated live ChatOllama client when CAREFOLD_RUN_OLLAMA_TESTS=1."""
    if not os.getenv("CAREFOLD_RUN_OLLAMA_TESTS"):
        pytest.skip("Live Ollama tests run on-demand only (set CAREFOLD_RUN_OLLAMA_TESTS=1)")
    from carefold.model.factory import create_chat_model
    ollama_url = os.getenv("CAREFOLD_OLLAMA_URL", "http://localhost:11434")
    ollama_model = os.getenv("CAREFOLD_OLLAMA_MODEL", "llama3.2:3b")
    return create_chat_model(
        provider="ollama",
        model=ollama_model,
        base_url=ollama_url,
        temperature=0.0,
    )



