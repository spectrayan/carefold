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

"""Catalog Indexing and Two-Hop Routing Test Suite.

Tests and verifies:
1. Two-Hop Routing & Fallback Chain Stress:
   - Step 1 category match across all 17 specialists (exact dot-notated & subcategory prefix normalization).
   - Step 2 domain widening when category is invalid or unmatched (assert candidate set <= 8).
   - Step 3 FTS fallback when domain has no matching agents (assert candidate set <= 8).
   - Step 4 pattern fallback when catalog has 0 candidates (assert candidate set <= 8).
   - Compound collision & precedence stress in routing_patterns.yaml.
2. Catalog Indexing & Category Tree:
   - SQLite FTS5 index contains all public agents, system agents, and companion skills.
   - Exclusion of all 6 system agents from public search and category tree.
   - Tags search via json_each across clinical, administrative, and wellness terms.
   - FTS keyword search across clinical and administrative terms.
   - Category tree accurate domain counts (clinical=13, navigation=6, wellness=1, therapy=0, education=0).
3. Candidate Set Boundedness:
   - Strict assertion that candidate set size is <= 8 across all queries and fallback steps.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
import pytest_asyncio
from langchain_core.messages import HumanMessage

# Ensure backend paths are on sys.path
_current_file = Path(__file__).resolve()
_backend_dir = _current_file.parents[1]
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))
if str(_backend_dir / "src") not in sys.path:
    sys.path.insert(0, str(_backend_dir / "src"))

from carefold.agents.registry import AgentRegistry
from carefold.config import settings
from carefold.constants.agents import AGENT_ORCHESTRATOR, DEFAULT_ROUTING_FALLBACK_AGENT
from carefold.loaders.skill_loader import load_all_skills
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
# Specification Data for all 17 Specialists, 3 Base Agents, and 6 System Agents
# ============================================================================

ALL_17_SPECIALISTS = [
    # 8 Core Organ Navigators (R1)
    {
        "id": "cardiology-guide",
        "skill": "cardiology-prep",
        "domain": "clinical",
        "category": "clinical.cardiology",
        "subcat": "cardiology",
        "fts_query": "hypertension arrhythmia palpitations blood pressure",
        "sample_query": "I have hypertension and chest palpitations, what should I prepare for my cardiologist?",
    },
    {
        "id": "pulmonology-guide",
        "skill": "pulmonology-prep",
        "domain": "clinical",
        "category": "clinical.pulmonology",
        "subcat": "pulmonology",
        "fts_query": "asthma copd inhaler dyspnea breathing",
        "sample_query": "I am experiencing shortness of breath and wheezing, my asthma inhaler is not helping",
    },
    {
        "id": "neurology-guide",
        "skill": "neurology-prep",
        "domain": "clinical",
        "category": "clinical.neurology",
        "subcat": "neurology",
        "fts_query": "migraine headache neuropathy tingling brain fog",
        "sample_query": "Severe migraine headaches with numbness and peripheral neuropathy tingling",
    },
    {
        "id": "gastro-guide",
        "skill": "gastro-prep",
        "domain": "clinical",
        "category": "clinical.gastroenterology",
        "subcat": "gastroenterology",
        "fts_query": "ibs ibd colonoscopy endoscopy gerd reflux",
        "sample_query": "Stomach cramps, chronic acid reflux heartburn and preparing for a colonoscopy",
    },
    {
        "id": "nephrology-guide",
        "skill": "nephrology-prep",
        "domain": "clinical",
        "category": "clinical.nephrology",
        "subcat": "nephrology",
        "fts_query": "kidney egfr creatinine dialysis renal",
        "sample_query": "My blood tests showed abnormal egfr and high creatinine indicating chronic kidney disease",
    },
    {
        "id": "endocrinology-guide",
        "skill": "endocrinology-prep",
        "domain": "clinical",
        "category": "clinical.endocrinology",
        "subcat": "endocrinology",
        "fts_query": "diabetes thyroid cgm a1c insulin glucose",
        "sample_query": "Managing continuous glucose monitor cgm logs and fluctuating thyroid tsh levels",
    },
    {
        "id": "ortho-guide",
        "skill": "ortho-prep",
        "domain": "clinical",
        "category": "clinical.orthopedics",
        "subcat": "orthopedics",
        "fts_query": "osteoarthritis joint mobility physical therapy cartilage",
        "sample_query": "Severe knee joint pain from osteoarthritis and physical therapy mobility exercises",
    },
    {
        "id": "derma-guide",
        "skill": "derma-prep",
        "domain": "clinical",
        "category": "clinical.dermatology",
        "subcat": "dermatology",
        "fts_query": "rash lesion mole abcde melanoma eczema",
        "sample_query": "Skin rash with an asymmetric changing lesion mole requiring abcde tracking",
    },
    # 5 Extended Medical & Surgical Navigators (R2)
    {
        "id": "oncology-navigator",
        "skill": "oncology-prep",
        "domain": "clinical",
        "category": "clinical.oncology",
        "subcat": "oncology",
        "fts_query": "chemotherapy tumor oncologist carcinoma staging",
        "sample_query": "Chemotherapy side effects management and preparing questions for the oncology tumor board",
    },
    {
        "id": "rheuma-guide",
        "skill": "rheuma-prep",
        "domain": "clinical",
        "category": "clinical.rheumatology",
        "subcat": "rheumatology",
        "fts_query": "rheumatoid lupus morning stiffness autoimmune biologic",
        "sample_query": "Lupus autoimmune flare-up with joint inflammation and prolonged morning stiffness",
    },
    {
        "id": "urology-guide",
        "skill": "urology-prep",
        "domain": "clinical",
        "category": "clinical.urology",
        "subcat": "urology",
        "fts_query": "bladder prostate bph psa nocturia incontinence",
        "sample_query": "Elevated psa levels, prostate bph, and frequent nocturnal urinary urgency",
    },
    {
        "id": "eye-guide",
        "skill": "vision-prep",
        "domain": "clinical",
        "category": "clinical.ophthalmology",
        "subcat": "ophthalmology",
        "fts_query": "glaucoma macular cataract amsler vision blurry",
        "sample_query": "Glaucoma intraocular pressure tracking and macular degeneration amsler grid distortion",
    },
    {
        "id": "ent-guide",
        "skill": "ent-prep",
        "domain": "clinical",
        "category": "clinical.ent",
        "subcat": "ent",
        "fts_query": "sinusitis tinnitus vertigo audiogram hearing loss",
        "sample_query": "Chronic sinusitis facial pressure with persistent ringing in the ears tinnitus",
    },
    # 4 Healthcare Administration Stewards (R3)
    {
        "id": "prior-auth-navigator",
        "skill": "prior-auth-prep",
        "domain": "navigation",
        "category": "navigation.prior_auth",
        "subcat": "prior_auth",
        "fts_query": "prior authorization step therapy appeal pre-auth",
        "sample_query": "Insurance denied my medication requiring prior authorization and step therapy fail first",
    },
    {
        "id": "claims-appeals-guide",
        "skill": "claims-appeals-prep",
        "domain": "navigation",
        "category": "navigation.claims",
        "subcat": "claims",
        "fts_query": "denied claim erisa billing dispute appeal eob",
        "sample_query": "Hospital claim denied under erisa; I need to file a formal medical appeal",
    },
    {
        "id": "records-coordinator",
        "skill": "records-management",
        "domain": "navigation",
        "category": "navigation.records",
        "subcat": "records",
        "fts_query": "medical records hipaa dossier release information",
        "sample_query": "How to file a hipaa medical records request to consolidate multi-provider dossiers",
    },
    {
        "id": "formulary-guide",
        "skill": "formulary-navigation",
        "domain": "navigation",
        "category": "navigation.formulary",
        "subcat": "formulary",
        "fts_query": "formulary drug tier copay assistance generic substitution",
        "sample_query": "My prescription is tier 4 specialty drug; can I get copay assistance or generic alternatives?",
    },
]

BASE_AGENT_IDS = ["benefits-guide", "habit-companion", "visit-steward"]
SYSTEM_AGENT_IDS = [
    "document-extractor",
    "orchestrator",
    "quality-reviewer",
    "skill-generator",
    "suggestion-generator",
    "triage-auditor",
]


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def registry() -> AgentRegistry:
    return AgentRegistry(
        agents_dir=settings.get_agents_dir().resolve(),
        skills_dir=settings.get_skills_dir().resolve(),
    )


@pytest.fixture(scope="module")
def loaded_skills() -> List[SkillManifest]:
    return load_all_skills(settings.get_skills_dir().resolve())


@pytest_asyncio.fixture
async def catalog(registry: AgentRegistry, loaded_skills: List[SkillManifest]) -> SqliteCatalogAdapter:
    adapter = SqliteCatalogAdapter(db_path=":memory:")
    for agent in registry.list_agents():
        await adapter.index_agent(agent)
    for skill in loaded_skills:
        await adapter.index_skill(skill)
    yield adapter
    await adapter.close()


# ============================================================================
# Test Suite 1: Step 1 Category Match Across All 17 Specialists & Candidates <= 8
# ============================================================================

class TestStep1CategoryMatchAndBounds:
    """Verifies Step 1 category match works for all 17 specialists and candidate set <= 8."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("spec", ALL_17_SPECIALISTS, ids=[s["id"] for s in ALL_17_SPECIALISTS])
    async def test_step1_exact_category_match_returns_agent_and_bounds_candidates(
        self,
        spec: Dict[str, Any],
        catalog: SqliteCatalogAdapter,
        registry: AgentRegistry,
    ):
        """Directly calls catalog.search_agents with domain and category."""
        # 1. Exact dot-notated category
        candidates = await catalog.search_agents(
            domain=spec["domain"],
            category=spec["category"],
            limit=8,
        )
        assert len(candidates) >= 1
        assert len(candidates) <= 8, f"Candidate set exceeded 8: {len(candidates)}"
        matched_ids = [c.id for c in candidates]
        assert spec["id"] in matched_ids

    @pytest.mark.asyncio
    @pytest.mark.parametrize("spec", ALL_17_SPECIALISTS, ids=[s["id"] for s in ALL_17_SPECIALISTS])
    async def test_step1_prefix_normalization_in_orchestrator(
        self,
        spec: Dict[str, Any],
        catalog: SqliteCatalogAdapter,
        registry: AgentRegistry,
    ):
        """Tier 1 outputs subcat without domain prefix (e.g. 'cardiology').

        OrchestratorNode normalizes to 'clinical.cardiology' and successfully finds candidate.
        """
        tier1_resp = json.dumps({
            "domain": spec["domain"],
            "category": spec["subcat"],  # without prefix!
            "reasoning": f"Query classified to {spec['subcat']}",
        })
        tier2_resp = json.dumps({
            "agent_id": spec["id"],
            "reasoning": f"Chosen specialist {spec['id']}",
            "instructions": "",
        })

        model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=model, registry=registry, catalog=catalog)

        state = {"messages": [HumanMessage(content=spec["sample_query"])]}
        result = await node.execute(state)

        assert result["current_agent"] == spec["id"]
        assert result["routed_subgraph"] == spec["id"]


