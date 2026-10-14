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

"""Unit and integration test suite for Index Freshness Automation (AU-27, Phase4).

Verifies:
1. JobRunner automatically registers index_doc and delete_doc handlers.
2. handle_index_doc_job indexes text payload, DB notes, and DB attachments.
3. handle_delete_doc_job purges documents from the search index idempotently.
4. Note create/update enqueues index_doc job.
5. Note delete enqueues delete_doc job.
6. Attachment delete enqueues delete_doc job.
7. JobRunner.tick() processes pending index_doc and delete_doc jobs end-to-end.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import AsyncIterator
import uuid
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
async def freshness_test_env(temp_workspace: Path, monkeypatch, tmp_path: Path):
    """Sets up an isolated database, local SQL auth adapter, and search index."""
    db_file = tmp_path / "freshness_test.db"
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

    idx_file = tmp_path / "test_freshness_search_idx.db"
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
def auth_user(freshness_test_env, client: TestClient) -> dict:
    """Registers and logs in a standard test user Alice with a primary profile."""
    user = register_and_login(client, "alice_freshness@carefold.test", "Password123!", "Alice Fresh")
    prof_res = client.get("/api/v1/profiles", headers=user["headers"])
    assert prof_res.status_code == 200
    user["profile_id"] = prof_res.json()[0]["id"]
    return user


class TestJobRunnerHandlerRegistration:
    """Verifies that JobRunner registers the required handlers for search freshness."""

    def test_runner_registers_index_and_delete_handlers(self):
        runner = JobRunner()
        assert runner.has_handler("index_doc") is True
        assert runner.has_handler("delete_doc") is True
        assert callable(runner.get_handler("index_doc"))
        assert callable(runner.get_handler("delete_doc"))


class TestHandleIndexDocJob:
    """Verifies index_doc execution across payloads, Notes, and Attachments."""

    @pytest.mark.asyncio
    async def test_handle_index_doc_with_payload_text(self, freshness_test_env, auth_user: dict):
        pid = auth_user["profile_id"]
        doc_id = "doc-explicit-1"
        payload = {
            "document_id": doc_id,
            "profile_id": pid,
            "text": "Cardiology clinic note: prescribed Lisinopril 20mg for arterial hypertension.",
            "metadata": {"source": "clinical_note", "category": "cardiology"},
        }

        await handle_index_doc_job(payload, session_factory=freshness_test_env["session_factory"])

        idx = get_search_index()
        hits = await idx.search("Lisinopril", profile_id=pid)
        assert len(hits) == 1
        assert hits[0].document_id == doc_id
        assert "Lisinopril" in hits[0].content
        assert hits[0].profile_id == pid

    @pytest.mark.asyncio
    async def test_handle_index_doc_with_db_note(self, freshness_test_env, auth_user: dict):
        sf = freshness_test_env["session_factory"]
        pid = auth_user["profile_id"]
        note_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with sf() as session:
            note = Note(
                id=note_id,
                profile_id=pid,
                title="Pulmonology Consultation",
                slug="pulmonology-consultation",
                content="Spirometry testing shows mild obstructive airflow limitation. Prescribed Albuterol MDI.",
                type="clinical",
                created_at=now,
                updated_at=now,
            )
            session.add(note)
            await session.commit()

        job_payload = {
            "document_id": note_id,
            "profile_id": pid,
            "doc_type": "note",
        }
        await handle_index_doc_job(job_payload, session_factory=sf)

        idx = get_search_index()
        hits = await idx.search("Albuterol", profile_id=pid)
        assert len(hits) >= 1
        assert hits[0].document_id == note_id
        assert hits[0].metadata.get("title") == "Pulmonology Consultation"
        assert hits[0].metadata.get("source") == "clinical_note"

    @pytest.mark.asyncio
    async def test_handle_index_doc_with_db_attachment(self, freshness_test_env, auth_user: dict):
        sf = freshness_test_env["session_factory"]
        pid = auth_user["profile_id"]
        att_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with sf() as session:
            att = Attachment(
                id=att_id,
                profile_id=pid,
                filename="lab_results.pdf",
                original_name="lab_results.pdf",
                content_type="application/pdf",
                size_bytes=1024,
                source="upload",
                extracted_text="Thyroid Panel: TSH 2.5 mIU/L, Free T4 1.2 ng/dL. Normal limits.",
                extraction_status="completed",
                created_at=now,
                updated_at=now,
            )
            session.add(att)
            await session.commit()

        job_payload = {
            "document_id": att_id,
            "profile_id": pid,
            "doc_type": "attachment",
        }
        await handle_index_doc_job(job_payload, session_factory=sf)

        idx = get_search_index()
        hits = await idx.search("Thyroid", profile_id=pid)
        assert len(hits) >= 1
        assert hits[0].document_id == att_id
        assert hits[0].metadata.get("filename") == "lab_results.pdf"

    @pytest.mark.asyncio
    async def test_handle_index_doc_missing_doc_graceful(self, freshness_test_env, auth_user: dict):
        sf = freshness_test_env["session_factory"]
        # Non-existent document should log and exit cleanly without raising an error
        await handle_index_doc_job(
            {"document_id": "missing-doc-id-9999", "profile_id": auth_user["profile_id"]},
            session_factory=sf,
        )

    @pytest.mark.asyncio
    async def test_handle_index_doc_validation_fail_closed(self, freshness_test_env):
        with pytest.raises(ValueError, match="missing 'document_id'"):
            await handle_index_doc_job({"profile_id": "pid-test"})

        with pytest.raises(ValueError, match="missing 'profile_id'"):
            await handle_index_doc_job({"document_id": "doc-1"})


class TestHandleDeleteDocJob:
    """Verifies delete_doc removes documents from SearchIndex and handles validation."""

    @pytest.mark.asyncio
    async def test_handle_delete_doc_purges_index(self, freshness_test_env, auth_user: dict):
        pid = auth_user["profile_id"]
        doc_id = "doc-to-delete-1"

        idx = get_search_index()
        await idx.index_document(
            document_id=doc_id,
            text="Gastroenterology visit notes on acid reflux symptoms.",
            metadata={"source": "clinical_note"},
            profile_id=pid,
        )

        hits_before = await idx.search("reflux", profile_id=pid)
        assert len(hits_before) >= 1

        await handle_delete_doc_job({"document_id": doc_id, "profile_id": pid})

        hits_after = await idx.search("reflux", profile_id=pid)
        assert len(hits_after) == 0

    @pytest.mark.asyncio
    async def test_handle_delete_doc_idempotent(self, freshness_test_env, auth_user: dict):
        # Deleting non-existent document should succeed cleanly
        await handle_delete_doc_job({"document_id": "doc-non-existent", "profile_id": auth_user["profile_id"]})

    @pytest.mark.asyncio
    async def test_handle_delete_doc_validation_fail_closed(self, freshness_test_env):
        with pytest.raises(ValueError, match="missing 'document_id'"):
            await handle_delete_doc_job({"profile_id": "pid-test"})

        with pytest.raises(ValueError, match="missing 'profile_id'"):
            await handle_delete_doc_job({"document_id": "doc-1"})


class TestApiLifecycleEnqueuing:
    """Verifies that Note and Attachment lifecycle operations enqueue DB jobs."""

    @pytest.mark.asyncio
    async def test_note_create_and_update_enqueues_index_doc(
        self, client: TestClient, auth_user: dict, freshness_test_env
    ):
        sf = freshness_test_env["session_factory"]
        pid = auth_user["profile_id"]

        # 1. Create Note
        create_res = client.post(
            "/api/v1/notes",
            headers=auth_user["headers"],
            json={
                "title": "Dermatology Eczema Assessment",
                "content": "Mild atopic dermatitis flare on flexural surfaces. Prescribed hydrocortisone 1%.",
                "profile_id": pid,
            },
        )
        assert create_res.status_code == 201
        slug = create_res.json()["slug"]

        # Retrieve Note id from DB
        async with sf() as session:
            note_stmt = select(Note).where(Note.slug == slug)
            res_note = await session.execute(note_stmt)
            created_note = res_note.scalar_one()
            note_id = created_note.id

            # Verify index_doc job was enqueued in DB
            stmt = select(DBJob).where(DBJob.kind == "index_doc")
            res = await session.execute(stmt)
            jobs = res.scalars().all()
            matching = [j for j in jobs if j.payload_dict.get("document_id") == note_id]
            assert len(matching) >= 1
            job = matching[0]
            assert job.status == "pending"
            assert job.profile_id == pid
            assert job.payload_dict["doc_type"] == "note"

        # 2. Update Note
        update_res = client.put(
            f"/api/v1/notes/{slug}",
            headers=auth_user["headers"],
            json={
                "title": "Dermatology Eczema Assessment",
                "content": "Updated: switched patient to triamcinolone acetonide 0.1% cream.",
                "profile_id": pid,
            },
        )
        assert update_res.status_code == 200

        # Verify a second index_doc job was enqueued for the update
        async with sf() as session:
            stmt = select(DBJob).where(DBJob.kind == "index_doc")
            res = await session.execute(stmt)
            jobs = res.scalars().all()
            matching = [j for j in jobs if j.payload_dict.get("document_id") == note_id]
            assert len(matching) >= 2

    @pytest.mark.asyncio
    async def test_note_delete_enqueues_delete_doc(
        self, client: TestClient, auth_user: dict, freshness_test_env
    ):
        sf = freshness_test_env["session_factory"]
        pid = auth_user["profile_id"]

        # Create note
        create_res = client.post(
            "/api/v1/notes",
            headers=auth_user["headers"],
            json={
                "title": "Note to be deleted",
                "content": "Temporary scratchpad note content.",
                "profile_id": pid,
            },
        )
        assert create_res.status_code == 201
        slug = create_res.json()["slug"]

        async with sf() as session:
            res_note = await session.execute(select(Note).where(Note.slug == slug))
            note_id = res_note.scalar_one().id

        # Delete note
        del_res = client.delete(
            f"/api/v1/notes/{slug}",
            headers=auth_user["headers"],
        )
        assert del_res.status_code == 200

        # Verify delete_doc job was enqueued in DB
        async with sf() as session:
            stmt = select(DBJob).where(DBJob.kind == "delete_doc")
            res = await session.execute(stmt)
            jobs = res.scalars().all()
            matching = [j for j in jobs if j.payload_dict.get("document_id") == note_id]
            assert len(matching) >= 1
            job = matching[0]
            assert job.status == "pending"
            assert job.profile_id == pid

    @pytest.mark.asyncio
    async def test_attachment_delete_enqueues_delete_doc(
        self, client: TestClient, auth_user: dict, freshness_test_env
    ):
        sf = freshness_test_env["session_factory"]
        pid = auth_user["profile_id"]
        att_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Create attachment in DB
        async with sf() as session:
            att = Attachment(
                id=att_id,
                profile_id=pid,
                filename="cardio_ecg.pdf",
                original_name="cardio_ecg.pdf",
                content_type="application/pdf",
                size_bytes=2048,
                source="upload",
                extracted_text="Sinus bradycardia observed.",
                extraction_status="completed",
                created_at=now,
                updated_at=now,
            )
            session.add(att)
            await session.commit()

        # Delete attachment via API
        del_res = client.delete(
            f"/api/v1/attachments/{att_id}",
            headers=auth_user["headers"],
        )
        assert del_res.status_code == 200

        # Verify delete_doc job was enqueued in DB
        async with sf() as session:
            stmt = select(DBJob).where(DBJob.kind == "delete_doc")
            res = await session.execute(stmt)
            jobs = res.scalars().all()
            matching = [j for j in jobs if j.payload_dict.get("document_id") == att_id]
            assert len(matching) >= 1
            job = matching[0]
            assert job.status == "pending"
            assert job.profile_id == pid


class TestEndToEndFreshnessAutomation:
    """Verifies JobRunner.tick() processes enqueued jobs and updates the REST search API."""

    @pytest.mark.asyncio
    async def test_end_to_end_note_indexing_and_search(
        self, client: TestClient, auth_user: dict, freshness_test_env
    ):
        sf = freshness_test_env["session_factory"]
        pid = auth_user["profile_id"]

        # 1. Create a note via API
        create_res = client.post(
            "/api/v1/notes",
            headers=auth_user["headers"],
            json={
                "title": "Neurology Migraine Evaluation",
                "content": "Patient reports frequent throbbing migraines with aura. Prescribed Sumatriptan 50mg.",
                "profile_id": pid,
            },
        )
        assert create_res.status_code == 201
        slug = create_res.json()["slug"]

        # Before job run: REST search returns 0 hits
        s_before = client.get(f"/api/v1/profiles/{pid}/search?q=Sumatriptan", headers=auth_user["headers"])
        assert s_before.status_code == 200
        assert len(s_before.json()) == 0

        # 2. Run JobRunner tick to process pending index_doc job
        runner = JobRunner(session_factory=sf)
        await runner.tick()

        # After job run: REST search finds the note!
        s_after = client.get(f"/api/v1/profiles/{pid}/search?q=Sumatriptan", headers=auth_user["headers"])
        assert s_after.status_code == 200
        hits = s_after.json()
        assert len(hits) >= 1
        assert "Sumatriptan" in hits[0]["content"]

        # 3. Delete the note via API
        del_res = client.delete(
            f"/api/v1/notes/{slug}",
            headers=auth_user["headers"],
        )
        assert del_res.status_code == 200

        # 4. Run JobRunner tick to process pending delete_doc job
        await runner.tick()

        # After delete job run: REST search returns 0 hits!
        s_del = client.get(f"/api/v1/profiles/{pid}/search?q=Sumatriptan", headers=auth_user["headers"])
        assert s_del.status_code == 200
        assert len(s_del.json()) == 0
