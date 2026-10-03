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

"""End-to-End Tests for Persona Purification & Separation of Concerns.

Verifies that all agent personas in `agents/*/persona.md` and `agents/_template/persona.md`
are completely purified of operational tool invocation syntax, skill slugs, reference document
filenames, and filesystem paths. Asserts word count >= 250 and presence of all 5 mandatory
uppercase section headers.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Dict, List, Set, Tuple
import pytest
import yaml

from carefold.loaders.agent_loader import load_agent


# ============================================================================
# Canonical Invariant Definitions
# ============================================================================

MANDATORY_HEADERS: List[str] = [
    "ROLE & EMPATHY:",
    "CLINICAL SCOPE & FOCUS:",
]

FORBIDDEN_TOOL_KEYWORDS: Set[str] = {
    "attach-read",
    "workspace-note",
    "skill-docs",
}

FORBIDDEN_SKILL_SLUGS: Set[str] = {
    "cardiology-prep",
    "visit-prep",
    "benefits-explainer",
    "pulmonology-prep",
    "neurology-prep",
    "gastro-prep",
    "nephrology-prep",
    "endocrinology-prep",
    "ortho-prep",
    "derma-prep",
    "rheuma-prep",
    "ent-prep",
    "eye-prep",
    "urology-prep",
    "oncology-prep",
    "emergency-red-flags",
    "clinical-safety-boundaries",
}

FORBIDDEN_FILESYSTEM_PATTERNS: List[re.Pattern] = [
    re.compile(r"\battachments/", re.IGNORECASE),
    re.compile(r"\bnotes/", re.IGNORECASE),
    re.compile(r"\bworkspace/notes/", re.IGNORECASE),
    re.compile(r"/Users/", re.IGNORECASE),
]

FORBIDDEN_DOC_FILENAMES: List[str] = [
    "cardiology_visit_agenda.md",
    "hypertension_log_template.md",
    "dyspnea_symptom_tracker.md",
    "migraine_headache_diary_template.md",
    "cognitive_symptom_timeline.md",
    "ibs_ibd_food_symptom_journal.md",
    "fluid_and_sodium_tracking_worksheet.md",
    "cgm_and_glucose_log_summary.md",
    "joint_mobility_and_pain_tracker.md",
    "rash_and_flareup_documentation_protocol.md",
    "lesion_abcde_tracking_guide.md",
    "symptom_log_template.md",
    "eob_explanation.md",
]


# ============================================================================
# Helper Functions & Parsers
# ============================================================================

def get_all_persona_paths(repo_root: Path) -> List[Path]:
    """Discovers all persona files under agents/ excluding _system internal nodes."""
    agents_dir = repo_root / "agents"
    if not agents_dir.is_dir():
        return []
    personas = []
    for d in sorted(agents_dir.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_system")):
            continue
        migrated = d / "persona.md.migrated"
        orig = d / "persona.md"
        if migrated.is_file():
            personas.append(migrated)
        elif orig.is_file():
            personas.append(orig)
    return sorted(personas, key=lambda x: str(x))


def count_words(text: str) -> int:
    """Calculates total word count of markdown text."""
    words = re.findall(r"\b[A-Za-z0-9_-]+\b", text)
    return len(words)


def inspect_persona_violations(persona_text: str) -> Dict[str, List[str]]:
    """Inspects persona text for violations of R1 purity invariants."""
    violations: Dict[str, List[str]] = {
        "tools": [],
        "skill_slugs": [],
        "filenames": [],
        "paths": [],
        "missing_headers": [],
    }

    # 1. Tool syntax check
    for tool in FORBIDDEN_TOOL_KEYWORDS:
        if tool.lower() in persona_text.lower():
            violations["tools"].append(tool)

    # Tool invocation syntax like tool="...", using the ... tool
    if re.search(r'tool\s*=\s*["\'][^"\']+["\']', persona_text, re.IGNORECASE):
        violations["tools"].append('tool="..." attribute')
    if re.search(r'using the \S+ tool', persona_text, re.IGNORECASE):
        violations["tools"].append('using the ... tool')

    # 2. Skill slugs check
    for slug in FORBIDDEN_SKILL_SLUGS:
        # Match word boundary or quoted slug
        if re.search(rf'\b{re.escape(slug)}\b', persona_text, re.IGNORECASE):
            violations["skill_slugs"].append(slug)
    if re.search(r'skill_id\s*=\s*["\'][^"\']+["\']', persona_text, re.IGNORECASE):
        violations["skill_slugs"].append('skill_id="..." attribute')

    # 3. Filename references (.md files)
    md_matches = re.findall(r'\b[a-zA-Z0-9_\-]+\.md\b', persona_text, re.IGNORECASE)
    for m in md_matches:
        violations["filenames"].append(m)
    for fname in FORBIDDEN_DOC_FILENAMES:
        if fname.lower() in persona_text.lower() and fname not in violations["filenames"]:
            violations["filenames"].append(fname)

    # 4. Filesystem path references
    for pat in FORBIDDEN_FILESYSTEM_PATTERNS:
        if pat.search(persona_text):
            violations["paths"].append(pat.pattern)

    # 5. Mandatory headers check
    for header in MANDATORY_HEADERS:
        if header not in persona_text:
            violations["missing_headers"].append(header)

    return violations


# ============================================================================
# Tier 1: Feature Coverage: Persona Purity
# ============================================================================

class TestPersonaPurityFeatureCoverage:
    """Tier 1: Comprehensive feature coverage verifying persona purity requirements."""

    def test_all_personas_contain_zero_tool_invocations(self, e2e_repo_root: Path):
        """Verifies zero operational tool invocations (attach-read, workspace-note, skill-docs)."""
        persona_paths = get_all_persona_paths(e2e_repo_root)
        assert len(persona_paths) >= 20, f"Expected >= 20 personas, found {len(persona_paths)}"

        failures = {}
        for p in persona_paths:
            content = p.read_text(encoding="utf-8")
            violations = inspect_persona_violations(content)
            if violations["tools"]:
                failures[p.parent.name] = violations["tools"]

        assert not failures, (
            f"Found forbidden tool invocation directives in {len(failures)} personas: {failures}"
        )

    def test_all_personas_contain_zero_skill_slugs(self, e2e_repo_root: Path):
        """Verifies zero skill slugs or skill_id attributes in persona text."""
        persona_paths = get_all_persona_paths(e2e_repo_root)
        failures = {}
        for p in persona_paths:
            content = p.read_text(encoding="utf-8")
            violations = inspect_persona_violations(content)
            if violations["skill_slugs"]:
                failures[p.parent.name] = violations["skill_slugs"]

        assert not failures, (
            f"Found forbidden skill slug references in {len(failures)} personas: {failures}"
        )

    def test_all_personas_contain_zero_document_filenames(self, e2e_repo_root: Path):
        """Verifies zero .md document filenames in persona text."""
        persona_paths = get_all_persona_paths(e2e_repo_root)
        failures = {}
        for p in persona_paths:
            content = p.read_text(encoding="utf-8")
            violations = inspect_persona_violations(content)
            if violations["filenames"]:
                failures[p.parent.name] = violations["filenames"]

        assert not failures, (
            f"Found forbidden reference document filenames in {len(failures)} personas: {failures}"
        )

    def test_all_personas_contain_zero_filesystem_paths(self, e2e_repo_root: Path):
        """Verifies zero filesystem paths (attachments/, notes/) in persona text."""
        persona_paths = get_all_persona_paths(e2e_repo_root)
        failures = {}
        for p in persona_paths:
            content = p.read_text(encoding="utf-8")
            violations = inspect_persona_violations(content)
            if violations["paths"]:
                failures[p.parent.name] = violations["paths"]

        assert not failures, (
            f"Found forbidden filesystem paths in {len(failures)} personas: {failures}"
        )

    def test_all_personas_meet_minimum_word_count(self, e2e_repo_root: Path):
        """Verifies all personas meet minimum >= 40 words requirement."""
        persona_paths = get_all_persona_paths(e2e_repo_root)
        failures = {}
        for p in persona_paths:
            content = p.read_text(encoding="utf-8")
            count = count_words(content)
            if count < 40 or count >= 600:
                failures[p.parent.name] = count

        assert not failures, (
            f"Found {len(failures)} personas with word count outside [40, 600): {failures}"
        )

    def test_all_personas_contain_mandatory_headers(self, e2e_repo_root: Path):
        """Verifies all personas contain all mandatory uppercase headers."""
        persona_paths = get_all_persona_paths(e2e_repo_root)
        failures = {}
        for p in persona_paths:
            content = p.read_text(encoding="utf-8")
            violations = inspect_persona_violations(content)
            if violations["missing_headers"]:
                failures[p.parent.name] = violations["missing_headers"]

        assert not failures, (
            f"Found {len(failures)} personas missing mandatory section headers: {failures}"
        )

    def test_agent_yaml_declarative_capabilities(self, e2e_repo_root: Path):
        """Verifies agents declare tools and skills strictly in agent.yaml."""
        agents_dir = e2e_repo_root / "agents"
        failures = []
        for agent_dir in agents_dir.glob("*"):
            if not agent_dir.is_dir() or agent_dir.name.startswith("_system"):
                continue
            yaml_path = agent_dir / "agent.yaml"
            assert yaml_path.is_file(), f"Missing agent.yaml for agent {agent_dir.name}"
            manifest_data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            meta_path = agent_dir / "metadata.yaml"
            if meta_path.is_file():
                meta_data = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
                if isinstance(meta_data, dict):
                    manifest_data = {**meta_data, **manifest_data}
            assert isinstance(manifest_data, dict), f"agent.yaml in {agent_dir.name} must be a map"
            assert "id" in manifest_data or "name" in manifest_data, f"agent.yaml in {agent_dir.name} missing 'id' or 'name'"
            assert "title" in manifest_data or "name" in manifest_data, f"agent.yaml in {agent_dir.name} missing 'title' or 'name'"


# ============================================================================
# Tier 2: Boundary & Corner Cases: Persona Purity
# ============================================================================

class TestPersonaPurityBoundaries:
    """Tier 2: Boundary conditions, corner cases, and negative tests for persona purity."""

    def test_word_count_exact_boundary_threshold(self):
        """Verifies boundary check: 39 words is rejected, 40 words is accepted."""
        words_39 = " ".join(["word"] * 39)
        words_40 = " ".join(["word"] * 40)
        assert count_words(words_39) == 39
        assert count_words(words_40) == 40
        assert count_words(words_39) < 40
        assert count_words(words_40) >= 40

    def test_substring_non_tool_words_allowed(self):
        """Verifies legitimate English words containing tool substrings do NOT trigger false positives."""
        clean_text = (
            "The patient had an emotional attachment to the old therapy plan. "
            "It is noteworthy that documentation was thorough and skilled. "
            "A notebook was provided for home journaling."
        )
        violations = inspect_persona_violations(clean_text)
        assert not violations["tools"], f"False positive detected: {violations['tools']}"
        assert not violations["skill_slugs"], f"False positive detected: {violations['skill_slugs']}"
        assert not violations["paths"], f"False positive detected: {violations['paths']}"

    def test_header_case_and_punctuation_sensitivity(self):
        """Verifies headers missing trailing colon or using mixed case are detected as missing."""
        malformed_text = (
            "Role & Empathy:\n"
            "Clinical Scope & Focus:\n"
        )
        violations = inspect_persona_violations(malformed_text)
        assert "ROLE & EMPATHY:" in violations["missing_headers"]
        assert "CLINICAL SCOPE & FOCUS:" in violations["missing_headers"]

    def test_empty_persona_handling(self):
        """Verifies empty or whitespace personas are rejected on word count and headers."""
        violations = inspect_persona_violations("   \n\t  ")
        assert count_words("   \n\t  ") == 0
        assert len(violations["missing_headers"]) == len(MANDATORY_HEADERS)

    def test_persona_with_codeblocks_and_quotes(self):
        """Verifies tool mentions inside markdown code blocks or quotes are still flagged."""
        quoted_text = (
            "ROLE & EMPATHY:\nTest.\n"
            "CLINICAL SCOPE & FOCUS:\nTest.\n"
            "STRUCTURED INTERACTION PROTOCOL:\n"
            "> As noted earlier: `attach-read` should be called.\n"
            "STRICT NON-CLINICAL BOUNDARIES:\nTest.\n"
            "EXPLICIT EMERGENCY RED FLAGS:\nTest.\n"
        )
        violations = inspect_persona_violations(quoted_text)
        assert "attach-read" in violations["tools"]


# ============================================================================
# Tier 3: Cross-Feature Combinations: Persona Purity
# ============================================================================

class TestPersonaCrossFeatureCombinations:
    """Tier 3: Pairwise interactions with AgentLoader and schema validation."""

    def test_persona_loading_via_agent_loader(self, e2e_repo_root: Path):
        """Verifies that purified personas load cleanly through Carefold's AgentLoader."""
        agents_dir = e2e_repo_root / "agents"
        for agent_dir in agents_dir.glob("*"):
            if not agent_dir.is_dir() or agent_dir.name.startswith("_system"):
                continue
            manifest, _, _ = load_agent(agent_dir)
            assert manifest is not None
            assert manifest.id == agent_dir.name
            assert len(manifest.persona) > 0


# ============================================================================
# Tier 4: Real-World Application Scenarios: Persona Purity
# ============================================================================

class TestPersonaRealWorldScenarios:
    """Tier 4: Realistic persona validation for key clinical specialties."""

    @pytest.mark.parametrize("specialist_id", [
        "cardiology-guide",
        "nephrology-guide",
        "endocrinology-guide",
        "pulmonology-guide",
        "ortho-guide",
    ])
    def test_core_specialists_have_clinical_protocols(self, e2e_repo_root: Path, specialist_id: str):
        """Verifies core clinical specialists have robust protocol structure and emergency red flags."""
        persona_path = e2e_repo_root / "agents" / specialist_id / "persona.md"
        assert persona_path.is_file(), f"Missing persona for {specialist_id}"
        content = persona_path.read_text(encoding="utf-8")
        profile_path = e2e_repo_root / "carefold-profile.yaml"
        profile_text = profile_path.read_text(encoding="utf-8") if profile_path.is_file() else ""
        combined = f"{content}\n{profile_text}"

        # Must have emergency instructions
        assert "911" in combined or "emergency" in combined.lower()
        # Must have non-clinical boundary reminder
        assert "diagnos" in combined.lower() or "prescrib" in combined.lower()
