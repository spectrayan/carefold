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

"""Attachments management, upload, download streaming, and deletion REST endpoints.

Decouples physical storage through hexagonal StoragePort and persists document
records, storage keys, and cryptographic SHA-256 hashes in carefold.db.
"""

from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, resolve_owner_user_id
from carefold.api.profiles import get_user_profile_access
from carefold.auth.ports import UserProfile
from carefold.config import settings
from carefold.constants.api import (
    HTTP_400_BAD_REQUEST,
    ROUTE_ATTACHMENTS,
)
from carefold.db.models import Attachment, Job, Profile, ProfileAccess
from carefold.db.session import get_db
from carefold.logging import get_logger
from carefold.storage.cas import get_cas_path, read_cas_file, store_cas_file
from carefold.storage.factory import get_storage_adapter
from carefold.storage.ports import StorageFile, StorageFileMetadata, StoragePort
from carefold.tools.attach_read import extract_text_from_pdf_bytes

logger = get_logger("carefold.api.attachments")

router = APIRouter(tags=["Attachments"])

ALLOWED_EXTENSIONS: set[str] = {
    ".txt",
    ".pdf",
    ".md",
    ".json",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
}
MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10 MB


def _sanitize_filename(name: str) -> str:
    """Sanitizes filename removing directory traversal and dangerous characters."""
    base = os.path.basename(name)
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", base)
    return sanitized if sanitized not in (".", "..", "") else "unnamed_attachment.txt"


