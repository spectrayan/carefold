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

"""Empirical Adversarial Challenge Test Harness for Milestone 2 (SettingsPort & DisabledAuthAdapter).

Challenger: challenger_m2_2
Target: Hexagonal SettingsPort, SqlSettingsAdapter, and DisabledAuthAdapter

Probes:
1. Complex nested JSON serialization (deeply nested dicts, lists, booleans, nulls, unicode, special chars).
2. Cache consistency and selective vs global invalidation.
3. Secret masking: get_all_settings(mask_secrets=True) masks secrets with '••••••••'.
4. Cache isolation: verifying get_all_settings masking does not poison in-memory cache.
5. Cache eviction on delete_setting and distinguishing null values from deleted keys.
6. High-concurrency cache hit performance and race-condition safety.
7. DisabledAuthAdapter zero-DB bypass across all 11 methods and tuple unpackings.
8. DisabledAuthAdapter custom steward injection and DTO support.
9. SQL injection in setting keys and special character resilience.
10. Non-JSON serializable object rejection without database mutation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from carefold.auth.adapters.disabled_adapter import (
    DEFAULT_STEWARD_USER,
    DisabledAuthAdapter,
)
from carefold.auth.ports import (
    AuthPort,
    PaginatedUsers,
    RegisterUserRequest,
    SessionToken,
    UserProfile,
    UserUpdate,
    ValidatedSession,
)
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.settings.adapters.sql_adapter import SqlSettingsAdapter
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


# ==============================================================================
# PROBE 1: COMPLEX NESTED JSON SERIALIZATION & DESERIALIZATION
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_1_complex_nested_json_serialization(sql_settings_adapter: SqlSettingsAdapter):
    """Empirical probe: verify JSON serialization for complex nested structures, unicode, and types."""
    test_cases = {
        "nested_dict": {"lvl1": {"lvl2": {"lvl3": {"lvl4": "deep_val"}}}},
        "mixed_types": {
            "int": 42,
            "neg_int": -999999999,
            "float": 3.141592653589793,
            "bool_true": True,
            "bool_false": False,
            "none_val": None,
            "empty_list": [],
            "empty_dict": {},
            "mixed_list": [1, "two", False, None, {"nested": [3, 4]}],
        },
        "unicode_and_emojis": {
            "hearts": "❤️❤️❤️",
            "bullets": "••••••••",
            "japanese": "こんにちは世界",
            "arabic": "مرحبا بالعالم",
            "symbols": "<>&\"'\n\t\r\\",
        },
        "deep_nesting": {f"k{i}": {f"v{i}": i} for i in range(25)},
        "pure_null": None,
        "pure_bool_true": True,
        "pure_bool_false": False,
        "pure_list": [1, 2, [3, [4, [5]]]],
        "empty_string": "",
    }

    for key, original_val in test_cases.items():
        await sql_settings_adapter.set_setting(key, original_val)

        # Cache read
        cached_val = await sql_settings_adapter.get_setting(key)
        assert cached_val == original_val, f"Cache mismatch for {key}"

        # SQL read after cache invalidation
        sql_settings_adapter.invalidate_cache(key)
        sql_val = await sql_settings_adapter.get_setting(key)
        assert sql_val == original_val, f"SQL mismatch for {key}"

    # Verify get_all_settings reflects all values
    all_settings = await sql_settings_adapter.get_all_settings(mask_secrets=False)
    for key, original_val in test_cases.items():
        assert key in all_settings
        assert all_settings[key] == original_val


# ==============================================================================
# PROBE 2: CACHE CONSISTENCY & INVALIDATION
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_2_cache_consistency_and_invalidation(sql_settings_adapter: SqlSettingsAdapter):
    """Empirical probe: verify selective and global cache invalidation forces fresh DB reads."""
    await sql_settings_adapter.set_setting("k1", "v1")
    await sql_settings_adapter.set_setting("k2", "v2")
    await sql_settings_adapter.set_setting("k3", "v3")

    assert len(sql_settings_adapter._cache) == 3

    # Selective invalidation
    sql_settings_adapter.invalidate_cache("k1")
    assert "k1" not in sql_settings_adapter._cache
    assert "k2" in sql_settings_adapter._cache
    assert "k3" in sql_settings_adapter._cache

    # Re-reading k1 fetches from DB and re-caches
    assert await sql_settings_adapter.get_setting("k1") == "v1"
    assert "k1" in sql_settings_adapter._cache

    # Global invalidation
    sql_settings_adapter.invalidate_cache()
    assert len(sql_settings_adapter._cache) == 0
    assert len(sql_settings_adapter._cache_is_secret) == 0

    # Sequential re-read repopulates cache
    assert await sql_settings_adapter.get_setting("k2") == "v2"
    assert len(sql_settings_adapter._cache) == 1


# ==============================================================================
# PROBE 3: SECRET MASKING IN GET_ALL_SETTINGS
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_3_secret_masking_all_settings(sql_settings_adapter: SqlSettingsAdapter):
    """Empirical probe: verify get_all_settings masks secret values with '••••••••'."""
    await sql_settings_adapter.set_setting("api.key", "sk-secret-12345", is_secret=True)
    await sql_settings_adapter.set_setting("db.password", "super-secret-db-pass", is_secret=True)
    await sql_settings_adapter.set_setting("app.name", "Carefold", is_secret=False)
    await sql_settings_adapter.set_setting("app.version", "0.4.0", is_secret=False)

    # 1. mask_secrets=True (default)
    masked = await sql_settings_adapter.get_all_settings(mask_secrets=True)
    assert masked["api.key"] == SECRET_MASK
    assert masked["api.key"] == "••••••••"
    assert masked["db.password"] == "••••••••"
    assert masked["app.name"] == "Carefold"
    assert masked["app.version"] == "0.4.0"

    # 2. mask_secrets=False
    unmasked = await sql_settings_adapter.get_all_settings(mask_secrets=False)
    assert unmasked["api.key"] == "sk-secret-12345"
    assert unmasked["db.password"] == "super-secret-db-pass"

    # 3. include_secrets=True parameter inversion
    inc_true = await sql_settings_adapter.get_all_settings(include_secrets=True)
    assert inc_true["api.key"] == "sk-secret-12345"

    # 4. include_secrets=False parameter inversion
    inc_false = await sql_settings_adapter.get_all_settings(include_secrets=False)
    assert inc_false["api.key"] == "••••••••"


# ==============================================================================
# PROBE 4: CACHE ISOLATION & NO CACHE POISONING FROM MASKING
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_4_cache_isolation_no_poisoning(sql_settings_adapter: SqlSettingsAdapter):
    """Empirical probe: verify get_all_settings(mask_secrets=True) does NOT poison internal cache."""
    await sql_settings_adapter.set_setting(
        "secret.dict",
        {"api_token": "token-xyz-789", "env": "prod"},
        is_secret=True,
    )

    # Call get_all_settings with mask_secrets=True
    all_masked = await sql_settings_adapter.get_all_settings(mask_secrets=True)
    assert all_masked["secret.dict"] == "••••••••"

    # Internal cache must retain raw value
    assert sql_settings_adapter._cache["secret.dict"] == {
        "api_token": "token-xyz-789",
        "env": "prod",
    }

    # Direct get_setting must return unmasked raw value
    direct_val = await sql_settings_adapter.get_setting("secret.dict")
    assert direct_val == {"api_token": "token-xyz-789", "env": "prod"}


# ==============================================================================
# PROBE 5: CACHE EVICTION ON DELETE & NULL HANDLING
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_5_delete_eviction_and_null_handling(sql_settings_adapter: SqlSettingsAdapter):
    """Empirical probe: verify delete_setting evicts cache and distinguishes null values."""
    # 1. Null value stored
    await sql_settings_adapter.set_setting("null_key", None)
    assert "null_key" in sql_settings_adapter._cache
    # Existing key with value None must return None, NOT default!
    assert await sql_settings_adapter.get_setting("null_key", default="FALLBACK") is None

    # Invalidate and ensure DB read preserves None vs default
    sql_settings_adapter.invalidate_cache("null_key")
    assert await sql_settings_adapter.get_setting("null_key", default="FALLBACK") is None

    # 2. Delete key
    assert await sql_settings_adapter.delete_setting("null_key") is True
    assert "null_key" not in sql_settings_adapter._cache
    assert "null_key" not in sql_settings_adapter._cache_is_secret

    # Now that it is deleted, default MUST be returned!
    assert await sql_settings_adapter.get_setting("null_key", default="FALLBACK") == "FALLBACK"

    # 3. Repeated delete returns False
    assert await sql_settings_adapter.delete_setting("null_key") is False


# ==============================================================================
# PROBE 6: CONCURRENT CACHE HIT PERFORMANCE
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_6_concurrent_cache_hits(sql_settings_adapter: SqlSettingsAdapter):
    """Empirical probe: verify 100 concurrent tasks reading cached settings survive without lock contention."""
    for i in range(10):
        await sql_settings_adapter.set_setting(f"item.{i}", {"val": i, "status": "ok"})

    async def read_worker(task_id):
        key = f"item.{task_id % 10}"
        res = await sql_settings_adapter.get_setting(key)
        assert res["val"] == task_id % 10
        return res

    results = await asyncio.gather(*(read_worker(i) for i in range(100)))
    assert len(results) == 100


# ==============================================================================
# PROBE 7: DISABLED AUTH ADAPTER ZERO-DB BYPASS
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_7_disabled_auth_adapter_zero_db_bypass():
    """Empirical probe: verify DisabledAuthAdapter functions without any DB engine or session."""
    adapter = DisabledAuthAdapter()
    assert isinstance(adapter, AuthPort)

    # 1. Default steward properties
    steward = adapter._steward
    assert steward.id == DEFAULT_STEWARD_USER.id
    assert steward.email == "steward@carefold.local"
    assert steward.username == "steward"
    assert steward.role == "admin"
    assert steward.auth_provider == "disabled"

    # 2. Authentication bypass
    assert await adapter.authenticate("any_user", "any_password") == steward
    assert await adapter.authenticate("", "") == steward

    # 3. Session creation & tuple unpacking
    st = await adapter.create_session("any-id", client_ip="127.0.0.1", user_agent="Desktop")
    assert isinstance(st, SessionToken)
    assert st.token == "disabled-session-token"
    raw_token, session_rec = st
    assert raw_token == "disabled-session-token"
    assert session_rec.user_id == steward.id

    # 4. Session validation & tuple unpacking
    val = await adapter.validate_session("any-token")
    assert isinstance(val, ValidatedSession)
    assert val.id == steward.id
    user_val, sess_val = val
    assert user_val.id == steward.id
    assert sess_val.id == "disabled-session-sha256-hash"

    # 5. Revocation & resets
    assert await adapter.revoke_session("any-token") is True
    assert await adapter.revoke_all_sessions("any-id") == 0
    assert await adapter.create_password_reset_token("any@email.com") == "disabled-password-reset-token"
    assert await adapter.reset_password("any", "new") is True
    assert await adapter.change_password("id", "old", "new") is True

    # 6. List users pagination & unpacking
    paginated = await adapter.list_users()
    assert isinstance(paginated, PaginatedUsers)
    assert paginated.total == 1
    users_list, total_count = paginated
    assert len(users_list) == 1
    assert total_count == 1

    # 7. Update user
    assert await adapter.update_user(steward.id, UserUpdate(full_name="Updated")) == steward


# ==============================================================================
# PROBE 8: DISABLED AUTH ADAPTER CUSTOM STEWARD & DTO REGISTRATION
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_8_disabled_auth_adapter_custom_steward_and_dto():
    """Empirical probe: verify custom steward injection and RegisterUserRequest DTO support."""
    custom_steward = UserProfile(
        id="11111111-2222-3333-4444-555555555555",
        email="custom@provider.org",
        username="lead_doctor",
        full_name="Lead Physician",
        role="steward",
        status="active",
        auth_provider="disabled",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    custom_adapter = DisabledAuthAdapter(steward=custom_steward)

    # DTO registration returns custom steward
    dto = RegisterUserRequest(email="reg@test.local", username="reg", password="password123")
    assert await custom_adapter.register_user(dto) == custom_steward

    # Authenticate returns custom steward
    assert (await custom_adapter.authenticate("foo", "bar")).id == custom_steward.id
    assert (await custom_adapter.create_session("any")).user_id == custom_steward.id


# ==============================================================================
# PROBE 9: SQL INJECTION IN KEYS & SPECIAL CHARACTERS
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_9_hostile_keys_and_sql_injection(sql_settings_adapter: SqlSettingsAdapter):
    """Empirical probe: verify SQL injection attacks in setting keys are safely neutralized."""
    sqli_keys = [
        "'; DROP TABLE system_settings; --",
        "' OR '1'='1",
        "key' UNION SELECT * FROM users --",
        "key; VACUUM;",
    ]

    for key in sqli_keys:
        await sql_settings_adapter.set_setting(key, {"safe": True})
        val = await sql_settings_adapter.get_setting(key)
        assert val == {"safe": True}
        assert await sql_settings_adapter.delete_setting(key) is True

    # Ensure table was not dropped or compromised
    await sql_settings_adapter.set_setting("app.alive", True)
    assert await sql_settings_adapter.get_setting("app.alive") is True


# ==============================================================================
# PROBE 10: NON-JSON SERIALIZABLE OBJECT REJECTION
# ==============================================================================

@pytest.mark.asyncio
async def test_probe_10_non_json_serializable_rejection(sql_settings_adapter: SqlSettingsAdapter):
    """Empirical probe: verify TypeError is raised for non-serializable objects without DB changes."""
    with pytest.raises(TypeError):
        await sql_settings_adapter.set_setting("invalid.set", {1, 2, 3})

    with pytest.raises(TypeError):
        await sql_settings_adapter.set_setting("invalid.lambda", lambda x: x)

    # Ensure key was not persisted in DB or cache
    assert await sql_settings_adapter.get_setting("invalid.set") is None
    assert "invalid.set" not in sql_settings_adapter._cache
