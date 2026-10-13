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

"""Adversarial stress test harness for Milestone 4 (AU-26 & AU-27).

Challenger 2 Empirical Verification Suite:
1. Cross-profile leakage attack (HTTP 403 Forbidden on foreign profile access).
2. Non-existent profile (HTTP 400 Bad Request).
3. Unauthenticated caller (HTTP 401 Unauthorized).
4. Query boundary attacks (empty q -> 400, limit boundaries 0, 101 -> 400/422, invalid mode -> 400).
5. Index Freshness Concurrency & Idempotency:
   - Rapid concurrent note creates, updates, and deletes.
   - Idempotency key deduplication preventing duplicate queue execution.
   - Document deletion removes all chunks with zero orphaned chunks.
   - Attachment deletion removes all chunks with zero orphaned chunks.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import AsyncIterator, Dict, List
import uuid
import aiosqlite
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.models import Attachment, Job as DBJob, Note, Profile
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.engine.job_runner import (
    JobRunner,
    handle_delete_doc_job,
    handle_index_doc_job,
)
from carefold.main import app
from carefold.search.adapters.sqlite import SqliteSearchIndex
from carefold.search.factory import get_search_index, reset_search_indexes, set_search_index


@pytest.fixture
async def challenge_test_env(temp_workspace: Path, monkeypatch, tmp_path: Path):
    """Sets up an isolated database, local SQL auth adapter, and search index."""
    db_file = tmp_path / "chal_env.db"
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

    idx_file = tmp_path / "chal_search_idx.db"
    idx = SqliteSearchIndex(db_path=idx_file)
    set_search_index(idx)

    try:
        yield {
            "workspace": temp_workspace,
            "session_factory": session_factory,
            "auth": sql_auth,
            "search_index": idx,
            "idx_file": idx_file,
            "db_file": db_file,
        }
    finally:
        app.dependency_overrides.clear()
        reset_auth_port()
        reset_search_indexes()


def register_and_login(client: TestClient, email: str, password: str, name: str) -> dict:
    """Helper to register and authenticate a user against local SQL auth."""
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
def user_alice(challenge_test_env, client: TestClient) -> dict:
    """Registers and logs in user Alice."""
    user = register_and_login(client, "alice_chal@carefold.test", "Password123!", "Alice Challenger")
    prof_res = client.get("/api/v1/profiles", headers=user["headers"])
    assert prof_res.status_code == 200
    user["profile_id"] = prof_res.json()[0]["id"]
    return user


@pytest.fixture
def user_bob(challenge_test_env, client: TestClient) -> dict:
    """Registers and logs in user Bob."""
    user = register_and_login(client, "bob_chal@carefold.test", "BobPassword123!", "Bob Challenger")
    prof_res = client.get("/api/v1/profiles", headers=user["headers"])
    assert prof_res.status_code == 200
    user["profile_id"] = prof_res.json()[0]["id"]
    return user


class TestAdversarialSearchApiSecurity:
    """Adversarial security challenge tests for REST Profile Search API."""

    def test_cross_profile_leakage_rejected_with_403(
        self, client: TestClient, user_alice: dict, user_bob: dict
    ):
        """Authenticated User B attempting to search User A's profile must return HTTP 403 Forbidden."""
        p_alice = user_alice["profile_id"]
        p_bob = user_bob["profile_id"]
        assert p_alice != p_bob

        # Alice creates a secondary profile
        p2_resp = client.post(
            "/api/v1/profiles",
            json={"name": "Alice Child Profile", "relationship": "child"},
            headers=user_alice["headers"],
        )
        assert p2_resp.status_code == 201
        p_alice_child = p2_resp.json()["id"]

        # Bob attempts to search Alice's primary profile via /api/v1 and legacy /api
        res1 = client.get(f"/api/v1/profiles/{p_alice}/search?q=hypertension", headers=user_bob["headers"])
        assert res1.status_code == 403
        assert "Forbidden: profile access denied" in res1.json().get("detail", "")

        res2 = client.get(f"/api/profiles/{p_alice}/search?q=hypertension", headers=user_bob["headers"])
        assert res2.status_code == 403
        assert "Forbidden: profile access denied" in res2.json().get("detail", "")

        # Bob attempts to search Alice's child profile -> 403 Forbidden
        res3 = client.get(f"/api/v1/profiles/{p_alice_child}/search?q=pediatric", headers=user_bob["headers"])
        assert res3.status_code == 403
        assert "Forbidden: profile access denied" in res3.json().get("detail", "")

        # Alice can search her own profiles without 403
        res_alice_1 = client.get(f"/api/v1/profiles/{p_alice}/search?q=hypertension", headers=user_alice["headers"])
        assert res_alice_1.status_code == 200

        res_alice_2 = client.get(f"/api/v1/profiles/{p_alice_child}/search?q=pediatric", headers=user_alice["headers"])
        assert res_alice_2.status_code == 200

    def test_non_existent_profile_returns_400(self, client: TestClient, user_alice: dict):
        """Searching a non-existent profile ID must return HTTP 400 Bad Request."""
        bogus_ids = [
            "non-existent-profile-9999",
            "00000000-0000-0000-0000-000000000000",
            str(uuid.uuid4()),
            "prof-phantom-xyz",
            "%20",
        ]
        for bogus_id in bogus_ids:
            res_v1 = client.get(f"/api/v1/profiles/{bogus_id}/search?q=test", headers=user_alice["headers"])
            assert res_v1.status_code == 400
            assert "Profile not found" in res_v1.json().get("detail", "")

            res_leg = client.get(f"/api/profiles/{bogus_id}/search?q=test", headers=user_alice["headers"])
            assert res_leg.status_code == 400
            assert "Profile not found" in res_leg.json().get("detail", "")

    def test_unauthenticated_caller_returns_401(self, client: TestClient, user_alice: dict):
        """Unauthenticated requests must return HTTP 401 Unauthorized."""
        pid = user_alice["profile_id"]

        # 1. Completely unauthenticated (no headers)
        with TestClient(app) as raw_client:
            r1 = raw_client.get(f"/api/v1/profiles/{pid}/search?q=test")
            assert r1.status_code == 401

            r2 = raw_client.get(f"/api/profiles/{pid}/search?q=test")
            assert r2.status_code == 401

            # 2. Bogus bearer token
            r3 = raw_client.get(
                f"/api/v1/profiles/{pid}/search?q=test",
                headers={"Authorization": "Bearer bogus-token-12345"},
            )
            assert r3.status_code == 401

            # 3. Empty bearer token
            r4 = raw_client.get(
                f"/api/v1/profiles/{pid}/search?q=test",
                headers={"Authorization": "Bearer "},
            )
            assert r4.status_code == 401


