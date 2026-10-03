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

"""Automated Search Evaluation and Verification Suite.

Tests:
1. SQLite FTS5 catalog indexing of the 8 new core organ agents & skills without errors.
2. Search query routing: 'hypertension', 'asthma', 'migraine', 'colonoscopy', 'eGFR',
   'diabetes CGM', 'joint pain', 'rash lesion' returning respective organ navigators as top candidates.
3. Adversarial query stress: special characters, SQL/FTS injection attempts, punctuation, and multi-word terms.
4. Golden offline evaluations: all 48 golden eval cases across the 8 agents executed with 100% pass rate.
5. Strict zero file leak detection: verifies that skills/ directory has 0 additions, deletions, or modifications
   after running the evaluation suites.
6. Penetration suite integration: verifies that all 47 penetration tests pass with 0 vulnerabilities.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Set, Tuple
import pytest

from carefold.agents.registry import AgentRegistry
from carefold.constants.paths import REFERENCES_DIR, SKILLS_DIR
from carefold.loaders.agent_loader import load_agent
from carefold.loaders.skill_loader import load_skill
from carefold.memory.adapters.sqlite.catalog_adapter import SqliteCatalogAdapter, sanitize_fts_query
from carefold.schemas.manifest import AgentDomain, AgentManifest, AgentMaturity, RiskClass
from evals.runner import EvalCase, run_single_eval


CORE_8_SPECIALISTS: Dict[str, Dict[str, Any]] = {
    "cardiology-guide": {
        "title": "Cardiology Navigator",
        "companion_skill": "cardiology-prep",
        "category": "clinical.cardiology",
        "query": "hypertension",
    },
    "pulmonology-guide": {
        "title": "Pulmonology Navigator",
        "companion_skill": "pulmonology-prep",
        "category": "clinical.pulmonology",
        "query": "asthma",
    },
    "neurology-guide": {
        "title": "Neurology Navigator",
        "companion_skill": "neurology-prep",
        "category": "clinical.neurology",
        "query": "migraine",
    },
    "gastro-guide": {
        "title": "Gastroenterology Navigator",
        "companion_skill": "gastro-prep",
        "category": "clinical.gastroenterology",
        "query": "colonoscopy",
    },
    "nephrology-guide": {
        "title": "Nephrology Navigator",
        "companion_skill": "nephrology-prep",
        "category": "clinical.nephrology",
        "query": "eGFR",
    },
    "endocrinology-guide": {
        "title": "Endocrinology Navigator",
        "companion_skill": "endocrinology-prep",
        "category": "clinical.endocrinology",
        "query": "diabetes CGM",
    },
    "ortho-guide": {
        "title": "Orthopedics Navigator",
        "companion_skill": "ortho-prep",
        "category": "clinical.orthopedics",
        "query": "joint pain",
    },
    "derma-guide": {
        "title": "Dermatology Navigator",
        "companion_skill": "derma-prep",
        "category": "clinical.dermatology",
        "query": "rash lesion",
    },
}


# ============================================================================
# Section 1: SQLite FTS5 Catalog Indexing Tests
# ============================================================================

class TestSqliteCatalogIndexingEmpirical:
    """Empirical tests for SQLite FTS5 catalog indexing of the 8 core organ agents and skills."""

    @pytest.mark.asyncio
    async def test_all_8_agents_index_in_memory_cleanly(self, temp_workspace: Path):
        """Verify that SqliteCatalogAdapter indexes all 8 core organ agents and skills into memory without errors."""
        agents_dir = temp_workspace / "agents"
        skills_dir = temp_workspace / "skills"

        catalog = SqliteCatalogAdapter(db_path=":memory:")

        for agent_id, meta in CORE_8_SPECIALISTS.items():
            agent_manifest, _, _ = load_agent(agents_dir / agent_id, skills_dir)
            await catalog.index_agent(agent_manifest)

            skill_id = meta["companion_skill"]
            skill_manifest = load_skill(skills_dir / skill_id)
            await catalog.index_skill(skill_manifest)

        assert await catalog.count_agents(include_hidden=False) == 8
        assert await catalog.count_skills() == 8

        # Verify get_agent returns intact manifests
        for agent_id, meta in CORE_8_SPECIALISTS.items():
            stored = await catalog.get_agent(agent_id)
            assert stored is not None, f"Agent {agent_id} could not be retrieved from catalog"
            assert stored.id == agent_id
            assert stored.title == meta["title"]
            assert stored.domain == AgentDomain.CLINICAL
            assert stored.category == meta["category"]
            assert stored.risk_class == RiskClass.CLINICAL_ASSIST
            assert stored.maturity == AgentMaturity.STABLE
            assert stored.hidden is False
            assert meta["companion_skill"] in stored.skills

        await catalog.close()

    @pytest.mark.asyncio
    async def test_all_8_agents_disk_persistence_and_reopen(self, tmp_path: Path, temp_workspace: Path):
        """Verify that SqliteCatalogAdapter writes to disk, closes, reopens, and preserves all indexes."""
        agents_dir = temp_workspace / "agents"
        skills_dir = temp_workspace / "skills"
        db_file = tmp_path / "test_catalog.db"

        # 1. Index to disk
        catalog1 = SqliteCatalogAdapter(db_path=db_file)
        for agent_id, meta in CORE_8_SPECIALISTS.items():
            agent_manifest, _, _ = load_agent(agents_dir / agent_id, skills_dir)
            await catalog1.index_agent(agent_manifest)
            skill_manifest = load_skill(skills_dir / meta["companion_skill"])
            await catalog1.index_skill(skill_manifest)
        await catalog1.close()

        # 2. Re-open from disk and verify
        catalog2 = SqliteCatalogAdapter(db_path=db_file)
        assert await catalog2.count_agents() == 8
        assert await catalog2.count_skills() == 8

        # 3. Category tree inspection
        tree = await catalog2.get_category_tree()
        assert "clinical" in tree["domains"]
        assert tree["domains"]["clinical"]["count"] == 8

        categories = tree["domains"]["clinical"]["categories"]
        for meta in CORE_8_SPECIALISTS.values():
            cat_short = meta["category"].split(".", 1)[1]
            assert cat_short in categories
            assert categories[cat_short]["count"] == 1

        await catalog2.close()

    @pytest.mark.asyncio
    async def test_idempotent_reindexing_does_not_corrupt_fts(self, temp_workspace: Path):
        """Verify re-indexing the same agents repeatedly updates cleanly without duplicates or FTS corruption."""
        agents_dir = temp_workspace / "agents"
        skills_dir = temp_workspace / "skills"

        catalog = SqliteCatalogAdapter(db_path=":memory:")

        # Index 3 times
        for _ in range(3):
            for agent_id, meta in CORE_8_SPECIALISTS.items():
                agent_manifest, _, _ = load_agent(agents_dir / agent_id, skills_dir)
                await catalog.index_agent(agent_manifest)
                skill_manifest = load_skill(skills_dir / meta["companion_skill"])
                await catalog.index_skill(skill_manifest)

        # Still exactly 8 agents and skills
        assert await catalog.count_agents() == 8
        assert await catalog.count_skills() == 8

        # Queries still return exactly 1 agent per category
        for meta in CORE_8_SPECIALISTS.values():
            results = await catalog.search_agents(category=meta["category"])
            assert len(results) == 1

        await catalog.close()


# ============================================================================
# Section 2: Search Queries & Two-Hop Routing Candidates
# ============================================================================

class TestTwoHopSearchQueriesRouting:
    """Empirical tests for candidate retrieval across the 8 core organ navigators."""

    @pytest.fixture
    async def full_marketplace_catalog(self, temp_workspace: Path) -> SqliteCatalogAdapter:
        """Catalog initialized with ALL marketplace agents (public, system, organ navigators)."""
        agents_dir = temp_workspace / "agents"
        skills_dir = temp_workspace / "skills"
        catalog = SqliteCatalogAdapter(db_path=":memory:")

        registry = AgentRegistry(agents_dir, skills_dir)
        for agent in registry.list_agents():
            await catalog.index_agent(agent)

        yield catalog
        await catalog.close()

    @pytest.mark.asyncio
    async def test_primary_clinical_queries_retrieve_top_candidate(self, full_marketplace_catalog: SqliteCatalogAdapter):
        """Test that the 8 primary queries retrieve their respective organ navigators as rank 1 candidates."""
        test_queries = {
            "hypertension": "cardiology-guide",
            "asthma": "pulmonology-guide",
            "migraine": "neurology-guide",
            "colonoscopy": "gastro-guide",
            "eGFR": "nephrology-guide",
            "diabetes CGM": "endocrinology-guide",
            "joint pain": "ortho-guide",
            "rash lesion": "derma-guide",
        }

        for query, expected_id in test_queries.items():
            results = await full_marketplace_catalog.search_agents(query=query, limit=5)
            assert len(results) > 0, f"Query '{query}' returned 0 results from catalog"
            top_candidate = results[0]
            assert top_candidate.id == expected_id, (
                f"For query '{query}', expected top candidate '{expected_id}' but got '{top_candidate.id}'"
            )

    @pytest.mark.asyncio
    async def test_realistic_clinical_inquiries_retrieve_correct_organ(self, full_marketplace_catalog: SqliteCatalogAdapter):
        """Test that realistic patient inquiry phrasing retrieves the expected organ specialist."""
        inquiries = {
            "cardiology-guide": "I have high systolic blood pressure readings and heart palpitations",
            "pulmonology-guide": "Experiencing wheezing and dyspnea shortness of breath after using my inhaler",
            "neurology-guide": "Severe throbbing unilateral headache with photophobia visual aura",
            "gastro-guide": "Prepping for upcoming colonoscopy and tracking abdominal bloating after meals",
            "nephrology-guide": "Lab report shows elevated serum creatinine and declining eGFR glomerular filtration",
            "endocrinology-guide": "Continuous glucose monitor CGM trending high blood sugar and A1C levels",
            "ortho-guide": "Knee joint pain and physical therapy exercise tracking for orthopedic surgery consultation",
            "derma-guide": "Found a pigmented skin rash lesion and need ABCDE tracking guide",
        }

        for expected_id, prompt in inquiries.items():
            results = await full_marketplace_catalog.search_agents(query=prompt, limit=5)
            assert len(results) > 0, f"Inquiry '{prompt}' returned 0 candidates"
            candidate_ids = [c.id for c in results]
            assert expected_id in candidate_ids, (
                f"Expected specialist '{expected_id}' not in candidates {candidate_ids} for prompt: '{prompt}'"
            )
            # Candidate 1 should be the target
            assert results[0].id == expected_id, (
                f"Expected top candidate '{expected_id}', got '{results[0].id}' for inquiry: '{prompt}'"
            )

    @pytest.mark.asyncio
    async def test_adversarial_queries_syntax_safety_and_retrieval(self, full_marketplace_catalog: SqliteCatalogAdapter):
        """Stress-tests search queries with punctuation, boolean operators, and injection attempts."""
        adversarial_tests = [
            ("asthma OR 'hypertension'", "pulmonology-guide"),
            ("migraine; DROP TABLE agents; --", "neurology-guide"),
            ("eGFR / creatinine (mL/min/1.73m^2)", "nephrology-guide"),
            ("diabetes + CGM - insulin *", "endocrinology-guide"),
            ("rash & lesion! #skin", "derma-guide"),
            ("joint pain: mobility / knee ???", "ortho-guide"),
            ("colonoscopy...", "gastro-guide"),
            ("hypertension!!!", "cardiology-guide"),
        ]

        for raw_query, expected_id in adversarial_tests:
            # Verify sanitize_fts_query does not throw
            sanitized = sanitize_fts_query(raw_query)
            assert isinstance(sanitized, str)

            # Search catalog directly with the adversarial query
            results = await full_marketplace_catalog.search_agents(query=raw_query, limit=5)
            assert len(results) > 0, f"Adversarial query '{raw_query}' returned 0 results"
            matched_ids = [r.id for r in results]
            assert expected_id in matched_ids, (
                f"Adversarial query '{raw_query}' failed to retrieve expected '{expected_id}'. Got: {matched_ids}"
            )

    @pytest.mark.asyncio
    async def test_two_hop_tier1_to_tier2_candidate_resolution(self, full_marketplace_catalog: SqliteCatalogAdapter):
        """Simulates Tier-1 classification output and verifies Tier-2 candidate selector receives <= 8 candidates."""
        for agent_id, meta in CORE_8_SPECIALISTS.items():
            # Tier-1 classified domain and category
            domain = "clinical"
            category = meta["category"]

            candidates = await full_marketplace_catalog.search_agents(
                domain=domain,
                category=category,
                limit=8,
            )
            assert len(candidates) >= 1
            assert len(candidates) <= 8
            assert candidates[0].id == agent_id


# ============================================================================
# Section 3: Golden Offline Evaluations & Strict Leak Detection
# ============================================================================

def take_skills_snapshot(skills_dir: Path) -> Dict[str, Tuple[int, float]]:
    """Records exact file inventory: relative_path -> (file_size_bytes, mtime)."""
    snapshot: Dict[str, Tuple[int, float]] = {}
    if not skills_dir.is_dir():
        return snapshot
    for root, _, files in os.walk(skills_dir):
        for f in files:
            p = Path(root) / f
            rel = str(p.relative_to(skills_dir))
            stat = p.stat()
            snapshot[rel] = (stat.st_size, stat.st_mtime)
    return snapshot


class TestGoldenOfflineEvalsAndLeakDetection:
    """Empirical tests running all 48 golden eval cases and asserting ZERO file leaks into skills/."""

    @pytest.mark.asyncio
    async def test_all_48_golden_eval_cases_pass_with_zero_skill_leaks(self, temp_workspace: Path):
        """EMPIRICAL VERIFICATION:
        1. Take baseline snapshot of skills/.
        2. Run all 48 golden evaluation cases across all 8 core organ agents.
        3. Confirm 100% pass rate.
        4. Take post-run snapshot of skills/.
        5. Assert exact snapshot identity (0 added, 0 removed, 0 modified files).
        6. Explicitly verify no symptom_log_template.md was created in any organ skill.
        """
        agents_dir = temp_workspace / "agents"
        skills_dir = temp_workspace / "skills"

        # Step 1: Baseline snapshot
        before_snapshot = take_skills_snapshot(skills_dir)
        assert len(before_snapshot) > 0, "Baseline skills directory is empty!"

        total_cases_run = 0
        failed_cases: List[str] = []

        # Step 2: Run all 48 golden evaluations
        for agent_id in CORE_8_SPECIALISTS:
            golden_path = agents_dir / agent_id / "evals" / "golden.jsonl"
            assert golden_path.is_file(), f"Missing golden.jsonl for agent {agent_id}"

            cases: List[EvalCase] = []
            with open(golden_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        cases.append(EvalCase(json.loads(line), golden_path, suite_type="agent"))

            assert len(cases) == 6, f"Agent {agent_id} expected exactly 6 golden cases, found {len(cases)}"

            for case in cases:
                success, msg = await run_single_eval(case, agent_id, temp_workspace, provider="ollama")
                if not success:
                    failed_cases.append(f"{agent_id}/{case.id}: {msg}")
                total_cases_run += 1

        # Step 3: Confirm 48 cases executed with 100% pass rate
        assert total_cases_run == 48, f"Expected 48 golden cases to run, got {total_cases_run}"
        assert len(failed_cases) == 0, f"Golden evaluation failures: {failed_cases}"

        # Step 4: Post-run snapshot
        after_snapshot = take_skills_snapshot(skills_dir)

        # Step 5: Assert zero additions, deletions, or modifications
        added_files = set(after_snapshot.keys()) - set(before_snapshot.keys())
        removed_files = set(before_snapshot.keys()) - set(after_snapshot.keys())
        modified_files = [
            f for f in before_snapshot
            if f in after_snapshot and before_snapshot[f] != after_snapshot[f]
        ]

        assert len(added_files) == 0, f"FILE LEAK DETECTED! New files created in skills/: {added_files}"
        assert len(removed_files) == 0, f"Files unexpectedly removed from skills/: {removed_files}"
        assert len(modified_files) == 0, f"Files unexpectedly modified in skills/: {modified_files}"

        # Step 6: Explicit check for symptom_log_template pollution
        for meta in CORE_8_SPECIALISTS.values():
            skill_id = meta["companion_skill"]
            leaked_template = skills_dir / skill_id / REFERENCES_DIR / "symptom_log_template.md"
            assert not leaked_template.exists(), (
                f"POLLUTION REGRESSION: '{leaked_template}' was created during eval execution!"
            )


# ============================================================================
# Section 4: Penetration Suite Integration
# ============================================================================

class TestPenetrationSuiteIntegration:
    """Verifies that the security & penetration suite passes 100% (47/47 tests)."""

    def test_penetration_suite_passes_all_47_controls(self, repo_root: Path):
        """Runs penetration_suite.py and verifies exit code 0 and 47/47 passed."""
        pentest_script = repo_root / "backend" / "tests" / "penetration_suite.py"
        assert pentest_script.is_file(), f"Missing penetration suite script: {pentest_script}"

        cmd = [sys.executable, str(pentest_script)]
        result = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, (
            f"Penetration suite failed with return code {result.returncode}.\n"
            f"Stdout: {result.stdout[-1000:]}\nStderr: {result.stderr[-500:]}"
        )

        assert "Passed (security controls held): 47" in result.stdout
        assert "Failed (vulnerabilities detected): 0" in result.stdout
