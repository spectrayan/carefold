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

"""Comprehensive unit and integration tests for Hexagonal SettingsPort and SQL adapter."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.settings.adapters.sql_adapter import SqlSettingsAdapter
from carefold.settings.factory import (
    create_settings_port,
    get_settings_port,
    reset_settings_port,
    set_settings_port,
)
from carefold.settings.ports import SECRET_MASK, SettingsPort


@pytest.fixture
async def sql_session_factory():
    """Sets up an isolated in-memory SQLite database and returns session factory."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest.fixture
def sql_settings_adapter(sql_session_factory: async_sessionmaker[AsyncSession]):
    """Instantiates SqlSettingsAdapter backed by the isolated test database."""
    return SqlSettingsAdapter(session_factory=sql_session_factory)


# ============================================================================
# SqlSettingsAdapter Tests
# ============================================================================


@pytest.mark.asyncio
async def test_sql_settings_crud_operations(sql_settings_adapter: SqlSettingsAdapter):
    """Verifies basic CRUD operations and JSON type serialization."""
    # 1. Unset key returns default
    assert await sql_settings_adapter.get_setting("nonexistent.key") is None
    assert await sql_settings_adapter.get_setting("nonexistent.key", "default_val") == "default_val"

    # 2. String setting
    await sql_settings_adapter.set_setting("app.name", "Carefold Platform")
    assert await sql_settings_adapter.get_setting("app.name") == "Carefold Platform"

    # 3. Numeric & Boolean settings
    await sql_settings_adapter.set_setting("auth.min_password_length", 12)
    await sql_settings_adapter.set_setting("auth.registration_enabled", True)
    assert await sql_settings_adapter.get_setting("auth.min_password_length") == 12
    assert await sql_settings_adapter.get_setting("auth.registration_enabled") is True

    # 4. Complex dict & list settings
    routing = {"cardiology": "claude-3-7-sonnet", "derma": "gpt-4o"}
    tags = ["clinical", "navigation", "admin"]
    await sql_settings_adapter.set_setting("models.routing_table", routing)
    await sql_settings_adapter.set_setting("system.tags", tags)

    assert await sql_settings_adapter.get_setting("models.routing_table") == routing
    assert await sql_settings_adapter.get_setting("system.tags") == tags

    # 5. Overwrite setting
    await sql_settings_adapter.set_setting("app.name", "Carefold Enterprise")
    assert await sql_settings_adapter.get_setting("app.name") == "Carefold Enterprise"

    # 6. Delete setting
    deleted = await sql_settings_adapter.delete_setting("app.name")
    assert deleted is True
    assert await sql_settings_adapter.get_setting("app.name") is None

    # 7. Delete non-existent setting returns False
    assert await sql_settings_adapter.delete_setting("app.name") is False


@pytest.mark.asyncio
async def test_sql_settings_in_memory_caching(sql_settings_adapter: SqlSettingsAdapter):
    """Verifies that in-memory cache serves fast hot-path lookups and invalidation works."""
    await sql_settings_adapter.set_setting("cache.test", "cached_value")

    # Value is in cache
    assert "cache.test" in sql_settings_adapter._cache
    assert sql_settings_adapter._cache["cache.test"] == "cached_value"

    # Modify directly in cache and verify get_setting reads from cache
    sql_settings_adapter._cache["cache.test"] = "hacked_cache_value"
    assert await sql_settings_adapter.get_setting("cache.test") == "hacked_cache_value"

    # Invalidate cache forces re-query from SQL persistence
    sql_settings_adapter.invalidate_cache("cache.test")
    assert "cache.test" not in sql_settings_adapter._cache

    re_read = await sql_settings_adapter.get_setting("cache.test")
    assert re_read == "cached_value"
    assert "cache.test" in sql_settings_adapter._cache

    # Deleting setting evicts from cache
    await sql_settings_adapter.delete_setting("cache.test")
    assert "cache.test" not in sql_settings_adapter._cache


