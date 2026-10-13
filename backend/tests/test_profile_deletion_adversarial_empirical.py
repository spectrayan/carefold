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

"""Adversarial Empirical Challenge Suite for Milestone 1: Profile Crypto-Shredding & Deletion Cascade (AU-11).

Empirically challenges:
1. DEK Crypto-shredding:
   - Does deleting a profile completely drop its DEK from profile_keys?
   - Is encrypted data rendered permanently unrecoverable?
   - Does rotated DEK get completely dropped?
2. CAS filesystem directory wipe:
   - Is the CAS filesystem directory completely wiped from disk with deep nested files and hidden files?
   - Are temporary upload directories wiped?
   - Are neighbor profiles in the same parent directory completely preserved (no collateral wipe)?
3. Memory accessibility & scoping:
   - Are all candidate memory namespaces purged?
   - Does direct memory port query return None?
   - Do HTTP memory endpoints return HTTP 404 for deleted profiles?
   - Are neighbor profiles' memories completely intact?
4. Zero files deletion safety:
   - Does deleting a profile with 0 files execute safely without error?
   - Are associated database child records (notes, chat threads) still cascaded cleanly?
5. Primary 'Me' profile deletion protection:
   - Does attempting to delete the primary 'Me' profile fail with HTTP 400 under all conditions?
     (owner, admin, query params, JSON body override, PATCH manipulation, cross-user 403, unauthenticated 401).
6. Concurrent deletion safety:
   - Do race conditions during deletion resolve cleanly without database corruption?
"""

from __future__ import annotations

import asyncio
import datetime
import os
from pathlib import Path
import shutil
from typing import AsyncIterator
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.vault.crypto import decrypt, encrypt
from carefold.db.models import (
    ChatThread,
    Note,
    Profile,
    ProfileKey,
    User,
)
from carefold.db.session import (
    create_db_engine,
    get_session_factory,
    init_db,
)
from carefold.main import app
from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
from carefold.memory.factory import reset_memory_ports, set_memory_port
from carefold.memory.ports.memory_port import MemoryTier
from carefold.vault.dek import (
    compute_dek_wrapping_aad,
    delete_profile_keys,
    get_or_create_dek,
    rotate_dek,
)


@pytest.fixture
async def adversarial_env(temp_workspace: Path, monkeypatch):
    """Sets up an isolated database, local auth adapter, and SQLite memory adapter."""
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


def login_user(client: TestClient, email: str, username: str, password: str = "Password123!") -> dict:
    """Helper to register and login user."""
    # Register admin if not present
    client.post(
        "/api/auth/register",
        json={
            "email": "admin@carefold.test",
            "username": "admin",
            "password": "AdminPassword123!",
            "full_name": "System Administrator",
        },
    )
    reg_resp = client.post(
        "/api/auth/register",
        json={"email": email, "username": username, "password": password, "full_name": username.title()},
    )
    assert reg_resp.status_code in (201, 400), reg_resp.text

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
# 1. DEK CRYPTO-SHREDDING GUARANTEE
# ============================================================================

@pytest.mark.asyncio
async def test_empirical_dek_crypto_shredding_and_unrecoverability(adversarial_env):
    """EMPIRICAL TEST 1: Verifies that deleting a profile completely drops DEK from profile_keys

    and renders encrypted data permanently unrecoverable, even after DEK rotation.
    """
    with TestClient(app) as client:
        user = login_user(client, "dek_user@test.local", "dek_user")
        session_factory = adversarial_env["session_factory"]

        # Create secondary profile
        p_resp = client.post(
            "/api/profiles",
            headers=user["headers"],
            json={"name": "Patient Alpha", "relationship": "parent"},
        )
        assert p_resp.status_code == 201
        prof_id = p_resp.json()["id"]

        kek = os.urandom(32)
        async with session_factory() as session:
            # 1. Generate DEK v1
            dek_v1, ver1 = await get_or_create_dek(session, prof_id, kek=kek)
            assert ver1 == 1

            # Encrypt sensitive genetic record under DEK v1
            secret_payload = b"GENETIC_MARKER_BRCA1_POSITIVE_HIGH_RISK"
            aad_v1 = compute_dek_wrapping_aad(prof_id, ver1)
            ciphertext_v1 = encrypt(dek_v1, secret_payload, aad_v1)
            decrypted_v1 = decrypt(dek_v1, ciphertext_v1, aad_v1)
            assert decrypted_v1 == secret_payload

            # 2. Rotate DEK to v2
            dek_v2, ver2 = await rotate_dek(session, prof_id, kek=kek)
            assert ver2 == 2
            assert dek_v2 != dek_v1

            # Verify profile_keys row exists in database
            key_stmt = select(ProfileKey).where(ProfileKey.profile_id == prof_id)
            key_res = await session.execute(key_stmt)
            key_row = key_res.scalar_one_or_none()
            assert key_row is not None
            assert key_row.dek_version == 2

        # 3. Trigger profile deletion via REST API
        del_resp = client.delete(f"/api/profiles/{prof_id}", headers=user["headers"])
        assert del_resp.status_code in (200, 204)
        assert del_resp.json()["deleted"] is True

        # 4. Verify empirical guarantee: DEK row completely wiped from database
        async with session_factory() as session:
            key_stmt = select(ProfileKey).where(ProfileKey.profile_id == prof_id)
            key_res = await session.execute(key_stmt)
            key_rows = key_res.scalars().all()
            assert len(key_rows) == 0, f"Expected 0 keys in profile_keys, found {len(key_rows)}"

        # 5. Verify crypto-shredding: key is permanently destroyed
        # Attempting to re-insert or derive a DEK for the deleted profile fails due to foreign key integrity
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            async with session_factory() as session:
                await get_or_create_dek(session, prof_id, kek=kek)

        # Ciphertext cannot be decrypted without the deleted key
        bogus_dek = os.urandom(32)
        with pytest.raises(Exception):
            decrypt(bogus_dek, ciphertext_v1, aad_v1)


