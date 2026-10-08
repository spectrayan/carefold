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

"""Hexagonal Port Interface and Domain Models for Authentication and Identity Management."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field


class UserProfile(BaseModel):
    """Domain model representing a verified user profile across the port boundary."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Unique user identifier (UUID v4 string)")
    email: str = Field(..., description="Normalized unique email address")
    username: str = Field(..., description="Unique username for login and display")
    full_name: Optional[str] = Field(default=None, description="Human display name")
    role: str = Field(default="member", description="Access role: admin, steward, or member")
    status: str = Field(default="active", description="Account status: active or disabled")
    auth_provider: str = Field(
        default="local",
        description="Identity source: local, oidc, google, github, disabled",
    )
    created_at: datetime = Field(..., description="Account creation timestamp (UTC)")
    updated_at: datetime = Field(..., description="Last modification timestamp (UTC)")
    last_login_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of most recent successful login (UTC)",
    )


# Domain alias for hexagonal architecture parity
UserRecord = UserProfile


class SessionRecord(BaseModel):
    """Domain representation of an active session stored in persistence."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="SHA-256 hex digest of the raw session secret token")
    user_id: str = Field(..., description="Referenced user identifier")
    client_ip: Optional[str] = Field(default=None, description="Client IP address")
    user_agent: Optional[str] = Field(default=None, description="Client user agent string")
    expires_at: datetime = Field(..., description="Session expiration timestamp (UTC)")
    created_at: datetime = Field(..., description="Session issuance timestamp (UTC)")
    last_active_at: datetime = Field(..., description="Last activity timestamp (UTC)")


class SessionToken(BaseModel):
    """Container holding the raw session secret token and associated session metadata.

    Supports direct property access as well as tuple unpacking (raw_token, session_record).
    """

    model_config = ConfigDict(frozen=True)

    token: str = Field(..., description="Cryptographically secure raw urlsafe token")
    session_id: str = Field(..., description="SHA-256 hex digest stored in database")
    user_id: str = Field(..., description="Referenced user identifier")
    expires_at: datetime = Field(..., description="Session expiration timestamp (UTC)")
    created_at: datetime = Field(..., description="Session issuance timestamp (UTC)")
    last_active_at: datetime = Field(..., description="Last activity timestamp (UTC)")
    client_ip: Optional[str] = Field(default=None, description="Client IP address")
    user_agent: Optional[str] = Field(default=None, description="Client user agent string")

    @property
    def id(self) -> str:
        """Alias for session_id."""
        return self.session_id

    @property
    def session(self) -> SessionRecord:
        """Constructs an immutable SessionRecord from session metadata."""
        return SessionRecord(
            id=self.session_id,
            user_id=self.user_id,
            client_ip=self.client_ip,
            user_agent=self.user_agent,
            expires_at=self.expires_at,
            created_at=self.created_at,
            last_active_at=self.last_active_at,
        )

    def __iter__(self):
        """Allows unpacking: raw_token, session = await auth_port.create_session(...)"""
        yield self.token
        yield self.session

    def __getitem__(self, idx: int) -> Any:
        return (self.token, self.session)[idx]

    def __len__(self) -> int:
        return 2


class ValidatedSession(UserProfile):
    """Result of successful session validation.

    Inherits from UserProfile so it can be used directly as a UserProfile,
    while also supporting tuple unpacking (user, session) and indexing [0], [1].
    """

    session: Optional[SessionRecord] = None

    def __iter__(self):
        yield self
        yield self.session

    def __getitem__(self, idx: int) -> Any:
        return (self, self.session)[idx]

    def __len__(self) -> int:
        return 2


class AuthSession(BaseModel):
    """Aggregate combining raw authentication token, session record, and user profile."""

    model_config = ConfigDict(frozen=True)

    token: str = Field(..., description="Raw urlsafe session token")
    session: SessionRecord = Field(..., description="Session record metadata")
    user: UserProfile = Field(..., description="Authenticated user profile")


class RegisterUserRequest(BaseModel):
    """Payload for registering a new user."""

    email: str = Field(..., description="Email address")
    username: str = Field(..., description="Desired username")
    password: Optional[str] = Field(default=None, description="Raw password string")
    full_name: Optional[str] = Field(default=None, description="Human display name")
    role: str = Field(default="member", description="Access role: admin, steward, or member")
    auth_provider: str = Field(
        default="local",
        description="Identity source: local, oidc, google, github, disabled",
    )


class UserUpdate(BaseModel):
    """Payload for updating user profile, role, or active status."""

    full_name: Optional[str] = Field(default=None, description="Updated display name")
    role: Optional[str] = Field(default=None, description="Updated role: admin, steward, member")
    status: Optional[str] = Field(default=None, description="Updated status: active or disabled")


class PasswordChangeRequest(BaseModel):
    """Payload for authenticated password change."""

    old_password: str = Field(..., description="Current password")
    new_password: str = Field(..., description="New password")


class PasswordResetRequest(BaseModel):
    """Payload for consuming a single-use password reset token."""

    token: str = Field(..., description="Raw password reset token")
    new_password: str = Field(..., description="New password")


class PaginatedUsers(BaseModel):
    """Paginated collection of user profiles."""

    users: List[UserProfile] = Field(default_factory=list, description="List of users")
    total: int = Field(default=0, description="Total matching count across all pages")
    offset: int = Field(default=0, description="Zero-based record offset")
    limit: int = Field(default=50, description="Page size limit")
    page: int = Field(default=1, description="1-based page index")
    page_size: int = Field(default=50, description="Page size")

    def __iter__(self):
        """Allows unpacking: users, total = await auth_port.list_users(...)"""
        yield self.users
        yield self.total

    def __getitem__(self, idx: int) -> Any:
        return (self.users, self.total)[idx]

    def __len__(self) -> int:
        return 2


class AuthPort(ABC):
    """Hexagonal Port Interface for Authentication and Identity Management.

    Defines the contract for authenticating credentials, managing stateful sessions,
    handling password lifecycle, and administering users across swappable backends.
    """

    @abstractmethod
    async def register_user(
        self,
        req_or_email: Optional[Union[RegisterUserRequest, str]] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        full_name: Optional[str] = None,
        role: str = "member",
        auth_provider: str = "local",
        *,
        email: Optional[str] = None,
        req: Optional[RegisterUserRequest] = None,
    ) -> UserProfile:
        """Registers a new user record.

        Accepts either a RegisterUserRequest or individual positional/keyword arguments.

        Raises:
            ValueError: If email or username is already registered, or password is invalid.
        """
        ...

    @abstractmethod
    async def authenticate(
        self,
        username_or_email: str,
        password: str,
    ) -> Optional[UserProfile]:
        """Authenticates user credentials using OWASP Argon2id verification.

        Returns UserProfile if valid and active, or None if invalid or disabled.
        Mitigates timing attacks by computing dummy verification on misses.
        """
        ...

    @abstractmethod
    async def create_session(
        self,
        user_id: str,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        duration_seconds: int = 86400 * 7,
    ) -> SessionToken:
        """Issues a new session for the specified user.

        Returns SessionToken containing the raw urlsafe secret token.
        Only SHA-256(raw_token) is stored in persistence.
        Supports tuple unpacking: `raw_token, session = await create_session(...)`.
        """
        ...

    @abstractmethod
    async def validate_session(
        self,
        raw_token: str,
    ) -> Optional[ValidatedSession]:
        """Validates a raw token against persisted active sessions.

        Returns ValidatedSession if valid and not expired; None otherwise.
        Updates last_active_at on success.
        Supports tuple unpacking: `user, session = await validate_session(...)`.
        """
        ...

    @abstractmethod
    async def revoke_session(
        self,
        raw_token: str,
    ) -> bool:
        """Revokes an active session by raw token.

        Returns True if found and deleted, False otherwise.
        """
        ...

    @abstractmethod
    async def revoke_all_sessions(
        self,
        user_id: str,
    ) -> int:
        """Revokes all active sessions for a user.

        Returns the number of sessions revoked.
        """
        ...

    @abstractmethod
    async def create_password_reset_token(
        self,
        email: str,
        expiry_minutes: int = 60,
    ) -> Optional[str]:
        """Generates a cryptographically random single-use password reset token.

        Returns the raw token if the user exists, or None otherwise.
        Stores SHA-256(raw_token) in persistence.
        """
        ...

    @abstractmethod
    async def reset_password(
        self,
        raw_token: str,
        new_password: str,
    ) -> bool:
        """Validates reset token, updates password with Argon2id, and revokes all user sessions.

        Returns True if successful, False if token is invalid, expired, or already used.
        """
        ...

    @abstractmethod
    async def change_password(
        self,
        user_id: str,
        old_password: Optional[str] = None,
        new_password: str = "",
        current_password: Optional[str] = None,
    ) -> bool:
        """Validates old password, updates to new Argon2id password hash.

        Returns True on success, False if old password does not match.
        """
        ...

    @abstractmethod
    async def list_users(
        self,
        page: int = 1,
        page_size: int = 50,
        search: Optional[str] = None,
        query: Optional[str] = None,
        role: Optional[str] = None,
        status: Optional[str] = None,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> PaginatedUsers:
        """Returns paginated collection of users matching optional filters."""
        ...

    @abstractmethod
    async def update_user(
        self,
        user_id: str,
        updates: Optional[Union[UserUpdate, Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Optional[UserProfile]:
        """Updates user profile attributes.

        If status is set to 'disabled', revokes all active sessions immediately.
        Returns updated UserProfile, or None if user not found.
        """
        ...
