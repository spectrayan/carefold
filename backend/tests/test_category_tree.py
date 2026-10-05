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

"""Category Tree, Factory Resolution, and Database Concurrency Test Suite.
Scope:
1. Category tree hierarchy (0 agents, 1 agent, many agents, canonical domains, multi-level dot categories)
2. Factory & Settings (sqlite backend, NotImplementedError on spector/postgres, ValueError on invalid, reset_memory_ports)
3. Concurrency (concurrent index and search operations in asyncio.gather(), multi-adapter WAL locking validation)
"""

import asyncio
import random
from pathlib import Path
from typing import Any, Dict, List
import pytest

from carefold.config import Settings
from carefold.memory.adapters.sqlite.catalog_adapter import (
    CANONICAL_DOMAINS,
    SqliteCatalogAdapter,
    build_category_tree_from_rows,
)
from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
from carefold.memory.factory import (
    SUPPORTED_MEMORY_BACKENDS,
    create_catalog_port,
    create_memory_port,
    get_catalog_port,
    get_memory_port,
    reset_memory_ports,
    set_catalog_port,
    set_memory_port,
)
from carefold.memory.ports.catalog_port import CatalogPort
from carefold.memory.ports.memory_port import MemoryPort, MemoryTier
from carefold.schemas.manifest import (
    AgentDomain,
    AgentManifest,
    AgentMaturity,
    RiskClass,
)


def _make_agent(
    agent_id: str,
    domain: AgentDomain = AgentDomain.WELLNESS,
    category: str = "",
    title: str = "Test Agent",
    hidden: bool = False,
    tags: List[str] = None,
) -> AgentManifest:
    return AgentManifest(
        id=agent_id,
        title=title,
        version="0.1.0",
        domain=domain,
        category=category,
        risk_class=RiskClass.WELLNESS,
        tags=tags or ["test"],
        description=f"Description for {title}",
        hidden=hidden,
        persona=f"Persona for {title}",
    )


# ==============================================================================
# 1. Category Tree Hierarchy Tests
# ==============================================================================

