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

"""REST API endpoints for Family Profiles, Access Governance, and Clinical Consent."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from carefold.api.deps import get_current_user, resolve_owner_user_id
from carefold.auth.ports import UserProfile
from carefold.db.models import Profile, ProfileAccess, ProfileConsent, User, ViewerInvite
from carefold.db.session import get_db
from carefold.logging import get_logger
from carefold.schemas.profiles import (
    AccessLevel,
    ProfileAccessGrant,
    ProfileAccessResponse,
    ProfileConsentResponse,
    ProfileConsentUpdate,
    ProfileCreate,
    ProfileDetailResponse,
    ProfileSummaryResponse,
    ProfileUpdate,
    ViewerInviteAcceptRequest,
    ViewerInviteAcceptResponse,
    ViewerInviteCreate,
    ViewerInviteResponse,
)

logger = get_logger("carefold.api.profiles")

router = APIRouter()


async def get_user_profile_access(
    profile: Profile,
    user: UserProfile,
    db: AsyncSession,
) -> Optional[AccessLevel]:
    """Determines user's access level ('manage', 'view_clinical', 'view_paperwork') for a profile."""
    # 1. System administrators always have full management access
    if getattr(user, "role", "member") == "admin":
        return "manage"

    owner_id = resolve_owner_user_id(user)

    # 2. Offline / single-user mode bypass
    if owner_id is None:
        if profile.user_id is None or profile.user_id == user.id:
            return "manage"

    # 3. Direct account ownership
    if profile.user_id is not None and profile.user_id == owner_id:
        return "manage"

    # 4. Check explicit access grants in profile_access
    effective_user_id = owner_id or user.id
    stmt = select(ProfileAccess).where(
        ProfileAccess.profile_id == profile.id,
        ProfileAccess.user_id == effective_user_id,
    )
    res = await db.execute(stmt)
    grant = res.scalar_one_or_none()
    if grant is not None:
        return grant.access_level  # type: ignore[return-value]

    return None


async def auto_provision_primary_me_profile(
    user: UserProfile,
    db: AsyncSession,
) -> Profile:
    """Idempotently provisions default primary 'Me' profile for a user with manage access and default consent."""
    owner_id = resolve_owner_user_id(user)

    # Check if a primary profile already exists
    stmt = select(Profile).where(Profile.is_primary.is_(True))
    if owner_id:
        stmt = stmt.where(Profile.user_id == owner_id)
    else:
        stmt = stmt.where(Profile.user_id.is_(None))

    profile_name = (user.full_name or user.username or "Me").strip() or "Me"

    res = await db.execute(stmt)
    existing = res.scalar_one_or_none()
    if existing is not None:
        if existing.name == "Me" and profile_name != "Me":
            existing.name = profile_name
            await db.commit()
            await db.refresh(existing)
        return existing

    # Create primary profile with user name
    profile_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    new_profile = Profile(
        id=profile_id,
        user_id=owner_id,
        name=profile_name,
        relationship="self",
        role="self",
        avatar_color="1",
        is_primary=True,
        created_at=now,
        updated_at=now,
    )
    db.add(new_profile)

    # Add manage access grant
    access_grant = ProfileAccess(
        profile_id=profile_id,
        user_id=owner_id or user.id,
        granted_by=owner_id or user.id,
        access_level="manage",
        granted_at=now,
    )
    db.add(access_grant)

    # Add default clinical consent
    consent = ProfileConsent(
        profile_id=profile_id,
        allow_clinical=False,
        terms_version="v1.0",
        consented_at=None,
        teen_handover_notified=False,
        created_at=now,
        updated_at=now,
    )
    db.add(consent)

    await db.commit()
    await db.refresh(new_profile)
    logger.info("auto_provisioned_me_profile", profile_id=profile_id, user_id=owner_id)
    return new_profile


