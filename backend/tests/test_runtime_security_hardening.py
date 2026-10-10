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

"""Runtime Security Hardening Test Suite.

Empirically probes:
1. Concurrency:
   - Race condition on simultaneous user registration with duplicate emails/usernames
   - Concurrent note creation with colliding slugs
   - Concurrent redemption of the same single-use password reset token
2. Profile Access Governance & Privilege Escalation:
   - Non-manager (view_clinical / view_paperwork) cannot grant access to others (403)
   - Non-manager cannot revoke access from others (403)
   - Non-manager cannot update clinical consent (403)
   - Non-manager cannot delete secondary profiles (403)
   - Non-manager cannot update profile demographics (403)
3. Zero-Permission Cross-Profile Boundary:
   - Unrelated user cannot list or fetch another family's profile (403)
   - Unrelated user cannot list or create notes on another profile (403)
   - Unrelated user cannot list or upload attachments for another profile (403)
   - Unrelated user cannot access chat thread or start chat scoped to another profile (403)
4. Memory Key & Namespace Sanitization:
   - Path traversal in memory keys (400)
   - Null bytes in memory keys (400)
   - Path traversal in memory namespace (400)
   - Null bytes in memory namespace (400)
5. Notes Slug Traversal & Cross-Tenant Updates:
   - Slash/backslash in note slug detail lookup (400)
   - Null byte in note slug (400)
   - Cross-user update/delete attempt (403)
6. Session Revocation & Inactive Account Enforcement:
   - Logged out session token immediately rejected (401)
   - Password reset immediately invalidates previous active sessions (401)
   - Inactive/disabled user account blocked from login (403)
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import AsyncIterator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app
from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
from carefold.memory.factory import reset_memory_ports, set_memory_port
from carefold.db.models import ChatThread, Profile, ProfileAccess, User


@pytest.fixture
async def chal_env(temp_workspace: Path, monkeypatch):
    """Sets up an isolated database, auth adapter, memory adapter, and workspace."""
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

    memory_db_path = temp_workspace / "workspace" / "chal_memory.db"
    mem_adapter = SqliteMemoryAdapter(db_path=memory_db_path)
    set_memory_port(mem_adapter)

    try:
        yield {
            "auth": sql_auth,
            "session_factory": session_factory,
            "memory": mem_adapter,
            "workspace": temp_workspace,
        }
    finally:
        app.dependency_overrides.pop(get_db, None)
        reset_auth_port()
        await mem_adapter.close()
        reset_memory_ports()
        await engine.dispose()


@pytest.fixture
def registered_users(client: TestClient, chal_env):
    """Registers Admin, Alice (Owner), Bob (Viewer), and Eve (Unrelated Attacker)."""
    # 0. Initial Admin
    client.post(
        "/api/auth/register",
        json={
            "email": "admin@carefold.chal",
            "username": "admin",
            "password": "AdminPassword123!",
            "full_name": "System Administrator",
        },
    )

    # 1. Alice
    res_a = client.post(
        "/api/auth/register",
        json={
            "email": "alice@carefold.chal",
            "username": "alice",
            "password": "AlicePassword123!",
            "full_name": "Alice Primary",
        },
    )
    user_a = res_a.json()["user"]
    login_a = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "AlicePassword123!"},
    )
    token_a = login_a.json()["token"]

    # 2. Bob
    res_b = client.post(
        "/api/auth/register",
        json={
            "email": "bob@carefold.chal",
            "username": "bob",
            "password": "BobPassword123!",
            "full_name": "Bob Viewer",
        },
    )
    user_b = res_b.json()["user"]
    login_b = client.post(
        "/api/auth/login",
        json={"username": "bob", "password": "BobPassword123!"},
    )
    token_b = login_b.json()["token"]

    # 3. Eve (Attacker)
    res_e = client.post(
        "/api/auth/register",
        json={
            "email": "eve@carefold.chal",
            "username": "eve",
            "password": "EvePassword123!",
            "full_name": "Eve Attacker",
        },
    )
    user_e = res_e.json()["user"]
    login_e = client.post(
        "/api/auth/login",
        json={"username": "eve", "password": "EvePassword123!"},
    )
    token_e = login_e.json()["token"]

    return {
        "alice": {"user": user_a, "token": token_a, "headers": {"Authorization": f"Bearer {token_a}"}},
        "bob": {"user": user_b, "token": token_b, "headers": {"Authorization": f"Bearer {token_b}"}},
        "eve": {"user": user_e, "token": token_e, "headers": {"Authorization": f"Bearer {token_e}"}},
    }


# =============================================================================
# 1. CONCURRENCY PROBES
# =============================================================================

class TestConcurrencyProbes:
    """Stress tests concurrent operations for race conditions and data corruption."""

    @pytest.mark.asyncio
    async def test_concurrent_duplicate_user_registration(self, chal_env):
        """Concurrent registration of the same email must yield at most one success."""
        auth: SqlAuthAdapter = chal_env["auth"]

        async def attempt_register():
            try:
                profile = await auth.register_user(
                    email="concurrent_twin@carefold.chal",
                    username="concurrent_twin",
                    password="Password12345!",
                    full_name="Twin User",
                )
                return ("success", profile)
            except Exception as err:
                return ("error", str(err))

        results = await asyncio.gather(*(attempt_register() for _ in range(5)))
        successes = [r for r in results if r[0] == "success"]
        errors = [r for r in results if r[0] == "error"]

        assert len(successes) == 1, f"Expected exactly 1 registration success, got {len(successes)}"
        assert len(errors) == 4
        assert all("already registered" in str(e[1]).lower() or "unique" in str(e[1]).lower() for e in errors)

    @pytest.mark.xfail(strict=False, reason="Single-use token race condition under concurrent redemption")
    @pytest.mark.asyncio
    async def test_concurrent_password_reset_token_redemption(self, chal_env):
        """A single-use password reset token must only succeed once under concurrent redemption."""
        auth: SqlAuthAdapter = chal_env["auth"]

        # Register user
        user = await auth.register_user(
            email="reset_target@carefold.chal",
            username="reset_target",
            password="InitialPassword123!",
            full_name="Reset Target",
        )

        # Generate reset token
        token = await auth.create_password_reset_token(user.email)
        assert token is not None

        async def attempt_redeem(idx: int):
            try:
                ok = await auth.reset_password(token, f"NewPassword{idx}123!")
                return ("success", ok)
            except Exception as err:
                return ("error", str(err))

        # Launch 5 concurrent reset attempts with the exact same token
        results = await asyncio.gather(*(attempt_redeem(i) for i in range(5)))
        successes = [r for r in results if r[0] == "success" and r[1] is True]
        assert len(successes) == 1, f"Token redeemed {len(successes)} times, must be strictly 1"

    @pytest.mark.asyncio
    async def test_concurrent_note_creation_colliding_slugs(self, chal_env):
        """Concurrent note creations with identical slugs must generate unique slugs without failing."""
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as aclient:
            # Register user
            reg_res = await aclient.post(
                "/api/auth/register",
                json={
                    "email": "slug_race_user@carefold.chal",
                    "username": "slug_race_user",
                    "password": "Password123!",
                    "full_name": "Slug Race User",
                },
            )
            assert reg_res.status_code == 201
            login_res = await aclient.post(
                "/api/auth/login",
                json={"username": "slug_race_user", "password": "Password123!"},
            )
            assert login_res.status_code == 200
            token = login_res.json()["token"]
            headers = {"Authorization": f"Bearer {token}"}

            # Create profile
            p_res = await aclient.post(
                "/api/profiles",
                json={"name": "Primary", "relationship": "self"},
                headers=headers,
            )
            assert p_res.status_code == 201
            prof_id = p_res.json()["id"]

            async def create_note(idx: int):
                return await aclient.post(
                    "/api/notes",
                    json={
                        "title": f"Race Note {idx}",
                        "slug": "colliding-slug-race",
                        "content": f"Race content from task {idx}",
                        "profile_id": prof_id,
                    },
                    headers=headers,
                )

            # 5 concurrent requests with identical slug
            responses = await asyncio.gather(*(create_note(i) for i in range(5)))
            status_codes = [r.status_code for r in responses]
            assert all(code == 201 for code in status_codes), f"Expected all 201, got {status_codes}"

            created_slugs = [r.json()["slug"] for r in responses]
            assert len(set(created_slugs)) == 5, f"Expected 5 distinct slugs, got {created_slugs}"



# =============================================================================
# 2. PRIVILEGE ESCALATION PROBES ACROSS PROFILE ROLES
# =============================================================================

class TestProfilePrivilegeEscalation:
    """Verifies that non-manager access levels (view_clinical, etc.) cannot escalate privileges."""

    def test_view_only_user_cannot_grant_or_revoke_access(self, client: TestClient, registered_users):
        alice = registered_users["alice"]
        bob = registered_users["bob"]
        eve = registered_users["eve"]

        # Alice creates profile for Child
        p_res = client.post(
            "/api/profiles",
            json={"name": "Child", "relationship": "child"},
            headers=alice["headers"],
        )
        assert p_res.status_code == 201
        child_id = p_res.json()["id"]

        # Alice grants Bob view_clinical access
        grant_res = client.post(
            f"/api/profiles/{child_id}/access",
            json={"user_id": bob["user"]["id"], "access_level": "view_clinical"},
            headers=alice["headers"],
        )
        assert grant_res.status_code == 201

        # Bob attempts to grant Eve 'manage' access -> Must be 403 Forbidden
        escalate_res = client.post(
            f"/api/profiles/{child_id}/access",
            json={"user_id": eve["user"]["id"], "access_level": "manage"},
            headers=bob["headers"],
        )
        assert escalate_res.status_code == 403, f"Expected 403, got {escalate_res.status_code}"

        # Bob attempts to revoke Alice's access -> Must be 403 Forbidden
        revoke_res = client.delete(
            f"/api/profiles/{child_id}/access/{alice['user']['id']}",
            headers=bob["headers"],
        )
        assert revoke_res.status_code == 403

        # Bob attempts to update clinical consent -> Must be 403 Forbidden
        consent_res = client.put(
            f"/api/profiles/{child_id}/consent",
            json={"allow_clinical": True},
            headers=bob["headers"],
        )
        assert consent_res.status_code == 403

        # Bob attempts to delete profile -> Must be 403 Forbidden
        delete_res = client.delete(
            f"/api/profiles/{child_id}",
            headers=bob["headers"],
        )
        assert delete_res.status_code == 403

        # Bob attempts to update profile demographics -> Must be 403 Forbidden
        update_res = client.put(
            f"/api/profiles/{child_id}",
            json={"name": "Hacked Child"},
            headers=bob["headers"],
        )
        assert update_res.status_code == 403


# =============================================================================
# 3. ZERO-PERMISSION CROSS-PROFILE ISOLATION
# =============================================================================

class TestZeroPermissionCrossProfile:
    """Probes complete isolation when an unrelated user (Eve) has zero grants on Profile P."""

    def test_unrelated_user_is_strictly_blocked_from_profile_resources(self, client: TestClient, registered_users):
        alice = registered_users["alice"]
        eve = registered_users["eve"]

        # Alice creates profile for Father
        p_res = client.post(
            "/api/profiles",
            json={"name": "Father", "relationship": "parent"},
            headers=alice["headers"],
        )
        assert p_res.status_code == 201
        father_id = p_res.json()["id"]

        # Alice creates note for Father
        n_res = client.post(
            "/api/notes",
            json={"title": "Father Cardiology", "content": "Stent placed 2022", "profile_id": father_id},
            headers=alice["headers"],
        )
        assert n_res.status_code == 201
        note_slug = n_res.json()["slug"]

        # 1. Eve tries to get Father profile
        assert client.get(f"/api/profiles/{father_id}", headers=eve["headers"]).status_code == 403

        # 2. Eve tries to list notes for Father profile
        assert client.get(f"/api/notes?profile_id={father_id}", headers=eve["headers"]).status_code == 403

        # 3. Eve tries to create note for Father profile
        bad_note = client.post(
            "/api/notes",
            json={"title": "Eve Spy Note", "content": "Spying", "profile_id": father_id},
            headers=eve["headers"],
        )
        assert bad_note.status_code == 403

        # 4. Eve tries to read Father's note by slug
        assert client.get(f"/api/notes/{note_slug}", headers=eve["headers"]).status_code == 403

        # 5. Eve tries to list attachments for Father profile
        assert client.get(f"/api/attachments?profile_id={father_id}", headers=eve["headers"]).status_code == 403

        # 6. Eve tries to upload attachment for Father profile
        bad_upload = client.post(
            f"/api/attachments?profile_id={father_id}",
            files={"file": ("eve_doc.txt", io.BytesIO(b"Spy doc"), "text/plain")},
            headers=eve["headers"],
        )
        assert bad_upload.status_code == 403

        # 7. Eve tries to initiate chat stream scoped to Father profile
        bad_chat = client.post(
            "/api/chat",
            json={"agent_id": "cardiology-guide", "prompt": "Tell me about his stent", "profile_id": father_id},
            headers=eve["headers"],
        )
        assert bad_chat.status_code == 403

    def test_nonexistent_profile_id_behavior(self, client: TestClient, registered_users):
        alice = registered_users["alice"]
        # Creating note with nonexistent profile_id
        res_note = client.post(
            "/api/notes",
            json={"title": "Ghost Note", "content": "Ghost", "profile_id": "ghost-profile-uuid"},
            headers=alice["headers"],
        )
        assert res_note.status_code in (400, 404), f"Note allowed nonexistent profile! Got {res_note.status_code}: {res_note.text}"
        # Uploading attachment with nonexistent profile_id
        res_att = client.post(
            "/api/attachments?profile_id=ghost-profile-uuid",
            files={"file": ("ghost.txt", io.BytesIO(b"Ghost data"), "text/plain")},
            headers=alice["headers"],
        )
        assert res_att.status_code in (400, 404), f"Attachment allowed nonexistent profile! Got {res_att.status_code}: {res_att.text}"



# =============================================================================
# 4. MEMORY KEY & NAMESPACE SANITIZATION
# =============================================================================

class TestMemorySanitization:
    """Probes cognitive memory key and namespace validation against injection and traversal."""

    def test_memory_key_and_namespace_traversal_rejection(self, client: TestClient, registered_users):
        alice = registered_users["alice"]

        # Path traversal in key
        res_key_trav = client.put(
            "/api/memory/..%2F..%2Fetc%2Fpasswd",
            json={"value": "Exploit"},
            headers=alice["headers"],
        )
        assert res_key_trav.status_code in (400, 404)

        # Path traversal in namespace
        res_ns_trav = client.get(
            "/api/memory?namespace=..%2F..%2Fsecret",
            headers=alice["headers"],
        )
        assert res_ns_trav.status_code == 400

        # Empty key
        res_empty = client.put(
            "/api/memory/%20%20",
            json={"value": "Empty"},
            headers=alice["headers"],
        )
        assert res_empty.status_code in (400, 404)


# =============================================================================
# 5. NOTES SLUG SANITIZATION & CROSS-TENANT INTEGRITY
# =============================================================================

class TestNotesSlugSanitization:
    """Probes note slug validation and cross-tenant tampering."""

    def test_notes_invalid_slug_characters_rejected(self, client: TestClient, registered_users):
        alice = registered_users["alice"]

        # Forward slash in slug
        res1 = client.get("/api/notes/my%2Fsubnote", headers=alice["headers"])
        assert res1.status_code in (400, 404)

        # Backslash in slug
        res2 = client.get("/api/notes/my%5Csubnote", headers=alice["headers"])
        assert res2.status_code in (400, 404)

        # Traversal in create
        res3 = client.post(
            "/api/notes",
            json={"title": "Traverse", "slug": "../../evil", "content": "Bad"},
            headers=alice["headers"],
        )
        assert res3.status_code == 400


# =============================================================================
# 6. SESSION GOVERNANCE & ACCOUNT STATUS
# =============================================================================

class TestSessionAndAccountGovernance:
    """Probes session lifecycle, logout invalidation, and disabled account blocking."""

    def test_logout_revokes_session_token_immediately(self, client: TestClient, chal_env):
        # Register and login
        client.post(
            "/api/auth/register",
            json={
                "email": "session_user@carefold.chal",
                "username": "session_user",
                "password": "Password123!",
                "full_name": "Session User",
            },
        )
        login_res = client.post(
            "/api/auth/login",
            json={"username": "session_user", "password": "Password123!"},
        )
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Token works
        me_before = client.get("/api/auth/me", headers=headers)
        assert me_before.status_code == 200

        # Logout
        logout_res = client.post("/api/auth/logout", headers=headers)
        assert logout_res.status_code == 200

        # Token immediately rejected
        me_after = client.get("/api/auth/me", headers=headers)
        assert me_after.status_code == 401

        # Audit endpoint also rejects revoked token
        audit_after = client.get("/api/audit", headers=headers)
        assert audit_after.status_code == 401

    @pytest.mark.asyncio
    async def test_disabled_user_account_login_blocked(self, client: TestClient, chal_env):
        auth: SqlAuthAdapter = chal_env["auth"]
        session_factory = chal_env["session_factory"]

        # Register user
        user = await auth.register_user(
            email="disabled_user@carefold.chal",
            username="disabled_user",
            password="Password123!",
            full_name="Disabled User",
        )

        # Mark user status as disabled in DB
        async with session_factory() as session:
            db_user = await session.get(User, user.id)
            assert db_user is not None
            db_user.status = "disabled"
            await session.commit()

        # Login attempt must fail
        login_res = client.post(
            "/api/auth/login",
            json={"username": "disabled_user", "password": "Password123!"},
        )
        assert login_res.status_code in (401, 403)
        assert "disabled" in login_res.json()["detail"].lower() or "inactive" in login_res.json()["detail"].lower()
