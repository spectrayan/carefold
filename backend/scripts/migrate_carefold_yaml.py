#!/usr/bin/env python3
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

"""Consolidates carefold.yaml into SKILL.md frontmatter metadata per Agent Skills spec."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from typing import Any, Dict, Tuple
import yaml

APACHE_HEADER = """# Carefold — Healthcare AI Agent Marketplace & Runtime
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
"""

DEFAULT_FALLBACKS: Dict[str, Dict[str, str]] = {
    "benefits-explainer": {"domain": "navigation", "category": "navigation.insurance"},
    "habit-checkin": {"domain": "wellness", "category": "wellness.habits"},
    "visit-prep": {"domain": "clinical", "category": "clinical.general"},
}

STANDARD_FORBIDDEN = [
    "diagnose",
    "prescribe",
    "dose",
    "replace_emergency_care",
    "instruct_stop_medication",
]


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Extracts existing YAML frontmatter and body."""
    normalized = content.replace("\r\n", "\n")
    match = re.match(r"^---\n([\s\S]*?)\n---\n?([\s\S]*)$", normalized)
    if not match:
        return {}, normalized.strip()
    raw_yaml = match.group(1)
    body = match.group(2).strip()
    try:
        parsed = yaml.safe_load(raw_yaml) or {}
    except Exception as err:
        raise ValueError(f"Malformed YAML frontmatter: {err}") from err
    return parsed, body


def migrate_skill(skill_dir: Path, dry_run: bool = False, verbose: bool = False) -> bool:
    """Migrates a single skill pack directory."""
    skill_md_path = skill_dir / "SKILL.md"
    carefold_yaml_path = skill_dir / "carefold.yaml"
    migrated_yaml_path = skill_dir / "carefold.yaml.migrated"

    if not skill_md_path.is_file():
        if verbose:
            print(f"Skipping {skill_dir.name}: No SKILL.md found.")
        return False

    # Check for carefold.yaml
    cf_data: Dict[str, Any] = {}
    if carefold_yaml_path.is_file():
        try:
            cf_data = yaml.safe_load(carefold_yaml_path.read_text(encoding="utf-8")) or {}
        except Exception as err:
            raise RuntimeError(f"Failed to read {carefold_yaml_path}: {err}") from err
    elif migrated_yaml_path.is_file():
        if verbose:
            print(f"{skill_dir.name}: Already migrated (carefold.yaml.migrated exists).")
        # Load from migrated yaml for idempotent re-runs
        try:
            cf_data = yaml.safe_load(migrated_yaml_path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    else:
        if verbose:
            print(f"Warning: Neither carefold.yaml nor carefold.yaml.migrated found in {skill_dir.name}.")

    # Read and parse existing SKILL.md
    raw_skill_md = skill_md_path.read_text(encoding="utf-8")
    existing_fm, body = parse_frontmatter(raw_skill_md)

    skill_name = existing_fm.get("name") or cf_data.get("id") or skill_dir.name
    description = existing_fm.get("description") or cf_data.get("description") or f"Preparation guide for {skill_name}."

    # Tools & allowed-tools
    tools = cf_data.get("tools") or (existing_fm.get("metadata") or {}).get("tools") or []
    allowed_tools = " ".join(tools) if tools else ""

    # Domain & category
    domain = (
        cf_data.get("domain")
        or existing_fm.get("domain")
        or (existing_fm.get("metadata") or {}).get("domain")
        or DEFAULT_FALLBACKS.get(skill_name, {}).get("domain", "wellness")
    )
    category = (
        cf_data.get("category")
        or existing_fm.get("category")
        or (existing_fm.get("metadata") or {}).get("category")
        or DEFAULT_FALLBACKS.get(skill_name, {}).get("category", "")
    )

    # Risk class
    risk_class = (
        cf_data.get("risk_class")
        or (existing_fm.get("metadata") or {}).get("risk_class")
        or "wellness"
    )

    # Version & author
    version = (
        cf_data.get("version")
        or (existing_fm.get("metadata") or {}).get("version")
        or "0.1.0"
    )
    author = (
        (existing_fm.get("metadata") or {}).get("author")
        or "Carefold Core Team"
    )

    # Forbidden verbs & evals
    forbidden = (
        cf_data.get("forbidden")
        or (existing_fm.get("metadata") or {}).get("forbidden")
        or STANDARD_FORBIDDEN
    )
    evals = (
        cf_data.get("evals")
        or (existing_fm.get("metadata") or {}).get("evals")
        or "evals/golden.jsonl"
    )

    # Build consolidated metadata
    metadata = {
        "risk_class": risk_class,
        "domain": domain,
        "category": category,
        "version": version,
        "author": author,
        "tools": tools,
        "forbidden": forbidden,
        "evals": evals,
    }

    # Top-level frontmatter
    new_fm: Dict[str, Any] = {
        "name": skill_name,
        "description": description,
        "license": "Apache-2.0",
        "compatibility": "Requires local LLM or API key for model access",
        "allowed-tools": allowed_tools,
        "metadata": metadata,
    }

    # Serialize YAML frontmatter
    fm_yaml = yaml.dump(new_fm, sort_keys=False, default_flow_style=False, indent=2)
    new_skill_content = f"---\n{APACHE_HEADER}\n{fm_yaml}---\n\n{body}\n"

    if dry_run:
        print(f"[DRY-RUN] Would update {skill_md_path} and archive {carefold_yaml_path}")
        return True

    # Write updated SKILL.md atomically
    skill_md_path.write_text(new_skill_content, encoding="utf-8")

    # Archive carefold.yaml to carefold.yaml.migrated
    if carefold_yaml_path.is_file():
        carefold_yaml_path.rename(migrated_yaml_path)

    print(f"✓ Migrated {skill_dir.name} -> SKILL.md metadata & archived carefold.yaml.migrated")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate Carefold skill manifests to Agent Skills spec.")
    parser.add_argument("--skills-dir", type=Path, default=Path("skills"), help="Path to skills root directory")
    parser.add_argument("--dry-run", action="store_true", help="Simulate migration without modifying files")
    parser.add_argument("--verbose", action="store_true", help="Print verbose migration details")
    args = parser.parse_args()

    skills_root = args.skills_dir.resolve()
    if not skills_root.is_dir():
        print(f"Error: Skills directory not found: {skills_root}", file=sys.stderr)
        return 1

    skill_dirs = sorted([d for d in skills_root.iterdir() if d.is_dir() and not d.name.startswith(".")])
    print(f"Discovered {len(skill_dirs)} skill pack(s) in {skills_root}...")

    migrated_count = 0
    for s_dir in skill_dirs:
        if migrate_skill(s_dir, dry_run=args.dry_run, verbose=args.verbose):
            migrated_count += 1

    print(f"\nMigration complete: {migrated_count}/{len(skill_dirs)} skill packs processed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