@router.get("", response_model=List[ProfileSummaryResponse])
@router.get("/", response_model=List[ProfileSummaryResponse], include_in_schema=False)
async def list_profiles(
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ProfileSummaryResponse]:
    """Lists all family / care profiles owned by or shared with the authenticated user."""
    owner_id = resolve_owner_user_id(user)
    effective_user_id = owner_id or user.id

    # 1. Fetch directly owned profiles
    stmt = select(Profile).order_by(Profile.is_primary.desc(), Profile.created_at.asc())
    if owner_id:
        stmt = stmt.where(Profile.user_id == owner_id)
    else:
        stmt = stmt.where(Profile.user_id.is_(None))

    res = await db.execute(stmt)
    owned_profiles = list(res.scalars().all())

    # If user has zero profiles, auto-provision default "Me" profile
    if len(owned_profiles) == 0:
        me_profile = await auto_provision_primary_me_profile(user, db)
        owned_profiles = [me_profile]

    profiles_map: Dict[str, tuple[Profile, AccessLevel]] = {
        p.id: (p, "manage") for p in owned_profiles
    }

    # 2. Fetch profiles shared with user via ProfileAccess (if distinct)
    if owner_id or user.id:
        shared_stmt = (
            select(Profile, ProfileAccess.access_level)
            .join(ProfileAccess, Profile.id == ProfileAccess.profile_id)
            .where(ProfileAccess.user_id == effective_user_id)
        )
        shared_res = await db.execute(shared_stmt)
        for p, access_level in shared_res.all():
            if p.id not in profiles_map:
                profiles_map[p.id] = (p, access_level)

    summaries: List[ProfileSummaryResponse] = []
    for p, access_level in profiles_map.values():
        summaries.append(
            ProfileSummaryResponse(
                id=p.id,
                user_id=p.user_id or effective_user_id,
                name=p.name,
                short_name=p.short_name,
                relationship=p.relationship,
                role=p.role,
                date_of_birth=p.date_of_birth,
                avatar_color=p.avatar_color,
                avatar_url=p.avatar_url,
                is_primary=p.is_primary,
                access_level=access_level,
                created_at=p.created_at.isoformat() if p.created_at else datetime.now(timezone.utc).isoformat(),
                updated_at=p.updated_at.isoformat() if p.updated_at else datetime.now(timezone.utc).isoformat(),
            )
        )

    # Sort so primary profile is first, followed by creation date
    summaries.sort(key=lambda x: (not x.is_primary, x.created_at))
    return summaries