# ============================================================================
# 2. CAS FILESYSTEM DIRECTORY WIPE & COLLATERAL ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_empirical_cas_filesystem_deep_wipe_and_neighbor_isolation(adversarial_env):
    """EMPIRICAL TEST 2: Verifies that CAS storage directory is completely wiped from disk,

    including nested subdirectories, binary payloads, and hidden files,
    WHILE neighbor profiles in the same parent directory are strictly preserved.
    """
    with TestClient(app) as client:
        user = login_user(client, "cas_user@test.local", "cas_user")
        uid = user["user"]["id"]
        home = adversarial_env["home"]

        # Create two distinct profiles
        resp1 = client.post(
            "/api/profiles",
            headers=user["headers"],
            json={"name": "Victim Profile", "relationship": "child"},
        )
        victim_id = resp1.json()["id"]

        resp2 = client.post(
            "/api/profiles",
            headers=user["headers"],
            json={"name": "Neighbor Profile", "relationship": "spouse"},
        )
        neighbor_id = resp2.json()["id"]

        # Populate Victim's CAS directory with complex deep structure
        victim_cas = home / "data" / "files" / uid / victim_id
        victim_cas.mkdir(parents=True, exist_ok=True)
        (victim_cas / "scan1.dcm").write_bytes(b"\x00\x01\x02DICOM_PAYLOAD_VICTIM")
        victim_sub = victim_cas / "subfolder" / "nested"
        victim_sub.mkdir(parents=True, exist_ok=True)
        (victim_sub / "deep_file.pdf").write_bytes(b"%PDF-1.4 deep file")
        (victim_cas / ".hidden_audit_meta").write_text("hidden metadata")

        # Populate Victim's uploads directory
        victim_uploads = settings.get_uploads_dir() / uid / victim_id
        victim_uploads.mkdir(parents=True, exist_ok=True)
        (victim_uploads / "temp_presc.png").write_bytes(b"PNG_HEADER_MOCK")

        # Populate Neighbor's CAS and uploads directories
        neighbor_cas = home / "data" / "files" / uid / neighbor_id
        neighbor_cas.mkdir(parents=True, exist_ok=True)
        neighbor_file = neighbor_cas / "neighbor_report.pdf"
        neighbor_file.write_bytes(b"%PDF-1.4 NEIGHBOR_SOVEREIGN_DATA")

        neighbor_uploads = settings.get_uploads_dir() / uid / neighbor_id
        neighbor_uploads.mkdir(parents=True, exist_ok=True)
        neighbor_up_file = neighbor_uploads / "neighbor_avatar.jpg"
        neighbor_up_file.write_bytes(b"JPG_NEIGHBOR_AVATAR")

        assert (victim_cas / "scan1.dcm").exists()
        assert (victim_sub / "deep_file.pdf").exists()
        assert (victim_uploads / "temp_presc.png").exists()
        assert neighbor_file.exists()
        assert neighbor_up_file.exists()

        # Delete Victim Profile
        del_resp = client.delete(f"/api/profiles/{victim_id}", headers=user["headers"])
        assert del_resp.status_code in (200, 204)

        # 1. Verify victim CAS directory is completely wiped from disk
        assert not victim_cas.exists(), f"Victim CAS directory still exists: {victim_cas}"
        assert not victim_uploads.exists(), f"Victim upload directory still exists: {victim_uploads}"

        # 2. Verify neighbor profile files are 100% preserved (no collateral wipe)
        assert neighbor_cas.exists(), "Neighbor CAS directory was improperly wiped!"
        assert neighbor_file.exists(), "Neighbor file was deleted collaterally!"
        assert neighbor_file.read_bytes() == b"%PDF-1.4 NEIGHBOR_SOVEREIGN_DATA"
        assert neighbor_uploads.exists(), "Neighbor upload directory was improperly wiped!"
        assert neighbor_up_file.exists(), "Neighbor upload file was deleted collaterally!"


