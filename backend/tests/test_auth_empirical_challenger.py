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

"""Empirical adversarial challenge test harness for Authentication REST endpoints.

Authored by Challenger 1 (Milestone 3):
1. Registration boundary cases (exact 10-char vs 9-char, missing char classes, case-insensitive collisions).
2. Cookie and Bearer session flows (cookie creation, /me access, logout revoking session & DB record, subsequent 401).
3. Disabled user handling (login returning 403, active session rejected with 403 upon status patching to disabled).
4. Password reset flow (token issuance, single-use consumption, old password rejection, all active sessions revoked).
"""

from __future__ import annotations

import asyncio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.models import Session, User
from carefold.db.session import create_db_engine, get_session_factory, init_db


@pytest.fixture
async def challenge_env(monkeypatch):
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


# ---------------------------------------------------------------------------
# Challenge 1: Registration Boundary Cases
# ---------------------------------------------------------------------------


def test_challenge_registration_password_length_boundary(client: TestClient, challenge_env):
    """Stress tests password length boundary: 9-char password vs exact 10-char password."""
    client.cookies.clear()
    # 9-character password: Aa1!bbbbb (len 9) -> Must fail with HTTP 400
    res_9 = client.post(
        "/api/auth/register",
        json={
            "email": "user9@example.com",
            "username": "user9",
            "password": "Aa1!bbbbb",
            "full_name": "Nine Char User",
        },
    )
    assert res_9.status_code == 400, f"Expected 400 for 9-char password, got {res_9.status_code}: {res_9.text}"
    assert "at least 10 characters" in res_9.json()["detail"]

    # Exact 10-character password: Aa1!bbbbbb (len 10) -> Must succeed with HTTP 201
    res_10 = client.post(
        "/api/auth/register",
        json={
            "email": "user10@example.com",
            "username": "user10",
            "password": "Aa1!bbbbbb",
            "full_name": "Ten Char User",
        },
    )
    assert res_10.status_code == 201, f"Expected 201 for 10-char password, got {res_10.status_code}: {res_10.text}"
    assert res_10.json()["user"]["username"] == "user10"

    # 11-character password: Aa1!bbbbbbb (len 11) -> Must succeed with HTTP 201
    res_11 = client.post(
        "/api/auth/register",
        json={
            "email": "user11@example.com",
            "username": "user11",
            "password": "Aa1!bbbbbbb",
            "full_name": "Eleven Char User",
        },
    )
    assert res_11.status_code == 201, f"Expected 201 for 11-char password, got {res_11.status_code}: {res_11.text}"


def test_challenge_registration_password_character_classes(client: TestClient, challenge_env):
    """Stress tests password complexity: uppercase, lowercase, digit, and special character requirements."""
    client.cookies.clear()
    # Missing uppercase: aa1!bbbbbb (len 10) -> HTTP 400
    res_no_upper = client.post(
        "/api/auth/register",
        json={"email": "noupper@example.com", "username": "noupper", "password": "aa1!bbbbbb"},
    )
    assert res_no_upper.status_code == 400
    assert "uppercase" in res_no_upper.json()["detail"]

    # Missing lowercase: AA1!BBBBBB (len 10) -> HTTP 400
    res_no_lower = client.post(
        "/api/auth/register",
        json={"email": "nolower@example.com", "username": "nolower", "password": "AA1!BBBBBB"},
    )
    assert res_no_lower.status_code == 400
    assert "lowercase" in res_no_lower.json()["detail"]

    # Missing digit AND special character: AaBBcccccc (len 10) -> HTTP 400
    res_no_num_or_special = client.post(
        "/api/auth/register",
        json={"email": "nonum@example.com", "username": "nonum", "password": "AaBBcccccc"},
    )
    assert res_no_num_or_special.status_code == 400
    assert "number or special character" in res_no_num_or_special.json()["detail"]

    # Valid with digit only (no special): Aa1bbbbbbb (len 10) -> HTTP 201
    res_digit_only = client.post(
        "/api/auth/register",
        json={"email": "digitonly@example.com", "username": "digitonly", "password": "Aa1bbbbbbb"},
    )
    assert res_digit_only.status_code == 201

    # Valid with special char only (no digit): Aa!bbbbbbb (len 10) -> HTTP 201
    res_special_only = client.post(
        "/api/auth/register",
        json={"email": "specialonly@example.com", "username": "specialonly", "password": "Aa!bbbbbbb"},
    )
    assert res_special_only.status_code == 201


