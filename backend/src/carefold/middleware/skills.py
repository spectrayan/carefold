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

"""Carefold custom SkillsMiddleware with clinical safety boundary prompt template."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, Sequence, Union

logger = logging.getLogger(__name__)

CAREFOLD_SKILLS_PROMPT = """\
## Carefold Clinical Skill Catalog

⚠ **CLINICAL SAFETY BOUNDARY**: You are a healthcare navigation assistant.
You do NOT provide formal medical diagnoses, prescribe medications, adjust dosages, or replace emergency triage.
For acute life-threatening emergencies (e.g., crushing chest pain, acute stroke, severe dyspnea, anaphylaxis), immediately direct the user to call 911 / 988 or seek emergency medical care.

### Skill Progressive Disclosure Protocol
1. Review the catalog below — each skill contains a `name`, `description`, and allowed tools.
2. When a user inquiry matches a skill's clinical scope, retrieve its full instructions on-demand:
   `read_file("{{path}}")` (e.g. `read_file("skills/<skill-name>/SKILL.md")`)
3. Follow the structured protocols defined inside `SKILL.md`. If specialized clinical guidelines or reference templates are cited, retrieve them on-demand:
   `read_file("skills/<skill-name>/references/<document>.md")`
4. Never extrapolate clinical advice or execute workflows beyond what the loaded skill's verified documentation explicitly permits.

### Skill Sources
{skills_locations}

### Catalog
{skills_list}

{skills_load_warnings}
"""

try:
    from deepagents.backends.filesystem import FilesystemBackend
    from deepagents.middleware.skills import SkillsMiddleware, SkillSource
except ImportError:
    FilesystemBackend = None  # type: ignore
    SkillsMiddleware = object  # type: ignore
    SkillSource = Any  # type: ignore


class CarefoldSkillsMiddleware(SkillsMiddleware):
    """Custom SkillsMiddleware embedding Carefold clinical safety preamble and progressive disclosure protocol."""

    def __init__(
        self,
        *,
        backend: Any,
        sources: Sequence[Any],
        system_prompt: Optional[str] = None,
    ) -> None:
        prompt = system_prompt if system_prompt is not None else CAREFOLD_SKILLS_PROMPT
        super().__init__(
            backend=backend,
            sources=sources,
            system_prompt=prompt,
        )

    @property
    def name(self) -> str:
        """Override middleware name to 'SkillsMiddleware' for in-place replacement."""
        return "SkillsMiddleware"

    def modify_request(self, request: Any) -> Any:
        """Inject skills documentation into model request's system message, ensuring string compatibility."""
        if hasattr(request, "system_message") and isinstance(request.system_message, str):
            from langchain_core.messages import SystemMessage

            try:
                request.system_message = SystemMessage(content=request.system_message)
            except Exception:
                pass
        return super().modify_request(request)


def create_carefold_skills_middleware(
    skills_dir: Optional[Union[Path, str, Sequence[Union[Path, str]]]] = None,
    *,
    backend: Optional[Any] = None,
    sources: Optional[Sequence[Any]] = None,
    system_prompt: Optional[str] = None,
) -> Any:
    """Factory creating Carefold SkillsMiddleware initialized with the clinical prompt template."""
    if FilesystemBackend is None:
        raise RuntimeError("deepagents package is required for Carefold SkillsMiddleware.")

    if backend is None:
        if skills_dir is None:
            from carefold.constants.paths import SKILLS_DIR

            root_path = Path(".").resolve() / SKILLS_DIR
        elif isinstance(skills_dir, (str, Path)):
            root_path = Path(skills_dir).resolve()
        elif isinstance(skills_dir, Sequence) and len(skills_dir) > 0:
            root_path = Path(skills_dir[0]).resolve()
        else:
            root_path = Path(".").resolve()
        backend = FilesystemBackend(root_dir=root_path)

    if sources is None:
        backend_root = getattr(backend, "cwd", None) or getattr(backend, "root_dir", None)
        if backend_root is not None:
            if skills_dir is None:
                sources = ["/"]
            elif isinstance(skills_dir, (str, Path)):
                try:
                    rel = Path(skills_dir).resolve().relative_to(Path(backend_root).resolve()).as_posix()
                    sources = ["/" if rel == "." else f"/{rel}"]
                except Exception:
                    sources = ["/"]
            elif isinstance(skills_dir, Sequence):
                resolved_sources = []
                for s in skills_dir:
                    try:
                        rel = Path(s).resolve().relative_to(Path(backend_root).resolve()).as_posix()
                        resolved_sources.append("/" if rel == "." else f"/{rel}")
                    except Exception:
                        resolved_sources.append("/")
                sources = resolved_sources or ["/"]
            else:
                sources = ["/"]
        else:
            sources = ["/"]

    return CarefoldSkillsMiddleware(
        backend=backend,
        sources=sources,
        system_prompt=system_prompt or CAREFOLD_SKILLS_PROMPT,
    )


create_skills_middleware = create_carefold_skills_middleware

__all__ = [
    "CAREFOLD_SKILLS_PROMPT",
    "CarefoldSkillsMiddleware",
    "create_carefold_skills_middleware",
    "create_skills_middleware",
]
