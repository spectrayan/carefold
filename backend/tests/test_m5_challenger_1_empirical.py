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

"""Empirical Challenger 1 Suite for Milestone 5: Admin REST Endpoints & RBAC.

Actively stress-tests:
1. Complete RBAC enforcement across all /api/admin/* endpoints (401 unauthenticated, 403 member/steward/disabled).
2. Self-deletion prevention (400 "Cannot delete own account"), valid deletion cascading multi-session revocation.
3. System settings secret masking (••••••••), non-secret updates, secret placeholder preservation.
4. System diagnostics endpoint dialect inspection, table counts, and catalog stats.
"""

from __future__ import annotations

import json
from typing import Any, Dict
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.auth.ports import UserUpdate
from carefold.config import settings
from carefold.constants.defaults import DEFAULT_VERSION
from carefold.db.models import Session as DbSession, SystemSetting, User
from carefold.db.session import create_db_engine, get_db, get_session_factory, init_db
from carefold.settings.adapters.sql_adapter import SqlSettingsAdapter
from carefold.settings.factory import reset_settings_port, set_settings_port
from carefold.settings.ports import SECRET_MASK


@pytest.fixture
async def m5_challenge_env(monkeypatch):
    """Establishes an isolated multi-user, multi-session test environment."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)

    auth_adapter = SqlAuthAdapter(session_factory=session_factory)
    settings_adapter = SqlSettingsAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    set_auth_port(auth_adapter)
    set_settings_port(settings_adapter)

    # 1. Admin 1 (Primary)
    admin1 = await auth_adapter.register_user(
        email="admin1@spectrayan.care",
        username="admin_one",
        password="Admin1Password123!",
        full_name="Admin One",
        role="admin",
        auth_provider="local",
    )
    await auth_adapter.update_user(admin1.id, UserUpdate(role="admin"))
    admin1_session = await auth_adapter.create_session(admin1.id)

    # 2. Admin 2 (Secondary)
    admin2 = await auth_adapter.register_user(
        email="admin2@spectrayan.care",
        username="admin_two",
        password="Admin2Password123!",
        full_name="Admin Two",
        role="admin",
        auth_provider="local",
    )
    await auth_adapter.update_user(admin2.id, UserUpdate(role="admin"))
    admin2_session = await auth_adapter.create_session(admin2.id)

    # 3. Steward User
    steward = await auth_adapter.register_user(
        email="steward@spectrayan.care",
        username="steward_user",
        password="StewardPassword123!",
        full_name="Steward Specialist",
        role="steward",
        auth_provider="local",
    )
    await auth_adapter.update_user(steward.id, UserUpdate(role="steward"))
    steward_session = await auth_adapter.create_session(steward.id)

    # 4. Member User
    member = await auth_adapter.register_user(
        email="member@spectrayan.care",
        username="member_user",
        password="MemberPassword123!",
        full_name="Member Patient",
        role="member",
        auth_provider="local",
    )
    member_session1 = await auth_adapter.create_session(member.id)
    member_session2 = await auth_adapter.create_session(member.id)
    member_session3 = await auth_adapter.create_session(member.id)

    # 5. Disabled Admin User (with active session in DB to test 403 Account is disabled)
    disabled_admin = await auth_adapter.register_user(
        email="disabled_admin@spectrayan.care",
        username="disabled_admin",
        password="DisabledAdminPassword123!",
        full_name="Disabled Admin",
        role="admin",
        auth_provider="local",
    )
    from carefold.auth.adapters.sql_adapter import _hash_token
    from datetime import datetime, timedelta, timezone
    disabled_token = "disabled-admin-raw-session-token-12345"
    async with session_factory() as session:
        user_row = await session.get(User, disabled_admin.id)
        user_row.status = "disabled"
        user_row.role = "admin"
        s = DbSession(
            id=_hash_token(disabled_token),
            user_id=disabled_admin.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            created_at=datetime.now(timezone.utc),
            last_active_at=datetime.now(timezone.utc),
        )
        session.add(s)
        await session.commit()

    # Pre-seed settings
    await settings_adapter.set_setting("auth.registration_enabled", True, is_secret=False)
    await settings_adapter.set_setting("models.default_provider", "ollama", is_secret=False)
    await settings_adapter.set_setting("openai_api_key", "sk-proj-super-secret-key-12345", is_secret=True)
    await settings_adapter.set_setting("anthropic_api_key", "sk-ant-api03-super-secret-67890", is_secret=True)

    from carefold.main import app

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield {
            "engine": engine,
            "session_factory": session_factory,
            "auth": auth_adapter,
            "settings": settings_adapter,
            "admin1": admin1,
            "admin1_token": admin1_session.token,
            "admin2": admin2,
            "admin2_token": admin2_session.token,
            "steward": steward,
            "steward_token": steward_session.token,
            "member": member,
            "member_token": member_session1.token,
            "member_tokens": [member_session1.token, member_session2.token, member_session3.token],
            "disabled_admin": disabled_admin,
            "disabled_admin_token": disabled_token,
        }
    finally:
        app.dependency_overrides.pop(get_db, None)
        reset_auth_port()
        reset_settings_port()


# ============================================================================
# Probe Suite 1: RBAC Access Control Across All /api/admin/* Endpoints
# ============================================================================

ADMIN_ENDPOINTS = [
    ("GET", "/api/admin/settings", None),
    ("PUT", "/api/admin/settings", {"settings": {"auth.registration_enabled": True}}),
    ("GET", "/api/admin/users", None),
    ("POST", "/api/admin/users", {
        "email": "new_probe@spectrayan.care",
        "username": "new_probe",
        "password": "ProbePassword123!",
        "role": "member",
    }),
    ("PATCH", "/api/admin/users/dummy-user-id", {"role": "member"}),
    ("POST", "/api/admin/users/dummy-user-id/reset-password", {"new_password": "NewProbePassword123!"}),
    ("DELETE", "/api/admin/users/dummy-user-id", None),
    ("GET", "/api/admin/diagnostics", None),
]


@pytest.mark.parametrize("method,path,payload", ADMIN_ENDPOINTS)
def test_admin_endpoints_unauthenticated_returns_401(client: TestClient, m5_challenge_env, method, path, payload):
    """Probe 1A: Every /api/admin/* endpoint rejects unauthenticated requests with 401."""
    resp = client.request(method, path, json=payload if payload else None)
    assert resp.status_code == 401, f"{method} {path} expected 401, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "detail" in data
    assert "Authentication required" in data["detail"]


@pytest.mark.parametrize("method,path,payload", ADMIN_ENDPOINTS)
def test_admin_endpoints_invalid_token_returns_401(client: TestClient, m5_challenge_env, method, path, payload):
    """Probe 1B: Every /api/admin/* endpoint rejects invalid/expired session tokens with 401."""
    resp = client.request(
        method,
        path,
        json=payload if payload else None,
        cookies={"carefold_session": "completely-invalid-forged-token-xyz"},
    )
    assert resp.status_code == 401, f"{method} {path} expected 401, got {resp.status_code}: {resp.text}"
    assert "Invalid or expired session" in resp.json()["detail"]


@pytest.mark.parametrize("method,path,payload", ADMIN_ENDPOINTS)
def test_admin_endpoints_member_role_forbidden_403(client: TestClient, m5_challenge_env, method, path, payload):
    """Probe 1C: Every /api/admin/* endpoint rejects member role with 403 Forbidden."""
    member_token = m5_challenge_env["member_token"]
    resp = client.request(
        method,
        path,
        json=payload if payload else None,
        cookies={"carefold_session": member_token},
    )
    assert resp.status_code == 403, f"{method} {path} expected 403 for member, got {resp.status_code}: {resp.text}"
    assert "Administrative privileges required" in resp.json()["detail"]


@pytest.mark.parametrize("method,path,payload", ADMIN_ENDPOINTS)
def test_admin_endpoints_steward_role_forbidden_403(client: TestClient, m5_challenge_env, method, path, payload):
    """Probe 1D: Every /api/admin/* endpoint rejects steward role with 403 Forbidden."""
    steward_token = m5_challenge_env["steward_token"]
    resp = client.request(
        method,
        path,
        json=payload if payload else None,
        cookies={"carefold_session": steward_token},
    )
    assert resp.status_code == 403, f"{method} {path} expected 403 for steward, got {resp.status_code}: {resp.text}"
    assert "Administrative privileges required" in resp.json()["detail"]


@pytest.mark.parametrize("method,path,payload", ADMIN_ENDPOINTS)
def test_admin_endpoints_disabled_admin_forbidden_403(client: TestClient, m5_challenge_env, method, path, payload):
    """Probe 1E: Disabled admin account is rejected with 403 Account is disabled."""
    disabled_token = m5_challenge_env["disabled_admin_token"]
    resp = client.request(
        method,
        path,
        json=payload if payload else None,
        cookies={"carefold_session": disabled_token},
    )
    assert resp.status_code == 403, f"{method} {path} expected 403 for disabled admin, got {resp.status_code}"
    assert "Account is disabled" in resp.json()["detail"]


def test_admin_endpoints_active_admin_authorized(client: TestClient, m5_challenge_env):
    """Probe 1F: Active admin token is authorized on GET /api/admin/settings, users, and diagnostics."""
    admin_token = m5_challenge_env["admin1_token"]
    cookies = {"carefold_session": admin_token}

    for path in ["/api/admin/settings", "/api/admin/users", "/api/admin/diagnostics"]:
        resp = client.get(path, cookies=cookies)
        assert resp.status_code == 200, f"GET {path} failed with {resp.status_code}: {resp.text}"

    # Also test Bearer header format
    for path in ["/api/admin/settings", "/api/admin/users", "/api/admin/diagnostics"]:
        resp = client.get(path, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200, f"Bearer GET {path} failed with {resp.status_code}: {resp.text}"


# ============================================================================
# Probe Suite 2: Self-Deletion Prevention and Session Revocation
# ============================================================================

def test_admin_self_deletion_prevented_cookie(client: TestClient, m5_challenge_env):
    """Probe 2A: Current admin cannot delete own account via session cookie."""
    admin1 = m5_challenge_env["admin1"]
    admin1_token = m5_challenge_env["admin1_token"]

    resp = client.delete(
        f"/api/admin/users/{admin1.id}",
        cookies={"carefold_session": admin1_token},
    )
    assert resp.status_code == 400
    assert "Cannot delete own account" in resp.json()["detail"]


def test_admin_self_deletion_prevented_bearer(client: TestClient, m5_challenge_env):
    """Probe 2B: Current admin cannot delete own account via Authorization Bearer header."""
    admin1 = m5_challenge_env["admin1"]
    admin1_token = m5_challenge_env["admin1_token"]

    resp = client.delete(
        f"/api/admin/users/{admin1.id}",
        headers={"Authorization": f"Bearer {admin1_token}"},
    )
    assert resp.status_code == 400
    assert "Cannot delete own account" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_admin_delete_other_user_cascades_and_revokes_all_sessions(client: TestClient, m5_challenge_env):
    """Probe 2C: Admin deleting another user succeeds, deletes DB record, and immediately revokes all active sessions."""
    admin1_token = m5_challenge_env["admin1_token"]
    member = m5_challenge_env["member"]
    member_tokens = m5_challenge_env["member_tokens"]

    # Verify member tokens are active before deletion
    for token in member_tokens:
        me_check = client.get("/api/auth/me", cookies={"carefold_session": token})
        assert me_check.status_code == 200
        assert me_check.json()["user"]["id"] == member.id

    # Admin deletes member
    del_resp = client.delete(
        f"/api/admin/users/{member.id}",
        cookies={"carefold_session": admin1_token},
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # User no longer exists
    patch_check = client.patch(
        f"/api/admin/users/{member.id}",
        json={"role": "member"},
        cookies={"carefold_session": admin1_token},
    )
    assert patch_check.status_code == 404

    # Every active session token belonging to deleted user is revoked (401)
    for token in member_tokens:
        me_after = client.get("/api/auth/me", cookies={"carefold_session": token})
        assert me_after.status_code == 401
        assert "Invalid or expired session" in me_after.json()["detail"]

    # Admin still functions normally
    admin_check = client.get("/api/auth/me", cookies={"carefold_session": admin1_token})
    assert admin_check.status_code == 200


def test_admin_can_delete_another_admin(client: TestClient, m5_challenge_env):
    """Probe 2D: Admin 1 can delete Admin 2 (cross-admin deletion); Admin 2's session is revoked, Admin 1 survives."""
    admin1_token = m5_challenge_env["admin1_token"]
    admin2 = m5_challenge_env["admin2"]
    admin2_token = m5_challenge_env["admin2_token"]

    # Admin 2 active
    a2_check = client.get("/api/auth/me", cookies={"carefold_session": admin2_token})
    assert a2_check.status_code == 200

    # Admin 1 deletes Admin 2
    del_resp = client.delete(
        f"/api/admin/users/{admin2.id}",
        cookies={"carefold_session": admin1_token},
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # Admin 2 is revoked
    a2_after = client.get("/api/auth/me", cookies={"carefold_session": admin2_token})
    assert a2_after.status_code == 401

    # Admin 1 remains intact
    a1_after = client.get("/api/auth/me", cookies={"carefold_session": admin1_token})
    assert a1_after.status_code == 200


def test_admin_delete_nonexistent_user_returns_404(client: TestClient, m5_challenge_env):
    """Probe 2E: Attempting to delete a nonexistent user UUID returns 404."""
    admin1_token = m5_challenge_env["admin1_token"]
    resp = client.delete(
        "/api/admin/users/00000000-dead-beef-0000-000000000000",
        cookies={"carefold_session": admin1_token},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


# ============================================================================
# Probe Suite 3: Settings Masking, Preservation & Secret Clobber Stress
# ============================================================================

def test_get_settings_masks_sensitive_keys(client: TestClient, m5_challenge_env):
    """Probe 3A: GET /api/admin/settings masks sensitive keys with •••••••• and exposes zero plaintext."""
    admin1_token = m5_challenge_env["admin1_token"]
    resp = client.get("/api/admin/settings", cookies={"carefold_session": admin1_token})
    assert resp.status_code == 200
    data = resp.json()["settings"]

    assert data["openai_api_key"] == SECRET_MASK
    assert data["anthropic_api_key"] == SECRET_MASK

    # Non-secrets remain in plaintext
    assert data["auth.registration_enabled"] is True
    assert data["models.default_provider"] == "ollama"

    # Strict wire leak check: no secret leaked in raw HTTP payload
    assert "sk-proj-super-secret" not in resp.text
    assert "sk-ant-api03" not in resp.text


def test_put_settings_updates_unmasked_setting(client: TestClient, m5_challenge_env):
    """Probe 3B: PUT /api/admin/settings correctly modifies unmasked settings."""
    admin1_token = m5_challenge_env["admin1_token"]
    cookies = {"carefold_session": admin1_token}

    put_resp = client.put(
        "/api/admin/settings",
        json={"settings": {"models.default_provider": "anthropic", "auth.registration_enabled": False}},
        cookies=cookies,
    )
    assert put_resp.status_code == 200
    res_settings = put_resp.json()["settings"]
    assert res_settings["models.default_provider"] == "anthropic"
    assert res_settings["auth.registration_enabled"] is False

    # Verify persistence via GET
    get_resp = client.get("/api/admin/settings", cookies=cookies)
    assert get_resp.status_code == 200
    data = get_resp.json()["settings"]
    assert data["models.default_provider"] == "anthropic"
    assert data["auth.registration_enabled"] is False


@pytest.mark.asyncio
async def test_put_settings_submitting_masked_placeholder_does_not_clobber_secret(client: TestClient, m5_challenge_env):
    """Probe 3C: Submitting masked placeholder •••••••• must NOT clobber the real stored secret."""
    admin1_token = m5_challenge_env["admin1_token"]
    settings_adapter = m5_challenge_env["settings"]
    cookies = {"carefold_session": admin1_token}

    original_secret = "sk-proj-super-secret-key-12345"

    # Step 1: Confirm original secret stored internally
    internal_val_before = await settings_adapter.get_setting("openai_api_key")
    assert internal_val_before == original_secret

    # Step 2: PUT request containing the masked placeholder
    put_resp = client.put(
        "/api/admin/settings",
        json={
            "settings": {
                "openai_api_key": SECRET_MASK,
                "models.default_provider": "google",
            }
        },
        cookies=cookies,
    )
    assert put_resp.status_code == 200

    # Step 3: Check internal storage: MUST NOT be clobbered by ••••••••
    internal_val_after = await settings_adapter.get_setting("openai_api_key")
    assert internal_val_after == original_secret, (
        f"CRITICAL FAULT: Secret was clobbered by masked placeholder! "
        f"Expected '{original_secret}', but got '{internal_val_after}'"
    )

    # Step 4: Check subsequent GET still returns masked secret
    get_resp = client.get("/api/admin/settings", cookies=cookies)
    assert get_resp.status_code == 200
    assert get_resp.json()["settings"]["openai_api_key"] == SECRET_MASK


@pytest.mark.asyncio
async def test_put_settings_updating_secret_with_new_plaintext_value(client: TestClient, m5_challenge_env):
    """Probe 3D: Admin supplying new plaintext secret key updates secret and retains is_secret masking."""
    admin1_token = m5_challenge_env["admin1_token"]
    settings_adapter = m5_challenge_env["settings"]
    cookies = {"carefold_session": admin1_token}

    new_secret = "sk-proj-brand-new-openai-key-99999"

    # Single-key format with is_secret=True
    put_resp = client.put(
        "/api/admin/settings",
        json={"key": "openai_api_key", "value": new_secret, "is_secret": True},
        cookies=cookies,
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["settings"]["openai_api_key"] == SECRET_MASK
    assert new_secret not in put_resp.text

    # Internal adapter returns the new secret
    internal_val = await settings_adapter.get_setting("openai_api_key")
    assert internal_val == new_secret


# ============================================================================
# Probe Suite 4: System Diagnostics Endpoint Integrity
# ============================================================================

def test_admin_diagnostics_endpoint_integrity(client: TestClient, m5_challenge_env):
    """Probe 4A: GET /api/admin/diagnostics returns complete, grounded diagnostic metrics."""
    admin1_token = m5_challenge_env["admin1_token"]
    cookies = {"carefold_session": admin1_token}

    resp = client.get("/api/admin/diagnostics", cookies=cookies)
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "ok"
    assert data["version"] == DEFAULT_VERSION

    # Database section
    assert "database" in data
    db_info = data["database"]
    assert db_info["dialect"] == "sqlite"
    assert db_info["connected"] is True
    assert "url" in db_info

    # Table counts section
    assert "table_counts" in data
    counts = data["table_counts"]
    # We registered admin1, admin2, steward, member, disabled_admin = 5 users
    assert counts["users"] >= 5
    assert counts["sessions"] >= 7
    assert counts["system_settings"] >= 4
    assert counts["password_resets"] >= 0

    # Agent & Skill catalog counts
    assert data["agents_count"] >= 20
    assert data["skills_count"] >= 20
