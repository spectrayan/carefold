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

"""Administrative control panel and user management REST API router."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.auth import validate_password_complexity
from carefold.api.deps import get_auth, get_settings, require_admin
from carefold.auth.adapters.disabled_adapter import DisabledAuthAdapter
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.ports import AuthPort, UserProfile, UserUpdate
from carefold.config import settings as app_settings
from carefold.constants.defaults import DEFAULT_VERSION
from carefold.db.models import PasswordReset, Session, SystemSetting, User
from carefold.db.session import get_db, get_engine, sanitize_db_url
from carefold.settings.ports import SECRET_MASK, SettingsPort

router = APIRouter(dependencies=[Depends(require_admin)])


class UpdateSettingsRequest(BaseModel):
    """Payload for updating runtime system configuration."""

    settings: Optional[Dict[str, Any]] = Field(default=None, description="Key-value mapping of settings")
    key: Optional[str] = Field(default=None, description="Single setting key")
    value: Optional[Any] = Field(default=None, description="Single setting value")
    is_secret: Optional[bool] = Field(default=None, description="Whether setting is confidential")


class AdminCreateUserRequest(BaseModel):
    """Payload for administrative user creation."""

    email: str = Field(..., description="Normalized unique email address")
    username: str = Field(..., description="Unique username")
    password: str = Field(..., description="Initial raw password string")
    full_name: Optional[str] = Field(default=None, description="Human display name")
    role: str = Field(default="member", description="Access role: admin, steward, or member")


class AdminUpdateUserRequest(BaseModel):
    """Payload for administrative user modification."""

    role: Optional[str] = Field(default=None, description="Access role: admin, steward, or member")
    status: Optional[str] = Field(default=None, description="Account status: active or disabled")
    full_name: Optional[str] = Field(default=None, description="Human display name")
    email: Optional[str] = Field(default=None, description="Email address")


class AdminResetPasswordRequest(BaseModel):
    """Payload for administrative password reset."""

    new_password: str = Field(..., description="New replacement password")


@router.get("/settings")
async def get_settings_endpoint(
    settings_port: SettingsPort = Depends(get_settings),
) -> Dict[str, Any]:
    """Retrieves all runtime system configuration settings with secrets masked."""
    all_settings = await settings_port.get_all_settings(mask_secrets=True)
    return {"settings": all_settings}


@router.put("/settings")
async def update_settings_endpoint(
    body: Union[UpdateSettingsRequest, Dict[str, Any]],
    settings_port: SettingsPort = Depends(get_settings),
) -> Dict[str, Any]:
    """Updates runtime system configuration settings."""
    if isinstance(body, UpdateSettingsRequest):
        if body.settings is not None:
            for k, v in body.settings.items():
                if v == SECRET_MASK:
                    continue
                await settings_port.set_setting(k, v)
        elif body.key is not None:
            if body.value != SECRET_MASK:
                await settings_port.set_setting(body.key, body.value, is_secret=body.is_secret)
    elif isinstance(body, dict):
        if "settings" in body and isinstance(body["settings"], dict):
            for k, v in body["settings"].items():
                if v == SECRET_MASK:
                    continue
                await settings_port.set_setting(k, v)
        elif "key" in body:
            if body.get("value") != SECRET_MASK:
                raw_is_secret = body.get("is_secret")
                is_secret_val = bool(raw_is_secret) if raw_is_secret is not None else None
                await settings_port.set_setting(
                    body["key"], body.get("value"), is_secret=is_secret_val
                )
        else:
            for k, v in body.items():
                if v == SECRET_MASK:
                    continue
                await settings_port.set_setting(k, v)

    all_settings = await settings_port.get_all_settings(mask_secrets=True)
    return {"settings": all_settings}


@router.get("/users")
async def list_users_endpoint(
    page: int = Query(default=1, ge=1, description="1-based page index"),
    limit: int = Query(default=50, ge=1, le=100, description="Page size limit"),
    search: Optional[str] = Query(default=None, description="Search filter on username, email, or name"),
    auth_port: AuthPort = Depends(get_auth),
) -> Dict[str, Any]:
    """Retrieves a paginated list of registered users."""
    res = await auth_port.list_users(page=page, page_size=limit, search=search)
    return {
        "users": res.users,
        "total": res.total,
        "page": page,
        "page_size": limit,
    }


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user_endpoint(
    body: AdminCreateUserRequest,
    auth_port: AuthPort = Depends(get_auth),
) -> Dict[str, Any]:
    """Admin creates a new user account."""
    if body.role not in ("admin", "steward", "member"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be one of: 'admin', 'steward', 'member'.",
        )
    validate_password_complexity(body.password)

    try:
        user = await auth_port.register_user(
            email=body.email,
            username=body.username,
            password=body.password,
            full_name=body.full_name,
            role=body.role,
            auth_provider="local",
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(err),
        )

    if user.role != body.role:
        updated = await auth_port.update_user(user.id, UserUpdate(role=body.role))
        if updated:
            user = updated

    return {"user": user}


@router.patch("/users/{user_id}")
async def patch_user_endpoint(
    user_id: str,
    body: AdminUpdateUserRequest,
    auth_port: AuthPort = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Admin modifies user role, status, name, or email."""
    if body.role is not None and body.role not in ("admin", "steward", "member"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be one of: 'admin', 'steward', 'member'.",
        )
    if body.status is not None and body.status not in ("active", "disabled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Status must be one of: 'active', 'disabled'.",
        )

    updates = body.model_dump(exclude_unset=True)
    user = await auth_port.update_user(user_id, updates=updates)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found.",
        )

    if body.email and not isinstance(auth_port, DisabledAuthAdapter):
        if isinstance(auth_port, SqlAuthAdapter):
            session_factory = auth_port._get_session_factory()
            async with session_factory() as session:
                user_row = await session.get(User, user_id)
                if user_row:
                    user_row.email = body.email.strip().lower()
                    await session.commit()
                    await session.refresh(user_row)
                    user = UserProfile(
                        id=user_row.id,
                        email=user_row.email,
                        username=user_row.username,
                        full_name=user_row.full_name,
                        role=user_row.role,
                        status=user_row.status,
                        auth_provider=user_row.auth_provider,
                        created_at=user_row.created_at,
                        updated_at=user_row.updated_at,
                        last_login_at=user_row.last_login_at,
                    )
        else:
            user_row = await db.get(User, user_id)
            if user_row:
                user_row.email = body.email.strip().lower()
                await db.commit()
                await db.refresh(user_row)
                user = UserProfile(
                    id=user_row.id,
                    email=user_row.email,
                    username=user_row.username,
                    full_name=user_row.full_name,
                    role=user_row.role,
                    status=user_row.status,
                    auth_provider=user_row.auth_provider,
                    created_at=user_row.created_at,
                    updated_at=user_row.updated_at,
                    last_login_at=user_row.last_login_at,
                )

    return {"user": user}


