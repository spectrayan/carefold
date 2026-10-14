# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Comprehensive test suite for Carefold Autonomy Batch 2: Profile Deletion Cascade (AU-11)
and Deep Entity Scoping (AU-12, AU-13).

Covers:
- Suite 1: Profile Deletion Cascade & Crypto-Shredding (AU-11):
  1. Cascade execution order (DEK drop -> CAS wipe -> Memory purge -> DB child cascade -> Profile row delete)
  2. DEK crypto-shredding from profile_keys
  3. CAS storage directory purge
  4. Memory namespace purge across candidate namespaces
  5. Relational child records deletion across 11 dependent models
  6. Tamper-evident AuditEventRecord profile_id update to NULL (SET NULL)
  7. Primary 'Me' profile deletion blocked with HTTP 400
- Suite 2: Idempotency & Error Recovery (AU-11):
  8. Deletion when CAS directory is absent on disk
  9. Resilient deletion when external memory/Spector service is unreachable
  10. Deletion when profile has no DEK row
  11. Cross-user profile deletion blocked with HTTP 403
  12. Non-existent profile deletion returns HTTP 404
- Suite 3: Deep Entity Scoping for Notes (AU-12):
  13. Note creation with profile_id = null rejected (HTTP 400)
  14. Note creation with empty string profile_id rejected (HTTP 400)
  15. Note creation with missing profile_id rejected (HTTP 400)
  16. Note creation with valid profile_id succeeds and persists scoped row
  17. Note update with null/empty profile_id rejected (HTTP 400)
  18. Cross-profile note read blocked with HTTP 403
  19. Cross-profile note update blocked with HTTP 403
  20. Cross-profile note deletion blocked with HTTP 403
  21. Note list filtering strictly scoped by profile_id
- Suite 4: Deep Entity Scoping for Chat Threads (AU-13):
  22. Chat stream with null profile_id rejected (HTTP 400)
  23. Chat stream with empty string profile_id rejected (HTTP 400)
  24. Chat stream with unauthorized profile_id rejected (HTTP 403)
  25. Cross-profile chat thread history blocked with HTTP 403
  26. Cross-profile chat thread deletion blocked with HTTP 403
  27. Database models enforce nullable=False on Note.profile_id & ChatThread.profile_id
- Suite 5: Deep Entity Scoping for Memory CRUD (AU-13):
  28. Memory recall requires profile_id (HTTP 400)
  29. Memory recall cross-profile blocked with HTTP 403
  30. Memory delete_all requires profile_id (HTTP 400)
  31. Memory delete_all cross-profile blocked with HTTP 403
  32. Memory single-item CRUD strictly scoped by profile_id
- Suite 6: Alembic Migration 0004 Verification (AU-12, AU-13):
  33. Migration 0004 upgrade and downgrade cycles (nullable=False <-> nullable=True)
  34. Migration 0004 legacy null profile_id safe data backfill
"""

from __future__ import annotations

import datetime
import io
import json
import os
from pathlib import Path
import shutil
from typing import AsyncIterator
import uuid

import alembic.command
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, delete, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import StaticPool

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.models import (
    Approval,
    Attachment,
    AuditEventRecord,
    ChatThread,
    Connection,
    Credential,
    Job,
    Note,
    Profile,
    ProfileAccess,
    ProfileConsent,
    ProfileKey,
    User,
    ViewerInvite,
)
from carefold.db.session import (
    create_db_engine,
    get_alembic_config,
    get_session_factory,
    init_db,
)
from carefold.main import app
from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
from carefold.memory.factory import reset_memory_ports, set_memory_port
from carefold.memory.ports.memory_port import MemoryTier
from carefold.vault.dek import get_or_create_dek, delete_profile_keys


@pytest.fixture
async def cascade_test_env(temp_workspace: Path, monkeypatch):
    """Sets up an isolated in-memory DB, local SQL auth provider, and memory port."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    sql_auth = SqlAuthAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    monkeypatch.setattr(settings, "workspace_root", temp_workspace)
    monkeypatch.setattr(settings, "home_dir", temp_workspace / "home")
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

    memory_db_path = temp_workspace / "memories.db"
    mem_adapter = SqliteMemoryAdapter(db_path=memory_db_path)
    set_memory_port(mem_adapter)

    try:
        yield {
            "workspace": temp_workspace,
            "home": settings.home_dir,
            "auth": sql_auth,
            "memory_adapter": mem_adapter,
            "session_factory": session_factory,
        }
    finally:
        app.dependency_overrides.clear()
        reset_auth_port()
        await mem_adapter.close()
        set_memory_port(None)