def test_challenge_registration_duplicate_username_case_insensitive(client: TestClient, challenge_env):
    """Stress tests case-insensitive duplicate username collision."""
    client.cookies.clear()
    # Initial registration: CamelCase username
    res1 = client.post(
        "/api/auth/register",
        json={"email": "case1@example.com", "username": "AliceWalker", "password": "StrongPassword1!"},
    )
    assert res1.status_code == 201

    # Collision 1: lowercase username
    res2 = client.post(
        "/api/auth/register",
        json={"email": "case2@example.com", "username": "alicewalker", "password": "StrongPassword1!"},
    )
    assert res2.status_code == 409, f"Expected 409 for duplicate lowercase username, got {res2.status_code}"

    # Collision 2: UPPERCASE username
    res3 = client.post(
        "/api/auth/register",
        json={"email": "case3@example.com", "username": "ALICEWALKER", "password": "StrongPassword1!"},
    )
    assert res3.status_code == 409, f"Expected 409 for duplicate UPPERCASE username, got {res3.status_code}"

    # Collision 3: Mixed case username
    res4 = client.post(
        "/api/auth/register",
        json={"email": "case4@example.com", "username": "aLiCeWaLkEr", "password": "StrongPassword1!"},
    )
    assert res4.status_code == 409, f"Expected 409 for duplicate mixed case username, got {res4.status_code}"


def test_challenge_registration_duplicate_email_case_insensitive(client: TestClient, challenge_env):
    """Stress tests case-insensitive duplicate email collision."""
    client.cookies.clear()
    # Initial registration: Mixed case email
    res1 = client.post(
        "/api/auth/register",
        json={"email": "Doctor.Bob@Example.Com", "username": "drbob1", "password": "StrongPassword1!"},
    )
    assert res1.status_code == 201

    # Collision 1: all lowercase email
    res2 = client.post(
        "/api/auth/register",
        json={"email": "doctor.bob@example.com", "username": "drbob2", "password": "StrongPassword1!"},
    )
    assert res2.status_code == 409, f"Expected 409 for duplicate lowercase email, got {res2.status_code}"

    # Collision 2: all uppercase email
    res3 = client.post(
        "/api/auth/register",
        json={"email": "DOCTOR.BOB@EXAMPLE.COM", "username": "drbob3", "password": "StrongPassword1!"},
    )
    assert res3.status_code == 409, f"Expected 409 for duplicate uppercase email, got {res3.status_code}"


# ---------------------------------------------------------------------------
# Challenge 2: Cookie and Bearer Session Flow
# ---------------------------------------------------------------------------


