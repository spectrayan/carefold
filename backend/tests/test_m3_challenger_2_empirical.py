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

"""Empirical Adversarial Challenge Test Harness for Milestone 3 (Challenger M3-2).

Target:
- R3: Backend Authentication & Admin REST Endpoints & Endpoint Protection
- Admin RBAC Enforcement Across All /api/admin/* Endpoints
- Self-Deletion Prevention and User Deletion Session Revocation
- Settings Secret Masking in GET/PUT /api/admin/settings
- Protected Endpoints & Unbuffered SSE Streaming in /api/chat

Author: challenger_m3_2
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient

from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.auth.ports import UserUpdate
from carefold.config import settings
from carefold.db.models import User
from carefold.db.session import create_db_engine, get_db, get_session_factory, init_db
from carefold.main import app
from carefold.settings.adapters.sql_adapter import SqlSettingsAdapter
from carefold.settings.factory import reset_settings_port, set_settings_port
from carefold.settings.ports import SECRET_MASK, SettingsPort


# ============================================================================
# Helpers
# ============================================================================

def parse_sse_events(raw_text: str) -> List[Dict[str, Any]]:
    """Parses raw HTTP SSE stream content into structured (event_type, data) dicts."""
    events = []
    current_event = None
    current_data = []

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            if current_event or current_data:
                data_str = "\n".join(current_data)
                try:
                    payload = json.loads(data_str) if data_str else {}
                except Exception:
                    payload = {"raw": data_str}
                events.append({"event": current_event or "message", "data": payload})
                current_event = None
                current_data = []
            continue

        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            current_data.append(line[len("data:"):].strip())

    if current_event or current_data:
        data_str = "\n".join(current_data)
        try:
            payload = json.loads(data_str) if data_str else {}
        except Exception:
            payload = {"raw": data_str}
        events.append({"event": current_event or "message", "data": payload})

    return events


# ============================================================================
# Adversarial Test Fixtures
# ============================================================================

@pytest.fixture
async def m3_challenge_env(monkeypatch):
    """Establishes an isolated multi-role SQL auth and settings environment."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)

    auth_adapter = SqlAuthAdapter(session_factory=session_factory)
    settings_adapter = SqlSettingsAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    set_auth_port(auth_adapter)
    set_settings_port(settings_adapter)

    # 1. Primary Admin User
    admin1 = await auth_adapter.register_user(
        email="admin1@spectrayan.care",
        username="admin_one",
        password="Admin1Password123!",
        full_name="Primary Administrator",
        role="admin",
        auth_provider="local",
    )
    await auth_adapter.update_user(admin1.id, UserUpdate(role="admin"))
    admin1_session = await auth_adapter.create_session(admin1.id)

    # 2. Secondary Admin User (for peer deletion checks)
    admin2 = await auth_adapter.register_user(
        email="admin2@spectrayan.care",
        username="admin_two",
        password="Admin2Password123!",
        full_name="Secondary Administrator",
        role="admin",
        auth_provider="local",
    )
    await auth_adapter.update_user(admin2.id, UserUpdate(role="admin"))
    admin2_session = await auth_adapter.create_session(admin2.id)

    # 3. Healthcare Steward User (privileged non-admin)
    steward1 = await auth_adapter.register_user(
        email="steward@spectrayan.care",
        username="steward_lead",
        password="Steward1Password123!",
        full_name="Clinical Care Steward",
        role="steward",
        auth_provider="local",
    )
    await auth_adapter.update_user(steward1.id, UserUpdate(role="steward"))
    steward1_session = await auth_adapter.create_session(steward1.id)

    # 4. Standard Member User (patient/end-user)
    member1 = await auth_adapter.register_user(
        email="member@spectrayan.care",
        username="patient_member",
        password="Member1Password123!",
        full_name="Patient Member",
        role="member",
        auth_provider="local",
    )
    member1_session = await auth_adapter.create_session(member1.id)

    # 5. Disabled User (suspended account)
    disabled1 = await auth_adapter.register_user(
        email="disabled@spectrayan.care",
        username="suspended_user",
        password="Disabled1Password123!",
        full_name="Suspended Account",
        role="member",
        auth_provider="local",
    )
    disabled1_session = await auth_adapter.create_session(disabled1.id)
    await auth_adapter.update_user(disabled1.id, UserUpdate(status="disabled"))

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield {
            "auth": auth_adapter,
            "settings": settings_adapter,
            "session_factory": session_factory,
            "admin1": admin1,
            "admin1_token": admin1_session.token,
            "admin2": admin2,
            "admin2_token": admin2_session.token,
            "steward1": steward1,
            "steward1_token": steward1_session.token,
            "member1": member1,
            "member1_token": member1_session.token,
            "disabled1": disabled1,
            "disabled1_token": disabled1_session.token,
        }
    finally:
        app.dependency_overrides.pop(get_db, None)
        reset_auth_port()
        reset_settings_port()


