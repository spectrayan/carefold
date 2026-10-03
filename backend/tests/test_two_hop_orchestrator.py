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

"""Unit and integration tests for Two-Hop Orchestrator Routing.

Verifies:
1. DomainClassification schema fields and defaults.
2. Static Tier-1 Domain Classifier prompt invariants (~500 tokens, 5 domains, zero agent descriptions).
3. Backward compatibility: OrchestratorNode with catalog=None executes single-hop flow with zero regression.
4. Two-Hop routing with SqliteCatalogAdapter (Tier-1 classification -> Tier-2 candidate selection).
5. Full 4-step fallback chain:
   - Step 1: Category match returns specific candidates.
   - Step 2: When category doesn't match, falls back to domain-only match.
   - Step 3: When domain doesn't match, falls back to FTS query on tags/prompt.
   - Step 4: When FTS returns 0, falls back to pattern-matching fallback.
6. Spy validation of CatalogPort call sequence.
7. Resilience against model errors, explicit bypass, and hallucinated candidate IDs.
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
    AGENT_BENEFITS_GUIDE,
    AGENT_DOCUMENT_EXTRACTOR,
    AGENT_HABIT_COMPANION,
    AGENT_ORCHESTRATOR,
    AGENT_VISIT_STEWARD,
    DEFAULT_ROUTING_FALLBACK_AGENT,
)
from carefold.memory.adapters.sqlite.catalog_adapter import SqliteCatalogAdapter
from carefold.memory.ports.catalog_port import CatalogPort
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
from tests.fixtures.fake_model import FakeListChatModel


# ============================================================================
# Test Fixtures & Test Data
# ============================================================================

def make_test_manifest(
    agent_id: str,
    title: str,
    domain: str,
    category: str,
    description: str,
    tags: Optional[List[str]] = None,
    tools: Optional[List[str]] = None,
) -> AgentManifest:
    """Creates a typed AgentManifest fixture for catalog indexing."""
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
        tools=tools or ["workspace-note", "attach-read"],
        can_delegate=True,
    )


@pytest.fixture
async def indexed_catalog() -> SqliteCatalogAdapter:
    """Provides an in-memory SqliteCatalogAdapter populated with test agents across domains."""
    catalog = SqliteCatalogAdapter(db_path=":memory:")

    agents = [
        make_test_manifest(
            agent_id="benefits-guide",
            title="Benefits Guide",
            domain="navigation",
            category="navigation.insurance",
            description="Specializes in health insurance coverage, copays, deductibles, and claims navigation.",
            tags=["insurance", "benefits", "eob", "deductible", "copay"],
            tools=["attach-read", "workspace-note"],
        ),
        make_test_manifest(
            agent_id="visit-steward",
            title="Visit Steward",
            domain="navigation",
            category="navigation.appointments",
            description="Assists with clinical appointment preparation, doctor questions, and visit checklists.",
            tags=["appointment", "doctor", "visit-prep", "checklist"],
            tools=["workspace-note", "attach-read"],
        ),
        make_test_manifest(
            agent_id="habit-companion",
            title="Habit Companion",
            domain="wellness",
            category="wellness.habits",
            description="Helps users build consistent healthy habits, track hydration, and improve sleep hygiene.",
            tags=["habits", "hydration", "sleep", "lifestyle", "water"],
            tools=["workspace-note"],
        ),
        make_test_manifest(
            agent_id="nutrition-coach",
            title="Nutrition Coach",
            domain="wellness",
            category="wellness.nutrition",
            description="Provides dietary planning, healthy meal guidance, and nutritional tracking.",
            tags=["nutrition", "meal", "diet", "macros", "food"],
            tools=["workspace-note"],
        ),
        make_test_manifest(
            agent_id="clinical-triage",
            title="Clinical Triage",
            domain="clinical",
            category="clinical.triage",
            description="Performs preliminary symptom assessment and physician visit recommendations.",
            tags=["symptoms", "triage", "fever", "cough", "clinical"],
            tools=["attach-read"],
        ),
    ]

    for a in agents:
        await catalog.index_agent(a)

    yield catalog
    await catalog.close()


# ============================================================================
# Section 1: Schema & Static Prompt Contract Tests
# ============================================================================

class TestTwoHopSchemasAndPromptContract:
    """Verifies DomainClassification schema and static Tier-1 prompt invariants."""

    def test_domain_classification_schema_defaults(self):
        """Validates DomainClassification schema fields, defaults, and serialization."""
        d = DomainClassification(domain="navigation")
        assert d.domain == "navigation"
        assert d.category == ""
        assert d.reasoning == ""

        data = d.model_dump()
        assert data["domain"] == "navigation"
        assert data["category"] == ""
        assert data["reasoning"] == ""

        d2 = DomainClassification(
            domain="wellness",
            category="wellness.habits",
            reasoning="Query asks about daily hydration goals.",
        )
        assert d2.domain == "wellness"
        assert d2.category == "wellness.habits"
        assert d2.reasoning == "Query asks about daily hydration goals."

    def test_tier1_static_prompt_invariants(self):
        """Verifies that Tier-1 classifier prompt is static, bounded, and contains NO agent catalogs."""
        prompt = TIER1_DOMAIN_CLASSIFIER_PROMPT

        # Must describe all 5 required domains
        assert "clinical" in prompt
        assert "therapy" in prompt
        assert "wellness" in prompt
        assert "navigation" in prompt
        assert "education" in prompt

        # Must contain example dot-notated category paths
        assert "clinical.triage" in prompt
        assert "therapy.cbt" in prompt
        assert "wellness.habits" in prompt
        assert "navigation.insurance" in prompt
        assert "education.conditions" in prompt

        # Invariant: Must NOT contain agent catalog descriptions or specific agent IDs
        assert "benefits-guide" not in prompt
        assert "visit-steward" not in prompt
        assert "habit-companion" not in prompt
        assert "document-extractor" not in prompt

        # Invariant: Prompt must be compact and bounded (~500 tokens / <500 words)
        words = prompt.split()
        assert len(words) < 500
        assert len(words) > 100

    def test_format_candidate_agents(self):
        """Verifies candidate agents formatting includes name, title, domain, category, description, tools."""
        node = OrchestratorNode()
        candidates = [
            make_test_manifest(
                agent_id="test-agent",
                title="Test Agent",
                domain="wellness",
                category="wellness.test",
                description="A test agent description.",
                tools=["tool-a", "tool-b"],
            )
        ]
        formatted = node._format_candidate_agents(candidates)
        assert "**test-agent**" in formatted
        assert "(Test Agent)" in formatted
        assert "[Domain: wellness, Category: wellness.test]" in formatted
        assert "Description: A test agent description." in formatted
        assert "Tools: [tool-a, tool-b]" in formatted


# ============================================================================
# Section 2: Backward Compatibility (catalog=None)
# ============================================================================

class TestBackwardCompatibility:
    """Verifies that OrchestratorNode with catalog=None runs single-hop flow with ZERO regression."""

    @pytest.mark.asyncio
    async def test_single_hop_flow_when_catalog_is_none(self, temp_workspace: Path):
        """Confirms that when catalog is None, node executes single-hop format_agent_catalog flow."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
        model_response = json.dumps({
            "agent_id": "benefits-guide",
            "reasoning": "Single-hop routing to benefits guide.",
            "instructions": "Clarify copay details.",
        })
        fake_model = FakeListChatModel(responses=[model_response])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=None)

        state = {"messages": [HumanMessage(content="What is my copay for a specialist?")]}
        result = await node.execute(state)

        assert result["current_agent"] == "benefits-guide"
        assert result["routed_subgraph"] == "benefits-guide"
        assert result["orchestrator_instructions"] == "Clarify copay details."
        assert "Single-hop routing to benefits guide" in result["orchestrator_reasoning"]

    @pytest.mark.asyncio
    async def test_single_hop_preserves_build_system_prompt(self, temp_workspace: Path):
        """Verifies _build_system_prompt remains functional and embeds full registry catalog."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
        node = OrchestratorNode(registry=registry, catalog=None)

        prompt = node._build_system_prompt({})
        assert "Available Specialist Agents:" in prompt
        assert AGENT_BENEFITS_GUIDE in prompt
        assert AGENT_VISIT_STEWARD in prompt
        assert AGENT_HABIT_COMPANION in prompt
        assert AGENT_DOCUMENT_EXTRACTOR in prompt

    @pytest.mark.asyncio
    async def test_single_hop_model_none_fallback(self, temp_workspace: Path):
        """Verifies single-hop offline pattern fallback when model is None."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
        node = OrchestratorNode(model=None, registry=registry, catalog=None)

        state = {"messages": [HumanMessage(content="What is my copay?")]}
        result = await node.execute(state)

        assert result["current_agent"] == "benefits-guide"
        assert "Model unconfigured" in result["orchestrator_reasoning"]


