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

"""Unit and integration tests for Admin REST API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from carefold.auth.adapters.disabled_adapter import DisabledAuthAdapter
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.auth.ports import UserUpdate
from carefold.config import settings
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.settings.adapters.sql_adapter import SqlSettingsAdapter
from carefold.settings.factory import reset_settings_port, set_settings_port
from carefold.settings.ports import SECRET_MASK


@pytest.fixture
async def admin_test_env(monkeypatch):
    """Configures an isolated in-memory database with SQL Auth & Settings adapters."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)

    auth_adapter = SqlAuthAdapter(session_factory=session_factory)
    settings_adapter = SqlSettingsAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    set_auth_port(auth_adapter)
    set_settings_port(settings_adapter)

    # Create admin user and normal member
    admin_user = await auth_adapter.register_user(
        email="admin@example.com",
        username="admin_user",
        password="AdminPassword123!",
        full_name="Admin Administrator",
        role="admin",
        auth_provider="local",
    )
    # Ensure role is admin
    await auth_adapter.update_user(admin_user.id, UserUpdate(role="admin"))

    member_user = await auth_adapter.register_user(
        email="member@example.com",
        username="member_user",
        password="MemberPassword123!",
        full_name="Member User",
        role="member",
        auth_provider="local",
    )

    admin_session = await auth_adapter.create_session(admin_user.id)
    member_session = await auth_adapter.create_session(member_user.id)

    from carefold.db.session import get_db
    from carefold.main import app

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield {
            "auth": auth_adapter,
            "settings": settings_adapter,
            "session_factory": session_factory,
            "admin": admin_user,
            "admin_token": admin_session.token,
            "member": member_user,
            "member_token": member_session.token,
        }
    finally:
        app.dependency_overrides.pop(get_db, None)
        reset_auth_port()
        reset_settings_port()


def test_require_admin_forbidden_for_members(client: TestClient, admin_test_env):
    """Verifies 403 Forbidden when a non-admin member attempts to access admin endpoints."""
    member_token = admin_test_env["member_token"]
    resp = client.get(
        "/api/admin/settings",
        cookies={"carefold_session": member_token},
    )
    assert resp.status_code == 403
    assert "Administrative privileges required" in resp.json()["detail"]


def test_require_admin_unauthenticated(client: TestClient, admin_test_env):
    """Verifies 401 Unauthorized when an unauthenticated request attempts to access admin endpoints."""
    resp = client.get("/api/admin/settings")
    assert resp.status_code == 401
    assert "Authentication required" in resp.json()["detail"]


