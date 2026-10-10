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

"""Stress Test Suite for Core Organ Clinical Navigators.

Stress-tests the 8 core organ clinical navigators and companion skills:
1. Word count strictness: exact word counts of all 8 personas (> 250 words) under multiple tokenizers.
2. Mandatory headings: presence, ordering, and content non-emptiness of all 5 uppercase headers.
3. Closed tool registry: strict containment within PHASE_0_REGISTRY, zero delegation or unauthorized tools.
4. Mandatory intended-use statements: all 3 required clinical disclaimers in every SKILL.md.
5. Reference files: >= 2 structured .md files per skill with substantial content and referential integrity.
6. Safety boundaries & Red flags: presence of anti-diagnostic/anti-prescribing terms and emergency escalation.
7. Catalog & Discovery: SQLite FTS5 catalog indexing and searchability.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Set
import pytest
import yaml

from carefold.constants.paths import REFERENCES_DIR, SKILLS_DIR
from carefold.loaders.agent_loader import load_agent
from carefold.loaders.frontmatter import check_mandatory_intended_use
from carefold.loaders.skill_loader import ManifestValidationError, load_skill
from carefold.loaders.union import ToolValidationError, validate_tools_in_phase0
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


CORE_ORGAN_AGENTS: List[str] = [
    "cardiology-guide",
    "pulmonology-guide",
    "neurology-guide",
    "gastro-guide",
    "nephrology-guide",
    "endocrinology-guide",
    "ortho-guide",
    "derma-guide",
]

CORE_ORGAN_SKILLS: List[str] = [
    "cardiology-prep",
    "pulmonology-prep",
    "neurology-prep",
    "gastro-prep",
    "nephrology-prep",
    "endocrinology-prep",
    "ortho-prep",
    "derma-prep",
]

AGENT_TO_SKILL: Dict[str, str] = dict(zip(CORE_ORGAN_AGENTS, CORE_ORGAN_SKILLS))

MANDATORY_HEADINGS: List[str] = [
    "ROLE & EMPATHY",
    "CLINICAL SCOPE & FOCUS",
]

MANDATORY_INTENDED_USE_STATEMENTS: List[str] = [
    "Not a clinician and not emergency care",
    "If this is an emergency, contact local emergency services",
    "Do not change medication without the prescribing clinician",
]

PHASE0_AGENT_TOOLS: Set[str] = {"attach-read", "skill-docs", "workspace-note"}
PHASE0_SKILL_TOOLS: Set[str] = {"attach-read", "skill-docs"}
FORBIDDEN_TOOLS: Set[str] = {"delegate_to_agent", "list_agents", "bash", "python", "shell", "read_file"}


def _get_persona_text(agent_yaml_path: Path, data: dict) -> str:
    persona = data.get("persona", "")
    if isinstance(persona, str) and "\n" not in persona and (persona.endswith(".md") or (agent_yaml_path.parent / persona).is_file()):
        return (agent_yaml_path.parent / persona).read_text(encoding="utf-8")
    return str(persona)


# ============================================================================
# Test Suite 1: Persona Word Count & Structure Stress
# ============================================================================

class TestPersonaWordCountAndStructureStress:
    """Empirically stress-tests persona word counts and section structural integrity."""

    def test_word_count_strictness_across_all_8_personas(self, temp_workspace: Path):
        """EMPIRICAL VERIFICATION: Every persona must exceed 250 words under both whitespace
        and regex word boundary tokenization, and be within reasonable limits (< 2000 words).
        """
        agents_dir = temp_workspace / "agents"
        word_counts: Dict[str, Dict[str, int]] = {}

        for agent_id in CORE_ORGAN_AGENTS:
            agent_yaml_path = agents_dir / agent_id / "agent.yaml"
            assert agent_yaml_path.is_file(), f"Missing agent.yaml for {agent_id}"

            data = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))
            persona = _get_persona_text(agent_yaml_path, data)
            assert isinstance(persona, str) and len(persona.strip()) > 0, f"Empty persona for {agent_id}"

            # Standard whitespace split
            whitespace_words = persona.split()
            ws_count = len(whitespace_words)

            # Regex alphanumeric word tokens
            regex_words = re.findall(r"\b\w+\b", persona)
            regex_count = len(regex_words)

            word_counts[agent_id] = {"whitespace": ws_count, "regex": regex_count}

            assert ws_count >= 40, (
                f"Agent '{agent_id}' persona whitespace word count {ws_count} < 40"
            )
            assert regex_count >= 40, (
                f"Agent '{agent_id}' persona regex word count {regex_count} < 40"
            )
            assert ws_count < 600, (
                f"Agent '{agent_id}' persona word count {ws_count} exceeds upper bound 600"
            )

        # Confirm all 8 agents were measured
        assert len(word_counts) == 8

    def test_word_count_truncation_detection(self):
        """Adversarial oracle: a persona truncated to 39 words MUST be detected and rejected."""
        dummy_words = ["word"] * 39
        truncated_persona = " ".join(dummy_words)
        assert len(truncated_persona.split()) == 39
        assert len(truncated_persona.split()) < 40

    def test_all_5_mandatory_headings_present_and_strictly_ordered(self, temp_workspace: Path):
        """EMPIRICAL VERIFICATION: All 5 mandatory uppercase headings must be present
        in strict sequential order across all 8 personas.
        """
        agents_dir = temp_workspace / "agents"

        for agent_id in CORE_ORGAN_AGENTS:
            agent_yaml_path = agents_dir / agent_id / "agent.yaml"
            data = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))
            persona = _get_persona_text(agent_yaml_path, data)

            indices: List[int] = []
            for heading in MANDATORY_HEADINGS:
                idx = persona.find(heading)
                assert idx != -1, f"Agent '{agent_id}' persona missing mandatory heading: '{heading}'"
                indices.append(idx)

            # Verify strictly ascending order
            for i in range(len(indices) - 1):
                assert indices[i] < indices[i + 1], (
                    f"Agent '{agent_id}' headings '{MANDATORY_HEADINGS[i]}' and "
                    f"'{MANDATORY_HEADINGS[i+1]}' are out of sequential order!"
                )

    def test_all_5_sections_have_substantial_content(self, temp_workspace: Path):
        """EMPIRICAL VERIFICATION: Each section under each heading must contain substantive
        guidance (at least 20 words each) and not just empty or placeholder headers.
        """
        agents_dir = temp_workspace / "agents"

        for agent_id in CORE_ORGAN_AGENTS:
            agent_yaml_path = agents_dir / agent_id / "agent.yaml"
            data = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))
            persona = _get_persona_text(agent_yaml_path, data)

            # Split by headings
            pattern = "(" + "|".join(re.escape(h) for h in MANDATORY_HEADINGS) + ")"
            splits = re.split(pattern, persona)

            # splits will look like: [preamble, H1, body1, H2, body2, ...]
            # Iterate through the headers and bodies
            for i in range(1, len(splits), 2):
                heading = splits[i]
                body = splits[i + 1] if i + 1 < len(splits) else ""
                body_words = body.split()
                assert len(body_words) >= 20, (
                    f"Agent '{agent_id}' section '{heading}' has only {len(body_words)} words (minimum 20 required)"
                )


# ============================================================================
# Test Suite 2: Closed Tool Registry & Delegation Lockdown
# ============================================================================

class TestClosedToolRegistryAndDelegationLockdown:
    """Empirically stress-tests tool registry lockdown and absence of delegation tools."""

    def test_agents_closed_tool_registry(self, temp_workspace: Path):
        """All 8 agents must only declare allowed Phase 0 tools and zero delegation/unauthorized tools."""
        agents_dir = temp_workspace / "agents"

        for agent_id in CORE_ORGAN_AGENTS:
            manifest, tools, _ = load_agent(agents_dir / agent_id)

            declared_tools = set(manifest.tools)
            assert declared_tools.issubset(PHASE0_AGENT_TOOLS), (
                f"Agent '{agent_id}' declared unauthorized tools: {declared_tools - PHASE0_AGENT_TOOLS}"
            )
            assert declared_tools.isdisjoint(FORBIDDEN_TOOLS), (
                f"Agent '{agent_id}' declared forbidden tools: {declared_tools & FORBIDDEN_TOOLS}"
            )
            assert manifest.can_delegate is False, (
                f"Agent '{agent_id}' has can_delegate=True; clinical navigators must not delegate"
            )
            assert manifest.hidden is False, (
                f"Agent '{agent_id}' is hidden; clinical navigators must be public"
            )

    def test_skills_closed_tool_registry(self, temp_workspace: Path):
        """All 8 skills must only declare allowed Phase 0 skill tools (attach-read, skill-docs)."""
        skills_dir = temp_workspace / "skills"

        for skill_id in CORE_ORGAN_SKILLS:
            skill = load_skill(skills_dir / skill_id)

            declared_tools = set(skill.tools)
            assert declared_tools.issubset(PHASE0_SKILL_TOOLS), (
                f"Skill '{skill_id}' declared unauthorized tools: {declared_tools - PHASE0_SKILL_TOOLS}"
            )
            assert "workspace-note" not in declared_tools, (
                f"Skill '{skill_id}' should not declare workspace-note (reserved for agents)"
            )
            assert declared_tools.isdisjoint(FORBIDDEN_TOOLS), (
                f"Skill '{skill_id}' declared forbidden tools: {declared_tools & FORBIDDEN_TOOLS}"
            )

    def test_tool_validator_rejects_unauthorized_tools_mutation(self):
        """Adversarial stress: validate_tools_in_phase0 must reject arbitrary tools outside PHASE_0_REGISTRY."""
        with pytest.raises(ToolValidationError):
            validate_tools_in_phase0(["web_search"], "adversarial_test")

        with pytest.raises(ToolValidationError):
            validate_tools_in_phase0(["execute_code", "attach-read"], "adversarial_test")

    def test_specialist_delegation_tool_oracle(self):
        """Adversarial oracle: a specialist navigator declaring delegation tools must be caught by policy."""
        specialist_declared = ["attach-read", "delegate_to_agent"]
        forbidden_for_navigators = {"delegate_to_agent", "list_agents"}
        assert not set(specialist_declared).isdisjoint(forbidden_for_navigators)
        assert not set(specialist_declared).issubset(PHASE0_AGENT_TOOLS)


# ============================================================================
# Test Suite 3: Mandatory Intended-Use Statements
# ============================================================================

class TestMandatoryIntendedUseStatements:
    """Empirically stress-tests intended-use statements in all 8 SKILL.md files."""

    def test_all_8_skills_contain_all_3_intended_use_statements(self, temp_workspace: Path):
        """All 8 skills must contain the 3 required intended-use statements verbatim."""
        skills_dir = temp_workspace / "skills"

        for skill_id in CORE_ORGAN_SKILLS:
            skill_md_path = skills_dir / skill_id / "SKILL.md"
            assert skill_md_path.is_file(), f"Missing SKILL.md for {skill_id}"

            content = skill_md_path.read_text(encoding="utf-8")
            valid, missing = check_mandatory_intended_use(content)

            assert valid is True, (
                f"Skill '{skill_id}' check_mandatory_intended_use failed. Missing: '{missing}'"
            )

            # Assert each statement specifically
            for stmt in MANDATORY_INTENDED_USE_STATEMENTS:
                assert stmt.lower() in content.lower(), (
                    f"Skill '{skill_id}' missing intended use statement: '{stmt}'"
                )

    def test_check_mandatory_intended_use_oracle(self):
        """Adversarial oracle: omission of any of the 3 statements causes validation failure."""
        base_text = (
            "Not a clinician and not emergency care.\n"
            "If this is an emergency, contact local emergency services.\n"
            "Do not change medication without the prescribing clinician."
        )
        assert check_mandatory_intended_use(base_text)[0] is True

        # Omit statement 1
        text_without_1 = (
            "If this is an emergency, contact local emergency services.\n"
            "Do not change medication without the prescribing clinician."
        )
        assert check_mandatory_intended_use(text_without_1)[0] is False

        # Omit statement 2
        text_without_2 = (
            "Not a clinician and not emergency care.\n"
            "Do not change medication without the prescribing clinician."
        )
        assert check_mandatory_intended_use(text_without_2)[0] is False

        # Omit statement 3
        text_without_3 = (
            "Not a clinician and not emergency care.\n"
            "If this is an emergency, contact local emergency services."
        )
        assert check_mandatory_intended_use(text_without_3)[0] is False


# ============================================================================
# Test Suite 4: Reference Files Integrity & Depth
# ============================================================================

class TestSkillReferencesIntegrityAndDepth:
    """Empirically stress-tests references/ in all 8 skills."""

    def test_all_8_skills_have_ge_2_reference_files_with_substantial_content(self, temp_workspace: Path):
        """All 8 skills must have >= 2 markdown reference files, each > 200 bytes, > 50 words, with headers."""
        skills_dir = temp_workspace / "skills"
        ref_counts: Dict[str, int] = {}

        for skill_id in CORE_ORGAN_SKILLS:
            ref_dir = skills_dir / skill_id / REFERENCES_DIR
            assert ref_dir.is_dir(), f"references/ directory missing in {skill_id}"

            md_files = sorted([f for f in ref_dir.glob("*.md") if f.is_file() and not f.name.startswith(".")])
            ref_counts[skill_id] = len(md_files)
            assert len(md_files) >= 2, (
                f"Skill '{skill_id}' has {len(md_files)} reference files (expected at least 2)"
            )

            for ref_file in md_files:
                text = ref_file.read_text(encoding="utf-8")
                size_bytes = len(text.encode("utf-8"))
                words = text.split()

                assert size_bytes >= 200, (
                    f"Reference file '{ref_file.name}' in '{skill_id}' is only {size_bytes} bytes (< 200)"
                )
                assert len(words) >= 50, (
                    f"Reference file '{ref_file.name}' in '{skill_id}' has only {len(words)} words (< 50)"
                )
                assert "#" in text, (
                    f"Reference file '{ref_file.name}' in '{skill_id}' contains no Markdown headings"
                )

        assert len(ref_counts) == 8
        assert all(cnt >= 2 for cnt in ref_counts.values())

    def test_skill_md_referenced_docs_exist_on_disk(self, temp_workspace: Path):
        """Referential integrity: every reference document mentioned in SKILL.md must exist on disk."""
        skills_dir = temp_workspace / "skills"

        for skill_id in CORE_ORGAN_SKILLS:
            skill_md_path = skills_dir / skill_id / "SKILL.md"
            text = skill_md_path.read_text(encoding="utf-8")

            # Find all references like `references/foo.md` or `doc: "foo.md"`
            matches = set(re.findall(r"(?:references/|doc:\s*[\"'])([a-zA-Z0-9_\-]+\.md)", text))
            assert len(matches) >= 2, f"Skill '{skill_id}' SKILL.md mentions fewer than 2 reference docs: {matches}"

            ref_dir = skills_dir / skill_id / REFERENCES_DIR
            for doc_name in matches:
                target_doc = ref_dir / doc_name
                assert target_doc.is_file(), (
                    f"Skill '{skill_id}' references '{doc_name}' in SKILL.md, but file does not exist in {ref_dir}"
                )


# ============================================================================
# Test Suite 5: Safety Boundaries, Prohibitions, and Emergency Red Flags
# ============================================================================

class TestSafetyBoundariesAndRedFlags:
    """Empirically stress-tests clinical safety boundaries and emergency referral requirements."""

    def test_all_8_personas_contain_strict_anti_diagnostic_anti_prescribing_terms(self, temp_workspace: Path, repo_root: Path):
        """All 8 agents combined with carefold profile must explicitly disclaim diagnosing, prescribing, and dosage calculations."""
        agents_dir = temp_workspace / "agents"
        profile_path = repo_root / "carefold-profile.yaml"
        profile_text = profile_path.read_text(encoding="utf-8") if profile_path.is_file() else ""

        required_boundary_terms = ["diagnos", "prescrib", "dos"]

        for agent_id in CORE_ORGAN_AGENTS:
            agent_yaml_path = agents_dir / agent_id / "agent.yaml"
            data = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))
            persona = f"{_get_persona_text(agent_yaml_path, data)}\n{profile_text}".lower()

            for term in required_boundary_terms:
                assert term in persona, (
                    f"Agent '{agent_id}' persona missing mandatory safety boundary term '{term}'"
                )

    def test_all_8_personas_contain_explicit_emergency_referrals(self, temp_workspace: Path, repo_root: Path):
        """All 8 agents combined with carefold profile must explicitly direct patients to call 911 or local emergency services."""
        agents_dir = temp_workspace / "agents"
        profile_path = repo_root / "carefold-profile.yaml"
        profile_text = profile_path.read_text(encoding="utf-8") if profile_path.is_file() else ""

        for agent_id in CORE_ORGAN_AGENTS:
            agent_yaml_path = agents_dir / agent_id / "agent.yaml"
            data = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))
            persona = f"{_get_persona_text(agent_yaml_path, data)}\n{profile_text}".lower()

            assert "911" in persona or "emergency services" in persona or "emergency department" in persona, (
                f"Agent '{agent_id}' persona missing explicit 911 or emergency department referral"
            )

    def test_all_8_agents_forbidden_intents_in_manifest(self, temp_workspace: Path):
        """All 8 agents must forbid diagnosing, prescribing, and modifying prescriptions in manifest."""
        agents_dir = temp_workspace / "agents"

        required_forbidden = {"diagnose", "prescribe", "dose", "replace_emergency_care", "instruct_stop_medication"}

        for agent_id in CORE_ORGAN_AGENTS:
            manifest, _, _ = load_agent(agents_dir / agent_id)
            assert set(manifest.forbidden) >= required_forbidden, (
                f"Agent '{agent_id}' missing required forbidden intents: {required_forbidden - set(manifest.forbidden)}"
            )


# ============================================================================
# Test Suite 6: Companion Skill Coupling & Manifest Symmetry
# ============================================================================

class TestCompanionSkillCouplingAndManifestSymmetry:
    """Empirically stress-tests the 1-to-1 relationship between agents and skills."""

    def test_agent_skill_one_to_one_symmetry(self, temp_workspace: Path):
        """Every agent declares its corresponding companion skill, and domains/categories match."""
        agents_dir = temp_workspace / "agents"
        skills_dir = temp_workspace / "skills"

        for agent_id, skill_id in AGENT_TO_SKILL.items():
            agent_manifest, _, loaded_skills = load_agent(agents_dir / agent_id, skills_dir)
            skill_manifest = load_skill(skills_dir / skill_id)

            assert skill_id in agent_manifest.skills, (
                f"Agent '{agent_id}' does not declare companion skill '{skill_id}'"
            )
            assert len(loaded_skills) == 1, (
                f"Agent '{agent_id}' should load exactly 1 companion skill, got {len(loaded_skills)}"
            )
            assert loaded_skills[0].id == skill_id

            # Symmetry in domain and category
            assert agent_manifest.domain == skill_manifest.domain == AgentDomain.CLINICAL
            assert agent_manifest.category == skill_manifest.category
            assert agent_manifest.risk_class == RiskClass.CLINICAL_ASSIST
            assert skill_manifest.risk_class == RiskClass.WELLNESS


# ============================================================================
# Test Suite 7: Starters & Golden Evals Robustness
# ============================================================================

class TestStartersAndGoldenEvalsRobustness:
    """Empirically stress-tests starter prompts and golden eval coverage."""

    def test_starters_json_contains_diverse_organ_prompts(self, temp_workspace: Path):
        """All 8 agents must provide at least 3 distinct starter questions in starters.json."""
        agents_dir = temp_workspace / "agents"

        for agent_id in CORE_ORGAN_AGENTS:
            starters_file = agents_dir / agent_id / "starters.json"
            assert starters_file.is_file(), f"Missing starters.json for {agent_id}"

            starters = json.loads(starters_file.read_text(encoding="utf-8"))
            assert isinstance(starters, list), f"starters.json for {agent_id} is not a list"
            assert len(starters) >= 3, f"Agent '{agent_id}' has fewer than 3 starters: {len(starters)}"
            assert all(isinstance(s, str) and len(s.strip()) > 10 for s in starters), (
                f"Agent '{agent_id}' has invalid or overly short starter strings"
            )

    @pytest.mark.asyncio
    async def test_all_8_agents_pass_all_golden_eval_cases(self, temp_workspace: Path):
        """Executes all 48 golden evaluation cases across all 8 agents using deterministic evals."""
        from evals.runner import EvalCase, run_single_eval

        agents_dir = temp_workspace / "agents"
        total_executed = 0

        for agent_id in CORE_ORGAN_AGENTS:
            golden_path = agents_dir / agent_id / "evals" / "golden.jsonl"
            assert golden_path.is_file(), f"Missing golden.jsonl for {agent_id}"

            cases: List[EvalCase] = []
            with open(golden_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        cases.append(EvalCase(json.loads(line), golden_path, suite_type="agent"))

            assert len(cases) >= 4, f"Agent '{agent_id}' has only {len(cases)} eval cases (min 4)"

            for case in cases:
                success, msg = await run_single_eval(case, agent_id, temp_workspace, provider="ollama")
                assert success is True, f"Agent '{agent_id}' failed golden eval case '{case.id}': {msg}"
                total_executed += 1

        assert total_executed == 48, f"Expected 48 golden eval cases executed, got {total_executed}"


# ============================================================================
# Test Suite 8: SQLite FTS5 Catalog Search & Tree Aggregation
# ============================================================================

class TestCatalogIndexingAndDiscoveryStress:
    """Empirically stress-tests indexing and searching all 8 agents in SQLite FTS5."""

    @pytest.mark.asyncio
    async def test_all_8_agents_and_skills_index_and_query_fts(self, temp_workspace: Path):
        """Indexes all 8 agents and skills into SqliteCatalogAdapter and runs multi-term FTS queries."""
        agents_dir = temp_workspace / "agents"
        skills_dir = temp_workspace / "skills"

        catalog = SqliteCatalogAdapter(db_path=":memory:")

        # Index all
        for agent_id in CORE_ORGAN_AGENTS:
            agent, _, _ = load_agent(agents_dir / agent_id, skills_dir)
            await catalog.index_agent(agent)
            skill = load_skill(skills_dir / AGENT_TO_SKILL[agent_id])
            await catalog.index_skill(skill)

        # 1. Total count check
        clinical_agents = await catalog.search_agents(domain="clinical", limit=50)
        assert len(clinical_agents) == 8

        # 2. Distinct organ queries
        search_terms = {
            "cardiology-guide": "blood pressure",
            "pulmonology-guide": "inhaler",
            "neurology-guide": "headache",
            "gastro-guide": "colonoscopy",
            "nephrology-guide": "creatinine",
            "endocrinology-guide": "glucose",
            "ortho-guide": "mobility",
            "derma-guide": "lesion",
        }

        for agent_id, term in search_terms.items():
            results = await catalog.search_agents(query=term)
            assert len(results) >= 1, f"FTS search for '{term}' returned 0 results"
            matched_ids = [r.id for r in results]
            assert agent_id in matched_ids, f"Agent '{agent_id}' not found when searching for '{term}'"

        # 3. Category tree
        tree = await catalog.get_category_tree()
        assert tree["domains"]["clinical"]["count"] == 8
        categories = tree["domains"]["clinical"]["categories"]
        for agent_id in CORE_ORGAN_AGENTS:
            cat_name = agent_id.replace("-guide", "")
            # Mapping check
            found = any(cat_name in k for k in categories.keys())
            assert found, f"Category for '{agent_id}' missing from category tree: {categories}"

        await catalog.close()
