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

"""SQLite FTS5 Catalog Adapter Test Suite.
Scope:
1. FTS5 Porter stemming:
   - Singular documents ("copay", "benefit", "prescription") queried by plurals ("copays", "benefits", "prescriptions")
   - Plural documents queried by singulars
   - Irregular plurals and healthcare domain terminology
2. Malformed/adversarial queries:
   - Unclosed double quotes (`"copay`)
   - Syntax colons (`tag:health`)
   - Boolean keywords (`AND OR NOT NEAR`)
   - SQL injection payloads (`' OR 1=1 --`)
   - Punctuation spam (`:::???***`)
   - Hyphen variations, whitespace, null characters, unicode, and extreme query lengths
3. Salience reinforcement edge cases:
   - Positive delta reinforcement and access count increments
   - Negative delta clamping to 0.0
   - Large deltas (1e6)
   - Zero delta behavior
   - Non-existent key reinforcement
   - Salience-weighted ranking in recall
   - Upsert salience preservation
   - Invalid float (NaN) delta handling
4. Namespace isolation & security:
   - Independent namespace separation (read, write, delete, salience)
   - Adversarial delimiter injection: colon collisions across `namespace` and `key`
     (e.g., `namespace="user:1", key="records"` vs `namespace="user", key="1:records"`)
5. Catalog tag filtering post-limit edge case:
   - Post-SQL LIMIT filtering behavior for tags in `search_agents` and `search_skills`
"""

import asyncio
import math
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

from carefold.memory.adapters.sqlite.catalog_adapter import (
    SqliteCatalogAdapter,
    build_category_tree_from_rows,
)
from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
from carefold.memory.ports.memory_port import MemoryTier
from carefold.schemas.manifest import (
    AgentDomain,
    AgentManifest,
    AgentMaturity,
    RiskClass,
    SkillManifest,
)


def _make_agent(
    agent_id: str,
    title: str = "Test Agent",
    description: str = "Test Description",
    domain: AgentDomain = AgentDomain.WELLNESS,
    category: str = "wellness.general",
    tags: Optional[List[str]] = None,
    hidden: bool = False,
    persona: str = "Test persona instructions",
) -> AgentManifest:
    return AgentManifest(
        id=agent_id,
        title=title,
        version="0.1.0",
        domain=domain,
        category=category,
        risk_class=RiskClass.WELLNESS,
        tags=tags or ["test"],
        description=description,
        hidden=hidden,
        persona=persona,
    )


def _make_skill(
    skill_id: str,
    name: str = "Test Skill",
    description: str = "Test Description",
    domain: AgentDomain = AgentDomain.NAVIGATION,
    category: str = "navigation.claims",
    tags: Optional[List[str]] = None,
    instructions: str = "Test instructions",
) -> SkillManifest:
    return SkillManifest(
        id=skill_id,
        name=name,
        version="0.1.0",
        domain=domain,
        category=category,
        risk_class=RiskClass.WELLNESS,
        tags=tags or ["test"],
        description=description,
        instructions=instructions,
    )


# ==============================================================================
# 1. FTS5 Porter Stemming Tests
# ==============================================================================