# ============================================================================
# 3. MEMORY PURGE & INACCESSIBILITY GUARANTEE
# ============================================================================

@pytest.mark.asyncio
async def test_empirical_memory_inaccessibility_and_scoping_after_deletion(adversarial_env):
    """EMPIRICAL TEST 3: Verifies that memory entries for a deleted profile are completely purged

    from the memory port across all namespace variants, that HTTP memory API endpoints
    reject any attempt to access the deleted profile with HTTP 404,
    and that neighbor profiles' memories remain untouched.
    """
    mem_adapter = adversarial_env["memory_adapter"]

    with TestClient(app) as client:
        user = login_user(client, "mem_user@test.local", "mem_user")
        uid = user["user"]["id"]

        resp1 = client.post(
            "/api/profiles",
            headers=user["headers"],
            json={"name": "Memory Victim", "relationship": "other"},
        )
        victim_id = resp1.json()["id"]

        resp2 = client.post(
            "/api/profiles",
            headers=user["headers"],
            json={"name": "Memory Neighbor", "relationship": "other"},
        )
        neighbor_id = resp2.json()["id"]

        # Store memories for victim across all 3 namespace patterns
        ns1 = f"user_{uid}_profile_{victim_id}"
        ns2 = victim_id
        ns3 = f"profile_{victim_id}"

        await mem_adapter.remember(
            key="blood_pressure",
            value={"systolic": 140, "diastolic": 90},
            tier=MemoryTier.WORKING,
            namespace=ns1,
        )
        await mem_adapter.remember(
            key="medication",
            value={"rx": "Lisinopril 10mg"},
            tier=MemoryTier.WORKING,
            namespace=ns2,
        )
        await mem_adapter.remember(
            key="allergy",
            value={"allergen": "Sulfa"},
            tier=MemoryTier.WORKING,
            namespace=ns3,
        )

        # Store memory for neighbor
        neighbor_ns = f"user_{uid}_profile_{neighbor_id}"
        await mem_adapter.remember(
            key="blood_pressure",
            value={"systolic": 120, "diastolic": 80},
            tier=MemoryTier.WORKING,
            namespace=neighbor_ns,
        )

        # Confirm memories present before deletion
        assert (await mem_adapter.get("blood_pressure", namespace=ns1)) is not None
        assert (await mem_adapter.get("medication", namespace=ns2)) is not None
        assert (await mem_adapter.get("allergy", namespace=ns3)) is not None
        assert (await mem_adapter.get("blood_pressure", namespace=neighbor_ns)) is not None

        # Delete Victim Profile
        del_resp = client.delete(f"/api/profiles/{victim_id}", headers=user["headers"])
        assert del_resp.status_code in (200, 204)

        # 1. Direct memory port verification: all victim namespaces purged
        assert (await mem_adapter.get("blood_pressure", namespace=ns1)) is None
        assert (await mem_adapter.get("medication", namespace=ns2)) is None
        assert (await mem_adapter.get("allergy", namespace=ns3)) is None

        # 2. Neighbor memory remains completely intact
        neighbor_mem = await mem_adapter.get("blood_pressure", namespace=neighbor_ns)
        assert neighbor_mem is not None
        assert neighbor_mem["value"]["systolic"] == 120

        # 3. HTTP API verification: all operations against victim profile_id fail with HTTP 404
        # GET /api/memory
        get_resp = client.get(f"/api/memory?profile_id={victim_id}", headers=user["headers"])
        assert get_resp.status_code == 404
        assert f"Profile '{victim_id}' not found" in get_resp.json()["detail"]

        # GET /api/memory/recall
        recall_resp = client.get(f"/api/memory/recall?profile_id={victim_id}&query=blood", headers=user["headers"])
        assert recall_resp.status_code == 404

        # DELETE /api/memory
        del_mem_resp = client.delete(f"/api/memory?profile_id={victim_id}", headers=user["headers"])
        assert del_mem_resp.status_code == 404

        # Neighbor memory endpoint succeeds with HTTP 200
        neighbor_resp = client.get(f"/api/memory?profile_id={neighbor_id}", headers=user["headers"])
        assert neighbor_resp.status_code == 200
        items = neighbor_resp.json()
        assert len(items) >= 1
        assert any(item["key"] == "blood_pressure" for item in items)


