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

import asyncio
import os
from pathlib import Path
import shutil
import tempfile
import pytest
from fastapi.testclient import TestClient

from carefold.constants.paths import (
    ENV_AUDIT_LOG_PATH,
    ENV_CATALOG_DB_PATH,
    ENV_DATABASE_URL,
    ENV_DATABASE_URL_FALLBACK,
    ENV_DB_PATH,
    ENV_WORKSPACE_ROOT,
)
from carefold.config import settings
from carefold.main import app
from tests.fixtures.fake_model import (
    FakeChatModel,
    FakeListChatModel,
    MockChatModel,
    MockModelClient,
)


@pytest.fixture(autouse=True)
def isolate_test_carefold_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Guarantees every pytest execution runs strictly inside tmp_path / '.carefold'.

    Prevents tests from touching ~/.carefold and disposes DB connections on teardown.
    """
    test_home = tmp_path / ".carefold"
    test_home.mkdir(parents=True, exist_ok=True)
    (test_home / "uploads").mkdir(parents=True, exist_ok=True)
    (test_home / "logs").mkdir(parents=True, exist_ok=True)
    (test_home / "notes").mkdir(parents=True, exist_ok=True)

    test_db_url = f"sqlite+aiosqlite:///{test_home}/carefold.db"

    monkeypatch.setenv("CAREFOLD_HOME", str(test_home))
    monkeypatch.delenv(ENV_DATABASE_URL, raising=False)
    monkeypatch.delenv(ENV_DB_PATH, raising=False)
    monkeypatch.delenv(ENV_CATALOG_DB_PATH, raising=False)
    monkeypatch.delenv(ENV_AUDIT_LOG_PATH, raising=False)
    monkeypatch.delenv(ENV_DATABASE_URL_FALLBACK, raising=False)

    old_home = getattr(settings, "home_dir", None)
    old_db_url = settings.database_url
    old_audit = settings.audit_log_path
    old_cat = settings.catalog_db_path
    old_db_path = settings.db_path
    old_auth = settings.auth_provider

    if hasattr(settings, "home_dir"):
        settings.home_dir = test_home
    settings.database_url = test_db_url
    settings.audit_log_path = None
    settings.catalog_db_path = None
    settings.db_path = None
    settings.auth_provider = "disabled"

    try:
        yield test_home
    finally:
        from carefold.db.session import close_db, reset_engine
        from carefold.memory.factory import reset_memory_ports
        from carefold.auth.factory import reset_auth_port
        from carefold.settings.factory import reset_settings_port
        from carefold.engine.graph import reset_db_init_cache
        from carefold.storage.factory import reset_storage_adapter

        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                asyncio.create_task(close_db())
            else:
                asyncio.run(close_db())
        except Exception:
            reset_engine()

        for reset_fn in (reset_memory_ports, reset_auth_port, reset_settings_port, reset_db_init_cache, reset_storage_adapter):
            try:
                reset_fn()
            except Exception:
                pass

        if hasattr(settings, "home_dir") and old_home is not None:
            settings.home_dir = old_home
        settings.database_url = old_db_url
        settings.audit_log_path = old_audit
        settings.catalog_db_path = old_cat
        settings.db_path = old_db_path
        settings.auth_provider = old_auth


isolate_test_home_and_settings = isolate_test_carefold_home


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
    old_auth = settings.auth_provider

    settings.workspace_root = ws
    settings.audit_log_path = ws / "logs" / "audit.jsonl"
    settings.audit_store_bodies = False
    settings.auth_provider = "disabled"

    try:
        from carefold.db.session import init_db
        asyncio.run(init_db())
    except Exception:
        pass

    yield ws

    settings.workspace_root = old_root
    settings.audit_log_path = old_log
    settings.audit_store_bodies = old_store
    settings.auth_provider = old_auth


@pytest.fixture
def client(temp_workspace: Path) -> TestClient:
    """Returns a FastAPI TestClient configured with test workspace."""
    with TestClient(app) as test_client:
        yield test_client


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


def pytest_sessionfinish(session, exitstatus):
    """Safety guardrail: cleanly shuts down any lingering non-daemon worker threads."""
    import threading
    try:
        from aiosqlite.core import _STOP_RUNNING_SENTINEL
        for t in threading.enumerate():
            if t.is_alive() and "_connection_worker_thread" in str(getattr(t, "_target", "")):
                try:
                    tx = t._args[0]
                    tx.put_nowait((None, lambda: _STOP_RUNNING_SENTINEL))
                    t.join(timeout=1.0)
                except Exception:
                    pass
    except Exception:
        pass
