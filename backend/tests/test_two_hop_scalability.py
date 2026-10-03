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

"""Two-Hop Routing Scalability and Token Bounds Test Suite.

Challenges:
1. Token Bounds Verification:
   - Measure token length of TIER1_DOMAIN_CLASSIFIER_PROMPT across tokenizers (cl100k_base, o200k_base, p50k_base).
   - Verify prompt is strictly under 500 tokens, contains all 5 domains, and has 0 agent catalog descriptions.
   - Scalability: Compare prompt size with 50 synthetic agents vs 5 agents.
   - Verify single-hop prompt grows linearly O(N), while Two-Hop Tier-1 is constant and Tier-2 is strictly capped at <= 8 candidates.
2. Backward Compatibility Challenge:
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
3. High-Stress Adversarial Edge Cases:
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
    AGENT_BENEFITS_GUIDE,
    AGENT_DOCUMENT_EXTRACTOR,
    AGENT_HABIT_COMPANION,
    AGENT_ORCHESTRATOR,
    AGENT_VISIT_STEWARD,
    DEFAULT_ROUTING_FALLBACK_AGENT,
)
from carefold.memory.adapters.sqlite.catalog_adapter import SqliteCatalogAdapter
from carefold.schemas.manifest import (
    AgentDomain,
    AgentManifest,
    AgentMaturity,
    RiskClass,
)
from carefold.workflows.nodes.orchestrator_node import (
    DomainClassification,
    OrchestratorDecision,
    OrchestratorNode,
    TIER1_DOMAIN_CLASSIFIER_PROMPT,
)
from carefold.workflows.nodes.supervisor_node import SupervisorNode
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
            agent_id="benefits-guide",
            title="Benefits Guide",
            domain="navigation",
            category="navigation.insurance",
            description="Specializes in health insurance coverage, copays, deductibles, and claims navigation.",
            tags=["insurance", "benefits", "eob", "deductible", "copay"],
        ),
        make_synthetic_agent(
            agent_id="visit-steward",
            title="Visit Steward",
            domain="navigation",
            category="navigation.appointments",
            description="Assists with clinical appointment preparation, doctor questions, and visit checklists.",
            tags=["appointment", "doctor", "visit-prep", "checklist"],
        ),
        make_synthetic_agent(
            agent_id="habit-companion",
            title="Habit Companion",
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
# Section 1: Token Bounds & Prompt Invariant Empirical Stress Testing
# ============================================================================

class TestTokenBoundsAndPromptInvariants:
    """Empirically measures token bounds and structural invariants of Tier-1 prompt."""

    def test_tier1_prompt_token_bounds_across_tokenizers(self):
        """Verifies TIER1_DOMAIN_CLASSIFIER_PROMPT is strictly under 500 tokens across encodings."""
        tokenizers = ["cl100k_base", "o200k_base", "p50k_base"]
        for enc_name in tokenizers:
            enc = tiktoken.get_encoding(enc_name)
            token_count = len(enc.encode(TIER1_DOMAIN_CLASSIFIER_PROMPT))
            assert token_count < 500, (
                f"Tokenizer {enc_name} measured {token_count} tokens, which violates the strict < 500 token limit!"
            )
            # Must also have meaningful substance (>200 tokens)
            assert token_count > 200, f"Prompt unexpectedly short: {token_count} tokens"

        # Word count bound
        words = TIER1_DOMAIN_CLASSIFIER_PROMPT.split()
        assert len(words) < 350
        assert len(words) > 150

    def test_tier1_prompt_domain_coverage_and_isolation(self):
        """Verifies all 5 canonical domains are described, with zero concrete agent descriptions."""
        prompt = TIER1_DOMAIN_CLASSIFIER_PROMPT

        # 5 required domains
        for domain in ["clinical", "therapy", "wellness", "navigation", "education"]:
            assert f"'{domain}'" in prompt or f"## {domain}" in prompt or domain in prompt

        # Category examples
        assert "clinical.triage" in prompt
        assert "therapy.cbt" in prompt
        assert "wellness.habits" in prompt
        assert "navigation.insurance" in prompt
        assert "education.conditions" in prompt

        # Strict isolation: Zero agent IDs or agent catalog listings
        forbidden_agent_names = [
            "benefits-guide",
            "visit-steward",
            "habit-companion",
            "document-extractor",
            "orchestrator",
            "Available Specialist Agents",
        ]
        for forbidden in forbidden_agent_names:
            assert forbidden not in prompt, f"TIER1 prompt leaked agent catalog entity: {forbidden}"


# ============================================================================
# Section 2: Catalog Scalability & Two-Hop vs Single-Hop Comparative Stress Testing
# ============================================================================

class TestCatalogScalabilityAndTwoHopLimits:
    """Empirically verifies prompt scaling properties between Single-Hop and Two-Hop routing."""

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
# Section 3: Backward Compatibility Challenge for OrchestratorNode(catalog=None)
# ============================================================================

class TestBackwardCompatibilityCatalogNone:
    """Verifies all existing test paths function identically when catalog=None."""

    @pytest.mark.asyncio
    async def test_single_hop_attachment_routing_paths(self, temp_workspace: Path):
        """Verifies that attachments in state route to document-extractor when catalog=None."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
        node = OrchestratorNode(model=None, registry=registry, catalog=None)

        attachment_states = [
            {"attachments": ["record.pdf"], "messages": [HumanMessage(content="Review this")]},
            {"document_dossiers": [{"type": "benefits"}], "messages": [HumanMessage(content="Review")]},
            {"document_text": "Clinical visit summary notes", "messages": [HumanMessage(content="Review")]},
            {"raw_text": "Insurance explanation of benefits text", "messages": [HumanMessage(content="Review")]},
        ]

        for st in attachment_states:
            res = await node.execute(st)
            assert res["current_agent"] == "document-extractor"
            assert res["routed_subgraph"] == "document-extractor"
            assert res["next_step"] == "document-extractor"

    @pytest.mark.asyncio
    async def test_single_hop_explicit_bypass_matrix(self, temp_workspace: Path):
        """Verifies explicit bypass variations when catalog=None."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
        node = OrchestratorNode(model=None, registry=registry, catalog=None)

        # 1. Standard explicit current_agent
        r1 = await node.execute({
            "current_agent": "benefits-guide",
            "messages": [HumanMessage(content="Random prompt")],
        })
        assert r1["current_agent"] == "benefits-guide"
        assert "Explicitly requested" in r1["orchestrator_reasoning"]

        # 2. Normalization: underscore to hyphen
        r2 = await node.execute({
            "current_agent": "visit_steward",
            "messages": [HumanMessage(content="Random prompt")],
        })
        assert r2["current_agent"] == "visit-steward"

        # 3. Normalization: uppercase
        r3 = await node.execute({
            "current_agent": "HABIT-COMPANION",
            "messages": [HumanMessage(content="Random prompt")],
        })
        assert r3["current_agent"] == "habit-companion"

        # 4. Routed subgraph takes precedence
        r4 = await node.execute({
            "routed_subgraph": "habit-companion",
            "messages": [HumanMessage(content="Random prompt")],
        })
        assert r4["current_agent"] == "habit-companion"

        # 5. Self-routing (orchestrator / supervisor) does NOT bypass
        fake_model = FakeListChatModel(responses=[
            json.dumps({"agent_id": "benefits-guide", "reasoning": "Model decision", "instructions": ""})
        ])
        node_with_model = OrchestratorNode(model=fake_model, registry=registry, catalog=None)

        r5 = await node_with_model.execute({
            "current_agent": "orchestrator",
            "messages": [HumanMessage(content="What is my copay?")],
        })
        assert r5["current_agent"] == "benefits-guide"
        assert r5["orchestrator_reasoning"] == "Model decision"

    @pytest.mark.asyncio
    async def test_single_hop_hallucinated_agents_safe_fallback(self, temp_workspace: Path):
        """Verifies unknown/hallucinated agent IDs fall back to a registered delegatable agent."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
        delegatable = registry.get_delegatable_agents(exclude=AGENT_ORCHESTRATOR)
        expected_fallback = delegatable[0].id

        hallucinated_ids = [
            "non-existent-specialist-999",
            "fake_agent_xyz",
            "chatgpt_super_doc",
            "",
        ]

        for bad_id in hallucinated_ids:
            fake_model = FakeListChatModel(responses=[
                json.dumps({"agent_id": bad_id, "reasoning": "Hallucinated", "instructions": ""})
            ])
            node = OrchestratorNode(model=fake_model, registry=registry, catalog=None)
            res = await node.execute({"messages": [HumanMessage(content="Help me with care")]})

            assert res["current_agent"] == expected_fallback
            assert res["routed_subgraph"] == expected_fallback
            assert "not found in registry" in res["orchestrator_reasoning"]

    @pytest.mark.asyncio
    async def test_single_hop_missing_skills_synthesis(self, temp_workspace: Path):
        """Verifies missing skill detection and synthesis when catalog=None."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        # 1. Missing skill in state during explicit bypass
        node = OrchestratorNode(model=None, registry=registry, catalog=None)
        res1 = await node.execute({
            "current_agent": "visit-steward",
            "missing_skill": "chemotherapy-checklist",
            "missing_skill_description": "Checklist for chemo appointment",
            "messages": [HumanMessage(content="Chemo prep")],
        })
        assert res1["current_agent"] == "visit-steward"
        assert "generated_skill" in res1
        assert res1["generated_skill"]["id"] == "chemotherapy-checklist"
        assert len(res1["generated_skills"]) == 1

        # 2. Missing skill requested by LLM decision
        model_resp = json.dumps({
            "agent_id": "benefits-guide",
            "reasoning": "Needs insurance review.",
            "instructions": "Review coverage.",
            "missing_skill": "prior-auth-navigator",
            "missing_skill_description": "Steps for prior authorization appeals",
        })
        skill_resp = json.dumps({
            "id": "prior-auth-navigator",
            "name": "Prior Auth Navigator",
            "description": "Steps for prior authorization appeals",
            "instructions": "Step by step prior authorization appeal guidance.",
            "tools": ["skill-docs"],
            "references": {},
        })
        fake_model = FakeListChatModel(responses=[model_resp, skill_resp])
        node_with_model = OrchestratorNode(model=fake_model, registry=registry, catalog=None)

        res2 = await node_with_model.execute({"messages": [HumanMessage(content="How do I appeal prior auth?")]})
        assert res2["current_agent"] == "benefits-guide"
        assert "generated_skill" in res2
        assert res2["generated_skill"]["id"] == "prior-auth-navigator"


# ============================================================================
# Section 4: SupervisorNode Full Backward Compatibility Matrix
# ============================================================================

class TestSupervisorNodeBackwardCompatibility:
    """Verifies SupervisorNode operates cleanly as an OrchestratorNode subclass."""

    def test_supervisor_node_clean_inheritance_and_contracts(self):
        """Verifies class hierarchy, default attributes, and polymorphism."""
        assert issubclass(SupervisorNode, OrchestratorNode)

        sup = SupervisorNode()
        assert isinstance(sup, OrchestratorNode)
        assert sup.name == "supervisor"
        assert sup.catalog is None
        assert sup.model is None

    @pytest.mark.asyncio
    async def test_supervisor_node_parameterless_routing_matrix(self):
        """Verifies parameterless SupervisorNode deterministic regex fallback across domains."""
        sup = SupervisorNode()

        test_matrix = [
            ("What is my insurance copay?", "benefits-guide"),
            ("Explain my deductible and out of pocket max", "benefits-guide"),
            ("How much water should I drink for hydration?", "habit-companion"),
            ("Track my sleep habits and bedtime routine", "habit-companion"),
            ("Questions to ask my doctor during appointment", "visit-steward"),
            ("Upcoming clinical clinic visit prep", "visit-steward"),
            ("Completely novel query with no keywords", DEFAULT_ROUTING_FALLBACK_AGENT),
        ]

        for query, expected in test_matrix:
            res = await sup.execute({"messages": [HumanMessage(content=query)]})
            assert res["current_agent"] == expected
            assert res["routed_subgraph"] == expected
            assert res["next_step"] == expected

    @pytest.mark.asyncio
    async def test_supervisor_node_attachments_and_bypass(self):
        """Verifies attachments and explicit bypass work cleanly on SupervisorNode."""
        sup = SupervisorNode()

        # Attachments
        res_att = await sup.execute({
            "attachments": ["eob_report.pdf"],
            "messages": [HumanMessage(content="Here is my document")],
        })
        assert res_att["current_agent"] == "document-extractor"
        assert res_att["routed_subgraph"] == "document-extractor"

        # Explicit bypass
        res_byp = await sup.execute({
            "current_agent": "habit-companion",
            "messages": [HumanMessage(content="Hello")],
        })
        assert res_byp["current_agent"] == "habit-companion"
        assert res_byp["routed_subgraph"] == "habit-companion"

    @pytest.mark.asyncio
    async def test_supervisor_node_with_model_structured_output(self, temp_workspace: Path):
        """Verifies SupervisorNode initialized with a chat model executes dynamic routing."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
        model_resp = json.dumps({
            "agent_id": "benefits-guide",
            "reasoning": "Insurance benefits question.",
            "instructions": "Clarify copay.",
        })
        fake_model = FakeListChatModel(responses=[model_resp])
        sup = SupervisorNode(model=fake_model, registry=registry)

        res = await sup.execute({"messages": [HumanMessage(content="What is my copay?")]})
        assert res["current_agent"] == "benefits-guide"
        assert res["routed_subgraph"] == "benefits-guide"
        assert res["orchestrator_instructions"] == "Clarify copay."

    @pytest.mark.asyncio
    async def test_supervisor_node_with_injected_catalog_two_hop(
        self, memory_catalog: SqliteCatalogAdapter, temp_workspace: Path
    ):
        """Verifies SupervisorNode executes two-hop routing seamlessly if catalog is set."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        tier1_resp = json.dumps({
            "domain": "wellness",
            "category": "wellness.habits",
            "reasoning": "Habit and hydration query.",
        })
        tier2_resp = json.dumps({
            "agent_id": "habit-companion",
            "reasoning": "Selected habit-companion from candidate set.",
            "instructions": "Set a goal of 64 ounces of water daily.",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        sup = SupervisorNode(model=fake_model, registry=registry)
        # Inject catalog onto supervisor
        sup.catalog = memory_catalog

        res = await sup.execute({"messages": [HumanMessage(content="Water intake routine")]})
        assert res["current_agent"] == "habit-companion"
        assert res["routed_subgraph"] == "habit-companion"
        assert res["orchestrator_instructions"] == "Set a goal of 64 ounces of water daily."


# ============================================================================
# Section 5: High-Stress Adversarial Edge Cases
# ============================================================================

class TestAdversarialEdgeCasesAndResilience:
    """Stress-tests edge cases: malformed responses, empty catalogs, and high concurrency."""

    @pytest.mark.asyncio
    async def test_adversarial_malformed_model_responses(
        self, memory_catalog: SqliteCatalogAdapter, temp_workspace: Path
    ):
        """Tests resilience when model returns various corrupted or malformed outputs."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        malformed_inputs = [
            # Markdown block with invalid JSON
            "```json\n{ not valid json ...\n```",
            # Plain non-JSON string
            "I recommend delegating to benefits-guide because of coverage rules.",
            # Valid JSON but wrong types
            json.dumps({"agent_id": 12345, "reasoning": None, "instructions": []}),
            # Empty string
            "",
        ]

        for bad_resp in malformed_inputs:
            fake_model = FakeListChatModel(responses=[bad_resp, bad_resp])
            node = OrchestratorNode(model=fake_model, registry=registry, catalog=memory_catalog)

            # Query has 'copay' which matches regex pattern fallback
            res = await node.execute({"messages": [HumanMessage(content="What is my in-network copay?")]})

            assert res["current_agent"] in registry.list_agent_ids()
            assert res["current_agent"] == "benefits-guide"

    @pytest.mark.asyncio
    async def test_adversarial_empty_catalog_fallback(self, temp_workspace: Path):
        """Verifies graceful degradation when catalog exists but is completely empty."""
        empty_catalog = SqliteCatalogAdapter(db_path=":memory:")
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        tier1_resp = json.dumps({
            "domain": "navigation",
            "category": "navigation.insurance",
            "reasoning": "Insurance navigation query.",
        })
        fake_model = FakeListChatModel(responses=[tier1_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=empty_catalog)

        # Prompt has benefits keyword 'copay'
        res = await node.execute({"messages": [HumanMessage(content="Explain my insurance copay")]})

        # All 3 catalog queries return 0 candidates -> step 4 triggers pattern fallback to benefits-guide
        assert res["current_agent"] == "benefits-guide"
        assert "pattern fallback" in res["orchestrator_reasoning"].lower()

        await empty_catalog.close()

    @pytest.mark.asyncio
    async def test_adversarial_concurrent_two_hop_invocations(
        self, memory_catalog: SqliteCatalogAdapter, temp_workspace: Path
    ):
        """Concurrently runs 20 parallel routing requests to stress-test async execution and SQLite locks."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        async def run_one(idx: int) -> Dict[str, Any]:
            is_even = (idx % 2 == 0)
            agent = "benefits-guide" if is_even else "habit-companion"
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
            expected = "benefits-guide" if i % 2 == 0 else "habit-companion"
            assert res["current_agent"] == expected
            assert res["routed_subgraph"] == expected
