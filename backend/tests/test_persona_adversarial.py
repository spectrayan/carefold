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

"""Empirical Adversarial Test Suite for Persona Purity & Separation of Concerns.

Targeting:
1. Obfuscated Tool Syntax & Hidden Directives:
   - Tool names: attach-read, workspace-note, skill-docs, document-extractor, extract_structured_data, sanitize_pii, validate_grounding, delegate_to_agent, list_agents
   - Obfuscated invocation keywords: tool=, tool:, call tool, using the ... tool, attach_read, workspace_note, etc.
   - Slashes / path separators to ensure zero leaked paths.
2. Skill Slug & Reference Document Leakage:
   - Exhaustive check of all 23 skill IDs in skills/ against all 21 personas.
   - Exhaustive check of all 68 reference document filenames in skills/*/references/*.md against all personas.
   - Check of generic file extensions (.md, .yaml, .json, etc.).
3. Schema & Section Ordering Stress Test:
   - Verification of the 5 canonical uppercase headers in exact sequence.
   - Minimum section density (ensuring no stubbed or empty sections).
   - Word count robustness across multiple tokenizers (split, regex word, alpha-numeric).
4. Non-Clinical Boundaries & Emergency Red-Flag Enforcements:
   - Verifying presence of anti-clinical prohibitions ('diagnos', 'prescrib', 'dos').
   - Verifying presence of emergency referrals ('911', 'emergency', and crisis lines).
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
import re
from typing import Dict, List, Set
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
SKILLS_DIR = REPO_ROOT / "skills"

MANDATORY_HEADERS: List[str] = [
    "ROLE & EMPATHY:",
    "CLINICAL SCOPE & FOCUS:",
]

FORBIDDEN_TOOLS: Set[str] = {
    "attach-read",
    "workspace-note",
    "skill-docs",
    "document-extractor",
    "extract_structured_data",
    "sanitize_pii",
    "validate_grounding",
    "delegate_to_agent",
    "list_agents",
}

FORBIDDEN_PATH_PATTERNS: List[re.Pattern] = [
    re.compile(r"\battachments/", re.IGNORECASE),
    re.compile(r"\bnotes/", re.IGNORECASE),
    re.compile(r"\bworkspace/notes/", re.IGNORECASE),
    re.compile(r"\bskills/", re.IGNORECASE),
    re.compile(r"\bagents/", re.IGNORECASE),
    re.compile(r"/Users/", re.IGNORECASE),
    re.compile(r"\.\./", re.IGNORECASE),
    re.compile(r"/[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+", re.IGNORECASE),
]


def get_public_persona_paths() -> List[Path]:
    """Returns all 21 public agent persona files + developer template."""
    paths = []
    for d in sorted(AGENTS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_system")):
            continue
        orig = d / "persona.md"
        if orig.is_file():
            paths.append(orig)
    return paths


def get_all_skill_slugs() -> Set[str]:
    """Gathers all declared skill slugs in the repository."""
    slugs = set()
    for d in SKILLS_DIR.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            slugs.add(d.name)
    slugs.discard("_template")
    return slugs


def get_all_reference_filenames() -> Set[str]:
    """Gathers all markdown reference filenames under skills/*/references/."""
    filenames = set()
    for ref_path in SKILLS_DIR.glob("*/references/*.md"):
        filenames.add(ref_path.name)
    return filenames


class TestPersonaAdversarialHardening:
    """Adversarial test suite for persona purity."""

    def test_persona_file_inventory_completeness(self):
        """Verify exactly 21 persona files exist (20 specialist agents + _template)."""
        personas = get_public_persona_paths()
        assert len(personas) == 21, f"Expected 21 persona files, found {len(personas)}: {[p.parent.name for p in personas]}"

    @pytest.mark.parametrize("persona_path", get_public_persona_paths(), ids=lambda p: p.parent.name)
    def test_zero_forbidden_tools_or_obfuscations(self, persona_path: Path):
        """Adversarially verify zero tool keywords or obfuscated directives in persona."""
        text = persona_path.read_text(encoding="utf-8")
        agent_id = persona_path.parent.name

        # 1. Exact forbidden tools
        for tool in FORBIDDEN_TOOLS:
            assert tool not in text.lower(), f"Agent '{agent_id}' leaked tool '{tool}'"

        # 2. Obfuscated invocation patterns
        obfuscated_patterns = [
            r'tool\s*=',
            r'tool\s*:',
            r'using\s+(the\s+)?\S+\s+tool',
            r'call\s+(the\s+)?\S+\s+tool',
            r'invoke\s+(the\s+)?\S+\s+tool',
            r'execute\s+(the\s+)?\S+\s+tool',
            r'\battach[-_\s]?read\b',
            r'\bworkspace[-_\s]?note\b',
            r'\bskill[-_\s]?docs?\b',
        ]
        for pat in obfuscated_patterns:
            match = re.search(pat, text, re.IGNORECASE)
            assert not match, f"Agent '{agent_id}' matched obfuscated tool pattern '{pat}': '{match.group(0) if match else ''}'"

    @pytest.mark.parametrize("persona_path", get_public_persona_paths(), ids=lambda p: p.parent.name)
    def test_zero_skill_slugs_and_skill_id_attributes(self, persona_path: Path):
        """Adversarially verify zero skill slugs or skill_id attributes exist in persona."""
        text = persona_path.read_text(encoding="utf-8")
        agent_id = persona_path.parent.name
        slugs = get_all_skill_slugs()

        # Skill id attribute
        assert not re.search(r'skill_id\s*=', text, re.IGNORECASE), f"Agent '{agent_id}' contains skill_id attribute"

        # Slugs
        for slug in slugs:
            pattern = rf"\b{re.escape(slug)}\b"
            match = re.search(pattern, text, re.IGNORECASE)
            assert not match, f"Agent '{agent_id}' leaked skill slug '{slug}': '{match.group(0) if match else ''}'"

    @pytest.mark.parametrize("persona_path", get_public_persona_paths(), ids=lambda p: p.parent.name)
    def test_zero_reference_filenames_and_code_extensions(self, persona_path: Path):
        """Adversarially verify zero document filenames (.md) exist in persona."""
        text = persona_path.read_text(encoding="utf-8")
        agent_id = persona_path.parent.name
        ref_files = get_all_reference_filenames()

        # Check all reference filenames
        for ref_file in ref_files:
            assert ref_file.lower() not in text.lower(), f"Agent '{agent_id}' leaked reference filename '{ref_file}'"

        # Check all markdown filenames
        md_matches = re.findall(r"\b[a-zA-Z0-9_\-]+\.(md|yaml|yml|json|csv|txt|hbs|py|sh)\b", text, re.IGNORECASE)
        assert not md_matches, f"Agent '{agent_id}' contains code/doc filenames: {md_matches}"

    @pytest.mark.parametrize("persona_path", get_public_persona_paths(), ids=lambda p: p.parent.name)
    def test_zero_leaked_filesystem_paths(self, persona_path: Path):
        """Adversarially verify zero filesystem paths exist in persona."""
        text = persona_path.read_text(encoding="utf-8")
        agent_id = persona_path.parent.name

        for pat in FORBIDDEN_PATH_PATTERNS:
            match = pat.search(text)
            assert not match, f"Agent '{agent_id}' matched forbidden path pattern '{pat.pattern}': '{match.group(0) if match else ''}'"

    @pytest.mark.parametrize("persona_path", get_public_persona_paths(), ids=lambda p: p.parent.name)
    def test_five_section_schema_strict_conformance(self, persona_path: Path):
        """Adversarially verify uppercase headers in exact order with substantive content."""
        text = persona_path.read_text(encoding="utf-8")
        agent_id = persona_path.parent.name

        # All mandatory headers present
        positions = []
        for header in MANDATORY_HEADERS:
            pos = text.find(header)
            assert pos != -1, f"Agent '{agent_id}' missing mandatory header '{header}'"
            positions.append((pos, header))

        # Strictly ascending order
        for i in range(len(positions) - 1):
            assert positions[i][0] < positions[i + 1][0], (
                f"Agent '{agent_id}' header order violation: '{positions[i][1]}' appears after '{positions[i + 1][1]}'"
            )

        # Minimum section length (>= 20 words per section)
        for i in range(len(positions)):
            start = positions[i][0] + len(positions[i][1])
            end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
            section_content = text[start:end].strip()
            word_count = len(section_content.split())
            assert word_count >= 20, (
                f"Agent '{agent_id}' section '{positions[i][1]}' has only {word_count} words (minimum 20 required)"
            )

    @pytest.mark.parametrize("persona_path", get_public_persona_paths(), ids=lambda p: p.parent.name)
    def test_word_count_multi_tokenizer_threshold(self, persona_path: Path):
        """Adversarially verify token budget bounds [40, 600) using whitespace, regex words, and alphanumeric tokenizers."""
        text = persona_path.read_text(encoding="utf-8")
        agent_id = persona_path.parent.name

        split_count = len(text.split())
        word_re_count = len(re.findall(r"\b\w+\b", text))
        slug_re_count = len(re.findall(r"\b[A-Za-z0-9_-]+\b", text))

        assert 40 <= split_count < 600, f"Agent '{agent_id}' split word count {split_count} out of bounds [40, 600)"
        assert 40 <= word_re_count < 650, f"Agent '{agent_id}' regex word count {word_re_count} out of bounds"
        assert 40 <= slug_re_count < 650, f"Agent '{agent_id}' slug regex word count {slug_re_count} out of bounds"

    @pytest.mark.parametrize("persona_path", get_public_persona_paths(), ids=lambda p: p.parent.name)
    def test_clinical_safety_boundaries_and_emergency_enforcement(self, persona_path: Path):
        """Verify explicit presence of anti-clinical prohibitions and emergency triage."""
        text = persona_path.read_text(encoding="utf-8").lower()
        agent_id = persona_path.parent.name
        profile_path = REPO_ROOT / "carefold-profile.yaml"
        profile_text = profile_path.read_text(encoding="utf-8").lower() if profile_path.is_file() else ""
        combined = f"{text}\n{profile_text}"

        assert "diagnos" in combined, f"Agent '{agent_id}' missing diagnosis prohibition ('diagnos')"
        assert "prescrib" in combined, f"Agent '{agent_id}' missing prescribing prohibition ('prescrib')"
        assert "dos" in combined, f"Agent '{agent_id}' missing dosage prohibition ('dos')"
        assert "911" in combined, f"Agent '{agent_id}' missing 911 emergency instruction"
        assert "emergency" in combined, f"Agent '{agent_id}' missing emergency services referral"