@router.post("/users/{user_id}/reset-password")
async def reset_user_password_endpoint(
    user_id: str,
    body: AdminResetPasswordRequest,
    auth_port: AuthPort = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Admin forces a password reset for a specific user and revokes active sessions."""
    validate_password_complexity(body.new_password)

    if isinstance(auth_port, DisabledAuthAdapter):
        return {"success": True}

    if isinstance(auth_port, SqlAuthAdapter):
        session_factory = auth_port._get_session_factory()
        async with session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User '{user_id}' not found.",
                )
            user_email = user.email
    else:
        user = await db.get(User, user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{user_id}' not found.",
            )
        user_email = user.email

    token = await auth_port.create_password_reset_token(user_email)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to create password reset token.",
        )

    success = await auth_port.reset_password(token, body.new_password)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to reset password.",
        )

    return {"success": True}


@router.delete("/users/{user_id}")
async def delete_user_endpoint(
    user_id: str,
    current_user: UserProfile = Depends(require_admin),
    auth_port: AuthPort = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Admin deletes user account. Prevents self-deletion."""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete own account",
        )

    if isinstance(auth_port, DisabledAuthAdapter):
        return {"success": True}

    if isinstance(auth_port, SqlAuthAdapter):
        session_factory = auth_port._get_session_factory()
        async with session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User '{user_id}' not found.",
                )
            await auth_port.revoke_all_sessions(user_id)
            await session.delete(user)
            await session.commit()
    else:
        user = await db.get(User, user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{user_id}' not found.",
            )
        await auth_port.revoke_all_sessions(user_id)
        await db.delete(user)
        await db.commit()

    return {"success": True}


@router.get("/diagnostics")
async def get_diagnostics_endpoint(
    db: AsyncSession = Depends(get_db),
    auth_port: AuthPort = Depends(get_auth),
) -> Dict[str, Any]:
    """Retrieves system diagnostics, database dialect, table counts, and agent/skill counts."""
    engine = get_engine()
    dialect = engine.dialect.name
    db_url = sanitize_db_url(engine.url)

    users_count = 0
    sessions_count = 0
    resets_count = 0
    settings_count = 0

    if not isinstance(auth_port, DisabledAuthAdapter):
        try:
            users_count = (await db.scalar(select(func.count()).select_from(User))) or 0
            sessions_count = (await db.scalar(select(func.count()).select_from(Session))) or 0
            resets_count = (await db.scalar(select(func.count()).select_from(PasswordReset))) or 0
            settings_count = (await db.scalar(select(func.count()).select_from(SystemSetting))) or 0
        except Exception:
            pass
    else:
        users_count = 1
        sessions_count = 1

    agents_dir = app_settings.get_agents_dir()
    skills_dir = app_settings.get_skills_dir()
    agents_count = (
        len([d for d in agents_dir.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))])
        if agents_dir.is_dir()
        else 0
    )
    skills_count = (
        len([d for d in skills_dir.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))])
        if skills_dir.is_dir()
        else 0
    )

    return {
        "status": "ok",
        "version": DEFAULT_VERSION,
        "database": {
            "dialect": dialect,
            "url": db_url,
            "connected": True,
        },
        "table_counts": {
            "users": users_count,
            "sessions": sessions_count,
            "password_resets": resets_count,
            "system_settings": settings_count,
        },
        "agents_count": agents_count,
        "skills_count": skills_count,
    }


__all__ = ["router"]
