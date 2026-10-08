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

"""Declarative SQLAlchemy models for Carefold authentication and system settings."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, List, Optional
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from carefold.db.base import Base


class User(Base):
    """User account entity for authentication and authorization."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique user identifier (UUID v4 string)",
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
        doc="Normalized unique email address",
    )
    username: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
        doc="Unique username for login and display",
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Argon2id password hash string",
    )
    full_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Human display name",
    )
    role: Mapped[str] = mapped_column(
        String(32),
        default="steward",
        nullable=False,
        doc="Access role: admin, steward, or member",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="active",
        nullable=False,
        doc="Account status: active or disabled",
    )
    auth_provider: Mapped[str] = mapped_column(
        String(32),
        default="local",
        nullable=False,
        doc="Identity source: local, oidc, google, github",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Account creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of most recent successful login (UTC)",
    )

    # Relationships
    sessions: Mapped[List[Session]] = relationship(
        "Session",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    password_resets: Mapped[List[PasswordReset]] = relationship(
        "PasswordReset",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @validates("email")
    def validate_email(self, key: str, address: Optional[str]) -> Optional[str]:
        """Ensures email addresses are normalized to lowercase."""
        if address is not None:
            return address.strip().lower()
        return address

    def __repr__(self) -> str:
        return f"<User id={self.id!r} username={self.username!r} role={self.role!r}>"


class Session(Base):
    """Active user session tracking for stateful cookie/bearer authentication."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        doc="SHA-256 hex digest of the raw session secret token",
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        doc="Referenced User identifier",
    )
    client_ip: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True,
        doc="Client IP address (IPv4 or IPv6)",
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="User agent string of client browser or device",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=False,
        doc="Session expiration timestamp (UTC)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Session issuance timestamp (UTC)",
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Last activity timestamp (UTC) for rolling expiration",
    )

    # Relationship
    user: Mapped[User] = relationship(
        "User",
        back_populates="sessions",
    )

    def __repr__(self) -> str:
        return f"<Session id={self.id[:8]}... user_id={self.user_id!r} expires_at={self.expires_at!s}>"


class PasswordReset(Base):
    """Single-use password reset tokens."""

    __tablename__ = "password_resets"

    token_hash: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        doc="SHA-256 hex digest of the raw password reset token",
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        doc="Referenced User identifier",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=False,
        doc="Reset token expiration timestamp (UTC)",
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when token was consumed; None if unused",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Token issuance timestamp (UTC)",
    )

    # Relationship
    user: Mapped[User] = relationship(
        "User",
        back_populates="password_resets",
    )

    def __repr__(self) -> str:
        return f"<PasswordReset token_hash={self.token_hash[:8]}... user_id={self.user_id!r} used={self.used_at is not None}>"


class SystemSetting(Base):
    """Key-value system setting and runtime configuration storage."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
        doc="Unique configuration key (e.g. auth.provider, llm.default_provider)",
    )
    value_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Serialized JSON representation of the configuration value",
    )
    is_secret: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="True if value contains confidential information that should be masked",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )
    updated_by: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Identifier or username of the user who last changed this setting",
    )

    def get_value(self) -> Any:
        """Deserializes and returns the stored configuration value."""
        return json.loads(self.value_json)

    def set_value(self, val: Any) -> None:
        """Serializes and updates the configuration value."""
        self.value_json = json.dumps(val)

    def __repr__(self) -> str:
        return f"<SystemSetting key={self.key!r} is_secret={self.is_secret}>"