@pytest.mark.asyncio
async def test_sql_settings_secret_masking(sql_settings_adapter: SqlSettingsAdapter):
    """Verifies secret masking with '••••••••' when mask_secrets=True."""
    await sql_settings_adapter.set_setting(
        "models.api_keys",
        {"anthropic": "sk-ant-secret-12345", "openai": "sk-openai-secret-67890"},
        is_secret=True,
    )
    await sql_settings_adapter.set_setting(
        "models.default_provider",
        "ollama",
        is_secret=False,
    )

    # 1. Masked export
    all_masked = await sql_settings_adapter.get_all_settings(mask_secrets=True)
    assert all_masked["models.default_provider"] == "ollama"
    assert all_masked["models.api_keys"] == SECRET_MASK
    assert all_masked["models.api_keys"] == "••••••••"

    # 2. Unmasked export via mask_secrets=False
    all_unmasked = await sql_settings_adapter.get_all_settings(mask_secrets=False)
    assert all_unmasked["models.default_provider"] == "ollama"
    assert isinstance(all_unmasked["models.api_keys"], dict)
    assert all_unmasked["models.api_keys"]["anthropic"] == "sk-ant-secret-12345"

    # 3. Unmasked export via include_secrets=True
    all_include = await sql_settings_adapter.get_all_settings(include_secrets=True)
    assert all_include["models.api_keys"]["anthropic"] == "sk-ant-secret-12345"

    # 4. Direct get_setting for internal services returns raw secret
    direct_secret = await sql_settings_adapter.get_setting("models.api_keys")
    assert direct_secret["anthropic"] == "sk-ant-secret-12345"


@pytest.mark.asyncio
async def test_sql_settings_secret_mask_placeholder_preserves_secret(
    sql_settings_adapter: SqlSettingsAdapter,
):
    """Verifies that set_setting with SECRET_MASK does not overwrite stored secret."""
    # Seed a secret setting
    await sql_settings_adapter.set_setting(
        "api.secret_token", "super-secret-token-val", is_secret=True
    )
    assert await sql_settings_adapter.get_setting("api.secret_token") == "super-secret-token-val"

    # Attempt to write SECRET_MASK (simulating client resubmission)
    await sql_settings_adapter.set_setting("api.secret_token", SECRET_MASK)
    # Stored secret must be preserved
    assert await sql_settings_adapter.get_setting("api.secret_token") == "super-secret-token-val"

    # Clear cache and verify database row was untouched
    sql_settings_adapter.invalidate_cache("api.secret_token")
    assert await sql_settings_adapter.get_setting("api.secret_token") == "super-secret-token-val"

    # Updating with new genuine secret without passing is_secret preserves is_secret=True
    await sql_settings_adapter.set_setting("api.secret_token", "new-secret-token-val")
    assert await sql_settings_adapter.get_setting("api.secret_token") == "new-secret-token-val"
    all_masked = await sql_settings_adapter.get_all_settings(mask_secrets=True)
    assert all_masked["api.secret_token"] == SECRET_MASK


@pytest.mark.asyncio
async def test_sql_settings_empty_key_validation(sql_settings_adapter: SqlSettingsAdapter):
    """Verifies empty and invalid key handling."""
    with pytest.raises(ValueError, match="cannot be empty"):
        await sql_settings_adapter.set_setting("", "value")

    assert await sql_settings_adapter.get_setting("", "fallback") == "fallback"
    assert await sql_settings_adapter.delete_setting("") is False


# ============================================================================
# Settings Factory Tests
# ============================================================================


def test_settings_factory_resolution():
    """Verifies create_settings_port instantiates SqlSettingsAdapter."""
    port_default = create_settings_port()
    assert isinstance(port_default, SqlSettingsAdapter)

    port_sql = create_settings_port("sql")
    assert isinstance(port_sql, SqlSettingsAdapter)

    with pytest.raises(ValueError, match="Unsupported settings backend"):
        create_settings_port("unknown_backend")


def test_settings_factory_singleton_and_lifecycle():
    """Verifies singleton caching, set_settings_port, and reset_settings_port."""
    reset_settings_port()
    p1 = get_settings_port()
    p2 = get_settings_port()
    assert p1 is p2
    assert isinstance(p1, SettingsPort)

    custom = SqlSettingsAdapter()
    set_settings_port(custom)
    assert get_settings_port() is custom

    reset_settings_port()
    p3 = get_settings_port()
    assert p3 is not custom
