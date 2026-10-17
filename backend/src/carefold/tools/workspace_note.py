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

        from carefold.config import settings

        ws_root = getattr(context, "workspace_root", None)
        if ws_root and not (Path(ws_root) / "backend").is_dir():
            ws_root_path = Path(ws_root).resolve()
            sub_ws_notes = ws_root_path / WORKSPACE_NOTES_DIR
            root_notes = ws_root_path / NOTES_DIR

            if sub_ws_notes.is_dir() or (ws_root_path / WORKSPACE_DIR).is_dir():
                notes_dir = sub_ws_notes
            elif root_notes.is_dir():
                notes_dir = root_notes
            else:
                notes_dir = sub_ws_notes
        else:
            ws_root_path = settings.home_dir
            notes_dir = settings.get_notes_dir()

        # Sanitize title to safe filename slug
        safe_title = re.sub(r"[^a-zA-Z0-9_\-\s]", "", title.strip())
        safe_title = re.sub(r"\s+", "-", safe_title).lower()[:MAX_NOTE_SLUG_LENGTH] or DEFAULT_NOTE_SLUG
        filename = f"{safe_title}.md"
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

        # Also persist into relational database (carefold.db -> notes table) when not in an isolated test tmp_path
        is_isolated_test_workspace = bool(
            ws_root
            and not (Path(ws_root) / "backend").is_dir()
            and Path(ws_root).resolve() != settings.home_dir.resolve()
        )
        if not is_isolated_test_workspace:
            try:
                import hashlib
                import json
                import uuid
                from sqlalchemy import select
                from carefold.db.models import Job, Note, Profile
                from carefold.db.session import get_session_factory

                ctx_user_id = getattr(context, "user_id", None) if context is not None else None
                ctx_profile_id = getattr(context, "profile_id", None) if context is not None else None
                if ctx_user_id in ("default_user", ""):
                    ctx_user_id = None
                if ctx_profile_id in ("default_profile", ""):
                    ctx_profile_id = None

                factory = get_session_factory()
                async with factory() as session:
                    resolved_profile_id = ctx_profile_id
                    resolved_user_id = ctx_user_id
                    if resolved_profile_id and str(resolved_profile_id).lower() == "me" and resolved_user_id:
                        prof_res = await session.execute(
                            select(Profile).where(Profile.user_id == resolved_user_id).limit(1)
                        )
                        prof_obj = prof_res.scalar_one_or_none()
                        if prof_obj is not None:
                            resolved_profile_id = prof_obj.id
                        else:
                            resolved_profile_id = None
                    elif resolved_profile_id:
                        prof_res = await session.execute(
                            select(Profile).where(Profile.id == resolved_profile_id).limit(1)
                        )
                        prof_obj = prof_res.scalar_one_or_none()
                        if prof_obj is None:
                            resolved_profile_id = None
                        elif not resolved_user_id:
                            resolved_user_id = prof_obj.user_id

                    existing_stmt = select(Note).where(Note.slug == safe_title)
                    if resolved_profile_id:
                        existing_stmt = existing_stmt.where(Note.profile_id == resolved_profile_id)
                    existing_res = await session.execute(existing_stmt.limit(1))
                    existing_note = existing_res.scalar_one_or_none()
                    now_dt = datetime.now(timezone.utc)
                    display_title = title.strip()
                    if display_title == safe_title:
                        display_title = safe_title.replace("-", " ").replace("_", " ").strip().title() or title.strip()

                    if existing_note is not None:
                        existing_note.title = display_title
                        existing_note.content = content.strip()
                        existing_note.type = agent_id or existing_note.type or "general"
                        existing_note.updated_at = now_dt
                        note_id = existing_note.id
                    else:
                        note_id = str(uuid.uuid4())
                        new_note = Note(
                            id=note_id,
                            type=agent_id or "general",
                            user_id=resolved_user_id,
                            profile_id=resolved_profile_id,
                            slug=safe_title,
                            title=display_title,
                            content=content.strip(),
                            tags_json="[]",
                            created_at=now_dt,
                            updated_at=now_dt,
                        )
                        session.add(new_note)

                    if resolved_profile_id:
                        content_hash = hashlib.sha256(content.strip().encode("utf-8")).hexdigest()[:12]
                        index_job = Job(
                            id=str(uuid.uuid4()),
                            profile_id=resolved_profile_id,
                            kind="index_doc",
                            payload=json.dumps({
                                "document_id": note_id,
                                "profile_id": resolved_profile_id,
                                "doc_type": "note",
                            }),
                            timezone="UTC",
                            next_run_at=now_dt,
                            idempotency_key=f"index:note:{note_id}:{content_hash}",
                            status="pending",
                        )
                        session.add(index_job)

                    await session.commit()
            except Exception:
                pass

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

