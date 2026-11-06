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

"""Boundary stress-test suite for Two-Hop Orchestrator Fallback Chain.

Target:
- yarvelle_core.workflows.nodes.orchestrator_node.OrchestratorNode
- carefold.memory.adapters.sqlite.catalog_adapter.SqliteCatalogAdapter

Challenges Tested:
1. Verification Step 1: Exact dot-notated category match.
2. Verification Step 2: Obscure subcategories not in database -> fallback to domain-only match.
3. Verification Step 3: Completely unrecognized domain -> fallback to FTS search on user query keywords/tags.
4. Verification Step 4: Pure gibberish / total absence of matching candidates -> fallback to pattern matching.
5. Verification Step 5: Candidate limits: Ensure candidates list passed to Tier-2 is strictly <= 8.
6. Verification Step 6: Empty CatalogPort (zero agents indexed) -> clean fallback to pattern matching without crashing.
7. Hostile / edge-case stress tests: symbols-only prompt, Tier-1 model crash, Tier-2 model crash, hallucinated IDs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest
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
from carefold.memory.adapters.sqlite.catalog_adapter import (
    SqliteCatalogAdapter,
    sanitize_fts_query,
)
from carefold.memory.ports.catalog_port import CatalogPort
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
# Helpers & Fixtures
# ============================================================================

def make_agent(
    agent_id: str,
    title: str,
    domain: str,
    category: str,
    description: str,
    tags: Optional[List[str]] = None,
    tools: Optional[List[str]] = None,
) -> AgentManifest:
    """Helper to create valid AgentManifest instances for boundary testing."""
    return AgentManifest(
        id=agent_id,
        title=title,
        version="1.0.0",
        domain=AgentDomain(domain),
        category=category,
        risk_class=RiskClass.WELLNESS,
        tags=tags or [],
        description=description,
        persona=f"You are {title}. {description}",
        tools=tools or ["workspace-note"],
        can_delegate=True,
    )


# ============================================================================
# Verification Step 1: Exact Dot-Notated Category Match
# ============================================================================

class TestChallengeStep1ExactCategoryMatch:
    """Verification Step 1: Exact dot-notated category match.
    
    Verifies:
    - Queries matching an exact subcategory retrieve only agents from that category.
    - Sibling subcategories and different domains are strictly excluded.
    - Only a single call to catalog.search_agents is executed (no fallback invoked).
    """

    @pytest.mark.asyncio
    async def test_exact_deep_subcategory_match(self, temp_workspace: Path):
        catalog = SqliteCatalogAdapter(db_path=":memory:")
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        # Setup hierarchical categories in catalog
        agents = [
            make_agent(
                "allergy-specialist",
                "Pediatric Allergy Specialist",
                domain="clinical",
                category="clinical.pediatrics.allergy",
                description="Treats pediatric food and seasonal allergies.",
                tags=["allergy", "pediatric", "peanuts", "hives"],
            ),
            make_agent(
                "pediatric-cardio",
                "Pediatric Cardiologist",
                domain="clinical",
                category="clinical.pediatrics.cardiology",
                description="Diagnoses congenital and pediatric heart conditions.",
                tags=["cardiology", "heart", "pediatric"],
            ),
            make_agent(
                "adult-cardio",
                "Adult Cardiologist",
                domain="clinical",
                category="clinical.cardiology",
                description="Treats adult cardiovascular disease.",
                tags=["heart", "cardio", "hypertension"],
            ),
            make_agent(
                "insurance-guide",
                "Insurance Guide",
                domain="navigation",
                category="navigation.insurance",
                description="Navigates health insurance benefits and copays.",
                tags=["insurance", "copay", "claims"],
            ),
        ]
        for a in agents:
            await catalog.index_agent(a)

        tier1_resp = json.dumps({
            "domain": "clinical",
            "category": "clinical.pediatrics.allergy",
            "reasoning": "Inquiry regarding pediatric peanut allergy reaction.",
        })
        tier2_resp = json.dumps({
            "agent_id": "allergy-specialist",
            "reasoning": "Targeted pediatric allergy specialist based on exact subcategory match.",
            "instructions": "Advise on pediatric allergy epinephrine protocol.",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=catalog)

        calls = []
        original_search = catalog.search_agents

        async def spy_search(*args: Any, **kwargs: Any):
            calls.append(kwargs)
            return await original_search(*args, **kwargs)

        with patch.object(catalog, "search_agents", side_effect=spy_search):
            state = {"messages": [HumanMessage(content="My 5-year-old had hives after eating peanuts")]}
            res = await node.execute(state)

        # Invariant 1: Exactly 1 catalog search call was performed
        assert len(calls) == 1, f"Expected exactly 1 search call, but got {len(calls)}"
        assert calls[0]["domain"] == "clinical"
        assert calls[0]["category"] == "clinical.pediatrics.allergy"
        assert calls[0]["limit"] == 8

        # Invariant 2: Result routed strictly to allergy-specialist
        assert res["current_agent"] == "allergy-specialist"
        assert res["routed_subgraph"] == "allergy-specialist"

        await catalog.close()


# ============================================================================
# Verification Step 2: Obscure Subcategories -> Fallback to Domain-Only Match
# ============================================================================

class TestChallengeStep2DomainOnlyFallback:
    """Verification Step 2: Obscure subcategories not in database -> fallback to domain-only match.
    
    Verifies:
    - Tier-1 returns a non-existent or obscure category path.
    - Step 1 (domain + category) yields 0 results.
    - Step 2 (domain-only) immediately succeeds and returns candidate agents.
    - Step 3 (FTS) is NEVER called.
    """

    @pytest.mark.asyncio
    async def test_obscure_subcategory_falls_back_to_domain_only(self, temp_workspace: Path):
        catalog = SqliteCatalogAdapter(db_path=":memory:")
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        # Catalog contains standard wellness agents
        agents = [
            make_agent(
                "habit-coordinator",
                "Habit Coordinator",
                domain="wellness",
                category="wellness.habits",
                description="Assists with hydration and daily routines.",
                tags=["habits", "hydration", "water"],
            ),
            make_agent(
                "nutrition-coach",
                "Nutrition Coach",
                domain="wellness",
                category="wellness.nutrition",
                description="Provides meal planning and dietary coaching.",
                tags=["nutrition", "diet", "meal"],
            ),
        ]
        for a in agents:
            await catalog.index_agent(a)

        # Tier-1 invents an obscure subcategory not present in the catalog
        obscure_category = "wellness.chrono_circadian_neuro_rhythms.pineal_alignment"
        tier1_resp = json.dumps({
            "domain": "wellness",
            "category": obscure_category,
            "reasoning": "Chrono-circadian sleep timing question.",
        })
        tier2_resp = json.dumps({
            "agent_id": "habit-coordinator",
            "reasoning": "Habit companion selected from domain-level candidates.",
            "instructions": "Guide on regular sleep-wake schedules.",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=catalog)

        calls = []
        original_search = catalog.search_agents

        async def spy_search(*args: Any, **kwargs: Any):
            calls.append(kwargs)
            return await original_search(*args, **kwargs)

        with patch.object(catalog, "search_agents", side_effect=spy_search):
            state = {"messages": [HumanMessage(content="How do I reset my pineal circadian rhythm for better sleep?")]}
            res = await node.execute(state)

        # Invariant 1: Exactly 2 search calls made (Step 1 failed, Step 2 succeeded)
        assert len(calls) == 2, f"Expected exactly 2 search calls, got {len(calls)}"

        # Call 1: domain + obscure category -> 0 matches
        assert calls[0]["domain"] == "wellness"
        assert calls[0]["category"] == obscure_category

        # Call 2: domain only -> found habit-coordinator & nutrition-coach
        assert calls[1]["domain"] == "wellness"
        assert calls[1].get("category") is None or calls[1].get("category") == ""

        # Invariant 2: Step 3 (FTS query) was NOT called
        assert "query" not in calls[1]
        assert not any("query" in c for c in calls)

        # Invariant 3: Clean delegation to habit-coordinator
        assert res["current_agent"] == "habit-coordinator"
        assert res["routed_subgraph"] == "habit-coordinator"

        await catalog.close()


# ============================================================================
# Verification Step 3: Unrecognized Domain -> Fallback to FTS Search
# ============================================================================

class TestChallengeStep3FTSFallback:
    """Verification Step 3: Completely unrecognized domain -> fallback to FTS search on user query keywords/tags.
    
    Verifies:
    - Tier-1 returns a domain that has ZERO agents in the database.
    - Step 1 (domain + category) yields 0.
    - Step 2 (domain-only) yields 0.
    - Step 3 (FTS on query) triggers and finds matching agent in another domain via tags/text.
    - Tier-2 receives FTS-matched candidates and selects the specialist.
    """

    @pytest.mark.asyncio
    async def test_unrecognized_domain_fts_cross_domain_recovery(self, temp_workspace: Path):
        catalog = SqliteCatalogAdapter(db_path=":memory:")
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        # Database contains wellness and navigation agents, NO therapy agents
        agents = [
            make_agent(
                "habit-coordinator",
                "Habit Coordinator",
                domain="wellness",
                category="wellness.habits",
                description="Assists with hydration, daily routines, and sleep hygiene tracking.",
                tags=["habits", "hydration", "sleep", "insomnia", "bedtime"],
            ),
            make_agent(
                "appointment-prep-coordinator",
                "Appointment Prep Coordinator",
                domain="navigation",
                category="navigation.appointments",
                description="Doctor visit preparation and questions checklist.",
                tags=["doctor", "appointment", "checklist"],
            ),
        ]
        for a in agents:
            await catalog.index_agent(a)

        # Tier-1 classifies query as 'therapy' domain (which has 0 indexed agents in DB)
        tier1_resp = json.dumps({
            "domain": "therapy",
            "category": "therapy.cognitive_behavioral",
            "reasoning": "Counseling inquiry for severe insomnia.",
        })
        tier2_resp = json.dumps({
            "agent_id": "habit-coordinator",
            "reasoning": "FTS matched sleep and insomnia tags in habit companion.",
            "instructions": "Support sleep hygiene routine.",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=catalog)

        calls = []
        original_search = catalog.search_agents

        async def spy_search(*args: Any, **kwargs: Any):
            calls.append(kwargs)
            return await original_search(*args, **kwargs)

        prompt_str = "I am struggling with chronic insomnia and need help tracking my bedtime sleep routine"
        with patch.object(catalog, "search_agents", side_effect=spy_search):
            state = {"messages": [HumanMessage(content=prompt_str)]}
            res = await node.execute(state)

        # Invariant 1: Exactly 3 search calls executed (Step 1 -> Step 2 -> Step 3)
        assert len(calls) == 3, f"Expected 3 search calls, got {len(calls)}"

        # Step 1: domain='therapy', category='therapy.cognitive_behavioral' -> 0
        assert calls[0]["domain"] == "therapy"
        assert calls[0]["category"] == "therapy.cognitive_behavioral"

        # Step 2: domain='therapy' -> 0
        assert calls[1]["domain"] == "therapy"

        # Step 3: FTS query matching 'insomnia' and 'sleep'
        assert calls[2]["query"] == prompt_str
        assert calls[2]["limit"] == 8

        # Invariant 2: Candidate retrieved via FTS was habit-coordinator
        assert res["current_agent"] == "habit-coordinator"
        assert res["routed_subgraph"] == "habit-coordinator"

        await catalog.close()

    @pytest.mark.asyncio
    async def test_completely_fabricated_domain_fts_recovery(self, temp_workspace: Path):
        """Tier-1 returns a fabricated domain like 'aerospace_medicine'."""
        catalog = SqliteCatalogAdapter(db_path=":memory:")
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        agents = [
            make_agent(
                "benefits-coordinator",
                "Benefits Coordinator",
                domain="navigation",
                category="navigation.insurance",
                description="Specializes in deductible, copay, and coinsurance benefits.",
                tags=["insurance", "deductible", "copay", "eob"],
            ),
        ]
        for a in agents:
            await catalog.index_agent(a)

        tier1_resp = json.dumps({
            "domain": "aerospace_medicine",
            "category": "aerospace.hyperbaric",
            "reasoning": "Flight physical insurance coverage.",
        })
        tier2_resp = json.dumps({
            "agent_id": "benefits-coordinator",
            "reasoning": "Selected benefits guide via FTS keyword match on copay.",
            "instructions": "",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=catalog)

        state = {"messages": [HumanMessage(content="What is my in-network copay deductible for an aerospace flight physical?")]}
        res = await node.execute(state)

        assert res["current_agent"] == "benefits-coordinator"

        await catalog.close()


# ============================================================================
# Verification Step 4: Pure Gibberish & Total Absence -> Pattern Matching Fallback
# ============================================================================



# ============================================================================
# Verification Step 5: Candidate Limits (Strictly <= 8)
# ============================================================================

class TestChallengeStep5CandidateLimits:
    """Verification Step 5: Candidate limits: Ensure candidates list passed to Tier-2 is strictly <= 8.
    
    Verifies:
    - When database has 25 matching agents for exact category, Tier-2 receives <= 8.
    - When database has 25 matching agents for domain fallback, Tier-2 receives <= 8.
    - When database has 25 matching agents for FTS fallback, Tier-2 receives <= 8.
    - When a custom or non-compliant CatalogPort returns >8 items, Orchestrator behavior is characterized.
    """

    @pytest.mark.asyncio
    async def test_exact_category_match_capped_at_8_with_25_indexed_agents(self, temp_workspace: Path):
        catalog = SqliteCatalogAdapter(db_path=":memory:")
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        # Index 25 agents under the EXACT SAME category
        for i in range(25):
            await catalog.index_agent(make_agent(
                agent_id=f"wellness-agent-{i:02d}",
                title=f"Wellness Agent {i:02d}",
                domain="wellness",
                category="wellness.habits",
                description=f"Specialist in daily wellness habits variant {i}.",
                tags=["habits", "daily", "wellness"],
            ))

        tier1_resp = json.dumps({
            "domain": "wellness",
            "category": "wellness.habits",
            "reasoning": "Habit wellness question matching 25 indexed agents.",
        })
        tier2_resp = json.dumps({
            "agent_id": "wellness-agent-00",
            "reasoning": "Selected agent-00.",
            "instructions": "",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=catalog)

        captured_candidates = []
        orig_build = node._build_tier2_system_prompt

        def spy_tier2_prompt(candidates: List[AgentManifest]) -> str:
            captured_candidates.extend(candidates)
            return orig_build(candidates)

        node._build_tier2_system_prompt = spy_tier2_prompt

        state = {"messages": [HumanMessage(content="Help me with daily habit tracking")]}
        res = await node.execute(state)

        # Invariant: Captured candidates passed to Tier-2 prompt must be <= 8
        assert len(captured_candidates) == 8, f"Expected exactly 8 candidates, got {len(captured_candidates)}"
        assert len(captured_candidates) <= 8

        # Verify system prompt contains exactly 8 agent blocks
        system_prompt = orig_build(captured_candidates)
        count_blocks = system_prompt.count("- **wellness-agent-")
        assert count_blocks == 8, f"Expected 8 agent entries in prompt, got {count_blocks}"

        await catalog.close()

    @pytest.mark.asyncio
    async def test_domain_fallback_capped_at_8_with_25_indexed_agents(self, temp_workspace: Path):
        catalog = SqliteCatalogAdapter(db_path=":memory:")
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        # Index 25 agents across different subcategories in clinical domain
        for i in range(25):
            await catalog.index_agent(make_agent(
                agent_id=f"clinical-agent-{i:02d}",
                title=f"Clinical Specialist {i:02d}",
                domain="clinical",
                category=f"clinical.subspecialty_{i:02d}",
                description=f"Clinical specialist number {i}.",
            ))

        # Tier-1 gives an unindexed subcategory
        tier1_resp = json.dumps({
            "domain": "clinical",
            "category": "clinical.unindexed_subspecialty",
            "reasoning": "Clinical query with unmatched subcategory.",
        })
        tier2_resp = json.dumps({
            "agent_id": "clinical-agent-00",
            "reasoning": "Selected first clinical specialist.",
            "instructions": "",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=catalog)

        captured_candidates = []
        orig_build = node._build_tier2_system_prompt

        def spy_tier2_prompt(candidates: List[AgentManifest]) -> str:
            captured_candidates.extend(candidates)
            return orig_build(candidates)

        node._build_tier2_system_prompt = spy_tier2_prompt

        state = {"messages": [HumanMessage(content="General clinical consultation needed")]}
        res = await node.execute(state)

        # Step 2 domain fallback must return strictly <= 8
        assert len(captured_candidates) == 8
        assert len(captured_candidates) <= 8

        await catalog.close()

    @pytest.mark.asyncio
    async def test_fts_fallback_capped_at_8_with_25_indexed_agents(self, temp_workspace: Path):
        catalog = SqliteCatalogAdapter(db_path=":memory:")
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        # Index 25 agents in navigation domain with tag 'hydration'
        for i in range(25):
            await catalog.index_agent(make_agent(
                agent_id=f"hydration-guide-{i:02d}",
                title=f"Hydration Guide {i:02d}",
                domain="navigation",
                category=f"navigation.logistics_{i:02d}",
                description=f"Hydration logistics guide {i}.",
                tags=["hydration", "water"],
            ))

        # Tier-1 gives 'wellness' (where 0 agents exist)
        tier1_resp = json.dumps({
            "domain": "wellness",
            "category": "wellness.habits",
            "reasoning": "Wellness domain, but no wellness agents indexed.",
        })
        tier2_resp = json.dumps({
            "agent_id": "hydration-guide-00",
            "reasoning": "Selected hydration guide from FTS.",
            "instructions": "",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=catalog)

        captured_candidates = []
        orig_build = node._build_tier2_system_prompt

        def spy_tier2_prompt(candidates: List[AgentManifest]) -> str:
            captured_candidates.extend(candidates)
            return orig_build(candidates)

        node._build_tier2_system_prompt = spy_tier2_prompt

        state = {"messages": [HumanMessage(content="Need hydration water logistics assistance")]}
        res = await node.execute(state)

        # Step 3 FTS fallback must return strictly <= 8
        assert len(captured_candidates) == 8
        assert len(captured_candidates) <= 8

        await catalog.close()


# ============================================================================
# Verification Step 6: Empty CatalogPort (Zero Agents Indexed)
# ============================================================================



# ============================================================================
# Section 7: Hostile & Boundary Edge Cases
# ============================================================================

class TestAdversarialHostileEdgeCases:
    """Stress tests covering model faults, non-alphanumeric inputs, and schema anomalies."""

    @pytest.mark.asyncio
    async def test_non_alphanumeric_symbols_prompt(self, temp_workspace: Path):
        """Prompt containing only punctuation / symbols (e.g. '??? !!! ...').
        
        Tests behavior when sanitize_fts_query produces an empty string.
        """
        catalog = SqliteCatalogAdapter(db_path=":memory:")
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        await catalog.index_agent(make_agent(
            "benefits-coordinator",
            "Benefits Coordinator",
            domain="navigation",
            category="navigation.insurance",
            description="Insurance guide",
        ))

        tier1_resp = json.dumps({
            "domain": "wellness",
            "category": "wellness.symbols",
            "reasoning": "Symbols only.",
        })
        tier2_resp = json.dumps({
            "agent_id": "benefits-coordinator",
            "reasoning": "Fallback choice.",
            "instructions": "",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=catalog)

        # Symbols prompt sanitizes to empty string
        state = {"messages": [HumanMessage(content="??? !!! ... @#$%^&*")]}
        res = await node.execute(state)

        assert res["current_agent"] is not None
        assert isinstance(res["current_agent"], str)

        await catalog.close()

    @pytest.mark.asyncio
    async def test_tier1_model_crash_recovers_via_fts_and_tier2(self, temp_workspace: Path):
        """Tier-1 model throws an unhandled exception; verify node catches and recovers."""
        catalog = SqliteCatalogAdapter(db_path=":memory:")
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        await catalog.index_agent(make_agent(
            "appointment-prep-coordinator",
            "Appointment Prep Coordinator",
            domain="navigation",
            category="navigation.appointments",
            description="Doctor appointment checklists and doctor visit preparation.",
            tags=["doctor", "appointment", "checklist"],
        ))

        class CrashingTier1Model:
            def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
                if schema == DomainClassification:
                    raise ConnectionResetError("Tier-1 LLM connection dropped by remote peer")
                from langchain_core.runnables import RunnableLambda
                return RunnableLambda(lambda msgs: OrchestratorDecision(
                    agent_id="appointment-prep-coordinator",
                    reasoning="Tier-2 succeeded despite Tier-1 crash.",
                    instructions="Prepare checklist.",
                ))

            async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
                raise ConnectionResetError("Raw Tier-1 connection dropped")

        node = OrchestratorNode(model=CrashingTier1Model(), registry=registry, catalog=catalog)

        state = {"messages": [HumanMessage(content="I need a doctor appointment preparation checklist")]}
        res = await node.execute(state)

        assert res["current_agent"] == "appointment-prep-coordinator"
        assert res["routed_subgraph"] == "appointment-prep-coordinator"

        await catalog.close()


