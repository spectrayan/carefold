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

"""System Agents API Endpoints Test Suite.

Validates:
1. GET /api/agents behavior:
   - Default request excludes system agents (only benefits-guide, habit-companion, visit-steward returned).
   - include_hidden=true includes orchestrator, document-extractor, skill-generator, suggestion-generator.
   - _template is never returned in either case.
2. GET /api/agents/{agent_id}:
   - GET /api/agents/orchestrator returns 200 with detail.
   - GET /api/agents/document-extractor returns 200 with detail.
   - Path traversal / dot / underscore queries:
     - GET /api/agents/_system returns 404.
     - GET /api/agents/_template returns 404.
     - GET /api/agents/.hidden returns 404.
     - URL-encoded path traversal (%2e, %2e%2e) returns 404.
"""

from __future__ import annotations

from typing import Set
import pytest
from fastapi.testclient import TestClient

EXPECTED_PUBLIC_AGENT_IDS: Set[str] = {
    "benefits-guide",
    "habit-companion",
    "visit-steward",
    # M1 Core Organ Navigators
    "cardiology-guide",
    "pulmonology-guide",
    "neurology-guide",
    "gastro-guide",
    "nephrology-guide",
    "endocrinology-guide",
    "ortho-guide",
    "derma-guide",
    # M2 Extended Specialty Navigators
    "oncology-navigator",
    "rheuma-guide",
    "urology-guide",
    "eye-guide",
    "ent-guide",
    # M3 Healthcare Administration Stewards
    "prior-auth-navigator",
    "claims-appeals-guide",
    "records-coordinator",
    "formulary-guide",
}

EXPECTED_SYSTEM_AGENT_IDS: Set[str] = {
    "orchestrator",
    "document-extractor",
    "skill-generator",
    "suggestion-generator",
    # M4 System Infrastructure Agents
    "triage-auditor",
    "quality-reviewer",
}


def test_get_agents_default_excludes_system_agents(client: TestClient) -> None:
    """Default GET /api/agents returns only public agents; system agents and _template are excluded."""
    res = client.get("/api/agents")
    assert res.status_code == 200
    agents = res.json()
    returned_ids = {a["id"] for a in agents}

    assert returned_ids == EXPECTED_PUBLIC_AGENT_IDS
    assert not (returned_ids & EXPECTED_SYSTEM_AGENT_IDS)
    assert "_template" not in returned_ids
    assert "_system" not in returned_ids

    for a in agents:
        assert not a.get("hidden", False)


def test_get_agents_include_hidden_true(client: TestClient) -> None:
    """GET /api/agents?include_hidden=true returns public and system agents; _template is NEVER returned."""
    for query in ["include_hidden=true", "include_hidden=True", "include_hidden=1"]:
        res = client.get(f"/api/agents?{query}")
        assert res.status_code == 200
        agents = res.json()
        returned_ids = {a["id"] for a in agents}

        expected_all = EXPECTED_PUBLIC_AGENT_IDS | EXPECTED_SYSTEM_AGENT_IDS
        assert returned_ids == expected_all
        assert "_template" not in returned_ids
        assert "_system" not in returned_ids

        for a in agents:
            if a["id"] in EXPECTED_SYSTEM_AGENT_IDS:
                assert a.get("hidden") is True
            else:
                assert not a.get("hidden", False)


def test_get_agents_include_hidden_false(client: TestClient) -> None:
    """Explicit include_hidden=false or 0 matches default behavior."""
    for query in ["include_hidden=false", "include_hidden=False", "include_hidden=0"]:
        res = client.get(f"/api/agents?{query}")
        assert res.status_code == 200
        returned_ids = {a["id"] for a in res.json()}
        assert returned_ids == EXPECTED_PUBLIC_AGENT_IDS


def test_get_agents_search_with_hidden_filtering(client: TestClient) -> None:
    """Search queries respect include_hidden visibility gating."""
    # Searching for system agent without include_hidden returns empty
    res_hidden_default = client.get("/api/agents?search=orchestrator")
    assert res_hidden_default.status_code == 200
    assert len(res_hidden_default.json()) == 0

    # Searching with include_hidden=true finds the system agent
    res_hidden_active = client.get("/api/agents?search=orchestrator&include_hidden=true")
    assert res_hidden_active.status_code == 200
    results = res_hidden_active.json()
    assert len(results) == 1
    assert results[0]["id"] == "orchestrator"
    assert results[0]["hidden"] is True

    # Searching for template never finds anything even with include_hidden=true
    res_template = client.get("/api/agents?search=template&include_hidden=true")
    assert res_template.status_code == 200
    assert len(res_template.json()) == 0


def test_get_agent_detail_orchestrator(client: TestClient) -> None:
    """GET /api/agents/orchestrator returns 200 with full detail and hidden=True."""
    res = client.get("/api/agents/orchestrator")
    assert res.status_code == 200
    data = res.json()

    assert data["id"] == "orchestrator"
    assert data["title"] == "Orchestrator"
    assert data["hidden"] is True
    assert data["can_delegate"] is True
    assert "delegate_to_agent" in data["effectiveTools"]
    assert "list_agents" in data["effectiveTools"]
    assert len(data["starters"]) >= 3


def test_get_agent_detail_document_extractor(client: TestClient) -> None:
    """GET /api/agents/document-extractor returns 200 with full detail and hidden=True."""
    res = client.get("/api/agents/document-extractor")
    assert res.status_code == 200
    data = res.json()

    assert data["id"] == "document-extractor"
    assert data["title"] == "Document Extractor"
    assert data["hidden"] is True
    assert data["can_delegate"] is False

    expected_tools = {"attach-read", "sanitize_pii", "extract_structured_data", "validate_grounding"}
    assert expected_tools.issubset(set(data["effectiveTools"]))


def test_get_agent_detail_remaining_system_agents(client: TestClient) -> None:
    """GET /api/agents/{agent_id} returns 200 with hidden=True for all system agents."""
    for agent_id in ["skill-generator", "suggestion-generator"]:
        res = client.get(f"/api/agents/{agent_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == agent_id
        assert data["hidden"] is True


def test_get_agent_detail_path_traversal_and_dots_underscores(client: TestClient) -> None:
    """_system, _template, .hidden, and path traversal attempts are rejected with 404."""
    prohibited_queries = [
        "_system",
        "_template",
        ".hidden",
        "_invalid",
        ".git",
        "%2e",
        "%2e%2e",
        "..%2F..%2Fetc%2Fpasswd",
        "%2e%2e%2f_system%2forchestrator",
        "___test___",
        "non-existent-agent",
    ]
    for target in prohibited_queries:
        res = client.get(f"/api/agents/{target}")
        assert res.status_code == 404, f"Target '{target}' did not return 404 (status={res.status_code})"
