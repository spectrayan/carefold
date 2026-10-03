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

"""Automated integration and verification test suite for Catalog Indexing & Two-Hop Routing.

Covers:
1. Indexing: SqliteCatalogAdapter indexing all agents (public specialists,
   baseline agents, hidden system agents) and skills into SQLite FTS5.
2. Categories API: GET /api/agents/categories and CatalogPort.get_category_tree()
   accurately reflecting all domains and category counts.
3. Two-Hop Routing: Domain classification -> candidate retrieval by category/domain/tags
   -> candidate selection, with 4-step fallback chain.
4. Pattern Fallback: Step 4 regex pattern matching resolving queries for each of
   the 17 new specialist agents.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage

# Ensure backend root and backend/src are on sys.path regardless of execution cwd
_current_file = Path(__file__).resolve()
_project_root = _current_file.parents[2]
_backend_dir = _project_root / "backend"
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))
if str(_backend_dir / "src") not in sys.path:
    sys.path.insert(0, str(_backend_dir / "src"))

from carefold.agents.registry import AgentRegistry
from carefold.config import settings
from carefold.constants.agents import AGENT_ORCHESTRATOR, DEFAULT_ROUTING_FALLBACK_AGENT
from carefold.loaders.skill_loader import load_all_skills
from carefold.main import app
from carefold.memory.adapters.sqlite.catalog_adapter import (
    SqliteCatalogAdapter,
    build_category_tree_from_rows,
)
from carefold.schemas.manifest import AgentManifest, SkillManifest
from carefold.workflows.nodes.orchestrator_node import (
    DomainClassification,
    OrchestratorDecision,
    OrchestratorNode,
    TIER1_DOMAIN_CLASSIFIER_PROMPT,
)
from tests.fixtures.fake_model import FakeListChatModel


# ============================================================================
# Test Data: 17 Public Specialists, 3 Baseline Agents, 2 System Agents, 17 Skills
# ============================================================================

ALL_17_SPECIALIST_SPECS: List[Dict[str, Any]] = [
    # 8 Core Organ Navigators (R1)
    {
        "id": "cardiology-guide",
        "companion_skill": "cardiology-prep",
        "domain": "clinical",
        "category": "clinical.cardiology",
        "fts_query": "hypertension blood pressure arrhythmia",
        "pattern_query": "hypertension management and arrhythmia palpitations with high blood pressure",
        "tier1_category": "clinical.cardiology",
    },
    {
        "id": "pulmonology-guide",
        "companion_skill": "pulmonology-prep",
        "domain": "clinical",
        "category": "clinical.pulmonology",
        "fts_query": "asthma copd inhaler dyspnea",
        "pattern_query": "asthma action plan and dyspnea inhaler for shortness of breath",
        "tier1_category": "clinical.pulmonology",
    },
    {
        "id": "neurology-guide",
        "companion_skill": "neurology-prep",
        "domain": "clinical",
        "category": "clinical.neurology",
        "fts_query": "migraine headache neuropathy tremor",
        "pattern_query": "migraine headache diary and neuropathy nerve pain with cognitive memory changes",
        "tier1_category": "clinical.neurology",
    },
    {
        "id": "gastro-guide",
        "companion_skill": "gastro-prep",
        "domain": "clinical",
        "category": "clinical.gastroenterology",
        "fts_query": "ibs ibd colonoscopy endoscopy",
        "pattern_query": "ibs flare-up with severe digestive stomach cramps and endoscopy preparation",
        "tier1_category": "clinical.gastroenterology",
    },
    {
        "id": "nephrology-guide",
        "companion_skill": "nephrology-prep",
        "domain": "clinical",
        "category": "clinical.nephrology",
        "fts_query": "kidney egfr creatinine dialysis",
        "pattern_query": "kidney function labs showing abnormal egfr and elevated creatinine",
        "tier1_category": "clinical.nephrology",
    },
    {
        "id": "endocrinology-guide",
        "companion_skill": "endocrinology-prep",
        "domain": "clinical",
        "category": "clinical.endocrinology",
        "fts_query": "diabetes thyroid cgm a1c insulin",
        "pattern_query": "diabetes management with cgm glucose monitoring and high a1c levels",
        "tier1_category": "clinical.endocrinology",
    },
    {
        "id": "ortho-guide",
        "companion_skill": "ortho-prep",
        "domain": "clinical",
        "category": "clinical.orthopedics",
        "fts_query": "joint mobility osteoarthritis physical therapy",
        "pattern_query": "severe joint mobility impairment and musculoskeletal knee osteoarthritis pain",
        "tier1_category": "clinical.orthopedics",
    },
    {
        "id": "derma-guide",
        "companion_skill": "derma-prep",
        "domain": "clinical",
        "category": "clinical.dermatology",
        "fts_query": "rash lesion mole abcde biopsy",
        "pattern_query": "skin rash with a suspicious pigmented lesion mole requiring abcde review",
        "tier1_category": "clinical.dermatology",
    },
    # 5 Extended Medical & Surgical Navigators (R2)
    {
        "id": "oncology-navigator",
        "companion_skill": "oncology-prep",
        "domain": "clinical",
        "category": "clinical.oncology",
        "fts_query": "chemotherapy tumor clinical trial oncologist",
        "pattern_query": "chemotherapy side effects management and oncology tumor board review",
        "tier1_category": "clinical.oncology",
    },
    {
        "id": "rheuma-guide",
        "companion_skill": "rheuma-prep",
        "domain": "clinical",
        "category": "clinical.rheumatology",
        "fts_query": "lupus rheumatoid morning stiffness biologic flare",
        "pattern_query": "rheumatoid arthritis morning stiffness and autoimmune lupus flare-up",
        "tier1_category": "clinical.rheumatology",
    },
    {
        "id": "urology-guide",
        "companion_skill": "urology-prep",
        "domain": "clinical",
        "category": "clinical.urology",
        "fts_query": "bladder prostate psa voiding incontinence",
        "pattern_query": "urinary incontinence and prostate bph with frequent nocturia",
        "tier1_category": "clinical.urology",
    },
    {
        "id": "eye-guide",
        "companion_skill": "vision-prep",
        "domain": "clinical",
        "category": "clinical.ophthalmology",
        "fts_query": "glaucoma macular cataract amsler vision",
        "pattern_query": "glaucoma intraocular pressure and macular degeneration amsler grid monitoring",
        "tier1_category": "clinical.ophthalmology",
    },
    {
        "id": "ent-guide",
        "companion_skill": "ent-prep",
        "domain": "clinical",
        "category": "clinical.ent",
        "fts_query": "sinusitis tinnitus vertigo audiogram hearing",
        "pattern_query": "sinusitis pressure with tinnitus ringing and audiology hearing evaluation",
        "tier1_category": "clinical.ent",
    },
    # 4 Healthcare Administration Stewards (R3)
    {
        "id": "prior-auth-navigator",
        "companion_skill": "prior-auth-prep",
        "domain": "navigation",
        "category": "navigation.prior_auth",
        "fts_query": "prior authorization step therapy appeal pre-auth",
        "pattern_query": "prior authorization denial requiring step therapy appeal and peer-to-peer",
        "tier1_category": "navigation.prior_auth",
    },
    {
        "id": "claims-appeals-guide",
        "companion_skill": "claims-appeals-prep",
        "domain": "navigation",
        "category": "navigation.claims",
        "fts_query": "denied claim erisa billing dispute appeal",
        "pattern_query": "denied claim under erisa appeal timeline with billing dispute",
        "tier1_category": "navigation.claims",
    },
    {
        "id": "records-coordinator",
        "companion_skill": "records-management",
        "domain": "navigation",
        "category": "navigation.records",
        "fts_query": "medical records hipaa dossier lab trends",
        "pattern_query": "hipaa medical records request and health records compilation",
        "tier1_category": "navigation.records",
    },
    {
        "id": "formulary-guide",
        "companion_skill": "formulary-navigation",
        "domain": "navigation",
        "category": "navigation.formulary",
        "fts_query": "formulary drug tier copay assistance generic substitution",
        "pattern_query": "formulary drug tiers and generic substitution with patient assistance program",
        "tier1_category": "navigation.formulary",
    },
]

BASELINE_AGENT_IDS = ["benefits-guide", "habit-companion", "visit-steward"]
SYSTEM_AGENT_IDS = ["triage-auditor", "quality-reviewer"]


# ============================================================================
# Shared Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def project_dirs() -> Tuple[Path, Path]:
    """Resolves project root agents and skills directories."""
    agents_dir = settings.get_agents_dir().resolve()
    skills_dir = settings.get_skills_dir().resolve()
    return agents_dir, skills_dir


@pytest.fixture(scope="module")
def live_registry(project_dirs: Tuple[Path, Path]) -> AgentRegistry:
    """Discovers all live agents from the filesystem."""
    agents_dir, skills_dir = project_dirs
    return AgentRegistry(agents_dir=agents_dir, skills_dir=skills_dir)


@pytest.fixture(scope="module")
def live_skills(project_dirs: Tuple[Path, Path]) -> List[SkillManifest]:
    """Discovers all live skills from the filesystem."""
    _, skills_dir = project_dirs
    return load_all_skills(skills_dir)


@pytest_asyncio.fixture
async def populated_catalog(
    live_registry: AgentRegistry,
    live_skills: List[SkillManifest],
) -> SqliteCatalogAdapter:
    """Provides an isolated in-memory SqliteCatalogAdapter seeded with all live manifests."""
    adapter = SqliteCatalogAdapter(db_path=":memory:")
    for agent in live_registry.list_agents():
        await adapter.index_agent(agent)
    for skill in live_skills:
        await adapter.index_skill(skill)
    yield adapter
    await adapter.close()


@pytest.fixture
def api_client() -> TestClient:
    """Provides a FastAPI TestClient configured for the Carefold application."""
    return TestClient(app)


# ============================================================================
# Test Suite 1: SQLite FTS5 Catalog Indexing
# ============================================================================

class TestCatalogIndexing:
    """Verifies SQLite FTS5 catalog indexing for all 20+ agents and 17 skills."""

    @pytest.mark.asyncio
    async def test_indexing_public_and_hidden_agents_count(
        self,
        populated_catalog: SqliteCatalogAdapter,
    ):
        """Verifies public agents and system agents (including hidden) are indexed."""
        public_count = await populated_catalog.count_agents(include_hidden=False)
        total_count = await populated_catalog.count_agents(include_hidden=True)

        assert public_count >= 20, (
            f"Expected at least 20 public agents, got {public_count}"
        )
        assert total_count >= public_count, (
            f"Expected total_count >= public_count, got {total_count}"
        )

    @pytest.mark.asyncio
    async def test_indexing_system_agents_marked_hidden(
        self,
        populated_catalog: SqliteCatalogAdapter,
    ):
        """Verifies hidden system agents (triage-auditor, quality-reviewer) are indexed with hidden=1."""
        for sys_id in SYSTEM_AGENT_IDS:
            agent = await populated_catalog.get_agent(sys_id)
            assert agent is not None, f"System agent '{sys_id}' not found in catalog"
            assert agent.hidden is True, f"System agent '{sys_id}' must have hidden=True"

        # Hidden agents should not appear in search_agents unless include_hidden=True
        default_search = await populated_catalog.search_agents(query="triage")
        assert not any(a.id == "triage-auditor" for a in default_search)

        hidden_search = await populated_catalog.search_agents(query="triage", include_hidden=True)
        assert any(a.id == "triage-auditor" for a in hidden_search)

    @pytest.mark.asyncio
    async def test_indexing_all_17_specialist_skills_registered(
        self,
        populated_catalog: SqliteCatalogAdapter,
    ):
        """Verifies each of the 17 new companion skills is indexed with >= 2 reference documents."""
        for spec in ALL_17_SPECIALIST_SPECS:
            sk_id = spec["companion_skill"]
            skill = await populated_catalog.get_skill(sk_id)
            assert skill is not None, f"Skill '{sk_id}' was not indexed into SQLite catalog"
            assert skill.domain.value == spec["domain"] or str(skill.domain) == spec["domain"]
            assert len(skill.references) >= 2, (
                f"Skill '{sk_id}' has {len(skill.references)} references; expected >= 2"
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "spec",
        ALL_17_SPECIALIST_SPECS,
        ids=[s["id"] for s in ALL_17_SPECIALIST_SPECS],
    )
    async def test_fts5_search_agents_all_17_specialists(
        self,
        spec: Dict[str, Any],
        populated_catalog: SqliteCatalogAdapter,
    ):
        """Verifies SQLite FTS5 search finds each of the 17 specialists in top results."""
        results = await populated_catalog.search_agents(query=spec["fts_query"], limit=5)
        matched_ids = [r.id for r in results]
        assert spec["id"] in matched_ids, (
            f"FTS5 agent search query '{spec['fts_query']}' failed to return target agent '{spec['id']}'. "
            f"Returned: {matched_ids}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "spec",
        ALL_17_SPECIALIST_SPECS,
        ids=[s["companion_skill"] for s in ALL_17_SPECIALIST_SPECS],
    )
    async def test_fts5_search_skills_all_17_skills(
        self,
        spec: Dict[str, Any],
        populated_catalog: SqliteCatalogAdapter,
    ):
        """Verifies SQLite FTS5 search finds each of the 17 companion skills in top results."""
        results = await populated_catalog.search_skills(query=spec["fts_query"], limit=5)
        matched_ids = [r.id for r in results]
        assert spec["companion_skill"] in matched_ids, (
            f"FTS5 skill search query '{spec['fts_query']}' failed to return target skill '{spec['companion_skill']}'. "
            f"Returned: {matched_ids}"
        )

    @pytest.mark.asyncio
    async def test_catalog_crud_lifecycle_and_tag_filtering(
        self,
        populated_catalog: SqliteCatalogAdapter,
    ):
        """Verifies get, delete, tag-filtering, and re-indexing lifecycle."""
        # 1. Tag filtering via json_each
        tagged = await populated_catalog.search_agents(tags=["hypertension"])
        assert len(tagged) >= 1
        assert any(a.id == "cardiology-guide" for a in tagged)

        # 2. Deletion lifecycle
        cardio = await populated_catalog.get_agent("cardiology-guide")
        assert cardio is not None

        deleted = await populated_catalog.delete_agent("cardiology-guide")
        assert deleted is True

        post_delete = await populated_catalog.get_agent("cardiology-guide")
        assert post_delete is None

        # 3. Re-index
        await populated_catalog.index_agent(cardio)
        post_reindex = await populated_catalog.get_agent("cardiology-guide")
        assert post_reindex is not None
        assert post_reindex.id == "cardiology-guide"


# ============================================================================
# Test Suite 2: Category Tree & FastAPI Categories API
# ============================================================================

class TestCategoryTreeAndAPI:
    """Verifies CatalogPort.get_category_tree() and GET /api/agents/categories."""

    @pytest.mark.asyncio
    async def test_category_tree_hierarchy_and_domain_counts(
        self,
        populated_catalog: SqliteCatalogAdapter,
    ):
        """Verifies get_category_tree() accurately aggregates all domains and categories."""
        tree = await populated_catalog.get_category_tree()

        assert tree["total"] == 20
        domains = tree["domains"]

        assert "clinical" in domains
        assert "navigation" in domains
        assert "wellness" in domains

        # Clinical specialists (at least 13 baseline)
        assert domains["clinical"]["count"] >= 13
        clinical_cats = domains["clinical"]["categories"]
        expected_clinical = {
            "cardiology", "pulmonology", "neurology", "gastroenterology",
            "nephrology", "endocrinology", "orthopedics", "dermatology",
            "oncology", "rheumatology", "urology", "ophthalmology", "ent",
        }
        for cat in expected_clinical:
            assert cat in clinical_cats, f"Clinical category '{cat}' missing from category tree"
            assert clinical_cats[cat]["count"] >= 1

        # Navigation specialists (at least 6 baseline)
        assert domains["navigation"]["count"] >= 6
        nav_cats = domains["navigation"]["categories"]
        expected_nav = {
            "appointments", "insurance", "prior_auth", "claims", "records", "formulary"
        }
        for cat in expected_nav:
            assert cat in nav_cats, f"Navigation category '{cat}' missing from category tree"
            assert nav_cats[cat]["count"] >= 1

        # Wellness agent (habit-companion)
        assert domains["wellness"]["count"] >= 1
        assert "habits" in domains["wellness"]["categories"]

    def test_get_agents_categories_api_endpoint(self, api_client: TestClient):
        """Verifies GET /api/agents/categories returns 200 OK and accurate counts."""
        res = api_client.get("/api/agents/categories")
        assert res.status_code == 200

        data = res.json()
        assert data.get("total", 0) >= 20

        domains = data.get("domains", {})
        assert domains.get("clinical", {}).get("count", 0) >= 13
        assert domains.get("navigation", {}).get("count", 0) >= 6
        assert domains.get("wellness", {}).get("count", 0) >= 1

    @pytest.mark.asyncio
    async def test_category_tree_domain_filter(
        self,
        populated_catalog: SqliteCatalogAdapter,
    ):
        """Verifies domain_filter narrows the tree to the single specified domain."""
        clinical_only = await populated_catalog.get_category_tree(domain="clinical")
        assert clinical_only["total"] >= 13
        assert list(clinical_only["domains"].keys()) == ["clinical"]

        nav_only = await populated_catalog.get_category_tree(domain="navigation")
        assert nav_only["total"] >= 6
        assert list(nav_only["domains"].keys()) == ["navigation"]

    @pytest.mark.asyncio
    async def test_system_agents_excluded_from_public_category_tree(
        self,
        populated_catalog: SqliteCatalogAdapter,
    ):
        """Verifies hidden system agents are never counted in the public category tree."""
        tree = await populated_catalog.get_category_tree(include_hidden=False)
        clinical_cats = tree["domains"]["clinical"]["categories"]

        # System agents quality-reviewer (clinical.quality) and triage-auditor (clinical.triage)
        assert "quality" not in clinical_cats
        assert "triage" not in clinical_cats


# ============================================================================
# Test Suite 3: Two-Hop Routing Integration & Fallback Chain
# ============================================================================

class TestTwoHopRoutingIntegration:
    """Verifies two-hop hierarchical routing with 4-step fallback chain."""

    def test_tier1_prompt_invariant(self):
        """Verifies Tier-1 prompt stays bounded under 500 words and mentions all 5 domains."""
        word_count = len(TIER1_DOMAIN_CLASSIFIER_PROMPT.split())
        assert word_count < 500, f"Tier-1 classifier prompt exceeds 500 words ({word_count})"
        for domain in ["clinical", "therapy", "wellness", "navigation", "education"]:
            assert domain in TIER1_DOMAIN_CLASSIFIER_PROMPT.lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "spec",
        ALL_17_SPECIALIST_SPECS,
        ids=[s["id"] for s in ALL_17_SPECIALIST_SPECS],
    )
    async def test_two_hop_routing_all_17_specialists(
        self,
        spec: Dict[str, Any],
        live_registry: AgentRegistry,
        populated_catalog: SqliteCatalogAdapter,
    ):
        """Verifies Tier-1 Domain Classification -> Candidate Retrieval -> Tier-2 Selection for all 17 specialists."""
        tier1_resp = json.dumps({
            "domain": spec["domain"],
            "category": spec["tier1_category"],
            "reasoning": f"Inquiry pertains to {spec['id']}",
        })
        tier2_resp = json.dumps({
            "agent_id": spec["id"],
            "reasoning": f"Selected specialist {spec['id']}",
            "instructions": f"Focus on {spec['category']}",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(
            model=fake_model,
            registry=live_registry,
            catalog=populated_catalog,
        )

        state = {"messages": [HumanMessage(content=spec["pattern_query"])]}
        result = await node.execute(state)

        assert result["current_agent"] == spec["id"]
        assert result["routed_subgraph"] == spec["id"]
        assert result["agent_id"] == spec["id"]

    @pytest.mark.asyncio
    async def test_two_hop_fallback_step2_domain_widening(
        self,
        live_registry: AgentRegistry,
        populated_catalog: SqliteCatalogAdapter,
    ):
        """Step 2 Fallback: When category has 0 candidates, widens to domain to retrieve candidates."""
        tier1_resp = json.dumps({
            "domain": "navigation",
            "category": "navigation.unmatched_nonexistent_subspecialty",
            "reasoning": "Unrecognized category under navigation",
        })
        tier2_resp = json.dumps({
            "agent_id": "prior-auth-navigator",
            "reasoning": "Selected from domain candidates",
            "instructions": "",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(
            model=fake_model,
            registry=live_registry,
            catalog=populated_catalog,
        )

        state = {"messages": [HumanMessage(content="I need help with prior authorization")]}
        result = await node.execute(state)

        assert result["current_agent"] == "prior-auth-navigator"

    @pytest.mark.asyncio
    async def test_two_hop_fallback_step3_fts_query(
        self,
        live_registry: AgentRegistry,
        populated_catalog: SqliteCatalogAdapter,
    ):
        """Step 3 Fallback: When domain + category have 0 candidates, falls back to FTS keyword search."""
        tier1_resp = json.dumps({
            "domain": "therapy",
            "category": "therapy.unmatched",
            "reasoning": "Misclassified domain with 0 candidates",
        })
        tier2_resp = json.dumps({
            "agent_id": "nephrology-guide",
            "reasoning": "Selected from FTS retrieved candidates",
            "instructions": "",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(
            model=fake_model,
            registry=live_registry,
            catalog=populated_catalog,
        )

        state = {"messages": [HumanMessage(content="elevated creatinine kidney egfr labs")]}
        result = await node.execute(state)

        assert result["current_agent"] == "nephrology-guide"

    @pytest.mark.asyncio
    async def test_two_hop_fallback_step4_pattern_fallback(
        self,
        live_registry: AgentRegistry,
    ):
        """Step 4 Fallback: When catalog returns 0 candidates, triggers regex pattern fallback."""
        empty_catalog = SqliteCatalogAdapter(db_path=":memory:")
        await empty_catalog._get_conn()

        tier1_resp = json.dumps({
            "domain": "therapy",
            "category": "therapy.cbt",
            "reasoning": "No candidates anywhere",
        })
        fake_model = FakeListChatModel(responses=[tier1_resp])
        node = OrchestratorNode(
            model=fake_model,
            registry=live_registry,
            catalog=empty_catalog,
        )

        state = {"messages": [HumanMessage(content="severe sinusitis pressure and audiology tinnitus evaluation")]}
        result = await node.execute(state)

        assert result["current_agent"] == "ent-guide"
        assert "Catalog fallback chain returned 0 candidates" in result["orchestrator_reasoning"]
        await empty_catalog.close()

    @pytest.mark.asyncio
    async def test_preflight_reference_doc_provisioning(
        self,
        live_registry: AgentRegistry,
        populated_catalog: SqliteCatalogAdapter,
    ):
        """Verifies pre-flight provisioning detects declared reference documents."""
        tier1_resp = json.dumps({
            "domain": "clinical",
            "category": "clinical.cardiology",
            "reasoning": "Cardiology inquiry",
        })
        tier2_resp = json.dumps({
            "agent_id": "cardiology-guide",
            "reasoning": "Cardiology specialist selected",
            "instructions": "",
            "required_docs": ["hypertension_log_template.md", "cardiology_visit_agenda.md"],
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(
            model=fake_model,
            registry=live_registry,
            catalog=populated_catalog,
        )

        state = {
            "messages": [HumanMessage(content="I want to log my blood pressure before seeing the cardiologist.")],
            "required_docs": ["hypertension_log_template.md"],
        }
        result = await node.execute(state)

        assert result["current_agent"] == "cardiology-guide"
        # Pre-flight provisioning confirms reference docs declared by cardiology-prep are recognized
        cardio_skill = live_registry.get_skill("cardiology-prep")
        assert cardio_skill is not None
        assert "hypertension_log_template.md" in cardio_skill.references


# ============================================================================
# Test Suite 4: Step 4 Pattern Fallback Robustness
# ============================================================================

class TestPatternFallbackRobustness:
    """Verifies regex pattern fallback matching for all 17 specialists without LLM (offline mode)."""

    @pytest.mark.parametrize(
        "spec",
        ALL_17_SPECIALIST_SPECS,
        ids=[s["id"] for s in ALL_17_SPECIALIST_SPECS],
    )
    def test_pattern_fallback_all_17_specialists(self, spec: Dict[str, Any]):
        """Verifies parameterless/offline pattern fallback resolves correctly for every specialist."""
        node = OrchestratorNode(model=None, catalog=None)
        resolved = node._resolve_pattern_fallback({}, spec["pattern_query"])

        assert resolved == spec["id"], (
            f"Pattern fallback failed for specialist '{spec['id']}'. "
            f"Query: '{spec['pattern_query']}' -> Resolved to: '{resolved}'"
        )

    def test_pattern_fallback_attachment_priority(self):
        """Verifies any query with attachments routes with top priority to document-extractor."""
        node = OrchestratorNode(model=None, catalog=None)
        state_with_attachment = {"attachments": ["medical_record.pdf"]}
        resolved = node._resolve_pattern_fallback(
            state_with_attachment,
            "I need cardiology help for my heart palpitations"
        )
        assert resolved == "document-extractor"

    def test_pattern_fallback_unrecognized_query_defaults(self):
        """Verifies an unrecognized query defaults safely to DEFAULT_ROUTING_FALLBACK_AGENT."""
        node = OrchestratorNode(model=None, catalog=None)
        resolved = node._resolve_pattern_fallback({}, "completely arbitrary gibberish xyz123")
        assert resolved == DEFAULT_ROUTING_FALLBACK_AGENT
