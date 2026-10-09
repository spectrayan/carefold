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

"""Unit and integration tests for Agents CRUD and Agent Knowledge Base documentation endpoints."""

import asyncio
import pytest
from fastapi.testclient import TestClient

from carefold.db import init_db
from carefold.db.seeding import sync_bundled_assets_to_db


@pytest.fixture(autouse=True)
def setup_db_for_agents():
    """Initializes and seeds database before running agent tests and cleans up after."""
    asyncio.run(init_db())
    asyncio.run(sync_bundled_assets_to_db())
    yield
    async def cleanup():
        from carefold.db.session import get_session_factory
        from carefold.db.models import Agent, KnowledgeBase
        from sqlalchemy import delete
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(delete(KnowledgeBase).where(KnowledgeBase.type == "user"))
            await session.execute(delete(Agent).where(Agent.type == "user"))
            await session.commit()
        from carefold.memory.factory import reset_memory_ports
        reset_memory_ports()
    asyncio.run(cleanup())


def test_list_agents(client: TestClient):
    """Verifies that GET /api/agents returns specialist agents."""
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert len(agents) > 0
    # cardiology-guide should exist
    cardio = next((a for a in agents if a["id"] == "cardiology-guide"), None)
    assert cardio is not None
    assert cardio["is_bundled"] is True
    assert cardio["type"] in ("bundled", "system")


def test_create_custom_agent(client: TestClient):
    """Verifies creating a custom specialist agent."""
    agent_payload = {
        "id": "custom-sleep-coach",
        "title": "Sleep & Circadian Rhythm Guide",
        "description": "Specialist in insomnia prep and sleep hygiene logs.",
        "persona": "You are a sleep hygiene guide helping patients prepare for sleep study appointments.",
        "model": "ollama:llama3.2",
        "skills": ["habit-checkin"],
        "tools": ["attach-read", "workspace-note"],
        "starters": ["How do I prepare for a sleep study?"],
        "domain": "wellness",
        "category": "habits",
        "risk_class": "wellness",
        "tags": ["sleep", "insomnia", "circadian"],
        "icon": "Moon",
        "can_delegate": False,
        "max_iterations": 3,
        "is_public": True,
    }

    create_resp = client.post("/api/agents", json=agent_payload)
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["id"] == "custom-sleep-coach"
    assert created["type"] == "user"
    assert created["is_bundled"] is False
    assert "attach-read" in created["effectiveTools"]

    # Duplicate ID returns 409
    dup_resp = client.post("/api/agents", json=agent_payload)
    assert dup_resp.status_code == 409


def test_get_agent_detail(client: TestClient):
    """Verifies getting agent detail with resolved skills and tool definitions."""
    resp = client.get("/api/agents/cardiology-guide?allow_clinical=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "cardiology-guide"
    assert len(data["skills"]) > 0
    assert len(data["effectiveTools"]) > 0


def test_update_agent(client: TestClient):
    """Verifies updating a custom agent."""
    agent_payload = {
        "id": "custom-migraine-guide",
        "title": "Migraine Guide",
        "description": "Initial migraine guide.",
        "persona": "Initial persona.",
    }
    client.post("/api/agents", json=agent_payload)

    put_resp = client.put(
        "/api/agents/custom-migraine-guide",
        json={
            "title": "Headache & Migraine Specialist",
            "description": "Comprehensive pre-consultation guide for neurological headaches.",
        },
    )
    assert put_resp.status_code == 200
    updated = put_resp.json()
    assert updated["title"] == "Headache & Migraine Specialist"
    assert "neurological headaches" in updated["description"]


def test_delete_agent(client: TestClient):
    """Verifies deleting a custom agent."""
    agent_payload = {
        "id": "temp-agent",
        "title": "Temporary Agent",
        "description": "To be removed.",
    }
    client.post("/api/agents", json=agent_payload)

    del_resp = client.delete("/api/agents/temp-agent")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    get_resp = client.get("/api/agents/temp-agent")
    assert get_resp.status_code == 404


def test_prevent_delete_bundled_agent(client: TestClient):
    """Verifies that bundled agents cannot be deleted by non-admin users."""
    del_resp = client.delete("/api/agents/cardiology-guide")
    assert del_resp.status_code in (403, 404)


def test_agent_knowledge_base_docs_crud_and_skill_inheritance(client: TestClient):
    """Verifies agent-level direct knowledge base docs and skill docs inclusion."""
    # 1. Create agent
    agent_payload = {
        "id": "endocrinology-navigator-custom",
        "title": "Endocrine Navigator",
        "description": "Thyroid and diabetes prep.",
        "skills": ["cardiology-prep"],  # references cardiology-prep skill docs
    }
    client.post("/api/agents", json=agent_payload)

    # 2. Add direct agent doc
    doc_payload = {
        "name": "thyroid_panel_guide.md",
        "title": "Thyroid Blood Panel Guide",
        "content": "# Thyroid Panel\nUnderstanding TSH, Free T3, and Free T4.",
        "format": "markdown",
    }
    post_doc_resp = client.post(
        "/api/agents/endocrinology-navigator-custom/docs",
        json=doc_payload,
    )
    assert post_doc_resp.status_code == 201
    created_doc = post_doc_resp.json()
    assert created_doc["name"] == "thyroid_panel_guide.md"

    # 3. List docs (returns direct_docs and skill_docs)
    list_docs_resp = client.get("/api/agents/endocrinology-navigator-custom/docs")
    assert list_docs_resp.status_code == 200
    docs_data = list_docs_resp.json()
    assert len(docs_data["direct_docs"]) >= 1
    assert any(d["name"] == "thyroid_panel_guide.md" for d in docs_data["direct_docs"])
    # Should include cardiology-prep reference docs in skill_docs
    assert len(docs_data["skill_docs"]) > 0

    # 4. Get direct doc detail
    get_doc_resp = client.get("/api/agents/endocrinology-navigator-custom/docs/thyroid_panel_guide.md")
    assert get_doc_resp.status_code == 200
    assert "TSH, Free T3" in get_doc_resp.json()["content"]

    # 5. Update direct doc
    put_doc_resp = client.put(
        "/api/agents/endocrinology-navigator-custom/docs/thyroid_panel_guide.md",
        json={"content": "# Updated Thyroid Panel\nIncludes antibody testing."},
    )
    assert put_doc_resp.status_code == 200
    assert "antibody testing" in put_doc_resp.json()["content"]

    # 6. Delete direct doc
    del_doc_resp = client.delete("/api/agents/endocrinology-navigator-custom/docs/thyroid_panel_guide.md")
    assert del_doc_resp.status_code == 200
    assert del_doc_resp.json()["deleted"] is True
