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

"""Pytest configuration and shared fixtures."""

import asyncio
import os
from pathlib import Path
import shutil
import tempfile

# Tests must never read the developer's real OS keychain (the vault KEK lives
# there). Force the keyring library's null backend for this process and any
# subprocess it starts. Checkpoint tests get throwaway keys instead.
os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
import keyring as _keyring  # noqa: E402
import keyring.backends.null as _null_keyring  # noqa: E402

_keyring.set_keyring(_null_keyring.Keyring())

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
def isolate_checkpoint_keys(monkeypatch: pytest.MonkeyPatch):
    """Checkpoints are encrypted by default; each test gets a throwaway key."""
    from tests.fixtures.checkpoint_crypto import install_test_checkpoint_keyring

    install_test_checkpoint_keyring(monkeypatch)
    yield


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

    from carefold.data_dir import clear_cli_data_dir_override

    clear_cli_data_dir_override()
    monkeypatch.delenv("CAREFOLD_DATA_DIR", raising=False)
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


@pytest.fixture(autouse=True, scope="session")
def speed_up_crypto_for_tests():
    """Patches Argon2 parameters during test execution for 60x speedup."""
    try:
        import argon2.low_level
        orig_raw = argon2.low_level.hash_secret_raw
        orig_sec = argon2.low_level.hash_secret

        def fast_raw(secret, salt, time_cost, memory_cost, parallelism, hash_len, type, **kwargs):
            return orig_raw(secret=secret, salt=salt, time_cost=1, memory_cost=1024, parallelism=1, hash_len=hash_len, type=type, **kwargs)

        def fast_sec(secret, salt, time_cost, memory_cost, parallelism, hash_len, type, **kwargs):
            return orig_sec(secret=secret, salt=salt, time_cost=1, memory_cost=1024, parallelism=1, hash_len=hash_len, type=type, **kwargs)

        argon2.low_level.hash_secret_raw = fast_raw
        argon2.low_level.hash_secret = fast_sec
        yield
        argon2.low_level.hash_secret_raw = orig_raw
        argon2.low_level.hash_secret = orig_sec
    except Exception:
        yield


# ============================================================================
# Shared Async SQLAlchemy & HTTP Factories (#343)
# ============================================================================


@pytest.fixture
async def async_db_session_factory():
    """Provides an isolated in-memory SQLite `async_sessionmaker` with schema DDL and clean teardown."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from yarvelle_core.db.base import Base
    import carefold.models  # noqa: F401 — ensure pack ORM tables are registered

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
def user_factory(async_db_session_factory):
    """Async factory creating persisted `User` ORM rows with sensible defaults (#343)."""
    import uuid
    from yarvelle_core.db.models import User

    async def _create_user(
        *,
        session=None,
        user_id: str | None = None,
        email: str | None = None,
        username: str | None = None,
        hashed_password: str = "hashed_password",
        role: str = "steward",
        **kwargs,
    ) -> User:
        uid = user_id or str(uuid.uuid4())
        short = uid.split("-")[0]
        user = User(
            id=uid,
            email=email or f"user-{short}@carefold.test",
            username=username or f"user_{short}",
            hashed_password=hashed_password,
            role=role,
            **kwargs,
        )
        if session is not None:
            session.add(user)
            await session.flush()
            return user
        async with async_db_session_factory() as s:
            s.add(user)
            await s.commit()
            return user

    return _create_user


@pytest.fixture
def profile_factory(async_db_session_factory, user_factory):
    """Async factory creating persisted `Profile` ORM rows, auto-creating an owner `User` when omitted (#343)."""
    import uuid
    from yarvelle_core.db.models import Profile

    async def _create_profile(
        *,
        session=None,
        profile_id: str | None = None,
        user_id: str | None = None,
        name: str = "Test Patient",
        relationship: str = "self",
        is_primary: bool = True,
        **kwargs,
    ) -> Profile:
        pid = profile_id or str(uuid.uuid4())
        owner_id = user_id
        if owner_id is None:
            owner = await user_factory(session=session)
            owner_id = owner.id

        profile = Profile(
            id=pid,
            user_id=owner_id,
            name=name,
            relationship=relationship,
            is_primary=is_primary,
            **kwargs,
        )
        if session is not None:
            session.add(profile)
            await session.flush()
            return profile
        async with async_db_session_factory() as s:
            s.add(profile)
            await s.commit()
            return profile

    return _create_profile


@pytest.fixture
def health_resource_factory(async_db_session_factory, profile_factory):
    """Async factory creating persisted `HealthResource` rows scoped to a profile (#343)."""
    from datetime import datetime, timezone
    import hashlib
    import json
    import uuid
    from carefold.models.health import HealthResource

    async def _create_health_resource(
        *,
        session=None,
        resource_id: str | None = None,
        profile_id: str | None = None,
        resource_type: str = "observation",
        source_type: str = "manual",
        status: str = "active",
        scope: str = "health.clinical",
        data: dict | None = None,
        effective_at: datetime | None = None,
        **kwargs,
    ) -> HealthResource:
        rid = resource_id or str(uuid.uuid4())
        pid = profile_id
        if pid is None:
            prof = await profile_factory(session=session)
            pid = prof.id

        now = effective_at or datetime.now(timezone.utc)
        fhir_payload = data or {
            "resourceType": "Observation",
            "id": rid,
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}]},
            "effectiveDateTime": now.isoformat(),
            "valueQuantity": {"value": 72, "unit": "/min"},
        }
        content_hash = kwargs.pop(
            "content_hash",
            hashlib.sha256(json.dumps(fhir_payload, sort_keys=True).encode("utf-8")).hexdigest(),
        )
        hr = HealthResource(
            id=rid,
            profile_id=pid,
            resource_type=resource_type,
            source_type=source_type,
            status=status,
            scope=scope,
            data=fhir_payload,
            content_hash=content_hash,
            effective_at=now,
            recorded_at=now,
            **kwargs,
        )
        if session is not None:
            session.add(hr)
            await session.flush()
            return hr
        async with async_db_session_factory() as s:
            s.add(hr)
            await s.commit()
            return hr

    return _create_health_resource