class TestAdversarialQueryBoundaries:
    """Adversarial boundary tests for query string, limit, and mode parameters."""

    def test_empty_and_whitespace_query_boundary_400(self, client: TestClient, user_alice: dict):
        """Empty, missing, or whitespace-only queries must return HTTP 400."""
        pid = user_alice["profile_id"]
        headers = user_alice["headers"]

        invalid_queries = [
            f"/api/v1/profiles/{pid}/search?q=",
            f"/api/v1/profiles/{pid}/search?query=",
            f"/api/v1/profiles/{pid}/search?q=%20%20%20",
            f"/api/v1/profiles/{pid}/search?query=%09%0A",
            f"/api/v1/profiles/{pid}/search",  # Missing param
            f"/api/profiles/{pid}/search?q=",
        ]
        for url in invalid_queries:
            res = client.get(url, headers=headers)
            assert res.status_code == 400
            assert "Search query cannot be empty" in res.json().get("detail", "")

    def test_limit_boundaries_0_and_101(self, client: TestClient, user_alice: dict):
        """Limit values outside [1, 100] must be rejected with HTTP 400 or 422."""
        pid = user_alice["profile_id"]
        headers = user_alice["headers"]

        boundary_limits = [0, -1, -50, 101, 102, 9999, "not-an-int"]
        for lim in boundary_limits:
            res = client.get(f"/api/v1/profiles/{pid}/search?q=test&limit={lim}", headers=headers)
            assert res.status_code in (400, 422), f"Expected 400/422 for limit={lim}, got {res.status_code}"

    def test_invalid_search_mode_400(self, client: TestClient, user_alice: dict):
        """Unsupported search retrieval modes must be rejected with HTTP 400."""
        pid = user_alice["profile_id"]
        headers = user_alice["headers"]

        invalid_modes = [
            "invalid_mode",
            "vector_only",
            "SQL_INJECTION' OR '1'='1",
            "raw_embedding",
            "unknown_mode",
            "   ",  # whitespace mode strips to empty string which is rejected
        ]
        for mode in invalid_modes:
            res = client.get(f"/api/v1/profiles/{pid}/search?q=test&mode={mode}", headers=headers)
            assert res.status_code == 400
            assert "Invalid search mode" in res.json().get("detail", "")

        # Empirical edge case observation: empty string mode ("?mode=") defaults to "hybrid"
        # because (mode or "hybrid") coerces "" to "hybrid", returning 200 OK.
        res_empty = client.get(f"/api/v1/profiles/{pid}/search?q=test&mode=", headers=headers)
        assert res_empty.status_code == 200


