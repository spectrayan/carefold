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

"""SQL-backed implementation of AuthPort with OWASP Argon2id password hashing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import logging
import secrets
from typing import Any, Dict, Optional, Union

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from carefold.db.models import PasswordReset, Session, User
from carefold.db.session import get_session_factory

logger = logging.getLogger(__name__)

# Initialize OWASP-recommended Argon2id hasher
try:
    from pwdlib import PasswordHash
    _default_hasher = PasswordHash.recommended()
except Exception:  # pragma: no cover
    import argon2

    class _Argon2FallbackHasher:
        def __init__(self) -> None:
            self._ph = argon2.PasswordHasher(
                time_cost=3,
                memory_cost=65536,
                parallelism=4,
                type=argon2.Type.ID,
            )

        def hash(self, password: str) -> str:
            return self._ph.hash(password)

        def verify(self, password: str, hash_str: str) -> bool:
            try:
                return self._ph.verify(hash_str, password)
            except Exception:
                return False

    _default_hasher = _Argon2FallbackHasher()

# Precomputed dummy Argon2id hash to mitigate user enumeration timing attacks
_DUMMY_HASH: str = _default_hasher.hash("carefold_constant_time_dummy_salt_timing_mitigation_998877")


def _hash_token(raw_token: str) -> str:
    """Computes SHA-256 hex digest of a raw token for storage at rest."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class SqlAuthAdapter(AuthPort):
    """Hexagonal SQL adapter implementing AuthPort via SQLAlchemy 2.0 Async."""

    def __init__(
        self,
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
        hasher: Optional[Any] = None,
    ) -> None:
        self._session_factory = session_factory
        self._hasher = hasher or _default_hasher

    def _get_session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is not None:
            return self._session_factory
        return get_session_factory()

    @staticmethod
    def _user_to_profile(user: User) -> UserProfile:
        return UserProfile(
            id=user.id,
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            status=user.status,
            auth_provider=user.auth_provider,
            created_at=user.created_at,
            updated_at=user.updated_at,
            last_login_at=user.last_login_at,
        )

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
        active_req = req if req is not None else (req_or_email if isinstance(req_or_email, RegisterUserRequest) else None)
        if active_req is not None:
            resolved_email = active_req.email
            resolved_username = active_req.username
            resolved_password = active_req.password
            resolved_full_name = active_req.full_name
            resolved_role = active_req.role
            resolved_auth_provider = active_req.auth_provider
        else:
            resolved_email = str(req_or_email) if req_or_email is not None else (email or "")
            resolved_username = username or ""
            resolved_password = password
            resolved_full_name = full_name
            resolved_role = role
            resolved_auth_provider = auth_provider

        norm_email = resolved_email.strip().lower()
        norm_username = resolved_username.strip()

        if not norm_email or not norm_username:
            raise ValueError("Email and username are required.")

        if resolved_password is not None:
            if len(resolved_password) < 10:
                raise ValueError("Password must be at least 10 characters long.")
            hashed_pw = self._hasher.hash(resolved_password)
        else:
            if resolved_auth_provider == "local":
                raise ValueError("Password is required for local authentication.")
            hashed_pw = ""

        session_factory = self._get_session_factory()
        async with session_factory() as session:
            existing_stmt = select(User).where(
                or_(User.email == norm_email, func.lower(User.username) == norm_username.lower())
            )
            existing = (await session.scalars(existing_stmt)).first()
            if existing is not None:
                raise ValueError("User with this email or username already exists.")

            now = datetime.now(timezone.utc)
            user = User(
                email=norm_email,
                username=norm_username,
                hashed_password=hashed_pw,
                full_name=resolved_full_name,
                role=resolved_role,
                status="active",
                auth_provider=resolved_auth_provider,
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return self._user_to_profile(user)

    async def authenticate(
        self,
        username_or_email: str,
        password: str,
    ) -> Optional[UserProfile]:
        norm_query = username_or_email.strip().lower()
        session_factory = self._get_session_factory()

        async with session_factory() as session:
            stmt = select(User).where(
                or_(User.email == norm_query, func.lower(User.username) == norm_query)
            )
            user = (await session.scalars(stmt)).first()

            if user is None:
                # Constant-time dummy verification to thwart user enumeration timing attacks
                self._hasher.verify(password, _DUMMY_HASH)
                return None

            if not self._hasher.verify(password, user.hashed_password):
                return None

            if user.status != "active":
                return self._user_to_profile(user)

            user.last_login_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(user)
            return self._user_to_profile(user)

    async def create_session(
        self,
        user_id: str,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        duration_seconds: int = 86400 * 7,
    ) -> SessionToken:
        session_factory = self._get_session_factory()
        async with session_factory() as session:
            user = await session.get(User, user_id)
            if user is None or user.status != "active":
                raise ValueError(f"User '{user_id}' does not exist or is inactive.")

            raw_token = secrets.token_urlsafe(32)
            token_hash = _hash_token(raw_token)
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=duration_seconds)

            db_session = Session(
                id=token_hash,
                user_id=user.id,
                client_ip=client_ip,
                user_agent=user_agent,
                expires_at=expires_at,
                created_at=now,
                last_active_at=now,
            )
            session.add(db_session)
            await session.commit()

            return SessionToken(
                token=raw_token,
                session_id=token_hash,
                user_id=user.id,
                expires_at=expires_at,
                created_at=now,
                last_active_at=now,
                client_ip=client_ip,
                user_agent=user_agent,
            )

    async def validate_session(
        self,
        raw_token: str,
    ) -> Optional[ValidatedSession]:
        if not raw_token or not raw_token.strip():
            return None

        token_hash = _hash_token(raw_token)
        session_factory = self._get_session_factory()

        async with session_factory() as session:
            stmt = select(Session, User).join(User, Session.user_id == User.id).where(
                Session.id == token_hash
            )
            result = (await session.execute(stmt)).first()
            if result is None:
                return None

            db_session, user = result
            now = datetime.now(timezone.utc)

            # Check expiration
            expires_at = db_session.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if expires_at <= now:
                await session.delete(db_session)
                await session.commit()
                return None

            session_record = SessionRecord(
                id=db_session.id,
                user_id=db_session.user_id,
                client_ip=db_session.client_ip,
                user_agent=db_session.user_agent,
                expires_at=expires_at,
                created_at=db_session.created_at,
                last_active_at=db_session.last_active_at,
            )

            profile = self._user_to_profile(user)

            if user.status != "active":
                return ValidatedSession(
                    **profile.model_dump(),
                    session=session_record,
                )

            # Update rolling activity timestamp
            db_session.last_active_at = now
            await session.commit()

            return ValidatedSession(
                **profile.model_dump(),
                session=session_record,
            )

    async def revoke_session(
        self,
        raw_token: str,
    ) -> bool:
        if not raw_token or not raw_token.strip():
            return False

        token_hash = _hash_token(raw_token)
        session_factory = self._get_session_factory()
        async with session_factory() as session:
            stmt = delete(Session).where(Session.id == token_hash)
            result = await session.execute(stmt)
            await session.commit()
            return (result.rowcount or 0) > 0

    async def revoke_all_sessions(
        self,
        user_id: str,
    ) -> int:
        session_factory = self._get_session_factory()
        async with session_factory() as session:
            stmt = delete(Session).where(Session.user_id == user_id)
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    async def create_password_reset_token(
        self,
        email: str,
        expiry_minutes: int = 60,
    ) -> Optional[str]:
        norm_email = email.strip().lower()
        session_factory = self._get_session_factory()

        async with session_factory() as session:
            stmt = select(User).where(User.email == norm_email)
            user = (await session.scalars(stmt)).first()
            if user is None:
                return None

            raw_token = secrets.token_urlsafe(32)
            token_hash = _hash_token(raw_token)
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(minutes=expiry_minutes)

            reset_entry = PasswordReset(
                token_hash=token_hash,
                user_id=user.id,
                expires_at=expires_at,
                created_at=now,
            )
            session.add(reset_entry)
            await session.commit()
            return raw_token

    async def reset_password(
        self,
        raw_token: str,
        new_password: str,
    ) -> bool:
        if not raw_token or not raw_token.strip():
            return False

        if len(new_password) < 10:
            raise ValueError("New password must be at least 10 characters long.")

        token_hash = _hash_token(raw_token)
        session_factory = self._get_session_factory()

        async with session_factory() as session:
            stmt = select(PasswordReset).where(PasswordReset.token_hash == token_hash)
            reset_entry = (await session.scalars(stmt)).first()
            if reset_entry is None or reset_entry.used_at is not None:
                return False

            now = datetime.now(timezone.utc)
            expires_at = reset_entry.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if expires_at <= now:
                return False

            user = await session.get(User, reset_entry.user_id)
            if user is None:
                return False

            # Mark token used
            reset_entry.used_at = now

            # Update password
            user.hashed_password = self._hasher.hash(new_password)
            user.updated_at = now

            # Cascade revoke all user sessions
            await session.execute(delete(Session).where(Session.user_id == user.id))
            await session.commit()
            return True

    async def change_password(
        self,
        user_id: str,
        old_password: Optional[str] = None,
        new_password: str = "",
        current_password: Optional[str] = None,
    ) -> bool:
        effective_old = current_password if old_password is None else old_password
        if effective_old is None:
            return False

        if len(new_password) < 10:
            raise ValueError("New password must be at least 10 characters long.")

        session_factory = self._get_session_factory()
        async with session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return False

            if not self._hasher.verify(effective_old, user.hashed_password):
                return False

            user.hashed_password = self._hasher.hash(new_password)
            user.updated_at = datetime.now(timezone.utc)
            await session.commit()
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
        effective_search = query if search is None else search
        effective_limit = limit if limit is not None else page_size
        if offset is not None:
            effective_offset = offset
        else:
            effective_offset = max(0, (page - 1) * effective_limit)

        session_factory = self._get_session_factory()
        async with session_factory() as session:
            stmt = select(User)

            if effective_search and effective_search.strip():
                pattern = f"%{effective_search.strip()}%"
                stmt = stmt.where(
                    or_(
                        User.email.ilike(pattern),
                        User.username.ilike(pattern),
                        User.full_name.ilike(pattern),
                    )
                )

            if role is not None and role.strip():
                stmt = stmt.where(User.role == role.strip())

            if status is not None and status.strip():
                stmt = stmt.where(User.status == status.strip())

            # Count total
            count_stmt = select(func.count()).select_from(stmt.subquery())
            total = (await session.scalar(count_stmt)) or 0

            # Fetch page
            paged_stmt = (
                stmt.order_by(User.created_at.desc())
                .offset(effective_offset)
                .limit(effective_limit)
            )
            rows = (await session.scalars(paged_stmt)).all()
            profiles = [self._user_to_profile(r) for r in rows]

            calc_page = (effective_offset // effective_limit) + 1 if effective_limit > 0 else 1
            return PaginatedUsers(
                users=profiles,
                total=total,
                offset=effective_offset,
                limit=effective_limit,
                page=calc_page,
                page_size=effective_limit,
            )

    async def update_user(
        self,
        user_id: str,
        updates: Optional[Union[UserUpdate, Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Optional[UserProfile]:
        patch_dict: Dict[str, Any] = {}
        if isinstance(updates, UserUpdate):
            patch_dict.update(updates.model_dump(exclude_unset=True))
        elif isinstance(updates, dict):
            patch_dict.update(updates)

        patch_dict.update({k: v for k, v in kwargs.items() if v is not None})

        session_factory = self._get_session_factory()
        async with session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None

            status_disabled = False
            for k, v in patch_dict.items():
                if k == "full_name":
                    user.full_name = v
                elif k == "role":
                    user.role = v
                elif k == "status":
                    if v == "disabled" and user.status != "disabled":
                        status_disabled = True
                    user.status = v

            user.updated_at = datetime.now(timezone.utc)

            # If user disabled, immediately revoke all active sessions
            if status_disabled:
                await session.execute(delete(Session).where(Session.user_id == user.id))

            await session.commit()
            await session.refresh(user)
            return self._user_to_profile(user)

    async def has_admin_user(self) -> bool:
        """Returns True if at least one active administrator user exists in the database."""
        session_factory = self._get_session_factory()
        async with session_factory() as session:
            stmt = select(func.count(User.id)).where(User.role == "admin", User.status == "active")
            count = (await session.execute(stmt)).scalar_one()
            return count > 0

