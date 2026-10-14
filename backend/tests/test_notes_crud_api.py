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

"""Unit and integration tests for Notes CRUD and database persistence."""

import asyncio
import pytest
from fastapi.testclient import TestClient

from carefold.db import init_db


@pytest.fixture(autouse=True)
def setup_db_for_notes():
    """Initializes database and cleans up notes before running notes tests and cleans up after."""
    asyncio.run(init_db())
    yield
    async def cleanup():
        from carefold.db.session import get_session_factory
        from carefold.db.models import Note
        from sqlalchemy import delete
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(delete(Note))
            await session.commit()
    asyncio.run(cleanup())


@pytest.fixture
def test_profile_id(client: TestClient) -> str:
    """Provisions a test profile for CRUD notes tests."""
    from carefold.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER
    from carefold.db.models import User
    from carefold.db.session import get_session_factory

    async def _ensure_steward():
        factory = get_session_factory()
        async with factory() as session:
            user = await session.get(User, DEFAULT_STEWARD_USER.id)
            if not user:
                user = User(
                    id=DEFAULT_STEWARD_USER.id,
                    email="steward@carefold.ai",
                    username="steward",
                    hashed_password="mock",
                    role="steward",
                    status="active",
                    auth_provider="disabled",
                )
                session.add(user)
                await session.commit()

    asyncio.run(_ensure_steward())
    resp = client.post("/api/profiles", json={"name": "Patient", "relationship": "self"})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_create_and_get_note(client: TestClient, test_profile_id: str):
    """Verifies creating a note and retrieving its detail."""
    payload = {
        "title": "Hypertension Log & Medication Checklist",
        "content": "Check BP daily at 8am and 8pm.\nBring log to cardiologist.",
        "type": "clinical_prep",
        "tags": ["cardiology", "hypertension"],
        "profile_id": test_profile_id,
    }
    create_resp = client.post("/api/notes", json=payload)
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["title"] == "Hypertension Log & Medication Checklist"
    slug = created["slug"]
    assert slug is not None

    # Get note detail
    get_resp = client.get(f"/api/notes/{slug}")
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["title"] == "Hypertension Log & Medication Checklist"
    assert "Check BP daily" in detail["content"]


def test_list_and_update_notes(client: TestClient, test_profile_id: str):
    """Verifies listing notes and updating a note."""
    create_resp = client.post(
        "/api/notes",
        json={"title": "Blood Sugar Chart", "content": "Fasting glucose targets.", "profile_id": test_profile_id},
    )
    assert create_resp.status_code == 201
    slug = create_resp.json()["slug"]

    # List notes
    list_resp = client.get("/api/notes")
    assert list_resp.status_code == 200
    notes = list_resp.json()
    assert any(n["slug"] == slug for n in notes)

    # Update note
    put_resp = client.put(
        f"/api/notes/{slug}",
        json={"content": "Fasting glucose target: 80-130 mg/dL."},
    )
    assert put_resp.status_code == 200
    assert "80-130 mg/dL" in put_resp.json()["content"]


def test_delete_note(client: TestClient, test_profile_id: str):
    """Verifies deleting a note."""
    create_resp = client.post(
        "/api/notes",
        json={"title": "To Delete Note", "content": "Ephemeral content.", "profile_id": test_profile_id},
    )
    assert create_resp.status_code == 201
    slug = create_resp.json()["slug"]

    del_resp = client.delete(f"/api/notes/{slug}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    get_again = client.get(f"/api/notes/{slug}")
    assert get_again.status_code == 404
