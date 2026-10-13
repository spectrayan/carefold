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

"""Unit and integration tests for REST Profile Search API endpoint (AU-26, M4)."""

from __future__ import annotations

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
from carefold.search.adapters.sqlite import SqliteSearchIndex
from carefold.search.factory import get_search_index, reset_search_indexes, set_search_index


@pytest.fixture
async def search_test_env(temp_workspace: Path, monkeypatch, tmp_path: Path):
    """Sets up an isolated database, local SQL auth adapter, and search index."""
    db_file = tmp_path / "search_env.db"
    engine = create_db_engine(f"sqlite+aiosqlite:///{db_file}")
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

    idx_file = tmp_path / "test_api_search_idx.db"
    idx = SqliteSearchIndex(db_path=idx_file)
    set_search_index(idx)

    try:
        yield {
            "workspace": temp_workspace,
            "session_factory": session_factory,
            "auth": sql_auth,
            "search_index": idx,
        }
    finally:
        app.dependency_overrides.clear()
        reset_auth_port()
        reset_search_indexes()


def register_and_login(client: TestClient, email: str, password: str, name: str) -> dict:
    """Helper to register and authenticate a user against local SQL auth."""
    # Ensure an initial admin exists so test users can register cleanly
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
    assert resp.status_code in (201, 200, 400), resp.text
    login_resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert login_resp.status_code == 200, login_resp.text
    token = login_resp.json()["token"]
    user_info = login_resp.json()["user"]
    return {"token": token, "user": user_info, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
def auth_user(search_test_env, client: TestClient) -> dict:
    """Registers and logs in a standard test user Alice with a primary profile."""
    user = register_and_login(client, "alice@carefold.test", "Password123!", "Alice")
    prof_res = client.get("/api/v1/profiles", headers=user["headers"])
    assert prof_res.status_code == 200
    user["profile_id"] = prof_res.json()[0]["id"]
    return user


class TestSearchApiValidation:
    """Verifies query parameters, mode, and profile validation rules."""

    def test_search_rejects_empty_query_400(self, client: TestClient, auth_user: dict):
        profile_id = auth_user["profile_id"]
        res = client.get(f"/api/v1/profiles/{profile_id}/search?q=", headers=auth_user["headers"])
        assert res.status_code == 400
        assert "Search query cannot be empty" in res.json().get("detail", "")

    def test_search_rejects_whitespace_query_400(self, client: TestClient, auth_user: dict):
        profile_id = auth_user["profile_id"]
        res = client.get(f"/api/v1/profiles/{profile_id}/search?q=%20%20%20", headers=auth_user["headers"])
        assert res.status_code == 400
        assert "Search query cannot be empty" in res.json().get("detail", "")

    def test_search_missing_query_parameter_400(self, client: TestClient, auth_user: dict):
        profile_id = auth_user["profile_id"]
        res = client.get(f"/api/v1/profiles/{profile_id}/search", headers=auth_user["headers"])
        assert res.status_code == 400
        assert "Search query cannot be empty" in res.json().get("detail", "")

    def test_search_limit_boundaries(self, client: TestClient, auth_user: dict):
        profile_id = auth_user["profile_id"]

        res_zero = client.get(f"/api/v1/profiles/{profile_id}/search?q=test&limit=0", headers=auth_user["headers"])
        assert res_zero.status_code in (400, 422)

        res_too_large = client.get(f"/api/v1/profiles/{profile_id}/search?q=test&limit=101", headers=auth_user["headers"])
        assert res_too_large.status_code in (400, 422)

    def test_search_invalid_mode_400(self, client: TestClient, auth_user: dict):
        profile_id = auth_user["profile_id"]
        res = client.get(f"/api/v1/profiles/{profile_id}/search?q=test&mode=vector_only", headers=auth_user["headers"])
        assert res.status_code == 400
        assert "Invalid search mode" in res.json().get("detail", "")

    def test_search_invalid_profile_400(self, client: TestClient, auth_user: dict):
        res = client.get("/api/v1/profiles/prof-nonexistent-99999/search?q=test", headers=auth_user["headers"])
        assert res.status_code == 400
        assert "Profile not found" in res.json().get("detail", "")

    def test_search_empty_profile_id_400(self, client: TestClient, auth_user: dict):
        res = client.get("/api/v1/profiles/%20/search?q=test", headers=auth_user["headers"])
        assert res.status_code == 400
        assert "Profile not found" in res.json().get("detail", "")


class TestSearchApiExecution:
    """Verifies search result serialization, dual mount parity, and retrieval modes."""

    @pytest.mark.asyncio
    async def test_search_happy_path_200(self, client: TestClient, auth_user: dict):
        profile_id = auth_user["profile_id"]

        idx = get_search_index()
        await idx.index_document(
            document_id="doc-cardio-1",
            text="Patient diagnosed with essential hypertension. Prescribed Lisinopril 10mg daily.",
            metadata={"category": "cardiology", "source": "clinical_note"},
            profile_id=profile_id,
        )

        res = client.get(f"/api/v1/profiles/{profile_id}/search?q=Lisinopril", headers=auth_user["headers"])
        assert res.status_code == 200
        hits = res.json()
        assert isinstance(hits, list)
        assert len(hits) >= 1
        assert hits[0]["document_id"] == "doc-cardio-1"
        assert "Lisinopril" in hits[0]["content"]
        assert hits[0]["profile_id"] == profile_id
        assert hits[0]["score"] > 0

    @pytest.mark.asyncio
    async def test_search_dual_mount_parity(self, client: TestClient, auth_user: dict):
        profile_id = auth_user["profile_id"]

        idx = get_search_index()
        await idx.index_document(
            document_id="doc-dual-1",
            text="Dual mount test clinical note on cholesterol levels.",
            metadata={"source": "clinical_note"},
            profile_id=profile_id,
        )

        r_v1 = client.get(f"/api/v1/profiles/{profile_id}/search?q=cholesterol", headers=auth_user["headers"])
        r_legacy = client.get(f"/api/profiles/{profile_id}/search?q=cholesterol", headers=auth_user["headers"])

        assert r_v1.status_code == 200
        assert r_legacy.status_code == 200
        assert r_v1.json() == r_legacy.json()

    @pytest.mark.asyncio
    async def test_search_limit_parameter(self, client: TestClient, auth_user: dict):
        profile_id = auth_user["profile_id"]

        idx = get_search_index()
        for i in range(5):
            await idx.index_document(
                document_id=f"doc-lim-{i}",
                text=f"Asthma assessment report number {i}. Albuterol inhaler prescribed.",
                metadata={"idx": i, "source": "clinical_note"},
                profile_id=profile_id,
            )

        res = client.get(f"/api/v1/profiles/{profile_id}/search?q=Asthma&limit=2", headers=auth_user["headers"])
        assert res.status_code == 200
        hits = res.json()
        assert len(hits) == 2

    @pytest.mark.asyncio
    async def test_search_supported_modes(self, client: TestClient, auth_user: dict):
        profile_id = auth_user["profile_id"]

        idx = get_search_index()
        await idx.index_document(
            document_id="doc-mode-test",
            text="Type 2 diabetes assessment report.",
            metadata={"source": "clinical_note"},
            profile_id=profile_id,
        )

        for mode in ("hybrid", "lexical", "semantic"):
            res = client.get(f"/api/v1/profiles/{profile_id}/search?q=diabetes&mode={mode}", headers=auth_user["headers"])
            assert res.status_code == 200
            hits = res.json()
            assert len(hits) >= 1

    @pytest.mark.asyncio
    async def test_search_source_filter(self, client: TestClient, auth_user: dict):
        profile_id = auth_user["profile_id"]

        idx = get_search_index()
        await idx.index_document(
            document_id="doc-src-upload",
            text="Uploaded lab report on thyroid stimulating hormone.",
            metadata={"source": "upload"},
            profile_id=profile_id,
        )
        await idx.index_document(
            document_id="doc-src-note",
            text="Clinical note on thyroid stimulating hormone follow-up.",
            metadata={"source": "clinical_note"},
            profile_id=profile_id,
        )

        res_upload = client.get(f"/api/v1/profiles/{profile_id}/search?q=thyroid&source=upload", headers=auth_user["headers"])
        assert res_upload.status_code == 200
        hits = res_upload.json()
        assert len(hits) == 1
        assert hits[0]["document_id"] == "doc-src-upload"

    @pytest.mark.asyncio
    async def test_search_query_alias(self, client: TestClient, auth_user: dict):
        profile_id = auth_user["profile_id"]

        idx = get_search_index()
        await idx.index_document(
            document_id="doc-alias-test",
            text="Electrocardiogram report shows normal sinus rhythm.",
            metadata={"source": "cardiology"},
            profile_id=profile_id,
        )

        # Uses ?query= instead of ?q=
        res = client.get(f"/api/v1/profiles/{profile_id}/search?query=Electrocardiogram", headers=auth_user["headers"])
        assert res.status_code == 200
        hits = res.json()
        assert len(hits) >= 1
        assert hits[0]["document_id"] == "doc-alias-test"

    @pytest.mark.asyncio
    async def test_search_me_alias(self, client: TestClient, auth_user: dict):
        idx = get_search_index()
        await idx.index_document(
            document_id="doc-me-test",
            text="Patient visit history and cardiology follow-up notes for primary steward.",
            metadata={"source": "clinical_note"},
            profile_id=auth_user["profile_id"],
        )

        res = client.get("/api/v1/profiles/me/search?q=cardiology", headers=auth_user["headers"])
        assert res.status_code == 200
        hits = res.json()
        assert isinstance(hits, list)
        assert len(hits) >= 1
        assert hits[0]["document_id"] == "doc-me-test"


class TestSearchApiAuthAndScoping:
    """Verifies cross-profile isolation and authentication/authorization access gates."""

    @pytest.mark.asyncio
    async def test_search_cross_profile_isolation(self, client: TestClient, auth_user: dict):
        # Create a second profile under Alice's account
        create_res = client.post(
            "/api/v1/profiles",
            json={"name": "Spouse Profile", "relationship": "spouse"},
            headers=auth_user["headers"],
        )
        assert create_res.status_code == 201
        p2_id = create_res.json()["id"]

        p1_id = auth_user["profile_id"]
        assert p1_id != p2_id

        idx = get_search_index()
        await idx.index_document(
            document_id="doc-confidential-p2",
            text="Strictly confidential psychiatric assessment for profile 2 only.",
            metadata={"source": "clinical_note"},
            profile_id=p2_id,
        )

        # Searching profile 1 must NOT return profile 2's documents
        res1 = client.get(f"/api/v1/profiles/{p1_id}/search?q=psychiatric", headers=auth_user["headers"])
        assert res1.status_code == 200
        assert len(res1.json()) == 0

        # Searching profile 2 returns the document
        res2 = client.get(f"/api/v1/profiles/{p2_id}/search?q=psychiatric", headers=auth_user["headers"])
        assert res2.status_code == 200
        assert len(res2.json()) == 1
        assert res2.json()[0]["document_id"] == "doc-confidential-p2"

    @pytest.mark.asyncio
    async def test_search_auth_and_permissions(self, client: TestClient, auth_user: dict):
        """Verifies 401 unauthenticated and 403 cross-user access under local SQL auth."""
        p_alice = auth_user["profile_id"]

        # 1. Unauthenticated request returns 401 (using client without session cookies)
        with TestClient(app) as unauth_client:
            res_unauth = unauth_client.get(f"/api/v1/profiles/{p_alice}/search?q=test")
            assert res_unauth.status_code == 401

        # 2. Register User B (Bob)
        bob = register_and_login(client, "bob@carefold.test", "BobPassword123!", "Bob")

        # 3. User B attempts to search User A's profile -> 403 Forbidden
        res_forbidden = client.get(f"/api/v1/profiles/{p_alice}/search?q=test", headers=bob["headers"])
        assert res_forbidden.status_code == 403
        assert "Forbidden: profile access denied" in res_forbidden.json().get("detail", "")