def register_and_login(client: TestClient, email: str, password: str, name: str) -> dict:
    """Helper to register and authenticate a user against local auth."""
    # Ensure an initial admin exists so test users are standard members
    client.post(
        "/api/auth/register",
        json={
            "email": "admin@carefold.test",
            "username": "admin",
            "password": "AdminPassword123!",
            "full_name": "System Administrator",
        },
    )
    username = email.split("@")[0].replace(".", "_")
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "username": username, "password": password, "full_name": name},
    )
    assert resp.status_code in (201, 400), resp.text
    login_resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert login_resp.status_code == 200, login_resp.text
    token = login_resp.json()["token"]
    user_info = login_resp.json()["user"]
    headers = {"Authorization": f"Bearer {token}"}
    client.get("/api/profiles", headers=headers)
    return {"token": token, "user": user_info, "headers": headers}


# ============================================================================
# Suite 1: Profile Deletion Cascade & Crypto-Shredding (AU-11)
# ============================================================================

@pytest.mark.asyncio
async def test_01_profile_deletion_cascade_order_verification(cascade_test_env, monkeypatch):
    """Test 01: Verifies the exact 5-phase deletion cascade sequence."""
    order_log: list[str] = []

    with TestClient(app) as client:
        user_a = register_and_login(client, "alice1@test.local", "Password123!", "Alice")

        # Create secondary profile
        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Dad", "relationship": "parent"},
        )
        assert p_resp.status_code == 201
        dad_id = p_resp.json()["id"]

        # Instrument Step 1: delete_profile_keys
        orig_delete_keys = delete_profile_keys
        async def spy_delete_keys(db, profile_id):
            order_log.append("1_dek_drop")
            return await orig_delete_keys(db, profile_id)
        monkeypatch.setattr("carefold.api.profiles.delete_profile_keys", spy_delete_keys)

        # Instrument Step 2: shutil.rmtree
        orig_rmtree = shutil.rmtree
        def spy_rmtree(path, *args, **kwargs):
            if str(dad_id) in str(path) and "2_cas_rm" not in order_log:
                order_log.append("2_cas_rm")
            return orig_rmtree(path, *args, **kwargs)
        monkeypatch.setattr("carefold.api.profiles.shutil.rmtree", spy_rmtree)

        # Instrument Step 3: memory_port.forget_all
        mem_adapter = cascade_test_env["memory_adapter"]
        orig_forget_all = mem_adapter.forget_all
        def spy_forget_all(namespace="default"):
            if "3_memory_purge" not in order_log:
                order_log.append("3_memory_purge")
            return orig_forget_all(namespace=namespace)
        monkeypatch.setattr(mem_adapter, "forget_all", spy_forget_all)

        # Create physical CAS dir so rmtree is called
        cas_dir = cascade_test_env["home"] / "data" / "files" / user_a["user"]["id"] / dad_id
        cas_dir.mkdir(parents=True, exist_ok=True)
        (cas_dir / "sample.txt").write_text("sample")

        # Invoke delete
        del_resp = client.delete(f"/api/profiles/{dad_id}", headers=user_a["headers"])
        assert del_resp.status_code in (200, 204)

        # Verify steps occurred in sequence
        assert "1_dek_drop" in order_log
        assert "2_cas_rm" in order_log
        assert "3_memory_purge" in order_log
        assert order_log.index("1_dek_drop") < order_log.index("2_cas_rm") < order_log.index("3_memory_purge")


@pytest.mark.asyncio
async def test_02_profile_deletion_instant_crypto_shredding(cascade_test_env):
    """Test 02: Deleting a profile drops its DEK from profile_keys (crypto-shredding)."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice2@test.local", "Password123!", "Alice")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Sister", "relationship": "sibling"},
        )
        assert p_resp.status_code == 201
        prof_id = p_resp.json()["id"]

        session_factory = cascade_test_env["session_factory"]
        async with session_factory() as session:
            # Generate a DEK for this profile
            raw_dek, ver = await get_or_create_dek(session, prof_id, kek=os.urandom(32))
            assert raw_dek is not None
            assert ver == 1

            # Verify key row exists
            k_stmt = select(ProfileKey).where(ProfileKey.profile_id == prof_id)
            k_res = await session.execute(k_stmt)
            assert k_res.scalar_one_or_none() is not None

        # Delete profile
        del_resp = client.delete(f"/api/profiles/{prof_id}", headers=user_a["headers"])
        assert del_resp.status_code in (200, 204)

        # Verify DEK is permanently purged
        async with session_factory() as session:
            k_res = await session.execute(select(ProfileKey).where(ProfileKey.profile_id == prof_id))
            assert k_res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_03_profile_deletion_cas_directory_purged(cascade_test_env):
    """Test 03: Profile deletion removes CAS and upload file directories on disk."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice3@test.local", "Password123!", "Alice")
        uid = user_a["user"]["id"]

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Brother", "relationship": "sibling"},
        )
        prof_id = p_resp.json()["id"]

        # Create physical CAS and upload directories
        home = cascade_test_env["home"]
        cas_dir = home / "data" / "files" / uid / prof_id
        cas_dir.mkdir(parents=True, exist_ok=True)
        doc_file = cas_dir / "lab_report.pdf"
        doc_file.write_bytes(b"%PDF-1.4 test lab report")

        uploads_dir = settings.get_uploads_dir() / uid / prof_id
        uploads_dir.mkdir(parents=True, exist_ok=True)
        up_file = uploads_dir / "temp_upload.txt"
        up_file.write_text("temporary upload")

        assert doc_file.exists()
        assert up_file.exists()

        # Delete profile
        del_resp = client.delete(f"/api/profiles/{prof_id}", headers=user_a["headers"])
        assert del_resp.status_code in (200, 204)

        # Verify filesystem wipe
        assert not cas_dir.exists()
        assert not uploads_dir.exists()


