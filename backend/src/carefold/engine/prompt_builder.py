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

"""Agent system prompt assembler powered by Handlebars templates."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
from carefold.safety.prompt import build_safety_preamble
from carefold.schemas.manifest import AgentManifest, SkillManifest
from carefold.templates.engine import render_template


def build_system_prompt(
    agent: AgentManifest,
    skills: Sequence[SkillManifest] = (),
    effective_tools: Sequence[str] = (),
    template_name: Optional[str] = None,
    progressive: bool = False,
) -> str:
    """Builds the comprehensive system prompt using dynamic Handlebars templates.

    When progressive=True, skills are formatted as Tier 1 catalog summaries rather
    than inlining full instruction bodies, reducing baseline system prompt tokens.
    """
    safety_preamble = build_safety_preamble(agent, skills)

    # Persona text resolution
    if isinstance(agent.persona, str):
        persona_text = agent.persona.strip()
    elif isinstance(agent.persona, dict):
        role = agent.persona.get("role")
        tone = agent.persona.get("tone")
        instructions = agent.persona.get("instructions")
        lines = []
        if role:
            lines.append(f"Role: {role}")
        if tone:
            lines.append(f"Tone: {tone}")
        if instructions:
            lines.append(f"Instructions: {instructions}")
        persona_text = "\n".join(lines)
    else:
        role = getattr(agent.persona, "role", None)
        tone = getattr(agent.persona, "tone", None)
        instructions = getattr(agent.persona, "instructions", None)
        lines = []
        if role:
            lines.append(f"Role: {role}")
        if tone:
            lines.append(f"Tone: {tone}")
        if instructions:
            lines.append(f"Instructions: {instructions}")
        persona_text = "\n".join(lines)

    # Tools summary
    if effective_tools:
        tools_summary = f"Available Tools (Sandboxed): {', '.join(effective_tools)}"
    else:
        tools_summary = "Available Tools: None (Conversational Only)"

    # Skills data
    if progressive:
        skill_items = [
            {
                "id": s.id,
                "name": s.name,
                "instructions": (
                    f"Summary: {s.description.strip()}"
                    if s.description
                    else "(Instructions available on-demand via skill-docs)"
                ),
            }
            for s in skills
            if s.name
        ]
    else:
        skill_items = [
            {
                "id": s.id,
                "name": s.name,
                "instructions": s.instructions.strip() if s.instructions else "",
            }
            for s in skills
            if s.instructions and s.instructions.strip()
        ]

    context: Dict[str, Any] = {
        "agent": {
            "id": agent.id,
            "title": agent.title,
            "version": agent.version,
            "domain": agent.domain.value if hasattr(agent.domain, "value") else str(agent.domain),
            "category": agent.category,
        },
        "risk_class": agent.risk_class.value if hasattr(agent.risk_class, "value") else str(agent.risk_class),
        "persona_text": persona_text,
        "tools_summary": tools_summary,
        "skills": skill_items,
        "has_skills": bool(skill_items),
        "safety_preamble": safety_preamble,
    }

    resolved_template = template_name or getattr(agent, "prompt_template", None) or "system_prompt"
    return render_template(resolved_template, context)


__all__ = ["build_system_prompt"]