def get_user_attachments_dir(owner_id: Optional[str], profile_id: Optional[str] = None) -> Path:
    """Legacy helper returning directory for user- and profile-scoped attachments."""
    base_dir = settings.get_uploads_dir()
    if not owner_id:
        target_dir = (base_dir / profile_id) if profile_id else base_dir
    else:
        target_dir = (base_dir / owner_id / profile_id) if profile_id else (base_dir / owner_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


# ============================================================================
# 1. POST /attachments (Upload Endpoint)
# ============================================================================

@router.post(ROUTE_ATTACHMENTS, status_code=status.HTTP_201_CREATED)
@router.post("/attachments/upload", status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def upload_attachment(
    file: UploadFile = File(...),
    profile_id: Optional[str] = Query(None, description="Optional profile ID to associate with attachment"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: StoragePort = Depends(get_storage_adapter),
) -> Dict[str, Any]:
    """Uploads a document via StoragePort, recording metadata and SHA-256 hash in carefold.db."""
    if not file or not file.filename:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="No file uploaded or missing filename.",
        )

    # 1. Validate file extension
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Allowed formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )

    owner_id = resolve_owner_user_id(user)

    # 2. Enforce profile scoping & access permissions
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
                detail="Access denied: no permission for target profile.",
            )
        # Uploading attachments requires management/self/guardian access
        if access not in ("manage", "self", "guardian") and getattr(user, "role", "member") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: manage permissions required to upload attachments for this profile.",
            )

    # 3. Read and validate file size
    content = await file.read()
    file_size = len(content)

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds maximum limit of 10MB ({(file_size / (1024 * 1024)):.2f}MB).",
        )

    sanitized_name = _sanitize_filename(file.filename)

    # 4. Save file through Content-Addressed Storage (CAS) layout and StoragePort
    cas_path, cas_sha256, is_dedup = store_cas_file(
        content=content,
        carefold_home=settings.home_dir,
        user_id=owner_id,
        profile_id=profile_id,
    )

    try:
        meta: StorageFileMetadata = await storage.save_file(
            content=content,
            filename=sanitized_name,
            user_id=owner_id,
            profile_id=profile_id,
            content_type=file.content_type or "application/octet-stream",
        )
    except Exception as storage_err:
        logger.error("storage_save_failed", filename=sanitized_name, error=str(storage_err))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save attachment to storage: {storage_err}",
        )

    # 5. Determine extraction status and enqueue background extraction if applicable
    extractable_extensions = {
        ".txt", ".text", ".log", ".rst", ".md", ".markdown", ".json",
        ".csv", ".tsv", ".yaml", ".yml", ".html", ".htm", ".xml",
        ".pdf",
        ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp",
    }
    extracted_text: Optional[str] = None
    extraction_status = "not_applicable"

    if ext in extractable_extensions:
        extraction_status = "pending"
        if ext in (".txt", ".md", ".json", ".csv", ".tsv", ".yaml", ".yml", ".text", ".log", ".rst", ".html", ".htm", ".xml"):
            extracted_text = content.decode("utf-8", errors="replace")

    # 6. Persist Attachment entity in relational database (carefold.db)
    now = meta.created_at or datetime.now(timezone.utc)
    attachment_id = str(uuid.uuid4())

    try:
        attachment_record = Attachment(
            id=attachment_id,
            user_id=owner_id,
            profile_id=profile_id,
            storage_key=meta.storage_key,
            filename=meta.filename,
            original_name=sanitized_name,
            content_type=meta.mime_type or file.content_type or "application/octet-stream",
            size_bytes=meta.byte_size,
            sha256_hash=meta.sha256_hash or cas_sha256,
            extracted_text=None,
            source="upload",
            source_ref=None,
            extraction_status=extraction_status,
            created_at=now,
            updated_at=now,
        )
        db.add(attachment_record)

        # Enqueue background extract_text job for extractable documents
        if extraction_status == "pending":
            job_profile_id = profile_id
            if not job_profile_id and owner_id:
                try:
                    p_stmt = select(Profile.id).where(Profile.user_id == owner_id).limit(1)
                    p_res = await db.execute(p_stmt)
                    job_profile_id = p_res.scalar_one_or_none()
                except Exception:
                    pass
            if not job_profile_id:
                try:
                    p_stmt = select(Profile.id).limit(1)
                    p_res = await db.execute(p_stmt)
                    job_profile_id = p_res.scalar_one_or_none()
                except Exception:
                    pass

            if job_profile_id:
                valid_stmt = select(Profile.id).where(Profile.id == job_profile_id)
                valid_res = await db.execute(valid_stmt)
                if valid_res.scalar_one_or_none() is not None:
                    extract_payload = {
                        "attachment_id": attachment_id,
                        "user_id": owner_id,
                        "profile_id": job_profile_id,
                        "sha256": meta.sha256_hash or cas_sha256,
                        "filename": meta.filename,
                        "content_type": meta.mime_type or file.content_type,
                    }
                    extract_job = Job(
                        id=str(uuid.uuid4()),
                        profile_id=job_profile_id,
                        kind="extract_text",
                        payload=json.dumps(extract_payload),
                        timezone="UTC",
                        next_run_at=now,
                        idempotency_key=f"extract:{attachment_id}:{meta.sha256_hash or cas_sha256}",
                        status="pending",
                    )
                    db.add(extract_job)

        await db.commit()
    except Exception as db_err:
        await db.rollback()
        logger.warning("db_record_attachment_failed", filename=meta.filename, error=str(db_err))

    # Construct backward-compatible relative path for clients and test suites
    if owner_id and profile_id:
        rel_path = f"attachments/{owner_id}/{profile_id}/{meta.filename}"
    elif owner_id:
        rel_path = f"attachments/{owner_id}/{meta.filename}"
    elif profile_id:
        rel_path = f"attachments/{profile_id}/{meta.filename}"
    else:
        rel_path = f"attachments/{meta.filename}"

    renamed = meta.filename != sanitized_name
    timestamp = now.isoformat()

    logger.info(
        "attachment_uploaded",
        id=attachment_id,
        filename=meta.filename,
        original_filename=sanitized_name,
        renamed=renamed,
        size_bytes=meta.byte_size,
        storage_key=meta.storage_key,
        sha256_hash=meta.sha256_hash or cas_sha256,
        profile_id=profile_id,
        is_deduplicated=is_dedup,
    )

    return {
        "success": True,
        "id": attachment_id,
        "filename": meta.filename,
        "original_name": sanitized_name,
        "storage_key": meta.storage_key,
        "path": rel_path,
        "user_id": owner_id,
        "profile_id": profile_id,
        "size": meta.byte_size,
        "type": meta.mime_type or file.content_type or "application/octet-stream",
        "mime": meta.mime_type or file.content_type or "application/octet-stream",
        "sha256": meta.sha256_hash or cas_sha256,
        "sha256_hash": meta.sha256_hash or cas_sha256,
        "timestamp": timestamp,
        "renamed": renamed,
        "extracted_text": extracted_text,
        "source": "upload",
        "extraction_status": extraction_status,
        "is_deduplicated": is_dedup,
    }