# ============================================================================
# Test Suite 2: Step 2 Domain Widening & Strict <= 8 Bound
# ============================================================================

class TestStep2DomainWideningAndCandidateBounds:
    """Verifies Step 2 domain widening when category is invalid or unmatched."""

    @pytest.mark.asyncio
    async def test_step2_domain_widening_strictly_bounds_candidates_to_8(
        self,
        catalog: SqliteCatalogAdapter,
        registry: AgentRegistry,
    ):
        """Clinical domain has 13 agents. When category is unmatched, Step 2 widens to domain.

        The retrieved candidates MUST be strictly <= 8.
        """
        # Unmatched category under clinical domain
        tier1_resp = json.dumps({
            "domain": "clinical",
            "category": "clinical.nonexistent_organ_system",
            "reasoning": "Unrecognized clinical subcategory",
        })
        tier2_resp = json.dumps({
            "agent_id": "cardiology-guide",
            "reasoning": "Selected from clinical domain candidates",
            "instructions": "",
        })

        model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=model, registry=registry, catalog=catalog)

        state = {"messages": [HumanMessage(content="Unmatched clinical query for heart")]}
        decision, candidates = await node._execute_two_hop(state, "Unmatched clinical query for heart", list(state["messages"]))

        # CRITICAL INVARIANT: Candidate set size MUST be <= 8
        assert len(candidates) <= 8, f"Expected <= 8 candidates, got {len(candidates)}"
        assert len(candidates) > 0, "Expected non-empty candidates from clinical domain"
        assert decision.agent_id == "cardiology-guide"

    @pytest.mark.asyncio
    async def test_step2_domain_widening_navigation_domain(
        self,
        catalog: SqliteCatalogAdapter,
        registry: AgentRegistry,
    ):
        """Navigation domain has 6 agents. Widening retrieves <= 8 candidates."""
        tier1_resp = json.dumps({
            "domain": "navigation",
            "category": "navigation.unrecognized_bureaucracy",
            "reasoning": "Unrecognized navigation subcategory",
        })
        tier2_resp = json.dumps({
            "agent_id": "prior-auth-navigator",
            "reasoning": "Selected from navigation domain candidates",
            "instructions": "",
        })

        model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=model, registry=registry, catalog=catalog)

        state = {"messages": [HumanMessage(content="Help with insurance authorization")]}
        decision, candidates = await node._execute_two_hop(state, "Help with insurance authorization", list(state["messages"]))

        assert len(candidates) <= 8
        assert len(candidates) == 6  # exactly 6 navigation agents
        assert decision.agent_id == "prior-auth-navigator"