@pytest.fixture
def appointment_factory(async_db_session_factory, profile_factory):
    """Async factory creating persisted `Appointment` ORM rows (#343)."""
    from datetime import datetime, timedelta, timezone
    import uuid
    from carefold.models.health import Appointment

    async def _create_appointment(
        *,
        session=None,
        appointment_id: str | None = None,
        profile_id: str | None = None,
        title: str = "Primary Care Visit",
        provider_name: str = "Dr. Maya Lin",
        specialty: str = "Primary Care",
        status: str = "scheduled",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        **kwargs,
    ) -> Appointment:
        aid = appointment_id or str(uuid.uuid4())
        pid = profile_id
        if pid is None:
            prof = await profile_factory(session=session)
            pid = prof.id

        st = start_time or datetime.now(timezone.utc) + timedelta(days=7)
        et = end_time or (st + timedelta(minutes=30))
        appt = Appointment(
            id=aid,
            profile_id=pid,
            title=title,
            provider_name=provider_name,
            specialty=specialty,
            status=status,
            start_time=st,
            end_time=et,
            **kwargs,
        )
        if session is not None:
            session.add(appt)
            await session.flush()
            return appt
        async with async_db_session_factory() as s:
            s.add(appt)
            await s.commit()
            return appt

    return _create_appointment


@pytest.fixture
def auth_async_client(async_db_session_factory, user_factory):
    """Async context-manager factory yielding an authenticated `httpx.AsyncClient` bound to `async_db_session_factory` (#343)."""
    from contextlib import asynccontextmanager
    from datetime import datetime, timezone
    from httpx import ASGITransport, AsyncClient
    from yarvelle_core.api.deps import get_current_user, get_db
    from yarvelle_core.auth.ports import UserProfile

    @asynccontextmanager
    async def _make_client(*, user=None, fastapi_app=None, base_url: str = "http://testserver"):
        target_app = fastapi_app or app
        active_user = user or await user_factory()
        now = datetime.now(timezone.utc)
        user_profile = (
            active_user
            if isinstance(active_user, UserProfile)
            else UserProfile(
                id=active_user.id,
                email=active_user.email,
                username=active_user.username,
                role=getattr(active_user, "role", "steward") or "steward",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )

        async def _override_db():
            async with async_db_session_factory() as s:
                yield s

        prev_overrides = dict(target_app.dependency_overrides)
        target_app.dependency_overrides[get_db] = _override_db
        target_app.dependency_overrides[get_current_user] = lambda: user_profile
        try:
            async with AsyncClient(transport=ASGITransport(app=target_app), base_url=base_url) as ac:
                yield ac, user_profile
        finally:
            target_app.dependency_overrides.clear()
            target_app.dependency_overrides.update(prev_overrides)

    return _make_client


