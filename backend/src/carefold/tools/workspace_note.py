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

"""Closed Phase 0 tool: workspace-note.

Saves structured markdown notes into the workspace notes directory.
Prevents directory traversal, protects against symlink overwriting, and formats with YAML frontmatter.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any, Dict

from carefold.constants.defaults import (
    DEFAULT_NOTE_AGENT_ID,
    DEFAULT_NOTE_SLUG,
    MAX_NOTE_SLUG_LENGTH,
)
from carefold.constants.paths import (
    NOTES_DIR,
    WORKSPACE_DIR,
    WORKSPACE_NOTES_DIR,
)
from carefold.schemas.tool import ToolResult
from carefold.tools.sandbox import SandboxSecurityError, resolve_sandboxed_path


async def execute_workspace_note(params: Dict[str, Any], context: Any) -> ToolResult:
    """Executes the workspace-note tool securely."""
    try:
        title = params.get("title")
        content = params.get("content")

        if not title or not isinstance(title, str):
            return ToolResult(
                success=False,
                output=None,
                error='Parameter "title" must be a non-empty string.',
            )
        if content is None or not isinstance(content, str):
            return ToolResult(
                success=False,
                output=None,
                error='Parameter "content" must be a string.',
            )

        ws_root = getattr(context, "workspace_root", None) or Path.cwd()
        ws_root_path = Path(ws_root).resolve()

        # Sanitize title to safe filename slug
        safe_title = re.sub(r"[^a-zA-Z0-9_\-\s]", "", title.strip())
        safe_title = re.sub(r"\s+", "-", safe_title).lower()[:MAX_NOTE_SLUG_LENGTH] or DEFAULT_NOTE_SLUG
        filename = f"{safe_title}.md"

        # Determine target notes directory (support both ws/workspace/notes and ws/notes)
        sub_ws_notes = ws_root_path / WORKSPACE_NOTES_DIR
        root_notes = ws_root_path / NOTES_DIR

        if sub_ws_notes.is_dir() or (ws_root_path / WORKSPACE_DIR).is_dir():
            notes_dir = sub_ws_notes
        elif root_notes.is_dir():
            notes_dir = root_notes
        else:
            notes_dir = sub_ws_notes

        notes_dir.mkdir(parents=True, exist_ok=True)

        target_path = resolve_sandboxed_path(notes_dir, filename, must_exist=False, for_write=True)

        # Defense-in-depth: check if candidate or target is an existing symlink
        candidate_file = notes_dir / filename
        if (
            candidate_file.is_symlink()
            or os.path.islink(candidate_file)
            or target_path.is_symlink()
            or os.path.islink(target_path)
        ):
            return ToolResult(
                success=False,
                output=None,
                error=f'Path traversal forbidden: Target note "{filename}" is an existing symlink.',
            )

        agent_id = DEFAULT_NOTE_AGENT_ID
        if hasattr(context, "agent") and context.agent and hasattr(context.agent, "id"):
            agent_id = context.agent.id

        now_iso = datetime.now(timezone.utc).isoformat()
        escaped_title = title.strip().replace("\\", "\\\\").replace('"', '\\"')
        frontmatter = (
            f"---\n"
            f'title: "{escaped_title}"\n'
            f'created_at: "{now_iso}"\n'
            f'agent_id: "{agent_id}"\n'
            f"---\n\n"
            f"{content.strip()}\n"
        )

        target_path.write_text(frontmatter, encoding="utf-8")

        try:
            rel_path = str(target_path.relative_to(ws_root_path))
        except ValueError:
            rel_path = str(target_path)

        abs_path = str(target_path.resolve())

        return ToolResult(
            success=True,
            output={
                "title": safe_title,
                "slug": safe_title,
                "display_title": title.strip(),
                "filename": filename,
                "path": rel_path,
                "full_path": abs_path,
                "absolute_path": abs_path,
                "bytes_written": len(frontmatter.encode("utf-8")),
            },
        )

    except SandboxSecurityError as sec_err:
        return ToolResult(success=False, output=None, error=str(sec_err))
    except Exception as err:
        return ToolResult(success=False, output=None, error=f"Failed to save note: {err}")


# Alias for compatibility with tests and tool runner
workspace_note_tool = execute_workspace_note

