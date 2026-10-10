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

"""Test suite for Milestone M4: Standardized Dual-Mounted API Versioning.

Verifies that both canonical /api/v1/* and legacy /api/* respond identically
with identical status codes, schemas, and data persistence across all core modules.
"""

from __future__ import annotations

import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from carefold.constants.api import (
    API_PREFIX,
    API_V1_PREFIX,
    API_V1_HEALTH,
    API_HEALTH,
    API_V1_NOTES,
    API_NOTES,
    API_V1_PROFILES,
    API_PROFILES,
    API_V1_ATTACHMENTS,
    API_ATTACHMENTS,
    API_V1_AGENTS,
    API_AGENTS,
    API_V1_SKILLS,
    API_SKILLS,
    API_V1_MODELS,
    API_MODELS,
    API_V1_MEMORY_STATUS,
    API_V1_AUTH_PROVIDERS,
    API_V1_AUTH_SETUP_STATUS,
    API_V1_AUTH_STATUS,
    API_V1_AUDIT,
    API_AUDIT,
)


def test_health_dual_mount(client: TestClient):
    """Verifies that /api/v1/health and /api/health respond with identical schemas."""
    r_v1 = client.get(API_V1_HEALTH)
    r_leg = client.get(API_HEALTH)

    assert r_v1.status_code == 200
    assert r_leg.status_code == 200

    d1 = r_v1.json()
    d2 = r_leg.json()

    assert set(d1.keys()) == set(d2.keys())
    assert d1["status"] == d2["status"] == "ok"
    assert d1["version"] == d2["version"]
    assert d1["backendReachable"] == d2["backendReachable"] is True
    assert d1["workspace"]["agentsCount"] == d2["workspace"]["agentsCount"]
    assert d1["workspace"]["skillsCount"] == d2["workspace"]["skillsCount"]


def test_auth_status_dual_mount(client: TestClient):
    """Verifies that /auth/providers, /auth/setup-status, and /auth/status match."""
    # Providers
    r1 = client.get(API_V1_AUTH_PROVIDERS)
    r2 = client.get(f"{API_PREFIX}/auth/providers")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json()

    # Setup status
    r1 = client.get(API_V1_AUTH_SETUP_STATUS)
    r2 = client.get(f"{API_PREFIX}/auth/setup-status")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json()

    # Status alias
    r1 = client.get(API_V1_AUTH_STATUS)
    r2 = client.get(f"{API_PREFIX}/auth/status")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json()


def test_notes_crud_dual_mount(client: TestClient):
    """Verifies creating via v1 and reading/updating/deleting via legacy /api and vice-versa."""
    note_payload = {
        "title": "Dual Mount Integration Note",
        "content": "Content verifying v1 and legacy API interoperability.",
        "tags": ["v1", "dual-mount"],
    }

    # Create note via /api/v1/notes
    create_resp = client.post(API_V1_NOTES, json=note_payload)
    assert create_resp.status_code == 201
    slug = create_resp.json()["slug"]

    # Read note detail via legacy /api/notes/{slug} and canonical /api/v1/notes/{slug}
    r_leg = client.get(f"{API_NOTES}/{slug}")
    r_v1 = client.get(f"{API_V1_NOTES}/{slug}")
    assert r_leg.status_code == 200 and r_v1.status_code == 200
    assert r_leg.json() == r_v1.json()

    # List notes via both endpoints
    list_leg = client.get(API_NOTES)
    list_v1 = client.get(API_V1_NOTES)
    assert list_leg.status_code == 200 and list_v1.status_code == 200
    assert list_leg.json() == list_v1.json()

    # Delete note via legacy /api/notes/{slug}
    del_resp = client.delete(f"{API_NOTES}/{slug}")
    assert del_resp.status_code in (200, 204)

    # Verify both return 404
    assert client.get(f"{API_V1_NOTES}/{slug}").status_code == 404
    assert client.get(f"{API_NOTES}/{slug}").status_code == 404


