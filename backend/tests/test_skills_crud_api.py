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

"""Unit and integration tests for Skills CRUD and Knowledge Base documentation endpoints."""

import asyncio
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from carefold.db import init_db
from carefold.db.seeding import sync_bundled_assets_to_db


@pytest.fixture(autouse=True)
def setup_db_for_skills():
    """Initializes and seeds database before running skill tests and cleans up after."""
    asyncio.run(init_db())
    asyncio.run(sync_bundled_assets_to_db())
    yield
    async def cleanup():
        from carefold.db.session import get_session_factory
        from carefold.db.models import KnowledgeBase, Skill
        from sqlalchemy import delete
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(delete(KnowledgeBase).where(KnowledgeBase.type == "user"))
            await session.execute(delete(Skill).where(Skill.type == "user"))
            await session.commit()
        from carefold.memory.factory import reset_memory_ports
        reset_memory_ports()
    asyncio.run(cleanup())


def test_list_skills(client: TestClient):
    """Verifies that GET /api/skills returns skills including bundled skills."""
    resp = client.get("/api/skills")
    assert resp.status_code == 200
    skills = resp.json()
    assert len(skills) > 0
    # Cardiology prep should exist
    cardio = next((s for s in skills if s["id"] == "cardiology-prep"), None)
    assert cardio is not None
    assert cardio["is_bundled"] is True
    assert cardio["type"] in ("bundled", "system")


def test_create_skill_with_mandatory_disclosures(client: TestClient):
    """Verifies that creating a skill automatically enforces mandatory non-clinical safety disclosures."""
    skill_payload = {
        "id": "custom-pediatric-prep",
        "name": "custom-pediatric-prep",
        "title": "Custom Pediatric Visit Prep",
        "description": "Preparation aid for pediatric doctor consultations.",
        "domain": "clinical",
        "category": "pediatrics",
        "risk_class": "clinical_assist",
        "tags": ["pediatrics", "children", "prep"],
        "tools": ["attach-read", "workspace-note"],
        "instructions": "Review growth charts, vaccination milestones, and child behavioral questions.",
        "forbidden": ["Do not diagnose autism spectrum disorder"],
        "is_public": True,
    }

    create_resp = client.post("/api/skills", json=skill_payload)
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["id"] == "custom-pediatric-prep"
    assert created["type"] == "user"
    assert created["is_bundled"] is False

    # Check that safety disclosure lines are auto-appended
    assert "Not a clinician and not emergency care" in created["instructions"]
    assert "If this is an emergency, contact local emergency services" in created["instructions"]
    assert "Do not change medication without the prescribing clinician" in created["instructions"]

    # Verify duplicate creation returns 409 Conflict
    dup_resp = client.post("/api/skills", json=skill_payload)
    assert dup_resp.status_code == 409


def test_get_skill_detail(client: TestClient):
    """Verifies reading skill detail by ID."""
    resp = client.get("/api/skills/cardiology-prep")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "cardiology-prep"
    assert data["is_bundled"] is True
    assert len(data["references"]) > 0


def test_update_skill(client: TestClient):
    """Verifies updating an existing custom skill."""
    skill_payload = {
        "id": "custom-diet-prep",
        "name": "custom-diet-prep",
        "title": "Diet Prep",
        "description": "Initial description.",
        "instructions": "Initial instructions.",
    }
    client.post("/api/skills", json=skill_payload)

    update_payload = {
        "title": "Updated Dietary Prep Guide",
        "description": "Enhanced clinical diet prep.",
        "instructions": "Updated instructions with checklist.",
    }
    put_resp = client.put("/api/skills/custom-diet-prep", json=update_payload)
    assert put_resp.status_code == 200
    updated = put_resp.json()
    assert updated["title"] == "Updated Dietary Prep Guide"
    assert updated["description"] == "Enhanced clinical diet prep."
    assert "Not a clinician and not emergency care" in updated["instructions"]


def test_delete_skill(client: TestClient):
    """Verifies deleting a custom skill removes it from listing."""
    skill_payload = {
        "id": "to-delete-skill",
        "name": "to-delete-skill",
        "title": "Temporary Skill",
        "description": "Will be deleted.",
    }
    client.post("/api/skills", json=skill_payload)

    del_resp = client.delete("/api/skills/to-delete-skill")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    get_resp = client.get("/api/skills/to-delete-skill")
    assert get_resp.status_code == 404


def test_prevent_delete_bundled_skill(client: TestClient):
    """Verifies that non-admin users cannot delete bundled skills."""
    # When role is member
    del_resp = client.delete("/api/skills/cardiology-prep")
    assert del_resp.status_code in (403, 404)


def test_skill_knowledge_base_docs_crud(client: TestClient):
    """Verifies CRUD operations for knowledge base reference documents attached to a skill."""
    # 1. Create skill
    skill_payload = {
        "id": "oncology-support-prep",
        "name": "oncology-support-prep",
        "title": "Oncology Support",
        "description": "Support guide for oncology appointments.",
    }
    client.post("/api/skills", json=skill_payload)

    # 2. Add reference doc
    doc_payload = {
        "name": "chemo_side_effects_log.md",
        "title": "Chemotherapy Side Effects Log",
        "content": "# Chemo Tracking Log\nRecord daily symptoms and fatigue levels.",
        "format": "markdown",
    }
    post_doc_resp = client.post("/api/skills/oncology-support-prep/docs", json=doc_payload)
    assert post_doc_resp.status_code == 201
    created_doc = post_doc_resp.json()
    assert created_doc["name"] == "chemo_side_effects_log.md"
    assert created_doc["title"] == "Chemotherapy Side Effects Log"

    # 3. List docs
    list_docs_resp = client.get("/api/skills/oncology-support-prep/docs")
    assert list_docs_resp.status_code == 200
    docs = list_docs_resp.json()
    assert any(d["name"] == "chemo_side_effects_log.md" for d in docs)

    # 4. Get doc detail
    get_doc_resp = client.get("/api/skills/oncology-support-prep/docs/chemo_side_effects_log.md")
    assert get_doc_resp.status_code == 200
    assert "Chemo Tracking Log" in get_doc_resp.json()["content"]

    # 5. Update doc
    put_doc_resp = client.put(
        "/api/skills/oncology-support-prep/docs/chemo_side_effects_log.md",
        json={"content": "# Updated Chemo Tracking Log\nRecord severity 1-10."},
    )
    assert put_doc_resp.status_code == 200
    assert "severity 1-10" in put_doc_resp.json()["content"]

    # 6. Delete doc
    del_doc_resp = client.delete("/api/skills/oncology-support-prep/docs/chemo_side_effects_log.md")
    assert del_doc_resp.status_code == 200
    assert del_doc_resp.json()["deleted"] is True

    # 7. Verify 404 after deletion
    get_again = client.get("/api/skills/oncology-support-prep/docs/chemo_side_effects_log.md")
    assert get_again.status_code == 404