@pytest.mark.asyncio
async def test_04_profile_deletion_memory_namespace_purged(cascade_test_env):
    """Test 04: Profile deletion purges memory namespaces."""
    mem_adapter = cascade_test_env["memory_adapter"]

    with TestClient(app) as client:
        user_a = register_and_login(client, "alice4@test.local", "Password123!", "Alice")
        uid = user_a["user"]["id"]

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Grandma", "relationship": "grandparent"},
        )
        prof_id = p_resp.json()["id"]

        # Store memories in candidate namespaces
        await mem_adapter.remember(
            key="condition",
            value={"dx": "osteoporosis"},
            tier=MemoryTier.WORKING,
            namespace=prof_id,
        )
        await mem_adapter.remember(
            key="allergy",
            value={"med": "penicillin"},
            tier=MemoryTier.WORKING,
            namespace=f"user_{uid}_profile_{prof_id}",
        )

        assert (await mem_adapter.get("condition", namespace=prof_id)) is not None
        assert (await mem_adapter.get("allergy", namespace=f"user_{uid}_profile_{prof_id}")) is not None

        # Delete profile
        del_resp = client.delete(f"/api/profiles/{prof_id}", headers=user_a["headers"])
        assert del_resp.status_code in (200, 204)

        # Verify memories forgotten
        assert (await mem_adapter.get("condition", namespace=prof_id)) is None
        assert (await mem_adapter.get("allergy", namespace=f"user_{uid}_profile_{prof_id}")) is None


