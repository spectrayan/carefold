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

"""Unit tests for CatalogPort contract, SqliteCatalogAdapter, FTS5 stemming, sanitization, and category tree."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

from carefold.memory.adapters.sqlite.catalog_adapter import (
    CANONICAL_DOMAINS,
    SqliteCatalogAdapter,
    build_category_tree_from_rows,
    sanitize_fts_query,
)
from carefold.memory.ports.catalog_port import CatalogPort
from carefold.schemas.manifest import (
    AgentDomain,
    AgentManifest,
    AgentMaturity,
    RiskClass,
    SkillManifest,
)


class TestCatalogPortContract:
    """Verifies that CatalogPort enforces its abstract interface."""

    def test_cannot_instantiate_abstract_catalog_port(self) -> None:
        with pytest.raises(TypeError) as exc_info:
            CatalogPort()  # type: ignore[abstract]
        error_msg = str(exc_info.value)
        assert "Can't instantiate abstract class" in error_msg
        for method in ("index_agent", "index_skill", "search_agents", "search_skills", "get_category_tree"):
            assert method in error_msg

    @pytest.mark.asyncio
    async def test_concrete_mock_implementation(self) -> None:
        class InMemoryCatalogAdapter(CatalogPort):
            def __init__(self) -> None:
                self.agents: Dict[str, AgentManifest] = {}
                self.skills: Dict[str, SkillManifest] = {}

            async def index_agent(self, manifest: AgentManifest) -> None:
                self.agents[manifest.id] = manifest

            async def index_skill(self, manifest: SkillManifest) -> None:
                self.skills[manifest.id] = manifest

            async def search_agents(
                self,
                query: Optional[str] = None,
                domain: Optional[str] = None,
                category: Optional[str] = None,
                limit: int = 10,
            ) -> List[AgentManifest]:
                res = list(self.agents.values())
                if domain:
                    res = [a for a in res if a.domain == domain]
                if category:
                    res = [a for a in res if a.category == category]
                if query:
                    res = [a for a in res if query.lower() in a.title.lower() or query.lower() in a.description.lower()]
                return res[:limit]

            async def search_skills(
                self,
                query: Optional[str] = None,
                domain: Optional[str] = None,
                category: Optional[str] = None,
                limit: int = 10,
            ) -> List[SkillManifest]:
                res = list(self.skills.values())
                if domain:
                    res = [s for s in res if s.domain == domain]
                if category:
                    res = [s for s in res if s.category == category]
                if query:
                    res = [s for s in res if query.lower() in s.name.lower() or query.lower() in s.description.lower()]
                return res[:limit]

            async def remove_agent(self, agent_id: str) -> None:
                self.agents.pop(agent_id, None)

            async def remove_skill(self, skill_id: str) -> None:
                self.skills.pop(skill_id, None)

            async def get_category_tree(self) -> Dict[str, Any]:
                rows = [{"domain": a.domain, "category": a.category} for a in self.agents.values()]
                return build_category_tree_from_rows(rows)

        adapter = InMemoryCatalogAdapter()
        agent = AgentManifest(
            id="test-agent",
            title="Test Agent",
            description="Testing agent",
            domain=AgentDomain.WELLNESS,
            category="wellness.test",
            persona="Test persona",
        )
        await adapter.index_agent(agent)
        found = await adapter.search_agents(query="Test")
        assert len(found) == 1
        assert found[0].id == "test-agent"

        tree = await adapter.get_category_tree()
        assert tree["total"] == 1
        assert tree["domains"]["wellness"]["count"] == 1
        await adapter.close()


class TestSqliteCatalogAdapter:
    """Verifies SQLite catalog adapter search, stemming, category tree, and sanitization."""

    @pytest.fixture
    async def catalog_adapter(self, tmp_path: Path):
        """Creates an isolated SqliteCatalogAdapter with a temporary database."""
        db_file = tmp_path / "test_catalog.db"
        adapter = SqliteCatalogAdapter(db_path=db_file)
        yield adapter
        await adapter.close()

    @pytest.fixture
    def sample_agents(self) -> Dict[str, AgentManifest]:
        return {
            "benefits-guide": AgentManifest(
                id="benefits-guide",
                title="Benefits Guide",
                description="Explains healthcare insurance benefits, copays, deductibles, and out-of-pocket maximums.",
                domain=AgentDomain.NAVIGATION,
                category="navigation.insurance",
                tags=["insurance", "benefits", "copay", "deductible"],
                persona="You are a helpful insurance benefits guide.",
            ),
            "habit-companion": AgentManifest(
                id="habit-companion",
                title="Habit Companion",
                description="Daily wellness habit tracker for hydration, sleep hygiene, and routines.",
                domain=AgentDomain.WELLNESS,
                category="wellness.habits",
                tags=["habits", "wellness", "sleep", "hydration"],
                persona="You are an encouraging habit coaching companion.",
            ),
            "visit-steward": AgentManifest(
                id="visit-steward",
                title="Visit Steward",
                description="Clinical visit preparation and doctor appointment navigation.",
                domain=AgentDomain.NAVIGATION,
                category="navigation.appointments",
                tags=["visit", "appointment", "doctor"],
                persona="You help patients prepare questions for medical appointments.",
            ),
            "pediatric-allergy": AgentManifest(
                id="pediatric-allergy",
                title="Pediatric Allergy Specialist",
                description="Guides parents on childhood allergy symptoms, triggers, and food avoidance.",
                domain=AgentDomain.CLINICAL,
                category="clinical.pediatrics.allergy",
                tags=["pediatrics", "allergy", "anaphylaxis"],
                persona="You assist parents with childhood allergy management.",
            ),
            "orchestrator-internal": AgentManifest(
                id="orchestrator",
                title="Internal Orchestrator",
                description="Internal routing engine.",
                domain=AgentDomain.WELLNESS,
                category="wellness.internal",
                tags=["system", "internal"],
                hidden=True,
                persona="System routing orchestrator.",
            ),
        }

    @pytest.mark.asyncio
    async def test_index_and_search_agents_basic(
        self,
        catalog_adapter: SqliteCatalogAdapter,
        sample_agents: Dict[str, AgentManifest],
    ) -> None:
        for agent in sample_agents.values():
            await catalog_adapter.index_agent(agent)

        # By default, hidden agents (orchestrator) should be excluded
        public_agents = await catalog_adapter.search_agents(limit=10)
        assert len(public_agents) == 4
        agent_ids = {a.id for a in public_agents}
        assert "benefits-guide" in agent_ids
        assert "habit-companion" in agent_ids
        assert "orchestrator" not in agent_ids

        # With include_hidden=True, all 5 are returned
        all_agents = await catalog_adapter.search_agents(limit=10, include_hidden=True)
        assert len(all_agents) == 5
        all_ids = {a.id for a in all_agents}
        assert "orchestrator" in all_ids

    @pytest.mark.asyncio
    async def test_index_and_search_skills(self, catalog_adapter: SqliteCatalogAdapter) -> None:
        skill = SkillManifest(
            id="benefits-explainer",
            name="benefits-explainer",
            description="Analyzes medical claims and explains out-of-pocket patient costs.",
            domain=AgentDomain.NAVIGATION,
            category="navigation.insurance",
            tags=["claims", "copay"],
            tools=["attach-read"],
            instructions="Explain all copays clearly.",
        )
        await catalog_adapter.index_skill(skill)

        results = await catalog_adapter.search_skills(query="claims")
        assert len(results) == 1
        assert results[0].id == "benefits-explainer"

        empty_results = await catalog_adapter.search_skills(query="orthopedics")
        assert len(empty_results) == 0

    @pytest.mark.asyncio
    async def test_fts5_porter_stemming(
        self,
        catalog_adapter: SqliteCatalogAdapter,
        sample_agents: Dict[str, AgentManifest],
    ) -> None:
        """Verifies that SQLite FTS5 Porter tokenizer matches plural queries to singular words."""
        for agent in sample_agents.values():
            await catalog_adapter.index_agent(agent)

        # 1. 'copays' (plural) matches manifest with 'copay' (singular)
        plural_results = await catalog_adapter.search_agents(query="copays")
        assert len(plural_results) >= 1
        assert any(a.id == "benefits-guide" for a in plural_results)

        # 2. 'copay' (singular) matches manifest
        singular_results = await catalog_adapter.search_agents(query="copay")
        assert len(singular_results) >= 1
        assert any(a.id == "benefits-guide" for a in singular_results)

        # 3. 'habits' matches 'habit'
        habit_results = await catalog_adapter.search_agents(query="habit")
        assert len(habit_results) >= 1
        assert any(a.id == "habit-companion" for a in habit_results)

        # 4. 'appointments' matches 'appointment'
        appointment_results = await catalog_adapter.search_agents(query="appointments")
        assert len(appointment_results) >= 1
        assert any(a.id == "visit-steward" for a in appointment_results)

    @pytest.mark.asyncio
    async def test_domain_and_category_filtering(
        self,
        catalog_adapter: SqliteCatalogAdapter,
        sample_agents: Dict[str, AgentManifest],
    ) -> None:
        for agent in sample_agents.values():
            await catalog_adapter.index_agent(agent)

        # Domain filter
        nav_agents = await catalog_adapter.search_agents(domain="navigation")
        assert len(nav_agents) == 2
        assert {a.id for a in nav_agents} == {"benefits-guide", "visit-steward"}

        wellness_agents = await catalog_adapter.search_agents(domain="wellness")
        assert len(wellness_agents) == 1
        assert wellness_agents[0].id == "habit-companion"

        therapy_agents = await catalog_adapter.search_agents(domain="therapy")
        assert len(therapy_agents) == 0

        # Exact category filter
        insurance_agents = await catalog_adapter.search_agents(category="navigation.insurance")
        assert len(insurance_agents) == 1
        assert insurance_agents[0].id == "benefits-guide"

        # Category prefix filter
        nav_cat_agents = await catalog_adapter.search_agents(category="navigation")
        assert len(nav_cat_agents) == 2

        # Combined query + domain filter
        matched = await catalog_adapter.search_agents(query="copays", domain="navigation")
        assert len(matched) == 1
        assert matched[0].id == "benefits-guide"

        # Mismatched query + domain returns empty list
        mismatched = await catalog_adapter.search_agents(query="copays", domain="clinical")
        assert len(mismatched) == 0

    @pytest.mark.asyncio
    async def test_get_category_tree_hierarchy_and_counts(
        self,
        catalog_adapter: SqliteCatalogAdapter,
        sample_agents: Dict[str, AgentManifest],
    ) -> None:
        for agent in sample_agents.values():
            await catalog_adapter.index_agent(agent)

        tree = await catalog_adapter.get_category_tree()

        # Total count (excludes hidden by default)
        assert tree["total"] == 4

        # Canonical domains must always be present
        domains = tree["domains"]
        for canonical in ("clinical", "therapy", "wellness", "navigation", "education"):
            assert canonical in domains
            assert "count" in domains[canonical]
            assert "categories" in domains[canonical]

        # Domain counts
        assert domains["navigation"]["count"] == 2
        assert domains["wellness"]["count"] == 1
        assert domains["clinical"]["count"] == 1
        assert domains["therapy"]["count"] == 0
        assert domains["education"]["count"] == 0

        # Subcategories under navigation
        nav_cats = domains["navigation"]["categories"]
        assert "insurance" in nav_cats
        assert nav_cats["insurance"]["count"] == 1
        assert "appointments" in nav_cats
        assert nav_cats["appointments"]["count"] == 1

        # Deep subcategories under clinical (clinical.pediatrics.allergy)
        clinical_cats = domains["clinical"]["categories"]
        assert "pediatrics" in clinical_cats
        assert clinical_cats["pediatrics"]["count"] == 1
        ped_subs = clinical_cats["pediatrics"].get("subcategories", {})
        assert "allergy" in ped_subs
        assert ped_subs["allergy"]["count"] == 1

        # Including hidden
        tree_hidden = await catalog_adapter.get_category_tree(include_hidden=True)
        assert tree_hidden["total"] == 5
        assert tree_hidden["domains"]["wellness"]["count"] == 2

    @pytest.mark.asyncio
    async def test_get_category_tree_empty_catalog(self, catalog_adapter: SqliteCatalogAdapter) -> None:
        tree = await catalog_adapter.get_category_tree()
        assert tree["total"] == 0
        for canonical in ("clinical", "therapy", "wellness", "navigation", "education"):
            assert tree["domains"][canonical]["count"] == 0
            assert tree["domains"][canonical]["categories"] == {}

    @pytest.mark.asyncio
    async def test_fts5_query_sanitization_adversarial_queries(
        self,
        catalog_adapter: SqliteCatalogAdapter,
        sample_agents: Dict[str, AgentManifest],
    ) -> None:
        """Verifies that malformed, punctuation-heavy, and injection queries do not crash SQLite."""
        for agent in sample_agents.values():
            await catalog_adapter.index_agent(agent)

        hazardous_queries = [
            "::??? () *",                                 # Pure punctuation & wildcards
            '"unclosed quote with copay',                 # Unclosed double quote
            "'single quote and insurance",                # Single quote
            "copay AND OR NOT NEAR insurance",            # FTS5 reserved keywords
            "title:benefits description:copay",           # Column filter collision
            "copay*",                                     # Suffix wildcard
            "copay (insurance AND (deductible OR out))",  # Nested parentheses
            "' OR 1=1 --",                                # SQL injection attempt
            "médicament & résumé",                        # Accents and ampersand
            "   ",                                        # Pure whitespace
        ]

        for query in hazardous_queries:
            # Query must never raise sqlite3.OperationalError: fts5: syntax error
            results = await catalog_adapter.search_agents(query=query)
            assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_get_and_delete_operations(
        self,
        catalog_adapter: SqliteCatalogAdapter,
        sample_agents: Dict[str, AgentManifest],
    ) -> None:
        agent = sample_agents["benefits-guide"]
        await catalog_adapter.index_agent(agent)

        # get_agent
        fetched = await catalog_adapter.get_agent("benefits-guide")
        assert fetched is not None
        assert fetched.id == "benefits-guide"
        assert fetched.title == "Benefits Guide"

        # count_agents
        assert await catalog_adapter.count_agents() == 1

        # delete_agent
        deleted = await catalog_adapter.delete_agent("benefits-guide")
        assert deleted is True
        assert await catalog_adapter.count_agents() == 0
        assert await catalog_adapter.get_agent("benefits-guide") is None

        # delete non-existent
        assert await catalog_adapter.delete_agent("benefits-guide") is False

    @pytest.mark.asyncio
    async def test_skill_get_and_delete(self, catalog_adapter: SqliteCatalogAdapter) -> None:
        skill = SkillManifest(
            id="test-skill",
            name="test-skill",
            description="A test skill",
            domain=AgentDomain.THERAPY,
            category="therapy.cbt",
        )
        await catalog_adapter.index_skill(skill)
        assert await catalog_adapter.count_skills() == 1

        fetched = await catalog_adapter.get_skill("test-skill")
        assert fetched is not None
        assert fetched.id == "test-skill"

        deleted = await catalog_adapter.delete_skill("test-skill")
        assert deleted is True
        assert await catalog_adapter.count_skills() == 0

    @pytest.mark.asyncio
    async def test_tag_filtering(
        self,
        catalog_adapter: SqliteCatalogAdapter,
        sample_agents: Dict[str, AgentManifest],
    ) -> None:
        for agent in sample_agents.values():
            await catalog_adapter.index_agent(agent)

        tagged = await catalog_adapter.search_agents(tags=["copay"])
        assert len(tagged) == 1
        assert tagged[0].id == "benefits-guide"

        multi_tag = await catalog_adapter.search_agents(tags=["sleep", "anaphylaxis"])
        assert len(multi_tag) == 2
        matched_ids = {a.id for a in multi_tag}
        assert matched_ids == {"habit-companion", "pediatric-allergy"}

    @pytest.mark.asyncio
    async def test_pagination(
        self,
        catalog_adapter: SqliteCatalogAdapter,
        sample_agents: Dict[str, AgentManifest],
    ) -> None:
        for agent in sample_agents.values():
            await catalog_adapter.index_agent(agent)

        # Page 1, limit 2
        page1 = await catalog_adapter.search_agents(limit=2, offset=0)
        assert len(page1) == 2

        # Page 2, limit 2
        page2 = await catalog_adapter.search_agents(limit=2, offset=2)
        assert len(page2) == 2

        # Ensure disjoint pages
        p1_ids = {a.id for a in page1}
        p2_ids = {a.id for a in page2}
        assert p1_ids.isdisjoint(p2_ids)
