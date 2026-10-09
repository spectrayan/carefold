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

"""Workspace notes REST endpoints backed by generic SQL database and workspace notes directory."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
import yaml

from carefold.api.deps import get_current_user, resolve_owner_user_id
from carefold.auth.ports import UserProfile
from carefold.config import settings
from carefold.constants.api import ROUTE_NOTE_DETAIL, ROUTE_NOTES
from carefold.db.models import Note
from carefold.db.session import get_db
from carefold.logging import get_logger
from carefold.schemas.notes import (
    NoteCreateRequest,
    NoteUpdateRequest,
    WorkspaceNoteDetail,
    WorkspaceNoteSummary,
)
from carefold.tools.sandbox import resolve_sandboxed_path

logger = get_logger("carefold.api.notes")

router = APIRouter(tags=["Notes"])

FRONTMATTER_PATTERN = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)$", re.DOTALL)
HEADING_PATTERN = re.compile(r"^#\s+(.+)$", re.MULTILINE)
SAFE_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")


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

    agent = metadata.get("agent_id") or metadata.get("agent")
    if agent and not isinstance(agent, str):
        agent = str(agent)

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
async def list_notes(
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[WorkspaceNoteSummary]:
    """Lists all markdown notes saved in the database or workspace notes directory."""
    seen_slugs = set()
    summaries: List[WorkspaceNoteSummary] = []

    # 1. Query database notes
    try:
        stmt = select(Note).order_by(Note.updated_at.desc())
        owner_id = resolve_owner_user_id(user)
        if owner_id and getattr(user, "role", "member") != "admin":
            stmt = stmt.where(Note.user_id == owner_id)
        res = await db.execute(stmt)
        for n in res.scalars().all():
            seen_slugs.add(n.slug)
            summaries.append(
                WorkspaceNoteSummary(
                    slug=n.slug,
                    title=n.title,
                    agent=None,
                    created_at=n.created_at.isoformat() if n.created_at else datetime.now(timezone.utc).isoformat(),
                    size_bytes=len(n.content.encode("utf-8")),
                )
            )
    except Exception as err:
        logger.warning("db_notes_query_failed", error=str(err))

    # 2. Add filesystem notes not already tracked
    notes_dir = settings.get_notes_dir()
    if notes_dir.is_dir():
        for item in notes_dir.iterdir():
            if item.is_file() and item.suffix.lower() == ".md" and not item.name.startswith("."):
                if item.stem in seen_slugs:
                    continue
                try:
                    real_path = item.resolve()
                    real_path.relative_to(notes_dir.resolve())
                except (ValueError, RuntimeError, OSError):
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


@router.post(ROUTE_NOTES, response_model=WorkspaceNoteDetail, status_code=status.HTTP_201_CREATED)
async def create_note(
    payload: NoteCreateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceNoteDetail:
    """Creates a new note in the database and writes a local file to workspace/notes/."""
    # Compute slug
    if payload.slug:
        slug = payload.slug.strip().lower()
    else:
        raw_slug = re.sub(r"[^a-zA-Z0-9_\-\s]", "", payload.title.strip())
        slug = re.sub(r"\s+", "-", raw_slug).lower()[:64] or "note"

    if not SAFE_SLUG_PATTERN.match(slug):
        raise HTTPException(status_code=400, detail="Invalid note slug.")

    owner_id = resolve_owner_user_id(user)
    created_iso = datetime.now(timezone.utc).isoformat()
    try:
        stmt = select(Note).where(Note.slug == slug)
        if owner_id:
            stmt = stmt.where(Note.user_id == owner_id)
        res = await db.execute(stmt)
        if res.scalar_one_or_none() is not None:
            # Append unique timestamp suffix
            slug = f"{slug}-{int(datetime.now(timezone.utc).timestamp())}"

        new_note = Note(
            type=payload.type or "scratchpad",
            user_id=owner_id,
            slug=slug,
            title=payload.title,
            content=payload.content,
            tags_json=json.dumps(payload.tags),
        )
        db.add(new_note)
        await db.commit()
        await db.refresh(new_note)
        if new_note.created_at:
            created_iso = new_note.created_at.isoformat()
    except Exception as db_err:
        logger.warning("db_create_note_failed", slug=slug, error=str(db_err))

    # Write file to workspace/notes/
    notes_dir = settings.get_notes_dir()
    notes_dir.mkdir(parents=True, exist_ok=True)
    target_file = notes_dir / f"{slug}.md"
    file_content = f"---\ntitle: \"{payload.title}\"\ncreated_at: \"{created_iso}\"\n---\n\n{payload.content.strip()}\n"
    try:
        target_file.write_text(file_content, encoding="utf-8")
    except Exception as file_err:
        logger.warning("failed_to_write_note_file", slug=slug, error=str(file_err))

    return WorkspaceNoteDetail(
        slug=slug,
        title=payload.title,
        agent=None,
        created_at=created_iso,
        size_bytes=len(payload.content.encode("utf-8")),
        content=payload.content,
        raw_content=file_content,
        metadata={"title": payload.title, "created_at": created_iso},
        path=f"workspace/notes/{slug}.md",
    )


@router.get(ROUTE_NOTE_DETAIL, response_model=WorkspaceNoteDetail)
async def get_note_detail(
    slug: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceNoteDetail:
    """Reads a specific note by slug with strict path traversal protection."""
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

    # 1. Query database first
    try:
        stmt = select(Note).where(Note.slug == clean_slug)
        res = await db.execute(stmt)
        note = res.scalar_one_or_none()
        if note is not None:
            created_iso = note.created_at.isoformat() if note.created_at else datetime.now(timezone.utc).isoformat()
            raw_content = f"---\ntitle: \"{note.title}\"\ncreated_at: \"{created_iso}\"\n---\n\n{note.content}\n"
            return WorkspaceNoteDetail(
                slug=note.slug,
                title=note.title,
                agent=None,
                created_at=created_iso,
                size_bytes=len(note.content.encode("utf-8")),
                content=note.content,
                raw_content=raw_content,
                metadata={"title": note.title, "created_at": created_iso},
                path=f"workspace/notes/{note.slug}.md",
            )
    except Exception as err:
        logger.warning("db_note_detail_query_failed", slug=clean_slug, error=str(err))

    # 2. Fallback to filesystem
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


@router.put(ROUTE_NOTE_DETAIL, response_model=WorkspaceNoteDetail)
async def update_note(
    slug: str,
    payload: NoteUpdateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceNoteDetail:
    """Updates a note in the database and reflects changes in workspace notes directory."""
    clean_slug = os.path.basename(slug.strip())
    if clean_slug.endswith(".md"):
        clean_slug = clean_slug[:-3]

    note = None
    try:
        stmt = select(Note).where(Note.slug == clean_slug)
        res = await db.execute(stmt)
        note = res.scalar_one_or_none()
    except Exception as db_err:
        logger.warning("db_update_note_query_failed", slug=clean_slug, error=str(db_err))

    notes_dir = settings.get_notes_dir()
    target_file = notes_dir / f"{clean_slug}.md"

    if note is None and not target_file.is_file():
        raise HTTPException(status_code=404, detail=f"Note '{clean_slug}' not found.")

    now_iso = datetime.now(timezone.utc).isoformat()
    if note is not None:
        if payload.title is not None:
            note.title = payload.title
        if payload.content is not None:
            note.content = payload.content
        if payload.type is not None:
            note.type = payload.type
        if payload.tags is not None:
            note.set_tags(payload.tags)

        try:
            await db.commit()
            await db.refresh(note)
            created_iso = note.created_at.isoformat() if note.created_at else now_iso
            title = note.title
            content = note.content
        except Exception as commit_err:
            logger.warning("db_update_note_commit_failed", slug=clean_slug, error=str(commit_err))
            created_iso = now_iso
            title = payload.title or clean_slug
            content = payload.content or ""
    else:
        # Fallback to filesystem note
        parsed = parse_note_file(target_file, settings.workspace_root)
        created_iso = parsed.get("created_at", now_iso)
        title = payload.title if payload.title is not None else parsed.get("title", clean_slug)
        content = payload.content if payload.content is not None else parsed.get("content", "")

    # Reflect in filesystem if file exists or directory exists
    raw_content = f"---\ntitle: \"{title}\"\ncreated_at: \"{created_iso}\"\n---\n\n{content}\n"
    if notes_dir.is_dir():
        try:
            target_file.write_text(raw_content, encoding="utf-8")
        except Exception:
            pass

    return WorkspaceNoteDetail(
        slug=clean_slug,
        title=title,
        agent=None,
        created_at=created_iso,
        size_bytes=len(content.encode("utf-8")),
        content=content,
        raw_content=raw_content,
        metadata={"title": title, "created_at": created_iso},
        path=f"workspace/notes/{clean_slug}.md",
    )


@router.delete(ROUTE_NOTE_DETAIL)
async def delete_note(
    slug: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Deletes a note from the database and removes its file from workspace/notes/."""
    clean_slug = os.path.basename(slug.strip())
    if clean_slug.endswith(".md"):
        clean_slug = clean_slug[:-3]

    # Delete from DB
    try:
        stmt = select(Note).where(Note.slug == clean_slug)
        res = await db.execute(stmt)
        note = res.scalar_one_or_none()
        if note is not None:
            await db.delete(note)
            await db.commit()
    except Exception as db_err:
        logger.warning("db_delete_note_failed", slug=clean_slug, error=str(db_err))

    # Remove from filesystem
    notes_dir = settings.get_notes_dir()
    target_file = notes_dir / f"{clean_slug}.md"
    if target_file.is_file():
        try:
            target_file.unlink()
        except Exception:
            pass

    return {"deleted": True, "slug": clean_slug}


__all__ = [
    "router",
    "list_notes",
    "create_note",
    "get_note_detail",
    "update_note",
    "delete_note",
    "parse_note_file",
]