def test_admin_settings_get_and_put(client: TestClient, admin_test_env):
    """Verifies getting and updating runtime system settings via admin API."""
    admin_token = admin_test_env["admin_token"]
    cookies = {"carefold_session": admin_token}

    # Initial settings
    resp = client.get("/api/admin/settings", cookies=cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "settings" in data

    # Update settings
    update_resp = client.put(
        "/api/admin/settings",
        json={
            "settings": {
                "auth.registration_enabled": False,
                "models.default_provider": "google",
            }
        },
        cookies=cookies,
    )
    assert update_resp.status_code == 200
    updated_settings = update_resp.json()["settings"]
    assert updated_settings.get("auth.registration_enabled") is False
    assert updated_settings.get("models.default_provider") == "google"


@pytest.mark.asyncio
async def test_admin_settings_does_not_clobber_secret_with_mask(client: TestClient, admin_test_env):
    """Verifies that submitting SECRET_MASK does not overwrite stored secret via PUT /api/admin/settings."""
    admin_token = admin_test_env["admin_token"]
    settings_adapter = admin_test_env["settings"]
    cookies = {"carefold_session": admin_token}

    await settings_adapter.set_setting("models.anthropic_key", "sk-ant-live-12345", is_secret=True)

    # 1. Update with SECRET_MASK in settings dictionary
    resp = client.put(
        "/api/admin/settings",
        json={
            "settings": {
                "models.anthropic_key": SECRET_MASK,
                "models.default_provider": "anthropic",
            }
        },
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert await settings_adapter.get_setting("models.anthropic_key") == "sk-ant-live-12345"

    # 2. Update with SECRET_MASK in single key/value payload
    resp2 = client.put(
        "/api/admin/settings",
        json={"key": "models.anthropic_key", "value": SECRET_MASK},
        cookies=cookies,
    )
    assert resp2.status_code == 200
    assert await settings_adapter.get_setting("models.anthropic_key") == "sk-ant-live-12345"


def test_admin_list_users(client: TestClient, admin_test_env):
    """Verifies listing users with pagination and search."""
    admin_token = admin_test_env["admin_token"]
    cookies = {"carefold_session": admin_token}

    resp = client.get("/api/admin/users?page=1&limit=10", cookies=cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "users" in data
    assert data["total"] >= 2
    assert data["page"] == 1

    # Search filter
    search_resp = client.get("/api/admin/users?search=member", cookies=cookies)
    assert search_resp.status_code == 200
    search_data = search_resp.json()
    assert any(u["username"] == "member_user" for u in search_data["users"])


def test_admin_create_user(client: TestClient, admin_test_env):
    """Verifies admin user creation with role validation."""
    admin_token = admin_test_env["admin_token"]
    cookies = {"carefold_session": admin_token}

    # Invalid role
    bad_role_resp = client.post(
        "/api/admin/users",
        json={
            "email": "badrole@example.com",
            "username": "badrole",
            "password": "Password123!",
            "role": "superhero",
        },
        cookies=cookies,
    )
    assert bad_role_resp.status_code == 400

    # Successful creation
    good_resp = client.post(
        "/api/admin/users",
        json={
            "email": "doctor@example.com",
            "username": "doctor_who",
            "password": "TardisPassword123!",
            "full_name": "The Doctor",
            "role": "steward",
        },
        cookies=cookies,
    )
    assert good_resp.status_code == 201
    created = good_resp.json()["user"]
    assert created["email"] == "doctor@example.com"
    assert created["role"] == "steward"


def test_admin_patch_user(client: TestClient, admin_test_env):
    """Verifies updating user role and status via admin PATCH."""
    admin_token = admin_test_env["admin_token"]
    cookies = {"carefold_session": admin_token}
    member_id = admin_test_env["member"].id

    # Update role to steward and status to disabled
    patch_resp = client.patch(
        f"/api/admin/users/{member_id}",
        json={"role": "steward", "status": "disabled"},
        cookies=cookies,
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()["user"]
    assert updated["role"] == "steward"
    assert updated["status"] == "disabled"

    # Disabled user's session should now be rejected
    member_token = admin_test_env["member_token"]
    me_resp = client.get("/api/auth/me", cookies={"carefold_session": member_token})
    # Either session was revoked (401) or status inactive (403)
    assert me_resp.status_code in (401, 403)

    # Non-existent user -> 404
    missing_resp = client.patch(
        "/api/admin/users/non-existent-user-id",
        json={"role": "admin"},
        cookies=cookies,
    )
    assert missing_resp.status_code == 404


def test_admin_reset_user_password(client: TestClient, admin_test_env):
    """Verifies admin forcing a user password reset."""
    admin_token = admin_test_env["admin_token"]
    cookies = {"carefold_session": admin_token}
    member_id = admin_test_env["member"].id

    reset_resp = client.post(
        f"/api/admin/users/{member_id}/reset-password",
        json={"new_password": "NewMemberPassword123!"},
        cookies=cookies,
    )
    assert reset_resp.status_code == 200
    assert reset_resp.json()["success"] is True

    # Login with new password succeeds
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "member_user", "password": "NewMemberPassword123!"},
    )
    assert login_resp.status_code == 200


def test_admin_self_deletion_prevented(client: TestClient, admin_test_env):
    """Verifies that an administrator cannot delete their own account."""
    admin_token = admin_test_env["admin_token"]
    admin_id = admin_test_env["admin"].id
    cookies = {"carefold_session": admin_token}

    del_resp = client.delete(f"/api/admin/users/{admin_id}", cookies=cookies)
    assert del_resp.status_code == 400
    assert "Cannot delete own account" in del_resp.json()["detail"]


def test_admin_delete_other_user(client: TestClient, admin_test_env):
    """Verifies that an administrator can delete another user's account."""
    admin_token = admin_test_env["admin_token"]
    cookies = {"carefold_session": admin_token}
    member_id = admin_test_env["member"].id

    del_resp = client.delete(f"/api/admin/users/{member_id}", cookies=cookies)
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # After deletion, member no longer exists
    missing_resp = client.patch(
        f"/api/admin/users/{member_id}",
        json={"role": "member"},
        cookies=cookies,
    )
    assert missing_resp.status_code == 404


def test_admin_diagnostics(client: TestClient, admin_test_env):
    """Verifies retrieval of system diagnostics including database dialect and table counts."""
    admin_token = admin_test_env["admin_token"]
    cookies = {"carefold_session": admin_token}

    resp = client.get("/api/admin/diagnostics", cookies=cookies)
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "ok"
    assert "version" in data
    assert "database" in data
    assert "dialect" in data["database"]
    assert "table_counts" in data
    assert "users" in data["table_counts"]
    assert "sessions" in data["table_counts"]
    assert "agents_count" in data
    assert "skills_count" in data
