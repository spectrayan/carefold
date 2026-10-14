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

"""Clinical consultation visit preparation pack REST endpoints (AU-33, AU-34)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, resolve_owner_user_id
from carefold.api.profiles import get_user_profile_access
from carefold.auth.ports import UserProfile
from carefold.clinical.prep_pack import generate_and_persist_prep_pack
from carefold.db.models import Appointment, Note, Profile
from carefold.db.session import get_db

logger = logging.getLogger("carefold.api.prep_pack")

router = APIRouter(tags=["PrepPack"])


class PrepPackGenerateRequest(BaseModel):
    """Request payload for compiling a clinical visit prep pack."""

    appointment_id: Optional[str] = Field(default=None, description="Linked appointment UUID")
    specialty: Optional[str] = Field(default=None, description="Medical specialty (e.g. Cardiology)")
    visit_reason: Optional[str] = Field(default=None, description="Chief complaint or purpose of visit")
    doctor_questions: Optional[List[str]] = Field(default=None, description="Prioritized questions list (max 5)")


class PrepPackResponse(BaseModel):
    """Response model for a compiled clinical prep pack."""

    note_id: str
    appointment_id: Optional[str] = None
    profile_id: str
    title: str
    markdown: str
    questions_count: int
    has_vitals_summary: bool
    printable_html_ready: bool = True
    undo_reference: Optional[str] = None
    status: str = "compiled"


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
            detail="profile_id must be a non-empty string.",
        )

    stmt = select(Profile).where(Profile.id == clean_id)
    res = await db.execute(stmt)
    prof = res.scalar_one_or_none()
    if prof is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{clean_id}' not found.",
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
            detail="Access denied: clinical view permissions required to inspect clinical prep packs.",
        )

    if required_level == "manage" and access != "manage":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: management permissions required to generate prep packs for this profile.",
        )

    return prof


@router.post(
    "/profiles/{profile_id}/prep-pack",
    response_model=PrepPackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_prep_pack_endpoint(
    profile_id: str,
    payload: PrepPackGenerateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PrepPackResponse:
    """Compiles a clinical visit prep pack, persists as a visit Note, and enqueues indexing."""
    await _verify_profile_access(profile_id, user, db, required_level="manage")
    owner_id = resolve_owner_user_id(user)

    try:
        res = await generate_and_persist_prep_pack(
            session=db,
            profile_id=profile_id.strip(),
            appointment_id=payload.appointment_id,
            specialty=payload.specialty,
            visit_reason=payload.visit_reason,
            doctor_questions=payload.doctor_questions,
            user_id=owner_id or getattr(user, "id", None),
        )
        return PrepPackResponse(
            note_id=res["note_id"],
            appointment_id=res.get("appointment_id"),
            profile_id=res["profile_id"],
            title=res["title"],
            markdown=res["markdown"],
            questions_count=res["questions_count"],
            has_vitals_summary=res["has_vitals_summary"],
            printable_html_ready=res.get("printable_html_ready", True),
            undo_reference=res.get("undo_reference"),
            status="compiled",
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )
    except Exception as exc:
        logger.exception("Failed to generate prep pack: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate prep pack: {exc}",
        )


@router.get(
    "/profiles/{profile_id}/prep-pack/{appointment_id}",
    response_model=PrepPackResponse,
)
async def get_prep_pack_for_appointment(
    profile_id: str,
    appointment_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PrepPackResponse:
    """Retrieves the generated prep pack note associated with an appointment."""
    await _verify_profile_access(profile_id, user, db, required_level="view_clinical")
    clean_pid = profile_id.strip()
    clean_aid = appointment_id.strip()

    # Verify appointment exists and belongs to profile
    appt_stmt = select(Appointment).where(
        Appointment.id == clean_aid,
        Appointment.profile_id == clean_pid,
    )
    appt_res = await db.execute(appt_stmt)
    if appt_res.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment '{clean_aid}' not found for profile '{clean_pid}'.",
        )

    # Find most recent visit note linked to this appointment
    note_stmt = select(Note).where(
        Note.profile_id == clean_pid,
        Note.linked_appointment_id == clean_aid,
        Note.type == "visit",
    ).order_by(Note.updated_at.desc()).limit(1)

    note_res = await db.execute(note_stmt)
    note = note_res.scalar_one_or_none()
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No preparation pack found for appointment '{clean_aid}'.",
        )

    return PrepPackResponse(
        note_id=note.id,
        appointment_id=note.linked_appointment_id,
        profile_id=note.profile_id,
        title=note.title,
        markdown=note.content,
        questions_count=0,
        has_vitals_summary=False,
        printable_html_ready=True,
        undo_reference=f"note:{note.id}",
        status="compiled",
    )


__all__ = [
    "PrepPackGenerateRequest",
    "PrepPackResponse",
    "generate_prep_pack_endpoint",
    "get_prep_pack_for_appointment",
    "router",
]
