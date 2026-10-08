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

"""FastAPI dependency providers for Carefold runtime."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.auth.adapters.disabled_adapter import (
    DEFAULT_STEWARD_USER,
    DisabledAuthAdapter,
)
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.adapters.oidc_adapter import OidcAuthAdapter
from carefold.auth.factory import get_auth_port
from carefold.auth.ports import AuthPort, UserProfile
from carefold.config import settings
from carefold.db.session import get_db
from carefold.memory.factory import get_memory_port
from carefold.memory.ports.memory_port import MemoryPort
from carefold.settings.factory import get_settings_port
from carefold.settings.ports import SettingsPort


def get_current_memory_port() -> MemoryPort:
    """Dependency provider resolving the active MemoryPort adapter singleton.

    Can be overridden in tests via app.dependency_overrides[get_current_memory_port].
    """
    return get_memory_port()


def get_auth() -> AuthPort:
    """Dependency provider resolving the active AuthPort adapter singleton."""
    return get_auth_port()


def get_settings() -> SettingsPort:
    """Dependency provider resolving the active SettingsPort adapter singleton."""
    return get_settings_port()


get_current_auth_port = get_auth
get_current_settings_port = get_settings


async def get_current_user(
    request: Request,
    auth: AuthPort = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    """FastAPI dependency resolving the currently authenticated user profile.

    If active auth port is DisabledAuthAdapter (or config.auth_provider == "disabled"),
    returns DEFAULT_STEWARD_USER.
    In local or OIDC mode, validates session token from cookie or Authorization header.
    """
    auth_port = auth if isinstance(auth, AuthPort) else get_auth_port()

    # If active auth port is DisabledAuthAdapter (or config.auth_provider == "disabled"), return DEFAULT_STEWARD_USER
    if isinstance(auth_port, DisabledAuthAdapter) or getattr(settings, "auth_provider", "disabled") == "disabled":
        return DEFAULT_STEWARD_USER

    # In local/oidc auth mode:
    # Explicit Authorization header takes precedence over ambient cookie
    token: Optional[str] = None
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth_header:
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif auth_header.startswith("bearer "):
            token = auth_header[7:].strip()
        else:
            token = auth_header.strip()

    if not token:
        token = request.cookies.get("carefold_session")

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    validated = await auth_port.validate_session(token)
    if validated is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = validated[0] if isinstance(validated, (tuple, list)) else validated
    if user.status != "active":
        raise HTTPException(status_code=403, detail="Account is disabled")

    return user


async def require_admin(
    user: UserProfile = Depends(get_current_user),
) -> UserProfile:
    """FastAPI dependency requiring the current user to have administrative privileges."""
    if user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Administrative privileges required",
        )
    return user


__all__ = [
    "get_current_memory_port",
    "get_auth",
    "get_settings",
    "get_current_auth_port",
    "get_current_settings_port",
    "get_current_user",
    "require_admin",
]
