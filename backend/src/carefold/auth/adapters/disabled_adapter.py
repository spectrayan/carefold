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

"""Disabled authentication adapter for single-user local desktop steward bypass."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from carefold.auth.ports import (
    AuthPort,
    PaginatedUsers,
    RegisterUserRequest,
    SessionRecord,
    SessionToken,
    UserProfile,
    UserUpdate,
    ValidatedSession,
)

DEFAULT_STEWARD_USER: UserProfile = UserProfile(
    id="00000000-0000-0000-0000-000000000001",
    email="steward@carefold.local",
    username="steward",
    full_name="Local Healthcare Steward",
    role="admin",
    status="active",
    auth_provider="disabled",
    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    last_login_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
)

_STATIC_SESSION_RECORD: SessionRecord = SessionRecord(
    id="disabled-session-sha256-hash",
    user_id=DEFAULT_STEWARD_USER.id,
    client_ip="127.0.0.1",
    user_agent="Carefold-Desktop-Local",
    expires_at=datetime(2099, 12, 31, tzinfo=timezone.utc),
    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    last_active_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
)


class DisabledAuthAdapter(AuthPort):
    """Bypass adapter for local offline desktop mode requiring zero login friction."""

    def __init__(self, steward: Optional[UserProfile] = None) -> None:
        self._steward = steward or DEFAULT_STEWARD_USER

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
        return self._steward

    async def authenticate(
        self,
        username_or_email: str,
        password: str,
    ) -> Optional[UserProfile]:
        return self._steward

    async def create_session(
        self,
        user_id: str,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        duration_seconds: int = 86400 * 7,
    ) -> SessionToken:
        return SessionToken(
            token="disabled-session-token",
            session_id=_STATIC_SESSION_RECORD.id,
            user_id=self._steward.id,
            expires_at=_STATIC_SESSION_RECORD.expires_at,
            created_at=_STATIC_SESSION_RECORD.created_at,
            last_active_at=datetime.now(timezone.utc),
            client_ip=client_ip or _STATIC_SESSION_RECORD.client_ip,
            user_agent=user_agent or _STATIC_SESSION_RECORD.user_agent,
        )

    async def validate_session(
        self,
        raw_token: str,
    ) -> Optional[ValidatedSession]:
        return ValidatedSession(
            **self._steward.model_dump(),
            session=_STATIC_SESSION_RECORD,
        )

    async def revoke_session(
        self,
        raw_token: str,
    ) -> bool:
        return True

    async def revoke_all_sessions(
        self,
        user_id: str,
    ) -> int:
        return 0

    async def create_password_reset_token(
        self,
        email: str,
        expiry_minutes: int = 60,
    ) -> Optional[str]:
        return "disabled-password-reset-token"

    async def reset_password(
        self,
        raw_token: str,
        new_password: str,
    ) -> bool:
        return True

    async def change_password(
        self,
        user_id: str,
        old_password: Optional[str] = None,
        new_password: str = "",
        current_password: Optional[str] = None,
    ) -> bool:
        return True

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
        effective_limit = limit if limit is not None else page_size
        effective_offset = offset if offset is not None else (page - 1) * effective_limit
        return PaginatedUsers(
            users=[self._steward],
            total=1,
            offset=effective_offset,
            limit=effective_limit,
            page=1,
            page_size=effective_limit,
        )

    async def update_user(
        self,
        user_id: str,
        updates: Optional[Union[UserUpdate, Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Optional[UserProfile]:
        return self._steward

    async def has_admin_user(self) -> bool:
        """In disabled single-user steward mode, an admin steward always exists."""
        return True