class TestFTS5PorterStemming:
    """Stress-tests SQLite FTS5 Porter stemming across singular/plural and domain terms."""

    @pytest.fixture
    async def memory_adapter(self, tmp_path: Path):
        db_file = tmp_path / "stemming_memory.db"
        adapter = SqliteMemoryAdapter(db_path=db_file)
        yield adapter
        await adapter.close()

    @pytest.fixture
    async def catalog_adapter(self, tmp_path: Path):
        db_file = tmp_path / "stemming_catalog.db"
        adapter = SqliteCatalogAdapter(db_path=db_file)
        yield adapter
        await adapter.close()

    @pytest.mark.asyncio
    async def test_memory_adapter_plural_queries_match_singular_documents(
        self, memory_adapter: SqliteMemoryAdapter
    ) -> None:
        """Challenge: Document has strictly singular words ('copay', 'benefit', 'prescription').
        Queries with plural forms ('copays', 'benefits', 'prescriptions') must match via Porter stemmer.
        """
        await memory_adapter.remember(
            key="copay_policy",
            value="The patient has a fixed copay for primary care visits.",
            tier=MemoryTier.SEMANTIC,
            namespace="tenant_rx",
        )
        await memory_adapter.remember(
            key="benefit_summary",
            value="Annual maximum healthcare benefit details and exclusions.",
            tier=MemoryTier.SEMANTIC,
            namespace="tenant_rx",
        )
        await memory_adapter.remember(
            key="rx_order",
            value="Doctor issued a new medication prescription yesterday.",
            tier=MemoryTier.EPISODIC,
            namespace="tenant_rx",
        )

        # 1. 'copays' matches 'copay'
        copays_match = await memory_adapter.recall("copays", namespace="tenant_rx")
        assert len(copays_match) == 1
        assert copays_match[0]["key"] == "copay_policy"

        # 2. 'benefits' matches 'benefit'
        benefits_match = await memory_adapter.recall("benefits", namespace="tenant_rx")
        assert len(benefits_match) == 1
        assert benefits_match[0]["key"] == "benefit_summary"

        # 3. 'prescriptions' matches 'prescription'
        rx_match = await memory_adapter.recall("prescriptions", namespace="tenant_rx")
        assert len(rx_match) == 1
        assert rx_match[0]["key"] == "rx_order"

    @pytest.mark.asyncio
    async def test_memory_adapter_singular_queries_match_plural_documents(
        self, memory_adapter: SqliteMemoryAdapter
    ) -> None:
        """Challenge: Document has plural words ('copays', 'benefits', 'prescriptions').
        Queries with singular forms must match via Porter stemmer.
        """
        await memory_adapter.remember(
            key="plural_doc",
            value="Detailed breakdown of tiered copays, pharmacy benefits, and specialty prescriptions.",
            tier=MemoryTier.SEMANTIC,
            namespace="tenant_plural",
        )

        for singular in ["copay", "benefit", "prescription"]:
            matched = await memory_adapter.recall(singular, namespace="tenant_plural")
            assert len(matched) == 1, f"Expected singular query '{singular}' to match plural document"
            assert matched[0]["key"] == "plural_doc"

    @pytest.mark.asyncio
    async def test_catalog_adapter_stemming_verification(
        self, catalog_adapter: SqliteCatalogAdapter
    ) -> None:
        """Challenge: Catalog manifests with singular descriptions match plural queries."""
        agent1 = _make_agent(
            agent_id="copay-advisor",
            title="Copay Advisor",
            description="Clarifies each copay requirement across in-network clinics.",
            domain=AgentDomain.NAVIGATION,
            category="navigation.copay",
            tags=["copay"],
        )
        agent2 = _make_agent(
            agent_id="benefit-navigator",
            title="Benefit Navigator",
            description="Reviews every plan benefit and deductible status.",
            domain=AgentDomain.NAVIGATION,
            category="navigation.insurance",
            tags=["benefit"],
        )
        agent3 = _make_agent(
            agent_id="prescription-steward",
            title="Prescription Steward",
            description="Refills and tracks each active medication prescription.",
            domain=AgentDomain.WELLNESS,
            category="wellness.medications",
            tags=["prescription"],
        )

        await catalog_adapter.index_agent(agent1)
        await catalog_adapter.index_agent(agent2)
        await catalog_adapter.index_agent(agent3)

        # Plural queries
        copays_res = await catalog_adapter.search_agents(query="copays")
        assert any(a.id == "copay-advisor" for a in copays_res)

        benefits_res = await catalog_adapter.search_agents(query="benefits")
        assert any(a.id == "benefit-navigator" for a in benefits_res)

        rx_res = await catalog_adapter.search_agents(query="prescriptions")
        assert any(a.id == "prescription-steward" for a in rx_res)

    @pytest.mark.asyncio
    async def test_stemming_irregular_plurals_behavior(
        self, memory_adapter: SqliteMemoryAdapter
    ) -> None:
        """Challenge: Test Porter stemmer behavior on English irregular plurals.
        Porter stemmer stems:
        - baby/babies -> babi (matches)
        - child/children -> children vs child (fails)
        - diagnosis/diagnoses -> diagnosi vs diagnos (fails)
        """
        await memory_adapter.remember("rec_baby", "Pediatric wellness for babies", MemoryTier.SEMANTIC, "ns_irreg")
        await memory_adapter.remember("rec_diag", "Patient clinical diagnoses", MemoryTier.SEMANTIC, "ns_irreg")

        # 'baby' -> 'babies' (Porter stems both to 'babi')
        baby_res = await memory_adapter.recall("baby", namespace="ns_irreg")
        assert len(baby_res) == 1
        assert baby_res[0]["key"] == "rec_baby"

        # 'diagnosis' vs 'diagnoses' stems to 'diagnosi' vs 'diagnos' (known Porter limitation)
        diag_res = await memory_adapter.recall("diagnosis", namespace="ns_irreg")
        # Documents known boundary condition: diagnosis does not stem to diagnoses under Porter
        assert len(diag_res) == 0


# ==============================================================================
# 2. Malformed / Adversarial Query Tests
# ==============================================================================