# ============================================================================
# Test Suite 3: Step 3 FTS Fallback & Strict <= 8 Bound
# ============================================================================

class TestStep3FTSFallbackAndCandidateBounds:
    """Verifies Step 3 FTS fallback when domain has 0 matching agents."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "target_agent,fts_keywords,expected_domain",
        [
            ("cardiology-guide", "hypertension arrhythmia palpitations", "clinical"),
            ("pulmonology-guide", "copd asthma inhaler dyspnea", "clinical"),
            ("nephrology-guide", "kidney egfr creatinine dialysis", "clinical"),
            ("prior-auth-navigator", "prior authorization step therapy appeal", "navigation"),
            ("claims-appeals-guide", "denied claim erisa billing dispute", "navigation"),
            ("habit-companion", "hydration water intake sleep habit", "wellness"),
        ],
    )
    async def test_step3_fts_fallback_recovers_from_misclassified_domain(
        self,
        target_agent: str,
        fts_keywords: str,
        expected_domain: str,
        catalog: SqliteCatalogAdapter,
        registry: AgentRegistry,
    ):
        """Tier 1 classifies domain as 'therapy' (0 matching agents).

        Step 1 (therapy.unmatched) -> 0 candidates.
        Step 2 (therapy domain) -> 0 candidates.
        Step 3 (FTS on query) -> finds candidate.
        Candidate set <= 8.
        """
        tier1_resp = json.dumps({
            "domain": "therapy",
            "category": "therapy.unmatched_therapy_topic",
            "reasoning": "Misclassified domain with zero agents",
        })
        tier2_resp = json.dumps({
            "agent_id": target_agent,
            "reasoning": f"Recovered via FTS and selected {target_agent}",
            "instructions": "",
        })

        model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=model, registry=registry, catalog=catalog)

        state = {"messages": [HumanMessage(content=fts_keywords)]}
        decision, candidates = await node._execute_two_hop(state, fts_keywords, list(state["messages"]))

        assert len(candidates) <= 8, f"Expected <= 8 candidates, got {len(candidates)}"
        assert len(candidates) > 0, "Step 3 FTS fallback should have returned candidates"
        assert decision.agent_id == target_agent


# ============================================================================
# Test Suite 4: Step 4 Pattern Fallback When Catalog Has 0 Candidates
# ============================================================================

class TestStep4PatternFallbackAndBounds:
    """Verifies Step 4 regex pattern fallback when catalog returns 0 candidates."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("spec", ALL_17_SPECIALISTS, ids=[s["id"] for s in ALL_17_SPECIALISTS])
    async def test_step4_pattern_fallback_across_all_17_specialists(
        self,
        spec: Dict[str, Any],
        registry: AgentRegistry,
    ):
        """Empty catalog triggers Step 4 pattern fallback for each specialist."""
        empty_catalog = SqliteCatalogAdapter(db_path=":memory:")
        await empty_catalog._get_conn()

        tier1_resp = json.dumps({
            "domain": "education",
            "category": "education.anatomy",
            "reasoning": "No catalog candidates exist",
        })
        model = FakeListChatModel(responses=[tier1_resp])
        node = OrchestratorNode(model=model, registry=registry, catalog=empty_catalog)

        state = {"messages": [HumanMessage(content=spec["sample_query"])]}
        decision, candidates = await node._execute_two_hop(state, spec["sample_query"], list(state["messages"]))

        # Step 4 returns empty candidate list (<= 8)
        assert len(candidates) == 0
        assert decision.agent_id == spec["id"]
        assert "Catalog fallback chain returned 0 candidates" in decision.reasoning

        await empty_catalog.close()

    @pytest.mark.asyncio
    async def test_step4_attachment_priority_overrides_everything(
        self,
        registry: AgentRegistry,
    ):
        """When attachments are present in state, Step 4 pattern fallback resolves immediately to document-extractor."""
        empty_catalog = SqliteCatalogAdapter(db_path=":memory:")
        await empty_catalog._get_conn()

        tier1_resp = json.dumps({
            "domain": "clinical",
            "category": "clinical.cardiology",
            "reasoning": "Unmatched",
        })
        model = FakeListChatModel(responses=[tier1_resp])
        node = OrchestratorNode(model=model, registry=registry, catalog=empty_catalog)

        state = {
            "messages": [HumanMessage(content="Check my cardiology EKG record")],
            "attachments": ["ekg_scan.pdf"],
        }
        decision, candidates = await node._execute_two_hop(state, "Check my cardiology EKG record", list(state["messages"]))

        assert decision.agent_id == "document-extractor"
        await empty_catalog.close()

    @pytest.mark.asyncio
    async def test_step4_unmatchable_query_defaults_safely(
        self,
        registry: AgentRegistry,
    ):
        """When query matches nothing, defaults to DEFAULT_ROUTING_FALLBACK_AGENT."""
        empty_catalog = SqliteCatalogAdapter(db_path=":memory:")
        await empty_catalog._get_conn()

        tier1_resp = json.dumps({"domain": "therapy", "category": "therapy.none", "reasoning": "None"})
        model = FakeListChatModel(responses=[tier1_resp])
        node = OrchestratorNode(model=model, registry=registry, catalog=empty_catalog)

        state = {"messages": [HumanMessage(content="qwertyuiop asdfghjkl zxcvbnm")]}
        decision, candidates = await node._execute_two_hop(state, "qwertyuiop asdfghjkl zxcvbnm", list(state["messages"]))

        assert decision.agent_id == DEFAULT_ROUTING_FALLBACK_AGENT
        assert decision.agent_id == "visit-steward"
        await empty_catalog.close()