class TestCategoryTreeHierarchyEmpirical:
    """Empirical challenge for CatalogPort.get_category_tree() hierarchy and roll-up semantics."""

    @pytest.fixture
    async def adapter(self, tmp_path: Path):
        db_file = tmp_path / "cat_tree_test.db"
        ad = SqliteCatalogAdapter(db_path=db_file)
        yield ad
        await ad.close()

    @pytest.mark.asyncio
    async def test_get_category_tree_zero_agents(self, adapter: SqliteCatalogAdapter) -> None:
        """Challenge 1.1: 0 agents in catalog.
        
        Must return total=0 and all 5 canonical domains with count=0 and empty categories.
        """
        tree = await adapter.get_category_tree()
        assert isinstance(tree, dict)
        assert tree["total"] == 0
        assert "domains" in tree
        domains = tree["domains"]

        expected_canonical = {"clinical", "therapy", "wellness", "navigation", "education"}
        assert set(domains.keys()) == expected_canonical

        for dom_name in expected_canonical:
            dom_data = domains[dom_name]
            assert dom_data["count"] == 0, f"Domain {dom_name} expected count 0, got {dom_data['count']}"
            assert dom_data["categories"] == {}, f"Domain {dom_name} expected empty categories"

    @pytest.mark.asyncio
    async def test_get_category_tree_single_agent_each_domain(self, adapter: SqliteCatalogAdapter) -> None:
        """Challenge 1.2: 1 agent in each canonical domain in turn."""
        canonical_enums = [
            AgentDomain.CLINICAL,
            AgentDomain.THERAPY,
            AgentDomain.WELLNESS,
            AgentDomain.NAVIGATION,
            AgentDomain.EDUCATION,
        ]

        for domain_enum in canonical_enums:
            # Create fresh isolated adapter for each test
            agent = _make_agent(
                agent_id=f"agent-{domain_enum.value}",
                domain=domain_enum,
                category=f"{domain_enum.value}.primary",
                title=f"{domain_enum.value.capitalize()} Agent",
            )
            await adapter.index_agent(agent)

        tree = await adapter.get_category_tree()
        assert tree["total"] == 5
        for domain_enum in canonical_enums:
            dom = domain_enum.value
            assert tree["domains"][dom]["count"] == 1
            assert "primary" in tree["domains"][dom]["categories"]
            assert tree["domains"][dom]["categories"]["primary"]["count"] == 1

    @pytest.mark.asyncio
    async def test_get_category_tree_agent_without_category(self, adapter: SqliteCatalogAdapter) -> None:
        """Challenge 1.3: Agent with empty category string."""
        agent = _make_agent("no-cat-agent", domain=AgentDomain.WELLNESS, category="")
        await adapter.index_agent(agent)

        tree = await adapter.get_category_tree()
        assert tree["total"] == 1
        assert tree["domains"]["wellness"]["count"] == 1
        assert tree["domains"]["wellness"]["categories"] == {}

    @pytest.mark.asyncio
    async def test_get_category_tree_agent_category_equals_domain(self, adapter: SqliteCatalogAdapter) -> None:
        """Challenge 1.4: Agent where category string is exactly the domain name.
        
        Should not create a redundant self-referential subcategory.
        """
        agent = _make_agent("self-cat-agent", domain=AgentDomain.CLINICAL, category="clinical")
        await adapter.index_agent(agent)

        tree = await adapter.get_category_tree()
        assert tree["total"] == 1
        assert tree["domains"]["clinical"]["count"] == 1
        assert tree["domains"]["clinical"]["categories"] == {}

    @pytest.mark.asyncio
    async def test_get_category_tree_multilevel_dot_categories(self, adapter: SqliteCatalogAdapter) -> None:
        """Challenge 1.5: Multi-level dot categories.
        
        Examples from specification:
        - "clinical.pediatrics.allergy"
        - "navigation.insurance.claims"
        - Sibling: "navigation.insurance.billing"
        - Sibling: "navigation.appointments"
        - 4-level deep: "wellness.habits.sleep.hygiene"
        """
        agents = [
            _make_agent("ped-allergy", domain=AgentDomain.CLINICAL, category="clinical.pediatrics.allergy"),
            _make_agent("ins-claims", domain=AgentDomain.NAVIGATION, category="navigation.insurance.claims"),
            _make_agent("ins-billing", domain=AgentDomain.NAVIGATION, category="navigation.insurance.billing"),
            _make_agent("nav-appts", domain=AgentDomain.NAVIGATION, category="navigation.appointments"),
            _make_agent("deep-sleep", domain=AgentDomain.WELLNESS, category="wellness.habits.sleep.hygiene"),
        ]

        for a in agents:
            await adapter.index_agent(a)

        tree = await adapter.get_category_tree()
        assert tree["total"] == 5

        # 1. Clinical: pediatrics -> allergy
        clin = tree["domains"]["clinical"]
        assert clin["count"] == 1
        assert "pediatrics" in clin["categories"]
        assert clin["categories"]["pediatrics"]["count"] == 1
        ped_subs = clin["categories"]["pediatrics"]["subcategories"]
        assert "allergy" in ped_subs
        assert ped_subs["allergy"]["count"] == 1

        # 2. Navigation: insurance -> claims & billing, appointments
        nav = tree["domains"]["navigation"]
        assert nav["count"] == 3
        nav_cats = nav["categories"]
        assert "insurance" in nav_cats
        assert nav_cats["insurance"]["count"] == 2
        ins_subs = nav_cats["insurance"]["subcategories"]
        assert "claims" in ins_subs
        assert ins_subs["claims"]["count"] == 1
        assert "billing" in ins_subs
        assert ins_subs["billing"]["count"] == 1

        assert "appointments" in nav_cats
        assert nav_cats["appointments"]["count"] == 1
        assert nav_cats["appointments"]["subcategories"] == {}

        # 3. Wellness: habits -> sleep -> hygiene (4 levels total)
        well = tree["domains"]["wellness"]
        assert well["count"] == 1
        habits = well["categories"]["habits"]
        assert habits["count"] == 1
        sleep = habits["subcategories"]["sleep"]
        assert sleep["count"] == 1
        hygiene = sleep["subcategories"]["hygiene"]
        assert hygiene["count"] == 1

        # 4. Therapy and Education (empty canonical domains)
        assert tree["domains"]["therapy"]["count"] == 0
        assert tree["domains"]["therapy"]["categories"] == {}
        assert tree["domains"]["education"]["count"] == 0
        assert tree["domains"]["education"]["categories"] == {}

    @pytest.mark.asyncio
    async def test_get_category_tree_many_agents_stress(self, adapter: SqliteCatalogAdapter) -> None:
        """Challenge 1.6: Stress test with 60 agents across domains and subcategories."""
        categories = {
            AgentDomain.CLINICAL: ["clinical.pediatrics.allergy", "clinical.cardiology", "clinical.neurology.pediatric"],
            AgentDomain.THERAPY: ["therapy.cbt", "therapy.physical.rehab", "therapy.speech"],
            AgentDomain.WELLNESS: ["wellness.habits.nutrition", "wellness.habits.sleep", "wellness.mindfulness"],
            AgentDomain.NAVIGATION: ["navigation.insurance.claims", "navigation.insurance.preauth", "navigation.transport"],
            AgentDomain.EDUCATION: ["education.diabetes", "education.heart_disease", "education.asthma"],
        }
        domains = list(categories.keys())

        agent_count = 0
        for domain in domains:
            domain_cats = categories[domain]
            for i in range(12):  # 12 agents per domain = 60 total
                cat = domain_cats[i % len(domain_cats)]
                agent = _make_agent(
                    agent_id=f"stress-agent-{domain.value}-{i}",
                    domain=domain,
                    category=cat,
                    title=f"Stress Agent {domain.value} {i}",
                )
                await adapter.index_agent(agent)
                agent_count += 1

        assert agent_count == 60

        tree = await adapter.get_category_tree()
        assert tree["total"] == 60

        domain_sum = sum(tree["domains"][d.value]["count"] for d in domains)
        assert domain_sum == 60

        for domain in domains:
            dom_data = tree["domains"][domain.value]
            assert dom_data["count"] == 12
            # Sum of top-level categories within this domain must equal 12
            cat_sum = sum(cat_info["count"] for cat_info in dom_data["categories"].values())
            assert cat_sum == 12

    @pytest.mark.asyncio
    async def test_get_category_tree_domain_filter(self, adapter: SqliteCatalogAdapter) -> None:
        """Challenge 1.7: Category tree domain_filter parameter."""
        await adapter.index_agent(_make_agent("clin-1", domain=AgentDomain.CLINICAL, category="clinical.cardio"))
        await adapter.index_agent(_make_agent("clin-2", domain=AgentDomain.CLINICAL, category="clinical.neuro"))
        await adapter.index_agent(_make_agent("nav-1", domain=AgentDomain.NAVIGATION, category="navigation.insurance"))

        # Filter by clinical
        filtered = await adapter.get_category_tree(domain="clinical")
        assert filtered["total"] == 2
        assert list(filtered["domains"].keys()) == ["clinical"]
        assert filtered["domains"]["clinical"]["count"] == 2

        # Case-insensitive filtering
        filtered_caps = await adapter.get_category_tree(domain="CLINICAL")
        assert filtered_caps["total"] == 2
        assert "clinical" in filtered_caps["domains"]

        # Filter by domain with 0 agents
        filtered_empty = await adapter.get_category_tree(domain="education")
        assert filtered_empty["total"] == 0
        assert filtered_empty["domains"]["education"]["count"] == 0