class TestAdversarialAndMalformedQueries:
    """Stress-tests SQLite FTS5 query sanitization against crashes, injection, and edge cases."""

    @pytest.fixture
    async def memory_adapter(self, tmp_path: Path):
        db_file = tmp_path / "adv_memory.db"
        adapter = SqliteMemoryAdapter(db_path=db_file)
        yield adapter
        await adapter.close()

    @pytest.fixture
    async def catalog_adapter(self, tmp_path: Path):
        db_file = tmp_path / "adv_catalog.db"
        adapter = SqliteCatalogAdapter(db_path=db_file)
        yield adapter
        await adapter.close()

    @pytest.mark.asyncio
    async def test_queries_do_not_crash(
        self,
        memory_adapter: SqliteMemoryAdapter,
        catalog_adapter: SqliteCatalogAdapter,
    ) -> None:
        """Challenge: Verify that malicious, malformed, punctuation-dense, and injection queries
        never raise sqlite3.OperationalError or break FTS5 MATCH evaluation.
        """
        # Populate adapters with baseline test data
        await memory_adapter.remember(
            key="patient_health_note",
            value="Patient health record discussing copay, benefit, and insurance details.",
            tier=MemoryTier.SEMANTIC,
            namespace="sec_ns",
        )
        agent = _make_agent(
            agent_id="sec-agent",
            title="Security Test Agent",
            description="Agent for evaluating security queries with health copay benefits.",
            domain=AgentDomain.WELLNESS,
            category="wellness.security",
            tags=["health", "copay"],
        )
        await catalog_adapter.index_agent(agent)

        adversarial_payloads = [
            # 1. Unclosed double quotes
            '"copay',
            'copay"',
            '"""',
            '"copay"benefit"',
            '""copay""',
            # 2. Syntax colons
            'tag:health',
            'category:wellness.security',
            'domain:clinical',
            'content:patient',
            'id:sec-agent',
            ':::',
            'tag::health',
            # 3. Boolean keywords
            'AND OR NOT NEAR',
            'AND',
            'OR',
            'NOT',
            'NEAR',
            'copay AND benefit',
            'copay OR NOT health',
            'NEAR(copay, benefit, 5)',
            'AND AND AND',
            # 4. SQL injection payloads
            "' OR 1=1 --",
            "'; DROP TABLE memories; --",
            "'; DROP TABLE agents; --",
            "1' UNION SELECT 1,2,3,4,5,6,7,8,9,10,11 --",
            "' OR ''='",
            "admin'--",
            # 5. Punctuation spam and wildcards
            ':::???***',
            '***',
            '*',
            '???',
            '!@#$%^&*()_+{}|:"<>?[];,./`~',
            '-',
            '--',
            '---',
            '----copay----',
            # 6. Whitespace and null characters
            '',
            ' ',
            '   \t\r\n   ',
            '\x00null',
            # 7. Extreme payloads
            'copay ' * 200,
            'a' * 5000,
            # 8. Unicode, accents, emojis
            'médicament et santé résumé',
            '🩺 💊 🩹',
        ]

        for payload in adversarial_payloads:
            try:
                mem_res = await memory_adapter.recall(query=payload, namespace="sec_ns")
                assert isinstance(mem_res, list)
            except Exception as exc:
                pytest.fail(f"MemoryAdapter crashed on payload {payload!r}: {type(exc).__name__}: {exc}")

            try:
                cat_res = await catalog_adapter.search_agents(query=payload)
                assert isinstance(cat_res, list)
            except Exception as exc:
                pytest.fail(f"CatalogAdapter crashed on payload {payload!r}: {type(exc).__name__}: {exc}")

    @pytest.mark.asyncio
    async def test_punctuation_only_query_behavior(
        self,
        memory_adapter: SqliteMemoryAdapter,
        catalog_adapter: SqliteCatalogAdapter,
    ) -> None:
        """Challenge: When a query contains only punctuation (e.g. ':::???***'),
        sanitization strips all tokens to empty string.
        Verify:
        - MemoryAdapter treats empty sanitized query as a default browse/recency query.
        - CatalogAdapter returns all catalog agents ordered by title.
        """
        await memory_adapter.remember("k1", "Val 1", MemoryTier.WORKING, "punc_ns")
        await memory_adapter.remember("k2", "Val 2", MemoryTier.WORKING, "punc_ns")

        agent1 = _make_agent("a1", title="A Agent")
        agent2 = _make_agent("b1", title="B Agent")
        await catalog_adapter.index_agent(agent1)
        await catalog_adapter.index_agent(agent2)

        # Query with pure punctuation
        mem_results = await memory_adapter.recall(":::???***", namespace="punc_ns")
        assert len(mem_results) == 2

        cat_results = await catalog_adapter.search_agents(query=":::???***")
        assert len(cat_results) == 2
        assert cat_results[0].title == "A Agent"
        assert cat_results[1].title == "B Agent"


# ==============================================================================
# 3. Salience Reinforcement Edge Cases
# ==============================================================================