def test_challenge_cookie_and_bearer_session_flow(client: TestClient, challenge_env):
    """Stress tests cookie generation, Bearer header access, logout cookie removal, and session DB revocation."""
    client.cookies.clear()
    _, session_factory = challenge_env

    # 1. Register test user
    reg = client.post(
        "/api/auth/register",
        json={"email": "sessionflow@example.com", "username": "sessionflow", "password": "SessionPass123!"},
    )
    assert reg.status_code == 201

    # 2. Login creates valid cookie and returns token
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "sessionflow", "password": "SessionPass123!"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]
    assert token and len(token) > 20

    # Verify cookie attributes
    assert "carefold_session" in login_resp.cookies
    cookie_token = login_resp.cookies["carefold_session"]
    assert cookie_token == token

    # Check Set-Cookie header contains HttpOnly and SameSite
    set_cookie_header = login_resp.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie_header or "httponly" in set_cookie_header.lower()
    assert "samesite=lax" in set_cookie_header.lower()

    # 3. Access /api/auth/me with cookie works
    me_cookie = client.get("/api/auth/me", cookies={"carefold_session": token})
    assert me_cookie.status_code == 200
    assert me_cookie.json()["user"]["username"] == "sessionflow"

    # 4. Access /api/auth/me with Bearer header works
    client.cookies.clear()
    me_bearer = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_bearer.status_code == 200
    assert me_bearer.json()["user"]["username"] == "sessionflow"

    # 5. Access /api/auth/me with lowercase bearer works
    me_bearer_lower = client.get("/api/auth/me", headers={"Authorization": f"bearer {token}"})
    assert me_bearer_lower.status_code == 200
    assert me_bearer_lower.json()["user"]["username"] == "sessionflow"

    # 6. Logout clears cookie and invalidates session token in DB
    logout_resp = client.post("/api/auth/logout", cookies={"carefold_session": token})
    assert logout_resp.status_code == 200
    assert logout_resp.json()["success"] is True

    # Verify cookie is cleared in response
    logout_cookie_header = logout_resp.headers.get("set-cookie", "")
    assert "carefold_session" in logout_cookie_header
    assert "max-age=0" in logout_cookie_header.lower() or 'expires=' in logout_cookie_header.lower()

    # 7. Subsequent requests with that token return 401
    client.cookies.clear()
    subsequent_cookie = client.get("/api/auth/me", cookies={"carefold_session": token})
    assert subsequent_cookie.status_code == 401, f"Expected 401 after logout via cookie, got {subsequent_cookie.status_code}"

    subsequent_bearer = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert subsequent_bearer.status_code == 401, f"Expected 401 after logout via Bearer, got {subsequent_bearer.status_code}"


# ---------------------------------------------------------------------------
# Challenge 3: Disabled User Handling
# ---------------------------------------------------------------------------


def test_challenge_disabled_user_login_rejection(client: TestClient, challenge_env):
    """Stress tests disabled user trying to login: must return 403 Forbidden.

    Specification:
    '3. Disabled user handling: user with status "disabled" trying to login returns 403;
        user active who gets patched to disabled immediately has active session rejected with 403 on subsequent requests.'
    """
    client.cookies.clear()
    sql_adapter, session_factory = challenge_env

    # Register user
    reg = client.post(
        "/api/auth/register",
        json={"email": "disabled1@example.com", "username": "disabled1", "password": "DisabledPass1!"},
    )
    assert reg.status_code == 201
    user_id = reg.json()["user"]["id"]

    # Directly set user status to disabled in database
    async def disable_user():
        async with session_factory() as s:
            u = await s.get(User, user_id)
            u.status = "disabled"
            await s.commit()
    asyncio.run(disable_user())

    client.cookies.clear()

    # User with status "disabled" trying to login must return 403 Forbidden
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "disabled1", "password": "DisabledPass1!"},
    )
    assert login_resp.status_code == 403, (
        f"Expected 403 Forbidden for disabled user login, but got {login_resp.status_code}: {login_resp.text}"
    )
    assert "disabled" in login_resp.json()["detail"].lower()