# ==============================================================================
# 2. Factory & Settings Tests
# ==============================================================================

class TestFactoryAndSettingsEmpirical:
    """Empirical challenge for dynamic memory adapter factory and Settings integration."""

    def setup_method(self) -> None:
        reset_memory_ports()

    def teardown_method(self) -> None:
        reset_memory_ports()

    def test_factory_sqlite_backend_default(self, tmp_path: Path) -> None:
        """Challenge 2.1: get_memory_port() & get_catalog_port() with sqlite backend."""
        db_path = tmp_path / "factory_sqlite.db"
        settings = Settings(memory_backend="sqlite", catalog_db_path=db_path)

        mem = get_memory_port(settings)
        cat = get_catalog_port(settings)

        assert isinstance(mem, MemoryPort)
        assert isinstance(cat, CatalogPort)
        assert isinstance(mem, SqliteMemoryAdapter)
        assert isinstance(cat, SqliteCatalogAdapter)

    def test_factory_not_implemented_error_spector(self) -> None:
        """Challenge 2.2: MemoryPort succeeds for 'spector', CatalogPort raises NotImplementedError."""
        spector_settings = Settings(
            memory_backend="spector",
            spector_url="http://custom-spector:8080",
        )

        # get_memory_port succeeds and returns a MemoryPort with .store
        mem = get_memory_port(spector_settings)
        assert isinstance(mem, MemoryPort)
        assert hasattr(mem, "store")
        assert mem.store is not None

        # get_catalog_port continues to raise NotImplementedError
        with pytest.raises(NotImplementedError) as exc_cat:
            get_catalog_port(spector_settings)
        assert "spector" in str(exc_cat.value).lower()
        assert "http://custom-spector:8080" in str(exc_cat.value)

        # create_memory_port direct call succeeds and returns a MemoryPort with .store
        created_mem = create_memory_port(backend="spector")
        assert isinstance(created_mem, MemoryPort)
        assert hasattr(created_mem, "store")
        assert created_mem.store is not None

        # create_catalog_port direct call raises NotImplementedError
        with pytest.raises(NotImplementedError):
            create_catalog_port(backend="spector")

    def test_factory_not_implemented_error_postgres(self) -> None:
        """Challenge 2.3: NotImplementedError raised for 'postgres'."""
        postgres_settings = Settings(memory_backend="postgres")

        # get_memory_port
        with pytest.raises(NotImplementedError) as exc_mem:
            get_memory_port(postgres_settings)
        assert "postgres" in str(exc_mem.value).lower()

        # get_catalog_port
        with pytest.raises(NotImplementedError) as exc_cat:
            get_catalog_port(postgres_settings)
        assert "postgres" in str(exc_cat.value).lower()

        # create_memory_port direct call
        with pytest.raises(NotImplementedError):
            create_memory_port(backend="postgres")

        # create_catalog_port direct call
        with pytest.raises(NotImplementedError):
            create_catalog_port(backend="postgres")

    def test_factory_value_error_for_invalid_backends(self) -> None:
        """Challenge 2.4: ValueError raised for unrecognized/invalid backends."""
        invalid_backends = ["redis", "mongodb", "dynamodb", "", "   ", "cassandra", "memcached"]

        for backend in invalid_backends:
            inv_settings = Settings(memory_backend=backend)

            with pytest.raises(ValueError) as exc_mem:
                get_memory_port(inv_settings)
            assert "Unsupported memory backend" in str(exc_mem.value)

            with pytest.raises(ValueError) as exc_cat:
                get_catalog_port(inv_settings)
            assert "Unsupported catalog backend" in str(exc_cat.value)

            with pytest.raises(ValueError):
                create_memory_port(backend=backend)

            with pytest.raises(ValueError):
                create_catalog_port(backend=backend)

    def test_factory_reset_memory_ports_clears_singletons(self, tmp_path: Path) -> None:
        """Challenge 2.5: reset_memory_ports() clears cached singletons."""
        settings_1 = Settings(catalog_db_path=tmp_path / "db1.db")
        m1 = get_memory_port(settings_1)
        c1 = get_catalog_port(settings_1)

        # Same call returns identical singleton instances
        assert get_memory_port() is m1
        assert get_catalog_port() is c1

        # Reset singletons
        reset_memory_ports()

        # New call creates distinct new instances
        settings_2 = Settings(catalog_db_path=tmp_path / "db2.db")
        m2 = get_memory_port(settings_2)
        c2 = get_catalog_port(settings_2)

        assert m2 is not m1
        assert c2 is not c1

    def test_factory_explicit_set_memory_and_catalog_ports(self, tmp_path: Path) -> None:
        """Challenge 2.6: set_memory_port() and set_catalog_port() overrides."""
        mem_custom = create_memory_port(db_path=tmp_path / "custom_m.db")
        cat_custom = create_catalog_port(db_path=tmp_path / "custom_c.db")

        set_memory_port(mem_custom)
        set_catalog_port(cat_custom)

        assert get_memory_port() is mem_custom
        assert get_catalog_port() is cat_custom

        # Clearing them with None
        set_memory_port(None)
        set_catalog_port(None)

        m_new = get_memory_port()
        c_new = get_catalog_port()
        assert m_new is not mem_custom
        assert c_new is not cat_custom