class TestSalienceReinforcementEdgeCases:
    """Stress-tests salience reinforcement math, boundary clamping, access counts, and ranking."""

    @pytest.fixture
    async def memory_adapter(self, tmp_path: Path):
        db_file = tmp_path / "salience_test.db"
        adapter = SqliteMemoryAdapter(db_path=db_file)
        yield adapter
        await adapter.close()

    @pytest.mark.asyncio
    async def test_positive_reinforcement_and_access_count(
        self, memory_adapter: SqliteMemoryAdapter
    ) -> None:
        """Challenge: Reinforcing with positive delta increases salience, increments access_count,
        and records last_accessed_at timestamp.
        """
        await memory_adapter.remember("med_1", "Lisinopril 10mg daily", MemoryTier.SEMANTIC, "patient_a")
        initial = await memory_adapter.get("med_1", "patient_a")
        assert initial is not None
        assert initial["salience"] == 1.0
        assert initial["access_count"] == 0
        assert initial["last_accessed_at"] is None

        # Reinforce 3 times by 0.2
        for _ in range(3):
            await memory_adapter.reinforce("med_1", "patient_a", delta=0.2)

        updated = await memory_adapter.get("med_1", "patient_a")
        assert updated is not None
        assert math.isclose(updated["salience"], 1.6, rel_tol=1e-5)
        assert updated["access_count"] == 3
        assert updated["last_accessed_at"] is not None

    @pytest.mark.asyncio
    async def test_negative_delta_clamping_to_zero(
        self, memory_adapter: SqliteMemoryAdapter
    ) -> None:
        """Challenge: Negative deltas that would drop salience below 0.0 must clamp strictly to 0.0."""
        await memory_adapter.remember("temp_note", "Temporary note to decay", MemoryTier.WORKING, "patient_a")

        # Moderate negative delta: 1.0 - 0.4 = 0.6
        await memory_adapter.reinforce("temp_note", "patient_a", delta=-0.4)
        m1 = await memory_adapter.get("temp_note", "patient_a")
        assert m1 is not None
        assert math.isclose(m1["salience"], 0.6, rel_tol=1e-5)
        assert m1["access_count"] == 1

        # Excessive negative delta: 0.6 - 100.0 must clamp to 0.0 (never negative)
        await memory_adapter.reinforce("temp_note", "patient_a", delta=-100.0)
        m2 = await memory_adapter.get("temp_note", "patient_a")
        assert m2 is not None
        assert m2["salience"] == 0.0
        assert m2["access_count"] == 2

    @pytest.mark.asyncio
    async def test_large_positive_delta(self, memory_adapter: SqliteMemoryAdapter) -> None:
        """Challenge: Large delta values (1,000,000.0) should apply without float overflow."""
        await memory_adapter.remember("critical_alert", "Severe anaphylaxis warning", MemoryTier.SEMANTIC, "patient_a")
        await memory_adapter.reinforce("critical_alert", "patient_a", delta=1_000_000.0)

        alert = await memory_adapter.get("critical_alert", "patient_a")
        assert alert is not None
        assert alert["salience"] == 1_000_001.0
        assert alert["access_count"] == 1

    @pytest.mark.asyncio
    async def test_zero_delta_behavior(self, memory_adapter: SqliteMemoryAdapter) -> None:
        """Challenge: Delta=0.0 leaves salience unchanged, but increments access_count."""
        await memory_adapter.remember("zero_key", "Touch record without boosting", MemoryTier.EPISODIC, "patient_a")
        await memory_adapter.reinforce("zero_key", "patient_a", delta=0.0)

        rec = await memory_adapter.get("zero_key", "patient_a")
        assert rec is not None
        assert rec["salience"] == 1.0
        assert rec["access_count"] == 1
        assert rec["last_accessed_at"] is not None

    @pytest.mark.asyncio
    async def test_reinforce_non_existent_key(self, memory_adapter: SqliteMemoryAdapter) -> None:
        """Challenge: Calling reinforce on a key that does not exist must complete without error."""
        await memory_adapter.reinforce("non_existent_key", "patient_a", delta=0.5)
        assert await memory_adapter.get("non_existent_key", "patient_a") is None

    @pytest.mark.asyncio
    async def test_salience_weighting_affects_recall_ranking(
        self, memory_adapter: SqliteMemoryAdapter
    ) -> None:
        """Challenge: Two records match the exact same query with identical text BM25 relevance.
        The record with higher salience must be ranked first.
        """
        await memory_adapter.remember("doc_low", "Standard clinical guidelines for hypertension", MemoryTier.SEMANTIC, "ns_rank")
        await memory_adapter.remember("doc_high", "Standard clinical guidelines for hypertension", MemoryTier.SEMANTIC, "ns_rank")

        # Boost doc_high salience to 3.0
        await memory_adapter.reinforce("doc_high", "ns_rank", delta=2.0)

        results = await memory_adapter.recall("hypertension", namespace="ns_rank")
        assert len(results) == 2
        assert results[0]["key"] == "doc_high"
        assert results[1]["key"] == "doc_low"
        assert results[0]["score"] > results[1]["score"]

    @pytest.mark.asyncio
    async def test_upsert_preserves_salience_and_access_count(
        self, memory_adapter: SqliteMemoryAdapter
    ) -> None:
        """Challenge: Updating an existing memory via remember() must NOT reset its salience
        or access_count back to defaults (1.0 and 0).
        """
        await memory_adapter.remember("key_up", "Initial value", MemoryTier.WORKING, "ns_up")
        await memory_adapter.reinforce("key_up", "ns_up", delta=0.8)

        before = await memory_adapter.get("key_up", "ns_up")
        assert before is not None
        assert math.isclose(before["salience"], 1.8, rel_tol=1e-5)
        assert before["access_count"] == 1

        # Upsert with new value
        await memory_adapter.remember("key_up", "Updated value", MemoryTier.WORKING, "ns_up")

        after = await memory_adapter.get("key_up", "ns_up")
        assert after is not None
        assert after["value"] == "Updated value"
        assert math.isclose(after["salience"], 1.8, rel_tol=1e-5), "Salience was reset on upsert!"
        assert after["access_count"] == 1, "Access count was reset on upsert!"

    @pytest.mark.asyncio
    async def test_reinforce_non_finite_float_raises_value_error(
        self, memory_adapter: SqliteMemoryAdapter
    ) -> None:
        """Challenge: Calling reinforce with NaN or Inf delta must raise ValueError to prevent SQLite corruption."""
        await memory_adapter.remember("key_finite", "Finite test", MemoryTier.WORKING, "ns_finite")
        for bad_delta in [float("nan"), float("inf"), float("-inf")]:
            with pytest.raises(ValueError) as exc:
                await memory_adapter.reinforce("key_finite", "ns_finite", delta=bad_delta)
            assert "finite" in str(exc.value)