@router.post("", response_model=ProfileDetailResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=ProfileDetailResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_profile(
    payload: ProfileCreate,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileDetailResponse:
    """Creates a new care profile in the user's household with manage access and default consent."""
    owner_id = resolve_owner_user_id(user)
    effective_user_id = owner_id or user.id
    now = datetime.now(timezone.utc)

    # Check if this should be marked primary (only if user has no primary profile)
    check_stmt = select(Profile).where(Profile.is_primary.is_(True))
    if owner_id:
        check_stmt = check_stmt.where(Profile.user_id == owner_id)
    else:
        check_stmt = check_stmt.where(Profile.user_id.is_(None))
    res = await db.execute(check_stmt)
    has_primary = res.scalar_one_or_none() is not None

    new_profile = Profile(
        id=str(uuid.uuid4()),
        user_id=owner_id,
        name=payload.name.strip(),
        short_name=payload.short_name.strip() if payload.short_name else None,
        relationship=payload.relationship.strip().lower(),
        role=payload.role,
        date_of_birth=payload.date_of_birth,
        avatar_color=payload.avatar_color,
        avatar_url=payload.avatar_url.strip() if payload.avatar_url else None,
        is_primary=not has_primary,
        created_at=now,
        updated_at=now,
    )
    db.add(new_profile)

    access_grant = ProfileAccess(
        profile_id=new_profile.id,
        user_id=effective_user_id,
        granted_by=effective_user_id,
        access_level="manage",
        granted_at=now,
    )
    db.add(access_grant)

    consent = ProfileConsent(
        profile_id=new_profile.id,
        allow_clinical=False,
        terms_version="v1.0",
        consented_at=None,
        teen_handover_notified=False,
        created_at=now,
        updated_at=now,
    )
    db.add(consent)

    await db.commit()
    await db.refresh(new_profile)

    return ProfileDetailResponse(
        id=new_profile.id,
        user_id=new_profile.user_id or effective_user_id,
        name=new_profile.name,
        short_name=new_profile.short_name,
        relationship=new_profile.relationship,
        role=new_profile.role,
        date_of_birth=new_profile.date_of_birth,
        avatar_color=new_profile.avatar_color,
        avatar_url=new_profile.avatar_url,
        is_primary=new_profile.is_primary,
        access_level="manage",
        consent=ProfileConsentResponse(
            id=consent.id,
            profile_id=consent.profile_id,
            allow_clinical=consent.allow_clinical,
            terms_version=consent.terms_version,
            consented_at=consent.consented_at.isoformat() if consent.consented_at else None,
            teen_handover_notified=consent.teen_handover_notified,
        ),
        access_grants=[
            ProfileAccessResponse(
                id=access_grant.id,
                profile_id=access_grant.profile_id,
                user_id=access_grant.user_id or effective_user_id,
                granted_by=access_grant.granted_by,
                access_level="manage",
                granted_at=access_grant.granted_at.isoformat(),
            )
        ],
        created_at=new_profile.created_at.isoformat(),
        updated_at=new_profile.updated_at.isoformat(),
    )


@router.post("/invites/accept", response_model=ViewerInviteAcceptResponse)
async def accept_viewer_invite(
    payload: ViewerInviteAcceptRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ViewerInviteAcceptResponse:
    """Accepts a viewer invitation code, validating expiration and creating ProfileAccess with role='viewer'."""
    clean_code = payload.invite_code.strip()
    stmt = select(ViewerInvite).where(ViewerInvite.invite_code == clean_code)
    res = await db.execute(stmt)
    invite = res.scalar_one_or_none()

    if invite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid invitation code.",
        )
    if invite.accepted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation has already been accepted.",
        )
    now = datetime.now(timezone.utc)
    exp = invite.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation code has expired.",
        )

    # Fetch referenced profile
    p_stmt = select(Profile).where(Profile.id == invite.profile_id)
    p_res = await db.execute(p_stmt)
    profile = p_res.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target profile no longer exists.",
        )

    owner_id = resolve_owner_user_id(user)
    effective_user_id = owner_id or user.id
    if profile.user_id is not None and profile.user_id == effective_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are already the owner of this profile.",
        )

    # Determine access level from invite permissions
    access_level = "view_clinical" if invite.view_clinical else ("view_paperwork" if invite.view_paperwork else "view_clinical")

    # Upsert ProfileAccess record
    acc_stmt = select(ProfileAccess).where(
        ProfileAccess.profile_id == profile.id,
        ProfileAccess.user_id == effective_user_id,
    )
    acc_res = await db.execute(acc_stmt)
    access_record = acc_res.scalar_one_or_none()

    if access_record is None:
        access_record = ProfileAccess(
            id=str(uuid.uuid4()),
            profile_id=profile.id,
            user_id=effective_user_id,
            granted_by=invite.invited_by,
            role="viewer",
            access_level=access_level,
            granted_at=now,
        )
        db.add(access_record)
    else:
        access_record.role = "viewer"
        access_record.access_level = access_level
        access_record.granted_at = now

    invite.accepted_at = now
    invite.accepted_by = effective_user_id
    invite.updated_at = now

    await db.commit()
    await db.refresh(access_record)

    logger.info(
        "viewer_invite_accepted",
        invite_code=clean_code,
        profile_id=profile.id,
        user_id=effective_user_id,
        access_level=access_level,
    )

    return ViewerInviteAcceptResponse(
        success=True,
        message="Invitation accepted successfully",
        profile_id=profile.id,
        profile_name=profile.name,
        role="viewer",
        access_level=access_level,
        access_id=access_record.id,
    )


@router.get("/{profile_id}/invites", response_model=List[ViewerInviteResponse])
async def list_viewer_invites(
    profile_id: str,
    include_expired: bool = False,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ViewerInviteResponse]:
    """Lists active viewer invitations for the profile (requires 'manage' access)."""
    if profile_id.lower() == "me":
        profile = await auto_provision_primary_me_profile(user, db)
    else:
        stmt = select(Profile).where(Profile.id == profile_id)
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' not found.",
        )

    access = await get_user_profile_access(profile, user, db)
    if access != "manage":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: management privileges required to list invitations.",
        )

    stmt = select(ViewerInvite).where(ViewerInvite.profile_id == profile.id)
    if not include_expired:
        now = datetime.now(timezone.utc)
        stmt = stmt.where(
            ViewerInvite.accepted_at.is_(None),
            ViewerInvite.expires_at > now,
        )
    stmt = stmt.order_by(ViewerInvite.created_at.desc())

    res = await db.execute(stmt)
    invites = res.scalars().all()

    return [
        ViewerInviteResponse(
            id=inv.id,
            invite_code=inv.invite_code,
            profile_id=inv.profile_id,
            invited_by=inv.invited_by,
            invitee_name=inv.invitee_name,
            role=inv.role,
            view_clinical=inv.view_clinical,
            view_paperwork=inv.view_paperwork,
            expires_at=inv.expires_at.isoformat(),
            accepted_at=inv.accepted_at.isoformat() if inv.accepted_at else None,
            accepted_by=inv.accepted_by,
            created_at=inv.created_at.isoformat(),
        )
        for inv in invites
    ]