# ==============================================================================
# 3. Concurrency & Database Locking Tests
# ==============================================================================

class TestConcurrencyAndDatabaseLockingEmpirical:
    """Empirical challenge for concurrency, race conditions, and SQLite locking issues."""

    @pytest.mark.asyncio
    async def test_concurrent_catalog_index_and_search_single_adapter(self, tmp_path: Path) -> None:
        """Challenge 3.1: 40 concurrent index and search tasks using asyncio.gather().
        
        Tests that async lock and transaction handling prevent 'database is locked' errors.
        """
        db_file = tmp_path / "concurrent_catalog.db"
        adapter = SqliteCatalogAdapter(db_path=db_file)

        async def writer(i: int):
            agent = _make_agent(
                agent_id=f"agent-conc-{i}",
                domain=AgentDomain.NAVIGATION if i % 2 == 0 else AgentDomain.CLINICAL,
                category="navigation.insurance" if i % 2 == 0 else "clinical.cardiology",
                title=f"Concurrent Agent {i}",
                tags=["concurrent", f"tag-{i % 5}"],
            )
            await adapter.index_agent(agent)

        async def reader(i: int):
            # Interleaved searches with full text and category tree
            if i % 3 == 0:
                return await adapter.search_agents(query="Concurrent")
            elif i % 3 == 1:
                return await adapter.search_agents(domain="navigation")
            else:
                return await adapter.get_category_tree()

        # Run 20 writers and 20 readers concurrently
        tasks = []
        for i in range(20):
            tasks.append(writer(i))
            tasks.append(reader(i))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check that no exceptions (like OperationalError: database is locked) were raised
        for r in results:
            if isinstance(r, Exception):
                pytest.fail(f"Concurrent catalog task raised exception: {r}")

        # Verify all 20 agents were properly indexed
        count = await adapter.count_agents()
        assert count == 20

        tree = await adapter.get_category_tree()
        assert tree["total"] == 20
        assert tree["domains"]["navigation"]["count"] == 10
        assert tree["domains"]["clinical"]["count"] == 10

        await adapter.close()

    @pytest.mark.asyncio
    async def test_concurrent_memory_read_write_operations(self, tmp_path: Path) -> None:
        """Challenge 3.2: 40 concurrent memory operations (remember, recall, reinforce, forget)."""
        db_file = tmp_path / "concurrent_memory.db"
        adapter = SqliteMemoryAdapter(db_path=db_file)

        async def worker(i: int):
            ns = f"user_{i % 4}"
            key = f"key_{i}"
            # 1. remember
            await adapter.remember(
                key=key,
                value=f"Concurrent memory payload {i} with vital details",
                tier=MemoryTier.SEMANTIC if i % 2 == 0 else MemoryTier.EPISODIC,
                namespace=ns,
            )
            # 2. recall
            results = await adapter.recall("Concurrent", namespace=ns)
            assert len(results) >= 1

            # 3. reinforce
            await adapter.reinforce(key, namespace=ns, delta=0.2)

            # 4. get
            fetched = await adapter.get(key, namespace=ns)
            assert fetched is not None
            assert fetched["salience"] > 1.0

        tasks = [worker(i) for i in range(40)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                pytest.fail(f"Concurrent memory worker failed with exception: {r}")

        # Total memories across 4 namespaces should be 40
        all_recalled = await adapter.recall("Concurrent", namespace="user_0", limit=100)
        assert len(all_recalled) == 10  # 40 / 4 namespaces = 10 per namespace

        await adapter.close()

    @pytest.mark.asyncio
    async def test_concurrent_multi_adapter_file_access(self, tmp_path: Path) -> None:
        """Challenge 3.3: Multiple separate adapter instances connecting to the same SQLite file.
        
        Simulates multi-process/multi-worker concurrency.
        Verifies WAL mode (PRAGMA journal_mode = WAL) and busy timeout (PRAGMA busy_timeout = 10000)
        prevent 'database is locked' errors across distinct database connections.
        """
        shared_db = tmp_path / "shared_wal_test.db"

        # Create 5 separate catalog adapters and 5 separate memory adapters pointing to same file
        catalog_adapters = [SqliteCatalogAdapter(db_path=shared_db) for _ in range(5)]
        memory_adapters = [SqliteMemoryAdapter(db_path=shared_db) for _ in range(5)]

        async def catalog_worker(adapter_idx: int, task_idx: int):
            ad = catalog_adapters[adapter_idx]
            agent = _make_agent(
                agent_id=f"multi-agent-{adapter_idx}-{task_idx}",
                domain=AgentDomain.WELLNESS,
                category="wellness.multi",
                title=f"Multi Adapter Agent {adapter_idx} {task_idx}",
            )
            await ad.index_agent(agent)
            found = await ad.search_agents(query="Multi")
            assert len(found) >= 1

        async def memory_worker(adapter_idx: int, task_idx: int):
            ad = memory_adapters[adapter_idx]
            key = f"multi_key_{adapter_idx}_{task_idx}"
            await ad.remember(key, f"Multi adapter memory {task_idx}", MemoryTier.WORKING, namespace="shared_ns")
            recalled = await ad.recall(f"memory {task_idx}", namespace="shared_ns")
            assert len(recalled) >= 1

        tasks = []
        for i in range(5):
            for j in range(6):  # 5 * 6 = 30 catalog tasks, 30 memory tasks = 60 concurrent tasks
                tasks.append(catalog_worker(i, j))
                tasks.append(memory_worker(i, j))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                pytest.fail(f"Multi-adapter concurrency failed with exception: {r}")

        # Verification via adapter 0
        final_agents_count = await catalog_adapters[0].count_agents()
        assert final_agents_count == 30

        tree = await catalog_adapters[0].get_category_tree()
        assert tree["total"] == 30
        assert tree["domains"]["wellness"]["count"] == 30

        # Close all adapters
        for ad in catalog_adapters:
            await ad.close()
        for ad in memory_adapters:
            await ad.close()
