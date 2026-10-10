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

"""Adversarial stress test for candidate boundaries (<= 8 candidates) across all 5 domains,
API pagination, domain filtering, and system agent isolation.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from carefold.constants.agents import (
    AGENT_BENEFITS_GUIDE,
    AGENT_DOCUMENT_EXTRACTOR,
    AGENT_HABIT_COMPANION,
    AGENT_ORCHESTRATOR,
    AGENT_VISIT_STEWARD,
    DEFAULT_ROUTING_FALLBACK_AGENT,
)
from carefold.loaders.agent_loader import load_agent, load_all_agents
from carefold.memory.adapters.sqlite.catalog_adapter import (
    CANONICAL_DOMAINS,
    SqliteCatalogAdapter,
)
from carefold.schemas.manifest import (
    AgentDetailResponse,
    AgentDomain,
    AgentManifest,
    AgentMaturity,
    AgentSummary,
)
from carefold.workflows.nodes.orchestrator_node import (
    DomainClassification,
    OrchestratorDecision,
    OrchestratorNode,
)
from tests.fixtures.fake_model import FakeListChatModel


def create_mock_manifest(
    agent_id: str,
    domain: AgentDomain,
    category: str = "",
    tags: List[str] = None,
    hidden: bool = False,
    desc: str = "Test agent",
) -> AgentManifest:
    return AgentManifest(
        id=agent_id,
        title=agent_id.replace("-", " ").title(),
        version="1.0.0",
        domain=domain,
        category=category,
        tags=tags or [],
        hidden=hidden,
        description=desc,
        persona=f"You are {agent_id}.",
    )


# ============================================================================
# Section 1: Candidate Boundaries Across All 5 Canonical Domains (<= 8 candidates)
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("domain_name", CANONICAL_DOMAINS)
async def test_domain_candidate_boundary_scales_and_caps_at_eight(tmp_path: Path, domain_name: str):
    """For each of the 5 canonical domains, index 0, 1, 8, and 15 agents and verify <= 8 candidate bound."""
    db_file = tmp_path / f"catalog_bound_{domain_name}.db"
    catalog = SqliteCatalogAdapter(db_path=db_file)

    try:
        domain_enum = AgentDomain(domain_name)

        # 1. Zero agents in domain: search should return 0 candidates
        empty_res = await catalog.search_agents(domain=domain_name, limit=8)
        assert len(empty_res) == 0

        # 2. Add 1 agent in domain: search should return exactly 1 candidate
        a1 = create_mock_manifest(f"{domain_name}-agent-01", domain_enum, f"{domain_name}.sub1")
        await catalog.index_agent(a1)
        res_1 = await catalog.search_agents(domain=domain_name, limit=8)
        assert len(res_1) == 1
        assert res_1[0].id == f"{domain_name}-agent-01"

        # 3. Add 7 more agents (total 8 agents in domain): search should return exactly 8 candidates
        for i in range(2, 9):
            ag = create_mock_manifest(f"{domain_name}-agent-{i:02d}", domain_enum, f"{domain_name}.sub1")
            await catalog.index_agent(ag)
        res_8 = await catalog.search_agents(domain=domain_name, limit=8)
        assert len(res_8) == 8, f"Expected 8 candidates for domain {domain_name}, got {len(res_8)}"

        # 4. Add 7 more agents (total 15 agents in domain): search must strictly enforce limit=8 <= 8
        for i in range(9, 16):
            ag = create_mock_manifest(f"{domain_name}-agent-{i:02d}", domain_enum, f"{domain_name}.sub1")
            await catalog.index_agent(ag)
        res_15 = await catalog.search_agents(domain=domain_name, limit=8)
        assert len(res_15) == 8, f"Candidate limit exceeded for {domain_name}: {len(res_15)} > 8"
        # Candidate IDs must all belong to this domain
        for c in res_15:
            assert c.domain == domain_enum

        # 5. Two-hop orchestrator execution targeting this domain
        tier1_resp = json.dumps({"domain": domain_name, "category": f"{domain_name}.sub1", "reasoning": "Valid"})
        tier2_resp = json.dumps({"agent_id": f"{domain_name}-agent-01", "reasoning": "Selected", "instructions": ""})
        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        orch = OrchestratorNode(model=fake_model, catalog=catalog)

        decision, candidates = await orch._execute_two_hop(
            state={},
            prompt_text=f"Help me with {domain_name}",
            raw_messages=[HumanMessage(content=f"Help me with {domain_name}")],
        )
        assert len(candidates) <= 8
        assert decision.agent_id == f"{domain_name}-agent-01"
    finally:
        await catalog.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("domain_name", CANONICAL_DOMAINS)
async def test_domain_candidate_isolation_and_system_agent_exclusion(tmp_path: Path, domain_name: str):
    """Verify that system agents (hidden=True) in any domain are NEVER included in candidate list."""
    db_file = tmp_path / f"catalog_sys_{domain_name}.db"
    catalog = SqliteCatalogAdapter(db_path=db_file)

    try:
        domain_enum = AgentDomain(domain_name)
        # Create public agents
        for i in range(3):
            pub = create_mock_manifest(f"{domain_name}-pub-{i}", domain_enum, f"{domain_name}.sub", hidden=False)
            await catalog.index_agent(pub)

        # Create hidden system agents in the same domain
        for i in range(3):
            sys_ag = create_mock_manifest(f"{domain_name}-sys-{i}", domain_enum, f"{domain_name}.sub", hidden=True)
            await catalog.index_agent(sys_ag)

        # Total in catalog should be 6
        assert await catalog.count_agents(include_hidden=True) == 6
        assert await catalog.count_agents(include_hidden=False) == 3

        # Candidate search without include_hidden must return ONLY 3 public agents
        candidates = await catalog.search_agents(domain=domain_name, limit=8)
        assert len(candidates) == 3
        for c in candidates:
            assert not c.hidden
            assert "sys" not in c.id

        # Orchestrator two-hop candidate retrieval must NEVER expose hidden agents
        tier1_resp = json.dumps({"domain": domain_name, "category": f"{domain_name}.sub", "reasoning": "Check"})
        tier2_resp = json.dumps({"agent_id": f"{domain_name}-pub-0", "reasoning": "Pick pub", "instructions": ""})
        model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        orch = OrchestratorNode(model=model, catalog=catalog)

        decision, two_hop_candidates = await orch._execute_two_hop(
            state={},
            prompt_text="test prompt",
            raw_messages=[HumanMessage(content="test prompt")],
        )
        assert len(two_hop_candidates) == 3
        for c in two_hop_candidates:
            assert not c.hidden
    finally:
        await catalog.close()


# ============================================================================
# Section 2: API Pagination and Parameter Fuzzing
# ============================================================================

def test_api_agents_pagination_comprehensive(client: TestClient):
    """Stress test pagination boundaries on /api/agents."""
    # Public agents include legacy agents plus newly expanded organ navigators
    all_resp = client.get("/api/agents")
    assert all_resp.status_code == 200
    all_agents = all_resp.json()
    total_count = len(all_agents)
    assert total_count >= 3

    # Test per_page = 1 across all pages
    seen_ids = set()
    for p in range(1, total_count + 1):
        resp = client.get(f"/api/agents?page={p}&per_page=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        agent_id = data[0]["id"]
        assert agent_id not in seen_ids
        seen_ids.add(agent_id)

    assert len(seen_ids) == total_count

    # Page beyond total count must return empty list []
    beyond_resp = client.get(f"/api/agents?page={total_count + 1}&per_page=1")
    assert beyond_resp.status_code == 200
    assert beyond_resp.json() == []

    # Large page number returns empty list []
    large_page = client.get("/api/agents?page=999999&per_page=20")
    assert large_page.status_code == 200
    assert large_page.json() == []

    # Per_page larger than total count returns all items
    huge_per_page = client.get("/api/agents?page=1&per_page=100")
    assert huge_per_page.status_code == 200
    assert len(huge_per_page.json()) == total_count

    # Invalid pagination types or negative/zero numbers must return 422
    for bad_param in ["page=0", "page=-1", "per_page=0", "per_page=-10", "page=abc", "per_page=xyz"]:
        r = client.get(f"/api/agents?{bad_param}")
        assert r.status_code == 422, f"Expected 422 for bad param: {bad_param}, got {r.status_code}"


def test_api_domain_filtering_case_insensitivity_and_isolation(client: TestClient):
    """Verify domain filtering is case-insensitive, returns correct counts, and isolates system agents."""
    # Test case insensitivity on domain
    for d_query in ["navigation", "Navigation", "NAVIGATION"]:
        r = client.get(f"/api/agents?domain={d_query}")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 6
        for a in data:
            assert a["domain"] == "navigation"

    for w_query in ["wellness", "Wellness", "WELLNESS"]:
        r = client.get(f"/api/agents?domain={w_query}")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["id"] == "habit-companion"

    for empty_domain in ["therapy", "education"]:
        r = client.get(f"/api/agents?domain={empty_domain}")
        assert r.status_code == 200
        assert r.json() == []

    r_clin = client.get("/api/agents?domain=clinical")
    assert r_clin.status_code == 200
    assert len(r_clin.json()) >= 8

    # Hidden system agents isolation
    # 4 system agents exist: orchestrator, document-extractor, skill-generator, suggestion-generator
    public_r = client.get("/api/agents")
    assert public_r.status_code == 200
    public_ids = {a["id"] for a in public_r.json()}
    for sys_id in ["orchestrator", "document-extractor", "skill-generator", "suggestion-generator"]:
        assert sys_id not in public_ids

    # With include_hidden=true, system agents appear
    hidden_r = client.get("/api/agents?include_hidden=true")
    assert hidden_r.status_code == 200
    hidden_ids = {a["id"] for a in hidden_r.json()}
    for sys_id in ["orchestrator", "document-extractor", "skill-generator", "suggestion-generator"]:
        assert sys_id in hidden_ids

    # _template must NEVER appear even with include_hidden=true
    assert "_template" not in hidden_ids
    for a in hidden_r.json():
        assert not a["id"].startswith("_template")