@router.post("/{profile_id}/invites", response_model=ViewerInviteResponse, status_code=status.HTTP_201_CREATED)
async def create_viewer_invite(
    profile_id: str,
    payload: ViewerInviteCreate,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ViewerInviteResponse:
    """Creates a cryptographically secure viewer invite with 7-day expiration (requires 'manage' access)."""
    if profile_id.lower() == "me":
        profile = await auto_provision_primary_me_profile(user, db)
    else:
        stmt = select(Profile).where(Profile.id == profile_id)
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' not found.",
        )

    access = await get_user_profile_access(profile, user, db)
    if access != "manage":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: management privileges required to create invitations.",
        )

    owner_id = resolve_owner_user_id(user)
    effective_user_id = owner_id or user.id
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=7)

    invite_code = f"cf-inv-{secrets.token_hex(12)}"

    new_invite = ViewerInvite(
        id=str(uuid.uuid4()),
        invite_code=invite_code,
        profile_id=profile.id,
        invited_by=effective_user_id,
        invitee_name=payload.invitee_name.strip(),
        role=payload.role or "viewer",
        view_clinical=payload.view_clinical,
        view_paperwork=payload.view_paperwork,
        expires_at=expires_at,
        created_at=now,
        updated_at=now,
    )
    db.add(new_invite)
    await db.commit()
    await db.refresh(new_invite)

    logger.info(
        "viewer_invite_created",
        invite_id=new_invite.id,
        invite_code=new_invite.invite_code,
        profile_id=profile.id,
        invited_by=effective_user_id,
    )

    return ViewerInviteResponse(
        id=new_invite.id,
        invite_code=new_invite.invite_code,
        profile_id=new_invite.profile_id,
        invited_by=new_invite.invited_by,
        invitee_name=new_invite.invitee_name,
        role=new_invite.role,
        view_clinical=new_invite.view_clinical,
        view_paperwork=new_invite.view_paperwork,
        expires_at=new_invite.expires_at.isoformat(),
        accepted_at=None,
        accepted_by=None,
        created_at=new_invite.created_at.isoformat(),
    )


