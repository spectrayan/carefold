# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Dynamic Handlebars template engine for prompts and system messages powered by pydantic-handlebars.

Integrates pydantic-handlebars with custom helpers, caching, and resolution
for data-driven agent system prompts and catalog templates.
"""

from __future__ import annotations

import logging
from pathlib import Path
import threading
from typing import Any, Callable, Dict, Optional, Union

from pydantic import BaseModel
from pydantic_handlebars import HandlebarsEnvironment

from carefold.templates.helpers import BUILTIN_HELPERS

logger = logging.getLogger(__name__)


class TemplateEngine:
    """Handlebars template compiler and cache wrapping pydantic-handlebars."""

    def __init__(self, templates_dir: Optional[Union[Path, str]] = None) -> None:
        if templates_dir:
            self.templates_dir = Path(templates_dir).resolve()
        else:
            self.templates_dir = (
                Path(__file__).parent.parent / "resources" / "prompts" / "templates"
            ).resolve()

        # Initialize pydantic-handlebars environment with extra helpers and HTML auto-escaping disabled
        self._env = HandlebarsEnvironment(extra_helpers=True, auto_escape=False)
        self._compiled_cache: Dict[str, Any] = {}
        self._lock = threading.RLock()

        # Register Carefold built-in helpers
        for name, fn in BUILTIN_HELPERS.items():
            self._env.register_helper(name, fn)

    def register_helper(self, name: str, helper_fn: Callable) -> None:
        """Registers a custom Handlebars helper function."""
        with self._lock:
            self._env.register_helper(name, helper_fn)

    def resolve_template_source(
        self,
        template_name_or_source: str,
        custom_dir: Optional[Union[Path, str]] = None,
    ) -> str:
        """Resolves template source string from file or returns raw string if contains Handlebars tags."""
        if "{{" in template_name_or_source and "}}" in template_name_or_source:
            return template_name_or_source

        candidate_dirs = []
        if custom_dir:
            candidate_dirs.append(Path(custom_dir).resolve())
        candidate_dirs.append(self.templates_dir)

        filename = template_name_or_source
        if not filename.endswith((".hbs", ".handlebars")):
            filename = f"{filename}.hbs"

        for d in candidate_dirs:
            p = d / filename
            if p.is_file():
                return p.read_text(encoding="utf-8")

        for d in candidate_dirs:
            p = d / template_name_or_source
            if p.is_file():
                return p.read_text(encoding="utf-8")

        raise FileNotFoundError(
            f"Handlebars template '{template_name_or_source}' not found in candidate directories: {candidate_dirs}"
        )

    def compile(
        self,
        template_name_or_source: str,
        custom_dir: Optional[Union[Path, str]] = None,
    ) -> Any:
        """Compiles a Handlebars template and caches the compiled template object."""
        cache_key = f"{custom_dir}::{template_name_or_source}"
        if cache_key in self._compiled_cache:
            return self._compiled_cache[cache_key]

        with self._lock:
            if cache_key in self._compiled_cache:
                return self._compiled_cache[cache_key]

            source = self.resolve_template_source(template_name_or_source, custom_dir)
            compiled = self._env.compile(source)
            self._compiled_cache[cache_key] = compiled
            return compiled

    def render(
        self,
        template_name_or_source: str,
        context: Union[Dict[str, Any], BaseModel],
        custom_dir: Optional[Union[Path, str]] = None,
    ) -> str:
        """Compiles (if needed) and renders a Handlebars template with the given context."""
        compiled = self.compile(template_name_or_source, custom_dir)
        try:
            rendered = compiled.render(context)
            return str(rendered).strip()
        except Exception as err:
            logger.warning(
                "Error rendering Handlebars template '%s': %s; falling back to basic regex rendering",
                template_name_or_source,
                err,
            )
            return self._fallback_render(self.resolve_template_source(template_name_or_source, custom_dir), context)

    def _fallback_render(self, source: str, context: Union[Dict[str, Any], BaseModel]) -> str:
        """Lightweight regex-based fallback for simple {{variable}} and {{{variable}}} interpolation."""
        import re

        data: Dict[str, Any] = context.model_dump() if isinstance(context, BaseModel) else dict(context)

        def _resolve_var(var_path: str, d: Dict[str, Any]) -> str:
            parts = var_path.strip().split(".")
            curr = d
            for part in parts:
                if isinstance(curr, dict):
                    curr = curr.get(part, "")
                elif hasattr(curr, part):
                    curr = getattr(curr, part, "")
                else:
                    return ""
            return str(curr or "")

        res = source
        res = re.sub(r"\{\{\{([\w\.]+)\}\}\}", lambda m: _resolve_var(m.group(1), data), res)
        res = re.sub(r"\{\{([\w\.]+)\}\}", lambda m: _resolve_var(m.group(1), data), res)
        res = re.sub(r"\{\{#[^}]+\}\}.*?\{\{/[^}]+\}\}", "", res, flags=re.DOTALL)
        return res.strip()


_DEFAULT_ENGINE: Optional[TemplateEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_template_engine(templates_dir: Optional[Union[Path, str]] = None) -> TemplateEngine:
    """Returns singleton TemplateEngine instance."""
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None or templates_dir is not None:
        with _ENGINE_LOCK:
            if _DEFAULT_ENGINE is None or templates_dir is not None:
                engine = TemplateEngine(templates_dir)
                if templates_dir is None:
                    _DEFAULT_ENGINE = engine
                return engine
    return _DEFAULT_ENGINE


def render_template(
    template_name_or_source: str,
    context: Union[Dict[str, Any], BaseModel],
    custom_dir: Optional[Union[Path, str]] = None,
) -> str:
    """Convenience functional wrapper to render a template."""
    return get_template_engine().render(template_name_or_source, context, custom_dir)


__all__ = [
    "TemplateEngine",
    "get_template_engine",
    "render_template",
]