@pytest.fixture
async def auth_env(temp_workspace: Path, monkeypatch):
    """Sets up an isolated in-memory DB and local SQL auth provider for profile tests."""
    from carefold.api.deps import get_db
    from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
    from carefold.auth.factory import reset_auth_port, set_auth_port
    from carefold.config import settings
    from carefold.db.session import create_db_engine, get_session_factory, init_db
    from carefold.main import app

    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    sql_auth = SqlAuthAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    monkeypatch.setattr(settings, "workspace_root", temp_workspace)
    set_auth_port(sql_auth)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    try:
        yield {"auth": sql_auth, "session_factory": session_factory}
    finally:
        app.dependency_overrides.clear()
        reset_auth_port()


def test_profiles_dual_mount(client: TestClient, auth_env):
    """Verifies profile CRUD and listing consistency across /api/v1/profiles and /api/profiles."""
    # Register and login test user
    reg_payload = {
        "email": "dualmount@carefold.org",
        "username": "dualmountuser",
        "password": "Password123!",
        "full_name": "Dual Mount Tester",
    }
    client.post(f"{API_V1_PREFIX}/auth/register", json=reg_payload)
    login_resp = client.post(
        f"{API_PREFIX}/auth/login",
        json={"username": "dualmountuser", "password": "Password123!"},
    )
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # List profiles via both
    list_v1 = client.get(API_V1_PROFILES, headers=headers)
    list_leg = client.get(API_PROFILES, headers=headers)
    assert list_v1.status_code == 200 and list_leg.status_code == 200
    assert list_v1.json() == list_leg.json()
    assert len(list_v1.json()) > 0

    me_id = list_v1.json()[0]["id"]

    # Read profile via legacy /api and canonical /api/v1
    p_leg = client.get(f"{API_PROFILES}/{me_id}", headers=headers)
    p_v1 = client.get(f"{API_V1_PROFILES}/{me_id}", headers=headers)
    assert p_leg.status_code == 200 and p_v1.status_code == 200
    assert p_leg.json() == p_v1.json()

    # Create profile via /api/v1/profiles
    new_profile = {
        "name": "Grandpa Joe",
        "relationship": "parent",
        "role": "viewer",
        "date_of_birth": "1948-03-12",
        "avatar_color": "emerald",
    }
    create_resp = client.post(API_V1_PROFILES, json=new_profile, headers=headers)
    assert create_resp.status_code == 201
    profile_id = create_resp.json()["id"]

    # Read new profile via legacy /api and canonical /api/v1
    prof_leg = client.get(f"{API_PROFILES}/{profile_id}", headers=headers)
    prof_v1 = client.get(f"{API_V1_PROFILES}/{profile_id}", headers=headers)
    assert prof_leg.status_code == 200 and prof_v1.status_code == 200
    assert prof_leg.json() == prof_v1.json()

    # Consent query via both
    cons_leg = client.get(f"{API_PROFILES}/{profile_id}/consent", headers=headers)
    cons_v1 = client.get(f"{API_V1_PROFILES}/{profile_id}/consent", headers=headers)
    assert cons_leg.status_code == 200 and cons_v1.status_code == 200
    assert cons_leg.json() == cons_v1.json()


def test_attachments_dual_mount(client: TestClient):
    """Verifies attachment upload, list, and download consistency across /api/v1 and /api."""
    file_bytes = b"Sample lab result data for versioning verification."
    files = {"file": ("test_lab.txt", io.BytesIO(file_bytes), "text/plain")}

    # Upload via v1
    up_resp = client.post(API_V1_ATTACHMENTS, files=files)
    assert up_resp.status_code == 201
    att_id = up_resp.json()["id"]

    # List attachments via both
    list_v1 = client.get(API_V1_ATTACHMENTS)
    list_leg = client.get(API_ATTACHMENTS)
    assert list_v1.status_code == 200 and list_leg.status_code == 200
    assert list_v1.json() == list_leg.json()

    # Download via v1 and legacy
    dl_v1 = client.get(f"{API_V1_ATTACHMENTS}/{att_id}/download")
    dl_leg = client.get(f"{API_ATTACHMENTS}/{att_id}/download")
    assert dl_v1.status_code == 200 and dl_leg.status_code == 200
    assert dl_v1.content == dl_leg.content == file_bytes