@router.delete("/{profile_id}/invites/{invite_id}")
async def revoke_viewer_invite(
    profile_id: str,
    invite_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Revokes an outstanding viewer invitation (requires 'manage' access)."""
    if profile_id.lower() == "me":
        profile = await auto_provision_primary_me_profile(user, db)
    else:
        stmt = select(Profile).where(Profile.id == profile_id)
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' not found.",
        )

    access = await get_user_profile_access(profile, user, db)
    if access != "manage":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: management privileges required to revoke invitations.",
        )

    stmt = select(ViewerInvite).where(
        ViewerInvite.id == invite_id,
        ViewerInvite.profile_id == profile.id,
    )
    res = await db.execute(stmt)
    invite = res.scalar_one_or_none()
    if invite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found.",
        )

    await db.delete(invite)
    await db.commit()

    logger.info("viewer_invite_revoked", invite_id=invite_id, profile_id=profile.id)
    return {"revoked": True, "id": invite_id}


@router.get("/{profile_id}", response_model=ProfileDetailResponse)
async def get_profile(
    profile_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileDetailResponse:
    """Retrieves full detail of a specific profile, including consent and access grants."""
    owner_id = resolve_owner_user_id(user)
    effective_user_id = owner_id or user.id

    # Resolve "me" alias to user's primary profile
    if profile_id.lower() == "me":
        profile = await auto_provision_primary_me_profile(user, db)
    else:
        stmt = (
            select(Profile)
            .options(
                selectinload(Profile.consent),
                selectinload(Profile.access_grants),
            )
            .where(Profile.id == profile_id)
        )
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' not found.",
        )

    access_level = await get_user_profile_access(profile, user, db)
    if access_level is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: you do not have permission to view this profile.",
        )

    # Consent record (ensure one exists)
    consent = profile.consent
    if consent is None:
        consent_stmt = select(ProfileConsent).where(ProfileConsent.profile_id == profile.id)
        c_res = await db.execute(consent_stmt)
        consent = c_res.scalar_one_or_none()
        if consent is None:
            consent = ProfileConsent(
                profile_id=profile.id,
                allow_clinical=False,
                terms_version="v1.0",
            )
            db.add(consent)
            await db.commit()
            await db.refresh(consent)

    consent_resp = ProfileConsentResponse(
        id=consent.id,
        profile_id=consent.profile_id,
        allow_clinical=consent.allow_clinical,
        terms_version=consent.terms_version,
        consented_at=consent.consented_at.isoformat() if consent.consented_at else None,
        teen_handover_notified=consent.teen_handover_notified,
    )

    # Access grants list (only populated for 'manage' access)
    grants_resp: List[ProfileAccessResponse] = []
    if access_level == "manage":
        stmt_grants = select(ProfileAccess).where(ProfileAccess.profile_id == profile.id)
        grants_res = await db.execute(stmt_grants)
        for g in grants_res.scalars().all():
            grants_resp.append(
                ProfileAccessResponse(
                    id=g.id,
                    profile_id=g.profile_id,
                    user_id=g.user_id or effective_user_id,
                    granted_by=g.granted_by,
                    access_level=g.access_level,  # type: ignore[arg-type]
                    granted_at=g.granted_at.isoformat() if g.granted_at else datetime.now(timezone.utc).isoformat(),
                )
            )

    return ProfileDetailResponse(
        id=profile.id,
        user_id=profile.user_id or effective_user_id,
        name=profile.name,
        short_name=profile.short_name,
        relationship=profile.relationship,
        role=profile.role,
        date_of_birth=profile.date_of_birth,
        avatar_color=profile.avatar_color,
        avatar_url=profile.avatar_url,
        is_primary=profile.is_primary,
        access_level=access_level,
        consent=consent_resp,
        access_grants=grants_resp,
        created_at=profile.created_at.isoformat() if profile.created_at else datetime.now(timezone.utc).isoformat(),
        updated_at=profile.updated_at.isoformat() if profile.updated_at else datetime.now(timezone.utc).isoformat(),
    )


@router.put("/{profile_id}", response_model=ProfileDetailResponse)
async def update_profile(
    profile_id: str,
    payload: ProfileUpdate,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileDetailResponse:
    """Updates attributes of an existing profile (requires 'manage' access)."""
    if profile_id.lower() == "me":
        profile = await auto_provision_primary_me_profile(user, db)
    else:
        stmt = select(Profile).where(Profile.id == profile_id)
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' not found.",
        )

    access_level = await get_user_profile_access(profile, user, db)
    if access_level != "manage":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: management privileges required to update this profile.",
        )

    if payload.name is not None:
        profile.name = payload.name.strip()
    if payload.short_name is not None:
        profile.short_name = payload.short_name.strip() if payload.short_name else None
    if payload.relationship is not None:
        profile.relationship = payload.relationship.strip().lower()
    if payload.role is not None:
        profile.role = payload.role
    if payload.date_of_birth is not None:
        profile.date_of_birth = payload.date_of_birth
    if payload.avatar_color is not None:
        profile.avatar_color = payload.avatar_color
    if payload.avatar_url is not None:
        profile.avatar_url = payload.avatar_url.strip() if payload.avatar_url else None

    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(profile)

    return await get_profile(profile.id, user, db)


@router.delete("/{profile_id}")
async def delete_profile(
    profile_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Deletes a secondary care profile and associated data. Primary 'Me' profile deletion is strictly blocked."""
    stmt = select(Profile).where(Profile.id == profile_id)
    res = await db.execute(stmt)
    profile = res.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' not found.",
        )

    owner_id = resolve_owner_user_id(user)
    is_owner = (profile.user_id is None) if owner_id is None else (profile.user_id == owner_id)
    is_admin = getattr(user, "role", "member") == "admin"

    if not (is_owner or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: only the account owner or administrator can delete this profile.",
        )

    # Primary 'Me' profile deletion protection
    if profile.is_primary:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete primary 'Me' profile.",
        )

    await db.delete(profile)
    await db.commit()

    logger.info("profile_deleted", profile_id=profile_id, user_id=owner_id)
    return {"deleted": True, "id": profile_id}