# ============================================================================
# Probe Suite 1: Exhaustive Admin RBAC Matrix
# ============================================================================

ADMIN_ENDPOINTS = [
    ("GET", "/api/admin/settings", None),
    ("PUT", "/api/admin/settings", {"key": "probe_key", "value": "probe_val"}),
    ("GET", "/api/admin/users", None),
    ("POST", "/api/admin/users", {
        "email": "test_rbac@example.com",
        "username": "test_rbac",
        "password": "Password123!",
        "role": "member",
    }),
    ("PATCH", "/api/admin/users/{user_id}", {"full_name": "Updated Name"}),
    ("POST", "/api/admin/users/{user_id}/reset-password", {"new_password": "NewPassword123!"}),
    ("DELETE", "/api/admin/users/{user_id}", None),
]


@pytest.mark.parametrize("method,path_template,payload", ADMIN_ENDPOINTS)
def test_admin_rbac_unauthenticated_rejected(
    client: TestClient,
    m3_challenge_env,
    method: str,
    path_template: str,
    payload: Optional[Dict[str, Any]],
):
    """Adversarial Probe 1A: Unauthenticated requests to ANY /api/admin/* endpoint return 401."""
    member_id = m3_challenge_env["member1"].id
    url = path_template.replace("{user_id}", member_id)

    resp = client.request(method, url, json=payload)
    assert resp.status_code == 401, f"{method} {url} returned {resp.status_code}, expected 401"
    assert "Authentication required" in resp.json()["detail"]


@pytest.mark.parametrize("method,path_template,payload", ADMIN_ENDPOINTS)
def test_admin_rbac_invalid_token_rejected(
    client: TestClient,
    m3_challenge_env,
    method: str,
    path_template: str,
    payload: Optional[Dict[str, Any]],
):
    """Adversarial Probe 1B: Requests with invalid session tokens return 401."""
    member_id = m3_challenge_env["member1"].id
    url = path_template.replace("{user_id}", member_id)

    # 1. Invalid cookie
    resp_cookie = client.request(
        method,
        url,
        json=payload,
        cookies={"carefold_session": "bogus_hex_token_9999999999"},
    )
    assert resp_cookie.status_code == 401
    assert "Invalid or expired session" in resp_cookie.json()["detail"]

    # 2. Invalid Bearer header
    resp_bearer = client.request(
        method,
        url,
        json=payload,
        headers={"Authorization": "Bearer bogus_bearer_token_8888888888"},
    )
    assert resp_bearer.status_code == 401
    assert "Invalid or expired session" in resp_bearer.json()["detail"]


