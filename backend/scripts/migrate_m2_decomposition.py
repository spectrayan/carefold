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

"""Migration script for Milestone 2: Persona slimming and agent manifest splitting."""

from __future__ import annotations

from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
SKILLS_DIR = REPO_ROOT / "skills"

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

SPECIALISTS_MAP: Dict[str, str] = {
    "benefits-guide": "benefits-explainer",
    "cardiology-guide": "cardiology-prep",
    "claims-appeals-guide": "claims-appeals-prep",
    "derma-guide": "derma-prep",
    "endocrinology-guide": "endocrinology-prep",
    "ent-guide": "ent-prep",
    "eye-guide": "vision-prep",
    "formulary-guide": "formulary-navigation",
    "gastro-guide": "gastro-prep",
    "habit-companion": "habit-checkin",
    "nephrology-guide": "nephrology-prep",
    "neurology-guide": "neurology-prep",
    "oncology-navigator": "oncology-prep",
    "ortho-guide": "ortho-prep",
    "prior-auth-navigator": "prior-auth-prep",
    "pulmonology-guide": "pulmonology-prep",
    "records-coordinator": "records-management",
    "rheuma-guide": "rheuma-prep",
    "urology-guide": "urology-prep",
    "visit-steward": "visit-prep",
    "_template": "_template",
}

SYSTEM_AGENTS_MAP: Dict[str, Dict[str, Any]] = {
    "orchestrator": {"icon": "Cpu", "can_delegate": True, "max_iterations": 5},
    "document-extractor": {"icon": "FileSearch", "can_delegate": False, "max_iterations": 3},
    "quality-reviewer": {
        "icon": "CheckCheck",
        "can_delegate": False,
        "max_iterations": 3,
        "primary_skill": "clinical-safety-boundaries",
    },
    "skill-generator": {"icon": "Sparkles", "can_delegate": False, "max_iterations": 1},
    "suggestion-generator": {"icon": "MessageSquare", "can_delegate": False, "max_iterations": 1},
    "triage-auditor": {
        "icon": "ShieldAlert",
        "can_delegate": False,
        "max_iterations": 3,
        "primary_skill": "emergency-red-flags",
    },
}

SECTION_PATTERN = re.compile(
    r"^(ROLE & EMPATHY:|CLINICAL SCOPE & FOCUS:|STRUCTURED INTERACTION PROTOCOL:|"
    r"STRICT NON-CLINICAL BOUNDARIES:|EXPLICIT EMERGENCY RED FLAGS:)\s*$",
    re.MULTILINE,
)


class CarefoldYamlDumper(yaml.SafeDumper):
    """Custom YAML dumper providing standard 2-space indented lists."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    """Formats strings into folded or literal blocks when appropriate."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    if len(data.split()) > 10:
        return dumper.represent_scalar("tag:yaml.org,2002:str", " ".join(data.split()), style=">")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


CarefoldYamlDumper.add_representer(str, str_representer)


def parse_persona_sections(content: str) -> Dict[str, str]:
    """Parses standard 5-section persona text into section name -> body."""
    splits = SECTION_PATTERN.split(content)
    sections: Dict[str, str] = {}
    for i in range(1, len(splits), 2):
        sections[splits[i].strip()] = splits[i + 1].strip()
    return sections


def decompose_persona(
    agent_dir: Path,
    skill_dir: Optional[Path] = None,
    append_protocol_to_skill: bool = True,
) -> bool:
    """Decomposes persona.md into persona_slim.md, moves protocol to SKILL.md, archives persona.md."""
    persona_path = agent_dir / "persona.md"
    migrated_path = agent_dir / "persona.md.migrated"
    slim_path = agent_dir / "persona_slim.md"

    if not persona_path.exists():
        if migrated_path.exists() and slim_path.exists():
            return True
        return False

    content = persona_path.read_text(encoding="utf-8")
    sections = parse_persona_sections(content)

    s1 = sections.get("ROLE & EMPATHY:", "")
    s2 = sections.get("CLINICAL SCOPE & FOCUS:", "")
    s3 = sections.get("STRUCTURED INTERACTION PROTOCOL:", "")

    if not s1 or not s2:
        print(f"  [WARN] Missing sections in {persona_path.name}")
        return False

    slim_content = f"ROLE & EMPATHY:\n{s1}\n\nCLINICAL SCOPE & FOCUS:\n{s2}\n"
    word_count = len(slim_content.split())
    if word_count < 40 or word_count >= 600:
        raise ValueError(f"Slim persona word count {word_count} out of bounds for {agent_dir.name}")

    slim_path.write_text(slim_content, encoding="utf-8")

    if append_protocol_to_skill and s3 and skill_dir and skill_dir.is_dir():
        skill_file = skill_dir / "SKILL.md"
        if skill_file.is_file():
            skill_text = skill_file.read_text(encoding="utf-8")
            if "## Structured Interaction Protocol" not in skill_text:
                protocol_block = f"\n\n## Structured Interaction Protocol\n{s3}\n"
                new_skill_text = skill_text.rstrip() + protocol_block
                skill_file.write_text(new_skill_text, encoding="utf-8")

    persona_path.rename(migrated_path)
    return True