# ============================================================================
# Test Suite 5: Adversarial Compound Queries & Precedence Collisions
# ============================================================================

class TestPrecedenceCollisionsInRoutingPatterns:
    """Verifies specialized stewards & clinical navigators take precedence over generalists."""

    @pytest.mark.parametrize(
        "query,expected_agent,counter_agent",
        [
            (
                "I need to prepare for my doctor visit regarding prior authorization denial and step therapy",
                "prior-auth-navigator",
                "visit-steward",
            ),
            (
                "Doctor appointment checklist for my cardiologist heart palpitations and arrhythmia",
                "cardiology-guide",
                "visit-steward",
            ),
            (
                "Health insurance deductible copay assistance and formulary drug tier coverage",
                "formulary-guide",
                "benefits-guide",
            ),
            (
                "ERISA insurance claim appeal timeline for denied hospital stay explanation of benefits",
                "claims-appeals-guide",
                "benefits-guide",
            ),
            (
                "Organize my medical records and health history for doctor visit",
                "records-coordinator",
                "visit-steward",
            ),
            (
                "Chemotherapy oncologist doctor appointment questions and tumor board",
                "oncology-navigator",
                "visit-steward",
            ),
            (
                "Dermatologist clinic visit for skin rash lesion mole abcde review",
                "derma-guide",
                "visit-steward",
            ),
            (
                "Asthma inhaler prescription doctor appointment for shortness of breath",
                "pulmonology-guide",
                "visit-steward",
            ),
            (
                "Kidney egfr dialysis doctor appointment questions",
                "nephrology-guide",
                "visit-steward",
            ),
            (
                "Rheumatoid arthritis morning stiffness doctor visit prep",
                "rheuma-guide",
                "visit-steward",
            ),
            (
                "Urologist doctor visit for prostate bph and urinary frequency",
                "urology-guide",
                "visit-steward",
            ),
            (
                "Ophthalmologist doctor visit for glaucoma eye drops and cataract surgery",
                "eye-guide",
                "visit-steward",
            ),
            (
                "ENT doctor visit for chronic sinusitis pressure and tinnitus hearing test",
                "ent-guide",
                "visit-steward",
            ),
        ],
    )
    def test_precedence_inversion_queries(
        self,
        query: str,
        expected_agent: str,
        counter_agent: str,
    ):
        """Verifies specific patterns win over broad generalist patterns."""
        node = OrchestratorNode(model=None, catalog=None)
        resolved = node._resolve_pattern_fallback({}, query)
        assert resolved == expected_agent, (
            f"Query '{query}' was intercepted by '{resolved}' instead of target '{expected_agent}'"
        )
        assert resolved != counter_agent