def test_agents_and_skills_catalog_dual_mount(client: TestClient):
    """Verifies specialist agents and skills catalog consistency across v1 and legacy."""
    # Agents list
    ag_v1 = client.get(API_V1_AGENTS)
    ag_leg = client.get(API_AGENTS)
    assert ag_v1.status_code == 200 and ag_leg.status_code == 200
    assert ag_v1.json() == ag_leg.json()

    # Clinical agent detail with allow_clinical=true
    ag_det_v1 = client.get(f"{API_V1_AGENTS}/visit-steward?allow_clinical=true")
    ag_det_leg = client.get(f"{API_AGENTS}/visit-steward?allow_clinical=true")
    assert ag_det_v1.status_code == 200 and ag_det_leg.status_code == 200
    assert ag_det_v1.json() == ag_det_leg.json()

    # Wellness agent detail without allow_clinical requirement
    ag_hc_v1 = client.get(f"{API_V1_AGENTS}/habit-companion")
    ag_hc_leg = client.get(f"{API_AGENTS}/habit-companion")
    assert ag_hc_v1.status_code == 200 and ag_hc_leg.status_code == 200
    assert ag_hc_v1.json() == ag_hc_leg.json()

    # Skills list
    sk_v1 = client.get(API_V1_SKILLS)
    sk_leg = client.get(API_SKILLS)
    assert sk_v1.status_code == 200 and sk_leg.status_code == 200
    assert sk_v1.json() == sk_leg.json()

    # Skill detail
    sk_det_v1 = client.get(f"{API_V1_SKILLS}/visit-prep")
    sk_det_leg = client.get(f"{API_SKILLS}/visit-prep")
    assert sk_det_v1.status_code == 200 and sk_det_leg.status_code == 200
    assert sk_det_v1.json() == sk_det_leg.json()


def test_models_dual_mount(client: TestClient):
    """Verifies models endpoint consistency across v1 and legacy."""
    mod_v1 = client.get(API_V1_MODELS)
    mod_leg = client.get(API_MODELS)
    assert mod_v1.status_code == 200 and mod_leg.status_code == 200
    assert mod_v1.json() == mod_leg.json()


def test_memory_status_dual_mount(client: TestClient):
    """Verifies memory status consistency across v1 and legacy."""
    mem_v1 = client.get(API_V1_MEMORY_STATUS)
    mem_leg = client.get(f"{API_PREFIX}/memory/status")
    assert mem_v1.status_code == 200 and mem_leg.status_code == 200
    assert mem_v1.json() == mem_leg.json()


def test_audit_dual_mount(client: TestClient):
    """Verifies audit events list consistency across v1 and legacy."""
    aud_v1 = client.get(API_V1_AUDIT)
    aud_leg = client.get(API_AUDIT)
    assert aud_v1.status_code == 200 and aud_leg.status_code == 200
    assert aud_v1.json() == aud_leg.json()


def test_openapi_schema_v1_presence(client: TestClient):
    """Verifies that OpenAPI documentation includes canonical /api/v1 endpoints."""
    schema_resp = client.get("/openapi.json")
    assert schema_resp.status_code == 200
    schema = schema_resp.json()
    paths = schema.get("paths", {})

    # Ensure canonical v1 routes are present in OpenAPI schema
    assert "/api/v1/health" in paths
    assert "/api/v1/notes" in paths
    assert "/api/v1/profiles" in paths
    assert "/api/v1/attachments" in paths
    assert "/api/v1/agents" in paths
    assert "/api/v1/skills" in paths

    # Verify Swagger UI loads successfully
    docs_resp = client.get("/docs")
    assert docs_resp.status_code == 200
