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

"""Test Harness for
Schema Migrations & Viewer Invites Lifecycle.

Scope:
  1. Pre-existing database with `note` table: migration renames it to `notes` without data loss.
  2. Missing columns in `profiles`: `_run_schema_migrations()` adds `short_name` and `avatar_url` safely.
  3. Unique constraint on `invite_code`: duplicate codes are strictly rejected.
  4. Viewer invite lifecycle: 7-day expiration check, single-use acceptance, expired rejection,
     double-acceptance rejection, revocation, and filtering.
  5. Cascading deletes: deleting a profile deletes all associated viewer invites at ORM and SQLite engine levels.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import AsyncIterator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.base import Base
from carefold.db.models import Note, Profile, ProfileAccess, User, ViewerInvite
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app


# ==============================================================================
# Test Fixtures
# ==============================================================================

@pytest.fixture
async def chal_test_env(temp_workspace: Path, monkeypatch):
    """Sets up an isolated in-memory DB and local SQL auth provider for API probes."""
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
        yield {"session_factory": session_factory, "engine": engine}
    finally:
        app.dependency_overrides.clear()
        reset_auth_port()
        await engine.dispose()


def _register_user(client: TestClient, email: str, name: str) -> dict:
    """Helper to register and login a test user, returning token and auth headers."""
    username = email.split("@")[0].replace(".", "_")
    reg_resp = client.post(
        "/api/auth/register",
        json={"email": email, "username": username, "password": "TestPassword123!", "full_name": name},
    )
    assert reg_resp.status_code in (200, 201), f"Registration failed: {reg_resp.text}"
    login_resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": "TestPassword123!"},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    token = login_resp.json()["token"]
    user_info = login_resp.json()["user"]
    return {"token": token, "user": user_info, "headers": {"Authorization": f"Bearer {token}"}}


# ==============================================================================
# AREA 1: Pre-existing database with 'note' table -> 'notes' without data loss
# ==============================================================================

@pytest.mark.asyncio
async def test_migration_note_to_notes_large_and_diverse_data(tmp_path: Path):
    """Stress-test: Legacy DB with 50 diverse rows in 'note' (unicode, emojis, large markdown,

    tags, legacy columns missing profile_id) is migrated to 'notes' with 0 data loss.
    """
    db_file = tmp_path / "diverse_legacy_carefold.db"

    # 1. Populate legacy SQLite schema directly
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("""
            CREATE TABLE note (
                id VARCHAR(36) PRIMARY KEY,
                type VARCHAR(32) NOT NULL DEFAULT 'scratchpad',
                user_id VARCHAR(36),
                slug VARCHAR(128) NOT NULL,
                title VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
        """)

        # Insert 50 stress rows
        test_rows = []
        for i in range(50):
            nid = f"note-{i:03d}"
            ntype = ["scratchpad", "clinical_prep", "visit_summary", "general", "custom_type"][i % 5]
            uid = f"user-{i % 3:02d}" if i % 2 == 0 else None
            slug = f"slug-note-{i:03d}-{'special_chars_!@#' if i == 7 else 'normal'}"
            title = f"Title {i} - 🏥 Cardiology Prep & 睡眠监测 (Sleep Monitoring) {i}"
            content = f"# Section {i}\nBody content with markdown:\n```json\n{{\"index\": {i}}}\n```\n" + ("x" * 2048)
            tags = f'["tag_{i}", "medical", "emoji_🩺"]'
            ts = f"2026-01-{(i % 28) + 1:02d}T10:00:00Z"
            test_rows.append((nid, ntype, uid, slug, title, content, tags, ts, ts))

        conn.executemany(
            "INSERT INTO note (id, type, user_id, slug, title, content, tags_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            test_rows,
        )
        conn.commit()

    # 2. Run Carefold init_db() migration
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)

    try:
        await init_db(engine)

        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
            # 'note' must be renamed to 'notes'
            assert "notes" in tables, "Table 'notes' must exist after migration"
            assert "note" not in tables, "Legacy table 'note' must no longer exist"

            # Check that missing 'profile_id' column was safely added to 'notes'
            notes_cols = await conn.run_sync(lambda sc: [c["name"] for c in inspect(sc).get_columns("notes")])
            assert "profile_id" in notes_cols, "'profile_id' column must have been added to 'notes'"

            # Verify count and exact data integrity across all 50 rows
            res = await conn.execute(text("SELECT id, type, user_id, slug, title, content, tags_json FROM notes ORDER BY id ASC;"))
            rows = res.fetchall()
            assert len(rows) == 50, f"Expected 50 rows in notes, got {len(rows)}"

            for i, r in enumerate(rows):
                expected = test_rows[i]
                assert r[0] == expected[0], f"Row {i} id mismatch: {r[0]} vs {expected[0]}"
                assert r[1] == expected[1], f"Row {i} type mismatch: {r[1]} vs {expected[1]}"
                assert r[2] == expected[2], f"Row {i} user_id mismatch: {r[2]} vs {expected[2]}"
                assert r[3] == expected[3], f"Row {i} slug mismatch: {r[3]} vs {expected[3]}"
                assert r[4] == expected[4], f"Row {i} title mismatch: {r[4]} vs {expected[4]}"
                assert r[5] == expected[5], f"Row {i} content mismatch"
                assert r[6] == expected[6], f"Row {i} tags mismatch"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_collision_empty_notes_table(tmp_path: Path):
    """Stress-test: Legacy DB has both 'note' (populated) and 'notes' (empty).

    Migration drops empty 'notes', renames 'note' to 'notes', preserving all data.
    """
    db_file = tmp_path / "collision_empty_notes.db"

    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("CREATE TABLE note (id VARCHAR(36) PRIMARY KEY, slug VARCHAR(128), title VARCHAR(255), content TEXT);")
        conn.execute("CREATE TABLE notes (id VARCHAR(36) PRIMARY KEY, slug VARCHAR(128), title VARCHAR(255), content TEXT);")
        conn.execute("INSERT INTO note (id, slug, title, content) VALUES ('n-100', 'slug-100', 'Note 100', 'Content 100');")
        conn.execute("INSERT INTO note (id, slug, title, content) VALUES ('n-101', 'slug-101', 'Note 101', 'Content 101');")
        conn.commit()

    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)

    try:
        await init_db(engine)

        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
            assert "notes" in tables
            assert "note" not in tables

            res = await conn.execute(text("SELECT id, slug, title FROM notes ORDER BY id;"))
            rows = res.fetchall()
            assert len(rows) == 2
            assert rows[0][0] == "n-100"
            assert rows[1][0] == "n-101"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_collision_both_populated_merges_safely(tmp_path: Path):
    """Stress-test: Both 'note' and 'notes' are populated with overlapping and distinct IDs.

    Migration copies non-conflicting rows into 'notes', avoids primary key collision, and purges 'note'.
    """
    db_file = tmp_path / "collision_both_populated.db"

    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("CREATE TABLE notes (id VARCHAR(36) PRIMARY KEY, slug VARCHAR(128), title VARCHAR(255), content TEXT);")
        conn.execute("CREATE TABLE note (id VARCHAR(36) PRIMARY KEY, slug VARCHAR(128), title VARCHAR(255), content TEXT);")

        # In notes: n-01, n-02
        conn.execute("INSERT INTO notes VALUES ('n-01', 'slug-01', 'Title 01 in notes', 'Content 01');")
        conn.execute("INSERT INTO notes VALUES ('n-02', 'slug-02', 'Title 02 in notes', 'Content 02');")

        # In note: n-01 (colliding id), n-03 (new id)
        conn.execute("INSERT INTO note VALUES ('n-01', 'slug-01-collide', 'Title 01 in note', 'Collide');")
        conn.execute("INSERT INTO note VALUES ('n-03', 'slug-03', 'Title 03 in note', 'Content 03');")
        conn.commit()

    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)

    try:
        await init_db(engine)

        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
            assert "notes" in tables
            assert "note" not in tables

            res = await conn.execute(text("SELECT id, title FROM notes ORDER BY id;"))
            rows = dict(res.fetchall())
            # Should have n-01, n-02, and n-03
            assert len(rows) == 3
            assert "n-01" in rows
            assert "n-02" in rows
            assert "n-03" in rows
            # Conflicting n-01 in notes kept original title (INSERT OR IGNORE)
            assert rows["n-01"] == "Title 01 in notes"
            assert rows["n-03"] == "Title 03 in note"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_idempotence_five_passes(tmp_path: Path):
    """Stress-test: Executing init_db() 5 consecutive times on the same database

    produces zero errors, zero table duplications, and preserves row counts.
    """
    db_file = tmp_path / "idempotent_five_passes.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)

    try:
        for pass_num in range(1, 6):
            await init_db(engine)

        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
            assert "notes" in tables
            assert "profiles" in tables
            assert "viewer_invites" in tables
            assert "note" not in tables
    finally:
        await engine.dispose()


# ==============================================================================
# AREA 2: Missing columns in 'profiles' -> short_name & avatar_url safely added
# ==============================================================================

@pytest.mark.asyncio
async def test_migration_profiles_missing_both_columns_preserves_data(tmp_path: Path):
    """Stress-test: Legacy DB with 20 existing profiles missing short_name and avatar_url.

    Migration adds both columns without altering existing fields, leaving defaults as NULL.
    Subsequent ORM updates to short_name and avatar_url succeed.
    """
    db_file = tmp_path / "profiles_missing_columns.db"

    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("""
            CREATE TABLE profiles (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36),
                name VARCHAR(255) NOT NULL,
                relationship VARCHAR(64) NOT NULL DEFAULT 'self',
                role VARCHAR(32) NOT NULL DEFAULT 'self',
                date_of_birth VARCHAR(10),
                avatar_color VARCHAR(32) NOT NULL DEFAULT '1',
                is_primary BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
        """)
        profile_rows = []
        for i in range(20):
            pid = f"prof-{i:03d}"
            name = f"Family Member {i}"
            rel = ["self", "child", "parent", "partner", "spouse"][i % 5]
            dob = f"199{i % 10:01d}-05-15"
            is_prim = 1 if i == 0 else 0
            profile_rows.append((pid, f"user-{i % 2}", name, rel, "self", dob, "2", is_prim, "2026-01-01", "2026-01-01"))

        conn.executemany(
            "INSERT INTO profiles (id, user_id, name, relationship, role, date_of_birth, avatar_color, is_primary, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            profile_rows,
        )
        conn.commit()

    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)

    try:
        await init_db(engine)

        async with engine.connect() as conn:
            profile_cols = await conn.run_sync(lambda sc: [c["name"] for c in inspect(sc).get_columns("profiles")])
            assert "short_name" in profile_cols, "'short_name' must be added"
            assert "avatar_url" in profile_cols, "'avatar_url' must be added"

            # Check that all 20 rows are intact
            res = await conn.execute(text("SELECT id, name, relationship, date_of_birth, short_name, avatar_url FROM profiles ORDER BY id;"))
            rows = res.fetchall()
            assert len(rows) == 20
            for i, r in enumerate(rows):
                assert r[0] == f"prof-{i:03d}"
                assert r[1] == f"Family Member {i}"
                assert r[4] is None  # short_name defaulted to NULL
                assert r[5] is None  # avatar_url defaulted to NULL

        # Verify ORM updates on the migrated table
        factory = get_session_factory(engine)
        async with factory() as session:
            p = await session.get(Profile, "prof-000")
            assert p is not None
            p.short_name = "Nickname Leo"
            p.avatar_url = "https://carefold.local/avatars/leo.png"
            await session.commit()

            refetched = await session.get(Profile, "prof-000")
            assert refetched.short_name == "Nickname Leo"
            assert refetched.avatar_url == "https://carefold.local/avatars/leo.png"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_profiles_partial_presence(tmp_path: Path):
    """Stress-test: Table already has 'short_name' but missing 'avatar_url', and vice versa.

    Migration must add only the missing column without failing on duplicate columns.
    """
    # Case A: short_name exists, avatar_url missing
    db_file_a = tmp_path / "profiles_has_short_name.db"
    with sqlite3.connect(str(db_file_a)) as conn:
        conn.execute("""
            CREATE TABLE profiles (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                short_name VARCHAR(64)
            );
        """)
        conn.execute("INSERT INTO profiles VALUES ('p-a', 'Alice', 'Ali');")
        conn.commit()

    engine_a = create_db_engine(f"sqlite+aiosqlite:///{db_file_a.resolve()}")
    try:
        await init_db(engine_a)
        async with engine_a.connect() as conn:
            cols = await conn.run_sync(lambda sc: [c["name"] for c in inspect(sc).get_columns("profiles")])
            assert "short_name" in cols
            assert "avatar_url" in cols
            res = await conn.execute(text("SELECT id, name, short_name, avatar_url FROM profiles;"))
            row = res.fetchone()
            assert row[2] == "Ali"
            assert row[3] is None
    finally:
        await engine_a.dispose()

    # Case B: avatar_url exists, short_name missing
    db_file_b = tmp_path / "profiles_has_avatar_url.db"
    with sqlite3.connect(str(db_file_b)) as conn:
        conn.execute("""
            CREATE TABLE profiles (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                avatar_url VARCHAR(512)
            );
        """)
        conn.execute("INSERT INTO profiles VALUES ('p-b', 'Bob', '/uploads/b.png');")
        conn.commit()

    engine_b = create_db_engine(f"sqlite+aiosqlite:///{db_file_b.resolve()}")
    try:
        await init_db(engine_b)
        async with engine_b.connect() as conn:
            cols = await conn.run_sync(lambda sc: [c["name"] for c in inspect(sc).get_columns("profiles")])
            assert "short_name" in cols
            assert "avatar_url" in cols
            res = await conn.execute(text("SELECT id, name, short_name, avatar_url FROM profiles;"))
            row = res.fetchone()
            assert row[2] is None
            assert row[3] == "/uploads/b.png"
    finally:
        await engine_b.dispose()


@pytest.mark.asyncio
async def test_migration_profile_access_role_column_added(tmp_path: Path):
    """Stress-test: Legacy profile_access missing 'role' column is migrated with default 'viewer'."""
    db_file = tmp_path / "legacy_profile_access.db"
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("""
            CREATE TABLE profile_access (
                id VARCHAR(36) PRIMARY KEY,
                profile_id VARCHAR(36) NOT NULL,
                user_id VARCHAR(36) NOT NULL,
                access_level VARCHAR(32) NOT NULL DEFAULT 'view_clinical'
            );
        """)
        conn.execute("INSERT INTO profile_access VALUES ('pa-1', 'p-1', 'u-1', 'view_clinical');")
        conn.commit()

    engine = create_db_engine(f"sqlite+aiosqlite:///{db_file.resolve()}")
    try:
        await init_db(engine)
        async with engine.connect() as conn:
            cols = await conn.run_sync(lambda sc: [c["name"] for c in inspect(sc).get_columns("profile_access")])
            assert "role" in cols
            res = await conn.execute(text("SELECT id, role FROM profile_access;"))
            row = res.fetchone()
            assert row[1] == "viewer"
    finally:
        await engine.dispose()


# ==============================================================================
# AREA 3: Unique constraint on 'invite_code' -> duplicate codes rejected
# ==============================================================================

@pytest.mark.asyncio
async def test_unique_invite_code_constraint_orm_and_sql(tmp_path: Path):
    """Stress-test: Duplicate invite_code rejection across ORM and raw SQLite engine.

    Probes:
    1. Duplicate on same profile -> IntegrityError.
    2. Duplicate across different profiles/users -> IntegrityError.
    3. Direct raw SQL INSERT -> IntegrityError.
    """
    db_file = tmp_path / "unique_codes_test.db"
    engine = create_db_engine(f"sqlite+aiosqlite:///{db_file.resolve()}")
    await init_db(engine)
    factory = get_session_factory(engine)

    try:
        # Create 2 distinct profiles
        async with factory() as session:
            p1 = Profile(name="Profile One", relationship="self")
            p2 = Profile(name="Profile Two", relationship="spouse")
            session.add_all([p1, p2])
            await session.commit()
            p1_id, p2_id = p1.id, p2.id

        # 1. Insert first invite
        now = datetime.now(timezone.utc)
        async with factory() as session:
            inv1 = ViewerInvite(
                invite_code="cf-inv-STRESS-UNIQUE-001",
                profile_id=p1_id,
                invitee_name="Invitee Alpha",
                expires_at=now + timedelta(days=7),
            )
            session.add(inv1)
            await session.commit()

        # 2. Attempt duplicate on same profile
        async with factory() as session:
            inv2 = ViewerInvite(
                invite_code="cf-inv-STRESS-UNIQUE-001",
                profile_id=p1_id,
                invitee_name="Invitee Beta",
                expires_at=now + timedelta(days=7),
            )
            session.add(inv2)
            with pytest.raises(IntegrityError):
                await session.commit()

        # 3. Attempt duplicate across DIFFERENT profile (global uniqueness constraint)
        async with factory() as session:
            inv3 = ViewerInvite(
                invite_code="cf-inv-STRESS-UNIQUE-001",
                profile_id=p2_id,
                invitee_name="Invitee Gamma",
                expires_at=now + timedelta(days=7),
            )
            session.add(inv3)
            with pytest.raises(IntegrityError):
                await session.commit()

        # 4. Attempt duplicate via raw SQL insert
        async with engine.connect() as conn:
            with pytest.raises(Exception):  # sqlite3.IntegrityError
                await conn.execute(text(
                    "INSERT INTO viewer_invites (id, invite_code, profile_id, invitee_name, expires_at, created_at, updated_at) "
                    "VALUES ('raw-id-01', 'cf-inv-STRESS-UNIQUE-001', :p_id, 'Raw Invitee', '2026-02-01', '2026-01-01', '2026-01-01');"
                ), {"p_id": p1_id})
    finally:
        await engine.dispose()


# ==============================================================================
# AREA 4: Viewer invite lifecycle stress testing
# ==============================================================================

@pytest.mark.asyncio
async def test_invite_lifecycle_creation_and_7_day_duration(chal_test_env):
    """Stress-test: API invite creation generates cf-inv- token with exactly ~7 days lifespan."""
    with TestClient(app) as client:
        owner = _register_user(client, "alice_life@carefold.local", "Alice Life")
        profs = client.get("/api/profiles", headers=owner["headers"]).json()
        prof_id = profs[0]["id"]

        create_resp = client.post(
            f"/api/profiles/{prof_id}/invites",
            headers=owner["headers"],
            json={"invitee_name": "Nurse Joy", "view_clinical": True, "view_paperwork": True},
        )
        assert create_resp.status_code == 201
        data = create_resp.json()

        assert data["invite_code"].startswith("cf-inv-")
        # Entropy check: token suffix must be at least 24 hex chars (12 bytes)
        token_suffix = data["invite_code"][len("cf-inv-"):]
        assert len(token_suffix) >= 24
        assert data["view_clinical"] is True
        assert data["view_paperwork"] is True
        assert data["role"] == "viewer"

        # Expiration calculation: between 6 days 23 hours 50 mins and 7 days 10 mins
        exp_dt = datetime.fromisoformat(data["expires_at"])
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = exp_dt - now
        assert timedelta(days=6, hours=23, minutes=50) <= delta <= timedelta(days=7, minutes=10)


@pytest.mark.asyncio
async def test_invite_acceptance_and_dual_permission_scenarios(chal_test_env):
    """Stress-test: Accept invite with different permission flags (clinical only vs paperwork only).

    Verifies granted access_level reflects invite permissions.
    """
    with TestClient(app) as client:
        owner = _register_user(client, "owner_perm@carefold.local", "Owner Perm")
        prof_id = client.get("/api/profiles", headers=owner["headers"]).json()[0]["id"]

        viewer_clin = _register_user(client, "viewer_clin@carefold.local", "Viewer Clin")
        viewer_paper = _register_user(client, "viewer_paper@carefold.local", "Viewer Paper")

        # 1. Clinical-only invite
        inv1 = client.post(
            f"/api/profiles/{prof_id}/invites",
            headers=owner["headers"],
            json={"invitee_name": "Clin Viewer", "view_clinical": True, "view_paperwork": False},
        ).json()

        acc1 = client.post(
            "/api/profiles/invites/accept",
            headers=viewer_clin["headers"],
            json={"invite_code": inv1["invite_code"]},
        )
        assert acc1.status_code == 200
        assert acc1.json()["access_level"] == "view_clinical"
        assert acc1.json()["role"] == "viewer"

        # 2. Paperwork-only invite
        inv2 = client.post(
            f"/api/profiles/{prof_id}/invites",
            headers=owner["headers"],
            json={"invitee_name": "Paper Viewer", "view_clinical": False, "view_paperwork": True},
        ).json()

        acc2 = client.post(
            "/api/profiles/invites/accept",
            headers=viewer_paper["headers"],
            json={"invite_code": inv2["invite_code"]},
        )
        assert acc2.status_code == 200
        assert acc2.json()["access_level"] == "view_paperwork"
        assert acc2.json()["role"] == "viewer"


@pytest.mark.asyncio
async def test_invite_rejection_expired_code(chal_test_env):
    """Stress-test: Expired invitation rejection.

    Probes:
    1. Past timestamp in expires_at is rejected with HTTP 400.
    2. No ProfileAccess is granted on expired redemption attempt.
    """
    session_factory = chal_test_env["session_factory"]

    with TestClient(app) as client:
        owner = _register_user(client, "owner_exp@carefold.local", "Owner Exp")
        viewer = _register_user(client, "viewer_exp@carefold.local", "Viewer Exp")
        prof_id = client.get("/api/profiles", headers=owner["headers"]).json()[0]["id"]

        inv = client.post(
            f"/api/profiles/{prof_id}/invites",
            headers=owner["headers"],
            json={"invitee_name": "Exp Viewer"},
        ).json()
        code = inv["invite_code"]

        # Backdate expiration to 1 minute ago in DB
        async with session_factory() as session:
            stmt = select(ViewerInvite).where(ViewerInvite.invite_code == code)
            res = await session.execute(stmt)
            record = res.scalar_one()
            record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            await session.commit()

        # Attempt to accept
        resp = client.post(
            "/api/profiles/invites/accept",
            headers=viewer["headers"],
            json={"invite_code": code},
        )
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

        # Verify viewer did NOT gain access to the profile
        v_profs = client.get("/api/profiles", headers=viewer["headers"]).json()
        assert not any(p["id"] == prof_id for p in v_profs)


@pytest.mark.asyncio
async def test_double_acceptance_replay_attack_rejected(chal_test_env):
    """Stress-test: Double acceptance replay attack.

    Probes:
    1. Same user accepting twice -> HTTP 400 on second try.
    2. Different user attempting to accept the already-consumed invite -> HTTP 400.
    3. Third user gets no access grant.
    """
    with TestClient(app) as client:
        owner = _register_user(client, "owner_replay@carefold.local", "Owner")
        viewer1 = _register_user(client, "viewer_one@carefold.local", "Viewer One")
        viewer2 = _register_user(client, "viewer_two@carefold.local", "Viewer Two")
        prof_id = client.get("/api/profiles", headers=owner["headers"]).json()[0]["id"]

        inv = client.post(
            f"/api/profiles/{prof_id}/invites",
            headers=owner["headers"],
            json={"invitee_name": "Shared Link"},
        ).json()
        code = inv["invite_code"]

        # First acceptance by viewer1 -> OK
        acc1 = client.post("/api/profiles/invites/accept", headers=viewer1["headers"], json={"invite_code": code})
        assert acc1.status_code == 200

        # Second acceptance by viewer1 -> REJECTED
        acc1_retry = client.post("/api/profiles/invites/accept", headers=viewer1["headers"], json={"invite_code": code})
        assert acc1_retry.status_code == 400
        assert "already been accepted" in acc1_retry.json()["detail"].lower()

        # Acceptance attempt by viewer2 -> REJECTED
        acc2 = client.post("/api/profiles/invites/accept", headers=viewer2["headers"], json={"invite_code": code})
        assert acc2.status_code == 400
        assert "already been accepted" in acc2.json()["detail"].lower()

        # Confirm viewer2 has no access
        v2_profs = client.get("/api/profiles", headers=viewer2["headers"]).json()
        assert not any(p["id"] == prof_id for p in v2_profs)


@pytest.mark.asyncio
async def test_self_invite_acceptance_rejected(chal_test_env):
    """Stress-test: Profile owner cannot accept an invite for their own profile."""
    with TestClient(app) as client:
        owner = _register_user(client, "owner_self@carefold.local", "Owner Self")
        prof_id = client.get("/api/profiles", headers=owner["headers"]).json()[0]["id"]

        inv = client.post(
            f"/api/profiles/{prof_id}/invites",
            headers=owner["headers"],
            json={"invitee_name": "Self Invite"},
        ).json()

        resp = client.post(
            "/api/profiles/invites/accept",
            headers=owner["headers"],
            json={"invite_code": inv["invite_code"]},
        )
        assert resp.status_code == 400
        assert "already the owner" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_invalid_and_whitespace_invite_codes(chal_test_env):
    """Stress-test: Invalid, nonexistent, or whitespace invite codes are safely handled."""
    with TestClient(app) as client:
        user = _register_user(client, "user_invalid@carefold.local", "User Invalid")

        # Nonexistent code
        r1 = client.post("/api/profiles/invites/accept", headers=user["headers"], json={"invite_code": "cf-inv-DOESNOTEXIST"})
        assert r1.status_code == 404

        # Empty string
        r2 = client.post("/api/profiles/invites/accept", headers=user["headers"], json={"invite_code": ""})
        assert r2.status_code in (404, 422)

        # Whitespace only
        r3 = client.post("/api/profiles/invites/accept", headers=user["headers"], json={"invite_code": "   "})
        assert r3.status_code == 404


@pytest.mark.asyncio
async def test_invite_revocation_and_unauthorized_deletion(chal_test_env):
    """Stress-test: Revoking an invite prevents subsequent acceptance, and unauthorized revokes are blocked."""
    with TestClient(app) as client:
        owner = _register_user(client, "owner_rev@carefold.local", "Owner Rev")
        stranger = _register_user(client, "stranger@carefold.local", "Stranger")
        prof_id = client.get("/api/profiles", headers=owner["headers"]).json()[0]["id"]

        inv = client.post(
            f"/api/profiles/{prof_id}/invites",
            headers=owner["headers"],
            json={"invitee_name": "To Revoke"},
        ).json()
        inv_id, code = inv["id"], inv["invite_code"]

        # Stranger attempts to revoke -> HTTP 403 / 404
        unauth_del = client.delete(f"/api/profiles/{prof_id}/invites/{inv_id}", headers=stranger["headers"])
        assert unauth_del.status_code in (403, 404)

        # Owner revokes -> HTTP 200
        auth_del = client.delete(f"/api/profiles/{prof_id}/invites/{inv_id}", headers=owner["headers"])
        assert auth_del.status_code == 200
        assert auth_del.json()["revoked"] is True

        # Stranger attempts to accept revoked code -> HTTP 404
        accept_resp = client.post("/api/profiles/invites/accept", headers=stranger["headers"], json={"invite_code": code})
        assert accept_resp.status_code == 404


@pytest.mark.asyncio
async def test_list_invites_filtering_and_include_expired(chal_test_env):
    """Stress-test: list_viewer_invites correctly filters out expired/accepted unless include_expired=true."""
    session_factory = chal_test_env["session_factory"]

    with TestClient(app) as client:
        owner = _register_user(client, "owner_filter@carefold.local", "Owner Filter")
        viewer = _register_user(client, "viewer_filter@carefold.local", "Viewer Filter")
        prof_id = client.get("/api/profiles", headers=owner["headers"]).json()[0]["id"]

        # 1. Create active invite
        inv_active = client.post(f"/api/profiles/{prof_id}/invites", headers=owner["headers"], json={"invitee_name": "Active"}).json()

        # 2. Create accepted invite
        inv_accepted = client.post(f"/api/profiles/{prof_id}/invites", headers=owner["headers"], json={"invitee_name": "Accepted"}).json()
        client.post("/api/profiles/invites/accept", headers=viewer["headers"], json={"invite_code": inv_accepted["invite_code"]})

        # 3. Create expired invite
        inv_expired = client.post(f"/api/profiles/{prof_id}/invites", headers=owner["headers"], json={"invitee_name": "Expired"}).json()
        async with session_factory() as session:
            stmt = select(ViewerInvite).where(ViewerInvite.id == inv_expired["id"])
            res = await session.execute(stmt)
            rec = res.scalar_one()
            rec.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
            await session.commit()

        # Default list (active only)
        list_active = client.get(f"/api/profiles/{prof_id}/invites", headers=owner["headers"]).json()
        active_ids = [i["id"] for i in list_active]
        assert inv_active["id"] in active_ids
        assert inv_accepted["id"] not in active_ids
        assert inv_expired["id"] not in active_ids

        # List with include_expired=true
        list_all = client.get(f"/api/profiles/{prof_id}/invites?include_expired=true", headers=owner["headers"]).json()
        all_ids = [i["id"] for i in list_all]
        assert inv_active["id"] in all_ids
        assert inv_accepted["id"] in all_ids
        assert inv_expired["id"] in all_ids


# ==============================================================================
# AREA 5: Cascading deletes: deleting a profile deletes all associated invites
# ==============================================================================

@pytest.mark.asyncio
async def test_profile_delete_orm_cascades_invites(tmp_path: Path):
    """Stress-test: Deleting a profile via SQLAlchemy ORM cascades and deletes all viewer invites."""
    db_file = tmp_path / "orm_cascade_test.db"
    engine = create_db_engine(f"sqlite+aiosqlite:///{db_file.resolve()}")
    await init_db(engine)
    factory = get_session_factory(engine)

    try:
        async with factory() as session:
            profile = Profile(name="Arthur Dent", relationship="self")
            session.add(profile)
            await session.commit()

            # Create 5 invites
            now = datetime.now(timezone.utc)
            invites = [
                ViewerInvite(
                    invite_code=f"cf-inv-CASCADE-ORM-{i}",
                    profile_id=profile.id,
                    invitee_name=f"Companion {i}",
                    expires_at=now + timedelta(days=7),
                )
                for i in range(5)
            ]
            session.add_all(invites)
            await session.commit()

            # Confirm 5 invites exist
            res = await session.execute(select(ViewerInvite).where(ViewerInvite.profile_id == profile.id))
            assert len(res.scalars().all()) == 5

            # Delete the profile
            await session.delete(profile)
            await session.commit()

            # Confirm 0 invites exist
            res_after = await session.execute(select(ViewerInvite).where(ViewerInvite.profile_id == profile.id))
            assert len(res_after.scalars().all()) == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_profile_delete_raw_sql_cascades_sqlite_engine_level(tmp_path: Path):
    """Stress-test: Raw SQL 'DELETE FROM profiles WHERE id = ...' triggers SQLite engine-level

    ON DELETE CASCADE (PRAGMA foreign_keys = ON) to delete viewer_invites with zero ORM involvement.
    """
    db_file = tmp_path / "sqlite_engine_cascade_test.db"
    engine = create_db_engine(f"sqlite+aiosqlite:///{db_file.resolve()}")
    await init_db(engine)
    factory = get_session_factory(engine)

    try:
        # Create profile and 4 invites
        async with factory() as session:
            p = Profile(name="Ford Prefect", relationship="other")
            session.add(p)
            await session.commit()
            p_id = p.id

            now = datetime.now(timezone.utc)
            for i in range(4):
                inv = ViewerInvite(
                    invite_code=f"cf-inv-RAW-SQL-{i}",
                    profile_id=p_id,
                    invitee_name=f"Hitchhiker {i}",
                    expires_at=now + timedelta(days=7),
                )
                session.add(inv)
            await session.commit()

        # Execute RAW SQL deletion on profile without loading into session
        async with engine.begin() as conn:
            # Ensure foreign keys are active
            fk_check = (await conn.execute(text("PRAGMA foreign_keys;"))).scalar()
            assert fk_check == 1, "PRAGMA foreign_keys must be ON in engine connection"

            del_res = await conn.execute(text("DELETE FROM profiles WHERE id = :pid;"), {"pid": p_id})
            assert del_res.rowcount == 1

            # Query viewer_invites table directly via SQL
            count_res = await conn.execute(
                text("SELECT count(*) FROM viewer_invites WHERE profile_id = :pid;"),
                {"pid": p_id},
            )
            count_invites = count_res.scalar()
            assert count_invites == 0, f"Expected 0 invites after raw SQL profile delete, got {count_invites}"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_acceptor_user_delete_sets_accepted_by_null(tmp_path: Path):
    """Stress-test: Deleting the user who accepted an invite triggers ON DELETE SET NULL on accepted_by

    without deleting the invite itself.
    """
    db_file = tmp_path / "user_set_null_test.db"
    engine = create_db_engine(f"sqlite+aiosqlite:///{db_file.resolve()}")
    await init_db(engine)
    factory = get_session_factory(engine)

    try:
        async with factory() as session:
            owner = User(email="owner@c.local", username="owner_c", hashed_password="pw")
            acceptor = User(email="acceptor@c.local", username="acceptor_c", hashed_password="pw")
            session.add_all([owner, acceptor])
            await session.commit()

            profile = Profile(user_id=owner.id, name="Trillian", relationship="self")
            session.add(profile)
            await session.commit()

            invite = ViewerInvite(
                invite_code="cf-inv-SETNULL-01",
                profile_id=profile.id,
                invited_by=owner.id,
                invitee_name="Acceptor Friend",
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                accepted_at=datetime.now(timezone.utc),
                accepted_by=acceptor.id,
            )
            session.add(invite)
            await session.commit()
            inv_id = invite.id
            acceptor_id = acceptor.id

        # Delete the acceptor user via raw SQL
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM users WHERE id = :uid;"), {"uid": acceptor_id})

            # Check that invite still exists, but accepted_by is NULL
            res = await conn.execute(
                text("SELECT id, accepted_at, accepted_by FROM viewer_invites WHERE id = :iid;"),
                {"iid": inv_id},
            )
            row = res.fetchone()
            assert row is not None, "Invite should not be deleted when acceptor user is deleted"
            assert row[1] is not None, "accepted_at timestamp should be preserved"
            assert row[2] is None, "accepted_by foreign key should be set to NULL"
    finally:
        await engine.dispose()