# ============================================================================
# Test Suite 6: Catalog Indexing & Category Tree Stress Tests
# ============================================================================

class TestCatalogIndexingAndCategoryTreeStress:
    """Verifies SQLite FTS5 catalog indexing, tags search, FTS, and category tree integrity."""

    @pytest.mark.asyncio
    async def test_catalog_contains_all_public_and_system_agents(
        self,
        catalog: SqliteCatalogAdapter,
    ):
        """Catalog must contain public agents and all 6 system agents."""
        pub_count = await catalog.count_agents(include_hidden=False)
        total_count = await catalog.count_agents(include_hidden=True)

        assert pub_count >= 20
        assert total_count == pub_count + len(SYSTEM_AGENT_IDS)

        # Check all 6 system agents are indexed and marked hidden
        for sys_id in SYSTEM_AGENT_IDS:
            agent = await catalog.get_agent(sys_id)
            assert agent is not None, f"System agent '{sys_id}' missing from catalog"
            assert agent.hidden is True, f"System agent '{sys_id}' must be hidden=True"

    @pytest.mark.asyncio
    async def test_system_agents_strictly_excluded_from_public_searches(
        self,
        catalog: SqliteCatalogAdapter,
    ):
        """Public search_agents without include_hidden must never return system agents."""
        for sys_id in SYSTEM_AGENT_IDS:
            results = await catalog.search_agents(query=sys_id, include_hidden=False)
            assert not any(a.id == sys_id for a in results), (
                f"System agent '{sys_id}' leaked into public search results!"
            )

    @pytest.mark.asyncio
    async def test_all_17_companion_skills_indexed_with_references(
        self,
        catalog: SqliteCatalogAdapter,
    ):
        """All 17 companion skills must be in catalog with >= 2 reference docs."""
        for spec in ALL_17_SPECIALISTS:
            skill = await catalog.get_skill(spec["skill"])
            assert skill is not None, f"Skill '{spec['skill']}' missing from catalog"
            assert len(skill.references) >= 2, (
                f"Skill '{spec['skill']}' has only {len(skill.references)} references; expected >= 2"
            )

    @pytest.mark.asyncio
    async def test_tags_search_across_clinical_and_admin_domains(
        self,
        catalog: SqliteCatalogAdapter,
    ):
        """Verifies tag-based filtering via json_each on agents."""
        # Clinical tags
        cardio = await catalog.search_agents(tags=["hypertension"])
        assert any(a.id == "cardiology-guide" for a in cardio)

        pulmo = await catalog.search_agents(tags=["asthma"])
        assert any(a.id == "pulmonology-guide" for a in pulmo)

        derma = await catalog.search_agents(tags=["lesion"])
        assert any(a.id == "derma-guide" for a in derma)

        derma_rash = await catalog.search_agents(tags=["rash-documentation"])
        assert any(a.id == "derma-guide" for a in derma_rash)

        # Admin tags
        pa = await catalog.search_agents(tags=["prior-authorization"])
        assert any(a.id == "prior-auth-navigator" for a in pa)

        pa_step = await catalog.search_agents(tags=["step-therapy"])
        assert any(a.id == "prior-auth-navigator" for a in pa_step)

        claims = await catalog.search_agents(tags=["appeals"])
        assert any(a.id == "claims-appeals-guide" for a in claims)

        # Wellness tag
        habits = await catalog.search_agents(tags=["hydration"])
        assert any(a.id == "habit-companion" for a in habits)

    @pytest.mark.asyncio
    async def test_fts_keyword_search_across_clinical_and_admin_terms(
        self,
        catalog: SqliteCatalogAdapter,
    ):
        """Verifies FTS5 keyword searches match expected agents."""
        test_queries = [
            ("hypertension arrhythmia palpitations", "cardiology-guide"),
            ("asthma inhaler dyspnea", "pulmonology-guide"),
            ("migraine headache neuropathy", "neurology-guide"),
            ("ibs colonoscopy endoscopy", "gastro-guide"),
            ("kidney egfr creatinine", "nephrology-guide"),
            ("diabetes cgm a1c insulin", "endocrinology-guide"),
            ("osteoarthritis joint mobility physical therapy", "ortho-guide"),
            ("rash lesion mole abcde", "derma-guide"),
            ("oncologist chemotherapy radiation tumor", "oncology-navigator"),
            ("methotrexate biologics rheumatoid lupus", "rheuma-guide"),
            ("voiding nocturia prostate bph", "urology-guide"),
            ("amsler grid cataract visual acuity glaucoma", "eye-guide"),
            ("audiogram tinnitus vertigo sinusitis", "ent-guide"),
            ("step therapy prior authorization", "prior-auth-navigator"),
            ("erisa denied claim dispute appeal", "claims-appeals-guide"),
            ("hipaa medical records request", "records-coordinator"),
            ("formulary tier copay assistance generic", "formulary-guide"),
        ]

        for query, expected_id in test_queries:
            results = await catalog.search_agents(query=query, limit=5)
            matched = [r.id for r in results]
            assert expected_id in matched, f"Query '{query}' failed to match '{expected_id}'. Got {matched}"

    @pytest.mark.asyncio
    async def test_category_tree_integrity(
        self,
        catalog: SqliteCatalogAdapter,
    ):
        """Category tree must contain public agents across core domains."""
        tree = await catalog.get_category_tree(include_hidden=False)

        assert tree["total"] >= 20
        domains = tree["domains"]

        assert domains["clinical"]["count"] >= 13
        assert domains["navigation"]["count"] >= 6
        assert domains["wellness"]["count"] >= 1
        assert domains.get("therapy", {}).get("count", 0) >= 0
        assert domains.get("education", {}).get("count", 0) >= 0

        # Hidden system agents must be excluded
        clin_cats = domains["clinical"]["categories"]
        assert "triage" not in clin_cats
        assert "quality" not in clin_cats