# ============================================================================
# 2. GET /attachments (List Endpoint)
# ============================================================================

@router.get(ROUTE_ATTACHMENTS)
async def list_attachments(
    profile_id: Optional[str] = Query(None, description="Optional profile ID filter"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: StoragePort = Depends(get_storage_adapter),
) -> List[Dict[str, Any]]:
    """Lists attachments scoped to user and profile, reconciling DB records with storage."""
    owner_id = resolve_owner_user_id(user)
    effective_user_id = user.id if user else None
    is_admin = getattr(user, "role", "member") == "admin"

    # Enforce profile authorization filter
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
                detail="Access denied: no permission for target profile.",
            )
        stmt = select(Attachment).where(Attachment.profile_id == profile_id).order_by(Attachment.created_at.desc())
    else:
        if is_admin or owner_id is None:
            # Admin or offline desktop single-user mode sees all attachments
            stmt = select(Attachment).order_by(Attachment.created_at.desc())
        else:
            # Multi-tenant: user sees attachments they own, or attachments belonging to profiles they have access to
            accessible_profiles_stmt = (
                select(Profile.id)
                .outerjoin(ProfileAccess, Profile.id == ProfileAccess.profile_id)
                .where(
                    (Profile.user_id == owner_id)
                    | (
                        (ProfileAccess.user_id == effective_user_id)
                        & ProfileAccess.access_level.in_(("manage", "view_clinical", "view_paperwork"))
                    )
                )
                .distinct()
            )
            acc_res = await db.execute(accessible_profiles_stmt)
            acc_profile_ids = list(acc_res.scalars().all())

            stmt = select(Attachment).where(
                (
                    (Attachment.user_id == owner_id)
                    & (Attachment.profile_id.is_(None))
                )
                | (Attachment.profile_id.in_(acc_profile_ids))
            ).order_by(Attachment.created_at.desc())

    results: List[Dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    try:
        res = await db.execute(stmt)
        for att in res.scalars().all():
            dedup_key = (att.profile_id or "", att.filename, att.sha256_hash or "")
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            if att.user_id and att.profile_id:
                rel = f"attachments/{att.user_id}/{att.profile_id}/{att.filename}"
            elif att.user_id:
                rel = f"attachments/{att.user_id}/{att.filename}"
            elif att.profile_id:
                rel = f"attachments/{att.profile_id}/{att.filename}"
            else:
                rel = f"attachments/{att.filename}"

            results.append({
                "id": att.id,
                "filename": att.filename,
                "original_name": att.original_name,
                "storage_key": att.storage_key or rel,
                "path": rel,
                "profile_id": att.profile_id,
                "size": att.size_bytes,
                "type": att.content_type,
                "sha256_hash": att.sha256_hash,
                "extracted_text": att.extracted_text,
                "source": att.source,
                "source_ref": att.source_ref,
                "extraction_status": att.extraction_status,
                "timestamp": att.created_at.isoformat() if att.created_at else datetime.now(timezone.utc).isoformat(),
                "download_url": f"/api/v1/attachments/{att.id}/download",
            })
    except Exception as db_err:
        await db.rollback()
        logger.warning("db_list_attachments_failed", error=str(db_err))

    results.sort(key=lambda x: x["timestamp"], reverse=True)
    return results


# ============================================================================
# 3. GET /attachments/{attachment_id}/download & /content (Download Endpoint)
# ============================================================================

@router.get("/attachments/{attachment_id}/download")
@router.get("/attachments/{attachment_id}/content", include_in_schema=False)
async def download_attachment(
    attachment_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: StoragePort = Depends(get_storage_adapter),
) -> StreamingResponse:
    """Streams attachment file content from StoragePort with security authorization checks."""
    owner_id = resolve_owner_user_id(user)
    is_admin = getattr(user, "role", "member") == "admin"

    # 1. Lookup attachment in carefold.db by id, storage_key, or filename
    stmt = select(Attachment).where(
        (Attachment.id == attachment_id)
        | (Attachment.storage_key == attachment_id)
        | (Attachment.filename == attachment_id)
    )
    res = await db.execute(stmt)
    att = res.scalar_one_or_none()

    # 2. Authorize caller access & resolve physical file
    if att is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attachment '{attachment_id}' not found.",
        )

    if att.profile_id is not None:
        p_stmt = select(Profile).where(Profile.id == att.profile_id)
        p_res = await db.execute(p_stmt)
        prof = p_res.scalar_one_or_none()
        if prof is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found.",
            )
        access = await get_user_profile_access(prof, user, db)
        if access is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: no permission for attachment profile.",
            )
    elif owner_id and not is_admin:
        if att.user_id is not None and att.user_id != owner_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: attachment belongs to another user.",
            )

    target_storage_key = att.storage_key or att.filename
    target_user_id = att.user_id
    target_profile_id = att.profile_id
    content_type = att.content_type or "application/octet-stream"
    filename = att.original_name or att.filename

    # 3. Retrieve file: First check Content-Addressed Storage (CAS) layout
    content_bytes: Optional[bytes] = None
    stored_file: Optional[StorageFile] = None

    if att.sha256_hash:
        try:
            content_bytes = read_cas_file(
                carefold_home=settings.home_dir,
                user_id=att.user_id,
                profile_id=att.profile_id,
                sha256_hash=att.sha256_hash,
            )
        except (FileNotFoundError, ValueError):
            content_bytes = None

    if content_bytes is None:
        # Fallback to Hexagonal StoragePort
        stored_file = await storage.get_file(
            target_storage_key,
            user_id=target_user_id,
            profile_id=target_profile_id,
        )

        if stored_file is None:
            # Retry with base filename if storage_key had a path prefix
            if "/" in target_storage_key or "\\" in target_storage_key:
                stored_file = await storage.get_file(
                    os.path.basename(target_storage_key),
                    user_id=target_user_id,
                    profile_id=target_profile_id,
                )

        if stored_file is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Attachment '{attachment_id}' not found in storage.",
            )

        content_bytes = stored_file.content
        resolved_mime = stored_file.metadata.mime_type or content_type
    else:
        resolved_mime = content_type

    content_length = len(content_bytes)
    safe_filename = _sanitize_filename(filename)
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_filename}"',
        "Content-Length": str(content_length),
        "X-Content-Type-Options": "nosniff",
    }
    etag_hash = getattr(att, "sha256_hash", None) or (
        stored_file.metadata.sha256_hash if (stored_file and getattr(stored_file, "metadata", None)) else None
    )
    if etag_hash:
        headers["ETag"] = f'"{etag_hash}"'

    return StreamingResponse(
        io.BytesIO(content_bytes),
        media_type=resolved_mime,
        headers=headers,
    )


