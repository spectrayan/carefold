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

"""Security Test Suite for Catalog API Fuzzing & SQL Injection Hardening.

Tests the integrated lifecycle:
1. Filesystem agent & skill loading (including _system/ separation, template skipping, and taxonomy metadata).
2. SqliteCatalogAdapter indexing and taxonomy parity (get_category_tree() vs filesystem manifests).
3. Adversarial FTS query sanitization and SQL injection hardening.
4. Two-hop orchestrator routing across all 5 canonical domains with candidate verification and 4-step fallback chain.
5. FastAPI REST endpoints (/api/agents/categories, /api/agents, /api/skills) response schemas and pagination.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from carefold.agents.registry import AgentRegistry
from carefold.config import settings
from carefold.constants.agents import (
    AGENT_BENEFITS_GUIDE,
    AGENT_DOCUMENT_EXTRACTOR,
    AGENT_HABIT_COMPANION,
    AGENT_ORCHESTRATOR,
    AGENT_VISIT_STEWARD,
    DEFAULT_ROUTING_FALLBACK_AGENT,
)
from carefold.loaders.agent_loader import load_agent, load_all_agents
from carefold.loaders.skill_loader import load_all_skills, load_skill
from carefold.memory.adapters.sqlite.catalog_adapter import (
    CANONICAL_DOMAINS,
    SqliteCatalogAdapter,
    sanitize_fts_query,
)
from carefold.schemas.manifest import (
    AgentDetailResponse,
    AgentDomain,
    AgentManifest,
    AgentMaturity,
    AgentSummary,
    RiskClass,
    SkillDetailResponse,
    SkillManifest,
    SkillSummary,
)
from carefold.workflows.nodes.orchestrator_node import (
    DomainClassification,
    OrchestratorDecision,
    OrchestratorNode,
)
from tests.fixtures.fake_model import FakeListChatModel


# ============================================================================
# Part 1: Filesystem Loading & Metadata Verification
# ============================================================================

def test_filesystem_agent_loading_and_taxonomy_metadata(repo_root: Path):
    """Verify loading directly from filesystem respects _system separation and extracts rich taxonomy."""
    agents_dir = repo_root / "agents"
    skills_dir = repo_root / "skills"
    assert agents_dir.is_dir(), f"Agents directory missing at {agents_dir}"
    assert (agents_dir / "_system").is_dir(), "_system subdirectory missing"
    assert (agents_dir / "_template").is_dir(), "_template directory missing"

    all_summaries = load_all_agents(agents_dir, skills_dir)
    summary_map = {s.id: s for s in all_summaries}

    # Public agents check
    assert "benefits-guide" in summary_map
    assert "habit-companion" in summary_map
    assert "visit-steward" in summary_map

    # System agents check (should be loaded with hidden=True)
    assert "orchestrator" in summary_map
    assert "document-extractor" in summary_map
    assert "skill-generator" in summary_map
    assert "suggestion-generator" in summary_map

    # _template must NEVER be loaded
    assert "_template" not in summary_map
    for agent_id in summary_map:
        assert not agent_id.startswith("_template")

    # Detailed taxonomy verification on public agents
    bg = summary_map["benefits-guide"]
    assert bg.domain == AgentDomain.NAVIGATION or bg.domain == "navigation"
    assert bg.category == "navigation.insurance"
    assert "insurance" in bg.tags
    assert "benefits" in bg.tags
    assert bg.icon == "FileText"
    assert bg.maturity == AgentMaturity.STABLE or bg.maturity == "stable"
    assert "post_visit" in bg.care_stages
    assert "daily_living" in bg.care_stages

    hc = summary_map["habit-companion"]
    assert hc.domain == AgentDomain.WELLNESS or hc.domain == "wellness"
    assert hc.category == "wellness.habits"
    assert "habits" in hc.tags
    assert "hydration" in hc.tags
    assert hc.icon == "HeartPulse"
    assert "daily_living" in hc.care_stages

    vs = summary_map["visit-steward"]
    assert vs.domain == AgentDomain.NAVIGATION or vs.domain == "navigation"
    assert vs.category == "navigation.appointments"
    assert "visit-prep" in vs.tags
    assert "appointment" in vs.tags
    assert vs.icon == "Stethoscope"
    assert "pre_visit" in vs.care_stages
    assert "during_visit" in vs.care_stages

    # Verify individual load_agent on system agents
    orch, _, _ = load_agent(agents_dir / "_system" / "orchestrator", skills_dir)
    assert orch.id == "orchestrator"
    assert orch.can_delegate is True
    assert orch.hidden is True


# ============================================================================
# Part 2: SqliteCatalogAdapter Indexing & Category Tree Parity
# ============================================================================

@pytest.mark.asyncio
async def test_catalog_indexing_and_category_tree_parity(repo_root: Path, tmp_path: Path):
    """Verify SqliteCatalogAdapter indexes all agents and taxonomy tree parity with filesystem."""
    agents_dir = repo_root / "agents"
    skills_dir = repo_root / "skills"
    catalog_db = tmp_path / "catalog_lifecycle.db"
    catalog = SqliteCatalogAdapter(db_path=catalog_db)

    try:
        # 1. Load agents and index into catalog
        all_summaries = load_all_agents(agents_dir, skills_dir)
        for summary in all_summaries:
            # Load full manifest
            agent_dir = agents_dir / summary.id
            if not agent_dir.is_dir():
                agent_dir = agents_dir / "_system" / summary.id
            manifest, _, _ = load_agent(agent_dir, skills_dir)
            if summary.id in ("orchestrator", "document-extractor", "skill-generator", "suggestion-generator"):
                manifest.hidden = True
            await catalog.index_agent(manifest)

        # 2. Count agents
        public_count = await catalog.count_agents(include_hidden=False)
        all_count = await catalog.count_agents(include_hidden=True)
        assert public_count >= 3, f"Expected >=3 public agents, got {public_count}"
        assert all_count >= 7, f"Expected >=7 total agents, got {all_count}"

        # 3. Query category tree with include_hidden=False
        public_tree = await catalog.get_category_tree(include_hidden=False)
        assert public_tree["total"] == public_count
        domains = public_tree["domains"]
        for d in CANONICAL_DOMAINS:
            assert d in domains

        assert domains["navigation"]["count"] == 6
        assert "insurance" in domains["navigation"]["categories"]
        assert domains["navigation"]["categories"]["insurance"]["count"] == 1
        assert "appointments" in domains["navigation"]["categories"]
        assert domains["navigation"]["categories"]["appointments"]["count"] == 1

        assert domains["wellness"]["count"] == 1
        assert "habits" in domains["wellness"]["categories"]
        assert domains["wellness"]["categories"]["habits"]["count"] == 1

        assert domains["clinical"]["count"] >= 8
        assert domains["therapy"]["count"] == 0
        assert domains["education"]["count"] == 0

        # 4. Query category tree with include_hidden=True
        all_tree = await catalog.get_category_tree(include_hidden=True)
        assert all_tree["total"] == all_count
        all_domains = all_tree["domains"]
        assert all_domains["navigation"]["count"] == 6
        # System agents default to domain wellness with empty category
        assert all_domains["wellness"]["count"] >= 5

        # 5. Query domain filtered tree
        nav_tree = await catalog.get_category_tree(domain="navigation", include_hidden=False)
        assert nav_tree["total"] == 6
        assert list(nav_tree["domains"].keys()) == ["navigation"]

        # 6. Verify Idempotence: Indexing again must not duplicate or corrupt counts
        for summary in all_summaries:
            agent_dir = agents_dir / summary.id
            if not agent_dir.is_dir():
                agent_dir = agents_dir / "_system" / summary.id
            manifest, _, _ = load_agent(agent_dir, skills_dir)
            if summary.id in ("orchestrator", "document-extractor", "skill-generator", "suggestion-generator"):
                manifest.hidden = True
            await catalog.index_agent(manifest)

        re_tree = await catalog.get_category_tree(include_hidden=False)
        assert re_tree["total"] == public_count
        assert re_tree["domains"]["navigation"]["count"] == 6
        assert re_tree["domains"]["wellness"]["count"] == 1
        assert re_tree["domains"]["clinical"]["count"] >= 8
    finally:
        await catalog.close()


# ============================================================================
# Part 3: Adversarial FTS & SQL Injection Resistance
# ============================================================================

@pytest.mark.asyncio
async def test_adversarial_fts_query_sanitization_and_sql_injection(tmp_path: Path):
    """Adversarially challenge FTS5 query parser with injection payloads and hostile text."""
    catalog = SqliteCatalogAdapter(db_path=tmp_path / "adversarial_fts.db")

    try:
        # Index a known agent
        sample_manifest = AgentManifest(
            id="sample-agent",
            title="Sample Agent",
            version="0.1.0",
            domain=AgentDomain.WELLNESS,
            category="wellness.mindfulness",
            tags=["stress", "relaxation", "meditation"],
            description="A sample mindfulness meditation assistant.",
            persona="You help people relax.",
        )
        await catalog.index_agent(sample_manifest)

        # Test hostile queries through sanitize_fts_query
        hostile_queries = [
            "",
            "   ",
            "---",
            "'; DROP TABLE agents; --",
            "\" OR 1=1 --",
            "AND OR NOT NEAR()",
            "((( unmatched parens )))",
            "* * * ? ?",
            "\x00\x1f\u200b\u200chidden",
            "a" * 5000,
            "🩺 🧠 💊 emoji queries",
        ]

        for hq in hostile_queries:
            sanitized = sanitize_fts_query(hq)
            # Sanitized query must either be empty or contain only quoted tokens
            if sanitized:
                assert "DROP TABLE" not in sanitized.upper()

            # Query catalog directly with hostile query; MUST NOT raise exception
            results = await catalog.search_agents(query=hq)
            assert isinstance(results, list)

        # Ensure table was not dropped
        count = await catalog.count_agents(include_hidden=True)
        assert count == 1
    finally:
        await catalog.close()


# ============================================================================
# Part 4: Two-Hop Routing Across All 5 Canonical Domains
# ============================================================================

def make_manifest(
    agent_id: str,
    domain: AgentDomain,
    category: str,
    tags: List[str],
    desc: str,
) -> AgentManifest:
    return AgentManifest(
        id=agent_id,
        title=agent_id.replace("-", " ").title(),
        version="0.1.0",
        domain=domain,
        category=category,
        tags=tags,
        description=desc,
        persona=f"You are {agent_id}.",
    )


@pytest.mark.asyncio
async def test_two_hop_routing_across_all_five_domains(tmp_path: Path):
    """Empirically test Tier-1 classification and Tier-2 candidate retrieval across all 5 domains."""
    catalog = SqliteCatalogAdapter(db_path=tmp_path / "all_domains.db")

    try:
        # Set up agents across all 5 domains
        domain_agents = [
            make_manifest("clinical-triage", AgentDomain.CLINICAL, "clinical.triage", ["symptom", "triage", "urgent"], "Clinical symptom triage"),
            make_manifest("therapy-counselor", AgentDomain.THERAPY, "therapy.cbt", ["cbt", "anxiety", "depression"], "Cognitive behavioral therapy"),
            make_manifest("habit-companion", AgentDomain.WELLNESS, "wellness.habits", ["habits", "sleep", "water"], "Daily wellness habit companion"),
            make_manifest("benefits-guide", AgentDomain.NAVIGATION, "navigation.insurance", ["insurance", "deductible", "copay"], "Insurance benefits guidance"),
            make_manifest("education-guide", AgentDomain.EDUCATION, "education.diabetes", ["diabetes", "nutrition", "insulin"], "Patient chronic disease education"),
        ]

        for ag in domain_agents:
            await catalog.index_agent(ag)

        test_matrix = [
            {
                "domain": "clinical",
                "category": "clinical.triage",
                "prompt": "I need help assessing acute fever and rash symptoms.",
                "expected_agent": "clinical-triage",
            },
            {
                "domain": "therapy",
                "category": "therapy.cbt",
                "prompt": "I feel overwhelming anxiety and want to reframe negative thoughts.",
                "expected_agent": "therapy-counselor",
            },
            {
                "domain": "wellness",
                "category": "wellness.habits",
                "prompt": "Help me log my hydration and set up a morning routine.",
                "expected_agent": "habit-companion",
            },
            {
                "domain": "navigation",
                "category": "navigation.insurance",
                "prompt": "Can you explain what an in-network deductible means on my plan?",
                "expected_agent": "benefits-guide",
            },
            {
                "domain": "education",
                "category": "education.diabetes",
                "prompt": "Explain the difference between type 1 and type 2 diabetes insulin usage.",
                "expected_agent": "education-guide",
            },
        ]

        for item in test_matrix:
            tier1_resp = json.dumps({
                "domain": item["domain"],
                "category": item["category"],
                "reasoning": f"Query pertains to {item['domain']}",
            })
            tier2_resp = json.dumps({
                "agent_id": item["expected_agent"],
                "reasoning": f"Matched {item['expected_agent']}",
                "instructions": "Help user",
            })

            fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
            orchestrator = OrchestratorNode(
                model=fake_model,
                catalog=catalog,
            )

            # Test internal two-hop helper directly to inspect candidates
            decision, candidates = await orchestrator._execute_two_hop(
                state={},
                prompt_text=item["prompt"],
                raw_messages=[HumanMessage(content=item["prompt"])],
            )
            assert decision.agent_id == item["expected_agent"]
            assert len(candidates) >= 1
            assert any(c.id == item["expected_agent"] for c in candidates)

            # Re-queue responses for full execute()
            fake_model_exec = FakeListChatModel(responses=[tier1_resp, tier2_resp])
            orchestrator_exec = OrchestratorNode(
                model=fake_model_exec,
                catalog=catalog,
            )
            state = {
                "messages": [HumanMessage(content=item["prompt"])],
            }
            result = await orchestrator_exec.execute(state)
            assert result["current_agent"] == item["expected_agent"]
            assert result["agent_id"] == item["expected_agent"]
            assert result["next_step"] == item["expected_agent"]
    finally:
        await catalog.close()


# ============================================================================
# Part 5: Adversarial Fallback Chain in Two-Hop Orchestrator
# ============================================================================

@pytest.mark.asyncio
async def test_adversarial_two_hop_fallback_chain(tmp_path: Path):
    """Stress-test the full 4-step fallback chain under degraded/hostile conditions."""
    catalog = SqliteCatalogAdapter(db_path=tmp_path / "fallback_chain.db")

    try:
        # Only index benefits-guide (domain=navigation, category=navigation.insurance, tags=[insurance, copay])
        bg = make_manifest("benefits-guide", AgentDomain.NAVIGATION, "navigation.insurance", ["insurance", "copay"], "Insurance guide")
        await catalog.index_agent(bg)

        # Challenge Step 2: Tier-1 predicts unknown subcategory in navigation -> domain-only fallback succeeds
        tier1_step2 = json.dumps({"domain": "navigation", "category": "navigation.unheard_subcat", "reasoning": "Test step 2"})
        tier2_step2 = json.dumps({"agent_id": "benefits-guide", "reasoning": "Fallback to domain candidate", "instructions": ""})
        model_step2 = FakeListChatModel(responses=[tier1_step2, tier2_step2])
        orch_step2 = OrchestratorNode(model=model_step2, catalog=catalog)

        res_step2 = await orch_step2.execute({"messages": [HumanMessage(content="Random navigation question")]})
        assert res_step2["current_agent"] == "benefits-guide"

        # Challenge Step 3: Tier-1 predicts unknown domain -> FTS keyword fallback succeeds
        tier1_step3 = json.dumps({"domain": "astrology", "category": "astrology.horoscope", "reasoning": "Hallucinated domain"})
        tier2_step3 = json.dumps({"agent_id": "benefits-guide", "reasoning": "FTS matched copay tag", "instructions": ""})
        model_step3 = FakeListChatModel(responses=[tier1_step3, tier2_step3])
        orch_step3 = OrchestratorNode(model=model_step3, catalog=catalog)

        res_step3 = await orch_step3.execute({"messages": [HumanMessage(content="What is my insurance copay?")]})
        assert res_step3["current_agent"] == "benefits-guide"

        # Challenge Step 4: Complete gibberish with 0 matches -> pattern fallback
        tier1_step4 = json.dumps({"domain": "quantum", "category": "quantum.entanglement", "reasoning": "Zero match"})
        model_step4 = FakeListChatModel(responses=[tier1_step4])
        orch_step4 = OrchestratorNode(model=model_step4, catalog=catalog)

        res_step4 = await orch_step4.execute({"messages": [HumanMessage(content="xyzqwerty 99999999999")]})
        # Pattern fallback routes to default agent without exception
        assert res_step4["current_agent"] in (AGENT_VISIT_STEWARD, AGENT_BENEFITS_GUIDE, DEFAULT_ROUTING_FALLBACK_AGENT)
    finally:
        await catalog.close()


# ============================================================================
# Part 6: FastAPI REST Endpoints & Schema Validation
# ============================================================================

def test_fastapi_endpoints_schemas_and_filters(client: TestClient):
    """Empirically test /api/agents/categories, /api/agents, and /api/skills endpoints."""

    # 1. GET /api/agents/categories
    cat_resp = client.get("/api/agents/categories")
    assert cat_resp.status_code == 200
    cat_data = cat_resp.json()
    assert isinstance(cat_data, dict)
    domains_tree = cat_data.get("domains", cat_data)

    for canonical in ("clinical", "therapy", "wellness", "navigation", "education"):
        assert canonical in domains_tree, f"Missing domain {canonical} in categories response"
        assert "count" in domains_tree[canonical]

    # Verify counts match public manifests in repo
    assert domains_tree["navigation"]["count"] == 6
    assert domains_tree["wellness"]["count"] == 1
    assert domains_tree["clinical"]["count"] >= 8

    # 2. GET /api/agents (Public Marketplace View)
    agents_resp = client.get("/api/agents")
    assert agents_resp.status_code == 200
    agents = agents_resp.json()
    assert len(agents) >= 3

    # Validate against AgentSummary schema
    for raw in agents:
        summary = AgentSummary.model_validate(raw)
        assert summary.id
        assert summary.domain in (AgentDomain.NAVIGATION, AgentDomain.WELLNESS, AgentDomain.CLINICAL)
        assert isinstance(summary.tags, list)
        assert summary.icon is not None

    # Verify system agents excluded by default
    agent_ids = [a["id"] for a in agents]
    assert "orchestrator" not in agent_ids
    assert "document-extractor" not in agent_ids
    assert "_template" not in agent_ids

    # 3. GET /api/agents?include_hidden=true (Internal View)
    hidden_resp = client.get("/api/agents?include_hidden=true")
    assert hidden_resp.status_code == 200
    hidden_agents = hidden_resp.json()
    assert len(hidden_agents) == len(agents) + 6
    hidden_ids = [a["id"] for a in hidden_agents]
    assert "orchestrator" in hidden_ids
    assert "document-extractor" in hidden_ids
    assert "skill-generator" in hidden_ids
    assert "suggestion-generator" in hidden_ids
    assert "_template" not in hidden_ids

    # 4. Domain & Category Filters on /api/agents
    nav_resp = client.get("/api/agents?domain=navigation")
    assert nav_resp.status_code == 200
    nav_agents = nav_resp.json()
    assert len(nav_agents) == 6
    assert all(a["domain"] == "navigation" for a in nav_agents)

    well_resp = client.get("/api/agents?domain=wellness")
    assert well_resp.status_code == 200
    well_agents = well_resp.json()
    assert len(well_agents) == 1
    assert well_agents[0]["id"] == "habit-companion"

    clin_resp = client.get("/api/agents?domain=clinical")
    assert clin_resp.status_code == 200
    clin_agents = clin_resp.json()
    assert len(clin_agents) >= 8
    assert all(a["domain"] == "clinical" for a in clin_agents)

    ins_resp = client.get("/api/agents?category=navigation.insurance")
    assert ins_resp.status_code == 200
    ins_agents = ins_resp.json()
    assert len(ins_agents) == 1
    assert ins_agents[0]["id"] == "benefits-guide"

    # 5. Pagination on /api/agents
    p1_resp = client.get("/api/agents?page=1&per_page=2")
    assert p1_resp.status_code == 200
    p1_agents = p1_resp.json()
    assert len(p1_agents) == 2

    p2_resp = client.get("/api/agents?page=2&per_page=2")
    assert p2_resp.status_code == 200
    p2_agents = p2_resp.json()
    assert len(p2_agents) == 2
    assert p1_agents != p2_agents

    beyond_resp = client.get(f"/api/agents?page=999&per_page=2")
    assert beyond_resp.status_code == 200
    assert beyond_resp.json() == []

    # 6. GET /api/skills
    skills_resp = client.get("/api/skills")
    assert skills_resp.status_code == 200
    skills = skills_resp.json()
    assert len(skills) >= 3

    for raw_skill in skills:
        skill_sum = SkillSummary.model_validate(raw_skill)
        assert skill_sum.domain is not None
        assert isinstance(skill_sum.tags, list)

    # 7. Detail Endpoints & Validation
    bg_detail = client.get("/api/agents/benefits-guide")
    assert bg_detail.status_code == 200
    detail_model = AgentDetailResponse.model_validate(bg_detail.json())
    assert detail_model.id == "benefits-guide"
    assert detail_model.domain == AgentDomain.NAVIGATION
    assert detail_model.category == "navigation.insurance"

    orch_detail = client.get("/api/agents/orchestrator")
    assert orch_detail.status_code == 200
    orch_model = AgentDetailResponse.model_validate(orch_detail.json())
    assert orch_model.id == "orchestrator"
    assert orch_model.hidden is True

    # 8. 404 Guards
    assert client.get("/api/agents/_template").status_code == 404
    assert client.get("/api/agents/nonexistent_agent_xyz").status_code == 404
    assert client.get("/api/skills/nonexistent_skill_xyz").status_code == 404


# ============================================================================
# Part 7: Adversarial Concurrency, Candidate Limits & Output Parsing
# ============================================================================

@pytest.mark.asyncio
async def test_adversarial_candidate_limit_and_concurrency(tmp_path: Path):
    """Verify candidate list is strictly capped at <= 8 and concurrent routing does not lock/corrupt catalog."""
    import asyncio
    catalog = SqliteCatalogAdapter(db_path=tmp_path / "candidate_limit.db")

    try:
        # Index 20 distinct agents in domain wellness, category wellness.habits
        for i in range(20):
            ag = make_manifest(
                f"habit-bot-{i:02d}",
                AgentDomain.WELLNESS,
                "wellness.habits",
                ["habits", f"tag-{i}"],
                f"Habit tracker variant {i}",
            )
            await catalog.index_agent(ag)

        count = await catalog.count_agents(include_hidden=False)
        assert count == 20

        # Tier-1 and Tier-2 setup
        tier1_resp = json.dumps({"domain": "wellness", "category": "wellness.habits", "reasoning": "Habit query"})
        tier2_resp = json.dumps({"agent_id": "habit-bot-00", "reasoning": "Selected 00", "instructions": ""})

        # Check candidate truncation <= 8
        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        orch = OrchestratorNode(model=fake_model, catalog=catalog)

        decision, candidates = await orch._execute_two_hop(
            state={},
            prompt_text="I want to build healthy morning habits",
            raw_messages=[HumanMessage(content="I want to build healthy morning habits")],
        )
        assert len(candidates) <= 8, f"Expected <= 8 candidates, got {len(candidates)}"
        assert decision.agent_id == "habit-bot-00"

        # Concurrency stress: 10 simultaneous two-hop routing tasks
        async def run_single_routing(idx: int):
            t1 = json.dumps({"domain": "wellness", "category": "wellness.habits", "reasoning": f"Run {idx}"})
            t2 = json.dumps({"agent_id": f"habit-bot-{idx:02d}", "reasoning": f"Selected {idx}", "instructions": ""})
            fm = FakeListChatModel(responses=[t1, t2])
            o = OrchestratorNode(model=fm, catalog=catalog)
            res = await o.execute({"messages": [HumanMessage(content=f"Build habit {idx}")]})
            return res["agent_id"]

        results = await asyncio.gather(*(run_single_routing(i) for i in range(10)))
        assert len(results) == 10
        # Indices 0-7 are within the 8 candidates returned by catalog
        for i in range(8):
            assert results[i] == f"habit-bot-{i:02d}"
        # Indices 8 and 9 are outside the candidate list (limit=8), so orchestrator correctly falls back to candidates[0]
        assert results[8] == "habit-bot-00"
        assert results[9] == "habit-bot-00"
    finally:
        await catalog.close()


@pytest.mark.asyncio
async def test_adversarial_malformed_llm_markdown_and_hallucinations(tmp_path: Path):
    """Stress-test markdown json extraction, unparseable LLM output, and hallucinated candidate IDs."""
    catalog = SqliteCatalogAdapter(db_path=tmp_path / "markdown_test.db")

    try:
        sample = make_manifest("agent-alpha", AgentDomain.WELLNESS, "wellness.general", ["alpha"], "Alpha bot")
        await catalog.index_agent(sample)

        # 1. Tier-1 and Tier-2 return JSON wrapped inside markdown code blocks
        md_tier1 = "```json\n{\n  \"domain\": \"wellness\",\n  \"category\": \"wellness.general\",\n  \"reasoning\": \"Markdown block\"\n}\n```"
        md_tier2 = "```json\n{\n  \"agent_id\": \"agent-alpha\",\n  \"reasoning\": \"Selected alpha\",\n  \"instructions\": \"Go ahead\"\n}\n```"

        fake_model = FakeListChatModel(responses=[md_tier1, md_tier2])
        orch = OrchestratorNode(model=fake_model, catalog=catalog)

        res = await orch.execute({"messages": [HumanMessage(content="Hello wellness")]})
        assert res["agent_id"] == "agent-alpha"

        # 2. Tier-2 returns completely hallucinated agent ID
        h_tier1 = json.dumps({"domain": "wellness", "category": "wellness.general", "reasoning": "Valid domain"})
        h_tier2 = json.dumps({"agent_id": "hallucinated_ghost_agent_999", "reasoning": "Invented agent", "instructions": ""})

        fake_model_h = FakeListChatModel(responses=[h_tier1, h_tier2])
        orch_h = OrchestratorNode(model=fake_model_h, catalog=catalog)

        res_h = await orch_h.execute({"messages": [HumanMessage(content="Hello wellness")]})
        # Should gracefully fall back to existing candidate (agent-alpha)
        assert res_h["agent_id"] == "agent-alpha"
        assert "not found in registry; fell back to" in res_h["orchestrator_reasoning"]
    finally:
        await catalog.close()


def test_adversarial_api_fuzzing_and_malicious_query_params(client: TestClient):
    """Fuzz API query parameters to ensure schema safety, injection resistance, and proper error codes."""
    # 1. Negative or 0 page / per_page must return 422 Unprocessable Entity
    assert client.get("/api/agents?page=0").status_code == 422
    assert client.get("/api/agents?page=-1").status_code == 422
    assert client.get("/api/agents?per_page=0").status_code == 422
    assert client.get("/api/agents?per_page=-5").status_code == 422
    assert client.get("/api/skills?page=0").status_code == 422
    assert client.get("/api/skills?per_page=0").status_code == 422

    # 2. Hostile SQL injection / path traversal strings in domain & category queries
    hostile_domain = client.get("/api/agents?domain=' OR 1=1 --")
    assert hostile_domain.status_code == 200
    assert hostile_domain.json() == []

    hostile_cat = client.get("/api/agents?category=../../../../etc/passwd")
    assert hostile_cat.status_code == 200
    assert hostile_cat.json() == []

    # 3. Excessive pagination values return empty lists gracefully
    huge_page = client.get("/api/agents?page=999999&per_page=100")
    assert huge_page.status_code == 200
    assert huge_page.json() == []