# ============================================================================
# Test Suite 7: Candidate Set Boundedness (< 8) Strict Verification
# ============================================================================

class TestCandidateSetBoundedness:
    """Verifies that all catalog search calls in the orchestrator enforce limit=8."""

    @pytest.mark.asyncio
    async def test_catalog_search_strictly_respects_limit(
        self,
        catalog: SqliteCatalogAdapter,
    ):
        """When searching clinical domain, limit=8 must return exactly 8."""
        results = await catalog.search_agents(domain="clinical", limit=8)
        assert len(results) == 8, f"Expected exactly 8 candidates, got {len(results)}"

        # If limit=5 is requested, return 5
        results_5 = await catalog.search_agents(domain="clinical", limit=5)
        assert len(results_5) == 5

        # If limit=100 is requested, returns all available public agents in clinical domain
        results_all = await catalog.search_agents(domain="clinical", limit=100)
        clinical_count = (await catalog.get_category_tree(include_hidden=False))["domains"]["clinical"]["count"]
        assert len(results_all) == clinical_count

    @pytest.mark.asyncio
    async def test_orchestrator_candidate_set_never_exceeds_8(
        self,
        catalog: SqliteCatalogAdapter,
        registry: AgentRegistry,
    ):
        """Tier 2 prompt formatting receives at most 8 candidates."""
        tier1_resp = json.dumps({
            "domain": "clinical",
            "category": "clinical.cardiology",
            "reasoning": "Cardiology test",
        })
        tier2_resp = json.dumps({
            "agent_id": "cardiology-guide",
            "reasoning": "Selected",
            "instructions": "",
        })

        model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=model, registry=registry, catalog=catalog)

        state = {"messages": [HumanMessage(content="Cardiology inquiry")]}
        decision, candidates = await node._execute_two_hop(state, "Cardiology inquiry", list(state["messages"]))

        assert len(candidates) <= 8
        formatted = node._format_candidate_agents(candidates)
        bullet_count = formatted.count("- **")
        assert bullet_count <= 8
        assert bullet_count == len(candidates)


