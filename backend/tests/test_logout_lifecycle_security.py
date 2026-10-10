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

"""Test suite for Backend Logout Session Lifecycle & Revocation."""

from __future__ import annotations

import asyncio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from carefold.auth.adapters.sql_adapter import SqlAuthAdapter, _hash_token
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.models import Session, User
from carefold.db.session import create_db_engine, get_session_factory, init_db


@pytest.fixture
async def logout_auth_env(monkeypatch):
    """Configures an isolated in-memory DB and SqlAuthAdapter in local auth mode."""
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


def test_v1_logout_session_lifecycle(client: TestClient, logout_auth_env):
    """Tests POST /api/v1/auth/logout revokes session in DB, expires cookies, and blocks subsequent requests."""
    client.cookies.clear()
    sql_adapter, session_factory = logout_auth_env

    # 1. Register and login user
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": "logout_adv@example.com",
            "username": "logout_adv",
            "password": "Password123!",
            "full_name": "Logout Tester",
        },
    )
    assert reg.status_code == 201

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": "logout_adv", "password": "Password123!"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]
    assert "carefold_session" in login_resp.cookies

    # 2. Verify Session exists in database
    token_hash = _hash_token(token)

    async def get_db_session():
        async with session_factory() as s:
            return (await s.scalars(select(Session).where(Session.id == token_hash))).first()

    db_sess = asyncio.run(get_db_session())
    assert db_sess is not None
    assert db_sess.user_id == reg.json()["user"]["id"]

    # 3. Verify /me works before logout
    me_resp = client.get("/api/v1/auth/me", cookies={"carefold_session": token})
    assert me_resp.status_code == 200

    # 4. Perform logout via /api/v1/auth/logout
    logout_resp = client.post("/api/v1/auth/logout", cookies={"carefold_session": token})
    assert logout_resp.status_code == 200
    assert logout_resp.json() == {"success": True}

    # 5. Check Set-Cookie response header expires the cookie
    set_cookie_header = logout_resp.headers.get("set-cookie", "").lower()
    assert "carefold_session" in set_cookie_header
    assert "max-age=0" in set_cookie_header or "expires=" in set_cookie_header

    # 6. Verify Session record was physically deleted from DB
    db_sess_after = asyncio.run(get_db_session())
    assert db_sess_after is None, "Session record must be deleted from the database on logout"

    # 7. Subsequent access to /me with old cookie must fail with 401
    after_me_cookie = client.get("/api/v1/auth/me", cookies={"carefold_session": token})
    assert after_me_cookie.status_code == 401

    # 8. Subsequent access to /me with old Bearer token must fail with 401
    after_me_bearer = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert after_me_bearer.status_code == 401


def test_dual_mounted_logout_alias(client: TestClient, logout_auth_env):
    """Verifies that legacy alias POST /api/auth/logout functions identically to /api/v1/auth/logout."""
    client.cookies.clear()
    sql_adapter, session_factory = logout_auth_env

    client.post(
        "/api/auth/register",
        json={"email": "alias@example.com", "username": "alias_user", "password": "Password123!"},
    )
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "alias_user", "password": "Password123!"},
    )
    token = login_resp.json()["token"]

    logout_resp = client.post("/api/auth/logout", cookies={"carefold_session": token})
    assert logout_resp.status_code == 200
    assert logout_resp.json() == {"success": True}

    after_me = client.get("/api/auth/me", cookies={"carefold_session": token})
    assert after_me.status_code == 401


def test_logout_idempotence_and_resilience(client: TestClient, logout_auth_env):
    """Tests logout robustness when called unauthenticated, with garbage tokens, or multiple times."""
    client.cookies.clear()

    # 1. Calling logout with NO credentials should succeed gracefully and return Set-Cookie
    logout_unauth = client.post("/api/v1/auth/logout")
    assert logout_unauth.status_code == 200
    assert logout_unauth.json() == {"success": True}
    assert "carefold_session" in logout_unauth.headers.get("set-cookie", "")

    # 2. Calling logout with invalid/garbage token should not crash
    logout_garbage = client.post(
        "/api/v1/auth/logout",
        cookies={"carefold_session": "invalid_nonexistent_token_999"},
    )
    assert logout_garbage.status_code == 200
    assert logout_garbage.json() == {"success": True}

    # 3. Calling logout with Bearer token header
    client.post(
        "/api/v1/auth/register",
        json={"email": "bearer_logout@example.com", "username": "bearer_logout", "password": "Password123!"},
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": "bearer_logout", "password": "Password123!"},
    )
    token = login_resp.json()["token"]

    # Logout via Authorization header
    logout_bearer = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logout_bearer.status_code == 200
    assert logout_bearer.json() == {"success": True}

    # Repeating the exact same logout must be idempotent (status 200)
    logout_repeat = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logout_repeat.status_code == 200


def test_logout_session_isolation(client: TestClient, logout_auth_env):
    """Verifies that logging out of Session A does NOT invalidate concurrent Session B for the same user."""
    client.cookies.clear()
    sql_adapter, session_factory = logout_auth_env

    # 1. Register user
    client.post(
        "/api/v1/auth/register",
        json={"email": "multi@example.com", "username": "multi_user", "password": "Password123!"},
    )

    # 2. Login client A
    login_a = client.post("/api/v1/auth/login", json={"username": "multi_user", "password": "Password123!"})
    token_a = login_a.json()["token"]

    # 3. Login client B
    login_b = client.post("/api/v1/auth/login", json={"username": "multi_user", "password": "Password123!"})
    token_b = login_b.json()["token"]
    assert token_a != token_b

    # Verify both sessions work
    client.cookies.clear()
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a}"}).status_code == 200
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"}).status_code == 200

    # 4. Logout Session A only
    logout_a = client.post("/api/v1/auth/logout", cookies={"carefold_session": token_a})
    assert logout_a.status_code == 200

    # 5. Verify Session A is revoked, but Session B is STILL VALID
    client.cookies.clear()
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a}"}).status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"}).status_code == 200