# ==============================================================================
# 4. Namespace Isolation & Delimiter Collision Tests
# ==============================================================================

class TestNamespaceIsolation:
    """Stress-tests memory isolation between namespaces and adversarial delimiter collisions."""

    @pytest.fixture
    async def memory_adapter(self, tmp_path: Path):
        db_file = tmp_path / "ns_test.db"
        adapter = SqliteMemoryAdapter(db_path=db_file)
        yield adapter
        await adapter.close()

    @pytest.mark.asyncio
    async def test_standard_namespace_isolation(self, memory_adapter: SqliteMemoryAdapter) -> None:
        """Challenge: Independent namespaces (e.g. 'tenant_alice' vs 'tenant_bob') must never
        share or leak memories across recall(), get(), forget(), or reinforce().
        """
        # Alice and Bob store data with identical key
        await memory_adapter.remember(
            key="shared_key_name",
            value="Alice confidential diagnosis: Asthma",
            tier=MemoryTier.SEMANTIC,
            namespace="tenant_alice",
        )
        await memory_adapter.remember(
            key="shared_key_name",
            value="Bob confidential diagnosis: Diabetes",
            tier=MemoryTier.SEMANTIC,
            namespace="tenant_bob",
        )

        # 1. Recall isolation
        alice_recalled = await memory_adapter.recall("diagnosis", namespace="tenant_alice")
        assert len(alice_recalled) == 1
        assert "Asthma" in alice_recalled[0]["value"]
        assert "Diabetes" not in alice_recalled[0]["value"]

        bob_recalled = await memory_adapter.recall("diagnosis", namespace="tenant_bob")
        assert len(bob_recalled) == 1
        assert "Diabetes" in bob_recalled[0]["value"]
        assert "Asthma" not in bob_recalled[0]["value"]

        # 2. Get isolation
        alice_get = await memory_adapter.get("shared_key_name", namespace="tenant_alice")
        assert alice_get is not None
        assert "Asthma" in alice_get["value"]

        bob_get = await memory_adapter.get("shared_key_name", namespace="tenant_bob")
        assert bob_get is not None
        assert "Diabetes" in bob_get["value"]

        # 3. Third party namespace sees nothing
        charlie_get = await memory_adapter.get("shared_key_name", namespace="tenant_charlie")
        assert charlie_get is None

        # 4. Forget in Alice does not affect Bob
        assert await memory_adapter.forget("shared_key_name", namespace="tenant_alice") is True
        assert await memory_adapter.get("shared_key_name", namespace="tenant_alice") is None
        assert await memory_adapter.get("shared_key_name", namespace="tenant_bob") is not None

    @pytest.mark.asyncio
    async def test_colon_delimiter_collision_vulnerability(
        self, memory_adapter: SqliteMemoryAdapter
    ) -> None:
        """CRITICAL CHALLENGE:
        SqliteMemoryAdapter computes memory primary key as `mem_id = f"{namespace}:{key}"`.
        Because colons are standard in healthcare namespaces (e.g. 'user:101', 'agent:visit-steward'),
        a malicious or colliding tenant can forge IDs across namespace boundaries:
        - Tenant 1: namespace = "user:1", key = "phi_data" -> id = "user:1:phi_data"
        - Tenant 2: namespace = "user", key = "1:phi_data" -> id = "user:1:phi_data"

        This test checks whether Tenant 2 can leak Tenant 1's data.
        """
        # Tenant 1 stores sensitive medical data in hierarchical namespace 'user:1'
        await memory_adapter.remember(
            key="phi_data",
            value="CONFIDENTIAL PATIENT 1 MEDICAL HISTORY: Oncology Patient",
            tier=MemoryTier.SEMANTIC,
            namespace="user:1",
        )

        # Tenant 2 is in namespace 'user', and accesses key '1:phi_data'
        leaked_record = await memory_adapter.get("1:phi_data", namespace="user")

        # Isolation verification: Tenant 2 cannot access Tenant 1's PHI
        assert leaked_record is None, "Isolation failed: Tenant 2 was able to read Tenant 1's PHI"

    @pytest.mark.asyncio
    async def test_colon_delimiter_overwrite_and_deletion_vulnerability(
        self, memory_adapter: SqliteMemoryAdapter
    ) -> None:
        """CRITICAL CHALLENGE:
        Verify that Tenant 2 CANNOT overwrite, delete, or alter the salience of Tenant 1's records
        due to delimiter isolation and composite key filtering.
        """
        # 1. Tenant 1 stores vital record
        await memory_adapter.remember(
            key="vitals",
            value="Patient 1 Vitals: BP 120/80, Pulse 72",
            tier=MemoryTier.EPISODIC,
            namespace="clinic:patient_100",
        )

        # 2. Tenant 2 in 'clinic' namespace modifies 'patient_100:vitals'
        await memory_adapter.reinforce("patient_100:vitals", namespace="clinic", delta=5.0)
        t1_rec = await memory_adapter.get("vitals", namespace="clinic:patient_100")
        assert t1_rec is not None
        assert t1_rec["salience"] == 1.0, "Tenant 2 must NOT tamper with Tenant 1 salience!"

        # 3. Tenant 2 overwrites 'patient_100:vitals' in 'clinic' namespace
        await memory_adapter.remember(
            key="patient_100:vitals",
            value="CORRUPTED DATA INJECTED BY TENANT 2",
            tier=MemoryTier.EPISODIC,
            namespace="clinic",
        )
        t1_overwritten = await memory_adapter.get("vitals", namespace="clinic:patient_100")
        assert t1_overwritten is not None
        assert "Patient 1 Vitals" in str(t1_overwritten["value"]), "Tenant 2 must NOT overwrite Tenant 1 data!"
        assert "CORRUPTED DATA INJECTED" not in str(t1_overwritten["value"])

        # 4. Tenant 2 deletes 'patient_100:vitals' in 'clinic' namespace
        deleted = await memory_adapter.forget("patient_100:vitals", namespace="clinic")
        assert deleted is True, "Tenant 2 deleted its own record"
        t1_after_delete = await memory_adapter.get("vitals", namespace="clinic:patient_100")
        assert t1_after_delete is not None, "Tenant 1 record must NOT be destroyed by Tenant 2 forget() call!"