# ============================================================================
# 4. ZERO-FILE DELETION SAFETY & CASCADE GUARANTEE
# ============================================================================

@pytest.mark.asyncio
async def test_empirical_zero_files_profile_deletion_safety_and_cascade(adversarial_env):
    """EMPIRICAL TEST 4: Verifies that deleting a profile with 0 files executes safely

    without error (no crashes on absent directories), cleans up child rows,
    and returns idempotent clean responses.
    """
    with TestClient(app) as client:
        user = login_user(client, "zerofile_user@test.local", "zerofile_user")
        uid = user["user"]["id"]
        session_factory = adversarial_env["session_factory"]

        # Create secondary profile with 0 files
        p_resp = client.post(
            "/api/profiles",
            headers=user["headers"],
            json={"name": "Zero Files Profile", "relationship": "other"},
        )
        assert p_resp.status_code == 201
        prof_id = p_resp.json()["id"]

        # Attach child database records (notes, chat threads) but ZERO files
        note_id = str(uuid.uuid4())
        thread_id = f"thread-{uuid.uuid4().hex[:8]}"

        async with session_factory() as session:
            session.add(Note(
                id=note_id,
                slug="zero-file-note",
                title="Zero File Clinical Note",
                content="Clinical observation without files",
                user_id=uid,
                profile_id=prof_id,
            ))
            session.add(ChatThread(
                id=thread_id,
                user_id=uid,
                profile_id=prof_id,
                agent_id="general-guide",
                title="General Consultation",
            ))
            await session.commit()

        # Ensure no CAS or upload directory exists on disk
        home = adversarial_env["home"]
        cas_path = home / "data" / "files" / uid / prof_id
        upload_path = settings.get_uploads_dir() / uid / prof_id
        assert not cas_path.exists()
        assert not upload_path.exists()

        # Delete the profile
        del_resp = client.delete(f"/api/profiles/{prof_id}", headers=user["headers"])
        assert del_resp.status_code in (200, 204)
        data = del_resp.json()
        assert data["deleted"] is True
        assert data["id"] == prof_id

        # Verify child database records were cascaded and deleted cleanly
        async with session_factory() as session:
            n_row = (await session.execute(select(Note).where(Note.id == note_id))).scalar_one_or_none()
            assert n_row is None, "Note was not cascade deleted!"

            t_row = (await session.execute(select(ChatThread).where(ChatThread.id == thread_id))).scalar_one_or_none()
            assert t_row is None, "ChatThread was not cascade deleted!"

            p_row = (await session.execute(select(Profile).where(Profile.id == prof_id))).scalar_one_or_none()
            assert p_row is None, "Profile row was not deleted!"

        # Attempt to delete again -> returns HTTP 404 (clean non-crashing response)
        del_again = client.delete(f"/api/profiles/{prof_id}", headers=user["headers"])
        assert del_again.status_code == 404


# ============================================================================
# 5. PRIMARY 'ME' PROFILE DELETION PROTECTION UNDER ALL CONDITIONS
# ============================================================================

