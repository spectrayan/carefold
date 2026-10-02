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

"""Skill manifest loader and validator."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, List, Optional, Union
import yaml
from pydantic import ValidationError

from carefold.constants.defaults import DEFAULT_VERSION
from carefold.constants.paths import (
    CAREFOLD_YAML_FILENAME,
    REFERENCES_DIR,
    SKILL_MANIFEST_FILENAME,
)
from carefold.loaders.frontmatter import check_mandatory_intended_use, parse_frontmatter
from carefold.loaders.union import ToolValidationError, validate_tools_in_phase0
from carefold.schemas.manifest import (
    AgentDomain,
    CarefoldYaml,
    RiskClass,
    SkillFrontmatter,
    SkillManifest,
)


class ManifestValidationError(ValueError):
    """Raised when a manifest fails validation or is missing required fields."""


def _normalize_tags(tags_input: Any) -> List[str]:
    """Normalizes tags from list or comma-separated string into a clean list of strings."""
    if not tags_input:
        return []
    if isinstance(tags_input, str):
        return [t.strip() for t in tags_input.split(",") if t.strip()]
    if isinstance(tags_input, (list, tuple, set)):
        return [str(t).strip() for t in tags_input if str(t).strip()]
    return []


def load_skill(skill_dir: Union[Path, str]) -> SkillManifest:
    """Loads and validates a skill directory containing SKILL.md and optional carefold.yaml."""
    skill_path = Path(skill_dir).resolve()
    if not skill_path.is_dir():
        raise ManifestValidationError(f'Skill directory not found: "{skill_path}"')

    skill_md_path = (skill_path / SKILL_MANIFEST_FILENAME).resolve()
    if not skill_md_path.is_relative_to(skill_path) or not skill_md_path.is_file():
        raise ManifestValidationError(f'Missing required SKILL.md in "{skill_path}"')

    try:
        raw_markdown = skill_md_path.read_text(encoding="utf-8")
    except Exception as err:
        raise ManifestValidationError(f'Cannot read SKILL.md in "{skill_path}": {err}') from err

    # 1. Parse frontmatter
    try:
        parsed = parse_frontmatter(raw_markdown)
    except Exception as err:
        raise ManifestValidationError(f'Invalid frontmatter in "{skill_md_path}": {err}') from err

    carefold_yaml_path = (skill_path / CAREFOLD_YAML_FILENAME).resolve()
    cf_data = {}
    if carefold_yaml_path.is_relative_to(skill_path) and carefold_yaml_path.is_file():
        try:
            raw_yaml = carefold_yaml_path.read_text(encoding="utf-8")
            cf_data = yaml.safe_load(raw_yaml) or {}
        except Exception:
            pass

    fm_dict = dict(parsed.frontmatter)
    if not fm_dict.get("name"):
        if cf_data.get("id"):
            fm_dict["name"] = cf_data["id"]
        elif cf_data.get("name"):
            safe_n = re.sub(r"[^a-zA-Z0-9_\-]", "-", cf_data["name"].strip()).lower()
            fm_dict["name"] = safe_n
        else:
            fm_dict["name"] = skill_path.name

    if not fm_dict.get("description"):
        if cf_data.get("description"):
            fm_dict["description"] = cf_data["description"]
        else:
            fm_dict["description"] = f"{fm_dict.get('name', 'skill')} description"

    try:
        fm = SkillFrontmatter(**fm_dict)
    except ValidationError as err:
        issues = ", ".join(f"{e['loc']}: {e['msg']}" for e in err.errors())
        raise ManifestValidationError(f'Invalid SKILL.md frontmatter in "{skill_path}": {issues}') from err

    # 2. Check 3 mandatory intended-use statements
    valid_use, missing_line = check_mandatory_intended_use(raw_markdown)
    if not valid_use and not (carefold_yaml_path.is_relative_to(skill_path) and carefold_yaml_path.is_file() and not parsed.frontmatter):
        raise ManifestValidationError(
            f'Mandatory intended-use line missing in "{skill_path}/SKILL.md": "{missing_line}"'
        )

    folder_id = skill_path.name
    skill_id = folder_id or fm.name

    # 3. Check for references
    references: List[str] = []
    ref_dir = (skill_path / REFERENCES_DIR).resolve()
    if ref_dir.is_relative_to(skill_path) and ref_dir.is_dir():
        references = sorted([
            f.name for f in ref_dir.iterdir()
            if f.is_file() and not f.name.startswith(".") and (ref_dir / f.name).resolve().is_relative_to(ref_dir)
        ])

    # 4. Check for carefold.yaml
    cf: Optional[CarefoldYaml] = None
    tools: List[str] = []
    if carefold_yaml_path.is_relative_to(skill_path) and carefold_yaml_path.is_file():
        try:
            raw_yaml = carefold_yaml_path.read_text(encoding="utf-8")
            cf_dict = yaml.safe_load(raw_yaml) or {}
            cf = CarefoldYaml(**cf_dict)
        except ValidationError as err:
            issues = ", ".join(f"{e['loc']}: {e['msg']}" for e in err.errors())
            raise ManifestValidationError(f'Invalid carefold.yaml in "{skill_path}": {issues}') from err
        except Exception as err:
            raise ManifestValidationError(f'Malformed carefold.yaml in "{skill_path}": {err}') from err

        tools = cf.tools or []
        validate_tools_in_phase0(tools, f'skill "{skill_id}"')

    # 5. Resolve taxonomy fields across carefold.yaml and SKILL.md frontmatter
    domain_val = None
    if cf and getattr(cf, "domain", None):
        domain_val = cf.domain
    elif getattr(fm, "domain", None):
        domain_val = fm.domain

    if isinstance(domain_val, AgentDomain):
        skill_domain = domain_val
    elif domain_val is not None:
        try:
            val_str = domain_val.value if hasattr(domain_val, "value") else str(domain_val)
            skill_domain = AgentDomain(val_str.strip().lower())
        except ValueError:
            skill_domain = AgentDomain.WELLNESS
    else:
        skill_domain = AgentDomain.WELLNESS

    skill_category = ""
    if cf and getattr(cf, "category", None):
        skill_category = str(cf.category).strip()
    elif getattr(fm, "category", None):
        skill_category = str(fm.category).strip()

    cf_tags = _normalize_tags(getattr(cf, "tags", None)) if cf else []
    fm_tags = _normalize_tags(getattr(fm, "tags", None))
    combined_tags = list(dict.fromkeys(cf_tags + fm_tags))

    if cf is not None:
        return SkillManifest(
            id=cf.id or skill_id,
            name=fm.name,
            description=fm.description,
            version=cf.version or (fm.metadata.version if fm.metadata else DEFAULT_VERSION) or DEFAULT_VERSION,
            license=cf.license or fm.license,
            risk_class=cf.risk_class or RiskClass.WELLNESS,
            domain=skill_domain,
            category=skill_category,
            tags=combined_tags,
            tools=tools,
            forbidden=cf.forbidden or [],
            instructions=parsed.body,
            references=references,
            evals=cf.evals,
            is_verified=True,
            unverified=False,
        )

    # Missing carefold.yaml fallback per CF-S11
    return SkillManifest(
        id=skill_id,
        name=fm.name,
        description=fm.description,
        version=(fm.metadata.version if fm.metadata else DEFAULT_VERSION) or DEFAULT_VERSION,
        license=fm.license,
        risk_class=RiskClass.WELLNESS,
        domain=skill_domain,
        category=skill_category,
        tags=combined_tags,
        tools=[],
        forbidden=[],
        instructions=parsed.body,
        references=references,
        is_verified=False,
        unverified=True,
    )


def load_all_skills(skills_dir: Union[Path, str]) -> List[SkillManifest]:
    """Loads all valid skills from the given skills root directory."""
    skills_path = Path(skills_dir).resolve()
    if not skills_path.is_dir():
        return []

    skills: List[SkillManifest] = []
    for entry in sorted(skills_path.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            try:
                skill = load_skill(entry)
                skills.push(skill) if hasattr(skills, "push") else skills.append(skill)
            except ManifestValidationError:
                # Skip non-skill folders or report
                continue

    return skills
