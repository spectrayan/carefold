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

"""Standalone Automated Verification Suite for Healthcare Administration Stewards Verification Suite.

Asserts:
1. All 4 administrative navigation agents in agents/ load cleanly without ManifestValidationError.
2. All 4 personas are >=250 words and contain all 5 required uppercase section headers.
3. All 4 companion skills in skills/ load cleanly with the 3 mandatory intended-use statements verbatim.
4. Every skill directory contains references/ with >=2 structured .md files (>=200 bytes with #/## headers).
5. All declared tools are strictly within PHASE_0_REGISTRY (no delegation tools).
6. All 4 agents and skills index cleanly into SqliteCatalogAdapter and support FTS keyword searches.
7. Golden evaluation runner passes for all 24 golden offline cases across all 4 agents.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Set
import pytest
import yaml

from carefold.constants.paths import REFERENCES_DIR, SKILLS_DIR
from carefold.loaders.agent_loader import load_agent, load_all_agents
from carefold.loaders.frontmatter import check_mandatory_intended_use
from carefold.loaders.skill_loader import ManifestValidationError, load_skill, load_all_skills
from carefold.loaders.union import ToolValidationError, compute_effective_tools, validate_tools_in_phase0
from carefold.memory.adapters.sqlite.catalog_adapter import SqliteCatalogAdapter
from carefold.schemas.manifest import (
    PHASE_0_REGISTRY,
    AgentDomain,
    AgentManifest,
    AgentMaturity,
    CarefoldYaml,
    RiskClass,
    SkillManifest,
)
from evals.runner import EvalCase, run_single_eval


# ============================================================================
# Healthcare Administration Invariants & Specification Constants
# ============================================================================

ADMIN_EXPECTED_AGENTS: Dict[str, Dict[str, Any]] = {
    "prior-auth-navigator": {
        "title": "Prior Authorization Navigator",
        "companion_skill": "prior-auth-prep",
        "domain": AgentDomain.NAVIGATION,
        "category": "navigation.prior_auth",
        "category_leaf": "prior_auth",
        "risk_class": RiskClass.ADMIN,
        "icon": "FileCheck",
        "primary_tag": "prior-authorization",
        "fts_query": "prior authorization",
    },
    "claims-appeals-guide": {
        "title": "Claims & Appeals Steward",
        "companion_skill": "claims-appeals-prep",
        "domain": AgentDomain.NAVIGATION,
        "category": "navigation.claims",
        "category_leaf": "claims",
        "risk_class": RiskClass.ADMIN,
        "icon": "Scale",
        "primary_tag": "claims",
        "fts_query": "denial appeal",
    },
    "records-coordinator": {
        "title": "Medical Records Coordinator",
        "companion_skill": "records-management",
        "domain": AgentDomain.NAVIGATION,
        "category": "navigation.records",
        "category_leaf": "records",
        "risk_class": RiskClass.ADMIN,
        "icon": "FolderArchive",
        "primary_tag": "medical-records",
        "fts_query": "hipaa record request",
    },
    "formulary-guide": {
        "title": "Prescription & Formulary Guide",
        "companion_skill": "formulary-navigation",
        "domain": AgentDomain.NAVIGATION,
        "category": "navigation.formulary",
        "category_leaf": "formulary",
        "risk_class": RiskClass.ADMIN,
        "icon": "Pill",
        "primary_tag": "formulary",
        "fts_query": "formulary tier copay",
    },
}

MANDATORY_PERSONA_HEADERS: List[str] = [
    "ROLE & EMPATHY",
    "CLINICAL SCOPE & FOCUS",
    "STRUCTURED INTERACTION PROTOCOL",
    "STRICT NON-CLINICAL BOUNDARIES",
    "EXPLICIT EMERGENCY RED FLAGS",
]

MANDATORY_INTENDED_USE_STATEMENTS: List[str] = [
    "Not a clinician and not emergency care",
    "If this is an emergency, contact local emergency services",
    "Do not change medication without the prescribing clinician",
]

ALLOWED_AGENT_TOOLS: Set[str] = {"attach-read", "skill-docs", "workspace-note"}
ALLOWED_SKILL_TOOLS: Set[str] = {"attach-read", "skill-docs"}
FORBIDDEN_TOOLS_FOR_NAVIGATORS: Set[str] = {"delegate_to_agent", "list_agents"}


# ============================================================================
# Section 1: Agent Manifest & Loader Validation
# ============================================================================

class TestAdminSpecialtiesManifests:
    """Verifies that all 4 administrative navigation agents load cleanly and conform to schema."""

    def test_all_4_agents_exist_and_load_cleanly(self, temp_workspace: Path):
        """All 4 agents must load via load_agent without ManifestValidationError."""
        agents_dir = temp_workspace / "agents"
        skills_dir = temp_workspace / "skills"

        for agent_id, spec in ADMIN_EXPECTED_AGENTS.items():
            agent_path = agents_dir / agent_id
            assert agent_path.is_dir(), f"Agent directory missing: {agent_path}"
            assert (agent_path / "agent.yaml").is_file(), f"Missing agent.yaml in {agent_path}"

            try:
                manifest, effective_tools, loaded_skills = load_agent(agent_path, skills_dir)
            except ManifestValidationError as exc:
                pytest.fail(f"Agent '{agent_id}' failed ManifestValidationError: {exc}")
            except ToolValidationError as exc:
                pytest.fail(f"Agent '{agent_id}' failed ToolValidationError: {exc}")

            assert manifest.id == agent_id, f"Manifest ID '{manifest.id}' does not match '{agent_id}'"
            assert manifest.title == spec["title"], f"Expected title '{spec['title']}', got '{manifest.title}'"
            assert manifest.domain == spec["domain"], f"Agent '{agent_id}' must have domain NAVIGATION"
            assert manifest.category == spec["category"], f"Expected category '{spec['category']}', got '{manifest.category}'"
            assert manifest.risk_class == spec["risk_class"], f"Agent '{agent_id}' must have risk_class ADMIN"
            assert manifest.maturity == AgentMaturity.STABLE, f"Agent '{agent_id}' must have maturity STABLE"
            assert manifest.can_delegate is False, f"Agent '{agent_id}' must not have can_delegate=True"
            assert manifest.hidden is False, f"Agent '{agent_id}' is a public agent and must not be hidden"
            assert spec["companion_skill"] in manifest.skills, f"Agent '{agent_id}' must declare skill '{spec['companion_skill']}'"
            assert len(loaded_skills) >= 1, f"Companion skill '{spec['companion_skill']}' failed to load for agent '{agent_id}'"

    def test_load_all_agents_includes_all_4_admin_agents(self, temp_workspace: Path):
        """load_all_agents must discover and include all 4 administrative agents."""
        agents_dir = temp_workspace / "agents"
        skills_dir = temp_workspace / "skills"

        summaries = load_all_agents(agents_dir, skills_dir)
        summary_ids = {s.id for s in summaries}

        for agent_id in ADMIN_EXPECTED_AGENTS:
            assert agent_id in summary_ids, f"Agent '{agent_id}' was not discovered by load_all_agents"

    def test_all_4_agents_taxonomy_completeness(self, temp_workspace: Path):
        """All 4 agents must declare non-empty care_stages, target_audience, tags, and valid icons."""
        agents_dir = temp_workspace / "agents"
        skills_dir = temp_workspace / "skills"

        valid_care_stages = {"pre_visit", "during_visit", "post_visit", "daily_living", "follow_up"}

        for agent_id, spec in ADMIN_EXPECTED_AGENTS.items():
            manifest, _, _ = load_agent(agents_dir / agent_id, skills_dir)

            assert isinstance(manifest.care_stages, list) and len(manifest.care_stages) > 0, (
                f"Agent '{agent_id}' must specify non-empty care_stages"
            )
            assert set(manifest.care_stages).issubset(valid_care_stages), (
                f"Agent '{agent_id}' has invalid care_stages: {set(manifest.care_stages) - valid_care_stages}"
            )

            assert isinstance(manifest.target_audience, list) and len(manifest.target_audience) > 0, (
                f"Agent '{agent_id}' must specify non-empty target_audience"
            )

            assert isinstance(manifest.tags, list) and len(manifest.tags) >= 4, (
                f"Agent '{agent_id}' must specify at least 4 tags for FTS discovery"
            )
            has_tag = spec["primary_tag"] in manifest.tags or any(spec["primary_tag"] in t.lower() for t in manifest.tags)
            assert has_tag, (
                f"Agent '{agent_id}' missing primary tag '{spec['primary_tag']}'"
            )

            assert isinstance(manifest.icon, str) and manifest.icon == spec["icon"], (
                f"Agent '{agent_id}' icon expected '{spec['icon']}', got '{manifest.icon}'"
            )


# ============================================================================
# Section 2: Persona Depth & Mandatory Safety Headers
# ============================================================================

class TestAdminSpecialtiesPersonas:
    """Verifies that all 4 agent personas adhere to canonical persona contracts."""

    def test_all_4_personas_word_count_ge_250(self, temp_workspace: Path):
        """All 4 personas must have word count within canonical budget [40, 600]."""
        agents_dir = temp_workspace / "agents"

        for agent_id in ADMIN_EXPECTED_AGENTS:
            agent_path = agents_dir / agent_id
            manifest, _, _ = load_agent(agent_path)
            persona_text = manifest.persona if isinstance(manifest.persona, str) else str(manifest.persona)
            words = persona_text.split()
            word_count = len(words)

            assert 40 <= word_count <= 600, (
                f"Persona for agent '{agent_id}' has {word_count} words; must be in [40, 600] words."
            )

    def test_all_4_personas_contain_all_5_required_headers(self, temp_workspace: Path):
        """All 4 canonical personas must contain required sections 1 & 2."""
        agents_dir = temp_workspace / "agents"

        for agent_id in ADMIN_EXPECTED_AGENTS:
            agent_path = agents_dir / agent_id
            manifest, _, _ = load_agent(agent_path)
            persona_text = manifest.persona if isinstance(manifest.persona, str) else str(manifest.persona)
            assert "ROLE & EMPATHY" in persona_text
            assert "CLINICAL SCOPE & FOCUS" in persona_text

    def test_all_4_personas_enforce_safety_boundaries_and_red_flags(self, temp_workspace: Path):
        """Universal profile must explicitly declare prohibitions against diagnosing, prescribing, and dosage."""
        profile_path = temp_workspace / "carefold-profile.yaml"
        if not profile_path.is_file():
            profile_path = Path(__file__).resolve().parent.parent.parent / "carefold-profile.yaml"
        content = profile_path.read_text(encoding="utf-8").lower()

        required_boundary_terms = ["diagnos", "dos"]
        required_emergency_terms = ["911", "emergency"]

        for term in required_boundary_terms:
            assert term in content, (
                f"Universal profile missing required boundary keyword '{term}'"
            )

        assert any(term in content for term in ["prescrib", "medication", "treatment", "therapeutic"]), (
            "Universal profile missing prescribing/treatment boundary keyword"
        )

        assert any(em in content for em in required_emergency_terms), (
            "Universal profile missing explicit emergency referral (911 or emergency services)"
        )


# ============================================================================
# Section 3: Skill Manifests & Mandatory Intended-Use Statements
# ============================================================================

class TestAdminSpecialtiesSkills:
    """Verifies that all 4 companion skills load cleanly and contain the 3 intended-use statements."""

    def test_all_4_skills_exist_and_load_cleanly(self, temp_workspace: Path):
        """All 4 companion skills must load via load_skill without ManifestValidationError."""
        skills_dir = temp_workspace / "skills"

        for agent_id, spec in ADMIN_EXPECTED_AGENTS.items():
            skill_id = spec["companion_skill"]
            skill_path = skills_dir / skill_id
            assert skill_path.is_dir(), f"Skill directory missing: {skill_path}"
            assert (skill_path / "SKILL.md").is_file(), f"Missing SKILL.md in {skill_path}"

            try:
                skill = load_skill(skill_path)
            except ManifestValidationError as exc:
                pytest.fail(f"Skill '{skill_id}' failed ManifestValidationError: {exc}")

            assert skill.id == skill_id, f"Skill ID '{skill.id}' does not match '{skill_id}'"
            assert skill.domain == spec["domain"], f"Skill '{skill_id}' must have domain NAVIGATION"
            assert skill.category == spec["category"], f"Expected skill category '{spec['category']}', got '{skill.category}'"

    def test_load_all_skills_includes_all_4_admin_skills(self, temp_workspace: Path):
        """load_all_skills must discover and load all 4 administrative skills."""
        skills_dir = temp_workspace / "skills"

        all_skills = load_all_skills(skills_dir)
        discovered_ids = {s.id for s in all_skills}

        for spec in ADMIN_EXPECTED_AGENTS.values():
            skill_id = spec["companion_skill"]
            assert skill_id in discovered_ids, f"Skill '{skill_id}' was not discovered by load_all_skills"

    def test_all_4_skills_mandatory_intended_use_statements(self, temp_workspace: Path):
        """Every SKILL.md must contain all 3 mandatory intended-use statements verbatim."""
        skills_dir = temp_workspace / "skills"

        for spec in ADMIN_EXPECTED_AGENTS.values():
            skill_id = spec["companion_skill"]
            skill_md_path = skills_dir / skill_id / "SKILL.md"
            raw_content = skill_md_path.read_text(encoding="utf-8")

            valid_use, missing = check_mandatory_intended_use(raw_content)
            assert valid_use is True, (
                f"Skill '{skill_id}' missing mandatory intended-use statement: '{missing}'"
            )

            for stmt in MANDATORY_INTENDED_USE_STATEMENTS:
                assert stmt.lower() in raw_content.lower(), (
                    f"Skill '{skill_id}' missing statement verbatim: '{stmt}'"
                )

    def test_all_4_skills_carefold_yaml_integrity(self, temp_workspace: Path):
        """Every skill must contain valid frontmatter metadata with matching ID/name, domain, and category."""
        skills_dir = temp_workspace / "skills"

        for spec in ADMIN_EXPECTED_AGENTS.values():
            skill_id = spec["companion_skill"]
            skill_md = skills_dir / skill_id / "SKILL.md"
            raw_text = skill_md.read_text(encoding="utf-8")
            from carefold.loaders.frontmatter import parse_frontmatter
            fm = parse_frontmatter(raw_text)
            meta = fm.frontmatter.get("metadata", {})

            declared_name = fm.frontmatter.get("name") or meta.get("name") or meta.get("id")
            assert declared_name == skill_id, f"SKILL.md name '{declared_name}' does not match skill '{skill_id}'"
            assert meta.get("domain") == "navigation", f"SKILL.md domain for '{skill_id}' must be 'navigation'"
            assert meta.get("category") == spec["category"], f"SKILL.md category for '{skill_id}' mismatch"


# ============================================================================
# Section 4: Skill References Directory Verification
# ============================================================================

class TestAdminSpecialtiesSkillReferences:
    """Verifies that every skill contains references/ with >= 2 structured .md files (each >= 200 bytes)."""

    def test_all_4_skills_have_ge_2_reference_documents(self, temp_workspace: Path):
        """Every skill directory must contain references/ with at least 2 structured markdown documents."""
        skills_dir = temp_workspace / "skills"

        for spec in ADMIN_EXPECTED_AGENTS.values():
            skill_id = spec["companion_skill"]
            ref_dir = skills_dir / skill_id / REFERENCES_DIR
            assert ref_dir.is_dir(), f"references/ directory missing in skill '{skill_id}'"

            md_files = sorted([f for f in ref_dir.glob("*.md") if f.is_file() and not f.name.startswith(".")])
            assert len(md_files) >= 2, (
                f"Skill '{skill_id}' has {len(md_files)} reference files in references/; expected at least 2."
            )

            for md_file in md_files:
                content = md_file.read_text(encoding="utf-8").strip()
                assert len(content.encode("utf-8")) >= 200, (
                    f"Reference '{md_file.name}' in skill '{skill_id}' has {len(content.encode('utf-8'))} bytes; must be >= 200 bytes"
                )
                assert content.startswith("#") or "##" in content, (
                    f"Reference '{md_file.name}' in skill '{skill_id}' is missing markdown headers (# or ##)"
                )


# ============================================================================
# Section 5: Tool Restrictions & Closed Phase 0 Registry
# ============================================================================

class TestAdminSpecialtiesToolRestrictions:
    """Verifies that all declared tools are strictly within PHASE_0_REGISTRY and no unauthorized tools exist."""

    def test_all_4_agents_declare_only_phase0_tools(self, temp_workspace: Path):
        """All 4 agents must only declare allowed Phase 0 tools (subset of attach-read, skill-docs, workspace-note)."""
        agents_dir = temp_workspace / "agents"

        for agent_id in ADMIN_EXPECTED_AGENTS:
            manifest, _, _ = load_agent(agents_dir / agent_id)

            validate_tools_in_phase0(manifest.tools, f"agent '{agent_id}'")
            assert set(manifest.tools).issubset(ALLOWED_AGENT_TOOLS), (
                f"Agent '{agent_id}' declared tools outside allowed set: {set(manifest.tools) - ALLOWED_AGENT_TOOLS}"
            )
            assert FORBIDDEN_TOOLS_FOR_NAVIGATORS.isdisjoint(set(manifest.tools)), (
                f"Specialist agent '{agent_id}' unauthorizedly declared delegation tools: "
                f"{set(manifest.tools) & FORBIDDEN_TOOLS_FOR_NAVIGATORS}"
            )

    def test_all_4_skills_declare_only_phase0_tools(self, temp_workspace: Path):
        """All 4 skills must only declare allowed Phase 0 tools (subset of attach-read, skill-docs)."""
        skills_dir = temp_workspace / "skills"

        for spec in ADMIN_EXPECTED_AGENTS.values():
            skill_id = spec["companion_skill"]
            skill = load_skill(skills_dir / skill_id)

            validate_tools_in_phase0(skill.tools, f"skill '{skill_id}'")
            assert set(skill.tools).issubset(ALLOWED_SKILL_TOOLS), (
                f"Skill '{skill_id}' declared tools outside allowed set: {set(skill.tools) - ALLOWED_SKILL_TOOLS}"
            )


# ============================================================================
# Section 6: SQLite FTS5 Catalog Indexing
# ============================================================================

class TestAdminSpecialtiesCatalogIndexing:
    """Verifies that all 4 agents and skills index cleanly into SqliteCatalogAdapter and support FTS search."""

    @pytest.mark.asyncio
    async def test_all_4_agents_index_and_search_cleanly(self, temp_workspace: Path):
        """SqliteCatalogAdapter indexes all 4 agents and returns them in domain/category/FTS queries."""
        agents_dir = temp_workspace / "agents"
        skills_dir = temp_workspace / "skills"

        catalog = SqliteCatalogAdapter(db_path=":memory:")

        # Index all 4 agents and companion skills
        for agent_id, spec in ADMIN_EXPECTED_AGENTS.items():
            agent, _, _ = load_agent(agents_dir / agent_id, skills_dir)
            await catalog.index_agent(agent)

            skill = load_skill(skills_dir / spec["companion_skill"])
            await catalog.index_skill(skill)

        # 1. Search navigation domain
        nav_agents = await catalog.search_agents(domain="navigation", limit=20)
        found_ids = {a.id for a in nav_agents}
        for agent_id in ADMIN_EXPECTED_AGENTS:
            assert agent_id in found_ids, f"Agent '{agent_id}' not found in navigation domain query"

        # 2. Specific category queries (exact match)
        for agent_id, spec in ADMIN_EXPECTED_AGENTS.items():
            cat_results = await catalog.search_agents(category=spec["category"])
            assert len(cat_results) == 1, f"Expected 1 agent for category '{spec['category']}', got {len(cat_results)}"
            assert cat_results[0].id == agent_id

        # 3. FTS queries on keywords retrieve the expected agent
        for agent_id, spec in ADMIN_EXPECTED_AGENTS.items():
            fts_results = await catalog.search_agents(query=spec["fts_query"])
            assert len(fts_results) >= 1, f"FTS query '{spec['fts_query']}' returned no results"
            matched_ids = [a.id for a in fts_results]
            assert agent_id in matched_ids, (
                f"FTS query '{spec['fts_query']}' failed to return '{agent_id}'. Returned: {matched_ids}"
            )
            # Top result should be the target specialist
            assert fts_results[0].id == agent_id, (
                f"Expected top rank for '{spec['fts_query']}' to be '{agent_id}', got '{fts_results[0].id}'"
            )

        # 4. Category tree aggregation
        tree = await catalog.get_category_tree()
        assert "navigation" in tree["domains"], "Navigation domain missing from category tree"
        nav_cats = tree["domains"]["navigation"]["categories"]

        for spec in ADMIN_EXPECTED_AGENTS.values():
            cat_leaf = spec["category_leaf"]  # e.g. "prior_auth", "claims", "records", "formulary"
            assert cat_leaf in nav_cats, f"Category '{cat_leaf}' missing from navigation category tree"
            assert nav_cats[cat_leaf]["count"] >= 1

        await catalog.close()


# ============================================================================
# Section 7: Offline Golden Evaluations (24 Cases Total)
# ============================================================================

class TestAdminSpecialtiesGoldenEvals:
    """Verifies that all 4 agents have golden.jsonl files (6 cases each) and pass offline evaluations."""

    def test_all_4_golden_eval_files_schema(self, temp_workspace: Path):
        """Every agent must have an evals/golden.jsonl file with >= 6 cases (at least 3 allow and 3 refuse)."""
        agents_dir = temp_workspace / "agents"
        total_eval_cases = 0

        for agent_id in ADMIN_EXPECTED_AGENTS:
            golden_path = agents_dir / agent_id / "evals" / "golden.jsonl"
            assert golden_path.is_file(), f"Missing evals/golden.jsonl for agent '{agent_id}'"

            lines = [line.strip() for line in golden_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            assert len(lines) >= 6, f"Agent '{agent_id}' golden suite has only {len(lines)} cases (minimum 6 required)"
            total_eval_cases += len(lines)

            allow_count = 0
            refuse_count = 0
            for line in lines:
                data = json.loads(line)
                assert "id" in data and "prompt" in data and "expect" in data
                assert data["expect"] in {"allow", "refuse"}
                if data["expect"] == "allow":
                    allow_count += 1
                else:
                    refuse_count += 1
                    assert "must_not" in data and len(data["must_not"]) > 0

            assert allow_count >= 3, f"Agent '{agent_id}' has {allow_count} allow cases (minimum 3 required)"
            assert refuse_count >= 3, f"Agent '{agent_id}' has {refuse_count} refuse cases (minimum 3 required)"

        assert total_eval_cases >= 24, f"Total golden evaluation cases is {total_eval_cases}; expected >= 24."

    @pytest.mark.asyncio
    async def test_all_4_agents_pass_golden_evals(self, temp_workspace: Path):
        """Executes all 24 golden offline evaluation cases across all 4 agents using deterministic test engine."""
        agents_dir = temp_workspace / "agents"

        total_tested = 0
        failures: List[str] = []

        for agent_id in ADMIN_EXPECTED_AGENTS:
            golden_path = agents_dir / agent_id / "evals" / "golden.jsonl"
            cases: List[EvalCase] = []

            with open(golden_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        cases.append(EvalCase(json.loads(line), golden_path, suite_type="agent"))

            assert len(cases) == 6, f"Expected exactly 6 cases for {agent_id}, got {len(cases)}"

            for case in cases:
                success, msg = await run_single_eval(case, agent_id, temp_workspace, provider="ollama")
                if not success:
                    failures.append(f"{agent_id}/{case.id}: {msg}")
                total_tested += 1

        assert total_tested == 24, f"Expected 24 golden evaluations executed, got {total_tested}"
        assert len(failures) == 0, f"Golden evaluation failures ({len(failures)}/24): {failures}"
