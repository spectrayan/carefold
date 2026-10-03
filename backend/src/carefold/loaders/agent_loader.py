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

"""Agent manifest loader, skill resolver, and permission union engine."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union
import yaml
from pydantic import ValidationError

from carefold.constants.defaults import BUNDLED_AGENT_IDS
from carefold.constants.paths import (
    AGENT_MANIFEST_FILENAME,
    README_FILENAME,
    SKILLS_DIR,
    STARTERS_FILENAME,
    SYSTEM_AGENTS_DIR,
    TEMPLATE_DIR,
)
from carefold.loaders.skill_loader import ManifestValidationError, find_skill_dir, load_skill
from carefold.loaders.union import (
    ToolValidationError,
    compute_effective_tools,
    validate_tools_in_phase0,
)
from carefold.schemas.manifest import (
    PHASE_0_REGISTRY,
    SLUG_REGEX,
    AgentDetailResponse,
    AgentDomain,
    AgentManifest,
    AgentMaturity,
    AgentSummary,
    ResolvedSkillSummary,
    RiskClass,
    SkillManifest,
    ToolDefinitionSchema,
)


def load_agent_starters(agent_dir: Union[Path, str]) -> List[str]:
    """Loads prompt starter strings from starters.json if present."""
    agent_path = Path(agent_dir).resolve()
    starters_file = (agent_path / STARTERS_FILENAME).resolve()
    if not starters_file.is_relative_to(agent_path) or not starters_file.is_file():
        return []
    try:
        data = json.loads(starters_file.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(s) for s in data if s]
        if isinstance(data, dict) and "starters" in data and isinstance(data["starters"], list):
            return [str(s) for s in data["starters"] if s]
    except Exception:
        pass
    return []


def load_agent_readme(agent_dir: Union[Path, str]) -> Optional[str]:
    """Loads README.md text if present."""
    agent_path = Path(agent_dir).resolve()
    readme_file = (agent_path / README_FILENAME).resolve()
    if not readme_file.is_relative_to(agent_path) or not readme_file.is_file():
        return None
    try:
        return readme_file.read_text(encoding="utf-8")
    except Exception:
        return None


HEADER_PREFIX_PATTERN = re.compile(
    r"^(?:#+\s*|\*+\s*)?(?:ROLE(?:\s*&|\s+AND)?\s*EMPATHY|ROLE|CLINICAL SCOPE(?:\s*&|\s+FOCUS)?|MISSION|OVERVIEW|PURPOSE|BACKGROUND|INTENDED BEHAVIOR)[\s:]*$",
    re.IGNORECASE,
)


def extract_fallback_description(persona: Union[str, Dict[str, Any], Any]) -> str:
    """Extracts a substantive summary from an agent persona, skipping section headers."""
    if not persona:
        return ""
    if isinstance(persona, dict):
        role = persona.get("role", "")
        if role and not HEADER_PREFIX_PATTERN.match(role.strip()):
            return role.strip()
        instructions = persona.get("instructions", "")
        if instructions:
            return extract_fallback_description(instructions)
        return ""
    if hasattr(persona, "role") and getattr(persona, "role"):
        role = getattr(persona, "role")
        if not HEADER_PREFIX_PATTERN.match(str(role).strip()):
            return str(role).strip()

    if isinstance(persona, str):
        lines = [line.strip() for line in persona.strip().splitlines()]
        for line in lines:
            if not line:
                continue
            if line.startswith("#") or line.startswith("---") or line.startswith("==="):
                continue
            if HEADER_PREFIX_PATTERN.match(line):
                continue
            if len(line) < 35 and line.endswith(":") and "." not in line:
                continue
            return line

    return ""


def find_agent_dir(agents_dir: Union[Path, str], agent_id: str) -> Optional[Path]:
    """Safely resolves an agent directory from a trusted agents directory without path injection."""
    if not agent_id or not isinstance(agent_id, str):
        return None
    raw_id = os.path.basename(agent_id.strip())
    if not SLUG_REGEX.match(raw_id) or raw_id.startswith("."):
        return None

    base_dir = Path(agents_dir).resolve()
    if not base_dir.is_dir():
        return None

    for entry in base_dir.iterdir():
        if entry.is_dir() and entry.name == raw_id and not entry.name.startswith((".", "_")):
            resolved_entry = entry.resolve()
            if resolved_entry.is_relative_to(base_dir):
                return resolved_entry

    system_dir = (base_dir / SYSTEM_AGENTS_DIR).resolve()
    if system_dir.is_dir():
        for entry in system_dir.iterdir():
            if entry.is_dir() and entry.name == raw_id and not entry.name.startswith("."):
                resolved_entry = entry.resolve()
                if resolved_entry.is_relative_to(base_dir):
                    return resolved_entry

    # Allow custom or template dirs (e.g. _template) if exact match
    for entry in base_dir.iterdir():
        if entry.is_dir() and entry.name == raw_id:
            resolved_entry = entry.resolve()
            if resolved_entry.is_relative_to(base_dir):
                return resolved_entry

    return None


def load_agent(
    agent_dir: Union[Path, str],
    skills_dir: Optional[Union[Path, str]] = None,
) -> Tuple[AgentManifest, List[str], List[SkillManifest]]:
    """Loads and validates an agent directory containing agent.yaml and resolves declared skills.

    Returns: (agent_manifest, effective_tools, loaded_skills)
    """
    agent_path = Path(agent_dir).resolve()
    if not agent_path.is_dir():
        raise ManifestValidationError(f'Agent directory not found: "{agent_path}"')

    agent_yaml_path = (agent_path / AGENT_MANIFEST_FILENAME).resolve()
    if not agent_yaml_path.is_relative_to(agent_path) or not agent_yaml_path.is_file():
        raise ManifestValidationError(f'Missing required agent.yaml in "{agent_path}"')

    try:
        raw_yaml = agent_yaml_path.read_text(encoding="utf-8")
        parsed_yaml = yaml.safe_load(raw_yaml)
    except Exception as err:
        raise ManifestValidationError(f'Malformed YAML in "{agent_yaml_path}": {err}') from err

    if not isinstance(parsed_yaml, dict):
        raise ManifestValidationError(f'Expected YAML dictionary in "{agent_yaml_path}"')

    # Load companion metadata.yaml if present
    metadata_yaml_path = (agent_path / "metadata.yaml").resolve()
    meta_dict: Dict[str, Any] = {}
    if metadata_yaml_path.is_relative_to(agent_path) and metadata_yaml_path.is_file():
        try:
            loaded_meta = yaml.safe_load(metadata_yaml_path.read_text(encoding="utf-8"))
            if isinstance(loaded_meta, dict):
                meta_dict = loaded_meta
        except Exception as err:
            raise ManifestValidationError(f'Malformed YAML in "{metadata_yaml_path}": {err}') from err

    # Merge companion metadata fields into parsed_yaml with priority: metadata.yaml > agent.yaml > defaults
    is_system = agent_path.parent.name == SYSTEM_AGENTS_DIR or agent_path.name.startswith("_")
    agent_id = parsed_yaml.get("id") or meta_dict.get("id") or parsed_yaml.get("name") or agent_path.name
    parsed_yaml["id"] = agent_id

    if "title" not in parsed_yaml:
        parsed_yaml["title"] = meta_dict.get("title") or agent_id.replace("-", " ").title()

    if "version" not in parsed_yaml and "version" in meta_dict:
        parsed_yaml["version"] = meta_dict["version"]

    if "license" not in parsed_yaml and "license" in meta_dict:
        parsed_yaml["license"] = meta_dict["license"]

    if "care_stages" not in parsed_yaml and "care_stages" in meta_dict:
        parsed_yaml["care_stages"] = meta_dict["care_stages"]

    if "target_audience" not in parsed_yaml and "target_audience" in meta_dict:
        parsed_yaml["target_audience"] = meta_dict["target_audience"]

    if "tags" not in parsed_yaml and "tags" in meta_dict:
        parsed_yaml["tags"] = meta_dict["tags"]

    if "icon" not in parsed_yaml and "icon" in meta_dict:
        parsed_yaml["icon"] = meta_dict["icon"]

    if "maturity" not in parsed_yaml and "maturity" in meta_dict:
        parsed_yaml["maturity"] = meta_dict["maturity"]

    if "hidden" not in parsed_yaml and "hidden" in meta_dict:
        parsed_yaml["hidden"] = meta_dict["hidden"]

    if "domain" not in parsed_yaml and "domain" in meta_dict:
        parsed_yaml["domain"] = meta_dict["domain"]

    if "category" not in parsed_yaml and "category" in meta_dict:
        parsed_yaml["category"] = meta_dict["category"]

    if "risk_class" not in parsed_yaml and "risk_class" in meta_dict:
        parsed_yaml["risk_class"] = meta_dict["risk_class"]

    if "description" not in parsed_yaml and "description" in meta_dict:
        parsed_yaml["description"] = meta_dict["description"]

    if "forbidden" not in parsed_yaml:
        parsed_yaml["forbidden"] = meta_dict.get(
            "forbidden",
            ["diagnose", "prescribe", "dose", "replace_emergency_care", "instruct_stop_medication"],
        )

    raw_skills = parsed_yaml.get("skills", [])
    if isinstance(raw_skills, list):
        parsed_yaml["skills"] = [
            s.strip("/").split("/")[-1] if isinstance(s, str) and s.startswith("/") else s
            for s in raw_skills
        ]

    raw_model = parsed_yaml.get("model")
    if isinstance(raw_model, str) and raw_model and ":" not in raw_model:
        parsed_yaml["model"] = f"ollama:{raw_model}"

    # Resolve persona file reference if present
    persona_val = parsed_yaml.get("persona")
    persona_file = parsed_yaml.get("persona_file")

    if persona_file and isinstance(persona_file, str):
        if ".." in persona_file or persona_file.startswith(("/", "\\")):
            raise ManifestValidationError(f'Path traversal in persona_file: "{persona_file}"')
        target_file = (agent_path / persona_file).resolve()
        if not target_file.is_relative_to(agent_path):
            raise ManifestValidationError(f'Persona file outside agent directory: "{persona_file}"')
        if target_file.is_file():
            parsed_yaml["persona"] = target_file.read_text(encoding="utf-8")
            parsed_yaml["persona_file"] = persona_file
        else:
            raise ManifestValidationError(f'Persona file not found: "{persona_file}" in "{agent_path}"')
    elif isinstance(persona_val, str) and "\n" not in persona_val:
        cleaned_val = persona_val.strip()
        if ".." in cleaned_val or cleaned_val.startswith(("/", "\\")):
            raise ManifestValidationError(f'Path traversal in persona: "{persona_val}"')
        target_file = (agent_path / cleaned_val).resolve()
        if not target_file.is_relative_to(agent_path):
            raise ManifestValidationError(f'Persona file outside agent directory: "{persona_val}"')
        if target_file.is_file():
            parsed_yaml["persona"] = target_file.read_text(encoding="utf-8")
            parsed_yaml["persona_file"] = cleaned_val
        elif cleaned_val.endswith(".md"):
            raise ManifestValidationError(f'Persona file not found: "{persona_val}" in "{agent_path}"')
    elif (persona_val is None or persona_val == ""):
        for default_name in ("persona.md", "persona_slim.md"):
            default_persona = (agent_path / default_name).resolve()
            if default_persona.is_relative_to(agent_path) and default_persona.is_file():
                parsed_yaml["persona"] = default_persona.read_text(encoding="utf-8")
                parsed_yaml["persona_file"] = default_name
                break

    try:
        agent = AgentManifest(**parsed_yaml)
    except ValidationError as err:
        issues = ", ".join(f"{e['loc']}: {e['msg']}" for e in err.errors())
        raise ManifestValidationError(f'Invalid agent.yaml in "{agent_path}": {issues}') from err

    if agent_path.name != agent.id:
        raise ManifestValidationError(
            f'Agent ID mismatch: Directory name "{agent_path.name}" does not match manifest ID "{agent.id}".'
        )

    # Validate agent-declared tools against Phase 0 closed registry
    validate_tools_in_phase0(agent.tools, f'agent "{agent.id}"')

    # Resolve skills directory
    if skills_dir:
        resolved_skills_dir = Path(skills_dir).resolve()
    else:
        # Check standard (2 levels up), nested (_system/ 3 levels up), or sibling skills directory
        for candidate in (
            agent_path.parent.parent / SKILLS_DIR,
            agent_path.parent.parent.parent / SKILLS_DIR,
            agent_path.parent / SKILLS_DIR,
        ):
            if candidate.is_dir():
                resolved_skills_dir = candidate.resolve()
                break
        else:
            resolved_skills_dir = (agent_path.parent.parent / SKILLS_DIR).resolve()

    # Load and validate declared skills
    loaded_skills: List[SkillManifest] = []
    for skill_id in agent.skills:
        if not SLUG_REGEX.match(skill_id):
            raise ManifestValidationError(
                f'Invalid declared skill ID "{skill_id}": Skill IDs must be alphanumeric slugs.'
            )
        skill_path = find_skill_dir(resolved_skills_dir, skill_id)
        if not skill_path or not skill_path.is_dir():
            raise ManifestValidationError(
                f'Missing declared skill: {skill_id} (looked in "{resolved_skills_dir}")'
            )

        skill = load_skill(skill_path)
        loaded_skills.append(skill)

    # Compute effective tools union: unique(agent.tools ∪ skill.tools) ∩ Phase0Registry
    effective_tools = compute_effective_tools(agent.tools, loaded_skills)

    # Populate domain, category, risk_class from primary skill if not explicit
    primary_skill = loaded_skills[0] if loaded_skills else None
    if primary_skill:
        if "domain" not in parsed_yaml and "domain" not in meta_dict:
            agent.domain = primary_skill.domain
        if "category" not in parsed_yaml and "category" not in meta_dict:
            agent.category = primary_skill.category
        if "risk_class" not in parsed_yaml and "risk_class" not in meta_dict:
            agent.risk_class = primary_skill.risk_class

    # Risk class elevation: if any declared skill is clinical_assist, agent is clinical_assist
    if any(s.risk_class == RiskClass.CLINICAL_ASSIST for s in loaded_skills):
        agent.risk_class = RiskClass.CLINICAL_ASSIST

    return agent, effective_tools, loaded_skills


def load_all_agents(
    agents_dir: Union[Path, str],
    skills_dir: Optional[Union[Path, str]] = None,
) -> List[AgentSummary]:
    """Discovers and summarizes all valid agents in agents_dir, including agents/_system."""
    agents_path = Path(agents_dir).resolve()
    if not agents_path.is_dir():
        return []

    candidates: List[Tuple[Path, bool]] = []
    if agents_path.name == SYSTEM_AGENTS_DIR:
        for entry in sorted(agents_path.iterdir()):
            if entry.is_dir() and not entry.name.startswith((".", "_")):
                candidates.append((entry, True))
    else:
        for entry in sorted(agents_path.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name == SYSTEM_AGENTS_DIR:
                for subentry in sorted(entry.iterdir()):
                    if subentry.is_dir() and not subentry.name.startswith((".", "_")):
                        candidates.append((subentry, True))
            elif not entry.name.startswith((".", "_")):
                candidates.append((entry, False))

    candidates.sort(key=lambda item: item[0].name)

    summaries: List[AgentSummary] = []
    for entry, is_system in candidates:
        try:
            agent, effective_tools, _ = load_agent(entry, skills_dir)
            if is_system:
                agent.hidden = True
            starters = load_agent_starters(entry)
            is_bundled = entry.name in BUNDLED_AGENT_IDS

            # Description extraction: prefer manifest.description, fallback to sanitized persona summary
            desc = agent.description or extract_fallback_description(agent.persona)

            summaries.append(
                AgentSummary(
                    id=agent.id,
                    title=agent.title,
                    version=agent.version,
                    risk_class=agent.risk_class.value,
                    domain=agent.domain,
                    category=agent.category,
                    care_stages=agent.care_stages,
                    target_audience=agent.target_audience,
                    tags=agent.tags,
                    icon=agent.icon,
                    maturity=agent.maturity,
                    skills=agent.skills,
                    effectiveTools=effective_tools,
                    tools=agent.tools,
                    starters=starters,
                    startersCount=len(starters),
                    description=desc,
                    can_delegate=agent.can_delegate,
                    max_iterations=agent.max_iterations,
                    is_bundled=is_bundled,
                    isBundled=is_bundled,
                    clinical_enabled=True,
                    verified=True,
                    hidden=True if is_system else agent.hidden,
                    persona_file=agent.persona_file,
                )
            )
        except Exception as err:
            summaries.append(
                AgentSummary(
                    id=entry.name,
                    title=entry.name,
                    version="0.0.0",
                    risk_class="wellness",
                    domain=AgentDomain.WELLNESS,
                    category="",
                    care_stages=[],
                    target_audience=[],
                    tags=[],
                    icon="Shield",
                    maturity=AgentMaturity.STABLE,
                    skills=[],
                    effectiveTools=[],
                    tools=[],
                    verified=False,
                    hidden=is_system,
                    error=str(err),
                )
            )

    return summaries


def load_subagent_from_yaml(
    agent_dir: Union[Path, str],
    resolve_tools: bool = False,
) -> Dict[str, Any]:
    """Builds a native Deep Agents SubAgent dict from slim agent.yaml."""
    agent_path = Path(agent_dir).resolve()
    yaml_file = agent_path / AGENT_MANIFEST_FILENAME
    if not yaml_file.is_file():
        raise FileNotFoundError(f'Missing required agent.yaml in "{agent_path}"')

    raw = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raw = {}

    persona_ref = raw.get("persona") or "persona.md"
    persona_path = agent_path / persona_ref
    if not persona_path.is_file():
        for fallback in ("persona.md", "persona_slim.md"):
            fb_path = agent_path / fallback
            if fb_path.is_file():
                persona_path = fb_path
                break

    system_prompt = persona_path.read_text(encoding="utf-8") if persona_path.is_file() else ""

    declared_tools = raw.get("tools", [])
    if not isinstance(declared_tools, list):
        declared_tools = []
    valid_tools = [t for t in declared_tools if t in PHASE_0_REGISTRY]

    if resolve_tools:
        from carefold.tools.registry import CLOSED_TOOL_DEFINITIONS

        tools_payload = [CLOSED_TOOL_DEFINITIONS[t] for t in valid_tools if t in CLOSED_TOOL_DEFINITIONS]
    else:
        tools_payload = valid_tools

    skills = raw.get("skills", [])
    if not isinstance(skills, list):
        skills = []

    return {
        "name": raw.get("name") or raw.get("id", agent_path.name),
        "description": raw.get("description", ""),
        "system_prompt": system_prompt,
        "model": raw.get("model", "ollama:llama3.2"),
        "skills": skills,
        "tools": tools_payload,
    }