@pytest.mark.parametrize("method,path_template,payload", ADMIN_ENDPOINTS)
def test_admin_rbac_member_role_forbidden(
    client: TestClient,
    m3_challenge_env,
    method: str,
    path_template: str,
    payload: Optional[Dict[str, Any]],
):
    """Adversarial Probe 1C: Requests with member role return 403 Forbidden across all admin routes."""
    member_token = m3_challenge_env["member1_token"]
    member_id = m3_challenge_env["member1"].id
    url = path_template.replace("{user_id}", member_id)

    # Cookie test
    resp = client.request(
        method,
        url,
        json=payload,
        cookies={"carefold_session": member_token},
    )
    assert resp.status_code == 403, f"{method} {url} returned {resp.status_code}, expected 403"
    assert "Administrative privileges required" in resp.json()["detail"]

    # Bearer header test
    resp_bearer = client.request(
        method,
        url,
        json=payload,
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp_bearer.status_code == 403, f"{method} {url} returned {resp_bearer.status_code}, expected 403"
    assert "Administrative privileges required" in resp_bearer.json()["detail"]


@pytest.mark.parametrize("method,path_template,payload", ADMIN_ENDPOINTS)
def test_admin_rbac_steward_role_forbidden(
    client: TestClient,
    m3_challenge_env,
    method: str,
    path_template: str,
    payload: Optional[Dict[str, Any]],
):
    """Adversarial Probe 1D: Even privileged clinical stewards are forbidden (403) from admin endpoints."""
    steward_token = m3_challenge_env["steward1_token"]
    member_id = m3_challenge_env["member1"].id
    url = path_template.replace("{user_id}", member_id)

    resp = client.request(
        method,
        url,
        json=payload,
        cookies={"carefold_session": steward_token},
    )
    assert resp.status_code == 403
    assert "Administrative privileges required" in resp.json()["detail"]


# ============================================================================
# Probe Suite 2: Self-Deletion Prevention & Session Revocation
# ============================================================================

def test_admin_self_deletion_strictly_prevented(client: TestClient, m3_challenge_env):
    """Adversarial Probe 2A: Admin attempting DELETE /api/admin/users/{current_admin_id} returns 400."""
    admin1 = m3_challenge_env["admin1"]
    admin1_token = m3_challenge_env["admin1_token"]
    cookies = {"carefold_session": admin1_token}

    resp = client.delete(f"/api/admin/users/{admin1.id}", cookies=cookies)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Cannot delete own account"

    # Verify admin account still exists and session remains active
    me_resp = client.get("/api/auth/me", cookies=cookies)
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["id"] == admin1.id

    # Verify admin can still list users
    list_resp = client.get("/api/admin/users", cookies=cookies)
    assert list_resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_delete_other_user_revokes_sessions(client: TestClient, m3_challenge_env):
    """Adversarial Probe 2B: Deleting another user succeeds and revokes their active sessions."""
    admin1_token = m3_challenge_env["admin1_token"]
    member1 = m3_challenge_env["member1"]
    member1_token = m3_challenge_env["member1_token"]
    session_factory = m3_challenge_env["session_factory"]

    # 1. Verify member session is currently valid
    me_before = client.get("/api/auth/me", cookies={"carefold_session": member1_token})
    assert me_before.status_code == 200
    assert me_before.json()["user"]["username"] == "patient_member"

    # 2. Admin deletes member
    del_resp = client.delete(
        f"/api/admin/users/{member1.id}",
        cookies={"carefold_session": admin1_token},
    )
    assert del_resp.status_code == 200
    assert del_resp.json() == {"success": True}

    # 3. Verify user record is gone from DB
    async with session_factory() as session:
        user_in_db = await session.get(User, member1.id)
        assert user_in_db is None

    # 4. Verify member's session is immediately revoked (subsequent request returns 401)
    me_after = client.get("/api/auth/me", cookies={"carefold_session": member1_token})
    assert me_after.status_code == 401
    assert "Invalid or expired session" in me_after.json()["detail"]

    # 5. Subsequent delete on already deleted user returns 404
    del_again = client.delete(
        f"/api/admin/users/{member1.id}",
        cookies={"carefold_session": admin1_token},
    )
    assert del_again.status_code == 404


def test_admin_can_delete_another_admin_with_session_revocation(client: TestClient, m3_challenge_env):
    """Adversarial Probe 2C: Admin 1 can delete Admin 2, revoking Admin 2's session; Admin 1 cannot delete self."""
    admin1_token = m3_challenge_env["admin1_token"]
    admin2 = m3_challenge_env["admin2"]
    admin2_token = m3_challenge_env["admin2_token"]

    # Admin 2 active
    resp2_before = client.get("/api/auth/me", cookies={"carefold_session": admin2_token})
    assert resp2_before.status_code == 200

    # Admin 1 deletes Admin 2
    del_admin2 = client.delete(
        f"/api/admin/users/{admin2.id}",
        cookies={"carefold_session": admin1_token},
    )
    assert del_admin2.status_code == 200

    # Admin 2 session now revoked
    resp2_after = client.get("/api/auth/me", cookies={"carefold_session": admin2_token})
    assert resp2_after.status_code == 401

    # Admin 1 still cannot delete self
    self_del = client.delete(
        f"/api/admin/users/{m3_challenge_env['admin1'].id}",
        cookies={"carefold_session": admin1_token},
    )
    assert self_del.status_code == 400
    assert self_del.json()["detail"] == "Cannot delete own account"


# ============================================================================
# Probe Suite 3: Settings Secret Masking
# ============================================================================

@pytest.mark.asyncio
async def test_settings_secrets_masked_in_get_settings(client: TestClient, m3_challenge_env):
    """Adversarial Probe 3A: Sensitive keys returned from GET /api/admin/settings must be masked."""
    admin1_token = m3_challenge_env["admin1_token"]
    settings_port: SettingsPort = m3_challenge_env["settings"]

    # Seed secrets and public configuration
    await settings_port.set_setting("openai_api_key", "sk-proj-super-secret-openai-key-9988", is_secret=True)
    await settings_port.set_setting("anthropic_api_key", "sk-ant-api03-super-secret-claude-key-7766", is_secret=True)
    await settings_port.set_setting("google_api_key", "AIzaSy-super-secret-gemini-key-5544", is_secret=True)
    await settings_port.set_setting("models.default_provider", "anthropic", is_secret=False)
    await settings_port.set_setting("auth.registration_enabled", True, is_secret=False)

    # Fetch settings via admin REST endpoint
    resp = client.get(
        "/api/admin/settings",
        cookies={"carefold_session": admin1_token},
    )
    assert resp.status_code == 200
    data = resp.json()["settings"]

    # Verify secrets are masked with bullets/asterisks
    assert data["openai_api_key"] == SECRET_MASK
    assert data["anthropic_api_key"] == SECRET_MASK
    assert data["google_api_key"] == SECRET_MASK

    # Verify non-secret values are plaintext
    assert data["models.default_provider"] == "anthropic"
    assert data["auth.registration_enabled"] is True

    # Rigorous wire check: NO plaintext secret appears anywhere in the raw response text
    raw_text = resp.text
    assert "sk-proj-super-secret" not in raw_text
    assert "sk-ant-api03-super-secret" not in raw_text
    assert "AIzaSy-super-secret" not in raw_text


@pytest.mark.asyncio
async def test_settings_secrets_masked_in_put_settings_response(client: TestClient, m3_challenge_env):
    """Adversarial Probe 3B: PUT /api/admin/settings masks secrets in returned payload and preserves internal storage."""
    admin1_token = m3_challenge_env["admin1_token"]
    settings_port: SettingsPort = m3_challenge_env["settings"]

    secret_key = "cohere_api_key"
    secret_val = "cohere-secret-token-abcdef123456"

    # Update setting with is_secret=True
    put_resp = client.put(
        "/api/admin/settings",
        json={"key": secret_key, "value": secret_val, "is_secret": True},
        cookies={"carefold_session": admin1_token},
    )
    assert put_resp.status_code == 200
    put_data = put_resp.json()["settings"]

    # PUT response itself must be masked
    assert put_data[secret_key] == SECRET_MASK
    assert secret_val not in put_resp.text

    # Subsequent GET must also be masked
    get_resp = client.get(
        "/api/admin/settings",
        cookies={"carefold_session": admin1_token},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["settings"][secret_key] == SECRET_MASK
    assert secret_val not in get_resp.text

    # Internal adapter call preserves plaintext for backend LLM engine
    internal_val = await settings_port.get_setting(secret_key)
    assert internal_val == secret_val


# ============================================================================
# Probe Suite 4: Endpoint Protection & SSE Verification for /api/chat
# ============================================================================

def test_api_chat_unauthenticated_returns_401_immediately(client: TestClient, m3_challenge_env):
    """Adversarial Probe 4A: POST /api/chat without token returns 401 immediately prior to streaming."""
    chat_payload = {
        "agentId": "visit-steward",
        "prompt": "Hello! Can you help me prepare for my visit?",
        "mock": True,
        "allow_clinical": True,
    }

    # No cookies, no Authorization header
    resp = client.post("/api/chat", json=chat_payload)
    assert resp.status_code == 401
    assert "text/event-stream" not in resp.headers.get("content-type", "")
    assert resp.headers.get("content-type", "").startswith("application/json")
    assert resp.json()["detail"] == "Authentication required"


def test_api_chat_invalid_token_returns_401_immediately(client: TestClient, m3_challenge_env):
    """Adversarial Probe 4B: POST /api/chat with invalid token returns 401 immediately."""
    chat_payload = {
        "agentId": "visit-steward",
        "prompt": "Hello! Can you help me prepare for my visit?",
        "mock": True,
        "allow_clinical": True,
    }

    # Invalid session cookie
    resp = client.post(
        "/api/chat",
        json=chat_payload,
        cookies={"carefold_session": "nonexistent_session_token_xyz"},
    )
    assert resp.status_code == 401
    assert "text/event-stream" not in resp.headers.get("content-type", "")
    assert resp.json()["detail"] == "Invalid or expired session"

    # Invalid Authorization Bearer header
    resp_bearer = client.post(
        "/api/chat",
        json=chat_payload,
        headers={"Authorization": "Bearer nonexistent_bearer_token_xyz"},
    )
    assert resp_bearer.status_code == 401
    assert "text/event-stream" not in resp_bearer.headers.get("content-type", "")
    assert resp_bearer.json()["detail"] == "Invalid or expired session"


def test_api_chat_disabled_user_returns_403_immediately(client: TestClient, m3_challenge_env):
    """Adversarial Probe 4C: POST /api/chat with disabled user returns 403 Forbidden immediately."""
    disabled_token = m3_challenge_env["disabled1_token"]
    chat_payload = {
        "agentId": "visit-steward",
        "prompt": "Hello! Can you help me prepare for my visit?",
        "mock": True,
        "allow_clinical": True,
    }

    resp = client.post(
        "/api/chat",
        json=chat_payload,
        cookies={"carefold_session": disabled_token},
    )
    assert resp.status_code in (401, 403)
    assert "text/event-stream" not in resp.headers.get("content-type", "")
    assert any(
        msg in resp.json().get("detail", "")
        for msg in ("Invalid or expired session", "Account is disabled", "Authentication required")
    )


def test_api_chat_authenticated_streams_unbuffered_sse(client: TestClient, m3_challenge_env):
    """Adversarial Probe 4D: POST /api/chat with valid token streams SSE events without proxy buffering."""
    member_token = m3_challenge_env["member1_token"]
    chat_payload = {
        "agentId": "visit-steward",
        "prompt": "Can you help me prepare for a general health checkup?",
        "mock": True,
        "allow_clinical": True,
    }

    with client.stream(
        "POST",
        "/api/chat",
        json=chat_payload,
        cookies={"carefold_session": member_token},
    ) as response:
        assert response.status_code == 200
        # Verify SSE content-type
        assert "text/event-stream" in response.headers["content-type"]
        # Verify unbuffered proxy headers
        assert "no-cache" in response.headers.get("cache-control", "")
        assert response.headers.get("x-accel-buffering") == "no"
        assert response.headers.get("connection") == "keep-alive"

        response.read()
        content = response.text

        # Verify streaming event chunks
        assert "event: token" in content
        assert "event: done" in content

        events = parse_sse_events(content)
        event_types = [e["event"] for e in events]
        assert "token" in event_types
        assert "done" in event_types

        done_event = next(e for e in events if e["event"] == "done")
        done_data = done_event["data"]
        assert done_data.get("refused") is False
        suggestions = done_data.get("followUpSuggestions") or done_data.get("suggestions", [])
        assert isinstance(suggestions, list)
        assert len(suggestions) >= 2


def test_api_chat_authenticated_via_bearer_header(client: TestClient, m3_challenge_env):
    """Adversarial Probe 4E: POST /api/chat with Authorization Bearer header streams properly."""
    admin_token = m3_challenge_env["admin1_token"]
    chat_payload = {
        "agentId": "visit-steward",
        "prompt": "What documents should I bring to an appointment?",
        "mock": True,
        "allow_clinical": True,
    }

    with client.stream(
        "POST",
        "/api/chat",
        json=chat_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        assert response.headers.get("x-accel-buffering") == "no"

        response.read()
        assert "event: token" in response.text
        assert "event: done" in response.text


# ============================================================================
# Probe Suite 5: Additional Protected Routes Verification
# ============================================================================

def test_protected_routes_require_authentication(client: TestClient, m3_challenge_env):
    """Adversarial Probe 5: Verifies /api/notes and /api/attachments require authentication."""
    member_token = m3_challenge_env["member1_token"]

    # 1. /api/notes
    notes_unauth = client.get("/api/notes")
    assert notes_unauth.status_code == 401

    notes_auth = client.get("/api/notes", cookies={"carefold_session": member_token})
    assert notes_auth.status_code == 200

    # 2. /api/attachments
    att_unauth = client.get("/api/attachments")
    assert att_unauth.status_code == 401

    att_auth = client.get("/api/attachments", cookies={"carefold_session": member_token})
    assert att_auth.status_code == 200
