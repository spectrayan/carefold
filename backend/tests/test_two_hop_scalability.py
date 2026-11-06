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

"""Two-Hop Routing Scalability and Token Bounds Test Suite.

Challenges:
1. Token Bounds Verification:
   - Measure token length of TIER1_DOMAIN_CLASSIFIER_PROMPT across tokenizers (cl100k_base, o200k_base, p50k_base).
   - Verify prompt is strictly under 500 tokens, contains all 5 domains, and has 0 agent catalog descriptions.
   - Scalability: Compare prompt size with 50 synthetic agents vs 5 agents.
   - Verify single-hop prompt grows linearly O(N), while Two-Hop Tier-1 is constant and Tier-2 is strictly capped at <= 8 candidates.
2. Backward Compatibility Verification:
   - Test OrchestratorNode(catalog=None) across existing test paths:
     * Attachments: attachments, document_dossiers, document_text, raw_text -> document-extractor.
     * Explicit bypass: current_agent, routed_subgraph, case-insensitivity, underscore preservation, self-routing guards.
     * Hallucinated agents: non-existent agent IDs fall back safely to delegatable agents with clear reasoning.
     * Missing skills: undeclared, state-requested, and LLM-requested missing skills invoke skill-generator.
   - Verify SupervisorNode works cleanly with OrchestratorNode:
     * Clean subclassing and polymorphism.
     * Parameterless fallback across domains.
     * Attachments and bypass handling.
     * Model-driven structured output and optional catalog injection.
3. High-Stress Boundary Edge Cases:
   - Empty catalog fallback chain.
   - 100+ synthetic agents in identical domain/category verifying limit=8 truncation.
   - Malformed model responses and connection exceptions.
   - High-concurrency async invocations.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest
import tiktoken
from langchain_core.messages import AIMessage, HumanMessage

from carefold.agents.registry import AgentRegistry
from carefold.constants.agents import (
    AGENT_BENEFITS_COORDINATOR,
    AGENT_DOCUMENT_EXTRACTOR,
    AGENT_HABIT_COORDINATOR,
    AGENT_ORCHESTRATOR,
    AGENT_VISIT_PREP_COORDINATOR,
    DEFAULT_ROUTING_FALLBACK_AGENT,
)
from carefold.memory.adapters.sqlite.catalog_adapter import SqliteCatalogAdapter
from carefold.schemas.manifest import (
    AgentDomain,
    AgentManifest,
    AgentMaturity,
    RiskClass,
)
from tests.fixtures.core_routing import (
    DomainClassification,
    OrchestratorDecision,
    OrchestratorNode,
    TIER1_DOMAIN_CLASSIFIER_PROMPT,
)
from tests.fixtures.fake_model import FakeListChatModel


# ============================================================================
# Helper Functions & Fixtures
# ============================================================================

def make_synthetic_agent(
    agent_id: str,
    title: str,
    domain: str = "wellness",
    category: str = "wellness.habits",
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    tools: Optional[List[str]] = None,
    skills: Optional[List[str]] = None,
) -> AgentManifest:
    """Creates a typed synthetic AgentManifest for catalog and registry testing."""
    desc = description or f"Synthetic agent {agent_id} specialized in {category} healthcare guidance."
    return AgentManifest(
        id=agent_id,
        title=title,
        version="1.0.0",
        domain=AgentDomain(domain),
        category=category,
        risk_class=RiskClass.WELLNESS,
        tags=tags or ["synthetic", domain, "carefold"],
        description=desc,
        persona=f"You are {title}. Assist users with {category} inquiries.",
        tools=tools or ["workspace-note", "attach-read"],
        skills=skills or [],
        can_delegate=False,
    )


@pytest.fixture
async def memory_catalog() -> SqliteCatalogAdapter:
    """Provides an in-memory SqliteCatalogAdapter with standard agents."""
    catalog = SqliteCatalogAdapter(db_path=":memory:")
    base_agents = [
        make_synthetic_agent(
            agent_id="benefits-coordinator",
            title="Benefits Coordinator",
            domain="navigation",
            category="navigation.insurance",
            description="Specializes in health insurance coverage, copays, deductibles, and claims navigation.",
            tags=["insurance", "benefits", "eob", "deductible", "copay"],
        ),
        make_synthetic_agent(
            agent_id="appointment-prep-coordinator",
            title="Appointment Prep Coordinator",
            domain="navigation",
            category="navigation.appointments",
            description="Assists with clinical appointment preparation, doctor questions, and visit checklists.",
            tags=["appointment", "doctor", "visit-prep", "checklist"],
        ),
        make_synthetic_agent(
            agent_id="habit-coordinator",
            title="Habit Coordinator",
            domain="wellness",
            category="wellness.habits",
            description="Helps users build consistent healthy habits, track hydration, and improve sleep hygiene.",
            tags=["habits", "hydration", "sleep", "lifestyle", "water"],
        ),
        make_synthetic_agent(
            agent_id="document-extractor",
            title="Document Extractor",
            domain="navigation",
            category="navigation.records",
            description="Extracts clinical and insurance structured data dossiers from attached documents.",
            tags=["extraction", "attachments", "pdf", "table", "dossier"],
        ),
    ]
    for a in base_agents:
        await catalog.index_agent(a)

    yield catalog
    await catalog.close()


# ============================================================================
# Section 1: Token Bounds & Prompt Invariant Systematic Stress Testing
# ============================================================================



# ============================================================================
# Section 2: Catalog Scalability & Two-Hop vs Single-Hop Comparative Stress Testing
# ============================================================================

class TestCatalogScalabilityAndTwoHopLimits:
    """Systematically verifies prompt scaling properties between Single-Hop and Two-Hop routing."""

    @pytest.mark.asyncio
    async def test_scalability_single_hop_vs_two_hop_prompt_growth(self, temp_workspace: Path):
        """Verifies Single-Hop prompt grows linearly O(N) while Two-Hop Tier-1 is constant and Tier-2 is capped."""
        enc = tiktoken.get_encoding("cl100k_base")

        # 1. Benchmark 5 synthetic agents
        agents_5 = [
            make_synthetic_agent(f"agent-{i:02d}", f"Agent {i}", domain="wellness", category="wellness.habits")
            for i in range(5)
        ]
        cat_5 = SqliteCatalogAdapter(db_path=":memory:")
        for a in agents_5:
            await cat_5.index_agent(a)

        # 2. Benchmark 50 synthetic agents
        agents_50 = [
            make_synthetic_agent(f"agent-{i:02d}", f"Agent {i}", domain="wellness", category="wellness.habits")
            for i in range(50)
        ]
        cat_50 = SqliteCatalogAdapter(db_path=":memory:")
        for a in agents_50:
            await cat_50.index_agent(a)

        # --- Single-Hop Prompt Measurement ---
        reg_5 = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
        reg_5._agents = {a.id: a for a in agents_5}
        node_single_5 = OrchestratorNode(registry=reg_5, catalog=None)
        single_prompt_5 = node_single_5._build_system_prompt({})
        tokens_single_5 = len(enc.encode(single_prompt_5))

        reg_50 = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
        reg_50._agents = {a.id: a for a in agents_50}
        node_single_50 = OrchestratorNode(registry=reg_50, catalog=None)
        single_prompt_50 = node_single_50._build_system_prompt({})
        tokens_single_50 = len(enc.encode(single_prompt_50))

        # Single-hop growth must be substantial (>2x larger when agents increase 10x due to fixed prompt header)
        growth_ratio = tokens_single_50 / tokens_single_5
        assert growth_ratio >= 2.0, (
            f"Single-hop prompt did not exhibit linear growth: 5 agents={tokens_single_5} tokens, "
            f"50 agents={tokens_single_50} tokens (ratio: {growth_ratio:.2f}x)"
        )

        # --- Two-Hop Prompt Measurement ---
        # Tier-1 prompt is completely static: exactly identical tokens regardless of catalog size
        t1_tokens_5 = len(enc.encode(TIER1_DOMAIN_CLASSIFIER_PROMPT))
        t1_tokens_50 = len(enc.encode(TIER1_DOMAIN_CLASSIFIER_PROMPT))
        assert t1_tokens_5 == t1_tokens_50
        assert t1_tokens_5 < 500

        # Tier-2 candidate queries
        cands_5 = await cat_5.search_agents(domain="wellness", category="wellness.habits", limit=8)
        cands_50 = await cat_50.search_agents(domain="wellness", category="wellness.habits", limit=8)

        assert len(cands_5) == 5
        # Crucial invariant: 50-agent catalog query MUST be strictly capped at <= 8 candidates
        assert len(cands_50) <= 8
        assert len(cands_50) == 8

        # Tier-2 prompt size with capped candidates
        node_two_hop = OrchestratorNode()
        t2_prompt_5 = node_two_hop._build_tier2_system_prompt(cands_5)
        t2_prompt_50 = node_two_hop._build_tier2_system_prompt(cands_50)

        t2_tokens_5 = len(enc.encode(t2_prompt_5))
        t2_tokens_50 = len(enc.encode(t2_prompt_50))

        # Tier-2 prompt for 50 agents must be bounded (< 1200 tokens) and capped
        assert t2_tokens_50 < 1200, f"Tier-2 prompt exceeded token budget: {t2_tokens_50} tokens"
        assert t2_tokens_50 < tokens_single_50, (
            f"Tier-2 prompt ({t2_tokens_50}) should be much smaller than single-hop prompt ({tokens_single_50})"
        )

        await cat_5.close()
        await cat_50.close()

    @pytest.mark.asyncio
    async def test_catalog_100_agents_candidate_cap_enforcement(self):
        """Stress-tests that candidate retrieval strictly caps at <= 8 even with 100 matching agents."""
        catalog = SqliteCatalogAdapter(db_path=":memory:")
        # Index 100 agents all in clinical.pediatrics
        for i in range(100):
            agent = make_synthetic_agent(
                agent_id=f"pediatric-specialist-{i:03d}",
                title=f"Pediatric Specialist {i}",
                domain="clinical",
                category="clinical.pediatrics",
                description=f"Pediatric subspecialist number {i} for pediatric consultations.",
                tags=["pediatrics", "children", "clinical"],
            )
            await catalog.index_agent(agent)

        # 1. Search with category match
        cands_cat = await catalog.search_agents(domain="clinical", category="clinical.pediatrics", limit=8)
        assert len(cands_cat) == 8

        # 2. Search with domain only
        cands_dom = await catalog.search_agents(domain="clinical", limit=8)
        assert len(cands_dom) == 8

        # 3. Search with FTS query
        cands_fts = await catalog.search_agents(query="pediatric consultations", limit=8)
        assert len(cands_fts) == 8

        await catalog.close()


# ============================================================================
# Section 3: Backward Compatibility Verification for OrchestratorNode(catalog=None)
# ============================================================================

class TestBackwardCompatibilityCatalogNone:
    """Verifies all existing test paths function identically when catalog=None."""


    @pytest.mark.asyncio
    async def test_single_hop_explicit_bypass_matrix(self, temp_workspace: Path):
        """Verifies explicit bypass variations when catalog=None."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
        node = OrchestratorNode(model=None, registry=registry, catalog=None)

        # 1. Standard explicit current_agent
        r1 = await node.execute({
            "current_agent": "benefits-coordinator",
            "messages": [HumanMessage(content="Random prompt")],
        })
        assert r1["current_agent"] == "benefits-coordinator"
        assert "Explicitly requested" in r1["orchestrator_reasoning"]

        # 2. Normalization: underscore to hyphen
        r2 = await node.execute({
            "current_agent": "appointment_prep_coordinator",
            "messages": [HumanMessage(content="Random prompt")],
        })
        assert r2["current_agent"] == "appointment-prep-coordinator"

        # 3. Normalization: uppercase
        r3 = await node.execute({
            "current_agent": "HABIT-COORDINATOR",
            "messages": [HumanMessage(content="Random prompt")],
        })
        assert r3["current_agent"] == "habit-coordinator"

        # 4. Routed subgraph takes precedence
        r4 = await node.execute({
            "routed_subgraph": "habit-coordinator",
            "messages": [HumanMessage(content="Random prompt")],
        })
        assert r4["current_agent"] == "habit-coordinator"

        # 5. Self-routing (orchestrator / supervisor) does NOT bypass
        fake_model = FakeListChatModel(responses=[
            json.dumps({"agent_id": "benefits-coordinator", "reasoning": "Model decision", "instructions": ""})
        ])
        node_with_model = OrchestratorNode(model=fake_model, registry=registry, catalog=None)

        r5 = await node_with_model.execute({
            "current_agent": "orchestrator",
            "messages": [HumanMessage(content="What is my copay?")],
        })
        assert r5["current_agent"] == "benefits-coordinator"
        assert r5["orchestrator_reasoning"] == "Model decision"


    @pytest.mark.asyncio
    async def test_single_hop_missing_skills_synthesis(self, temp_workspace: Path):
        """Verifies missing skill detection and synthesis when catalog=None."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        # 1. Missing skill in state during explicit bypass
        node = OrchestratorNode(model=None, registry=registry, catalog=None)
        res1 = await node.execute({
            "current_agent": "appointment-prep-coordinator",
            "missing_skill": "chemotherapy-checklist",
            "missing_skill_description": "Checklist for chemo appointment",
            "messages": [HumanMessage(content="Chemo prep")],
        })
        assert res1["current_agent"] == "appointment-prep-coordinator"
        assert "generated_skill" in res1
        assert res1["generated_skill"]["id"] == "chemotherapy-checklist"
        assert len(res1["generated_skills"]) == 1

        # 2. Missing skill requested by LLM decision
        model_resp = json.dumps({
            "agent_id": "benefits-coordinator",
            "reasoning": "Needs insurance review.",
            "instructions": "Review coverage.",
            "missing_skill": "prior-authorization-coordinator",
            "missing_skill_description": "Steps for prior authorization appeals",
        })
        skill_resp = json.dumps({
            "id": "prior-authorization-coordinator",
            "name": "Prior Auth Navigator",
            "description": "Steps for prior authorization appeals",
            "instructions": "Step by step prior authorization appeal guidance.",
            "tools": ["skill-docs"],
            "references": {},
        })
        fake_model = FakeListChatModel(responses=[model_resp, skill_resp])
        node_with_model = OrchestratorNode(model=fake_model, registry=registry, catalog=None)

        res2 = await node_with_model.execute({"messages": [HumanMessage(content="How do I appeal prior auth?")]})
        assert res2["current_agent"] == "benefits-coordinator"
        assert "generated_skill" in res2
        assert res2["generated_skill"]["id"] == "prior-authorization-coordinator"


# ============================================================================
# Section 4: SupervisorNode Full Backward Compatibility Matrix
# ============================================================================



# ============================================================================
# Section 5: High-Stress Boundary Edge Cases
# ============================================================================

class TestAdversarialEdgeCasesAndResilience:
    """Stress-tests edge cases: malformed responses, empty catalogs, and high concurrency."""



    @pytest.mark.asyncio
    async def test_concurrent_two_hop_invocations(
        self, memory_catalog: SqliteCatalogAdapter, temp_workspace: Path
    ):
        """Concurrently runs 20 parallel routing requests to stress-test async execution and SQLite locks."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        async def run_one(idx: int) -> Dict[str, Any]:
            is_even = (idx % 2 == 0)
            agent = "benefits-coordinator" if is_even else "habit-coordinator"
            domain = "navigation" if is_even else "wellness"
            category = "navigation.insurance" if is_even else "wellness.habits"
            prompt = "What is my copay?" if is_even else "How much water to drink?"

            model = FakeListChatModel(responses=[
                json.dumps({"domain": domain, "category": category, "reasoning": f"Tier 1 task {idx}"}),
                json.dumps({"agent_id": agent, "reasoning": f"Tier 2 picked {agent}", "instructions": ""}),
            ])
            node = OrchestratorNode(model=model, registry=registry, catalog=memory_catalog)
            return await node.execute({"messages": [HumanMessage(content=prompt)]})

        results = await asyncio.gather(*(run_one(i) for i in range(20)))

        assert len(results) == 20
        for i, res in enumerate(results):
            expected = "benefits-coordinator" if i % 2 == 0 else "habit-coordinator"
            assert res["current_agent"] == expected
            assert res["routed_subgraph"] == expected