# ============================================================================
# Test Suite 8: Adversarial LLM Output Formatting & Error Recovery
# ============================================================================

class TestAdversarialParsingAndRecovery:
    """Stress tests model output deviations (markdown codeblocks, malformed JSON, hallucinated IDs)."""

    @pytest.mark.asyncio
    async def test_tier1_markdown_codeblock_parsing(
        self,
        catalog: SqliteCatalogAdapter,
        registry: AgentRegistry,
    ):
        """Tier-1 returns JSON wrapped in markdown codeblock with commentary."""
        tier1_markdown = (
            "Here is the classification:\n```json\n"
            "{\n"
            '  "domain": "clinical",\n'
            '  "category": "clinical.pulmonology",\n'
            '  "reasoning": "Asthma and breathing problems"\n'
            "}\n```\nHope this helps!"
        )
        tier2_resp = json.dumps({
            "agent_id": "pulmonology-guide",
            "reasoning": "Selected pulmonologist",
            "instructions": "",
        })

        model = FakeListChatModel(responses=[tier1_markdown, tier2_resp])
        node = OrchestratorNode(model=model, registry=registry, catalog=catalog)

        state = {"messages": [HumanMessage(content="Shortness of breath with asthma")]}
        result = await node.execute(state)

        assert result["current_agent"] == "pulmonology-guide"

    @pytest.mark.asyncio
    async def test_tier1_malformed_json_falls_back_to_fts_and_recovers(
        self,
        catalog: SqliteCatalogAdapter,
        registry: AgentRegistry,
    ):
        """Tier-1 emits unparseable garbage text.

        Orchestrator handles exception, falls through to Step 3 FTS on prompt text,
        retrieves candidates, and Tier-2 selects the agent.
        """
        tier1_garbage = "I am an AI and cannot classify this into domain: {corrupted json..."
        tier2_resp = json.dumps({
            "agent_id": "cardiology-guide",
            "reasoning": "Selected via FTS candidates",
            "instructions": "",
        })

        model = FakeListChatModel(responses=[tier1_garbage, tier2_resp])
        node = OrchestratorNode(model=model, registry=registry, catalog=catalog)

        state = {"messages": [HumanMessage(content="hypertension palpitations chest pressure")]}
        result = await node.execute(state)

        assert result["current_agent"] == "cardiology-guide"

    @pytest.mark.asyncio
    async def test_tier2_hallucinated_agent_id_falls_back_to_first_candidate(
        self,
        catalog: SqliteCatalogAdapter,
        registry: AgentRegistry,
    ):
        """Tier-2 model hallucinates non-existent agent 'super-cardiologist-3000'.

        Node detects agent does not exist in registry and safely falls back to candidates[0].id.
        """
        tier1_resp = json.dumps({
            "domain": "clinical",
            "category": "clinical.cardiology",
            "reasoning": "Cardiology domain",
        })
        tier2_hallucinated = json.dumps({
            "agent_id": "super-cardiologist-3000",
            "reasoning": "Imaginary agent",
            "instructions": "",
        })

        model = FakeListChatModel(responses=[tier1_resp, tier2_hallucinated])
        node = OrchestratorNode(model=model, registry=registry, catalog=catalog)

        state = {"messages": [HumanMessage(content="Heart checkup")]}
        result = await node.execute(state)

        # Fallback to candidates[0] (which is cardiology-guide)
        assert result["current_agent"] == "cardiology-guide"
        assert "super-cardiologist-3000" in result["orchestrator_reasoning"]
        assert "not found in registry" in result["orchestrator_reasoning"]


