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

"""Workspace notes REST endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException
import yaml

from carefold.config import settings
from carefold.constants.api import ROUTE_NOTES, ROUTE_NOTE_DETAIL
from carefold.logging import get_logger
from carefold.schemas.notes import WorkspaceNoteDetail, WorkspaceNoteSummary

logger = get_logger("carefold.api.notes")

router = APIRouter(tags=["Notes"])

FRONTMATTER_PATTERN = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)$", re.DOTALL)
HEADING_PATTERN = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def parse_note_file(path: Path, workspace_root: Path | None = None) -> Dict[str, Any]:
    """Parses a markdown note file extracting frontmatter, resolved title, and content."""
    raw_text = path.read_text(encoding="utf-8", errors="replace")
    stat = path.stat()
    slug = path.stem

    match = FRONTMATTER_PATTERN.match(raw_text)
    if match:
        fm_raw, body = match.group(1), match.group(2)
        try:
            metadata = yaml.safe_load(fm_raw)
            if not isinstance(metadata, dict):
                metadata = {}
        except Exception:
            metadata = {}
    else:
        metadata = {}
        body = raw_text

    # Title resolution: 3-tier fallback
    # Tier 1: Frontmatter title (if human-readable, not matching raw slug)
    # Tier 2: First markdown `# ` heading
    # Tier 3: Title-cased slug
    fm_title = metadata.get("title")
    if fm_title is not None and not isinstance(fm_title, str):
        fm_title = str(fm_title)
    fm_title_clean = fm_title.strip() if fm_title else ""

    heading_match = HEADING_PATTERN.search(body)
    heading_title = heading_match.group(1).strip() if heading_match else None

    slug_title = slug.replace("-", " ").replace("_", " ").strip().title()

    if fm_title_clean and fm_title_clean != slug and fm_title_clean.lower() != slug:
        title = fm_title_clean
    elif heading_title:
        title = heading_title
    elif fm_title_clean:
        title = slug_title
    else:
        title = slug_title

    # Agent ID resolution
    agent = metadata.get("agent_id") or metadata.get("agent")
    if agent and not isinstance(agent, str):
        agent = str(agent)

    # Creation timestamp resolution
    created_at = metadata.get("created_at")
    if not created_at or not isinstance(created_at, str):
        created_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()

    ws_root = workspace_root or settings.workspace_root
    try:
        rel_path = str(path.relative_to(ws_root))
    except ValueError:
        rel_path = f"workspace/notes/{path.name}"

    return {
        "slug": slug,
        "title": title,
        "agent": agent,
        "created_at": created_at,
        "size_bytes": stat.st_size,
        "content": body.strip(),
        "raw_content": raw_text,
        "metadata": metadata,
        "path": rel_path,
    }


@router.get(ROUTE_NOTES, response_model=List[WorkspaceNoteSummary])
async def list_notes() -> List[WorkspaceNoteSummary]:
    """Lists all markdown notes saved in the workspace notes directory."""
    notes_dir = settings.get_notes_dir()
    if not notes_dir.is_dir():
        return []

    summaries: List[WorkspaceNoteSummary] = []
    for item in notes_dir.iterdir():
        if item.is_file() and item.suffix.lower() == ".md" and not item.name.startswith("."):
            try:
                real_path = item.resolve()
                real_path.relative_to(notes_dir.resolve())
            except (ValueError, RuntimeError, OSError):
                logger.warning("note_symlink_escape_ignored", file=item.name)
                continue

            try:
                parsed = parse_note_file(item, settings.workspace_root)
                summaries.append(
                    WorkspaceNoteSummary(
                        slug=parsed["slug"],
                        title=parsed["title"],
                        agent=parsed["agent"],
                        created_at=parsed["created_at"],
                        size_bytes=parsed["size_bytes"],
                    )
                )
            except Exception as err:
                logger.warning("note_parse_failed", file=item.name, error=str(err))

    # Sort descending by created_at
    summaries.sort(key=lambda n: n.created_at, reverse=True)
    return summaries


@router.get(ROUTE_NOTE_DETAIL, response_model=WorkspaceNoteDetail)
async def get_note_detail(slug: str) -> WorkspaceNoteDetail:
    """Reads a specific note by slug with strict path traversal protection."""
    SAFE_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")

    if "/" in slug or "\\" in slug:
        raise HTTPException(
            status_code=400,
            detail="Invalid note slug: must contain only alphanumeric characters, dashes, and underscores.",
        )

    clean_slug = os.path.basename(slug.strip())
    if clean_slug.endswith(".md"):
        clean_slug = clean_slug[:-3]

    if not clean_slug or not SAFE_SLUG_PATTERN.match(clean_slug):
        raise HTTPException(
            status_code=400,
            detail="Invalid note slug: must contain only alphanumeric characters, dashes, and underscores.",
        )

    filename = f"{clean_slug}.md"
    notes_dir = settings.get_notes_dir()
    if not notes_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Note '{clean_slug}' not found.")

    target_file: Path | None = None
    for entry in notes_dir.iterdir():
        if entry.is_file() and entry.name == filename and not entry.name.startswith("."):
            try:
                real_path = entry.resolve()
                if not real_path.is_relative_to(notes_dir.resolve()):
                    logger.warning("note_symlink_escape_blocked", file=entry.name)
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid note path: escapes sandbox directory",
                    )
                target_file = real_path
                break
            except (ValueError, RuntimeError, OSError) as path_err:
                logger.warning("note_symlink_escape_blocked", file=entry.name, error=str(path_err))
                raise HTTPException(status_code=400, detail=f"Invalid note path: {path_err}")

    if target_file is None:
        raise HTTPException(status_code=404, detail=f"Note '{clean_slug}' not found.")

    parsed = parse_note_file(target_file, settings.workspace_root)
    return WorkspaceNoteDetail(**parsed)


__all__ = ["router", "list_notes", "get_note_detail", "parse_note_file"]
