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

"""Workspace notes REST endpoints backed exclusively by relational database (carefold.db)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession
import yaml

from carefold.api.deps import get_current_user, resolve_owner_user_id
from carefold.api.profiles import get_user_profile_access
from carefold.auth.ports import UserProfile
from carefold.clinical.notes import (
    VALID_NOTE_TYPES,
    extract_after_visit_summary,
    validate_note_type,
)
from carefold.config import settings
from carefold.constants.api import ROUTE_NOTE_DETAIL, ROUTE_NOTES
from carefold.db.models import Appointment, Job, Note, Profile, ProfileAccess
from carefold.db.session import get_db
from carefold.i18n.locale import (
    DEFAULT_LOCALE,
    canonicalize_locale,
    normalize_text_nfc,
)
from carefold.logging import get_logger
from carefold.schemas.notes import (
    AfterVisitExtractionResponse,
    NoteCreateRequest as _BaseNoteCreateRequest,
    NoteUpdateRequest as _BaseNoteUpdateRequest,
    TypedNoteCreateRequest as _BaseTypedNoteCreateRequest,
    TypedNoteDetailResponse as _BaseTypedNoteDetailResponse,
    TypedNoteListResponse as _BaseTypedNoteListResponse,
    TypedNoteSummaryResponse as _BaseTypedNoteSummaryResponse,
    TypedNoteUpdateRequest as _BaseTypedNoteUpdateRequest,
    WorkspaceNoteDetail as _BaseWorkspaceNoteDetail,
    WorkspaceNoteSummary as _BaseWorkspaceNoteSummary,
)


class WorkspaceNoteSummary(_BaseWorkspaceNoteSummary):
    locale: str = Field(default=DEFAULT_LOCALE, description="IETF BCP 47 locale tag of the note content")


class WorkspaceNoteDetail(_BaseWorkspaceNoteDetail):
    locale: str = Field(default=DEFAULT_LOCALE, description="IETF BCP 47 locale tag of the note content")


class NoteCreateRequest(_BaseNoteCreateRequest):
    locale: Optional[str] = Field(default=None, max_length=16, description="Optional IETF BCP 47 locale tag")


class NoteUpdateRequest(_BaseNoteUpdateRequest):
    locale: Optional[str] = Field(default=None, max_length=16, description="Optional IETF BCP 47 locale tag")


class TypedNoteCreateRequest(_BaseTypedNoteCreateRequest):
    locale: Optional[str] = Field(default=None, max_length=16, description="Optional IETF BCP 47 locale tag")


class TypedNoteUpdateRequest(_BaseTypedNoteUpdateRequest):
    locale: Optional[str] = Field(default=None, max_length=16, description="Optional IETF BCP 47 locale tag")


class TypedNoteSummaryResponse(_BaseTypedNoteSummaryResponse):
    locale: str = Field(default=DEFAULT_LOCALE, description="IETF BCP 47 locale tag of the note content")


class TypedNoteDetailResponse(_BaseTypedNoteDetailResponse):
    locale: str = Field(default=DEFAULT_LOCALE, description="IETF BCP 47 locale tag of the note content")


class TypedNoteListResponse(_BaseTypedNoteListResponse):
    notes: List[TypedNoteSummaryResponse]


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
    raw_text = normalize_text_nfc(path.read_text(encoding="utf-8", errors="replace"))
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
    fm_title_clean = normalize_text_nfc(fm_title.strip()) if fm_title else ""

    heading_match = HEADING_PATTERN.search(body)
    heading_title = normalize_text_nfc(heading_match.group(1).strip()) if heading_match else None

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
        "title": normalize_text_nfc(title),
        "agent": agent,
        "profile_id": profile_id,
        "created_at": created_at,
        "size_bytes": stat.st_size,
        "content": normalize_text_nfc(body.strip()),
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
    note_locale = getattr(note, "locale", None) or DEFAULT_LOCALE
    profile_fm = f"\nprofile_id: \"{note.profile_id}\"" if note.profile_id else ""
    raw_content = f"---\ntitle: \"{note.title}\"\ncreated_at: \"{created_iso}\"{profile_fm}\n---\n\n{note.content}\n"
    rel_path = f"workspace/notes/{note.slug}.md"

    return WorkspaceNoteDetail(
        slug=note.slug,
        title=note.title,
        agent=note.type or None,
        type=note.type or None,
        profile_id=note.profile_id,
        linked_appointment_id=note.linked_appointment_id,
        locale=note_locale,
        created_at=created_iso,
        size_bytes=len(note.content.encode("utf-8")),
        content=note.content,
        raw_content=raw_content,
        metadata={
            "title": note.title,
            "created_at": created_iso,
            "agent_id": note.type,
            "profile_id": note.profile_id,
            "linked_appointment_id": note.linked_appointment_id,
            "locale": note_locale,
            "tags": tags,
        },
        path=rel_path,
        tags=tags,
        tags_json=note.tags_json or "[]",
    )


def _build_typed_note_detail(note: Note) -> TypedNoteDetailResponse:
    """Builds a TypedNoteDetailResponse."""
    created_iso = note.created_at.isoformat() if note.created_at else datetime.now(timezone.utc).isoformat()
    updated_iso = note.updated_at.isoformat() if note.updated_at else datetime.now(timezone.utc).isoformat()
    note_locale = getattr(note, "locale", None) or DEFAULT_LOCALE
    return TypedNoteDetailResponse(
        id=note.id,
        profile_id=note.profile_id,
        slug=note.slug,
        title=note.title,
        type=note.type,
        content=note.content,
        locale=note_locale,
        linked_appointment_id=note.linked_appointment_id,
        tags=note.get_tags(),
        tags_json=note.tags_json or "[]",
        created_at=created_iso,
        updated_at=updated_iso,
    )


def _build_typed_note_summary(note: Note) -> TypedNoteSummaryResponse:
    """Builds a TypedNoteSummaryResponse."""
    created_iso = note.created_at.isoformat() if note.created_at else datetime.now(timezone.utc).isoformat()
    updated_iso = note.updated_at.isoformat() if note.updated_at else datetime.now(timezone.utc).isoformat()
    note_locale = getattr(note, "locale", None) or DEFAULT_LOCALE
    return TypedNoteSummaryResponse(
        id=note.id,
        profile_id=note.profile_id,
        slug=note.slug,
        title=note.title,
        type=note.type,
        locale=note_locale,
        linked_appointment_id=note.linked_appointment_id,
        tags=note.get_tags(),
        size_bytes=len(note.content.encode("utf-8")),
        created_at=created_iso,
        updated_at=updated_iso,
    )


async def _verify_profile_access(
    profile_id: str,
    user: UserProfile,
    db: AsyncSession,
    required_level: str = "manage",
) -> Profile:
    """Helper verifying that the profile exists and the user has appropriate permissions."""
    clean_id = (profile_id or "").strip()
    if not clean_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="profile_id is required",
        )

    stmt = select(Profile).where(Profile.id == clean_id)
    res = await db.execute(stmt)
    prof = res.scalar_one_or_none()
    if prof is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found.",
        )

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

    if required_level == "manage" and access != "manage":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: management permissions required to modify clinical notes for this profile.",
        )

    return prof


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
        prof = await _verify_profile_access(profile_id, user, db, required_level="view_clinical")
        stmt = select(Note).where(Note.profile_id == prof.id).order_by(Note.updated_at.desc())
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
            type=n.type or None,
            profile_id=n.profile_id,
            linked_appointment_id=n.linked_appointment_id,
            locale=getattr(n, "locale", None) or DEFAULT_LOCALE,
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
    title = normalize_text_nfc(payload.title)
    content_nfc = normalize_text_nfc(payload.content)
    # Compute and validate slug
    if payload.slug:
        slug = _clean_and_validate_slug(payload.slug)
    else:
        raw_slug = re.sub(r"[^a-zA-Z0-9_\-\s]", "", title.strip())
        slug = re.sub(r"\s+", "-", raw_slug).lower()[:64] or "note"

    if not SAFE_SLUG_PATTERN.match(slug):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid note slug.")

    # 3-tier title resolution
    if title == slug:
        resolved_heading: Optional[str] = None
        for line in content_nfc.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                heading_text = stripped.lstrip("#").strip()
                if heading_text:
                    resolved_heading = normalize_text_nfc(heading_text)
                    break
        if resolved_heading:
            title = resolved_heading
        else:
            title = slug.replace("-", " ").replace("_", " ").title()

    owner_id = resolve_owner_user_id(user)
    clean_profile_id = (payload.profile_id or "").strip()
    prof = await _verify_profile_access(clean_profile_id, user, db, required_level="manage")

    if payload.locale is not None:
        try:
            note_locale = canonicalize_locale(payload.locale, strict=True)
        except ValueError as loc_err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(loc_err),
            ) from loc_err
    else:
        note_locale = getattr(prof, "preferred_locale", None) or DEFAULT_LOCALE

    # Validate note category
    raw_type = (payload.type or "scratchpad").strip()
    try:
        note_type = validate_note_type(raw_type, allow_legacy=True)
    except ValueError as type_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(type_err),
        )

    # Validate linked appointment if present
    linked_appt_id = payload.linked_appointment_id
    if linked_appt_id:
        linked_appt_id = linked_appt_id.strip() or None
        if linked_appt_id:
            appt_stmt = select(Appointment).where(
                Appointment.id == linked_appt_id,
                Appointment.profile_id == clean_profile_id,
            )
            appt_res = await db.execute(appt_stmt)
            if appt_res.scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Security violation: Linked appointment does not exist or does not belong to profile.",
                )

    # Concurrency-safe slug uniqueness resolution & persistence
    async with _get_note_creation_lock():
        base_slug = slug
        candidate_slug = base_slug
        while True:
            stmt = select(Note.id).where(Note.slug == candidate_slug).where(Note.profile_id == clean_profile_id)
            res = await db.execute(stmt)
            if res.scalar_one_or_none() is None:
                break
            ts = int(datetime.now(timezone.utc).timestamp())
            unique_suffix = f"{ts}-{uuid.uuid4().hex[:6]}"
            candidate_slug = f"{base_slug[:105]}-{unique_suffix}"

        slug = candidate_slug
        now = datetime.now(timezone.utc)
        tags_list = payload.tags or []

        new_note = Note(
            id=str(uuid.uuid4()),
            type=note_type,
            user_id=owner_id,
            profile_id=clean_profile_id,
            slug=slug,
            title=normalize_text_nfc(title),
            content=content_nfc,
            locale=note_locale,
            tags_json=json.dumps(tags_list),
            linked_appointment_id=linked_appt_id,
            created_at=now,
            updated_at=now,
        )
        db.add(new_note)

        # Enqueue index_doc job for search freshness (AU-27)
        index_payload = {
            "document_id": new_note.id,
            "profile_id": clean_profile_id,
            "doc_type": "note",
        }
        content_hash = hashlib.sha256((new_note.content or "").encode("utf-8")).hexdigest()[:12]
        idempotency_key = f"index:note:{new_note.id}:{content_hash}"
        index_job = Job(
            id=str(uuid.uuid4()),
            profile_id=clean_profile_id,
            kind="index_doc",
            payload=json.dumps(index_payload),
            timezone="UTC",
            next_run_at=now,
            idempotency_key=idempotency_key,
            status="pending",
        )
        db.add(index_job)

        await db.commit()

        # Audit event
        try:
            from carefold.audit.logger import record_audit
            await record_audit(
                {
                    "profile_id": clean_profile_id,
                    "action": "create",
                    "tool": "api_notes",
                    "risk": "write_local",
                    "external_ref": f"note:{new_note.id}",
                    "details": {
                        "title": new_note.title,
                        "type": new_note.type,
                        "linked_appointment_id": new_note.linked_appointment_id,
                    },
                },
                actor_user_id=getattr(user, "id", "user"),
                risk="write_local",
            )
        except Exception as audit_err:
            logger.debug("Audit logging failed in create_note: %s", audit_err)

    logger.info("note_created_in_db", slug=slug, profile_id=clean_profile_id, user_id=owner_id)
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
    if payload.profile_id is not None:
        clean_target_pid = payload.profile_id.strip()
        if not clean_target_pid:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="profile_id cannot be null or empty.")
        if clean_target_pid != note.profile_id:
            await _verify_profile_access(clean_target_pid, user, db, required_level="manage")
            note.profile_id = clean_target_pid

    if payload.type is not None:
        try:
            note.type = validate_note_type(payload.type, allow_legacy=True)
        except ValueError as err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))

    if payload.linked_appointment_id is not None:
        clean_aid = payload.linked_appointment_id.strip() or None
        if clean_aid:
            appt_stmt = select(Appointment).where(
                Appointment.id == clean_aid,
                Appointment.profile_id == note.profile_id,
            )
            appt_res = await db.execute(appt_stmt)
            if appt_res.scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Security violation: Linked appointment does not exist or does not belong to profile.",
                )
        note.linked_appointment_id = clean_aid

    if payload.locale is not None:
        try:
            note.locale = canonicalize_locale(payload.locale, strict=True)
        except ValueError as loc_err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(loc_err),
            ) from loc_err

    if payload.title is not None:
        note.title = normalize_text_nfc(payload.title)
    if payload.content is not None:
        note.content = normalize_text_nfc(payload.content)
    if payload.tags is not None:
        note.set_tags(payload.tags)

    note.updated_at = datetime.now(timezone.utc)

    # Enqueue index_doc job for search reindexing (AU-27)
    index_payload = {
        "document_id": note.id,
        "profile_id": note.profile_id,
        "doc_type": "note",
    }
    content_hash = hashlib.sha256((note.content or "").encode("utf-8")).hexdigest()[:12]
    idempotency_key = f"index:note:{note.id}:{content_hash}"
    index_job = Job(
        id=str(uuid.uuid4()),
        profile_id=note.profile_id,
        kind="index_doc",
        payload=json.dumps(index_payload),
        timezone="UTC",
        next_run_at=datetime.now(timezone.utc),
        idempotency_key=idempotency_key,
        status="pending",
    )
    db.add(index_job)

    await db.commit()
    try:
        await db.refresh(note)
    except (InvalidRequestError, Exception) as exc:
        logger.debug("note_refresh_skipped_on_update", slug=clean_slug, error=str(exc))

    # Audit event
    try:
        from carefold.audit.logger import record_audit
        await record_audit(
            {
                "profile_id": note.profile_id,
                "action": "update",
                "tool": "api_notes",
                "risk": "write_local",
                "external_ref": f"note:{note.id}",
                "details": {
                    "title": note.title,
                    "type": note.type,
                    "linked_appointment_id": note.linked_appointment_id,
                },
            },
            actor_user_id=getattr(user, "id", "user"),
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed in update_note: %s", audit_err)

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

    # Enqueue delete_doc job for search index purge (AU-27)
    delete_job = Job(
        id=str(uuid.uuid4()),
        profile_id=note.profile_id,
        kind="delete_doc",
        payload=json.dumps({
            "document_id": note.id,
            "profile_id": note.profile_id,
        }),
        timezone="UTC",
        next_run_at=datetime.now(timezone.utc),
        idempotency_key=f"delete:note:{note.id}",
        status="pending",
    )
    db.add(delete_job)

    # Audit event before delete
    try:
        from carefold.audit.logger import record_audit
        await record_audit(
            {
                "profile_id": note.profile_id,
                "action": "delete",
                "tool": "api_notes",
                "risk": "write_local",
                "external_ref": f"note:{note.id}",
                "details": {"title": note.title, "slug": note.slug},
            },
            actor_user_id=getattr(user, "id", "user"),
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed in delete_note: %s", audit_err)

    await db.delete(note)
    await db.commit()

    logger.info("note_deleted_from_db", slug=clean_slug)
    return {"deleted": True, "slug": clean_slug}


@router.post("/notes/{slug}/extract", response_model=AfterVisitExtractionResponse)
async def extract_note_by_slug(
    slug: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AfterVisitExtractionResponse:
    """Extracts after-visit clinical entities with citations and disclaimer by slug."""
    clean_slug = _clean_and_validate_slug(slug)
    owner_id = resolve_owner_user_id(user)
    note = await _find_note_for_user(clean_slug, user, owner_id, db, require_manage=False)
    res = extract_after_visit_summary(note.content)
    return AfterVisitExtractionResponse(
        note_id=note.id,
        diagnoses=res.get("diagnoses", []),
        medication_adjustments=res.get("medication_adjustments", []),
        ordered_tests=res.get("ordered_tests", []),
        follow_up_timeline=res.get("follow_up_timeline", []),
        recommended_reminders=res.get("recommended_reminders", []),
        disclaimer=res.get("disclaimer", "Extracted from your notes, not formal medical advice."),
        extracted_items_count=res.get("extracted_items_count", 0),
    )


# ============================================================================
# Profile-Scoped REST Endpoints (AU-35)
# ============================================================================

@router.post(
    "/profiles/{profile_id}/notes",
    response_model=TypedNoteDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_profile_typed_note(
    profile_id: str,
    payload: TypedNoteCreateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TypedNoteDetailResponse:
    """Creates a typed note scoped to a specific profile with category and appointment validation."""
    clean_pid = profile_id.strip()
    prof = await _verify_profile_access(clean_pid, user, db, required_level="manage")
    owner_id = resolve_owner_user_id(user)

    if payload.locale is not None:
        try:
            note_locale = canonicalize_locale(payload.locale, strict=True)
        except ValueError as loc_err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(loc_err),
            ) from loc_err
    else:
        note_locale = getattr(prof, "preferred_locale", None) or DEFAULT_LOCALE

    note_type = validate_note_type(payload.type)
    title_nfc = normalize_text_nfc(payload.title)
    content_nfc = normalize_text_nfc(payload.content)

    linked_appt_id = payload.linked_appointment_id
    if linked_appt_id:
        clean_aid = linked_appt_id.strip()
        appt_stmt = select(Appointment).where(
            Appointment.id == clean_aid,
            Appointment.profile_id == clean_pid,
        )
        appt_res = await db.execute(appt_stmt)
        if appt_res.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security violation: Linked appointment does not exist or does not belong to profile.",
            )

    # Compute slug
    if payload.slug:
        slug = _clean_and_validate_slug(payload.slug)
    else:
        raw_slug = re.sub(r"[^a-zA-Z0-9_\-\s]", "", title_nfc.strip())
        slug = re.sub(r"\s+", "-", raw_slug).lower()[:64] or "note"

    async with _get_note_creation_lock():
        base_slug = slug
        candidate_slug = base_slug
        while True:
            stmt = select(Note.id).where(Note.slug == candidate_slug, Note.profile_id == clean_pid)
            res = await db.execute(stmt)
            if res.scalar_one_or_none() is None:
                break
            ts = int(datetime.now(timezone.utc).timestamp())
            candidate_slug = f"{base_slug[:105]}-{ts}-{uuid.uuid4().hex[:6]}"

        slug = candidate_slug
        now = datetime.now(timezone.utc)
        note_id = str(uuid.uuid4())
        tags_list = payload.tags or []

        new_note = Note(
            id=note_id,
            type=note_type,
            user_id=owner_id,
            profile_id=clean_pid,
            slug=slug,
            title=title_nfc,
            content=content_nfc,
            locale=note_locale,
            tags_json=json.dumps(tags_list),
            linked_appointment_id=linked_appt_id,
            created_at=now,
            updated_at=now,
        )
        db.add(new_note)

        # Enqueue index_doc
        content_hash = hashlib.sha256((new_note.content or "").encode("utf-8")).hexdigest()[:12]
        index_job = Job(
            id=str(uuid.uuid4()),
            profile_id=clean_pid,
            kind="index_doc",
            payload=json.dumps({
                "document_id": new_note.id,
                "profile_id": clean_pid,
                "doc_type": "note",
            }),
            timezone="UTC",
            next_run_at=now,
            idempotency_key=f"index:note:{new_note.id}:{content_hash}",
            status="pending",
        )
        db.add(index_job)

        await db.commit()

        # Audit event
        try:
            from carefold.audit.logger import record_audit
            await record_audit(
                {
                    "profile_id": clean_pid,
                    "action": "create",
                    "tool": "api_notes",
                    "risk": "write_local",
                    "external_ref": f"note:{new_note.id}",
                    "details": {
                        "title": new_note.title,
                        "type": new_note.type,
                        "linked_appointment_id": new_note.linked_appointment_id,
                    },
                },
                actor_user_id=getattr(user, "id", "user"),
                risk="write_local",
            )
        except Exception as audit_err:
            logger.debug("Audit logging failed in create_profile_typed_note: %s", audit_err)

    return _build_typed_note_detail(new_note)


@router.get(
    "/profiles/{profile_id}/notes",
    response_model=TypedNoteListResponse,
)
async def list_profile_typed_notes(
    profile_id: str,
    type: Optional[str] = Query(default=None, description="Optional note category filter"),
    linked_appointment_id: Optional[str] = Query(default=None, description="Optional appointment link filter"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TypedNoteListResponse:
    """Lists typed notes for a profile with filtering by type, linked appointment, and pagination."""
    clean_pid = profile_id.strip()
    await _verify_profile_access(clean_pid, user, db, required_level="view_clinical")

    query = select(Note).where(Note.profile_id == clean_pid)
    count_query = select(func.count(Note.id)).where(Note.profile_id == clean_pid)

    if type is not None:
        clean_type = type.strip().lower()
        query = query.where(Note.type == clean_type)
        count_query = count_query.where(Note.type == clean_type)

    if linked_appointment_id is not None:
        clean_aid = linked_appointment_id.strip()
        query = query.where(Note.linked_appointment_id == clean_aid)
        count_query = count_query.where(Note.linked_appointment_id == clean_aid)

    query = query.order_by(Note.updated_at.desc()).offset(offset).limit(limit)

    total_res = await db.execute(count_query)
    total_count = total_res.scalar_one() or 0

    res = await db.execute(query)
    notes = res.scalars().all()

    return TypedNoteListResponse(
        notes=[_build_typed_note_summary(n) for n in notes],
        total=total_count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/profiles/{profile_id}/notes/{note_id}",
    response_model=TypedNoteDetailResponse,
)
async def get_profile_note_detail(
    profile_id: str,
    note_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TypedNoteDetailResponse:
    """Retrieves full detail of a typed note by ID or slug within a profile."""
    clean_pid = profile_id.strip()
    await _verify_profile_access(clean_pid, user, db, required_level="view_clinical")

    clean_target = note_id.strip()
    stmt = select(Note).where(
        Note.profile_id == clean_pid,
        (Note.id == clean_target) | (Note.slug == clean_target),
    )
    res = await db.execute(stmt)
    note = res.scalar_one_or_none()
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note '{clean_target}' not found in profile '{clean_pid}'.",
        )

    return _build_typed_note_detail(note)


@router.patch(
    "/profiles/{profile_id}/notes/{note_id}",
    response_model=TypedNoteDetailResponse,
)
async def patch_profile_note(
    profile_id: str,
    note_id: str,
    payload: TypedNoteUpdateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TypedNoteDetailResponse:
    """Updates fields of an existing note within a profile."""
    clean_pid = profile_id.strip()
    await _verify_profile_access(clean_pid, user, db, required_level="manage")

    clean_target = note_id.strip()
    stmt = select(Note).where(
        Note.profile_id == clean_pid,
        (Note.id == clean_target) | (Note.slug == clean_target),
    )
    res = await db.execute(stmt)
    note = res.scalar_one_or_none()
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note '{clean_target}' not found in profile '{clean_pid}'.",
        )

    if payload.type is not None:
        try:
            note.type = validate_note_type(payload.type, allow_legacy=True)
        except ValueError as err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))

    if payload.linked_appointment_id is not None:
        clean_aid = payload.linked_appointment_id.strip() or None
        if clean_aid:
            appt_stmt = select(Appointment).where(
                Appointment.id == clean_aid,
                Appointment.profile_id == clean_pid,
            )
            appt_res = await db.execute(appt_stmt)
            if appt_res.scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Security violation: Linked appointment does not exist or does not belong to profile.",
                )
        note.linked_appointment_id = clean_aid

    if payload.locale is not None:
        try:
            note.locale = canonicalize_locale(payload.locale, strict=True)
        except ValueError as loc_err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(loc_err),
            ) from loc_err

    if payload.title is not None:
        note.title = normalize_text_nfc(payload.title)
    if payload.content is not None:
        note.content = normalize_text_nfc(payload.content)
    if payload.tags is not None:
        note.set_tags(payload.tags)

    note.updated_at = datetime.now(timezone.utc)

    # Re-enqueue index_doc
    content_hash = hashlib.sha256((note.content or "").encode("utf-8")).hexdigest()[:12]
    index_job = Job(
        id=str(uuid.uuid4()),
        profile_id=clean_pid,
        kind="index_doc",
        payload=json.dumps({
            "document_id": note.id,
            "profile_id": clean_pid,
            "doc_type": "note",
        }),
        timezone="UTC",
        next_run_at=datetime.now(timezone.utc),
        idempotency_key=f"index:note:{note.id}:{content_hash}",
        status="pending",
    )
    db.add(index_job)

    await db.commit()

    # Audit event
    try:
        from carefold.audit.logger import record_audit
        await record_audit(
            {
                "profile_id": clean_pid,
                "action": "update",
                "tool": "api_notes",
                "risk": "write_local",
                "external_ref": f"note:{note.id}",
                "details": {
                    "title": note.title,
                    "type": note.type,
                    "linked_appointment_id": note.linked_appointment_id,
                },
            },
            actor_user_id=getattr(user, "id", "user"),
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed in patch_profile_note: %s", audit_err)

    return _build_typed_note_detail(note)


@router.delete("/profiles/{profile_id}/notes/{note_id}")
async def delete_profile_note(
    profile_id: str,
    note_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Deletes a note by ID or slug within a profile, queuing search index purge."""
    clean_pid = profile_id.strip()
    await _verify_profile_access(clean_pid, user, db, required_level="manage")

    clean_target = note_id.strip()
    stmt = select(Note).where(
        Note.profile_id == clean_pid,
        (Note.id == clean_target) | (Note.slug == clean_target),
    )
    res = await db.execute(stmt)
    note = res.scalar_one_or_none()
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note '{clean_target}' not found in profile '{clean_pid}'.",
        )

    # Queue delete_doc job
    delete_job = Job(
        id=str(uuid.uuid4()),
        profile_id=clean_pid,
        kind="delete_doc",
        payload=json.dumps({
            "document_id": note.id,
            "profile_id": clean_pid,
        }),
        timezone="UTC",
        next_run_at=datetime.now(timezone.utc),
        idempotency_key=f"delete:note:{note.id}",
        status="pending",
    )
    db.add(delete_job)

    # Audit event before delete
    try:
        from carefold.audit.logger import record_audit
        await record_audit(
            {
                "profile_id": clean_pid,
                "action": "delete",
                "tool": "api_notes",
                "risk": "write_local",
                "external_ref": f"note:{note.id}",
                "details": {"title": note.title, "slug": note.slug},
            },
            actor_user_id=getattr(user, "id", "user"),
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed in delete_profile_note: %s", audit_err)

    await db.delete(note)
    await db.commit()

    return {"deleted": True, "id": note.id, "profile_id": clean_pid}


@router.post(
    "/profiles/{profile_id}/notes/{note_id}/extract",
    response_model=AfterVisitExtractionResponse,
)
async def extract_profile_note(
    profile_id: str,
    note_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AfterVisitExtractionResponse:
    """Extracts after-visit clinical entities with citations and disclaimer from a profile note."""
    clean_pid = profile_id.strip()
    await _verify_profile_access(clean_pid, user, db, required_level="manage")

    clean_target = note_id.strip()
    stmt = select(Note).where(
        Note.profile_id == clean_pid,
        (Note.id == clean_target) | (Note.slug == clean_target),
    )
    res = await db.execute(stmt)
    note = res.scalar_one_or_none()
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note '{clean_target}' not found in profile '{clean_pid}'.",
        )

    res_dict = extract_after_visit_summary(note.content)
    return AfterVisitExtractionResponse(
        note_id=note.id,
        diagnoses=res_dict.get("diagnoses", []),
        medication_adjustments=res_dict.get("medication_adjustments", []),
        ordered_tests=res_dict.get("ordered_tests", []),
        follow_up_timeline=res_dict.get("follow_up_timeline", []),
        recommended_reminders=res_dict.get("recommended_reminders", []),
        disclaimer=res_dict.get("disclaimer", "Extracted from your notes, not formal medical advice."),
        extracted_items_count=res_dict.get("extracted_items_count", 0),
    )


@router.post(
    "/profiles/{profile_id}/notes/extract",
    response_model=AfterVisitExtractionResponse,
)
async def extract_profile_adhoc_note(
    profile_id: str,
    payload: Dict[str, Any],
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AfterVisitExtractionResponse:
    """Ad-hoc extraction from raw text payload for a profile."""
    clean_pid = profile_id.strip()
    await _verify_profile_access(clean_pid, user, db, required_level="manage")

    content = str(payload.get("content", ""))
    res_dict = extract_after_visit_summary(content)
    return AfterVisitExtractionResponse(
        note_id="adhoc",
        diagnoses=res_dict.get("diagnoses", []),
        medication_adjustments=res_dict.get("medication_adjustments", []),
        ordered_tests=res_dict.get("ordered_tests", []),
        follow_up_timeline=res_dict.get("follow_up_timeline", []),
        recommended_reminders=res_dict.get("recommended_reminders", []),
        disclaimer=res_dict.get("disclaimer", "Extracted from your notes, not formal medical advice."),
        extracted_items_count=res_dict.get("extracted_items_count", 0),
    )


__all__ = [
    "create_note",
    "create_profile_typed_note",
    "delete_note",
    "delete_profile_note",
    "extract_note_by_slug",
    "extract_profile_adhoc_note",
    "extract_profile_note",
    "get_note_detail",
    "get_profile_note_detail",
    "get_user_notes_dir",
    "list_notes",
    "list_profile_typed_notes",
    "parse_note_file",
    "patch_profile_note",
    "router",
    "update_note",
]