# ==============================================================================
# 5. Catalog Post-Limit Tag Filtering Edge Case
# ==============================================================================

class TestCatalogPostLimitTagFiltering:
    """Stress-tests tag filtering interaction with SQL LIMIT in SqliteCatalogAdapter."""

    @pytest.fixture
    async def catalog_adapter(self, tmp_path: Path):
        db_file = tmp_path / "tag_limit_test.db"
        adapter = SqliteCatalogAdapter(db_path=db_file)
        yield adapter
        await adapter.close()

    @pytest.mark.asyncio
    async def test_agent_tag_filtering_post_sql_limit_bug(
        self, catalog_adapter: SqliteCatalogAdapter
    ) -> None:
        """CHALLENGE / FINDING:
        In SqliteCatalogAdapter.search_agents, SQL executes `LIMIT ? OFFSET ?` first,
        and THEN Python filters `[m for m in manifests if any(t in requested_tags ...)]`.
        
        If 15 agents exist where agents 0..9 do NOT have tag 'critical',
        and agents 10..14 DO have tag 'critical':
        A query with `limit=5, tags=['critical']` queries SQL for first 5 agents (0..4),
        filters in Python, and returns 0 agents, even though 5 matching agents exist!
        """
        # Insert 15 agents ordered alphabetically by title
        for i in range(15):
            has_tag = ["critical"] if i >= 10 else ["standard"]
            agent = _make_agent(
                agent_id=f"agent_{i:02d}",
                title=f"Agent {i:02d}",
                tags=has_tag,
            )
            await catalog_adapter.index_agent(agent)

        # Search for tag 'critical' with limit 5
        results = await catalog_adapter.search_agents(limit=5, tags=["critical"])

        # Pre-limit SQL tag filtering correctly returns all 5 matching agents
        assert len(results) == 5, f"Expected pre-limit SQL tag filtering to return 5 results, got {len(results)}"
        assert all("critical" in a.tags for a in results)

    @pytest.mark.asyncio
    async def test_skill_tag_filtering_post_sql_limit_bug(
        self, catalog_adapter: SqliteCatalogAdapter
    ) -> None:
        """CHALLENGE / FINDING:
        Verify that SQL executes tag filtering before applying LIMIT ? OFFSET ?,
        ensuring skills matching tags beyond the initial window are discovered.
        """
        # Insert 15 skills ordered alphabetically by name
        for i in range(15):
            has_tag = ["critical"] if i >= 10 else ["standard"]
            skill = _make_skill(
                skill_id=f"skill_{i:02d}",
                name=f"Skill {i:02d}",
                tags=has_tag,
            )
            await catalog_adapter.index_skill(skill)

        # Search for tag 'critical' with limit 5
        results = await catalog_adapter.search_skills(limit=5, tags=["critical"])

        # Pre-limit SQL tag filtering correctly returns all 5 matching skills
        assert len(results) == 5, f"Expected pre-limit SQL tag filtering to return 5 results, got {len(results)}"
        assert all("critical" in s.tags for s in results)


# ==============================================================================
# 6. Category Tree Construction Edge Cases
# ==============================================================================

