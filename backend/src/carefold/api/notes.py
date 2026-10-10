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

"""Workspace notes REST endpoints backed exclusively by relational database (carefold.db)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession
import yaml

from carefold.api.deps import get_current_user, resolve_owner_user_id
from carefold.api.profiles import get_user_profile_access
from carefold.auth.ports import UserProfile
from carefold.config import settings
from carefold.constants.api import ROUTE_NOTE_DETAIL, ROUTE_NOTES
from carefold.db.models import Note, Profile, ProfileAccess
from carefold.db.session import get_db
from carefold.logging import get_logger
from carefold.schemas.notes import (
    NoteCreateRequest,
    NoteUpdateRequest,
    WorkspaceNoteDetail,
    WorkspaceNoteSummary,
)

logger = get_logger("carefold.api.notes")

router = APIRouter(tags=["Notes"])

FRONTMATTER_PATTERN = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)$", re.DOTALL)
HEADING_PATTERN = re.compile(r"^#\s+(.+)$", re.MULTILINE)
SAFE_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")
_note_creation_locks: dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}


def _get_note_creation_lock() -> asyncio.Lock:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    lock = _note_creation_locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _note_creation_locks[loop] = lock
    return lock


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

    profile_id = metadata.get("profile_id")
    if profile_id and not isinstance(profile_id, str):
        profile_id = str(profile_id)

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
        "profile_id": profile_id,
        "created_at": created_at,
        "size_bytes": stat.st_size,
        "content": body.strip(),
        "raw_content": raw_text,
        "metadata": metadata,
        "path": rel_path,
        "tags": metadata.get("tags") or [],
        "tags_json": json.dumps(metadata.get("tags") or []),
    }


def get_user_notes_dir(owner_id: Optional[str], profile_id: Optional[str] = None) -> Path:
    """Returns directory for user- and profile-scoped notes, creating it if needed."""
    base_dir = settings.get_notes_dir()
    if not owner_id:
        target_dir = (base_dir / profile_id) if profile_id else base_dir
    else:
        target_dir = (base_dir / owner_id / profile_id) if profile_id else (base_dir / owner_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def _clean_and_validate_slug(slug: str) -> str:
    """Validates slug for security, stripping any .md extension."""
    if "/" in slug or "\\" in slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid note slug: must contain only alphanumeric characters, dashes, and underscores.",
        )
    clean_slug = os.path.basename(slug.strip())
    if clean_slug.endswith(".md"):
        clean_slug = clean_slug[:-3]

    if not clean_slug or not SAFE_SLUG_PATTERN.match(clean_slug):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid note slug: must contain only alphanumeric characters, dashes, and underscores.",
        )
    return clean_slug


def _build_note_detail_response(note: Note) -> WorkspaceNoteDetail:
    """Builds a WorkspaceNoteDetail response synthesizing raw_content on the fly."""
    created_iso = note.created_at.isoformat() if note.created_at else datetime.now(timezone.utc).isoformat()
    tags = note.get_tags()
    profile_fm = f"\nprofile_id: \"{note.profile_id}\"" if note.profile_id else ""
    raw_content = f"---\ntitle: \"{note.title}\"\ncreated_at: \"{created_iso}\"{profile_fm}\n---\n\n{note.content}\n"
    rel_path = f"workspace/notes/{note.slug}.md"

    return WorkspaceNoteDetail(
        slug=note.slug,
        title=note.title,
        agent=note.type or None,
        profile_id=note.profile_id,
        created_at=created_iso,
        size_bytes=len(note.content.encode("utf-8")),
        content=note.content,
        raw_content=raw_content,
        metadata={
            "title": note.title,
            "created_at": created_iso,
            "agent_id": note.type,
            "profile_id": note.profile_id,
            "tags": tags,
        },
        path=rel_path,
        tags=tags,
        tags_json=note.tags_json or "[]",
    )


@router.get(ROUTE_NOTES, response_model=List[WorkspaceNoteSummary])
async def list_notes(
    profile_id: Optional[str] = Query(default=None, description="Optional profile ID filter"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[WorkspaceNoteSummary]:
    """Lists all clinical notes from carefold.db with strict user and profile scoping."""
    owner_id = resolve_owner_user_id(user)
    effective_user_id = owner_id or user.id
    is_admin = getattr(user, "role", "member") == "admin"

    if profile_id:
        p_stmt = select(Profile).where(Profile.id == profile_id)
        p_res = await db.execute(p_stmt)
        prof = p_res.scalar_one_or_none()
        if prof is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")

        access = await get_user_profile_access(prof, user, db)
        if access is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: no permissions for requested profile.",
            )
        if access == "view_paperwork":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: clinical view permissions required to inspect clinical notes.",
            )

        stmt = select(Note).where(Note.profile_id == profile_id).order_by(Note.updated_at.desc())
    else:
        if is_admin or owner_id is None:
            # Admin or offline desktop single-user mode sees all notes
            stmt = select(Note).order_by(Note.updated_at.desc())
        else:
            # Find all profiles user owns or has clinical/management access to
            accessible_profiles_stmt = (
                select(Profile.id)
                .outerjoin(ProfileAccess, Profile.id == ProfileAccess.profile_id)
                .where(
                    (Profile.user_id == owner_id)
                    | (
                        (ProfileAccess.user_id == effective_user_id)
                        & ProfileAccess.access_level.in_(("manage", "view_clinical"))
                    )
                )
                .distinct()
            )
            accessible_res = await db.execute(accessible_profiles_stmt)
            accessible_profile_ids = list(accessible_res.scalars().all())

            stmt = select(Note).where(
                (
                    (Note.user_id == owner_id)
                    & (Note.profile_id.is_(None))
                )
                | (Note.profile_id.in_(accessible_profile_ids))
            ).order_by(Note.updated_at.desc())

    res = await db.execute(stmt)
    notes = res.scalars().all()

    return [
        WorkspaceNoteSummary(
            slug=n.slug,
            title=n.title,
            agent=n.type or None,
            profile_id=n.profile_id,
            created_at=n.created_at.isoformat() if n.created_at else datetime.now(timezone.utc).isoformat(),
            size_bytes=len(n.content.encode("utf-8")),
            tags=n.get_tags(),
            tags_json=n.tags_json or "[]",
        )
        for n in notes
    ]


@router.post(ROUTE_NOTES, response_model=WorkspaceNoteDetail, status_code=status.HTTP_201_CREATED)
async def create_note(
    payload: NoteCreateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceNoteDetail:
    """Creates a new note strictly in carefold.db with zero filesystem disk write."""
    title = payload.title
    # Compute and validate slug
    if payload.slug:
        slug = _clean_and_validate_slug(payload.slug)
    else:
        raw_slug = re.sub(r"[^a-zA-Z0-9_\-\s]", "", title.strip())
        slug = re.sub(r"\s+", "-", raw_slug).lower()[:64] or "note"

    if not SAFE_SLUG_PATTERN.match(slug):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid note slug.")

    # 3-tier title resolution: if title matches slug or is empty, resolve from # heading or title-case slug
    if title == slug:
        heading_match = re.search(r"^\s*#\s+(.+)$", payload.content, re.MULTILINE)
        if heading_match:
            title = heading_match.group(1).strip()
        else:
            title = slug.replace("-", " ").replace("_", " ").title()

    owner_id = resolve_owner_user_id(user)

    if payload.profile_id:
        p_stmt = select(Profile).where(Profile.id == payload.profile_id)
        p_res = await db.execute(p_stmt)
        prof = p_res.scalar_one_or_none()
        if prof is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")

        access = await get_user_profile_access(prof, user, db)
        if access != "manage":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: management permissions required to create notes for this profile.",
            )

    # Concurrency-safe slug uniqueness resolution & persistence
    async with _get_note_creation_lock():
        base_slug = slug
        candidate_slug = base_slug
        while True:
            stmt = select(Note.id).where(Note.slug == candidate_slug)
            if payload.profile_id:
                stmt = stmt.where(Note.profile_id == payload.profile_id)
            elif owner_id:
                stmt = stmt.where(Note.user_id == owner_id)

            res = await db.execute(stmt)
            if res.scalar_one_or_none() is None:
                break

            # Collision detected: append unique timestamp-uuid suffix
            ts = int(datetime.now(timezone.utc).timestamp())
            unique_suffix = f"{ts}-{uuid.uuid4().hex[:6]}"
            candidate_slug = f"{base_slug[:105]}-{unique_suffix}"

        slug = candidate_slug

        now = datetime.now(timezone.utc)
        tags_list = payload.tags or []

        new_note = Note(
            id=str(uuid.uuid4()),
            type=payload.type or "scratchpad",
            user_id=owner_id,
            profile_id=payload.profile_id,
            slug=slug,
            title=title,
            content=payload.content,
            tags_json=json.dumps(tags_list),
            created_at=now,
            updated_at=now,
        )
        db.add(new_note)
        await db.commit()

    logger.info("note_created_in_db", slug=slug, profile_id=payload.profile_id, user_id=owner_id)
    return _build_note_detail_response(new_note)


async def _find_note_for_user(
    clean_slug: str,
    user: UserProfile,
    owner_id: Optional[str],
    db: AsyncSession,
    require_manage: bool = False,
) -> Note:
    """Finds a note matching slug with multi-tenant and profile access scoping, plus symlink escape protection."""
    # Defense-in-depth symlink escape check on disk
    notes_dir = settings.get_notes_dir()
    for ext in (".md", ""):
        candidate_file = notes_dir / f"{clean_slug}{ext}"
        if candidate_file.is_symlink():
            try:
                resolved = candidate_file.resolve()
                if not resolved.is_relative_to(notes_dir.resolve()):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid note path: symlink escape detected.",
                    )
            except (ValueError, RuntimeError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid note path: symlink escape detected.",
                )

    stmt = select(Note).where(Note.slug == clean_slug)
    res = await db.execute(stmt)
    matching_notes = list(res.scalars().all())

    if not matching_notes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note '{clean_slug}' not found.",
        )

    accessible_notes: list[tuple[Note, str]] = []
    has_forbidden = False

    for candidate in matching_notes:
        if candidate.profile_id is not None:
            p_stmt = select(Profile).where(Profile.id == candidate.profile_id)
            p_res = await db.execute(p_stmt)
            prof = p_res.scalar_one_or_none()
            if prof is not None:
                access = await get_user_profile_access(prof, user, db)
                if access is None or access == "view_paperwork":
                    has_forbidden = True
                    continue
                if require_manage and access != "manage":
                    has_forbidden = True
                    continue
                accessible_notes.append((candidate, access))
            else:
                has_forbidden = True
        elif owner_id and getattr(user, "role", "member") != "admin":
            if candidate.user_id is not None and candidate.user_id != owner_id:
                has_forbidden = True
                continue
            accessible_notes.append((candidate, "owner"))
        else:
            accessible_notes.append((candidate, "owner"))

    if not accessible_notes:
        if has_forbidden:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: note belongs to another user or profile.",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note '{clean_slug}' not found.",
        )

    if len(accessible_notes) > 1 and owner_id:
        for n, _ in accessible_notes:
            if n.user_id == owner_id:
                return n
    return accessible_notes[0][0]


@router.get(ROUTE_NOTE_DETAIL, response_model=WorkspaceNoteDetail)
async def get_note_detail(
    slug: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceNoteDetail:
    """Reads a note from carefold.db by slug with strict access validation and zero filesystem fallback."""
    clean_slug = _clean_and_validate_slug(slug)
    owner_id = resolve_owner_user_id(user)
    note = await _find_note_for_user(clean_slug, user, owner_id, db, require_manage=False)
    return _build_note_detail_response(note)


@router.put(ROUTE_NOTE_DETAIL, response_model=WorkspaceNoteDetail)
async def update_note(
    slug: str,
    payload: NoteUpdateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceNoteDetail:
    """Updates a note in carefold.db with strict access control and zero filesystem disk update."""
    clean_slug = _clean_and_validate_slug(slug)
    owner_id = resolve_owner_user_id(user)
    note = await _find_note_for_user(clean_slug, user, owner_id, db, require_manage=True)

    # Validate target profile access if being reassigned
    if payload.profile_id is not None and payload.profile_id != note.profile_id:
        p_stmt = select(Profile).where(Profile.id == payload.profile_id)
        p_res = await db.execute(p_stmt)
        target_prof = p_res.scalar_one_or_none()
        if target_prof is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target profile not found.")
        target_access = await get_user_profile_access(target_prof, user, db)
        if target_access != "manage":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: management permissions required for target profile.",
            )
        note.profile_id = payload.profile_id

    if payload.title is not None:
        note.title = payload.title
    if payload.content is not None:
        note.content = payload.content
    if payload.type is not None:
        note.type = payload.type
    if payload.tags is not None:
        note.set_tags(payload.tags)

    note.updated_at = datetime.now(timezone.utc)
    await db.commit()
    try:
        await db.refresh(note)
    except (InvalidRequestError, Exception) as exc:
        logger.debug("note_refresh_skipped_on_update", slug=clean_slug, error=str(exc))

    logger.info("note_updated_in_db", slug=clean_slug)
    return _build_note_detail_response(note)


@router.delete(ROUTE_NOTE_DETAIL)
async def delete_note(
    slug: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Deletes a note from carefold.db with zero filesystem unlink operations."""
    clean_slug = _clean_and_validate_slug(slug)
    owner_id = resolve_owner_user_id(user)
    note = await _find_note_for_user(clean_slug, user, owner_id, db, require_manage=True)

    await db.delete(note)
    await db.commit()

    logger.info("note_deleted_from_db", slug=clean_slug)
    return {"deleted": True, "slug": clean_slug}


__all__ = [
    "router",
    "list_notes",
    "create_note",
    "get_note_detail",
    "update_note",
    "delete_note",
    "parse_note_file",
    "get_user_notes_dir",
]
