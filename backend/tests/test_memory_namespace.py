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

"""Memory Namespace Isolation and Catalog Tag Filtering Test Suite.
Scope:
1. Delimiter collisions with extreme namespace values ('a:b:c', ':::', empty '', unicode colons).
2. Tag filtering in catalog with multi-tag combinations (AND vs OR semantics), case variations,
   empty tag lists, nonexistent tags with pagination limits, and whitespace edge cases.
3. Large memory payloads (>100KB JSON, multilingual unicode, and binary bytes handling).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List
import pytest

from carefold.memory.adapters.sqlite.catalog_adapter import SqliteCatalogAdapter
from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
from carefold.memory.ports.memory_port import MemoryTier
from carefold.schemas.manifest import (
    AgentDomain,
    AgentManifest,
    RiskClass,
    SkillManifest,
)


def _make_agent(
    agent_id: str,
    domain: AgentDomain = AgentDomain.WELLNESS,
    category: str = "wellness.general",
    title: str = "Test Agent",
    hidden: bool = False,
    tags: List[str] = None,
    persona: str = "Test persona",
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
        persona=persona,
    )


def _make_skill(
    skill_id: str,
    domain: AgentDomain = AgentDomain.WELLNESS,
    category: str = "wellness.general",
    name: str = "Test Skill",
    tags: List[str] = None,
    instructions: str = "Execute test skill",
) -> SkillManifest:
    return SkillManifest(
        id=skill_id,
        name=name,
        version="0.1.0",
        domain=domain,
        category=category,
        risk_class=RiskClass.WELLNESS,
        tags=tags or ["test"],
        description=f"Description for {name}",
        instructions=instructions,
    )


# ==============================================================================
# 1. Delimiter Collisions and Extreme Namespace Values
# ==============================================================================

class TestNamespaceIsolationAndDelimiterStress:
    """Stress tests challenging delimiter collisions and extreme namespace values."""

    @pytest.fixture
    async def adapter(self, tmp_path: Path):
        db_file = tmp_path / "extreme_namespace_test.db"
        mem = SqliteMemoryAdapter(db_path=db_file)
        yield mem
        await mem.close()

    @pytest.mark.asyncio
    async def test_delimiter_multiple_colons_namespace(self, adapter: SqliteMemoryAdapter) -> None:
        """Challenge 1.1: Namespace 'a:b:c' vs 'a:b' vs 'a' with colons in keys."""
        # Tenant A: namespace='a:b:c', key='d'
        # Tenant B: namespace='a:b',   key='c:d'
        # Tenant C: namespace='a',     key='b:c:d'
        await adapter.remember("d", "tenant_a_data", MemoryTier.WORKING, namespace="a:b:c")
        await adapter.remember("c:d", "tenant_b_data", MemoryTier.WORKING, namespace="a:b")
        await adapter.remember("b:c:d", "tenant_c_data", MemoryTier.WORKING, namespace="a")

        # Independent retrieval
        rec_a = await adapter.get("d", namespace="a:b:c")
        rec_b = await adapter.get("c:d", namespace="a:b")
        rec_c = await adapter.get("b:c:d", namespace="a")

        assert rec_a is not None and rec_a["value"] == "tenant_a_data"
        assert rec_b is not None and rec_b["value"] == "tenant_b_data"
        assert rec_c is not None and rec_c["value"] == "tenant_c_data"

        # Cross-tenant get must return None
        assert await adapter.get("d", namespace="a:b") is None
        assert await adapter.get("c:d", namespace="a:b:c") is None

        # Cross-tenant deletion isolation: Tenant B deletes its key
        assert await adapter.forget("c:d", namespace="a:b") is True
        assert await adapter.get("c:d", namespace="a:b") is None

        # Tenant A and C must remain untouched
        assert (await adapter.get("d", namespace="a:b:c"))["value"] == "tenant_a_data"
        assert (await adapter.get("b:c:d", namespace="a"))["value"] == "tenant_c_data"

    @pytest.mark.asyncio
    async def test_delimiter_colon_only_namespaces(self, adapter: SqliteMemoryAdapter) -> None:
        """Challenge 1.2: Extreme namespaces consisting solely of colons (":::", "::", ":", "")."""
        await adapter.remember("key", "val_3", MemoryTier.EPISODIC, namespace=":::")
        await adapter.remember(":key", "val_2", MemoryTier.EPISODIC, namespace="::")
        await adapter.remember("::key", "val_1", MemoryTier.EPISODIC, namespace=":")
        await adapter.remember(":::key", "val_0", MemoryTier.EPISODIC, namespace="")

        assert (await adapter.get("key", namespace=":::"))["value"] == "val_3"
        assert (await adapter.get(":key", namespace="::"))["value"] == "val_2"
        assert (await adapter.get("::key", namespace=":"))["value"] == "val_1"
        assert (await adapter.get(":::key", namespace=""))["value"] == "val_0"

        # Mutate in ':::'
        await adapter.remember("key", "val_3_mutated", MemoryTier.EPISODIC, namespace=":::")
        assert (await adapter.get("key", namespace=":::"))["value"] == "val_3_mutated"
        assert (await adapter.get(":::key", namespace=""))["value"] == "val_0"

    @pytest.mark.asyncio
    async def test_empty_namespace_lifecycle(self, adapter: SqliteMemoryAdapter) -> None:
        """Challenge 1.3: Empty namespace ('') lifecycle across all port methods."""
        # 1. remember in empty namespace
        await adapter.remember("k_empty", "v_empty", MemoryTier.SEMANTIC, namespace="")

        # 2. get in empty namespace
        rec = await adapter.get("k_empty", namespace="")
        assert rec is not None
        assert rec["value"] == "v_empty"
        assert rec["namespace"] == ""
        assert rec["salience"] == 1.0

        # 3. Isolation: default and user namespaces have no access
        assert await adapter.get("k_empty", namespace="default") is None
        assert await adapter.get("k_empty", namespace="user") is None

        # 4. recall in empty namespace with query
        recalled = await adapter.recall("v_empty", namespace="")
        assert len(recalled) == 1
        assert recalled[0]["key"] == "k_empty"

        # 5. recall in empty namespace with empty query
        recalled_empty_q = await adapter.recall("", namespace="")
        assert any(r["key"] == "k_empty" for r in recalled_empty_q)

        # 6. reinforce in empty namespace
        await adapter.reinforce("k_empty", namespace="", delta=0.5)
        rec_boosted = await adapter.get("k_empty", namespace="")
        assert rec_boosted["salience"] == 1.5
        assert rec_boosted["access_count"] == 1

        # 7. forget in empty namespace
        assert await adapter.forget("k_empty", namespace="") is True
        assert await adapter.get("k_empty", namespace="") is None

    @pytest.mark.asyncio
    async def test_unicode_colons_isolation(self, adapter: SqliteMemoryAdapter) -> None:
        """Challenge 1.4: Namespaces containing distinct unicode colon variants."""
        # Colons across unicode blocks:
        # standard:   U+003A (:)
        # fullwidth:  U+FF1A (：)
        # presentation: U+FE13 (︓)
        # small:      U+FE55 (﹕)
        # ratio:      U+2236 (∶)
        # modifier:   U+02D0 (ː)
        variants = {
            "std": "user:1",
            "fullwidth": "user：1",
            "presentation": "user︓1",
            "small": "user﹕1",
            "ratio": "user∶1",
            "modifier": "userː1",
        }

        for name, ns in variants.items():
            await adapter.remember(
                "token",
                f"payload_{name}",
                MemoryTier.WORKING,
                namespace=ns,
            )

        # Verify each variant retains its exact distinct value
        for name, ns in variants.items():
            item = await adapter.get("token", namespace=ns)
            assert item is not None, f"Expected item for {name} ({ns})"
            assert item["value"] == f"payload_{name}"

        # Delete one variant; other variants must remain intact
        assert await adapter.forget("token", namespace=variants["fullwidth"]) is True
        assert await adapter.get("token", namespace=variants["fullwidth"]) is None
        assert (await adapter.get("token", namespace=variants["std"]))["value"] == "payload_std"
        assert (await adapter.get("token", namespace=variants["ratio"]))["value"] == "payload_ratio"

    @pytest.mark.asyncio
    async def test_digit_prefix_namespace_collision_resistance(self, adapter: SqliteMemoryAdapter) -> None:
        """Challenge 1.5: Namespaces starting with digits and colons mimicking length prefix."""
        # e.g. ns="5:admin", key="key" vs ns="5", key="admin:key" vs ns="1:5:admin", key="key"
        await adapter.remember("key", "val_5_admin", MemoryTier.WORKING, namespace="5:admin")
        await adapter.remember("admin:key", "val_5_plain", MemoryTier.WORKING, namespace="5")
        await adapter.remember("key", "val_nested", MemoryTier.WORKING, namespace="1:5:admin")

        assert (await adapter.get("key", namespace="5:admin"))["value"] == "val_5_admin"
        assert (await adapter.get("admin:key", namespace="5"))["value"] == "val_5_plain"
        assert (await adapter.get("key", namespace="1:5:admin"))["value"] == "val_nested"

    @pytest.mark.asyncio
    async def test_extreme_length_namespace(self, adapter: SqliteMemoryAdapter) -> None:
        """Challenge 1.6: Very long namespace (4000+ chars) with mixed colons and symbols."""
        long_ns = "ns_" + ("segment:" * 400) + "terminal"
        assert len(long_ns) > 3200

        await adapter.remember("extreme_key", "extreme_value", MemoryTier.WORKING, namespace=long_ns)
        rec = await adapter.get("extreme_key", namespace=long_ns)
        assert rec is not None
        assert rec["value"] == "extreme_value"
        assert rec["namespace"] == long_ns

        recalled = await adapter.recall("extreme_value", namespace=long_ns)
        assert len(recalled) == 1
        assert recalled[0]["key"] == "extreme_key"


# ==============================================================================
# 2. Tag Filtering in Catalog
# ==============================================================================

class TestCatalogTagFilteringAdversarial:
    """Stress tests challenging multi-tag combinations, case variations, and pagination."""

    @pytest.fixture
    async def catalog(self, tmp_path: Path):
        db_file = tmp_path / "catalog_tags_test.db"
        cat = SqliteCatalogAdapter(db_path=db_file)
        yield cat
        await cat.close()

    @pytest.mark.asyncio
    async def test_multi_tag_or_semantics(self, catalog: SqliteCatalogAdapter) -> None:
        """Challenge 2.1: Verify multi-tag combinations behave with OR (match any) semantics."""
        a1 = _make_agent("a1", title="Cardio Agent", tags=["cardiology", "heart"])
        a2 = _make_agent("a2", title="Pediatric Agent", tags=["pediatrics", "child"])
        a3 = _make_agent("a3", title="Dual Agent", tags=["cardiology", "pediatrics"])
        a4 = _make_agent("a4", title="Oncology Agent", tags=["oncology", "cancer"])

        for a in [a1, a2, a3, a4]:
            await catalog.index_agent(a)

        # Searching with multiple tags ['cardiology', 'pediatrics']
        results = await catalog.search_agents(tags=["cardiology", "pediatrics"])
        result_ids = {a.id for a in results}

        # Under OR semantics: agents with ANY of the tags match (a1, a2, a3)
        assert result_ids == {"a1", "a2", "a3"}
        assert "a4" not in result_ids

    @pytest.mark.asyncio
    async def test_tag_case_insensitivity_ascii(self, catalog: SqliteCatalogAdapter) -> None:
        """Challenge 2.2: Case variations in query tags match uppercase, lowercase, mixed case."""
        a = _make_agent("a_case", tags=["CARDIOLOGY", "Pediatrics", "wellness_plan"])
        await catalog.index_agent(a)

        # All uppercase query
        res1 = await catalog.search_agents(tags=["CARDIOLOGY"])
        assert len(res1) == 1 and res1[0].id == "a_case"

        # All lowercase query
        res2 = await catalog.search_agents(tags=["cardiology"])
        assert len(res2) == 1 and res2[0].id == "a_case"

        # Mixed case query
        res3 = await catalog.search_agents(tags=["pEdIaTrIcS"])
        assert len(res3) == 1 and res3[0].id == "a_case"

        # Query tag with leading/trailing whitespace
        res4 = await catalog.search_agents(tags=["  wellness_plan  "])
        assert len(res4) == 1 and res4[0].id == "a_case"

    @pytest.mark.asyncio
    async def test_tag_case_insensitivity_accented_unicode_finding(self, catalog: SqliteCatalogAdapter) -> None:
        """Challenge 2.3: Empirical verification of SQLite LOWER() behavior on non-ASCII characters.
        
        Demonstrates that SQLite's built-in LOWER() function only folds ASCII A-Z.
        If a manifest tag contains uppercase accented unicode like 'CAFÉ', SQLite LOWER('CAFÉ')
        remains 'CAFÉ', so searching for lowercase 'café' does not match.
        """
        agent = _make_agent("a_accent", tags=["CAFÉ", "CLÍNICA"])
        await catalog.index_agent(agent)

        # Searching with lowercase 'café': clean_tags has 'café'
        # In SQL: json_each(a.tags) -> value='CAFÉ' -> SQLite LOWER('CAFÉ')='CAFÉ'
        # 'CAFÉ' IN ('café') -> FALSE
        res_lower = await catalog.search_agents(tags=["café"])
        assert len(res_lower) == 0, "Confirms SQLite built-in LOWER does not fold accented unicode"

        # Searching with uppercase 'CAFÉ': clean_tags has Python 'café'
        # In SQL: SQLite LOWER('CAFÉ')='CAFÉ'
        # 'CAFÉ' IN ('café') -> FALSE
        # This empirically proves that uppercase accented tags in manifests are PERMANENTLY UNSEARCHABLE!
        res_upper = await catalog.search_agents(tags=["CAFÉ"])
        assert len(res_upper) == 0, "Confirms uppercase accented tags in manifest are permanently unsearchable"

    @pytest.mark.asyncio
    async def test_manifest_untrimmed_whitespace_finding(self, catalog: SqliteCatalogAdapter) -> None:
        """Challenge 2.4: Untrimmed whitespace in manifest tags.
        
        If manifest.tags contains ' cardiology ' with spaces, SQL LOWER(value) retains the spaces,
        so searching with clean tag 'cardiology' fails to match.
        """
        agent = _make_agent("a_ws", tags=[" cardiology "])
        await catalog.index_agent(agent)

        # Search with stripped tag
        res = await catalog.search_agents(tags=["cardiology"])
        assert len(res) == 0, "Confirms SQL does not TRIM manifest tag whitespace"

    @pytest.mark.asyncio
    async def test_empty_and_whitespace_tag_lists(self, catalog: SqliteCatalogAdapter) -> None:
        """Challenge 2.5: Empty, None, and whitespace-only tag lists bypass tag filtering safely."""
        for i in range(5):
            await catalog.index_agent(_make_agent(f"agent_{i}", tags=[f"tag_{i}"]))

        # None tags
        res_none = await catalog.search_agents(tags=None)
        assert len(res_none) == 5

        # Empty list
        res_empty = await catalog.search_agents(tags=[])
        assert len(res_empty) == 5

        # Whitespace-only elements
        res_spaces = await catalog.search_agents(tags=["", "   ", "\t", "\n"])
        assert len(res_spaces) == 5

    @pytest.mark.asyncio
    async def test_nonexistent_tags_with_pagination(self, catalog: SqliteCatalogAdapter) -> None:
        """Challenge 2.6: Nonexistent tags with pagination limits and offsets."""
        for i in range(15):
            await catalog.index_agent(_make_agent(f"agent_{i}", tags=["common_tag"]))

        # Nonexistent tag returns empty list on page 0
        p0 = await catalog.search_agents(tags=["ghost_tag_xyz"], limit=5, offset=0)
        assert len(p0) == 0

        # Nonexistent tag returns empty list on page 2
        p2 = await catalog.search_agents(tags=["ghost_tag_xyz"], limit=5, offset=10)
        assert len(p2) == 0

    @pytest.mark.asyncio
    async def test_tag_pagination_boundary_integrity(self, catalog: SqliteCatalogAdapter) -> None:
        """Challenge 2.7: Strict pagination boundary integrity across 25 tagged agents with limit=7.
        
        Ensures pre-LIMIT tag filtering correctly returns all 25 matching agents across 4 pages
        without dropping records, overlapping records, or off-by-one errors.
        """
        # Index 40 agents: 25 matching 'target_tag', 15 with 'other_tag'
        for i in range(40):
            tag = "target_tag" if i < 25 else "other_tag"
            await catalog.index_agent(_make_agent(f"agent_{i:02d}", title=f"Agent {i:02d}", tags=[tag]))

        # Paginate with limit=7
        pages = []
        offset = 0
        limit = 7
        while True:
            page = await catalog.search_agents(tags=["target_tag"], limit=limit, offset=offset)
            if not page:
                break
            pages.append(page)
            offset += limit

        # 25 total records with limit=7: 4 pages (7, 7, 7, 4)
        assert len(pages) == 4
        assert [len(p) for p in pages] == [7, 7, 7, 4]

        all_ids = [a.id for page in pages for a in page]
        assert len(all_ids) == 25
        assert len(set(all_ids)) == 25, "No duplicate IDs across pages"
        assert set(all_ids) == {f"agent_{i:02d}" for i in range(25)}

    @pytest.mark.asyncio
    async def test_tags_combined_with_fts_search(self, catalog: SqliteCatalogAdapter) -> None:
        """Challenge 2.8: Tag filtering combined with full-text search query and scoring."""
        a1 = _make_agent("a1", title="Hypertension Clinical Guide", tags=["clinical", "cardio"])
        a2 = _make_agent("a2", title="Hypertension Wellness Tracker", tags=["wellness", "habits"])
        a3 = _make_agent("a3", title="Asthma Clinical Guide", tags=["clinical", "pulmonary"])
        for a in [a1, a2, a3]:
            await catalog.index_agent(a)

        # Query "Hypertension" + tag "clinical" -> should match only a1
        res = await catalog.search_agents(query="Hypertension", tags=["clinical"])
        assert len(res) == 1
        assert res[0].id == "a1"

        # Query "Hypertension" + tag "wellness" -> should match only a2
        res_w = await catalog.search_agents(query="Hypertension", tags=["wellness"])
        assert len(res_w) == 1
        assert res_w[0].id == "a2"

    @pytest.mark.asyncio
    async def test_skills_tag_filtering_and_pagination(self, catalog: SqliteCatalogAdapter) -> None:
        """Challenge 2.9: Verify skills catalog implements identical pre-LIMIT tag filtering."""
        for i in range(20):
            tag = "preauth" if i < 12 else "claims"
            await catalog.index_skill(_make_skill(f"skill_{i:02d}", name=f"Skill {i:02d}", tags=[tag]))

        # Paginate skills with limit=5
        s_page0 = await catalog.search_skills(tags=["preauth"], limit=5, offset=0)
        s_page1 = await catalog.search_skills(tags=["preauth"], limit=5, offset=5)
        s_page2 = await catalog.search_skills(tags=["preauth"], limit=5, offset=10)
        s_page3 = await catalog.search_skills(tags=["preauth"], limit=5, offset=15)

        assert len(s_page0) == 5
        assert len(s_page1) == 5
        assert len(s_page2) == 2
        assert len(s_page3) == 0

        preauth_ids = [s.id for p in [s_page0, s_page1, s_page2] for s in p]
        assert len(set(preauth_ids)) == 12


# ==============================================================================
# 3. Large Memory Payloads and Data Integrity
# ==============================================================================

class TestLargeMemoryPayloadsAndTypePreservation:
    """Stress tests challenging large payloads (>100KB), unicode scripts, and binary bytes."""

    @pytest.fixture
    async def adapter(self, tmp_path: Path):
        db_file = tmp_path / "large_payload_test.db"
        mem = SqliteMemoryAdapter(db_path=db_file)
        yield mem
        await mem.close()

    @pytest.mark.asyncio
    async def test_large_json_payload_100kb_plus(self, adapter: SqliteMemoryAdapter) -> None:
        """Challenge 3.1: 150KB+ JSON structured memory payload.
        
        Verifies:
        - Exact JSON round-trip fidelity through get() with zero corruption of nested types.
        - FTS5 indexing of large payload and keyword recall with bm25 score.
        """
        # Construct large JSON payload (~150KB)
        records = {}
        for i in range(350):
            records[f"patient_{i:03d}"] = {
                "demographics": {"age": 45 + (i % 30), "gender": "F" if i % 2 == 0 else "M"},
                "vitals": {"bp_systolic": 120 + (i % 20), "bp_diastolic": 80 + (i % 10), "heart_rate": 72},
                "medications": ["Metformin 500mg", "Lisinopril 10mg", "Atorvastatin 20mg"],
                "clinical_notes": (
                    "Patient presented with acute hypoglycemic episode after vigorous exercise."
                    if i == 175
                    else "Routine annual preventive follow-up with no acute complaints."
                ),
                "active": True,
                "history_score": 0.95,
            }
        serialized = json.dumps(records)
        payload_size_kb = len(serialized) / 1024.0
        assert payload_size_kb > 100.0, f"Payload must exceed 100KB, got {payload_size_kb:.2f} KB"

        await adapter.remember("large_medical_db", records, MemoryTier.SEMANTIC, namespace="clinic_data")

        # 1. Exact round-trip get()
        fetched = await adapter.get("large_medical_db", namespace="clinic_data")
        assert fetched is not None
        assert fetched["value"] == records
        assert fetched["value"]["patient_175"]["clinical_notes"].startswith("Patient presented with acute")
        assert fetched["value"]["patient_000"]["demographics"]["age"] == 45

        # 2. FTS recall of keyword embedded in record 175
        recalled = await adapter.recall("hypoglycemic", namespace="clinic_data")
        assert len(recalled) == 1
        assert recalled[0]["key"] == "large_medical_db"
        assert recalled[0]["score"] > 0

    @pytest.mark.asyncio
    async def test_large_json_payload_mutation_and_fts_reindex(self, adapter: SqliteMemoryAdapter) -> None:
        """Challenge 3.2: Updating a large JSON payload refreshes FTS index without duplication."""
        doc1 = {"text": "Original document content with keyword alpha_marker", "items": list(range(2000))}
        await adapter.remember("doc_key", doc1, MemoryTier.WORKING, namespace="docs")

        assert len(await adapter.recall("alpha_marker", namespace="docs")) == 1
        assert len(await adapter.recall("beta_marker", namespace="docs")) == 0

        # Update with new content
        doc2 = {"text": "Updated document content with keyword beta_marker", "items": list(range(2000))}
        await adapter.remember("doc_key", doc2, MemoryTier.WORKING, namespace="docs")

        # Old token must no longer match, new token must match
        assert len(await adapter.recall("alpha_marker", namespace="docs")) == 0
        assert len(await adapter.recall("beta_marker", namespace="docs")) == 1

        # Single record preserved in get()
        item = await adapter.get("doc_key", namespace="docs")
        assert item["value"]["text"] == doc2["text"]

    @pytest.mark.asyncio
    async def test_unicode_multilingual_memory_payloads(self, adapter: SqliteMemoryAdapter) -> None:
        """Challenge 3.3: Multilingual medical records (Cyrillic, Arabic, Devanagari, Greek, CJK, Emoji)."""
        multilingual_data = {
            "ru": "Медицинская карта: пациент перенес операцию без осложнений.",
            "ar": "تقرير طبي: المريض يعاني من ارتفاع ضغط الدم والسكري.",
            "hi": "चिकित्सा रिपोर्ट: रोगी का रक्तचाप सामान्य और स्थिर है।",
            "el": "Ιατρικό ιστορικό: Ο ασθενής δεν αναφέρει αλλεργικές αντιδράσεις.",
            "zh": "医疗记录：患者李四，患有2型 糖尿病 ，需每日监测血糖。",
            "emoji": "Vital signs: ❤️ 120/80 mmHg | 🌡️ 36.8°C | 🏥 ICU Ward 3 👨‍⚕️",
        }

        for lang, text in multilingual_data.items():
            await adapter.remember(f"note_{lang}", text, MemoryTier.EPISODIC, namespace="intl_clinic")

        # Verify get() preservation
        for lang, text in multilingual_data.items():
            rec = await adapter.get(f"note_{lang}", namespace="intl_clinic")
            assert rec is not None
            assert rec["value"] == text

        # Verify recall for Cyrillic
        rec_ru = await adapter.recall("пациент", namespace="intl_clinic")
        assert len(rec_ru) >= 1 and rec_ru[0]["key"] == "note_ru"

        # Verify recall for Arabic
        rec_ar = await adapter.recall("المريض", namespace="intl_clinic")
        assert len(rec_ar) >= 1 and rec_ar[0]["key"] == "note_ar"

        # Verify recall for Greek
        rec_el = await adapter.recall("αλλεργικές", namespace="intl_clinic")
        assert len(rec_el) >= 1 and rec_el[0]["key"] == "note_el"

        # Verify recall for space-separated Chinese term
        rec_zh = await adapter.recall("糖尿病", namespace="intl_clinic")
        assert len(rec_zh) >= 1 and rec_zh[0]["key"] == "note_zh"

    @pytest.mark.asyncio
    async def test_raw_bytes_handling_and_type_loss_finding(self, adapter: SqliteMemoryAdapter) -> None:
        """Challenge 3.4: Raw binary bytes storage and type conversion finding.
        
        Demonstrates that SqliteMemoryAdapter handles raw bytes without crashing,
        but serializes via json.dumps(str(value)), returning a string representation
        (e.g. "b'...'") rather than preserving binary bytes upon get().
        """
        raw_binary = b"\x00\x01\x02\x03\xff\xfe\x00\xaa"
        await adapter.remember("raw_bin", raw_binary, MemoryTier.WORKING, namespace="binary_ns")

        rec = await adapter.get("raw_bin", namespace="binary_ns")
        assert rec is not None
        # Type is string, not bytes
        assert isinstance(rec["value"], str)
        assert rec["value"] == str(raw_binary)

    @pytest.mark.asyncio
    async def test_dict_containing_bytes_type_error_finding(self, adapter: SqliteMemoryAdapter) -> None:
        """Challenge 3.5: Unhandled TypeError when value is a dict containing bytes.
        
        Lines 125-126 in SqliteMemoryAdapter execute:
            elif isinstance(value, (dict, list)):
                content = f"{key} {json.dumps(value)}"
        without exception handling. If a dict or list contains raw bytes,
        json.dumps(value) raises TypeError: Object of type bytes is not JSON serializable.
        """
        dict_with_bytes = {"filename": "scan.pdf", "raw_blob": b"\x25\x50\x44\x46"}
        with pytest.raises(TypeError) as exc_info:
            await adapter.remember("pdf_doc", dict_with_bytes, MemoryTier.WORKING)
        assert "bytes is not JSON serializable" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_metadata_containing_bytes_type_error_finding(self, adapter: SqliteMemoryAdapter) -> None:
        """Challenge 3.6: Unhandled TypeError when metadata contains bytes.
        
        Line 121 in SqliteMemoryAdapter executes:
            meta_str = json.dumps(metadata or {})
        If metadata contains bytes, json.dumps raises TypeError.
        """
        meta_with_bytes = {"hash": b"\xab\xcd\xef"}
        with pytest.raises(TypeError) as exc_info:
            await adapter.remember("normal_key", "normal_val", MemoryTier.WORKING, metadata=meta_with_bytes)
        assert "bytes is not JSON serializable" in str(exc_info.value)