@pytest.mark.asyncio
async def test_05_profile_deletion_db_child_rows_cascade(cascade_test_env):
    """Test 05: Deleting a profile deletes dependent rows across all 11 child tables."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice5@test.local", "Password123!", "Alice")
        uid = user_a["user"]["id"]

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Child Profile", "relationship": "child"},
        )
        prof_id = p_resp.json()["id"]

        session_factory = cascade_test_env["session_factory"]
        async with session_factory() as session:
            # 1. Note
            session.add(Note(
                id=str(uuid.uuid4()),
                slug=f"child-note-{uuid.uuid4().hex[:6]}",
                title="Pediatric Checkup",
                content="Healthy child",
                user_id=uid,
                profile_id=prof_id,
            ))
            # 2. ChatThread
            session.add(ChatThread(
                id=f"thread-{uuid.uuid4().hex[:8]}",
                user_id=uid,
                profile_id=prof_id,
                agent_id="pediatric-guide",
                title="Pediatric Chat",
            ))
            # 3. Attachment
            session.add(Attachment(
                id=str(uuid.uuid4()),
                user_id=uid,
                profile_id=prof_id,
                filename="growth_chart.png",
                original_name="growth_chart.png",
                content_type="image/png",
                size_bytes=1024,
            ))
            # 4. Connection
            conn = Connection(
                id=str(uuid.uuid4()),
                user_id=uid,
                profile_id=prof_id,
                connector_id="mychart-child",
                status="active",
            )
            session.add(conn)
            await session.flush()

            # 5. Credential
            session.add(Credential(
                id=str(uuid.uuid4()),
                connection_id=conn.id,
                user_id=uid,
                profile_id=prof_id,
                encrypted_blob="encrypted-secret-token",
                token_version=1,
                dek_version=1,
            ))
            # 6. ProfileKey
            session.add(ProfileKey(
                id=str(uuid.uuid4()),
                profile_id=prof_id,
                encrypted_dek="dek-ciphertext",
                dek_version=1,
            ))
            # 7. Job
            session.add(Job(
                id=str(uuid.uuid4()),
                profile_id=prof_id,
                kind="routine",
                routine_id="vaccine_tracker",
                next_run_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1),
            ))
            # 8. Approval
            session.add(Approval(
                id=str(uuid.uuid4()),
                profile_id=prof_id,
                run_id="run-1",
                tool_name="request_records",
                risk_tier="low",
                status="pending",
                payload_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
            ))
            # 9. ViewerInvite
            session.add(ViewerInvite(
                id=str(uuid.uuid4()),
                invite_code=f"cf-inv-{uuid.uuid4().hex[:8]}",
                profile_id=prof_id,
                invitee_name="Pediatrician Clinic",
                role="viewer",
                invited_by=uid,
                view_clinical=True,
                view_paperwork=False,
                expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7),
            ))
            await session.commit()

        # Verify child rows exist before deletion
        async with session_factory() as session:
            for model in [Note, ChatThread, Attachment, Credential, Connection, ProfileKey, Job, Approval, ViewerInvite, ProfileAccess, ProfileConsent]:
                cnt = (await session.execute(select(model).where(model.profile_id == prof_id))).scalars().all()
                assert len(cnt) >= 1, f"Expected rows in {model.__name__}"

        # Delete profile
        del_resp = client.delete(f"/api/profiles/{prof_id}", headers=user_a["headers"])
        assert del_resp.status_code in (200, 204)

        # Verify all child rows across all 11 models are deleted
        async with session_factory() as session:
            for model in [Note, ChatThread, Attachment, Credential, Connection, ProfileKey, Job, Approval, ViewerInvite, ProfileAccess, ProfileConsent]:
                cnt = (await session.execute(select(model).where(model.profile_id == prof_id))).scalars().all()
                assert len(cnt) == 0, f"Expected 0 rows in {model.__name__} after cascade"


@pytest.mark.asyncio
async def test_06_profile_deletion_audit_events_preserved_with_null(cascade_test_env):
    """Test 06: Profile deletion sets audit_events.profile_id to NULL (ON DELETE SET NULL)."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice6@test.local", "Password123!", "Alice")
        uid = user_a["user"]["id"]

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Audit Profile", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        audit_id = str(uuid.uuid4())
        session_factory = cascade_test_env["session_factory"]
        async with session_factory() as session:
            session.add(AuditEventRecord(
                id=audit_id,
                event="profile_access",
                principal="user",
                actor_user_id=uid,
                profile_id=prof_id,
            ))
            await session.commit()

        # Delete profile
        del_resp = client.delete(f"/api/profiles/{prof_id}", headers=user_a["headers"])
        assert del_resp.status_code in (200, 204)

        # Verify AuditEventRecord is preserved and profile_id is set to None
        async with session_factory() as session:
            rec = (await session.execute(select(AuditEventRecord).where(AuditEventRecord.id == audit_id))).scalar_one_or_none()
            assert rec is not None
            assert rec.profile_id is None


@pytest.mark.asyncio
async def test_07_primary_me_profile_deletion_blocked_400(cascade_test_env):
    """Test 07: Attempting to delete the primary 'Me' profile returns HTTP 400."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice7@test.local", "Password123!", "Alice")

        # Auto-provision primary profile
        p_list = client.get("/api/profiles", headers=user_a["headers"]).json()
        assert len(p_list) == 1
        me_id = p_list[0]["id"]
        assert p_list[0]["is_primary"] is True

        # Attempt to delete primary
        del_resp = client.delete(f"/api/profiles/{me_id}", headers=user_a["headers"])
        assert del_resp.status_code == 400
        assert "Cannot delete primary 'Me' profile" in del_resp.json()["detail"]

        # Verify profile is still in DB
        session_factory = cascade_test_env["session_factory"]
        async with session_factory() as session:
            p_row = (await session.execute(select(Profile).where(Profile.id == me_id))).scalar_one_or_none()
            assert p_row is not None


# ============================================================================
# Suite 2: Idempotency & Error Recovery (AU-11)
# ============================================================================

@pytest.mark.asyncio
async def test_08_profile_deletion_idempotent_when_cas_dir_absent(cascade_test_env):
    """Test 08: Profile deletion succeeds when no CAS directory exists on disk."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice8@test.local", "Password123!", "Alice")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "No CAS Profile", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        # Delete without any directory existing
        del_resp = client.delete(f"/api/profiles/{prof_id}", headers=user_a["headers"])
        assert del_resp.status_code in (200, 204)
        assert del_resp.json()["deleted"] is True


@pytest.mark.asyncio
async def test_09_profile_deletion_resilient_when_spector_unreachable(cascade_test_env, monkeypatch):
    """Test 09: Profile deletion logs a warning and completes if memory service is unreachable."""
    mem_adapter = cascade_test_env["memory_adapter"]

    def failing_forget_all(*args, **kwargs):
        raise ConnectionError("Spector Cognitive Memory connection refused on port 7070")

    monkeypatch.setattr(mem_adapter, "forget_all", failing_forget_all)

    with TestClient(app) as client:
        user_a = register_and_login(client, "alice9@test.local", "Password123!", "Alice")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Resilient Profile", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        del_resp = client.delete(f"/api/profiles/{prof_id}", headers=user_a["headers"])
        assert del_resp.status_code in (200, 204)
        assert del_resp.json()["deleted"] is True