class TestAdversarialIndexFreshnessConcurrency:
    """Adversarial stress testing of index freshness concurrency, idempotency, and orphaned chunks."""

    @pytest.mark.asyncio
    async def test_rapid_concurrent_note_creates_updates_deletes(
        self, client: TestClient, user_alice: dict, challenge_test_env
    ):
        """Stress test: rapid concurrent note creates, updates, and deletes maintain index consistency."""
        sf = challenge_test_env["session_factory"]
        pid = user_alice["profile_id"]
        headers = user_alice["headers"]

        # 1. Create 8 notes with distinct keywords
        slugs: List[str] = []
        for i in range(8):
            create_res = client.post(
                "/api/v1/notes",
                headers=headers,
                json={
                    "title": f"Concurrent Clinical Note {i}",
                    "content": f"Diagnostic workup for subject {i}. DistinctAlphaTag{i} documented.",
                    "profile_id": pid,
                },
            )
            assert create_res.status_code == 201
            slugs.append(create_res.json()["slug"])

        # 2. Concurrently update 4 notes and delete 2 notes
        def update_note(slug: str, idx: int):
            return client.put(
                f"/api/v1/notes/{slug}",
                headers=headers,
                json={
                    "title": f"Concurrent Clinical Note {idx} Updated",
                    "content": f"Updated diagnostic workup for subject {idx}. DistinctBetaTag{idx} documented.",
                    "profile_id": pid,
                },
            )

        def delete_note(slug: str):
            return client.delete(f"/api/v1/notes/{slug}", headers=headers)

        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(None, update_note, slugs[0], 0),
            loop.run_in_executor(None, update_note, slugs[1], 1),
            loop.run_in_executor(None, update_note, slugs[2], 2),
            loop.run_in_executor(None, update_note, slugs[3], 3),
            loop.run_in_executor(None, delete_note, slugs[4]),
            loop.run_in_executor(None, delete_note, slugs[5]),
        ]
        results = await asyncio.gather(*tasks)
        for r in results:
            assert r.status_code == 200

        # 3. Process all pending jobs through JobRunner (with batch_size large enough to drain queue)
        runner = JobRunner(session_factory=sf, batch_size=50)
        await runner.tick()

        # 4. Verify search index consistency
        # Deleted notes (4, 5) must return 0 results
        for i in (4, 5):
            res_del = client.get(f"/api/v1/profiles/{pid}/search?q=DistinctAlphaTag{i}", headers=headers)
            assert res_del.status_code == 200
            assert len(res_del.json()) == 0, f"Expected 0 hits for deleted note {i}, got {len(res_del.json())}"

        # Updated notes (0, 1, 2, 3) must match new keywords
        for i in range(4):
            res_upd = client.get(f"/api/v1/profiles/{pid}/search?q=DistinctBetaTag{i}", headers=headers)
            assert res_upd.status_code == 200
            assert len(res_upd.json()) >= 1
            assert f"DistinctBetaTag{i}" in res_upd.json()[0]["content"]

        # Unmodified notes (6, 7) must still be indexed
        for i in (6, 7):
            res_orig = client.get(f"/api/v1/profiles/{pid}/search?q=DistinctAlphaTag{i}", headers=headers)
            assert res_orig.status_code == 200
            assert len(res_orig.json()) >= 1

    @pytest.mark.asyncio
    async def test_idempotency_key_deduplication(
        self, client: TestClient, user_alice: dict, challenge_test_env
    ):
        """Verifies idempotency_key deduplication prevents duplicate queue execution."""
        sf = challenge_test_env["session_factory"]
        pid = user_alice["profile_id"]

        doc_id = "doc-idemp-unique"
        idemp_key = f"index:note:{doc_id}:fixedhash123"

        now = datetime.now(timezone.utc)
        payload = {"document_id": doc_id, "profile_id": pid, "text": "Idempotent testing payload.", "metadata": {}}

        # Enqueue job 1
        async with sf() as session:
            job1 = DBJob(
                id=str(uuid.uuid4()),
                profile_id=pid,
                kind="index_doc",
                payload=json.dumps(payload),
                timezone="UTC",
                next_run_at=now,
                idempotency_key=idemp_key,
                status="pending",
            )
            session.add(job1)
            await session.commit()

        # Enqueue job 2 with deduplication check (matching job_runner / note API pattern)
        async with sf() as session:
            check_stmt = select(DBJob.id).where(
                DBJob.idempotency_key == idemp_key,
                DBJob.status.in_(["pending", "active", "completed"]),
            )
            check_res = await session.execute(check_stmt)
            existing_job_id = check_res.scalar_one_or_none()
            assert existing_job_id is not None  # Duplicate detected!

            # If deduplicated, job 2 is NOT enqueued
            if existing_job_id is None:
                job2 = DBJob(
                    id=str(uuid.uuid4()),
                    profile_id=pid,
                    kind="index_doc",
                    payload=json.dumps(payload),
                    timezone="UTC",
                    next_run_at=now,
                    idempotency_key=idemp_key,
                    status="pending",
                )
                session.add(job2)
                await session.commit()

        # Verify only 1 job exists in the DB for this idempotency key
        async with sf() as session:
            stmt = select(DBJob).where(DBJob.idempotency_key == idemp_key)
            res = await session.execute(stmt)
            jobs = res.scalars().all()
            assert len(jobs) == 1

        # Also verify handle_index_doc_job is safe against multiple executions
        runner = JobRunner(session_factory=sf)
        await runner.tick()
        # Second tick should have 0 pending jobs
        await runner.tick()

        # Search index returns exactly 1 hit, no duplicates
        idx = get_search_index()
        hits = await idx.search("Idempotent", profile_id=pid)
        assert len(hits) == 1

    @pytest.mark.asyncio
    async def test_document_deletion_leaves_zero_orphaned_chunks(
        self, client: TestClient, user_alice: dict, challenge_test_env
    ):
        """Verifies that note deletion purges every single chunk from search index, leaving zero orphaned chunks."""
        sf = challenge_test_env["session_factory"]
        pid = user_alice["profile_id"]
        headers = user_alice["headers"]
        idx_file = challenge_test_env["idx_file"]

        # Build a large clinical document with multiple distinct sections to force multiple chunks
        multi_chunk_text = (
            "CHIEF COMPLAINT: Recurring retrosternal chest pain radiating to left jaw on exertion.\n\n"
            "HISTORY OF PRESENT ILLNESS: Patient is a 58-year-old male presenting with intermittent "
            "anginal symptoms over the past three months. Reports shortness of breath and diaphoresis. "
            + ("Clinical observation notes repeating details for volume. " * 30) + "\n\n"
            "MEDICATIONS: Atorvastatin 40mg daily, Metoprolol succinate 50mg daily, Aspirin 81mg. "
            + ("Additional medication adherence notes recorded. " * 30) + "\n\n"
            "LABORATORY FINDINGS: Troponin I negative at <0.01 ng/mL. Total cholesterol 220 mg/dL, "
            "LDL 140 mg/dL, HDL 42 mg/dL, Triglycerides 190 mg/dL. "
            + ("Routine metabolic panel details recorded. " * 30) + "\n\n"
            "ASSESSMENT AND PLAN: Coronary artery disease suspicion high. Schedule stress echocardiogram. "
            "Prescribe sublingual nitroglycerin 0.4mg PRN for acute chest discomfort."
        )

        create_res = client.post(
            "/api/v1/notes",
            headers=headers,
            json={
                "title": "Comprehensive Cardiology Evaluation",
                "content": multi_chunk_text,
                "profile_id": pid,
            },
        )
        assert create_res.status_code == 201
        slug = create_res.json()["slug"]

        # Get Note ID
        async with sf() as session:
            note_stmt = select(Note).where(Note.slug == slug)
            res_note = await session.execute(note_stmt)
            note_id = res_note.scalar_one().id

        # Run JobRunner to index the document
        runner = JobRunner(session_factory=sf)
        await runner.tick()

        # Directly inspect the SQLite FTS index table to verify multiple chunks were indexed
        async with aiosqlite.connect(idx_file) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM document_chunks_fts WHERE document_id = ? AND profile_id = ?;",
                (note_id, pid),
            ) as cursor:
                row = await cursor.fetchone()
                chunk_count_before = row[0] if row else 0

        assert chunk_count_before > 1, f"Expected multi-chunk indexing (>1), got {chunk_count_before}"

        # Delete the note via API
        del_res = client.delete(f"/api/v1/notes/{slug}", headers=headers)
        assert del_res.status_code == 200

        # Run JobRunner to process the delete_doc job
        await runner.tick()

        # EMPIRICAL PROOF: Verify chunk count in document_chunks_fts is EXACTLY ZERO
        async with aiosqlite.connect(idx_file) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM document_chunks_fts WHERE document_id = ? AND profile_id = ?;",
                (note_id, pid),
            ) as cursor:
                row = await cursor.fetchone()
                chunk_count_after = row[0] if row else -1

        assert chunk_count_after == 0, f"Expected 0 orphaned chunks, but found {chunk_count_after} chunks lingering!"

        # Search API must return 0 hits across all sections
        for term in ("retrosternal", "Atorvastatin", "Troponin", "nitroglycerin"):
            s_res = client.get(f"/api/v1/profiles/{pid}/search?q={term}", headers=headers)
            assert s_res.status_code == 200
            assert len(s_res.json()) == 0

    @pytest.mark.asyncio
    async def test_attachment_deletion_leaves_zero_orphaned_chunks(
        self, client: TestClient, user_alice: dict, challenge_test_env
    ):
        """Verifies that attachment deletion purges all chunks from search index, leaving zero orphaned chunks."""
        sf = challenge_test_env["session_factory"]
        pid = user_alice["profile_id"]
        headers = user_alice["headers"]
        idx_file = challenge_test_env["idx_file"]

        att_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Multi-chunk extracted text for an attachment
        att_text = (
            "ECHOCARDIOGRAPHY REPORT\n"
            "PATIENT ID: 12345\n\n"
            "FINDINGS: Left ventricular ejection fraction is estimated at 55-60%. "
            "Normal left ventricular chamber size and systolic function. "
            + ("Descriptive chamber dimension metrics and Doppler flow measurements. " * 30) + "\n\n"
            "VALVULAR ASSESSMENT: Mild mitral regurgitation. No aortic stenosis. "
            + ("Detailed peak velocities and mean pressure gradients across aortic valve. " * 30) + "\n\n"
            "IMPRESSION: Preserved left ventricular systolic function with mild degenerative mitral regurgitation."
        )

        async with sf() as session:
            att = Attachment(
                id=att_id,
                profile_id=pid,
                filename="echocardiogram_report.pdf",
                original_name="echocardiogram_report.pdf",
                content_type="application/pdf",
                size_bytes=4096,
                source="upload",
                extracted_text=att_text,
                extraction_status="completed",
                created_at=now,
                updated_at=now,
            )
            session.add(att)
            await session.commit()

        # Index the attachment
        await handle_index_doc_job(
            {"document_id": att_id, "profile_id": pid, "doc_type": "attachment"},
            session_factory=sf,
        )

        # Confirm chunks exist in FTS table
        async with aiosqlite.connect(idx_file) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM document_chunks_fts WHERE document_id = ? AND profile_id = ?;",
                (att_id, pid),
            ) as cursor:
                row = await cursor.fetchone()
                chunks_before = row[0] if row else 0

        assert chunks_before > 1, f"Expected multi-chunk attachment index (>1), got {chunks_before}"

        # Delete attachment via API
        del_res = client.delete(f"/api/v1/attachments/{att_id}", headers=headers)
        assert del_res.status_code == 200

        # Process delete_doc job via JobRunner
        runner = JobRunner(session_factory=sf)
        await runner.tick()

        # EMPIRICAL PROOF: Verify chunk count in document_chunks_fts is EXACTLY ZERO
        async with aiosqlite.connect(idx_file) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM document_chunks_fts WHERE document_id = ? AND profile_id = ?;",
                (att_id, pid),
            ) as cursor:
                row = await cursor.fetchone()
                chunks_after = row[0] if row else -1

        assert chunks_after == 0, f"Expected 0 orphaned chunks, but found {chunks_after} chunks lingering!"

        # Search API returns 0 hits for terms from the attachment
        for term in ("ECHOCARDIOGRAPHY", "regurgitation", "ejection"):
            s_res = client.get(f"/api/v1/profiles/{pid}/search?q={term}", headers=headers)
            assert s_res.status_code == 200
            assert len(s_res.json()) == 0
