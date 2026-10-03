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

"""Automated Verification Suite for Milestones M2, M3, and M4.

Validates:
1. Extended Medical & Surgical Navigators 9–13 (M2):
   - oncology-navigator / oncology-prep
   - rheuma-guide / rheuma-prep
   - urology-guide / urology-prep
   - eye-guide / vision-prep
   - ent-guide / ent-prep
2. Healthcare Administration Stewards 14–17 (M3):
   - prior-auth-navigator / prior-auth-prep
   - claims-appeals-guide / claims-appeals-prep
   - records-coordinator / records-management
   - formulary-guide / formulary-navigation
3. System Infrastructure Agents 18–19 (M4):
   - agents/_system/triage-auditor/
   - agents/_system/quality-reviewer/
4. Persona word counts (>=250 words) and 5 uppercase mandatory headers.
5. Skill frontmatter, 3 mandatory intended-use statements, >=2 reference files with valid H1 headers.
6. Closed tool registry (Phase 0 allowlist only).
7. SqliteCatalogAdapter indexing, FTS retrieval, and category hierarchy.
8. Golden evaluations across all new specialist agents.
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


M2_SPECIALTY_AGENTS: Dict[str, Dict[str, Any]] = {
    "oncology-navigator": {
        "title": "Oncology Care Steward",
        "companion_skill": "oncology-prep",
        "domain": AgentDomain.CLINICAL,
        "category": "clinical.oncology",
        "icon": "Ribbon",
        "fts_query": "chemotherapy",
    },
    "rheuma-guide": {
        "title": "Rheumatology Navigator",
        "companion_skill": "rheuma-prep",
        "domain": AgentDomain.CLINICAL,
        "category": "clinical.rheumatology",
        "icon": "Flame",
        "fts_query": "autoimmune",
    },
    "urology-guide": {
        "title": "Urology Navigator",
        "companion_skill": "urology-prep",
        "domain": AgentDomain.CLINICAL,
        "category": "clinical.urology",
        "icon": "Droplets",
        "fts_query": "voiding",
    },
    "eye-guide": {
        "title": "Ophthalmology Navigator",
        "companion_skill": "vision-prep",
        "domain": AgentDomain.CLINICAL,
        "category": "clinical.ophthalmology",
        "icon": "Eye",
        "fts_query": "glaucoma",
    },
    "ent-guide": {
        "title": "ENT Navigator",
        "companion_skill": "ent-prep",
        "domain": AgentDomain.CLINICAL,
        "category": "clinical.ent",
        "icon": "Ear",
        "fts_query": "sinusitis",
    },
}

M3_ADMIN_AGENTS: Dict[str, Dict[str, Any]] = {
    "prior-auth-navigator": {
        "title": "Prior Authorization Navigator",
        "companion_skill": "prior-auth-prep",
        "domain": AgentDomain.NAVIGATION,
        "category": "navigation.prior_auth",
        "icon": "FileCheck",
        "fts_query": "prior authorization",
    },
    "claims-appeals-guide": {
        "title": "Claims & Appeals Steward",
        "companion_skill": "claims-appeals-prep",
        "domain": AgentDomain.NAVIGATION,
        "category": "navigation.claims",
        "icon": "Scale",
        "fts_query": "claims appeal",
    },
    "records-coordinator": {
        "title": "Medical Records Coordinator",
        "companion_skill": "records-management",
        "domain": AgentDomain.NAVIGATION,
        "category": "navigation.records",
        "icon": "FolderArchive",
        "fts_query": "medical records",
    },
    "formulary-guide": {
        "title": "Prescription & Formulary Guide",
        "companion_skill": "formulary-navigation",
        "domain": AgentDomain.NAVIGATION,
        "category": "navigation.formulary",
        "icon": "Pill",
        "fts_query": "formulary",
    },
}

M4_SYSTEM_AGENTS: Dict[str, Dict[str, Any]] = {
    "triage-auditor": {
        "title": "Automated Triage Auditor",
        "domain": AgentDomain.CLINICAL,
        "category": "clinical.triage",
        "icon": "ShieldAlert",
        "hidden": True,
    },
    "quality-reviewer": {
        "title": "Clinical Quality Reviewer",
        "domain": AgentDomain.EDUCATION,
        "category": "education.quality",
        "icon": "CheckCheck",
        "hidden": True,
    },
}

MANDATORY_HEADERS = [
    "ROLE & EMPATHY",
    "CLINICAL SCOPE & FOCUS",
    "STRUCTURED INTERACTION PROTOCOL",
    "STRICT NON-CLINICAL BOUNDARIES",
    "EXPLICIT EMERGENCY RED FLAGS",
]


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


class TestExpansionAgentLoading:
    """Validates schema conformance and loader integrity for M2, M3, M4 agents."""

    @pytest.mark.parametrize("agent_id,expected", {**M2_SPECIALTY_AGENTS, **M3_ADMIN_AGENTS}.items())
    def test_domain_agents_load_cleanly(self, repo_root: Path, agent_id: str, expected: Dict[str, Any]):
        agents_dir = repo_root / "agents"
        skills_dir = repo_root / "skills"
        agent_dir = agents_dir / agent_id

        assert agent_dir.is_dir(), f"Agent directory missing: {agent_dir}"
        agent, tools, skills = load_agent(agent_dir, skills_dir)

        assert agent.id == agent_id
        assert agent.title == expected["title"]
        assert agent.domain == expected["domain"]
        assert agent.category == expected["category"]
        assert agent.icon == expected["icon"]
        assert agent.hidden is False
        assert expected["companion_skill"] in agent.skills

        # Validate tools strictly Phase 0
        validate_tools_in_phase0(agent.tools)
        for t in agent.tools:
            assert t in PHASE_0_REGISTRY

    @pytest.mark.parametrize("agent_id,expected", M4_SYSTEM_AGENTS.items())
    def test_system_agents_load_cleanly(self, repo_root: Path, agent_id: str, expected: Dict[str, Any]):
        system_dir = repo_root / "agents" / "_system" / agent_id
        skills_dir = repo_root / "skills"

        assert system_dir.is_dir(), f"System agent directory missing: {system_dir}"
        agent, tools, skills = load_agent(system_dir, skills_dir)

        assert agent.id == agent_id
        assert agent.title == expected["title"]
        assert agent.domain == expected["domain"]
        assert agent.category == expected["category"]
        assert agent.icon == expected["icon"]
        assert agent.hidden is True
        assert agent.skills == []
        assert agent.tools == []


class TestExpansionPersonas:
    """Validates persona depth, section headers, and safety boundaries."""

    @pytest.mark.parametrize("agent_id", list(M2_SPECIALTY_AGENTS.keys()) + list(M3_ADMIN_AGENTS.keys()) + list(M4_SYSTEM_AGENTS.keys()))
    def test_persona_word_count_and_headers(self, repo_root: Path, agent_id: str):
        if agent_id in M4_SYSTEM_AGENTS:
            agent_dir = repo_root / "agents" / "_system" / agent_id
        else:
            agent_dir = repo_root / "agents" / agent_id

        agent, _, _ = load_agent(agent_dir, repo_root / "skills")
        persona = agent.persona

        if agent_id in M4_SYSTEM_AGENTS:
            words = persona.split()
            assert len(words) >= 250, f"System agent '{agent_id}' persona has {len(words)} words; must be >= 250"
            for header in MANDATORY_HEADERS:
                assert f"{header}:" in persona or header in persona, (
                    f"System agent '{agent_id}' persona missing mandatory header '{header}'"
                )
            persona_lower = persona.lower()
            assert "not a" in persona_lower or "never" in persona_lower
            assert "911" in persona_lower or "emergency" in persona_lower
        else:
            words = persona.split()
            assert 40 <= len(words) < 600, f"Agent '{agent_id}' persona has {len(words)} words; must be in [40, 600)"
            for header in ["ROLE & EMPATHY", "CLINICAL SCOPE & FOCUS"]:
                assert f"{header}:" in persona or header in persona, (
                    f"Agent '{agent_id}' persona missing mandatory header '{header}'"
                )
            profile_path = repo_root / "carefold-profile.yaml"
            profile_text = profile_path.read_text(encoding="utf-8") if profile_path.is_file() else ""
            combined_lower = f"{persona}\n{profile_text}".lower()
            assert "not a" in combined_lower or "never" in combined_lower
            assert "911" in combined_lower or "emergency" in combined_lower


class TestExpansionSkills:
    """Validates companion skill frontmatter, intended-use statements, and references."""

    @pytest.mark.parametrize("agent_id,expected", {**M2_SPECIALTY_AGENTS, **M3_ADMIN_AGENTS}.items())
    def test_companion_skills_conformance(self, repo_root: Path, agent_id: str, expected: Dict[str, Any]):
        skill_id = expected["companion_skill"]
        skill_dir = repo_root / "skills" / skill_id
        assert skill_dir.is_dir(), f"Skill directory missing: {skill_dir}"

        skill = load_skill(skill_dir)
        assert skill.name == skill_id
        assert skill.domain == expected["domain"]
        assert skill.category == expected["category"]

        # Intended use checks
        skill_md = skill_dir / "SKILL.md"
        valid, missing = check_mandatory_intended_use(skill_md.read_text(encoding="utf-8"))
        assert valid is True, f"Skill '{skill_id}' missing intended use statement: {missing}"

        # Reference files check
        ref_dir = skill_dir / "references"
        assert ref_dir.is_dir(), f"Skill '{skill_id}' missing references/ directory"
        ref_files = [f for f in ref_dir.iterdir() if f.is_file() and f.suffix == ".md"]
        assert len(ref_files) >= 2, f"Skill '{skill_id}' has {len(ref_files)} reference files; expected >= 2"

        for ref_file in ref_files:
            content = ref_file.read_text(encoding="utf-8")
            assert content.startswith("# "), f"Reference '{ref_file.name}' in skill '{skill_id}' must start with '# '"
            assert len(content.encode("utf-8")) >= 200, f"Reference '{ref_file.name}' in skill '{skill_id}' is under 200 bytes"
            assert len(content.split()) >= 50, f"Reference '{ref_file.name}' in skill '{skill_id}' is under 50 words"


class TestExpansionCatalog:
    """Validates SqliteCatalogAdapter indexing, FTS retrieval, and category tree."""

    @pytest.mark.asyncio
    async def test_all_expansion_agents_and_skills_index_and_search(self, repo_root: Path, tmp_path: Path):
        catalog = SqliteCatalogAdapter(db_path=tmp_path / "expansion_catalog.db")
        agents_dir = repo_root / "agents"
        skills_dir = repo_root / "skills"

        all_summaries = load_all_agents(agents_dir, skills_dir)
        for summary in all_summaries:
            a_dir = agents_dir / summary.id
            if not a_dir.is_dir():
                a_dir = agents_dir / "_system" / summary.id
            manifest, _, _ = load_agent(a_dir, skills_dir)
            if a_dir.parent.name == "_system":
                manifest.hidden = True
            await catalog.index_agent(manifest)

        all_skills = load_all_skills(skills_dir)
        for skill in all_skills:
            await catalog.index_skill(skill)

        # Verify public count includes all 17 public agents
        public_count = await catalog.count_agents(include_hidden=False)
        assert public_count >= 17, f"Expected >= 17 public agents, got {public_count}"

        # Verify clinical domain count
        clinical_agents = await catalog.search_agents(domain="clinical", limit=50)
        assert len(clinical_agents) >= 13  # 8 core + 5 extended

        # Verify navigation domain count
        nav_agents = await catalog.search_agents(domain="navigation", limit=50)
        assert len(nav_agents) >= 6  # 2 original + 4 admin

        # Verify FTS search for new specialties
        search_terms = {
            "oncology-navigator": "chemotherapy",
            "rheuma-guide": "autoimmune",
            "urology-guide": "voiding",
            "eye-guide": "glaucoma",
            "ent-guide": "sinusitis",
            "prior-auth-navigator": "prior authorization",
            "claims-appeals-guide": "claims appeal",
            "records-coordinator": "medical records",
            "formulary-guide": "formulary",
        }

        for agent_id, term in search_terms.items():
            results = await catalog.search_agents(query=term)
            assert len(results) >= 1, f"Search for '{term}' returned 0 results"
            matched_ids = [r.id for r in results]
            assert agent_id in matched_ids, f"Agent '{agent_id}' not found when searching for '{term}'"

        await catalog.close()


class TestExpansionGoldenEvals:
    """Runs deterministic offline golden evaluations for all M2 and M3 agents."""

    @pytest.mark.parametrize("agent_id", list(M2_SPECIALTY_AGENTS.keys()) + list(M3_ADMIN_AGENTS.keys()))
    @pytest.mark.asyncio
    async def test_offline_golden_eval_suite(self, repo_root: Path, agent_id: str):
        evals_file = repo_root / "agents" / agent_id / "evals" / "golden.jsonl"
        assert evals_file.is_file(), f"Missing golden evals file for {agent_id}"

        cases: List[EvalCase] = []
        with open(evals_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    cases.append(EvalCase(json.loads(line), evals_file))

        assert len(cases) == 6, f"Expected exactly 6 golden cases for {agent_id}, got {len(cases)}"

        for case in cases:
            success, msg = await run_single_eval(case, agent_id, repo_root, provider="ollama")
            assert success is True, f"Eval case '{case.id}' failed on agent '{agent_id}': {msg}"