def split_agent_manifest(
    agent_dir: Path,
    is_system: bool = False,
    override_icon: Optional[str] = None,
    can_delegate: Optional[bool] = None,
    max_iterations: Optional[int] = None,
) -> None:
    """Splits agent.yaml into slim runtime agent.yaml and companion metadata.yaml."""
    yaml_file = agent_dir / "agent.yaml"
    raw: Dict[str, Any] = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}

    agent_id = raw.get("id") or raw.get("name") or agent_dir.name
    title = raw.get("title") or agent_id.replace("-", " ").title()
    version = raw.get("version", "0.1.0")
    license_val = raw.get("license", "Apache-2.0")

    care_stages = raw.get("care_stages")
    if care_stages is None:
        care_stages = ["pre_visit"] if not is_system else []

    target_audience = raw.get("target_audience")
    if target_audience is None:
        target_audience = ["patient_adult", "caregiver"] if not is_system else []

    tags = raw.get("tags")
    if tags is None:
        tags = [agent_id]

    icon = override_icon or raw.get("icon", "Shield")
    maturity = raw.get("maturity", "stable")
    hidden = raw.get("hidden", True if is_system or agent_id.startswith("_") else False)

    domain = raw.get("domain")
    category = raw.get("category")

    meta_dict: Dict[str, Any] = {
        "id": agent_id,
        "title": title,
        "version": version,
        "license": license_val,
        "care_stages": care_stages,
        "target_audience": target_audience,
        "tags": tags,
        "icon": icon,
        "maturity": maturity,
        "hidden": hidden,
    }
    if domain:
        meta_dict["domain"] = domain
    if category:
        meta_dict["category"] = category

    meta_str = yaml.dump(meta_dict, Dumper=CarefoldYamlDumper, sort_keys=False, allow_unicode=True)
    (agent_dir / "metadata.yaml").write_text(APACHE_HEADER + "\n" + meta_str, encoding="utf-8")

    # Slim runtime agent.yaml
    raw_model = raw.get("model", "llama3.2")
    if isinstance(raw_model, str) and ":" not in raw_model:
        model = f"ollama:{raw_model}"
    else:
        model = raw_model

    skills = raw.get("skills", [])
    tools = raw.get("tools", [])
    desc = raw.get("description", "")
    persona_ref = "persona_slim.md" if (agent_dir / "persona_slim.md").exists() else raw.get("persona", "persona.md")

    runtime_dict: Dict[str, Any] = {
        "name": agent_id,
        "description": desc,
        "model": model,
        "skills": skills,
        "tools": tools,
        "persona": persona_ref,
    }

    delegate_val = can_delegate if can_delegate is not None else raw.get("can_delegate", False)
    if delegate_val:
        runtime_dict["can_delegate"] = True

    iter_val = max_iterations if max_iterations is not None else raw.get("max_iterations")
    if iter_val is not None:
        runtime_dict["max_iterations"] = iter_val

    runtime_str = yaml.dump(runtime_dict, Dumper=CarefoldYamlDumper, sort_keys=False, allow_unicode=True)
    yaml_file.write_text(APACHE_HEADER + "\n" + runtime_str, encoding="utf-8")


def main() -> int:
    """Executes the full migration across all 21 specialist and 6 system agents."""
    print("Beginning M2 persona slimming and manifest splitting...")

    # 1. Migrate 21 specialist & template agents
    for agent_id, skill_id in SPECIALISTS_MAP.items():
        agent_dir = AGENTS_DIR / agent_id
        skill_dir = SKILLS_DIR / skill_id
        print(f"Migrating specialist: {agent_id} (primary skill: {skill_id})")

        ok = decompose_persona(agent_dir, skill_dir, append_protocol_to_skill=True)
        if not ok:
            print(f"  [ERROR] Failed to decompose persona for {agent_id}")
            return 1

        split_agent_manifest(agent_dir, is_system=False)
        print(f"  ✓ {agent_id} decomposed and split successfully.")

    # 2. Migrate 6 system agents
    for agent_id, cfg in SYSTEM_AGENTS_MAP.items():
        agent_dir = AGENTS_DIR / "_system" / agent_id
        print(f"Migrating system agent: _system/{agent_id}")

        if agent_id in ("quality-reviewer", "triage-auditor"):
            skill_dir = SKILLS_DIR / cfg["primary_skill"]
            decompose_persona(agent_dir, skill_dir, append_protocol_to_skill=False)

        split_agent_manifest(
            agent_dir,
            is_system=True,
            override_icon=cfg.get("icon"),
            can_delegate=cfg.get("can_delegate"),
            max_iterations=cfg.get("max_iterations"),
        )
        print(f"  ✓ _system/{agent_id} split successfully.")

    print("\nAll 27 agents successfully processed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