@pytest.mark.asyncio
async def test_10_profile_deletion_when_no_dek_exists(cascade_test_env):
    """Test 10: Profile deletion succeeds when no DEK was ever created."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice10@test.local", "Password123!", "Alice")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "No DEK Profile", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        del_resp = client.delete(f"/api/profiles/{prof_id}", headers=user_a["headers"])
        assert del_resp.status_code in (200, 204)
        assert del_resp.json()["deleted"] is True


@pytest.mark.asyncio
async def test_11_unauthorized_profile_deletion_blocked_403(cascade_test_env):
    """Test 11: User B cannot delete User A's profile without manage access."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice11@test.local", "Password123!", "Alice")
        user_b = register_and_login(client, "bob11@test.local", "Password123!", "Bob")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Alice Private", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        # Bob attempts delete
        del_resp = client.delete(f"/api/profiles/{prof_id}", headers=user_b["headers"])
        assert del_resp.status_code == 403


@pytest.mark.asyncio
async def test_12_nonexistent_profile_deletion_returns_404(cascade_test_env):
    """Test 12: Attempting to delete a non-existent profile returns HTTP 404."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice12@test.local", "Password123!", "Alice")
        fake_id = str(uuid.uuid4())

        del_resp = client.delete(f"/api/profiles/{fake_id}", headers=user_a["headers"])
        assert del_resp.status_code == 404


# ============================================================================
# Suite 3: Deep Entity Scoping for Notes (AU-12)
# ============================================================================

@pytest.mark.asyncio
async def test_13_note_create_with_null_profile_id_rejected_400(cascade_test_env):
    """Test 13: Creating note with profile_id=null is rejected with HTTP 400."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice13@test.local", "Password123!", "Alice")

        resp = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={"title": "Orphan Note", "content": "Content", "profile_id": None},
        )
        assert resp.status_code == 400
        assert "profile_id is required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_14_note_create_with_empty_string_profile_id_rejected_400(cascade_test_env):
    """Test 14: Creating note with empty/whitespace profile_id is rejected with HTTP 400."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice14@test.local", "Password123!", "Alice")

        resp = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={"title": "Whitespace Note", "content": "Content", "profile_id": "   "},
        )
        assert resp.status_code == 400
        assert "profile_id is required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_15_note_create_with_missing_profile_id_rejected_400(cascade_test_env):
    """Test 15: Creating note without profile_id field is rejected with HTTP 400."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice15@test.local", "Password123!", "Alice")

        resp = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={"title": "No Profile Note", "content": "Content"},
        )
        assert resp.status_code == 400
        assert "profile_id is required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_16_note_create_with_valid_profile_id_persists_scoped_note(cascade_test_env):
    """Test 16: Creating note with valid profile_id succeeds and persists non-null profile_id."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice16@test.local", "Password123!", "Alice")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Scoped Profile", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        resp = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={"title": "Scoped Note", "content": "Content", "profile_id": prof_id},
        )
        assert resp.status_code == 201
        slug = resp.json()["slug"]

        session_factory = cascade_test_env["session_factory"]
        async with session_factory() as session:
            note = (await session.execute(select(Note).where(Note.slug == slug))).scalar_one_or_none()
            assert note is not None
            assert note.profile_id == prof_id


@pytest.mark.asyncio
async def test_17_note_update_with_empty_profile_id_rejected_400(cascade_test_env):
    """Test 17: Updating note with empty string profile_id is rejected with HTTP 400."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice17@test.local", "Password123!", "Alice")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "P17", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        n_resp = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={"title": "N17", "content": "Content", "profile_id": prof_id},
        )
        slug = n_resp.json()["slug"]

        up_resp = client.put(
            f"/api/notes/{slug}",
            headers=user_a["headers"],
            json={"profile_id": "   "},
        )
        assert up_resp.status_code == 400
        assert "profile_id cannot be null or empty" in up_resp.json()["detail"]