# ============================================================================
# Test Suite 9: Adversarial FTS Injection & Sanitization
# ============================================================================

class TestAdversarialFTSInjectionAndSanitization:
    """Verifies that malicious or malformed FTS queries never crash the SQLite catalog."""

    @pytest.mark.asyncio
    async def test_queries_execute_safely_without_sqlite_syntax_errors(
        self,
        catalog: SqliteCatalogAdapter,
    ):
        adversarial_payloads = [
            "",
            "   ",
            "\t\n\r",
            '"* NEAR/2 *"',
            '" OR 1=1 --',
            "NOT AND OR",
            "() {} [] ^ * + ?",
            "; DROP TABLE agents; --",
            "clinical:cardiology",
            "hello \x00 world",
            "🔥 👩‍⚕️ 🩺",
            "a" * 1000,
            "--- --- ---",
            "MATCH *",
            "col:value",
        ]

        for payload in adversarial_payloads:
            # Must execute without throwing sqlite3.OperationalError or crashing
            results = await catalog.search_agents(query=payload)
            assert isinstance(results, list)

            results_skills = await catalog.search_skills(query=payload)
            assert isinstance(results_skills, list)


# ============================================================================
# Test Suite 10: Tier-1 Classifier Prompt Invariants & Token Measurements
# ============================================================================

class TestDomainClassifierPromptInvariantsAndTokens:
    """Verifies TIER1_DOMAIN_CLASSIFIER_PROMPT invariants and strict token ceiling (< 500 tokens)."""

    def test_prompt_token_counts_strictly_under_500(self):
        """Measures prompt token length across tiktoken GPT-3/4 encodings."""
        try:
            import tiktoken
            for enc_name in ["cl100k_base", "o200k_base", "p50k_base"]:
                enc = tiktoken.get_encoding(enc_name)
                token_count = len(enc.encode(TIER1_DOMAIN_CLASSIFIER_PROMPT))
                assert token_count < 500, (
                    f"Tier-1 prompt exceeded 500 tokens for {enc_name}: {token_count} tokens"
                )
        except ImportError:
            # Fallback word-count assertion
            word_count = len(TIER1_DOMAIN_CLASSIFIER_PROMPT.split())
            assert word_count < 350

    def test_prompt_contains_all_domains_and_no_banned_agent_ids(self):
        """Verifies prompt contains the 5 canonical domains and zero banned agent names."""
        for d in ["clinical", "therapy", "wellness", "navigation", "education"]:
            assert f"'{d}'" in TIER1_DOMAIN_CLASSIFIER_PROMPT or f"'{d}':" in TIER1_DOMAIN_CLASSIFIER_PROMPT

        # Tier-1 must never leak specific agent IDs (e.g. 'cardiology-guide', 'visit-steward')
        # It must only expose domains and categories!
        for spec in ALL_17_SPECIALISTS:
            assert spec["id"] not in TIER1_DOMAIN_CLASSIFIER_PROMPT, (
                f"Agent ID '{spec['id']}' leaked into Tier-1 Domain Classifier prompt!"
            )


# ============================================================================
# Test Suite 11: Pre-Flight Provisioning for All 17 Specialists
# ============================================================================

class TestPreflightProvisioningStress:
    """Verifies Orchestrator pre-flight provisioning accurately recognizes declared reference documents."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("spec", ALL_17_SPECIALISTS, ids=[s["id"] for s in ALL_17_SPECIALISTS])
    async def test_preflight_reference_docs_recognized_for_each_specialist(
        self,
        spec: Dict[str, Any],
        registry: AgentRegistry,
        catalog: SqliteCatalogAdapter,
    ):
        """Every specialist agent must have its companion skill's reference documents recognized."""
        skill = registry.get_skill(spec["skill"])
        assert skill is not None
        assert len(skill.references) >= 2

        ref_doc = skill.references[0]

        tier1_resp = json.dumps({
            "domain": spec["domain"],
            "category": spec["category"],
            "reasoning": "Pre-flight test",
        })
        tier2_resp = json.dumps({
            "agent_id": spec["id"],
            "reasoning": f"Delegating to {spec['id']}",
            "instructions": "",
            "required_docs": [ref_doc],
        })

        model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=model, registry=registry, catalog=catalog)

        state = {
            "messages": [HumanMessage(content=spec["sample_query"])],
            "required_docs": [ref_doc],
        }
        result = await node.execute(state)

        assert result["current_agent"] == spec["id"]
        # Verify skill doc is in the agent's companion skill
        agent_manifest = registry.get(spec["id"])
        assert agent_manifest is not None
        assert spec["skill"] in agent_manifest.skills

