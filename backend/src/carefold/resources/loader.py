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

"""Cached ResourceLoader for external YAML resources in carefold.resources.

Loads and caches:
- disclaimers.yaml: Intended use notices and refusal disclaimers.
- refusal_patterns.yaml: Clinical safety regex patterns and keyword dictionaries.
- prompts.yaml: Supervisor, agent, extraction, and safety prompts.
- errors.yaml: Standardized error messages and status codes.
"""

from __future__ import annotations

import collections
import logging
from pathlib import Path
import re
import threading
from typing import Any, Dict, List, NamedTuple, Optional, Tuple
import yaml

logger = logging.getLogger(__name__)


class RefusalPattern(NamedTuple):
    """Named tuple matching carefold.safety.classifier contract."""
    category: str
    regex: re.Pattern
    description: str


class ResourceLoader:
    """Thread-safe, cached singleton loader for Carefold YAML resources."""

    def __init__(self, resources_dir: Optional[Path] = None) -> None:
        self.resources_dir = (resources_dir or Path(__file__).parent).resolve()
        self._lock = threading.RLock()
        self._cache: Dict[str, Any] = {}
        self._compiled_refusal_patterns: Optional[List[RefusalPattern]] = None
        self._compiled_disclaimer_clauses: Optional[List[re.Pattern]] = None

    def load_yaml(self, filename: str) -> Dict[str, Any]:
        """Loads and caches a YAML file from resources directory.

        Raises:
            PermissionError: If filename attempts path traversal outside resources_dir.
            FileNotFoundError: If the file does not exist.
        """
        file_path = (self.resources_dir / filename).resolve()
        if not file_path.is_relative_to(self.resources_dir):
            raise PermissionError(
                f"Access denied: path '{filename}' is outside resources directory '{self.resources_dir}'"
            )

        if filename not in self._cache:
            with self._lock:
                if filename not in self._cache:
                    if not file_path.is_file():
                        raise FileNotFoundError(f"Resource file not found: {file_path}")
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    self._cache[filename] = data
        return self._cache[filename]

    def _load_yaml(self, filename: str) -> Dict[str, Any]:
        """Internal alias for load_yaml."""
        return self.load_yaml(filename)

    def clear_cache(self) -> None:
        """Clears all cached resources and compiled regex patterns."""
        with self._lock:
            self._cache.clear()
            self._compiled_refusal_patterns = None
            self._compiled_disclaimer_clauses = None

    # =========================================================================
    # 1. Primary Contract Methods
    # =========================================================================

    def get_disclaimers(self) -> Dict[str, Any]:
        """Loads and returns disclaimers from disclaimers.yaml."""
        return self.load_yaml("disclaimers.yaml")

    def get_refusal_patterns(self) -> Dict[str, Any]:
        """Loads and returns raw refusal pattern dictionary from refusal_patterns.yaml."""
        return self.load_yaml("refusal_patterns.yaml")

    def get_prompts(self) -> Dict[str, Any]:
        """Loads and returns prompt templates composed from individual prompt files under resources/prompts/.

        Falls back cleanly to prompts.yaml if individual prompt files are missing.
        """
        if "composed_prompts" in self._cache:
            return self._cache["composed_prompts"]

        try:
            base_prompts = dict(self.load_yaml("prompts.yaml"))
        except FileNotFoundError:
            base_prompts = {}

        prompts_dir = self.resources_dir / "prompts"
        if not prompts_dir.is_dir():
            return base_prompts

        composed = dict(base_prompts)

        # 1. Safety preamble
        preamble_file = prompts_dir / "safety" / "safety_preamble.md"
        if preamble_file.is_file():
            text = preamble_file.read_text(encoding="utf-8").strip()
            composed["safety_preamble"] = text
            composed.setdefault("safety", {})["system_preamble"] = text

        # 2. Orchestrator / Supervisor
        orch_file = prompts_dir / "orchestrator" / "system_prompt.md"
        if orch_file.is_file():
            text = orch_file.read_text(encoding="utf-8").strip()
            composed.setdefault("supervisor", {})["system_prompt"] = text
            composed.setdefault("orchestrator", {})["system_prompt"] = text

        # 3. Extraction
        ext_dir = prompts_dir / "extraction"
        if ext_dir.is_dir():
            ext_map = composed.setdefault("extraction", {})
            for f in ext_dir.iterdir():
                if f.suffix in (".md", ".txt"):
                    ext_map[f.stem] = f.read_text(encoding="utf-8").strip()

        # 4. Reflection
        refl_file = prompts_dir / "reflection" / "system_prompt.md"
        if refl_file.is_file():
            text = refl_file.read_text(encoding="utf-8").strip()
            composed.setdefault("reflection", {})["system_prompt"] = text

        # 5. Canonical Agents (resolved from agents/*/agent.yaml manifests via AgentRegistry)
        agents_map = composed.setdefault("agents", {})
        try:
            from carefold.agents.registry import get_agent_registry
            registry = get_agent_registry()
            for agent in registry.list_agents():
                persona_text = ""
                if isinstance(agent.persona, str):
                    persona_text = agent.persona.strip()
                elif hasattr(agent.persona, "instructions") and agent.persona.instructions:
                    persona_text = agent.persona.instructions.strip()
                elif isinstance(agent.persona, dict):
                    persona_text = str(agent.persona.get("instructions") or agent.persona.get("role") or "").strip()
                agents_map[agent.id.replace("-", "_")] = persona_text
        except Exception as err:
            logger.debug("Could not resolve dynamic agents for prompt composition: %s", err)

        # 6. System scaffold
        system_dir = prompts_dir / "system"
        if system_dir.is_dir():
            system_map = composed.setdefault("system", {})
            scaffold_file = system_dir / "scaffold.yaml"
            if scaffold_file.is_file():
                scaffold = yaml.safe_load(scaffold_file.read_text(encoding="utf-8")) or {}
                system_map.update(scaffold)
            for f in system_dir.iterdir():
                if f.suffix in (".md", ".txt"):
                    system_map[f.stem] = f.read_text(encoding="utf-8").strip()

        # 7. Suggestions
        sugg_file = prompts_dir / "suggestions" / "suggestions.yaml"
        if sugg_file.is_file():
            sugg = yaml.safe_load(sugg_file.read_text(encoding="utf-8")) or {}
            composed["suggestions"] = sugg

        gen_file = prompts_dir / "suggestions" / "generation.md"
        if gen_file.is_file():
            composed.setdefault("suggestions", {})["generation_prompt"] = gen_file.read_text(encoding="utf-8").strip()


        with self._lock:
            self._cache["composed_prompts"] = composed
        return composed

    def get_prompt_text(self, relative_path: str) -> str:
        """Loads raw prompt text from individual file under resources/prompts/."""
        prompts_dir = self.resources_dir / "prompts"
        candidates = [
            prompts_dir / relative_path,
            prompts_dir / f"{relative_path}.md",
            prompts_dir / f"{relative_path}.txt",
            prompts_dir / f"{relative_path}.yaml",
            prompts_dir / f"{relative_path}.yml",
        ]
        for p in candidates:
            if p.is_file():
                return p.read_text(encoding="utf-8").strip()
        raise FileNotFoundError(f"Prompt file not found for: {relative_path} (looked in {prompts_dir})")

    def render_prompt(self, relative_path: str, **kwargs: Any) -> str:
        """Loads and renders a parameterized prompt with keyword argument substitution.

        Validates that all expected placeholders are provided, raising ValueError on missing keys.
        """
        template = self.get_prompt_text(relative_path)
        try:
            return template.format(**kwargs)
        except KeyError as err:
            raise ValueError(
                f"Missing required parameter {err} for prompt '{relative_path}'. "
                f"Provided parameters: {list(kwargs.keys())}"
            ) from err

    def get_errors(self) -> Dict[str, Any]:
        """Loads and returns error dictionary from errors.yaml."""
        return self.load_yaml("errors.yaml")

    def get_routing_patterns(self) -> Dict[str, Any]:
        """Loads and returns offline routing pattern dictionary from routing_patterns.yaml."""
        return self.load_yaml("routing_patterns.yaml")



    # =========================================================================
    # 2. Disclaimer Convenience Accessors
    # =========================================================================

    def get_safe_refusal_template(self) -> str:
        """Returns the canonical Safe Refusal Template."""
        return str(self.get_disclaimers().get("safe_refusal_template", ""))

    def get_disclaimer_header_text(self) -> str:
        """Returns the persistent UI header disclaimer text."""
        return str(self.get_disclaimers().get("disclaimer_header_text", ""))

    def get_mandatory_intended_use_lines(self) -> Tuple[str, ...]:
        """Returns the 3 mandatory intended-use statements."""
        lines = self.get_disclaimers().get("mandatory_intended_use_lines", [])
        return tuple(str(x) for x in lines)

    # =========================================================================
    # 3. Refusal Patterns & Regex Resolution
    # =========================================================================

    def _resolve_building_blocks(self) -> Dict[str, str]:
        """Resolves building blocks by substituting <TAG> references in topological order."""
        raw = self.get_refusal_patterns()
        blocks = dict(raw.get("building_blocks", {}))

        # Handle list-to-pipe-joined string for common conditions
        cond_list = blocks.get("common_conditions_list", [])
        if isinstance(cond_list, list):
            common_conditions = "|".join(cond_list)
        else:
            common_conditions = str(cond_list)

        resolved: Dict[str, str] = {
            "COMMON_CONDITIONS": common_conditions,
        }

        # Resolution dependency order
        keys_order = [
            "single_num",
            "fraction_or_num",
            "numeric_quantity",
            "provider_role",
            "disclaimer_med_target",
            "all_cessation_drugs",
            "all_kinships",
            "kinship_modifier",
            "caregiver_recipient",
            "dosing_recipient",
            "family_possessive_determiners",
            "diagnostic_subjects",
            "confirm_subjects",
            "subject_qualifier",
            "dosing_units",
            "condition_tail",
        ]

        for k in keys_order:
            val = blocks.get(k, "")
            if not isinstance(val, str):
                continue
            for tag_name, tag_val in resolved.items():
                val = val.replace(f"<{tag_name}>", tag_val)
            resolved[k.upper()] = val

        return resolved

    def get_compiled_disclaimer_clauses(self) -> List[re.Pattern]:
        """Compiles and returns the 15 disclaimer neutralization regexes."""
        if self._compiled_disclaimer_clauses is not None:
            return self._compiled_disclaimer_clauses

        with self._lock:
            if self._compiled_disclaimer_clauses is not None:
                return self._compiled_disclaimer_clauses

            blocks = self._resolve_building_blocks()
            raw = self.get_refusal_patterns()
            clauses_raw = raw.get("disclaimer_clauses", [])

            compiled: List[re.Pattern] = []
            for item in clauses_raw:
                pattern_str = item.get("pattern", "") if isinstance(item, dict) else str(item)
                for tag_name, tag_val in blocks.items():
                    pattern_str = pattern_str.replace(f"<{tag_name}>", tag_val)
                compiled.append(re.compile(pattern_str, re.IGNORECASE))

            self._compiled_disclaimer_clauses = compiled
            return self._compiled_disclaimer_clauses

    def get_compiled_refusal_patterns(self) -> List[RefusalPattern]:
        """Compiles and returns the 34 RefusalPattern tuples."""
        if self._compiled_refusal_patterns is not None:
            return self._compiled_refusal_patterns

        with self._lock:
            if self._compiled_refusal_patterns is not None:
                return self._compiled_refusal_patterns

            blocks = self._resolve_building_blocks()
            raw = self.get_refusal_patterns()
            patterns_raw = raw.get("refusal_patterns", [])

            compiled: List[RefusalPattern] = []
            for item in patterns_raw:
                category = item.get("category", "")
                description = item.get("description", "")
                pattern_str = item.get("pattern", "")
                for tag_name, tag_val in blocks.items():
                    pattern_str = pattern_str.replace(f"<{tag_name}>", tag_val)
                compiled.append(
                    RefusalPattern(
                        category=category,
                        regex=re.compile(pattern_str, re.IGNORECASE),
                        description=description,
                    )
                )

            self._compiled_refusal_patterns = compiled
            return self._compiled_refusal_patterns

    # =========================================================================
    # 4. Prompts & Suggestions Convenience Accessors
    # =========================================================================

    def get_safety_preamble_template(self) -> str:
        """Returns the unrendered safety preamble template string."""
        prompts = self.get_prompts()
        if "safety_preamble" in prompts:
            return str(prompts["safety_preamble"])
        return str(prompts.get("safety", {}).get("system_preamble", ""))

    def get_follow_up_suggestions(
        self,
        agent_id: str,
        prompt: str = "",
        completion: str = "",
        tools_used: Optional[List[str]] = None,
        user_queries: Optional[Sequence[str]] = None,
    ) -> List[str]:
        """Generates 2-4 contextual follow-up chips based on agent persona, topic keywords, tools, and conversation history."""
        tools_used = tools_used or []
        aid = (agent_id or "").lower().strip()
        search_text = f"{(prompt or '').lower()} {(completion or '').lower()}".strip()

        s_data = self.get_prompts().get("suggestions", {})
        tool_s = s_data.get("tool_suggestions", {})
        persona_s = s_data.get("persona_suggestions", {})

        # 0. Check if the agent manifest defines inline suggestions
        manifest_suggestions: Optional[Dict[str, Any]] = None
        try:
            from carefold.agents.registry import get_agent_registry
            registry = get_agent_registry()
            agent_obj = registry.get(aid) or registry.get(aid.replace("-", "_"))
            if agent_obj and getattr(agent_obj, "suggestions", None):
                manifest_suggestions = agent_obj.suggestions
        except Exception as e:
            logger.debug("Could not inspect agent registry for inline suggestions: %s", e)

        # 1. Resolve agent persona definition
        aid_key = aid.replace("-", "_")
        persona_def: Dict[str, Any] = {}
        if manifest_suggestions and isinstance(manifest_suggestions, dict):
            if aid_key in manifest_suggestions:
                persona_def = dict(manifest_suggestions[aid_key])
            elif "persona_suggestions" in manifest_suggestions and aid_key in manifest_suggestions["persona_suggestions"]:
                persona_def = dict(manifest_suggestions["persona_suggestions"][aid_key])
            else:
                persona_def = dict(manifest_suggestions)
        elif aid_key in persona_s:
            persona_def = persona_s[aid_key]
        else:
            # Check safe prefix/substring matching (prevent single-word false matches like "guide")
            for k, pdef in persona_s.items():
                if k == aid_key or (len(k) > 4 and k.split("_")[0] in aid_key):
                    persona_def = pdef
                    aid_key = k
                    break

        matched_category_chips: List[str] = []
        other_persona_chips: List[str] = []
        tool_matched_chips: List[str] = []
        default_persona_chips: List[str] = []

        # 2. Dynamic Topic/Keyword Matching for Resolved Persona
        if persona_def:
            matched_keys = []
            for k, val in persona_def.items():
                if k.endswith("_keywords") and isinstance(val, list):
                    prefix = k[:-len("_keywords")]
                    target_chips_key = f"{prefix}_chips"
                    hit_count = sum(1 for w in val if isinstance(w, str) and w.lower() in search_text)
                    if hit_count > 0 and target_chips_key in persona_def:
                        matched_keys.append((hit_count, target_chips_key))
                    elif target_chips_key in persona_def:
                        for c in persona_def[target_chips_key]:
                            if c not in other_persona_chips:
                                other_persona_chips.append(c)

            matched_keys.sort(key=lambda x: x[0], reverse=True)
            for _, t_key in matched_keys:
                for c in persona_def.get(t_key, []):
                    if c not in matched_category_chips:
                        matched_category_chips.append(c)

            # 3. Contextual Tool Matching
            if tools_used:
                persona_tools = persona_def.get("tools") or persona_def.get("tool_suggestions") or {}
                for t in tools_used:
                    t_clean = t.replace("-", "_")
                    if t in persona_tools and persona_tools[t]:
                        tool_matched_chips.extend(persona_tools[t])
                    elif f"{t_clean}_chips" in persona_def and persona_def[f"{t_clean}_chips"]:
                        tool_matched_chips.extend(persona_def[f"{t_clean}_chips"])

                if not tool_matched_chips:
                    for t in tools_used:
                        if t in ("workspace-note", "attach-read") and t in tool_s and tool_s[t]:
                            tool_matched_chips.extend(tool_s[t])

            for c in persona_def.get("default_chips", []):
                if c not in default_persona_chips:
                    default_persona_chips.append(c)

        # Assemble candidate pool in priority order
        pool: List[str] = []
        for c in matched_category_chips:
            if c not in pool:
                pool.append(c)
        for c in tool_matched_chips:
            if c not in pool:
                pool.append(c)
        for c in default_persona_chips:
            if c not in pool:
                pool.append(c)
        for c in other_persona_chips:
            if c not in pool:
                pool.append(c)

        if not pool and tools_used:
            for t in tools_used:
                if t in tool_s and tool_s[t]:
                    for c in tool_s[t]:
                        if c not in pool:
                            pool.append(c)

        if not pool:
            pool = list(s_data.get("default_chips", [])) or [
                "Can you explain this in simpler terms?",
                "What questions should I ask my healthcare provider?",
                "Help me save a note summarizing these points.",
            ]

        # 4. Turn-awareness and deduplication against prior queries
        prior_queries = list(user_queries or [])
        if prompt and prompt not in prior_queries:
            prior_queries.append(prompt)

        def _was_asked(chip: str) -> bool:
            c_low = chip.strip().lower()
            for q in prior_queries:
                q_low = q.strip().lower()
                if not q_low:
                    continue
                if c_low == q_low or c_low in q_low or q_low in c_low:
                    return True
                c_words = set(re.findall(r"\w+", c_low)) - {"what", "how", "can", "you", "i", "my", "the", "a", "an", "is", "about", "to", "for", "in", "do", "me", "this"}
                q_words = set(re.findall(r"\w+", q_low)) - {"what", "how", "can", "you", "i", "my", "the", "a", "an", "is", "about", "to", "for", "in", "do", "me", "this"}
                if c_words and len(c_words & q_words) >= max(2, len(c_words) - 1):
                    return True
            return False

        filtered_pool = [c for c in pool if not _was_asked(c)]
        if len(filtered_pool) >= 2:
            active_pool = filtered_pool
        else:
            active_pool = pool

        # 5. Dynamic turn-based rotation so subsequent conversation turns vary suggestions
        turn_count = len(user_queries) if user_queries else 1
        if turn_count > 1 and len(active_pool) > 4:
            offset = (turn_count - 1) % len(active_pool)
            active_pool = active_pool[offset:] + active_pool[:offset]

        # 6. Deduplicate while preserving order and limit to 3 chips (F-30: 2-3 chips)
        result: List[str] = []
        for c in active_pool:
            if c not in result:
                result.append(c)
            if len(result) >= 3:
                break

        return result

    # =========================================================================
    # 5. Error Convenience Accessors
    # =========================================================================

    def format_error(self, error_key: str, **kwargs: Any) -> str:
        """Formats error message template for given error key safely."""
        err_def = self.get_errors().get("errors", {}).get(error_key, {})
        msg_template = str(err_def.get("message", error_key))
        try:
            safe_kwargs = collections.defaultdict(str, kwargs)
            return msg_template.format_map(safe_kwargs)
        except Exception:
            return msg_template

    def get_error_status_code(self, error_key: str) -> int:
        """Returns the HTTP status code for given error key."""
        err_def = self.get_errors().get("errors", {}).get(error_key, {})
        return int(err_def.get("status_code", 500))


_LOADER_LOCK = threading.Lock()
_LOADER_INSTANCE: Optional[ResourceLoader] = None


def get_resource_loader() -> ResourceLoader:
    """Returns the cached singleton ResourceLoader instance.

    Thread-safe implementation using double-checked locking with a
    threading.Lock to guarantee singleton identity under concurrent cold-start.
    """
    global _LOADER_INSTANCE
    if _LOADER_INSTANCE is None:
        with _LOADER_LOCK:
            if _LOADER_INSTANCE is None:
                _LOADER_INSTANCE = ResourceLoader()
    return _LOADER_INSTANCE