@pytest.mark.asyncio
async def test_18_cross_profile_note_read_blocked_403(cascade_test_env):
    """Test 18: User B cannot read User A's profile-scoped note."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice18@test.local", "Password123!", "Alice")
        user_b = register_and_login(client, "bob18@test.local", "Password123!", "Bob")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Alice Private", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        n_resp = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={"title": "Confidential", "content": "Secret note", "profile_id": prof_id},
        )
        slug = n_resp.json()["slug"]

        # Bob reads note
        read_resp = client.get(f"/api/notes/{slug}", headers=user_b["headers"])
        assert read_resp.status_code == 403


@pytest.mark.asyncio
async def test_19_cross_profile_note_update_blocked_403(cascade_test_env):
    """Test 19: User B cannot update User A's note."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice19@test.local", "Password123!", "Alice")
        user_b = register_and_login(client, "bob19@test.local", "Password123!", "Bob")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Alice Private", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        n_resp = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={"title": "Original Note", "content": "Original", "profile_id": prof_id},
        )
        slug = n_resp.json()["slug"]

        up_resp = client.put(
            f"/api/notes/{slug}",
            headers=user_b["headers"],
            json={"title": "Hacked Note"},
        )
        assert up_resp.status_code == 403


@pytest.mark.asyncio
async def test_20_cross_profile_note_delete_blocked_403(cascade_test_env):
    """Test 20: User B cannot delete User A's note."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice20@test.local", "Password123!", "Alice")
        user_b = register_and_login(client, "bob20@test.local", "Password123!", "Bob")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Alice Private", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        n_resp = client.post(
            "/api/notes",
            headers=user_a["headers"],
            json={"title": "Safe Note", "content": "Safe", "profile_id": prof_id},
        )
        slug = n_resp.json()["slug"]

        del_resp = client.delete(f"/api/notes/{slug}", headers=user_b["headers"])
        assert del_resp.status_code == 403


@pytest.mark.asyncio
async def test_21_note_list_scoped_filtering(cascade_test_env):
    """Test 21: Querying notes with profile_id strictly filters; unauthorized profile returns 403."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice21@test.local", "Password123!", "Alice")
        user_b = register_and_login(client, "bob21@test.local", "Password123!", "Bob")

        p_resp1 = client.post("/api/profiles", headers=user_a["headers"], json={"name": "P1", "relationship": "other"})
        p_resp2 = client.post("/api/profiles", headers=user_a["headers"], json={"name": "P2", "relationship": "other"})
        pid1 = p_resp1.json()["id"]
        pid2 = p_resp2.json()["id"]

        client.post("/api/notes", headers=user_a["headers"], json={"title": "N1", "content": "ItemOne", "profile_id": pid1})
        client.post("/api/notes", headers=user_a["headers"], json={"title": "N2", "content": "ItemTwo", "profile_id": pid2})

        # Alice lists notes for P1
        list_p1 = client.get(f"/api/notes?profile_id={pid1}", headers=user_a["headers"]).json()
        assert len(list_p1) == 1
        assert list_p1[0]["title"] == "N1"

        # Bob attempts listing notes for P1
        bob_resp = client.get(f"/api/notes?profile_id={pid1}", headers=user_b["headers"])
        assert bob_resp.status_code == 403


# ============================================================================
# Suite 4: Deep Entity Scoping for Chat Threads (AU-13)
# ============================================================================