class TestCategoryTreeConstruction:
    """Stress-tests category tree generation across deep nesting, empty, and duplicate paths."""

    @pytest.fixture
    async def catalog_adapter(self, tmp_path: Path):
        db_file = tmp_path / "cat_tree_test.db"
        adapter = SqliteCatalogAdapter(db_path=db_file)
        yield adapter
        await adapter.close()

    @pytest.mark.asyncio
    async def test_deep_nested_and_duplicate_categories(
        self, catalog_adapter: SqliteCatalogAdapter
    ) -> None:
        """Challenge: Nested categories ('a.b.c.d') with duplicate entries and domain prefixes."""
        # 1. Deep category with domain prefix: clinical.oncology.solid_tumor.lung.nsclc
        a1 = _make_agent("ag1", domain=AgentDomain.CLINICAL, category="clinical.oncology.solid_tumor.lung.nsclc")
        # 2. Duplicate deep category
        a2 = _make_agent("ag2", domain=AgentDomain.CLINICAL, category="clinical.oncology.solid_tumor.lung.nsclc")
        # 3. Same branch, sister leaf: clinical.oncology.solid_tumor.lung.sclc (without domain prefix in string)
        a3 = _make_agent("ag3", domain=AgentDomain.CLINICAL, category="oncology.solid_tumor.lung.sclc")
        # 4. Partial depth: clinical.oncology
        a4 = _make_agent("ag4", domain=AgentDomain.CLINICAL, category="clinical.oncology")

        await catalog_adapter.index_agent(a1)
        await catalog_adapter.index_agent(a2)
        await catalog_adapter.index_agent(a3)
        await catalog_adapter.index_agent(a4)

        tree = await catalog_adapter.get_category_tree()
        assert tree["total"] == 4
        clin = tree["domains"]["clinical"]
        assert clin["count"] == 4
        onc = clin["categories"]["oncology"]
        assert onc["count"] == 4
        solid = onc["subcategories"]["solid_tumor"]
        assert solid["count"] == 3
        lung = solid["subcategories"]["lung"]
        assert lung["count"] == 3
        assert lung["subcategories"]["nsclc"]["count"] == 2
        assert lung["subcategories"]["sclc"]["count"] == 1

    @pytest.mark.asyncio
    async def test_empty_and_malformed_category_strings(
        self, catalog_adapter: SqliteCatalogAdapter
    ) -> None:
        """Challenge: Empty strings, None, whitespace, dots-only, and category equals domain."""
        rows = [
            {"domain": "clinical", "category": ""},
            {"domain": "clinical", "category": None},
            {"domain": "clinical", "category": "   "},
            {"domain": "clinical", "category": "clinical"},
            {"domain": "therapy", "category": "..."},
            {"domain": "therapy", "category": "..cbt...anxiety.."},
        ]
        tree = build_category_tree_from_rows(rows)
        assert tree["total"] == 6
        assert tree["domains"]["clinical"]["count"] == 4
        assert tree["domains"]["clinical"]["categories"] == {}
        assert tree["domains"]["therapy"]["count"] == 2
        assert "cbt" in tree["domains"]["therapy"]["categories"]
        assert "anxiety" in tree["domains"]["therapy"]["categories"]["cbt"]["subcategories"]

    @pytest.mark.asyncio
    async def test_domain_filtering_in_category_tree(
        self, catalog_adapter: SqliteCatalogAdapter
    ) -> None:
        """Challenge: Filter tree by domain with mixed case."""
        a1 = _make_agent("ag1", domain=AgentDomain.NAVIGATION, category="navigation.insurance")
        a2 = _make_agent("ag2", domain=AgentDomain.WELLNESS, category="wellness.habits")
        await catalog_adapter.index_agent(a1)
        await catalog_adapter.index_agent(a2)

        tree_nav = await catalog_adapter.get_category_tree(domain="NAVIGATION")
        assert tree_nav["total"] == 1
        assert "navigation" in tree_nav["domains"]
        assert "wellness" not in tree_nav["domains"]

        tree_missing = await catalog_adapter.get_category_tree(domain="education")
        assert tree_missing["total"] == 0
        assert tree_missing["domains"]["education"]["count"] == 0


# ==============================================================================
# 7. Case-Insensitive Filtering Tests
# ==============================================================================

