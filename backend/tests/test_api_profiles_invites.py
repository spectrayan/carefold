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

"""Test suite for Family Profiles Viewer Invitations and Avatar/Nickname persistence."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.models import Profile, ProfileAccess, ViewerInvite
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app


@pytest.fixture
async def invites_test_env(temp_workspace: Path, monkeypatch):
    """Sets up an isolated in-memory DB and local SQL auth provider."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    sql_auth = SqlAuthAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    monkeypatch.setattr(settings, "workspace_root", temp_workspace)
    set_auth_port(sql_auth)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    try:
        yield {"session_factory": session_factory, "auth": sql_auth}
    finally:
        app.dependency_overrides.clear()
        reset_auth_port()


def _register_user(client: TestClient, email: str, name: str) -> dict:
    username = email.split("@")[0].replace(".", "_")
    client.post(
        "/api/auth/register",
        json={"email": email, "username": username, "password": "TestPassword123!", "full_name": name},
    )
    res = client.post(
        "/api/auth/login",
        json={"username": username, "password": "TestPassword123!"},
    )
    token = res.json()["token"]
    user_info = res.json()["user"]
    return {"token": token, "user": user_info, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.mark.asyncio
async def test_create_viewer_invite_and_7_day_expiry(invites_test_env):
    """Verifies creating a viewer invite with secure cf-inv- code and 7-day expiration."""
    with TestClient(app) as client:
        owner = _register_user(client, "alice@test.local", "Alice")
        me_resp = client.get("/api/profiles", headers=owner["headers"])
        prof_id = me_resp.json()[0]["id"]

        create_resp = client.post(
            f"/api/profiles/{prof_id}/invites",
            headers=owner["headers"],
            json={
                "invitee_name": "Grandma Rose",
                "role": "viewer",
                "view_clinical": True,
                "view_paperwork": False,
            },
        )
        assert create_resp.status_code == 201
        invite_data = create_resp.json()

        assert invite_data["invite_code"].startswith("cf-inv-")
        assert len(invite_data["invite_code"]) >= 24
        assert invite_data["invitee_name"] == "Grandma Rose"
        assert invite_data["view_clinical"] is True
        assert invite_data["view_paperwork"] is False
        assert invite_data["accepted_at"] is None

        # Verify 7-day expiration
        exp_dt = datetime.fromisoformat(invite_data["expires_at"])
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = exp_dt - now
        assert 6 <= delta.days <= 7


@pytest.mark.asyncio
async def test_list_and_revoke_viewer_invites(invites_test_env):
    """Verifies listing active invitations and revoking an invitation."""
    with TestClient(app) as client:
        owner = _register_user(client, "alice2@test.local", "Alice")
        prof_id = client.get("/api/profiles", headers=owner["headers"]).json()[0]["id"]

        # Create invite
        inv = client.post(
            f"/api/profiles/{prof_id}/invites",
            headers=owner["headers"],
            json={"invitee_name": "Uncle Bob"},
        ).json()
        invite_id = inv["id"]

        # List invites
        list_resp = client.get(f"/api/profiles/{prof_id}/invites", headers=owner["headers"])
        assert list_resp.status_code == 200
        invites = list_resp.json()
        assert any(i["id"] == invite_id for i in invites)

        # Revoke invite
        del_resp = client.delete(f"/api/profiles/{prof_id}/invites/{invite_id}", headers=owner["headers"])
        assert del_resp.status_code == 200
        assert del_resp.json()["revoked"] is True

        # Ensure excluded from active list
        list_resp2 = client.get(f"/api/profiles/{prof_id}/invites", headers=owner["headers"])
        assert not any(i["id"] == invite_id for i in list_resp2.json())


@pytest.mark.asyncio
async def test_accept_viewer_invite_lifecycle(invites_test_env):
    """Verifies accepting an invitation grants ProfileAccess role='viewer' and invalidates the code."""
    with TestClient(app) as client:
        owner = _register_user(client, "alice3@test.local", "Alice")
        viewer = _register_user(client, "bob3@test.local", "Bob")

        prof_id = client.get("/api/profiles", headers=owner["headers"]).json()[0]["id"]

        # 1. Create invite
        inv = client.post(
            f"/api/profiles/{prof_id}/invites",
            headers=owner["headers"],
            json={"invitee_name": "Bob", "view_clinical": True, "view_paperwork": False},
        ).json()
        code = inv["invite_code"]

        # 2. Bob accepts invite
        accept_resp = client.post(
            "/api/profiles/invites/accept",
            headers=viewer["headers"],
            json={"invite_code": code},
        )
        assert accept_resp.status_code == 200
        acc_data = accept_resp.json()
        assert acc_data["success"] is True
        assert acc_data["role"] == "viewer"
        assert acc_data["access_level"] == "view_clinical"
        assert acc_data["profile_id"] == prof_id

        # 3. Bob now sees Alice's profile in list_profiles
        b_profs = client.get("/api/profiles", headers=viewer["headers"]).json()
        assert any(p["id"] == prof_id and p["access_level"] == "view_clinical" for p in b_profs)

        # 4. Attempting to accept again must fail (single-use)
        reaccept = client.post(
            "/api/profiles/invites/accept",
            headers=viewer["headers"],
            json={"invite_code": code},
        )
        assert reaccept.status_code == 400
        assert "already been accepted" in reaccept.json()["detail"].lower()


@pytest.mark.asyncio
async def test_accept_expired_invite_rejected(invites_test_env):
    """Verifies that expired invitations return HTTP 400."""
    session_factory = invites_test_env["session_factory"]

    with TestClient(app) as client:
        owner = _register_user(client, "alice4@test.local", "Alice")
        viewer = _register_user(client, "bob4@test.local", "Bob")
        prof_id = client.get("/api/profiles", headers=owner["headers"]).json()[0]["id"]

        inv = client.post(
            f"/api/profiles/{prof_id}/invites",
            headers=owner["headers"],
            json={"invitee_name": "Bob"},
        ).json()
        code = inv["invite_code"]

        # Manually expire invite in database
        async with session_factory() as session:
            stmt = select(ViewerInvite).where(ViewerInvite.invite_code == code)
            res = await session.execute(stmt)
            record = res.scalar_one()
            record.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
            await session.commit()

        # Bob attempts to accept expired code
        res = client.post(
            "/api/profiles/invites/accept",
            headers=viewer["headers"],
            json={"invite_code": code},
        )
        assert res.status_code == 400
        assert "expired" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_profile_short_name_and_avatar_url_persistence(invites_test_env):
    """Verifies that short_name and avatar_url persist to SQLite and are returned in queries."""
    with TestClient(app) as client:
        owner = _register_user(client, "alice5@test.local", "Alice")

        # 1. Create with short_name and avatar_url
        create_resp = client.post(
            "/api/profiles",
            headers=owner["headers"],
            json={
                "name": "Leonardo Da Vinci",
                "short_name": "Leo",
                "relationship": "child",
                "avatar_url": "/uploads/avatars/leo_123.png",
                "avatar_color": "3",
            },
        )
        assert create_resp.status_code == 201
        p_data = create_resp.json()
        prof_id = p_data["id"]
        assert p_data["short_name"] == "Leo"
        assert p_data["avatar_url"] == "/uploads/avatars/leo_123.png"

        # 2. Get profile detail
        get_resp = client.get(f"/api/profiles/{prof_id}", headers=owner["headers"])
        assert get_resp.status_code == 200
        assert get_resp.json()["short_name"] == "Leo"
        assert get_resp.json()["avatar_url"] == "/uploads/avatars/leo_123.png"

        # 3. Update short_name and avatar_url
        update_resp = client.put(
            f"/api/profiles/{prof_id}",
            headers=owner["headers"],
            json={
                "short_name": "Little Leo",
                "avatar_url": "/uploads/avatars/leo_v2.png",
            },
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["short_name"] == "Little Leo"
        assert update_resp.json()["avatar_url"] == "/uploads/avatars/leo_v2.png"

        # 4. List profiles
        list_resp = client.get("/api/profiles", headers=owner["headers"])
        assert list_resp.status_code == 200
        leo_entry = next(p for p in list_resp.json() if p["id"] == prof_id)
        assert leo_entry["short_name"] == "Little Leo"
        assert leo_entry["avatar_url"] == "/uploads/avatars/leo_v2.png"