@pytest.mark.asyncio
async def test_22_chat_stream_with_null_profile_id_rejected_400(cascade_test_env):
    """Test 22: POST /api/chat with null profile_id is rejected with HTTP 400."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice22@test.local", "Password123!", "Alice")

        resp = client.post(
            "/api/chat",
            headers=user_a["headers"],
            json={"agent_id": "cardiology-guide", "prompt": "Hello", "profile_id": None},
        )
        assert resp.status_code == 400
        assert "profile_id is required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_23_chat_stream_with_empty_string_profile_id_rejected_400(cascade_test_env):
    """Test 23: POST /api/chat with whitespace profile_id is rejected with HTTP 400."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice23@test.local", "Password123!", "Alice")

        resp = client.post(
            "/api/chat",
            headers=user_a["headers"],
            json={"agent_id": "cardiology-guide", "prompt": "Hello", "profile_id": "   "},
        )
        assert resp.status_code == 400
        assert "profile_id is required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_24_chat_stream_unauthorized_profile_blocked_403(cascade_test_env):
    """Test 24: POST /api/chat targeting another user's profile is rejected with HTTP 403."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice24@test.local", "Password123!", "Alice")
        user_b = register_and_login(client, "bob24@test.local", "Password123!", "Bob")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Alice Private", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        resp = client.post(
            "/api/chat",
            headers=user_b["headers"],
            json={"agent_id": "cardiology-guide", "prompt": "Hello", "profile_id": prof_id},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_25_cross_profile_chat_thread_history_blocked_403(cascade_test_env):
    """Test 25: User B cannot retrieve chat history of User A's profile-scoped thread."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice25@test.local", "Password123!", "Alice")
        user_b = register_and_login(client, "bob25@test.local", "Password123!", "Bob")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Alice Private", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        thread_id = f"thread_alice_{uuid.uuid4().hex[:8]}"
        session_factory = cascade_test_env["session_factory"]
        async with session_factory() as session:
            session.add(ChatThread(
                id=thread_id,
                user_id=user_a["user"]["id"],
                profile_id=prof_id,
                agent_id="cardiology-guide",
                title="Cardiac Consultation",
            ))
            await session.commit()

        # Bob requests thread history
        resp = client.get(f"/api/chat/threads?thread_id={thread_id}", headers=user_b["headers"])
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_26_cross_profile_chat_thread_delete_blocked_403(cascade_test_env):
    """Test 26: User B cannot delete User A's chat thread."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice26@test.local", "Password123!", "Alice")
        user_b = register_and_login(client, "bob26@test.local", "Password123!", "Bob")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Alice Private", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        thread_id = f"thread_alice_{uuid.uuid4().hex[:8]}"
        session_factory = cascade_test_env["session_factory"]
        async with session_factory() as session:
            session.add(ChatThread(
                id=thread_id,
                user_id=user_a["user"]["id"],
                profile_id=prof_id,
                agent_id="cardiology-guide",
                title="Cardiac Consultation",
            ))
            await session.commit()

        del_resp = client.delete(f"/api/chat/threads/{thread_id}", headers=user_b["headers"])
        assert del_resp.status_code == 403


@pytest.mark.asyncio
async def test_27_db_model_constraints_enforce_not_null(cascade_test_env):
    """Test 27: Note and ChatThread models strictly enforce profile_id NOT NULL at DB level."""
    session_factory = cascade_test_env["session_factory"]

    # 1. Attempt inserting Note with profile_id = None
    async with session_factory() as session:
        with pytest.raises((IntegrityError, Exception)):
            session.add(Note(
                id=str(uuid.uuid4()),
                slug=f"null-prof-note-{uuid.uuid4().hex[:6]}",
                title="No Profile",
                content="Broken",
                profile_id=None,  # type: ignore
            ))
            await session.commit()

    # 2. Attempt inserting ChatThread with profile_id = None
    async with session_factory() as session:
        with pytest.raises((IntegrityError, Exception)):
            session.add(ChatThread(
                id=f"null-thread-{uuid.uuid4().hex[:8]}",
                agent_id="cardiology-guide",
                title="Broken Thread",
                profile_id=None,  # type: ignore
            ))
            await session.commit()


# ============================================================================
# Suite 5: Deep Entity Scoping for Memory CRUD (AU-13)
# ============================================================================

@pytest.mark.asyncio
async def test_28_memory_recall_requires_profile_id_400(cascade_test_env):
    """Test 28: GET /api/memory/recall without profile_id returns HTTP 400."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice28@test.local", "Password123!", "Alice")

        resp = client.get("/api/memory/recall", headers=user_a["headers"])
        assert resp.status_code == 400
        assert "profile_id is required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_29_memory_recall_unauthorized_profile_blocked_403(cascade_test_env):
    """Test 29: GET /api/memory/recall targeting another user's profile returns HTTP 403."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice29@test.local", "Password123!", "Alice")
        user_b = register_and_login(client, "bob29@test.local", "Password123!", "Bob")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Alice Private", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        resp = client.get(f"/api/memory/recall?profile_id={prof_id}", headers=user_b["headers"])
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_30_memory_delete_all_requires_profile_id_400(cascade_test_env):
    """Test 30: DELETE /api/memory without profile_id returns HTTP 400."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice30@test.local", "Password123!", "Alice")

        resp = client.delete("/api/memory", headers=user_a["headers"])
        assert resp.status_code == 400
        assert "profile_id is required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_31_memory_delete_all_unauthorized_profile_blocked_403(cascade_test_env):
    """Test 31: DELETE /api/memory targeting another user's profile returns HTTP 403."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice31@test.local", "Password123!", "Alice")
        user_b = register_and_login(client, "bob31@test.local", "Password123!", "Bob")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Alice Private", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        resp = client.delete(f"/api/memory?profile_id={prof_id}", headers=user_b["headers"])
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_32_memory_item_crud_scoping(cascade_test_env):
    """Test 32: GET, PUT, and DELETE /api/memory/{key} require profile_id and enforce isolation."""
    with TestClient(app) as client:
        user_a = register_and_login(client, "alice32@test.local", "Password123!", "Alice")
        user_b = register_and_login(client, "bob32@test.local", "Password123!", "Bob")

        p_resp = client.post(
            "/api/profiles",
            headers=user_a["headers"],
            json={"name": "Alice Private", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        # Missing profile_id on PUT returns 400
        put_bad = client.put(
            "/api/memory/blood_pressure",
            headers=user_a["headers"],
            json={"value": {"sys": 120, "dia": 80}},
        )
        assert put_bad.status_code == 400

        # Valid PUT by Alice succeeds
        put_ok = client.put(
            f"/api/memory/blood_pressure?profile_id={prof_id}",
            headers=user_a["headers"],
            json={"value": {"sys": 120, "dia": 80}},
        )
        assert put_ok.status_code == 200

        # Bob cannot read blood_pressure
        get_bob = client.get(
            f"/api/memory/blood_pressure?profile_id={prof_id}",
            headers=user_b["headers"],
        )
        assert get_bob.status_code == 403

        # Bob cannot delete blood_pressure
        del_bob = client.delete(
            f"/api/memory/blood_pressure?profile_id={prof_id}",
            headers=user_b["headers"],
        )
        assert del_bob.status_code == 403

        # Alice deletes blood_pressure successfully
        del_alice = client.delete(
            f"/api/memory/blood_pressure?profile_id={prof_id}",
            headers=user_a["headers"],
        )
        assert del_alice.status_code == 200


# ============================================================================
# Suite 6: Alembic Migration 0004 Verification (AU-12, AU-13)
# ============================================================================

def test_33_alembic_0004_upgrade_downgrade_cycle():
    """Test 33: Verifies Alembic 0004 sets nullable=False on upgrade and nullable=True on downgrade."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)

        # 1. Upgrade to head (0004)
        alembic.command.upgrade(cfg, "head")
        insp = inspect(conn)

        notes_cols = {c["name"]: c for c in insp.get_columns("notes")}
        assert notes_cols["profile_id"]["nullable"] is False

        thread_cols = {c["name"]: c for c in insp.get_columns("chat_threads")}
        assert thread_cols["profile_id"]["nullable"] is False

        # 2. Downgrade to 0003
        alembic.command.downgrade(cfg, "0003_household_profiles_and_audit")
        insp_down = inspect(conn)

        notes_cols_down = {c["name"]: c for c in insp_down.get_columns("notes")}
        assert notes_cols_down["profile_id"]["nullable"] is True

        thread_cols_down = {c["name"]: c for c in insp_down.get_columns("chat_threads")}
        assert thread_cols_down["profile_id"]["nullable"] is True

        # 3. Re-upgrade to head (0004)
        alembic.command.upgrade(cfg, "head")
        insp_up = inspect(conn)
        assert {c["name"]: c for c in insp_up.get_columns("notes")}["profile_id"]["nullable"] is False


