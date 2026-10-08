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

"""Unit and integration tests for Authentication REST API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from carefold.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER, DisabledAuthAdapter
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.session import create_db_engine, get_session_factory, init_db


@pytest.fixture
async def auth_test_env(monkeypatch):
    """Configures an isolated in-memory database and SqlAuthAdapter in local auth mode."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    sql_adapter = SqlAuthAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    set_auth_port(sql_adapter)

    try:
        yield sql_adapter, session_factory
    finally:
        reset_auth_port()


def test_auth_providers(client: TestClient):
    """Verifies GET /api/auth/providers returns the active provider configuration."""
    resp = client.get("/api/auth/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert "active_provider" in data
    assert data["registration_enabled"] is True
    assert "sso_providers" in data


def test_register_user_success(client: TestClient, auth_test_env):
    """Verifies successful user registration: first user becomes admin, subsequent users become member."""
    payload = {
        "email": "alice@example.com",
        "username": "alice",
        "password": "Password123!",
        "full_name": "Alice Smith",
    }
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "user" in data
    assert data["user"]["email"] == "alice@example.com"
    assert data["user"]["username"] == "alice"
    assert data["user"]["role"] == "admin"
    assert data["is_initial_admin"] is True
    assert data["user"]["status"] == "active"

    # Second user registration defaults to member
    payload2 = {
        "email": "bob@example.com",
        "username": "bob",
        "password": "Password123!",
        "full_name": "Bob Jones",
    }
    resp2 = client.post("/api/auth/register", json=payload2)
    assert resp2.status_code == 201
    data2 = resp2.json()
    assert data2["user"]["role"] == "member"
    assert data2["is_initial_admin"] is False



def test_register_user_password_complexity(client: TestClient, auth_test_env):
    """Verifies rejection of passwords that do not meet complexity requirements."""
    # Too short (< 10 chars)
    resp1 = client.post(
        "/api/auth/register",
        json={"email": "u1@example.com", "username": "u1", "password": "Short1!"},
    )
    assert resp1.status_code == 400
    assert "at least 10 characters" in resp1.json()["detail"]

    # Missing uppercase
    resp2 = client.post(
        "/api/auth/register",
        json={"email": "u2@example.com", "username": "u2", "password": "password123!"},
    )
    assert resp2.status_code == 400
    assert "uppercase" in resp2.json()["detail"]

    # Missing lowercase
    resp3 = client.post(
        "/api/auth/register",
        json={"email": "u3@example.com", "username": "u3", "password": "PASSWORD123!"},
    )
    assert resp3.status_code == 400
    assert "lowercase" in resp3.json()["detail"]

    # Missing digit or special
    resp4 = client.post(
        "/api/auth/register",
        json={"email": "u4@example.com", "username": "u4", "password": "PasswordOnly"},
    )
    assert resp4.status_code == 400
    assert "number or special character" in resp4.json()["detail"]


def test_register_user_duplicate_conflict(client: TestClient, auth_test_env):
    """Verifies 409 Conflict when attempting to register duplicate email or username."""
    payload = {
        "email": "duplicate@example.com",
        "username": "duplicate_user",
        "password": "StrongPassword1!",
    }
    res1 = client.post("/api/auth/register", json=payload)
    assert res1.status_code == 201

    # Duplicate email
    res2 = client.post(
        "/api/auth/register",
        json={
            "email": "duplicate@example.com",
            "username": "different_user",
            "password": "StrongPassword1!",
        },
    )
    assert res2.status_code == 409

    # Duplicate username
    res3 = client.post(
        "/api/auth/register",
        json={
            "email": "different@example.com",
            "username": "duplicate_user",
            "password": "StrongPassword1!",
        },
    )
    assert res3.status_code == 409


def test_login_and_cookie_generation(client: TestClient, auth_test_env):
    """Verifies login creates a session and attaches HTTP-only cookie."""
    client.post(
        "/api/auth/register",
        json={
            "email": "bob@example.com",
            "username": "bob",
            "password": "BobPassword123!",
        },
    )

    login_resp = client.post(
        "/api/auth/login",
        json={"username": "bob", "password": "BobPassword123!"},
    )
    assert login_resp.status_code == 200
    data = login_resp.json()
    assert "user" in data
    assert data["user"]["username"] == "bob"
    assert "token" in data

    # Check session cookie
    assert "carefold_session" in login_resp.cookies
    token = login_resp.cookies["carefold_session"]
    assert token == data["token"]


def test_login_invalid_credentials(client: TestClient, auth_test_env):
    """Verifies 401 Unauthorized for incorrect passwords or non-existent users."""
    # Non-existent user
    resp1 = client.post(
        "/api/auth/login",
        json={"username": "ghost", "password": "Password123!"},
    )
    assert resp1.status_code == 401
    assert "Invalid credentials" in resp1.json()["detail"]

    # Wrong password
    client.post(
        "/api/auth/register",
        json={"email": "charlie@example.com", "username": "charlie", "password": "CharliePassword1!"},
    )
    resp2 = client.post(
        "/api/auth/login",
        json={"username": "charlie", "password": "WrongPassword1!"},
    )
    assert resp2.status_code == 401


def test_logout_and_cookie_cleared(client: TestClient, auth_test_env):
    """Verifies logout revokes active session and clears the session cookie."""
    client.post(
        "/api/auth/register",
        json={"email": "david@example.com", "username": "david", "password": "DavidPassword1!"},
    )
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "david", "password": "DavidPassword1!"},
    )
    token = login_resp.json()["token"]

    # Ensure /api/auth/me works
    me_resp = client.get("/api/auth/me", cookies={"carefold_session": token})
    assert me_resp.status_code == 200

    # Logout
    logout_resp = client.post("/api/auth/logout", cookies={"carefold_session": token})
    assert logout_resp.status_code == 200
    assert logout_resp.json()["success"] is True

    # After logout, accessing /me should fail with 401
    after_me = client.get("/api/auth/me", cookies={"carefold_session": token})
    assert after_me.status_code == 401