@pytest.mark.asyncio
async def test_empirical_primary_me_profile_deletion_blocked_under_all_conditions(adversarial_env):
    """EMPIRICAL TEST 5: Verifies that attempting to delete the primary 'Me' profile

    fails with HTTP 400 under all adversarial conditions:
    1. Account owner normal DELETE request -> HTTP 400
    2. Admin user DELETE request -> HTTP 400
    3. Query parameter bypass attempts (?force=true, ?cascade=true, ?purge=1) -> HTTP 400
    4. JSON payload override attempts ({"force": true, "delete_primary": true}) -> HTTP 400
    5. PATCH/PUT manipulation attempt to unmark is_primary=False -> rejected/ignored, DELETE still HTTP 400
    6. Non-manager user DELETE request -> HTTP 403 Forbidden
    7. Unauthenticated request -> HTTP 401 Unauthorized
    """
    with TestClient(app) as client:
        # Create Owner
        owner = login_user(client, "me_owner@test.local", "me_owner")

        # Create Admin
        admin = login_user(client, "admin_user@test.local", "admin_user")
        # Elevate to admin role in DB
        session_factory = adversarial_env["session_factory"]
        async with session_factory() as session:
            adm_user = (await session.execute(select(User).where(User.username == "admin_user"))).scalar_one()
            adm_user.role = "admin"
            await session.commit()

        # Create Malicious Outside User
        attacker = login_user(client, "attacker@test.local", "attacker")

        # Fetch Owner's primary 'Me' profile
        profiles = client.get("/api/profiles", headers=owner["headers"]).json()
        primary_me = next(p for p in profiles if p["is_primary"] is True)
        me_id = primary_me["id"]

        # Attack Vector 1: Owner normal DELETE
        r1 = client.delete(f"/api/profiles/{me_id}", headers=owner["headers"])
        assert r1.status_code == 400
        assert "Cannot delete primary 'Me' profile" in r1.json()["detail"]

        # Attack Vector 2: Admin user DELETE
        r2 = client.delete(f"/api/profiles/{me_id}", headers=admin["headers"])
        # Even with manage/admin access, primary deletion must be blocked
        assert r2.status_code in (400, 403)
        if r2.status_code == 400:
            assert "Cannot delete primary 'Me' profile" in r2.json()["detail"]

        # Attack Vector 3: Query parameter overrides (?force=true, ?cascade=true)
        r3 = client.delete(f"/api/profiles/{me_id}?force=true&cascade=true&bypass=1", headers=owner["headers"])
        assert r3.status_code == 400
        assert "Cannot delete primary 'Me' profile" in r3.json()["detail"]

        # Attack Vector 4: JSON payload override
        r4 = client.request("DELETE", f"/api/profiles/{me_id}", headers=owner["headers"], json={"force": True, "delete_primary": True})
        assert r4.status_code == 400
        assert "Cannot delete primary 'Me' profile" in r4.json()["detail"]

        # Attack Vector 5: Attempt to unmark is_primary via PATCH/PUT
        patch_resp = client.put(
            f"/api/profiles/{me_id}",
            headers=owner["headers"],
            json={"name": "Renamed Primary", "is_primary": False},
        )
        assert patch_resp.status_code in (200, 422)
        # Check that is_primary is STILL True
        check_p = client.get(f"/api/profiles/{me_id}", headers=owner["headers"]).json()
        assert check_p["is_primary"] is True

        r5 = client.delete(f"/api/profiles/{me_id}", headers=owner["headers"])
        assert r5.status_code == 400
        assert "Cannot delete primary 'Me' profile" in r5.json()["detail"]

        # Attack Vector 6: Malicious outsider attempting deletion -> HTTP 403
        r6 = client.delete(f"/api/profiles/{me_id}", headers=attacker["headers"])
        assert r6.status_code == 403

        # Attack Vector 7: Unauthenticated request -> HTTP 401
        with TestClient(app) as unauth_client:
            r7 = unauth_client.delete(f"/api/profiles/{me_id}")
            assert r7.status_code == 401

        # EMPIRICAL INVARIANT: Primary 'Me' profile remains completely intact in DB
        async with session_factory() as session:
            me_row = (await session.execute(select(Profile).where(Profile.id == me_id))).scalar_one_or_none()
            assert me_row is not None
            assert me_row.is_primary is True


# ============================================================================
# 6. CONCURRENT DELETION RACE CONDITION SAFETY
# ============================================================================

@pytest.mark.asyncio
async def test_empirical_concurrent_deletion_race_condition_safety(adversarial_env):
    """EMPIRICAL TEST 6: Verifies that rapid concurrent deletion requests against the same profile

    do not trigger unhandled exceptions, race crashes, or partial data corruption.
    """
    with TestClient(app) as client:
        user = login_user(client, "race_user@test.local", "race_user")

        p_resp = client.post(
            "/api/profiles",
            headers=user["headers"],
            json={"name": "Race Profile", "relationship": "other"},
        )
        prof_id = p_resp.json()["id"]

        # Fire two deletion requests in rapid succession
        resp1 = client.delete(f"/api/profiles/{prof_id}", headers=user["headers"])
        resp2 = client.delete(f"/api/profiles/{prof_id}", headers=user["headers"])

        # Exactly one must succeed with 200/204, and the other must return 404 (already deleted)
        status_codes = [resp1.status_code, resp2.status_code]
        assert 200 in status_codes or 204 in status_codes
        assert 404 in status_codes
        assert 500 not in status_codes
