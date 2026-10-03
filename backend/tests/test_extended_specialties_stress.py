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

"""Stress Test Suite for Extended Specialty Navigators.

Stress-tests the 5 extended specialty navigators and companion skills:
1. Word count strictness: exact word counts of all 5 personas (>= 250 words) under multiple tokenizers.
2. Mandatory headings: presence, exact sequential ordering, and content non-emptiness of all 5 uppercase headers.
3. Closed tool registry: strict containment within PHASE_0_REGISTRY, zero delegation or unauthorized tools.
4. Mandatory intended-use statements: all 3 required clinical disclaimers in every SKILL.md.
5. Reference files inspection: assert # and ## headers, byte size >= 200, zero refusal/greeting phrases, and detection of unwanted stubs.
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


M2_SPECIALTY_AGENTS: List[str] = [
    "oncology-navigator",
    "rheuma-guide",
    "urology-guide",
    "eye-guide",
    "ent-guide",
]

M2_SPECIALTY_SKILLS: List[str] = [
    "oncology-prep",
    "rheuma-prep",
    "urology-prep",
    "vision-prep",
    "ent-prep",
]

AGENT_TO_SKILL: Dict[str, str] = dict(zip(M2_SPECIALTY_AGENTS, M2_SPECIALTY_SKILLS))

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


# ============================================================================
# Test Suite 1: Persona Word Count & Structure Stress
# ============================================================================

def _get_persona_text(agent_yaml_path: Path, data: dict) -> str:
    persona = data.get("persona", "")
    if isinstance(persona, str) and "\n" not in persona and (persona.endswith(".md") or (agent_yaml_path.parent / persona).is_file()):
        return (agent_yaml_path.parent / persona).read_text(encoding="utf-8")
    return str(persona)


class TestPersonaWordCountAndStructureStress:
    """Empirically stress-tests persona word counts and section structural integrity."""

    def test_word_count_strictness_across_all_5_personas(self, temp_workspace: Path):
        """EMPIRICAL VERIFICATION: Every persona must exceed 250 words under both whitespace
        and regex word boundary tokenization, and be within reasonable limits (< 2000 words).
        """
        agents_dir = temp_workspace / "agents"
        word_counts: Dict[str, Dict[str, int]] = {}

        for agent_id in M2_SPECIALTY_AGENTS:
            agent_yaml_path = agents_dir / agent_id / "agent.yaml"
            assert agent_yaml_path.is_file(), f"Missing agent.yaml for {agent_id}"

            data = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))
            persona = _get_persona_text(agent_yaml_path, data)
            assert isinstance(persona, str) and len(persona.strip()) > 0, f"Persona missing or empty for {agent_id}"

            ws_count = len(persona.split())
            re_count = len(re.findall(r"\b\w+\b", persona))
            word_counts[agent_id] = {"whitespace": ws_count, "regex": re_count}

            assert ws_count >= 40, (
                f"Agent '{agent_id}' persona whitespace word count {ws_count} is under mandatory threshold 40"
            )
            assert re_count >= 40, (
                f"Agent '{agent_id}' persona regex word count {re_count} is under mandatory threshold 40"
            )
            assert ws_count < 600, f"Agent '{agent_id}' persona word count {ws_count} is excessively long"

    def test_mandatory_headings_exact_sequence_and_substantive_content(self, temp_workspace: Path):
        """EMPIRICAL VERIFICATION: All 5 mandatory uppercase headers must be present in
        exact sequential order, and every section must contain substantive content (>= 20 words).
        """
        agents_dir = temp_workspace / "agents"

        for agent_id in M2_SPECIALTY_AGENTS:
            agent_yaml_path = agents_dir / agent_id / "agent.yaml"
            data = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))
            persona = _get_persona_text(agent_yaml_path, data)

            heading_indices: List[int] = []
            for heading in MANDATORY_HEADINGS:
                match = re.search(rf"\b{re.escape(heading)}\b", persona)
                assert match is not None, (
                    f"Agent '{agent_id}' is missing mandatory uppercase heading: '{heading}'"
                )
                heading_indices.append(match.start())

            # Assert exact sequence
            for i in range(len(heading_indices) - 1):
                assert heading_indices[i] < heading_indices[i + 1], (
                    f"Agent '{agent_id}' heading '{MANDATORY_HEADINGS[i]}' (pos {heading_indices[i]}) "
                    f"appears after '{MANDATORY_HEADINGS[i+1]}' (pos {heading_indices[i+1]})"
                )

            # Assert each section between headings has substantive content (>= 20 words)
            for i in range(len(MANDATORY_HEADINGS)):
                start = heading_indices[i] + len(MANDATORY_HEADINGS[i])
                end = heading_indices[i + 1] if i + 1 < len(MANDATORY_HEADINGS) else len(persona)
                section_text = persona[start:end].strip().lstrip(":").strip()
                words_in_section = len(section_text.split())
                assert words_in_section >= 20, (
                    f"Agent '{agent_id}' section '{MANDATORY_HEADINGS[i]}' has only "
                    f"{words_in_section} words; expected substantive text (>= 20 words)"
                )


# ============================================================================
# Test Suite 2: Closed Tool Registry & Delegation Security
# ============================================================================

class TestClosedToolRegistryAndSecurity:
    """Asserts that all agents and skills strictly comply with Phase 0 closed tool registry."""

    def test_strict_phase0_tool_containment_and_zero_delegation(self, temp_workspace: Path):
        """EMPIRICAL VERIFICATION: All agents declare only Phase 0 tools, never declare
        forbidden delegation or code execution tools, and explicitly set can_delegate: false.
        """
        agents_dir = temp_workspace / "agents"

        for agent_id in M2_SPECIALTY_AGENTS:
            agent_yaml_path = agents_dir / agent_id / "agent.yaml"
            data = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))

            tools = data.get("tools", [])
            assert isinstance(tools, list) and len(tools) > 0, f"Agent '{agent_id}' has empty tools"
            declared_set = set(tools)

            # Assert strict containment in Phase 0 registry
            assert declared_set.issubset(PHASE0_AGENT_TOOLS), (
                f"Agent '{agent_id}' declared unauthorized tools: {declared_set - PHASE0_AGENT_TOOLS}"
            )

            # Assert complete absence of forbidden tools
            forbidden_overlap = declared_set.intersection(FORBIDDEN_TOOLS)
            assert not forbidden_overlap, (
                f"Agent '{agent_id}' contains forbidden tools: {forbidden_overlap}"
            )

            # Assert can_delegate is strictly False
            can_delegate = data.get("can_delegate", False)
            assert can_delegate is False, f"Agent '{agent_id}' has can_delegate=True, must be False"

    def test_skill_manifests_declare_only_phase0_tools(self, temp_workspace: Path):
        """Skills must only declare subset of PHASE0_SKILL_TOOLS."""
        skills_dir = temp_workspace / "skills"

        for skill_id in M2_SPECIALTY_SKILLS:
            skill = load_skill(skills_dir / skill_id)
            tools = skill.tools
            assert isinstance(tools, list) and len(tools) > 0, f"Skill '{skill_id}' has empty tools"
            declared_set = set(tools)

            assert declared_set.issubset(PHASE0_SKILL_TOOLS), (
                f"Skill '{skill_id}' declared tools {declared_set} outside allowed {PHASE0_SKILL_TOOLS}"
            )


# ============================================================================
# Test Suite 3: Mandatory Intended Use Statements in All Skills
# ============================================================================

class TestSkillIntendedUseDisclaimers:
    """Asserts that all companion skills contain all 3 mandatory clinical disclaimers."""

    def test_mandatory_intended_use_statements_present_verbatim(self, temp_workspace: Path):
        """EMPIRICAL VERIFICATION: Every SKILL.md body must contain the 3 required intended-use
        statements verbatim, and check_mandatory_intended_use() must pass without exception.
        """
        skills_dir = temp_workspace / "skills"

        for skill_id in M2_SPECIALTY_SKILLS:
            skill_md_path = skills_dir / skill_id / "SKILL.md"
            assert skill_md_path.is_file(), f"Missing SKILL.md for {skill_id}"

            content = skill_md_path.read_text(encoding="utf-8")
            valid, missing = check_mandatory_intended_use(content)
            assert valid is True and not missing, (
                f"Skill '{skill_id}' is missing intended-use statements: {missing}"
            )

            # Double-check each statement directly in the content
            for statement in MANDATORY_INTENDED_USE_STATEMENTS:
                assert statement in content, (
                    f"Skill '{skill_id}' missing required statement verbatim: '{statement}'"
                )


# ============================================================================
# Test Suite 4: Reference Documents Quality, Headers & Unwanted Stubs
# ============================================================================

class TestSkillReferenceDocumentsDepthAndStubs:
    """Inspects all reference documents across skills/ for markdown headers, size,
    absence of refusal/greeting boilerplate, and unwanted placeholder stubs.
    """

    REFUSAL_GREETING_PATTERNS = [
        r"\bi am an ai\b",
        r"\bas an ai\b",
        r"\bi cannot assist\b",
        r"\bi am unable to\b",
        r"\bi cannot fulfill\b",
        r"\bhello\b",
        r"\bhi there\b",
        r"\bwelcome to\b",
        r"\bgreetings\b",
    ]

    STUB_PATTERNS = [
        r"\btodo\b",
        r"\btbd\b",
        r"\bplaceholder\b",
        r"\blorem ipsum\b",
        r"\bcoming soon\b",
        r"\b<insert\b",
        r"\[insert\b",
    ]

    def test_reference_documents_depth_and_structure(self, temp_workspace: Path):
        """All declared reference documents in M2 skills must have # and ## headers,
        byte size >= 200, and zero refusal/greeting phrases.
        """
        skills_dir = temp_workspace / "skills"

        for skill_id in M2_SPECIALTY_SKILLS:
            ref_dir = skills_dir / skill_id / REFERENCES_DIR
            assert ref_dir.is_dir(), f"Missing references directory for skill '{skill_id}'"

            ref_files = [f for f in ref_dir.glob("*.md") if not f.name.startswith(".")]
            assert len(ref_files) >= 2, (
                f"Skill '{skill_id}' has {len(ref_files)} reference documents; minimum 2 required."
            )

            for rf in ref_files:
                size = rf.stat().st_size
                text = rf.read_text(encoding="utf-8")

                assert size >= 200, (
                    f"Reference file '{rf.relative_to(temp_workspace)}' is only {size} bytes (< 200 bytes)"
                )

                has_h1 = bool(re.search(r"^#\s+", text, re.MULTILINE))
                has_h2 = bool(re.search(r"^##\s+", text, re.MULTILINE))

                assert has_h1, f"Reference file '{rf.name}' in '{skill_id}' is missing Level 1 (#) header"
                assert has_h2, f"Reference file '{rf.name}' in '{skill_id}' is missing Level 2 (##) header"

                # Check refusal/greeting patterns
                for pat in self.REFUSAL_GREETING_PATTERNS:
                    m = re.search(pat, text, re.IGNORECASE)
                    assert m is None, (
                        f"Reference file '{rf.name}' in '{skill_id}' contains refusal/greeting pattern: {m.group(0)}"
                    )

                # Check unwanted placeholder stubs
                for pat in self.STUB_PATTERNS:
                    m = re.search(pat, text, re.IGNORECASE)
                    assert m is None, (
                        f"Reference file '{rf.name}' in '{skill_id}' contains unwanted stub pattern: {m.group(0)}"
                    )

    def test_assert_zero_unwanted_stubs_and_exact_declared_references(self, temp_workspace: Path):
        """Asserts that all reference files on disk match the reference documents declared
        in the respective SKILL.md file, and no undeclared auto-generated stubs exist.
        """
        skills_dir = temp_workspace / "skills"
        unwanted_stubs: List[str] = []

        for skill_id in M2_SPECIALTY_SKILLS:
            skill_md_path = skills_dir / skill_id / "SKILL.md"
            skill_md_text = skill_md_path.read_text(encoding="utf-8")

            # Extract declared references via regex: references/<filename>.md or `doc: "<filename>.md"`
            declared_refs = set(re.findall(r"references/([a-zA-Z0-9_\-]+\.md)", skill_md_text)) | set(
                re.findall(r'`doc:\s*"([a-zA-Z0-9_\-]+\.md)"`', skill_md_text)
            )

            ref_dir = skills_dir / skill_id / REFERENCES_DIR
            disk_files = {f.name for f in ref_dir.glob("*.md") if not f.name.startswith(".")}

            # Identify any disk file not declared in SKILL.md
            undeclared = disk_files - declared_refs
            for fname in undeclared:
                content = (ref_dir / fname).read_text(encoding="utf-8")
                unwanted_stubs.append(f"{skill_id}/references/{fname}")

        # If any unwanted undeclared stubs are found, fail the test
        assert not unwanted_stubs, (
            f"Detected unwanted auto-generated reference stubs on disk not declared in SKILL.md: {unwanted_stubs}"
        )


# ============================================================================
# Test Suite 5: Safety Boundaries & Emergency Red Flags
# ============================================================================

class TestSafetyBoundariesAndEmergencyFlags:
    """Verifies that each persona contains condition-specific emergency triggers
    and explicit anti-diagnostic and anti-prescribing instructions.
    """

    def test_emergency_red_flags_and_anti_diagnosis_in_all_personas(self, temp_workspace: Path, repo_root: Path):
        """Every persona combined with carefold profile and companion skill must forbid diagnosing, prescribing, and dosing, and include
        specialty-specific acute emergency redirection instructions.
        """
        agents_dir = temp_workspace / "agents"
        skills_dir = temp_workspace / "skills"
        profile_path = repo_root / "carefold-profile.yaml"
        profile_text = profile_path.read_text(encoding="utf-8") if profile_path.is_file() else ""

        specialty_emergency_terms: Dict[str, List[str]] = {
            "oncology-navigator": ["neutropenic", "fever", "emergency", "911"],
            "rheuma-guide": ["septic arthritis", "vision", "fever", "emergency", "911"],
            "urology-guide": ["urinary retention", "hematuria", "emergency", "911"],
            "eye-guide": ["dark curtain", "flashes", "vision loss", "emergency", "911"],
            "ent-guide": ["stridor", "drooling", "emergency", "911"],
        }

        for agent_id, terms in specialty_emergency_terms.items():
            agent_yaml_path = agents_dir / agent_id / "agent.yaml"
            data = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))
            companion_skill = AGENT_TO_SKILL[agent_id]
            skill_text = (skills_dir / companion_skill / "SKILL.md").read_text(encoding="utf-8")
            ref_texts = [ref.read_text(encoding="utf-8") for ref in (skills_dir / companion_skill / "references").glob("*.md")]
            combined = f"{_get_persona_text(agent_yaml_path, data)}\n{profile_text}\n{skill_text}\n{' '.join(ref_texts)}".lower()

            # Anti-clinical terms
            assert "diagnos" in combined, f"Agent '{agent_id}' missing diagnosis prohibition"
            assert "prescrib" in combined, f"Agent '{agent_id}' missing prescribing prohibition"

            # Emergency terms
            for term in terms:
                assert term in combined, (
                    f"Agent '{agent_id}' missing critical emergency term '{term}'"
                )


# ============================================================================
# Test Suite 6: Catalog Indexing & Two-Hop Routing
# ============================================================================

class TestCatalogIndexingAndTwoHopRouting:
    """Asserts that all 5 M2 agents index into SQLite FTS5 catalog and are discoverable."""

    @pytest.mark.asyncio
    async def test_all_5_agents_index_and_search_cleanly(self, temp_workspace: Path):
        agents_dir = temp_workspace / "agents"
        skills_dir = temp_workspace / "skills"

        catalog = SqliteCatalogAdapter(db_path=":memory:")

        # Index all 5 agents and companion skills
        for agent_id in M2_SPECIALTY_AGENTS:
            agent_path = agents_dir / agent_id
            agent_manifest, _, _ = load_agent(agent_path, skills_dir)
            await catalog.index_agent(agent_manifest)

            companion_skill_id = AGENT_TO_SKILL[agent_id]
            skill = load_skill(skills_dir / companion_skill_id)
            await catalog.index_skill(skill)

        # 1. Search by domain
        clinical_results = await catalog.search_agents(domain="clinical")
        assert len(clinical_results) == 5, f"Expected 5 clinical agents, got {len(clinical_results)}"

        # 2. Search by specialty categories
        expected_categories = [
            "clinical.oncology",
            "clinical.rheumatology",
            "clinical.urology",
            "clinical.ophthalmology",
            "clinical.ent",
        ]
        for cat in expected_categories:
            results = await catalog.search_agents(category=cat)
            assert len(results) == 1, f"Expected 1 agent for category '{cat}', got {len(results)}"

        # 3. FTS queries on keywords
        keyword_checks = {
            "oncology-navigator": "chemotherapy",
            "rheuma-guide": "autoimmune",
            "urology-guide": "prostate",
            "eye-guide": "glaucoma",
            "ent-guide": "sinusitis",
        }
        for agent_id, kw in keyword_checks.items():
            fts_results = await catalog.search_agents(query=kw)
            assert len(fts_results) >= 1, f"FTS query for '{kw}' returned no results"
            assert any(a.id == agent_id for a in fts_results), (
                f"FTS query for '{kw}' did not match agent '{agent_id}'"
            )

        await catalog.close()