@router.get("/{profile_id}/access", response_model=List[ProfileAccessResponse])
async def list_profile_access(
    profile_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ProfileAccessResponse]:
    """Lists all access grants for a profile (requires 'manage' access)."""
    if profile_id.lower() == "me":
        profile = await auto_provision_primary_me_profile(user, db)
    else:
        stmt = select(Profile).where(Profile.id == profile_id)
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' not found.",
        )

    access_level = await get_user_profile_access(profile, user, db)
    if access_level != "manage":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: management privileges required.",
        )

    stmt_grants = select(ProfileAccess).where(ProfileAccess.profile_id == profile.id)
    res_grants = await db.execute(stmt_grants)
    grants = res_grants.scalars().all()

    owner_id = resolve_owner_user_id(user)
    effective_user_id = owner_id or user.id

    return [
        ProfileAccessResponse(
            id=g.id,
            profile_id=g.profile_id,
            user_id=g.user_id or effective_user_id,
            granted_by=g.granted_by,
            access_level=g.access_level,  # type: ignore[arg-type]
            granted_at=g.granted_at.isoformat() if g.granted_at else datetime.now(timezone.utc).isoformat(),
        )
        for g in grants
    ]


@router.post("/{profile_id}/access", response_model=ProfileAccessResponse, status_code=status.HTTP_201_CREATED)
async def grant_profile_access(
    profile_id: str,
    payload: ProfileAccessGrant,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileAccessResponse:
    """Grants or updates profile access for another user (requires 'manage' access)."""
    if profile_id.lower() == "me":
        profile = await auto_provision_primary_me_profile(user, db)
    else:
        stmt = select(Profile).where(Profile.id == profile_id)
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' not found.",
        )

    access_level = await get_user_profile_access(profile, user, db)
    if access_level != "manage":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: management privileges required.",
        )

    # Resolve target user
    target_user: Optional[User] = None
    if payload.user_id:
        u_res = await db.execute(select(User).where(User.id == payload.user_id))
        target_user = u_res.scalar_one_or_none()
    elif payload.email:
        u_res = await db.execute(select(User).where(User.email == payload.email.strip().lower()))
        target_user = u_res.scalar_one_or_none()

    target_user_id = target_user.id if target_user else payload.user_id
    if not target_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target user not found.",
        )

    owner_id = resolve_owner_user_id(user)
    effective_user_id = owner_id or user.id
    now = datetime.now(timezone.utc)

    # Upsert access grant
    grant_stmt = select(ProfileAccess).where(
        ProfileAccess.profile_id == profile.id,
        ProfileAccess.user_id == target_user_id,
    )
    res_grant = await db.execute(grant_stmt)
    existing_grant = res_grant.scalar_one_or_none()

    if existing_grant is not None:
        existing_grant.access_level = payload.access_level
        existing_grant.granted_by = effective_user_id
        existing_grant.granted_at = now
        await db.commit()
        await db.refresh(existing_grant)
        return ProfileAccessResponse(
            id=existing_grant.id,
            profile_id=existing_grant.profile_id,
            user_id=existing_grant.user_id,
            granted_by=existing_grant.granted_by,
            access_level=existing_grant.access_level,  # type: ignore[arg-type]
            granted_at=existing_grant.granted_at.isoformat(),
        )

    new_grant = ProfileAccess(
        profile_id=profile.id,
        user_id=target_user_id,
        granted_by=effective_user_id,
        access_level=payload.access_level,
        granted_at=now,
    )
    db.add(new_grant)
    await db.commit()
    await db.refresh(new_grant)

    return ProfileAccessResponse(
        id=new_grant.id,
        profile_id=new_grant.profile_id,
        user_id=new_grant.user_id,
        granted_by=new_grant.granted_by,
        access_level=new_grant.access_level,  # type: ignore[arg-type]
        granted_at=new_grant.granted_at.isoformat(),
    )