class TestCaseInsensitiveFiltering:
    """Stress-tests case insensitivity for domain and category matching in SqliteCatalogAdapter."""

    @pytest.fixture
    async def catalog_adapter(self, tmp_path: Path):
        db_file = tmp_path / "case_test.db"
        adapter = SqliteCatalogAdapter(db_path=db_file)
        yield adapter
        await adapter.close()

    @pytest.mark.asyncio
    async def test_case_insensitive_domain_and_category_search(
        self, catalog_adapter: SqliteCatalogAdapter
    ) -> None:
        """Challenge: Mixed-case domain and category parameters in both browse and FTS modes."""
        agent = _make_agent(
            "case-agent",
            title="Benefits Specialist",
            description="Navigating complex insurance benefits and copay claims.",
            domain=AgentDomain.NAVIGATION,
            category="Navigation.Insurance.SubPlan",
            tags=["claims"],
        )
        await catalog_adapter.index_agent(agent)

        # 1. Domain case insensitivity (without query)
        for dom in ["navigation", "NAVIGATION", "Navigation", "nAvIgAtIoN"]:
            res = await catalog_adapter.search_agents(domain=dom)
            assert len(res) == 1, f"Failed domain filter for {dom}"
            assert res[0].id == "case-agent"

        # 2. Category case insensitivity (exact)
        for cat in ["navigation.insurance.subplan", "NAVIGATION.INSURANCE.SUBPLAN", "Navigation.Insurance.SubPlan"]:
            res = await catalog_adapter.search_agents(category=cat)
            assert len(res) == 1, f"Failed exact category filter for {cat}"

        # 3. Category case insensitivity (prefix)
        for prefix in ["navigation", "NAVIGATION", "navigation.insurance", "NAVIGATION.INSURANCE"]:
            res = await catalog_adapter.search_agents(category=prefix)
            assert len(res) == 1, f"Failed prefix category filter for {prefix}"

        # 4. Combined with FTS query
        res_fts = await catalog_adapter.search_agents(query="copay", domain="NAVIGATION", category="NAVIGATION.INSURANCE")
        assert len(res_fts) == 1
        assert res_fts[0].id == "case-agent"


# ==============================================================================
# 8. Rapid Sequential and Concurrent Indexing Tests
# ==============================================================================

class TestRapidSequentialAndConcurrentCatalog:
    """Stress-tests SQLite catalog adapter under rapid indexing, updates, and concurrent access."""

    @pytest.fixture
    async def catalog_adapter(self, tmp_path: Path):
        db_file = tmp_path / "concurrency_catalog.db"
        adapter = SqliteCatalogAdapter(db_path=db_file)
        yield adapter
        await adapter.close()

    @pytest.mark.asyncio
    async def test_rapid_sequential_indexing_and_updates(
        self, catalog_adapter: SqliteCatalogAdapter
    ) -> None:
        """Challenge: Indexing 50 agents sequentially, then updating them with new titles/descriptions.
        Verify FTS consistency and no duplicate or ghost records in SQLite FTS5.
        """
        for i in range(50):
            agent = _make_agent(
                agent_id=f"seq-agent-{i}",
                title=f"Initial Title {i}",
                description=f"Initial description {i} for allergy condition",
            )
            await catalog_adapter.index_agent(agent)

        assert await catalog_adapter.count_agents() == 50
        initial_match = await catalog_adapter.search_agents(query="allergy", limit=100)
        assert len(initial_match) == 50

        # Update all 50 agents with cardiology terms
        for i in range(50):
            updated_agent = _make_agent(
                agent_id=f"seq-agent-{i}",
                title=f"Updated Title {i}",
                description=f"Updated description {i} for cardiology arrhythmia",
            )
            await catalog_adapter.index_agent(updated_agent)

        assert await catalog_adapter.count_agents() == 50
        old_match = await catalog_adapter.search_agents(query="allergy", limit=100)
        assert len(old_match) == 0, "Old FTS content still indexed after update!"
        new_match = await catalog_adapter.search_agents(query="cardiology", limit=100)
        assert len(new_match) == 50

    @pytest.mark.asyncio
    async def test_concurrent_indexing_and_searching(
        self, catalog_adapter: SqliteCatalogAdapter
    ) -> None:
        """Challenge: Multiple concurrent coroutines indexing and querying simultaneously.
        Verify that asyncio.Lock prevents 'database locked' or race condition errors.
        """
        async def index_batch(start_idx: int, count: int) -> None:
            for i in range(start_idx, start_idx + count):
                agent = _make_agent(
                    agent_id=f"conc-agent-{i}",
                    title=f"Concurrent Agent {i}",
                    description=f"Concurrent agent {i} details hypertension",
                    domain=AgentDomain.CLINICAL if i % 2 == 0 else AgentDomain.WELLNESS,
                )
                await catalog_adapter.index_agent(agent)

                skill = _make_skill(
                    skill_id=f"conc-skill-{i}",
                    name=f"Concurrent Skill {i}",
                    description=f"Concurrent skill {i} instructions prescription",
                )
                await catalog_adapter.index_skill(skill)

        async def query_worker(rounds: int) -> None:
            for _ in range(rounds):
                await catalog_adapter.search_agents(query="hypertension")
                await catalog_adapter.search_skills(query="prescription")
                await catalog_adapter.get_category_tree()

        # Launch 5 indexers (10 items each = 50 total) and 5 searchers concurrently
        workers = [
            index_batch(0, 10),
            index_batch(10, 10),
            index_batch(20, 10),
            index_batch(30, 10),
            index_batch(40, 10),
            query_worker(10),
            query_worker(10),
            query_worker(10),
            query_worker(10),
            query_worker(10),
        ]
        await asyncio.gather(*workers)

        assert await catalog_adapter.count_agents() == 50
        assert await catalog_adapter.count_skills() == 50

