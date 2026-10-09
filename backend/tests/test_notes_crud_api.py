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


def test_create_and_get_note(client: TestClient):
    """Verifies creating a note and retrieving its detail."""
    payload = {
        "title": "Hypertension Log & Medication Checklist",
        "content": "Check BP daily at 8am and 8pm.\nBring log to cardiologist.",
        "type": "clinical_prep",
        "tags": ["cardiology", "hypertension"],
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


def test_list_and_update_notes(client: TestClient):
    """Verifies listing notes and updating a note."""
    create_resp = client.post(
        "/api/notes",
        json={"title": "Blood Sugar Chart", "content": "Fasting glucose targets."},
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


def test_delete_note(client: TestClient):
    """Verifies deleting a note."""
    create_resp = client.post(
        "/api/notes",
        json={"title": "To Delete Note", "content": "Ephemeral content."},
    )
    slug = create_resp.json()["slug"]

    del_resp = client.delete(f"/api/notes/{slug}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    get_again = client.get(f"/api/notes/{slug}")
    assert get_again.status_code == 404