# ============================================================================
# Section 3: Two-Hop Routing Flow (Tier-1 Classifier -> Tier-2 Specialist Picker)
# ============================================================================

class TestTwoHopRoutingFlow:
    """Verifies the two-hop routing sequence when catalog is provided."""

    @pytest.mark.asyncio
    async def test_two_hop_full_success_flow(self, indexed_catalog: SqliteCatalogAdapter, temp_workspace: Path):
        """Tier-1 classifies domain & category, Tier-2 selects specialist from filtered candidate set."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        tier1_resp = json.dumps({
            "domain": "navigation",
            "category": "navigation.insurance",
            "reasoning": "User asks about insurance coverage and deductibles.",
        })
        tier2_resp = json.dumps({
            "agent_id": "benefits-guide",
            "reasoning": "Selected benefits-guide from candidate set to handle insurance query.",
            "instructions": "Explain in-network deductible terms.",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=indexed_catalog)

        state = {"messages": [HumanMessage(content="Can you explain my deductible?")]}
        result = await node.execute(state)

        assert result["current_agent"] == "benefits-guide"
        assert result["routed_subgraph"] == "benefits-guide"
        assert result["orchestrator_instructions"] == "Explain in-network deductible terms."
        assert "Selected benefits-guide from candidate set" in result["orchestrator_reasoning"]

    @pytest.mark.asyncio
    async def test_two_hop_wellness_domain_selection(self, indexed_catalog: SqliteCatalogAdapter, temp_workspace: Path):
        """Tier-1 classifies wellness.habits, Tier-2 selects habit-companion."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        tier1_resp = json.dumps({
            "domain": "wellness",
            "category": "wellness.habits",
            "reasoning": "Query asks about water intake and daily sleep habits.",
        })
        tier2_resp = json.dumps({
            "agent_id": "habit-companion",
            "reasoning": "Habit companion is best suited for hydration and sleep tracking.",
            "instructions": "Set a goal of 64 ounces of water daily.",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=indexed_catalog)

        state = {"messages": [HumanMessage(content="How much water should I drink every day?")]}
        result = await node.execute(state)

        assert result["current_agent"] == "habit-companion"
        assert result["routed_subgraph"] == "habit-companion"
        assert result["orchestrator_instructions"] == "Set a goal of 64 ounces of water daily."


# ============================================================================
# Section 4: Fallback Chain Tests (Step 1 -> Step 2 -> Step 3 -> Step 4)
# ============================================================================

class TestFallbackChain:
    """Verifies the 4-step fallback chain in Two-Hop routing:
    - Step 1: Category match returns specific candidates.
    - Step 2: When category doesn't match, falls back to domain-only match.
    - Step 3: When domain doesn't match, falls back to FTS query on tags/prompt.
    - Step 4: When FTS returns 0, falls back to pattern-matching fallback.
    """

    @pytest.mark.asyncio
    async def test_fallback_step1_category_match(self, indexed_catalog: SqliteCatalogAdapter, temp_workspace: Path):
        """Step 1: Category match returns only candidates matching the specific category."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        tier1_resp = json.dumps({
            "domain": "wellness",
            "category": "wellness.nutrition",
            "reasoning": "Query is about meal prep and nutrition.",
        })
        tier2_resp = json.dumps({
            "agent_id": "nutrition-coach",
            "reasoning": "Targeted nutrition coach based on exact category match.",
            "instructions": "Provide meal planning tips.",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=indexed_catalog)

        # Spy on catalog.search_agents to verify call kwargs
        original_search = indexed_catalog.search_agents
        calls = []

        async def spy_search(*args: Any, **kwargs: Any) -> List[AgentManifest]:
            calls.append(kwargs)
            return await original_search(*args, **kwargs)

        with patch.object(indexed_catalog, "search_agents", side_effect=spy_search):
            state = {"messages": [HumanMessage(content="What should I eat for dinner?")]}
            result = await node.execute(state)

        # Step 1 succeeded on the very first call: domain="wellness", category="wellness.nutrition"
        assert len(calls) == 1
        assert calls[0]["domain"] == "wellness"
        assert calls[0]["category"] == "wellness.nutrition"
        assert result["current_agent"] == "nutrition-coach"

    @pytest.mark.asyncio
    async def test_fallback_step2_domain_match_when_category_unmatched(
        self, indexed_catalog: SqliteCatalogAdapter, temp_workspace: Path
    ):
        """Step 2: When category doesn't match, falls back to domain-only match."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        # Tier-1 gives a category that does NOT exist in catalog ("wellness.mental_wellness")
        tier1_resp = json.dumps({
            "domain": "wellness",
            "category": "wellness.mental_wellness",
            "reasoning": "Wellness category that is not indexed in catalog.",
        })
        tier2_resp = json.dumps({
            "agent_id": "habit-companion",
            "reasoning": "Fell back to domain-wide candidates and selected habit companion.",
            "instructions": "",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=indexed_catalog)

        original_search = indexed_catalog.search_agents
        calls = []

        async def spy_search(*args: Any, **kwargs: Any) -> List[AgentManifest]:
            calls.append(kwargs)
            return await original_search(*args, **kwargs)

        with patch.object(indexed_catalog, "search_agents", side_effect=spy_search):
            state = {"messages": [HumanMessage(content="Help me relax before bedtime")]}
            result = await node.execute(state)

        # Call 1: domain="wellness", category="wellness.mental_wellness" -> 0 results
        # Call 2: domain="wellness" (domain-only) -> matched candidates [habit-companion, nutrition-coach]
        assert len(calls) == 2
        assert calls[0]["category"] == "wellness.mental_wellness"
        assert calls[1].get("category") is None or calls[1].get("category") == ""
        assert calls[1]["domain"] == "wellness"
        assert result["current_agent"] == "habit-companion"

    @pytest.mark.asyncio
    async def test_fallback_step3_fts_when_domain_unmatched(
        self, indexed_catalog: SqliteCatalogAdapter, temp_workspace: Path
    ):
        """Step 3: When domain has 0 agents, falls back to FTS query on prompt/tags."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        # Tier-1 returns "therapy" domain which has NO indexed agents in indexed_catalog
        tier1_resp = json.dumps({
            "domain": "therapy",
            "category": "therapy.cbt",
            "reasoning": "Therapy domain classification.",
        })
        tier2_resp = json.dumps({
            "agent_id": "habit-companion",
            "reasoning": "FTS matched sleep hygiene tags in habit companion.",
            "instructions": "Focus on evening sleep routine.",
        })

        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=indexed_catalog)

        original_search = indexed_catalog.search_agents
        calls = []

        async def spy_search(*args: Any, **kwargs: Any) -> List[AgentManifest]:
            calls.append(kwargs)
            return await original_search(*args, **kwargs)

        with patch.object(indexed_catalog, "search_agents", side_effect=spy_search):
            # Prompt text explicitly mentions "sleep hygiene" which matches habit-companion tags/description
            state = {"messages": [HumanMessage(content="I need help with my sleep hygiene and bedtime routine")]}
            result = await node.execute(state)

        # Call 1: domain="therapy", category="therapy.cbt" -> 0
        # Call 2: domain="therapy" -> 0
        # Call 3: query="I need help with my sleep hygiene and bedtime routine" -> FTS matches habit-companion!
        assert len(calls) == 3
        assert calls[0]["domain"] == "therapy"
        assert calls[1]["domain"] == "therapy"
        assert calls[2]["query"] == "I need help with my sleep hygiene and bedtime routine"
        assert result["current_agent"] == "habit-companion"

    @pytest.mark.asyncio
    async def test_fallback_step4_pattern_fallback_when_fts_returns_zero(
        self, indexed_catalog: SqliteCatalogAdapter, temp_workspace: Path
    ):
        """Step 4: When FTS returns 0 candidates, falls back to pattern-matching fallback."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        # Tier-1 returns "education" domain which has 0 agents
        tier1_resp = json.dumps({
            "domain": "education",
            "category": "education.pharmacology",
            "reasoning": "Education domain classification.",
        })

        # Tier 2 is NOT called because candidates == 0; it directly triggers _resolve_pattern_fallback
        fake_model = FakeListChatModel(responses=[tier1_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=indexed_catalog)

        # Prompt contains regex keyword for benefits-guide ("in-network copay deductible")
        # but catalog has FTS mocked or returning 0
        with patch.object(indexed_catalog, "search_agents", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []  # All catalog queries return 0 candidates

            state = {"messages": [HumanMessage(content="What is my in-network copay?")]}
            result = await node.execute(state)

        # Verify fallback chain was called:
        # Step 1: domain + category
        # Step 2: domain only
        # Step 3: query
        assert mock_search.call_count == 3

        # Step 4: pattern fallback resolved to benefits-guide via regex
        assert result["current_agent"] == "benefits-guide"
        assert result["routed_subgraph"] == "benefits-guide"
        assert "pattern fallback" in result["orchestrator_reasoning"].lower()


# ============================================================================
# Section 5: Edge Cases, Bypass & Resilience
# ============================================================================

class TestTwoHopResilienceAndEdgeCases:
    """Verifies edge cases including explicit routing bypass, model failure, and missing skills."""

    @pytest.mark.asyncio
    async def test_two_hop_explicit_routing_bypass(
        self, indexed_catalog: SqliteCatalogAdapter, temp_workspace: Path
    ):
        """Verifies that pre-routed state bypasses both Tier-1 and Tier-2 model calls."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
        node = OrchestratorNode(model=None, registry=registry, catalog=indexed_catalog)

        state = {
            "current_agent": "visit-steward",
            "messages": [HumanMessage(content="Hello doctor")],
        }
        result = await node.execute(state)

        assert result["current_agent"] == "visit-steward"
        assert result["routed_subgraph"] == "visit-steward"
        assert "Explicitly requested" in result["orchestrator_reasoning"]

    @pytest.mark.asyncio
    async def test_two_hop_tier1_model_error_falls_back_gracefully(
        self, indexed_catalog: SqliteCatalogAdapter, temp_workspace: Path
    ):
        """Verifies that if Tier-1 model call raises or fails, Step 3 (FTS on prompt) activates."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        class FailingTier1ChatModel:
            def __init__(self):
                self.call_count = 0

            def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
                self.call_count += 1
                if schema == DomainClassification:
                    raise RuntimeError("Tier-1 LLM connection error")
                # Tier-2 succeeds
                from langchain_core.runnables import RunnableLambda
                return RunnableLambda(lambda msgs: OrchestratorDecision(
                    agent_id="visit-steward",
                    reasoning="Tier-2 succeeded after Tier-1 recovery.",
                    instructions="",
                ))

            async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
                raise RuntimeError("Raw invocation error")

        model = FailingTier1ChatModel()
        node = OrchestratorNode(model=model, registry=registry, catalog=indexed_catalog)

        state = {"messages": [HumanMessage(content="doctor appointment prep checklist")]}
        result = await node.execute(state)

        assert result["current_agent"] == "visit-steward"
        assert result["routed_subgraph"] == "visit-steward"

    @pytest.mark.asyncio
    async def test_two_hop_tier2_model_error_falls_back_to_first_candidate(
        self, indexed_catalog: SqliteCatalogAdapter, temp_workspace: Path
    ):
        """Verifies that if Tier-2 fails, the first candidate from the catalog is selected as fallback."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        tier1_resp = json.dumps({
            "domain": "navigation",
            "category": "navigation.insurance",
            "reasoning": "Insurance category match.",
        })
        # Second response is invalid JSON / garbage
        fake_model = FakeListChatModel(responses=[tier1_resp, "Invalid unstructured response"])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=indexed_catalog)

        state = {"messages": [HumanMessage(content="What is my insurance copay?")]}
        result = await node.execute(state)

        assert result["current_agent"] == "benefits-guide"
        assert "fallback" in result["orchestrator_reasoning"].lower()

    @pytest.mark.asyncio
    async def test_two_hop_hallucinated_agent_falls_back_to_candidate(
        self, indexed_catalog: SqliteCatalogAdapter, temp_workspace: Path
    ):
        """Verifies that if Tier-2 returns an unknown agent_id, it safely falls back to a candidate."""
        registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")

        tier1_resp = json.dumps({
            "domain": "navigation",
            "category": "navigation.insurance",
            "reasoning": "Insurance category match.",
        })
        tier2_resp = json.dumps({
            "agent_id": "non-existent-agent-999",
            "reasoning": "Hallucinated agent ID.",
            "instructions": "",
        })
        fake_model = FakeListChatModel(responses=[tier1_resp, tier2_resp])
        node = OrchestratorNode(model=fake_model, registry=registry, catalog=indexed_catalog)

        state = {"messages": [HumanMessage(content="Insurance deductible inquiry")]}
        result = await node.execute(state)

        # Candidate benefits-guide was retrieved in Tier-2 candidate list, so fallback selects it
        assert result["current_agent"] == "benefits-guide"
        assert "not found in registry" in result["orchestrator_reasoning"]