# ============================================================================
# 4. DELETE /attachments/{attachment_id} (Delete Endpoint)
# ============================================================================

@router.delete("/attachments/{attachment_id}")
async def delete_attachment(
    attachment_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: StoragePort = Depends(get_storage_adapter),
) -> Dict[str, Any]:
    """Deletes attachment file from StoragePort and removes record from carefold.db."""
    owner_id = resolve_owner_user_id(user)
    is_admin = getattr(user, "role", "member") == "admin"

    # 1. Lookup attachment in carefold.db
    stmt = select(Attachment).where(
        (Attachment.id == attachment_id)
        | (Attachment.storage_key == attachment_id)
        | (Attachment.filename == attachment_id)
    )
    res = await db.execute(stmt)
    att = res.scalar_one_or_none()

    if att is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attachment '{attachment_id}' not found.",
        )

    # 2. Authorize deletion (requires management privileges or account ownership)
    if att.profile_id is not None:
        p_stmt = select(Profile).where(Profile.id == att.profile_id)
        p_res = await db.execute(p_stmt)
        prof = p_res.scalar_one_or_none()
        if prof is not None:
            access = await get_user_profile_access(prof, user, db)
            if access not in ("manage", "self", "guardian") and not is_admin:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: manage permissions required to delete attachment for this profile.",
                )
    elif owner_id and not is_admin:
        if att.user_id is not None and att.user_id != owner_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: attachment belongs to another user.",
            )

    # 3. Delete file from StoragePort and CAS
    storage_key_to_delete = att.storage_key or att.filename
    try:
        await storage.delete_file(
            storage_key_to_delete,
            user_id=att.user_id,
            profile_id=att.profile_id,
        )
    except Exception as storage_err:
        logger.warning(
            "storage_delete_failed_proceeding_with_db",
            storage_key=storage_key_to_delete,
            error=str(storage_err),
        )

    if att.sha256_hash:
        try:
            # Reference count check: only unlink if no other Attachment record shares this physical CAS file
            ref_conditions = [
                Attachment.id != att.id,
                Attachment.sha256_hash == att.sha256_hash,
            ]
            if att.user_id is not None:
                ref_conditions.append(Attachment.user_id == att.user_id)
            else:
                ref_conditions.append(Attachment.user_id.is_(None))

            if att.profile_id is not None:
                ref_conditions.append(Attachment.profile_id == att.profile_id)
            else:
                ref_conditions.append(Attachment.profile_id.is_(None))

            other_ref_stmt = select(Attachment.id).where(*ref_conditions).limit(1)
            other_ref_res = await db.execute(other_ref_stmt)
            has_shared_references = other_ref_res.scalar_one_or_none() is not None

            if not has_shared_references:
                cas_file = get_cas_path(
                    settings.home_dir,
                    att.user_id,
                    att.profile_id,
                    att.sha256_hash,
                )
                if cas_file.is_file():
                    cas_file.unlink()
            else:
                logger.debug(
                    "cas_delete_retained_for_shared_reference",
                    sha256=att.sha256_hash[:8],
                    retained_profile=att.profile_id,
                )
        except Exception as cas_del_err:
            logger.debug("cas_delete_skipped", error=str(cas_del_err))

    # 4. Remove record from carefold.db
    if att.profile_id is not None:
        delete_job = Job(
            id=str(uuid.uuid4()),
            profile_id=att.profile_id,
            kind="delete_doc",
            payload=json.dumps({
                "document_id": att.id,
                "profile_id": att.profile_id,
            }),
            timezone="UTC",
            next_run_at=datetime.now(timezone.utc),
            idempotency_key=f"delete:attachment:{att.id}",
            status="pending",
        )
        db.add(delete_job)

    deleted_id = att.id
    deleted_filename = att.filename
    await db.delete(att)
    await db.commit()

    logger.info("attachment_deleted", id=deleted_id, filename=deleted_filename)

    return {
        "success": True,
        "deleted": True,
        "id": deleted_id,
        "filename": deleted_filename,
    }


__all__ = [
    "router",
    "upload_attachment",
    "list_attachments",
    "download_attachment",
    "delete_attachment",
    "get_user_attachments_dir",
]
