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

"""Authentication and session management REST API router."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from carefold.api.deps import get_auth, get_current_user, get_settings
from carefold.auth.ports import AuthPort, UserProfile
from carefold.config import settings
from carefold.settings.ports import SettingsPort

router = APIRouter()


class RegisterUserRequest(BaseModel):
    """User self-registration payload."""

    email: str = Field(..., description="Normalized unique email address")
    username: str = Field(..., description="Unique username for login")
    password: str = Field(..., description="Raw password string")
    full_name: Optional[str] = Field(default=None, description="Human display name")


class LoginRequest(BaseModel):
    """User authentication credentials."""

    username: Optional[str] = Field(default=None, description="Username or email address")
    email: Optional[str] = Field(default=None, description="Email address fallback")
    password: str = Field(..., description="Raw password string")

    @property
    def identifier(self) -> str:
        return (self.username or self.email or "").strip()


class ForgotPasswordRequest(BaseModel):
    """Payload to request password reset token."""

    email: str = Field(..., description="Registered account email address")


class ResetPasswordRequest(BaseModel):
    """Payload to reset password using single-use token."""

    token: str = Field(..., description="Raw password reset token")
    new_password: str = Field(..., description="New replacement password")


class ChangePasswordRequest(BaseModel):
    """Payload for authenticated password change."""

    current_password: str = Field(..., description="Current password")
    new_password: str = Field(..., description="New replacement password")


def validate_password_complexity(password: Optional[str]) -> None:
    """Validates that a password satisfies complexity requirements.

    Requirements:
    - At least 10 characters in length.
    - Contains at least one uppercase letter.
    - Contains at least one lowercase letter.
    - Contains at least one digit or special character.
    """
    if not password or len(password) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 10 characters long.",
        )
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit_or_special = any(c.isdigit() or not c.isalnum() for c in password)
    if not (has_upper and has_lower and has_digit_or_special):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain uppercase, lowercase, and a number or special character.",
        )


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterUserRequest,
    request: Request,
    response: Response,
    auth_port: AuthPort = Depends(get_auth),
) -> Dict[str, Any]:
    """Registers a new user account.

    If no administrator accounts exist yet, the first registered user is automatically
    elevated to role='admin', immediately authenticated, and issued a session cookie.
    Subsequent user registrations default to role='member'.
    Validates password complexity (min 10 characters, mixed case, digit/special).
    Returns 409 Conflict if email or username is already registered.
    """
    validate_password_complexity(body.password)

    has_admin = await auth_port.has_admin_user()
    assigned_role = "admin" if not has_admin else "member"

    try:
        user = await auth_port.register_user(
            email=body.email,
            username=body.username,
            password=body.password,
            full_name=body.full_name,
            role=assigned_role,
            auth_provider="local",
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(err),
        )

    # If this is the initial admin creation on first-run, automatically establish the session
    session_token = None
    if not has_admin:
        token, sess = await auth_port.create_session(
            user_id=user.id,
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        session_token = token
        response.set_cookie(
            key="carefold_session",
            value=token,
            httponly=True,
            samesite="lax",
            secure=False,
            max_age=60 * 60 * 24 * 7,
            path="/",
        )

    return {
        "user": user,
        "is_initial_admin": not has_admin,
        "token": session_token,
    }


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    auth_port: AuthPort = Depends(get_auth),
) -> Dict[str, Any]:
    """Authenticates credentials and establishes a stateful HTTP-only session."""
    ident = body.identifier
    if not ident:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email is required.",
        )

    user = await auth_port.authenticate(ident, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    session_token = await auth_port.create_session(
        user_id=user.id,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    raw_token = session_token.token if hasattr(session_token, "token") else session_token[0]

    # Set HTTP-only session cookie
    response.set_cookie(
        key="carefold_session",
        value=raw_token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=60 * 60 * 24 * 7,  # 7 days
        secure=False,
    )

    return {"user": user, "token": raw_token}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    auth_port: AuthPort = Depends(get_auth),
) -> Dict[str, Any]:
    """Revokes the active session and clears the session cookie."""
    token: Optional[str] = request.cookies.get("carefold_session")
    if not token:
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
        if auth_header:
            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()
            elif auth_header.startswith("bearer "):
                token = auth_header[7:].strip()
            else:
                token = auth_header.strip()

    if token:
        await auth_port.revoke_session(token)

    response.delete_cookie(key="carefold_session", path="/")
    return {"success": True}


@router.get("/me")
async def me(
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Returns the profile of the currently authenticated user."""
    return {"user": user}


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    auth_port: AuthPort = Depends(get_auth),
) -> Dict[str, Any]:
    """Issues a single-use password reset token for registered email address."""
    token = await auth_port.create_password_reset_token(body.email)
    return {
        "success": True,
        "message": "If the email is registered, a password reset token has been issued.",
        "token": token,
    }


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    auth_port: AuthPort = Depends(get_auth),
) -> Dict[str, Any]:
    """Resets user password using single-use reset token and revokes active sessions."""
    validate_password_complexity(body.new_password)
    success = await auth_port.reset_password(body.token, body.new_password)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )
    return {"success": True}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: UserProfile = Depends(get_current_user),
    auth_port: AuthPort = Depends(get_auth),
) -> Dict[str, Any]:
    """Changes password for the currently authenticated user."""
    validate_password_complexity(body.new_password)
    success = await auth_port.change_password(
        user.id,
        current_password=body.current_password,
        new_password=body.new_password,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password incorrect",
        )
    return {"success": True}


@router.get("/providers")
async def providers(
    auth_port: AuthPort = Depends(get_auth),
    settings_port: SettingsPort = Depends(get_settings),
) -> Dict[str, Any]:
    """Returns the active authentication provider and supported SSO options."""
    active_provider = getattr(settings, "auth_provider", "local")
    try:
        configured = await settings_port.get_setting("auth.provider")
        if configured:
            active_provider = configured
    except Exception:
        pass

    has_admin = await auth_port.has_admin_user()

    return {
        "active_provider": active_provider,
        "sso_providers": [],
        "registration_enabled": True,
        "has_admin": has_admin,
        "needs_admin_setup": not has_admin,
    }


@router.get("/status")
@router.get("/setup-status")
async def setup_status(
    auth_port: AuthPort = Depends(get_auth),
) -> Dict[str, Any]:
    """Returns whether the system requires initial administrator account initialization."""
    has_admin = await auth_port.has_admin_user()
    active_provider = getattr(settings, "auth_provider", "local")
    return {
        "needs_admin_setup": not has_admin,
        "has_admin": has_admin,
        "active_provider": active_provider,
    }


__all__ = ["router", "validate_password_complexity"]