def test_me_endpoint_modes(client: TestClient, auth_test_env, monkeypatch):
    """Verifies /api/auth/me in authenticated, unauthenticated, and disabled modes."""
    # 1. Unauthenticated in local mode -> 401
    unauth_resp = client.get("/api/auth/me")
    assert unauth_resp.status_code == 401

    # 2. Authenticated in local mode via Bearer header -> 200
    client.post(
        "/api/auth/register",
        json={"email": "eve@example.com", "username": "eve", "password": "EvePassword1!"},
    )
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "eve", "password": "EvePassword1!"},
    )
    token = login_resp.json()["token"]

    bearer_resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert bearer_resp.status_code == 200
    assert bearer_resp.json()["user"]["username"] == "eve"

    # 3. Disabled mode -> returns DEFAULT_STEWARD_USER without token
    monkeypatch.setattr(settings, "auth_provider", "disabled")
    set_auth_port(DisabledAuthAdapter())

    disabled_resp = client.get("/api/auth/me")
    assert disabled_resp.status_code == 200
    assert disabled_resp.json()["user"]["id"] == DEFAULT_STEWARD_USER.id
    assert disabled_resp.json()["user"]["role"] == "admin"


def test_forgot_and_reset_password_flow(client: TestClient, auth_test_env):
    """Verifies forgot-password and reset-password token lifecycle."""
    client.post(
        "/api/auth/register",
        json={"email": "frank@example.com", "username": "frank", "password": "OldPassword123!"},
    )

    # Request reset token
    forgot_resp = client.post("/api/auth/forgot-password", json={"email": "frank@example.com"})
    assert forgot_resp.status_code == 200
    data = forgot_resp.json()
    assert data["success"] is True
    token = data["token"]
    assert token is not None

    # Reset with invalid token -> 400
    invalid_reset = client.post(
        "/api/auth/reset-password",
        json={"token": "bogus-token", "new_password": "NewPassword123!"},
    )
    assert invalid_reset.status_code == 400

    # Reset with valid token
    valid_reset = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "NewPassword123!"},
    )
    assert valid_reset.status_code == 200
    assert valid_reset.json()["success"] is True

    # Login with old password fails
    old_login = client.post(
        "/api/auth/login",
        json={"username": "frank", "password": "OldPassword123!"},
    )
    assert old_login.status_code == 401

    # Login with new password succeeds
    new_login = client.post(
        "/api/auth/login",
        json={"username": "frank", "password": "NewPassword123!"},
    )
    assert new_login.status_code == 200


def test_change_password_flow(client: TestClient, auth_test_env):
    """Verifies authenticated password change."""
    client.post(
        "/api/auth/register",
        json={"email": "grace@example.com", "username": "grace", "password": "GracePassword1!"},
    )
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "grace", "password": "GracePassword1!"},
    )
    token = login_resp.json()["token"]

    # Incorrect current password -> 400
    bad_change = client.post(
        "/api/auth/change-password",
        json={"current_password": "WrongPassword1!", "new_password": "NewGracePassword1!"},
        cookies={"carefold_session": token},
    )
    assert bad_change.status_code == 400
    assert "Current password incorrect" in bad_change.json()["detail"]

    # Successful change
    good_change = client.post(
        "/api/auth/change-password",
        json={"current_password": "GracePassword1!", "new_password": "NewGracePassword1!"},
        cookies={"carefold_session": token},
    )
    assert good_change.status_code == 200
    assert good_change.json()["success"] is True

    # Old password no longer works
    assert client.post(
        "/api/auth/login",
        json={"username": "grace", "password": "GracePassword1!"},
    ).status_code == 401

    # New password works
    assert client.post(
        "/api/auth/login",
        json={"username": "grace", "password": "NewGracePassword1!"},
    ).status_code == 200