def test_challenge_active_user_patched_to_disabled_rejects_session(client: TestClient, challenge_env):
    """Stress tests active user session rejection: user active who gets patched to disabled

    immediately has active session rejected with 403 on subsequent requests.

    Specification:
    '3. Disabled user handling: user with status "disabled" trying to login returns 403;
        user active who gets patched to disabled immediately has active session rejected with 403 on subsequent requests.'
    """
    client.cookies.clear()
    sql_adapter, session_factory = challenge_env

    # 1. Register active user
    reg = client.post(
        "/api/auth/register",
        json={"email": "patcheduser@example.com", "username": "patcheduser", "password": "PatchedPass1!"},
    )
    assert reg.status_code == 201
    user_id = reg.json()["user"]["id"]

    # 2. Login to get an active session
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "patcheduser", "password": "PatchedPass1!"},
    )
    assert login_resp.status_code == 200
    user_token = login_resp.json()["token"]

    # 3. Verify session works
    client.cookies.clear()
    me_resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {user_token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["username"] == "patcheduser"

    # 4. Patch user status to 'disabled' directly or via admin
    async def patch_disabled():
        async with session_factory() as s:
            u = await s.get(User, user_id)
            u.status = "disabled"
            await s.commit()
    asyncio.run(patch_disabled())

    # 5. Active session on subsequent requests must be rejected with 403 Forbidden
    client.cookies.clear()
    subsequent_resp = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert subsequent_resp.status_code == 403, (
        f"Expected 403 Forbidden on subsequent request for newly disabled user, but got {subsequent_resp.status_code}: {subsequent_resp.text}"
    )


# ---------------------------------------------------------------------------
# Challenge 4: Password Reset Flow and Session Revocation
# ---------------------------------------------------------------------------


def test_challenge_password_reset_flow_and_session_revocation(client: TestClient, challenge_env):
    """Stress tests password reset flow:

    1. Forgot password issues single-use token.
    2. Token consumed changes password.
    3. Old password fails to login.
    4. New password succeeds to login.
    5. Re-using the same token fails (single-use).
    6. All existing sessions for that user prior to reset are revoked.
    """
    client.cookies.clear()
    # 1. Register user
    reg = client.post(
        "/api/auth/register",
        json={"email": "resetflow@example.com", "username": "resetflow", "password": "OldPass1234!"},
    )
    assert reg.status_code == 201

    # 2. Establish Session 1 (desktop)
    login1 = client.post(
        "/api/auth/login",
        json={"username": "resetflow", "password": "OldPass1234!"},
    )
    token_desktop = login1.json()["token"]

    # 3. Establish Session 2 (mobile)
    login2 = client.post(
        "/api/auth/login",
        json={"username": "resetflow", "password": "OldPass1234!"},
    )
    token_mobile = login2.json()["token"]

    # Clear cookies so requests test specific tokens via Bearer
    client.cookies.clear()

    # Verify both sessions work
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_desktop}"}).status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_mobile}"}).status_code == 200

    # 4. Request password reset token
    forgot_resp = client.post(
        "/api/auth/forgot-password",
        json={"email": "resetflow@example.com"},
    )
    assert forgot_resp.status_code == 200
    reset_token = forgot_resp.json()["token"]
    assert reset_token and len(reset_token) > 10

    # 5. Consume token to change password
    reset_resp = client.post(
        "/api/auth/reset-password",
        json={"token": reset_token, "new_password": "NewPass5678!"},
    )
    assert reset_resp.status_code == 200
    assert reset_resp.json()["success"] is True

    # 6. Re-using the same token must fail (single-use enforcement)
    reused_reset = client.post(
        "/api/auth/reset-password",
        json={"token": reset_token, "new_password": "AnotherPass99!"},
    )
    assert reused_reset.status_code == 400

    # 7. Old password fails to login
    client.cookies.clear()
    old_login = client.post(
        "/api/auth/login",
        json={"username": "resetflow", "password": "OldPass1234!"},
    )
    assert old_login.status_code == 401

    # 8. ALL pre-existing sessions (desktop and mobile) must be revoked!
    client.cookies.clear()
    check_desktop = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_desktop}"})
    assert check_desktop.status_code == 401, (
        f"Expected desktop session to be revoked (401), but got {check_desktop.status_code}"
    )

    check_mobile = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_mobile}"})
    assert check_mobile.status_code == 401, (
        f"Expected mobile session to be revoked (401), but got {check_mobile.status_code}"
    )

    # Also test via cookie
    check_desktop_cookie = client.get("/api/auth/me", cookies={"carefold_session": token_desktop})
    assert check_desktop_cookie.status_code == 401

    # 9. New password succeeds to login and establishes new valid session
    new_login = client.post(
        "/api/auth/login",
        json={"username": "resetflow", "password": "NewPass5678!"},
    )
    assert new_login.status_code == 200
    new_session_token = new_login.json()["token"]
    client.cookies.clear()
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_session_token}"}).status_code == 200
