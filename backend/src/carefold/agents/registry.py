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

"""Runtime declarative AgentRegistry wrapping load_agent infrastructure (Milestone 6)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from carefold.config import settings
from carefold.constants.agents import AGENT_ORCHESTRATOR
from carefold.constants.paths import SYSTEM_AGENTS_DIR
from carefold.loaders.agent_loader import load_agent
from carefold.schemas.manifest import AgentManifest, AgentPersonaObject, SkillManifest

logger = logging.getLogger(__name__)


def _extract_first_line(persona: Union[str, AgentPersonaObject, Dict[str, Any], None]) -> str:
    """Extracts the first non-empty, non-header line from an agent persona."""
    if not persona:
        return ""
    if isinstance(persona, str):
        for line in persona.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
        return ""
    if isinstance(persona, AgentPersonaObject):
        if persona.role:
            return persona.role.strip()
        if persona.instructions:
            for line in persona.instructions.strip().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
        return ""
    if isinstance(persona, dict):
        if persona.get("role"):
            return str(persona["role"]).strip()
        if persona.get("instructions"):
            for line in str(persona["instructions"]).strip().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    return ""


class AgentRegistry:
    """Runtime registry wrapping load_agent() with dynamic catalog formatting.

    Discovers agent manifests from filesystem, resolves declared skills and
    effective tools, and provides dynamic catalog formatting for the orchestrator.
    """

    def __init__(
        self,
        agents_dir: Union[Path, str],
        skills_dir: Optional[Union[Path, str]] = None,
    ) -> None:
        self._agents_dir = Path(agents_dir).resolve()
        self._skills_dir = Path(skills_dir).resolve() if skills_dir else None
        self._agents: Dict[str, AgentManifest] = {}
        self._effective_tools: Dict[str, List[str]] = {}
        self._loaded_skills: Dict[str, List[SkillManifest]] = {}
        self.reload()

    def reload(self) -> None:
        """Discovers agents using existing load_agent() infrastructure."""
        self._agents.clear()
        self._effective_tools.clear()
        self._loaded_skills.clear()

        if not self._agents_dir.is_dir():
            logger.warning("Agents directory does not exist: %s", self._agents_dir)
            return

        candidate_dirs: List[Path] = []
        if self._agents_dir.name == SYSTEM_AGENTS_DIR:
            for entry in sorted(self._agents_dir.iterdir()):
                if entry.is_dir() and not entry.name.startswith((".", "_")):
                    candidate_dirs.append(entry)
        else:
            for entry in sorted(self._agents_dir.iterdir()):
                if not entry.is_dir():
                    continue
                if entry.name == SYSTEM_AGENTS_DIR:
                    for subentry in sorted(entry.iterdir()):
                        if subentry.is_dir() and not subentry.name.startswith((".", "_")):
                            candidate_dirs.append(subentry)
                elif not entry.name.startswith((".", "_")):
                    candidate_dirs.append(entry)

        for entry in candidate_dirs:
            try:
                manifest, effective_tools, loaded_skills = load_agent(entry, self._skills_dir)
                if entry.parent.name == SYSTEM_AGENTS_DIR:
                    manifest.hidden = True
                self._agents[manifest.id] = manifest
                self._effective_tools[manifest.id] = effective_tools
                self._loaded_skills[manifest.id] = loaded_skills
            except Exception as err:
                logger.warning("Failed to load agent %s: %s", entry.name, err)

    def get(self, agent_id: str) -> Optional[AgentManifest]:
        """Returns AgentManifest for agent_id if found, otherwise None."""
        if not agent_id or agent_id.startswith((".", "_")):
            return None

        if agent_id in self._agents:
            return self._agents[agent_id]

        candidates = [
            self._agents_dir / agent_id,
            self._agents_dir / SYSTEM_AGENTS_DIR / agent_id,
        ]
        current_settings_agents = settings.get_agents_dir().resolve()
        if current_settings_agents != self._agents_dir:
            candidates.append(current_settings_agents / agent_id)
            candidates.append(current_settings_agents / SYSTEM_AGENTS_DIR / agent_id)

        for candidate in candidates:
            if candidate.is_dir():
                try:
                    manifest, effective_tools, loaded_skills = load_agent(candidate, self._skills_dir)
                    if candidate.parent.name == SYSTEM_AGENTS_DIR:
                        manifest.hidden = True
                    self._agents[agent_id] = manifest
                    self._effective_tools[agent_id] = effective_tools
                    self._loaded_skills[agent_id] = loaded_skills
                    return manifest
                except Exception as err:
                    logger.debug("Failed on-demand load for agent '%s' from %s: %s", agent_id, candidate, err)
        return None

    def __getitem__(self, agent_id: str) -> AgentManifest:
        """Returns AgentManifest for agent_id or raises KeyError."""
        manifest = self.get(agent_id)
        if manifest is None:
            raise KeyError(f"Agent '{agent_id}' not found in registry.")
        return manifest

    def __contains__(self, agent_id: str) -> bool:
        """Returns True if agent_id is present in registry."""
        return self.get(agent_id) is not None

    def __len__(self) -> int:
        """Returns count of registered agents."""
        return len(self._agents)

    def has_agent(self, agent_id: str) -> bool:
        """Returns True if agent_id is present in registry."""
        return self.get(agent_id) is not None

    def list_agents(self) -> List[AgentManifest]:
        """Returns list of all registered AgentManifests sorted by ID."""
        return [self._agents[aid] for aid in sorted(self._agents.keys())]

    def list_agent_ids(self) -> List[str]:
        """Returns list of all registered agent IDs sorted."""
        return sorted(self._agents.keys())

    def get_effective_tools(self, agent_id: str) -> List[str]:
        """Returns effective tool allowlist for agent_id."""
        if agent_id not in self._effective_tools:
            self.get(agent_id)
        return list(self._effective_tools.get(agent_id, []))

    def get_loaded_skills(self, agent_id: str) -> List[SkillManifest]:
        """Returns loaded skills for agent_id."""
        if agent_id not in self._loaded_skills:
            self.get(agent_id)
        return list(self._loaded_skills.get(agent_id, []))

    def get_skill(self, skill_id: str) -> Optional[SkillManifest]:
        """Returns loaded SkillManifest by skill_id across agents or loads directly from skills_dir."""
        for skills in self._loaded_skills.values():
            for sk in skills:
                if sk.id == skill_id:
                    return sk
        if self._skills_dir and (self._skills_dir / skill_id).is_dir():
            from carefold.loaders.skill_loader import load_skill
            try:
                sk, _ = load_skill(self._skills_dir / skill_id)
                return sk
            except Exception:
                pass
        return None

    @property
    def effective_tools_map(self) -> Dict[str, List[str]]:
        """Returns a copy of the mapping of agent_id to effective tool names."""
        return dict(self._effective_tools)

    def get_delegatable_agents(self, exclude: str = "") -> List[AgentManifest]:
        """Returns non-orchestrator agents available for delegation.

        Filters out agents where can_delegate is True (such as orchestrator)
        and optionally filters out an agent by explicit ID.
        """
        return [
            a for a in sorted(self._agents.values(), key=lambda a: a.id)
            if a.id != exclude and not a.can_delegate
        ]

    def format_agent_catalog(self, exclude: str = AGENT_ORCHESTRATOR) -> str:
        """Formats agent catalog for the orchestrator's dynamic system prompt.

        Generates formatted markdown from live agent.yaml files.
        """
        agents = self.get_delegatable_agents(exclude)
        lines: List[str] = []
        for a in agents:
            desc = a.description or _extract_first_line(a.persona)
            tools_str = ", ".join(self._effective_tools.get(a.id, []))
            lines.append(
                f"- **{a.id}** ({a.title}): {desc}\n"
                f"  Tools: [{tools_str}]"
            )
        return "\n".join(lines)

    def get_subagent(self, agent_id: str, resolve_tools: bool = False) -> Optional[Dict[str, Any]]:
        """Returns native Deep Agents SubAgent dict for the specified agent."""
        if not agent_id or agent_id.startswith((".", "_")):
            return None
        candidate = self._agents_dir / agent_id
        if not candidate.is_dir():
            candidate = self._agents_dir / SYSTEM_AGENTS_DIR / agent_id
        if candidate.is_dir():
            from carefold.loaders.agent_loader import load_subagent_from_yaml

            return load_subagent_from_yaml(candidate, resolve_tools=resolve_tools)
        return None

    def list_subagents(self, resolve_tools: bool = False) -> List[Dict[str, Any]]:
        """Returns list of native Deep Agents SubAgent dicts for all non-system agents."""
        subagents: List[Dict[str, Any]] = []
        for aid in self.list_agent_ids():
            manifest = self._agents.get(aid)
            if manifest and getattr(manifest, "hidden", False):
                continue
            candidate = self._agents_dir / aid
            if not candidate.is_dir():
                continue
            sub = self.get_subagent(aid, resolve_tools=resolve_tools)
            if sub is not None:
                subagents.append(sub)
        return subagents



_registry_instance: Optional[AgentRegistry] = None


def get_agent_registry(
    agents_dir: Optional[Union[Path, str]] = None,
    skills_dir: Optional[Union[Path, str]] = None,
    force_reload: bool = False,
) -> AgentRegistry:
    """Returns singleton or newly initialized AgentRegistry."""
    global _registry_instance
    target_agents_dir = Path(agents_dir).resolve() if agents_dir else settings.get_agents_dir().resolve()
    target_skills_dir = Path(skills_dir).resolve() if skills_dir else settings.get_skills_dir().resolve()
    if (
        _registry_instance is None
        or force_reload
        or agents_dir is not None
        or (hasattr(_registry_instance, "_agents_dir") and _registry_instance._agents_dir != target_agents_dir)
    ):
        _registry_instance = AgentRegistry(target_agents_dir, target_skills_dir)
    return _registry_instance


__all__ = ["AgentRegistry", "_extract_first_line", "get_agent_registry"]
