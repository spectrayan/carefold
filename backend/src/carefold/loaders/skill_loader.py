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
    CAREFOLD_YAML_MIGRATED_FILENAME,
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
SLUG_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")


def find_skill_dir(skills_dir: Union[Path, str], skill_id: str) -> Optional[Path]:
    """Safely resolves a skill directory from a trusted skills directory without path injection."""
    if not skill_id or not isinstance(skill_id, str):
        return None
    raw_id = os.path.basename(skill_id.strip())
    if not SLUG_REGEX.match(raw_id) or raw_id.startswith("."):
        return None

    base_dir = Path(skills_dir).resolve()
    if not base_dir.is_dir():
        return None

    for entry in base_dir.iterdir():
        if entry.is_dir() and entry.name == raw_id:
            resolved_entry = entry.resolve()
            if resolved_entry.is_relative_to(base_dir):
                return resolved_entry

    return None


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

    target_yaml_path = None
    carefold_yaml_path = (skill_path / CAREFOLD_YAML_FILENAME).resolve()
    migrated_yaml_path = (skill_path / CAREFOLD_YAML_MIGRATED_FILENAME).resolve()

    if carefold_yaml_path.is_relative_to(skill_path) and carefold_yaml_path.is_file():
        target_yaml_path = carefold_yaml_path
    elif migrated_yaml_path.is_relative_to(skill_path) and migrated_yaml_path.is_file():
        target_yaml_path = migrated_yaml_path

    cf_data = {}
    if target_yaml_path is not None:
        try:
            raw_yaml = target_yaml_path.read_text(encoding="utf-8")
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
    if not valid_use and not (target_yaml_path is not None and not parsed.frontmatter):
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

    # 4. Check for carefold.yaml / carefold.yaml.migrated
    cf: Optional[CarefoldYaml] = None
    if target_yaml_path is not None:
        try:
            raw_yaml = target_yaml_path.read_text(encoding="utf-8")
            cf_dict = yaml.safe_load(raw_yaml) or {}
            cf = CarefoldYaml(**cf_dict)
        except ValidationError as err:
            issues = ", ".join(f"{e['loc']}: {e['msg']}" for e in err.errors())
            raise ManifestValidationError(f'Invalid {target_yaml_path.name} in "{skill_path}": {issues}') from err
        except Exception as err:
            raise ManifestValidationError(f'Malformed {target_yaml_path.name} in "{skill_path}": {err}') from err

    # 5. Resolve tools
    meta = fm.metadata
    tools: List[str] = []
    if meta and meta.tools is not None:
        tools = list(meta.tools)
    elif cf and cf.tools is not None:
        tools = list(cf.tools)
    elif fm.allowed_tools:
        tools = [t.strip() for t in fm.allowed_tools.split() if t.strip()]

    if tools:
        validate_tools_in_phase0(tools, f'skill "{skill_id}"')

    # 6. Resolve taxonomy fields across carefold.yaml and SKILL.md frontmatter
    domain_val = None
    if meta and meta.domain is not None:
        domain_val = meta.domain
    elif cf and getattr(cf, "domain", None):
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
    if meta and meta.category:
        skill_category = str(meta.category).strip()
    elif cf and getattr(cf, "category", None):
        skill_category = str(cf.category).strip()
    elif getattr(fm, "category", None):
        skill_category = str(fm.category).strip()

    cf_tags = _normalize_tags(getattr(cf, "tags", None)) if cf else []
    meta_tags = _normalize_tags(getattr(meta, "tags", None)) if meta else []
    fm_tags = _normalize_tags(getattr(fm, "tags", None))
    combined_tags = list(dict.fromkeys(cf_tags + meta_tags + fm_tags))

    # Risk class
    risk_class = RiskClass.WELLNESS
    if meta and meta.risk_class is not None:
        risk_class = meta.risk_class
    elif cf and cf.risk_class is not None:
        risk_class = cf.risk_class

    # Forbidden actions
    forbidden = []
    if meta and meta.forbidden is not None:
        forbidden = meta.forbidden
    elif cf and cf.forbidden is not None:
        forbidden = cf.forbidden

    # Evals path
    evals_path = None
    if meta and meta.evals is not None:
        evals_path = meta.evals
    elif cf and cf.evals is not None:
        evals_path = cf.evals

    # Version
    version = DEFAULT_VERSION
    if meta and meta.version:
        version = meta.version
    elif cf and cf.version:
        version = cf.version

    license_val = (cf.license if cf else None) or fm.license

    # Verification status
    has_spec = (
        cf is not None or
        (meta is not None and (
            meta.risk_class is not None or
            meta.tools is not None or
            meta.category is not None
        )) or
        fm.allowed_tools is not None
    )

    # Title resolution: metadata.title -> frontmatter title -> cf.title -> title-cased slug
    resolved_title: str = ""
    if meta and getattr(meta, "title", None) and str(meta.title).strip():
        resolved_title = str(meta.title).strip()
    elif getattr(fm, "title", None) and str(fm.title).strip():
        resolved_title = str(fm.title).strip()
    elif cf and getattr(cf, "title", None) and str(cf.title).strip():
        resolved_title = str(cf.title).strip()
    else:
        slug_for_title = (cf.id if cf else None) or skill_id or fm.name
        resolved_title = slug_for_title.replace("_", " ").replace("-", " ").title()

    if has_spec:
        return SkillManifest(
            id=(cf.id if cf else None) or skill_id,
            name=fm.name,
            title=resolved_title,
            description=fm.description,
            version=version,
            license=license_val,
            risk_class=risk_class,
            domain=skill_domain,
            category=skill_category,
            tags=combined_tags,
            tools=tools,
            forbidden=forbidden,
            instructions=parsed.body,
            references=references,
            evals=evals_path,
            is_verified=True,
            unverified=False,
        )

    # Missing carefold.yaml fallback per CF-S11
    return SkillManifest(
        id=skill_id,
        name=fm.name,
        title=resolved_title,
        description=fm.description,
        version=version,
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
        if entry.is_dir() and not entry.name.startswith((".", "_")):
            try:
                skill = load_skill(entry)
                skills.append(skill)
            except ManifestValidationError:
                # Skip non-skill folders or report
                continue

    return skills