@router.delete("/{profile_id}/access/{target_user_id}")
async def revoke_profile_access(
    profile_id: str,
    target_user_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Revokes profile access from a user (requires 'manage' access). Cannot revoke account owner."""
    if profile_id.lower() == "me":
        profile = await auto_provision_primary_me_profile(user, db)
    else:
        stmt = select(Profile).where(Profile.id == profile_id)
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' not found.",
        )

    access_level = await get_user_profile_access(profile, user, db)
    if access_level != "manage":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: management privileges required.",
        )

    if profile.user_id is not None and target_user_id == profile.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot revoke access for profile owner.",
        )

    stmt_grant = select(ProfileAccess).where(
        ProfileAccess.profile_id == profile.id,
        ProfileAccess.user_id == target_user_id,
    )
    res_grant = await db.execute(stmt_grant)
    grant = res_grant.scalar_one_or_none()
    if grant is not None:
        await db.delete(grant)
        await db.commit()

    return {"revoked": True, "user_id": target_user_id}


@router.get("/{profile_id}/consent", response_model=ProfileConsentResponse)
async def get_profile_consent(
    profile_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileConsentResponse:
    """Retrieves clinical consent state for a profile."""
    if profile_id.lower() == "me":
        profile = await auto_provision_primary_me_profile(user, db)
    else:
        stmt = select(Profile).where(Profile.id == profile_id)
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' not found.",
        )

    access_level = await get_user_profile_access(profile, user, db)
    if access_level is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )

    stmt_c = select(ProfileConsent).where(ProfileConsent.profile_id == profile.id)
    res_c = await db.execute(stmt_c)
    consent = res_c.scalar_one_or_none()
    if consent is None:
        consent = ProfileConsent(
            profile_id=profile.id,
            allow_clinical=False,
            terms_version="v1.0",
        )
        db.add(consent)
        await db.commit()
        await db.refresh(consent)

    return ProfileConsentResponse(
        id=consent.id,
        profile_id=consent.profile_id,
        allow_clinical=consent.allow_clinical,
        terms_version=consent.terms_version,
        consented_at=consent.consented_at.isoformat() if consent.consented_at else None,
        teen_handover_notified=consent.teen_handover_notified,
    )


@router.put("/{profile_id}/consent", response_model=ProfileConsentResponse)
async def update_profile_consent(
    profile_id: str,
    payload: ProfileConsentUpdate,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileConsentResponse:
    """Updates clinical consent authorization for a profile (requires 'manage' access)."""
    if profile_id.lower() == "me":
        profile = await auto_provision_primary_me_profile(user, db)
    else:
        stmt = select(Profile).where(Profile.id == profile_id)
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' not found.",
        )

    access_level = await get_user_profile_access(profile, user, db)
    if access_level != "manage":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: management privileges required to update clinical consent.",
        )

    stmt_c = select(ProfileConsent).where(ProfileConsent.profile_id == profile.id)
    res_c = await db.execute(stmt_c)
    consent = res_c.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if consent is None:
        consent = ProfileConsent(
            profile_id=profile.id,
            allow_clinical=payload.allow_clinical,
            terms_version=payload.terms_version or "v1.0",
            consented_at=now if payload.allow_clinical else None,
            created_at=now,
            updated_at=now,
        )
        db.add(consent)
    else:
        if payload.allow_clinical and not consent.allow_clinical:
            consent.consented_at = now
        elif not payload.allow_clinical:
            consent.consented_at = None

        consent.allow_clinical = payload.allow_clinical
        if payload.terms_version:
            consent.terms_version = payload.terms_version
        consent.updated_at = now

    await db.commit()
    await db.refresh(consent)

    return ProfileConsentResponse(
        id=consent.id,
        profile_id=consent.profile_id,
        allow_clinical=consent.allow_clinical,
        terms_version=consent.terms_version,
        consented_at=consent.consented_at.isoformat() if consent.consented_at else None,
        teen_handover_notified=consent.teen_handover_notified,
    )


__all__ = [
    "router",
    "get_user_profile_access",
    "auto_provision_primary_me_profile",
]