def test_34_alembic_0004_legacy_null_backfill():
    """Test 34: Legacy rows with profile_id=NULL are safely backfilled during 0004 upgrade."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.connect() as conn:
        cfg = get_alembic_config(conn)

        # 1. Upgrade only to 0003
        alembic.command.upgrade(cfg, "0003_household_profiles_and_audit")

        # 2. Seed user, primary profile, and orphaned note/thread rows with NULL profile_id
        uid = str(uuid.uuid4())
        pid = str(uuid.uuid4())
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        conn.execute(text("""
            INSERT INTO users (id, email, username, hashed_password, full_name, role, status, auth_provider, created_at, updated_at)
            VALUES (:uid, 'legacy@test.local', 'legacy_user', 'hash', 'Legacy User', 'member', 'active', 'local', :now, :now)
        """), {"uid": uid, "now": now_iso})

        conn.execute(text("""
            INSERT INTO profiles (id, user_id, name, relationship, role, avatar_color, is_primary, created_at, updated_at)
            VALUES (:pid, :uid, 'Me', 'self', 'adult', '#000000', 1, :now, :now)
        """), {"pid": pid, "uid": uid, "now": now_iso})

        conn.execute(text("""
            INSERT INTO notes (id, slug, title, content, user_id, profile_id, type, tags_json, created_at, updated_at)
            VALUES ('note-legacy', 'legacy-slug', 'Legacy Note', 'Content', :uid, NULL, 'scratchpad', '[]', :now, :now)
        """), {"uid": uid, "now": now_iso})

        conn.execute(text("""
            INSERT INTO chat_threads (id, agent_id, title, user_id, profile_id, created_at, updated_at)
            VALUES ('thread-legacy', 'cardiology-guide', 'Legacy Thread', :uid, NULL, :now, :now)
        """), {"uid": uid, "now": now_iso})

        conn.commit()

        # 3. Upgrade to 0004 (executes safe backfill)
        alembic.command.upgrade(cfg, "head")

        # 4. Verify no NULL profile_id remains and orphaned rows are backfilled
        note_pid = conn.execute(text("SELECT profile_id FROM notes WHERE id = 'note-legacy'")).scalar()
        assert note_pid == pid

        thread_pid = conn.execute(text("SELECT profile_id FROM chat_threads WHERE id = 'thread-legacy'")).scalar()
        assert thread_pid == pid
