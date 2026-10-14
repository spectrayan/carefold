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
import enum
import json
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship as sa_relationship, relationship, synonym, validates


from carefold.db.base import Base


def utc_now() -> datetime:
    """Returns current UTC timestamp with timezone."""
    return datetime.now(timezone.utc)


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
    notes: Mapped[List[Note]] = relationship(
        "Note",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    attachments: Mapped[List[Attachment]] = relationship(
        "Attachment",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    chat_threads: Mapped[List[ChatThread]] = relationship(
        "ChatThread",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    profiles: Mapped[List[Profile]] = relationship(
        "Profile",
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sent_invites: Mapped[List[ViewerInvite]] = relationship(
        "ViewerInvite",
        foreign_keys="ViewerInvite.invited_by",
        back_populates="inviter",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    accepted_invites: Mapped[List[ViewerInvite]] = relationship(
        "ViewerInvite",
        foreign_keys="ViewerInvite.accepted_by",
        back_populates="acceptor",
        lazy="selectin",
    )
    connections: Mapped[List[Connection]] = relationship(
        "Connection",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    credentials: Mapped[List[Credential]] = relationship(
        "Credential",
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


class Agent(Base):
    """Agent entity representing both system/bundled specialists and user-defined agents."""

    __tablename__ = "agent"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        doc="Unique agent identifier (e.g. cardiology-guide, custom-nutrition)",
    )
    type: Mapped[str] = mapped_column(
        String(32),
        default="bundled",
        nullable=False,
        index=True,
        doc="Agent type: system, bundled, or user",
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Owner user ID for user-created agents; None for bundled/system",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Agent display name / title",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        doc="Short agent summary or purpose",
    )
    persona: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        doc="Detailed system persona instructions (markdown prompt)",
    )
    model: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="ollama:llama3.2",
        doc="Default model configuration string",
    )
    skills_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        doc="Serialized JSON array of attached skill IDs",
    )
    tools_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        doc="Serialized JSON array of allowed tool names",
    )
    starters_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        doc="Serialized JSON array of sample conversation starter prompts",
    )
    domain: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="clinical",
        doc="Agent domain: clinical, wellness, navigation",
    )
    category: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="general",
        doc="Specialist category (e.g. cardiology, gastroenterology, general)",
    )
    risk_class: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="clinical_assist",
        doc="Clinical risk classification: wellness, admin, clinical_assist, education",
    )
    tags_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        doc="Serialized JSON array of taxonomy tags",
    )
    care_stages_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        doc="Serialized JSON array of care stages (e.g. pre_visit, post_visit)",
    )
    target_audience_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        doc="Serialized JSON array of target audience groups (e.g. patient, caregiver)",
    )
    forbidden_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        doc="Serialized JSON array of forbidden intent tokens",
    )
    icon: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="Bot",
        doc="Lucide icon identifier",
    )
    maturity: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="stable",
        doc="Lifecycle maturity: draft, beta, stable, deprecated",
    )
    can_delegate: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether agent can delegate to other agents",
    )
    max_iterations: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
        doc="Maximum tool iteration turns",
    )
    hidden: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether to hide from marketplace listings",
    )
    is_public: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether visible to other users or public listings",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    user: Mapped[Optional[User]] = relationship("User")

    def get_skills(self) -> List[str]:
        return json.loads(self.skills_json) if self.skills_json else []

    def set_skills(self, skills: List[str]) -> None:
        self.skills_json = json.dumps(skills)

    def get_tools(self) -> List[str]:
        return json.loads(self.tools_json) if self.tools_json else []

    def set_tools(self, tools: List[str]) -> None:
        self.tools_json = json.dumps(tools)

    def get_starters(self) -> List[str]:
        return json.loads(self.starters_json) if self.starters_json else []

    def set_starters(self, starters: List[str]) -> None:
        self.starters_json = json.dumps(starters)

    def get_tags(self) -> List[str]:
        return json.loads(self.tags_json) if self.tags_json else []

    def set_tags(self, tags: List[str]) -> None:
        self.tags_json = json.dumps(tags)

    def get_care_stages(self) -> List[str]:
        return json.loads(self.care_stages_json) if self.care_stages_json else []

    def set_care_stages(self, stages: List[str]) -> None:
        self.care_stages_json = json.dumps(stages)

    def get_target_audience(self) -> List[str]:
        return json.loads(self.target_audience_json) if self.target_audience_json else []

    def set_target_audience(self, audience: List[str]) -> None:
        self.target_audience_json = json.dumps(audience)

    def get_forbidden(self) -> List[str]:
        return json.loads(self.forbidden_json) if self.forbidden_json else []

    def set_forbidden(self, forbidden: List[str]) -> None:
        self.forbidden_json = json.dumps(forbidden)

    def __repr__(self) -> str:
        return f"<Agent id={self.id!r} type={self.type!r} title={self.title!r}>"


class Skill(Base):
    """Skill entity representing both system/bundled skills and user-defined skills."""

    __tablename__ = "skill"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        doc="Unique skill identifier (e.g. cardiology-prep)",
    )
    type: Mapped[str] = mapped_column(
        String(32),
        default="bundled",
        nullable=False,
        index=True,
        doc="Skill type: system, bundled, or user",
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Owner user ID for user-created skills; None for bundled/system",
    )
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        doc="Skill technical name / slug",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Skill display title",
    )
    description: Mapped[Text] = mapped_column(
        Text,
        nullable=False,
        default="",
        doc="Description of skill capability and usage",
    )
    domain: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="clinical",
        doc="Skill domain: clinical, wellness, navigation",
    )
    category: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="general",
        doc="Skill category (e.g. cardiology, pulmonology, general)",
    )
    risk_class: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="clinical_assist",
        doc="Clinical risk classification: wellness, admin, clinical_assist, education",
    )
    tags_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        doc="Serialized JSON array of taxonomy tags",
    )
    tools_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        doc="Serialized JSON array of allowed tool names",
    )
    instructions: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        doc="Skill instruction body with safety boundaries and guidelines",
    )
    forbidden_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        doc="Serialized JSON array of forbidden patterns / actions",
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether clinical safety review has verified this skill",
    )
    is_public: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether visible to other users or public listings",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    user: Mapped[Optional[User]] = relationship("User")

    def get_tags(self) -> List[str]:
        return json.loads(self.tags_json) if self.tags_json else []

    def set_tags(self, tags: List[str]) -> None:
        self.tags_json = json.dumps(tags)

    def get_tools(self) -> List[str]:
        return json.loads(self.tools_json) if self.tools_json else []

    def set_tools(self, tools: List[str]) -> None:
        self.tools_json = json.dumps(tools)

    def get_forbidden(self) -> List[str]:
        return json.loads(self.forbidden_json) if self.forbidden_json else []

    def set_forbidden(self, forbidden: List[str]) -> None:
        self.forbidden_json = json.dumps(forbidden)

    def __repr__(self) -> str:
        return f"<Skill id={self.id!r} type={self.type!r} title={self.title!r}>"


class KnowledgeBase(Base):
    """Reference document entity in knowledge base attached to agents, skills, or global scope."""

    __tablename__ = "knowledge_base"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique knowledge base document identifier (UUID)",
    )
    type: Mapped[str] = mapped_column(
        String(32),
        default="bundled",
        nullable=False,
        index=True,
        doc="Document source type: bundled or user",
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Owner user ID for user-created documents; None for bundled",
    )
    target_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        doc="Attachment target type: agent, skill, or global",
    )
    target_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Identifier of the target agent or skill (e.g. cardiology-prep)",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        doc="Document filename (e.g. hypertension_protocol.md)",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Human-readable document title",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        doc="Raw document text or markdown content",
    )
    format: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="markdown",
        doc="Document format: markdown, text",
    )
    size_bytes: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Size of content in bytes",
    )
    metadata_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
        doc="Serialized JSON metadata dictionary",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    __table_args__ = (
        UniqueConstraint("target_type", "target_id", "name", name="uq_kb_target_name"),
    )

    user: Mapped[Optional[User]] = relationship("User")

    def get_metadata(self) -> dict[str, Any]:
        return json.loads(self.metadata_json) if self.metadata_json else {}

    def set_metadata(self, meta: dict[str, Any]) -> None:
        self.metadata_json = json.dumps(meta)

    def __repr__(self) -> str:
        return f"<KnowledgeBase id={self.id!r} target={self.target_type}:{self.target_id} name={self.name!r}>"


class Profile(Base):
    """Family / care profile entity representing an individual receiving care."""

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique profile identifier (UUID v4 string)",
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
        doc="Account owner user identifier (nullable for single-user offline mode)",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Profile display name (e.g. Leo, Mom, Me)",
    )
    relationship: Mapped[str] = mapped_column(
        String(64),
        default="self",
        nullable=False,
        doc="Relationship to account owner: self, child, parent, partner, spouse, other",
    )
    role: Mapped[str] = mapped_column(
        String(32),
        default="self",
        nullable=False,
        doc="Profile role: self, guardian, viewer",
    )
    date_of_birth: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        doc="Date of birth formatted as YYYY-MM-DD",
    )
    avatar_color: Mapped[str] = mapped_column(
        String(32),
        default="1",
        nullable=False,
        doc="Avatar color slot: 1, 2, 3, 4, 5, or auto",
    )
    short_name: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="Short display name / nickname for the profile (e.g. Leo, Mom)",
    )
    avatar_url: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        doc="Uploaded avatar image URL or asset storage key",
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether this is the primary self/steward profile",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    # Relationships
    owner: Mapped[User] = sa_relationship("User", back_populates="profiles")
    access_grants: Mapped[List[ProfileAccess]] = sa_relationship(
        "ProfileAccess",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    viewer_invites: Mapped[List[ViewerInvite]] = sa_relationship(
        "ViewerInvite",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    consent: Mapped[Optional[ProfileConsent]] = sa_relationship(
        "ProfileConsent",
        back_populates="profile",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    notes: Mapped[List[Note]] = sa_relationship(
        "Note",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    attachments: Mapped[List[Attachment]] = sa_relationship(
        "Attachment",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    chat_threads: Mapped[List[ChatThread]] = sa_relationship(
        "ChatThread",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    connections: Mapped[List[Connection]] = sa_relationship(
        "Connection",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    credentials: Mapped[List[Credential]] = sa_relationship(
        "Credential",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    profile_keys: Mapped[List[ProfileKey]] = sa_relationship(
        "ProfileKey",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    approvals: Mapped[List[Approval]] = sa_relationship(
        "Approval",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    jobs: Mapped[List[Job]] = sa_relationship(
        "Job",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    health_resources: Mapped[List[HealthResource]] = sa_relationship(
        "HealthResource",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    appointments: Mapped[List[Appointment]] = sa_relationship(
        "Appointment",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reminders: Mapped[List[Reminder]] = sa_relationship(
        "Reminder",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    preventive_records: Mapped[List[PreventiveRecord]] = sa_relationship(
        "PreventiveRecord",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    import_batches: Mapped[List[ImportBatch]] = sa_relationship(
        "ImportBatch",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    school_forms: Mapped[List[SchoolForm]] = sa_relationship(
        "SchoolForm",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    consent_grants: Mapped[List[ConsentGrant]] = sa_relationship(
        "ConsentGrant",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sync_runs: Mapped[List[SyncRun]] = sa_relationship(
        "SyncRun",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    routines: Mapped[List[Routine]] = sa_relationship(
        "Routine",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    mcp_tool_pins: Mapped[List[McpToolPin]] = sa_relationship(
        "McpToolPin",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    email_drafts: Mapped[List[EmailDraft]] = sa_relationship(
        "EmailDraft",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    school_ics_feeds: Mapped[List[SchoolIcsFeed]] = sa_relationship(
        "SchoolIcsFeed",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    companion_devices: Mapped[List[CompanionDevice]] = sa_relationship(
        "CompanionDevice",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Profile id={self.id!r} name={self.name!r} relationship={self.relationship!r} role={self.role!r}>"


class ProfileAccess(Base):
    """Access grant authorizing a user to interact with a specific profile."""

    __tablename__ = "profile_access"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique access grant identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        doc="Referenced profile identifier",
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
        doc="Authorized user identifier",
    )
    granted_by: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="User ID of account owner or steward who issued the grant",
    )
    role: Mapped[str] = mapped_column(
        String(32),
        default="viewer",
        nullable=False,
        doc="Access role: viewer, guardian, self",
    )
    access_level: Mapped[str] = mapped_column(
        String(32),
        default="manage",
        nullable=False,
        doc="Access level: manage, view_clinical, view_paperwork",
    )
    allowed_sections_json: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Optional JSON array of permitted viewer sections (e.g. ['vitals', 'appointments', 'connections'])",
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Access grant timestamp (UTC)",
    )

    __table_args__ = (
        UniqueConstraint("profile_id", "user_id", name="uq_profile_access_user"),
    )

    # Relationships
    profile: Mapped[Profile] = relationship("Profile", back_populates="access_grants")
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    grantor: Mapped[Optional[User]] = relationship("User", foreign_keys=[granted_by])

    @property
    def allowed_sections(self) -> Optional[List[str]]:
        if not self.allowed_sections_json:
            return None
        try:
            return json.loads(self.allowed_sections_json)
        except Exception:
            return None

    def __repr__(self) -> str:
        return f"<ProfileAccess profile_id={self.profile_id!r} user_id={self.user_id!r} level={self.access_level!r}>"


class ProfileConsent(Base):
    """Clinical consent tracking and teen handover reminder state for a profile."""

    __tablename__ = "profile_consents"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique consent record identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
        doc="Referenced profile identifier",
    )
    consented_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when clinical consent was explicitly acknowledged (UTC)",
    )
    terms_version: Mapped[str] = mapped_column(
        String(32),
        default="v1.0",
        nullable=False,
        doc="Clinical consent terms version string",
    )
    allow_clinical: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether clinical-assist agents and skills are authorized for this profile",
    )
    teen_handover_notified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether 90-day teen handover reminder notification has been dispatched",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    # Relationships
    profile: Mapped[Profile] = relationship("Profile", back_populates="consent")

    def __repr__(self) -> str:
        return f"<ProfileConsent profile_id={self.profile_id!r} allow_clinical={self.allow_clinical}>"


class ViewerInvite(Base):
    """Pending or accepted read-only invitation for household viewer access."""

    __tablename__ = "viewer_invites"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique invitation identifier (UUID v4 string)",
    )
    invite_code: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
        doc="Unique redemption code (e.g. cf-inv-XXXXXX)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        doc="Referenced care profile identifier",
    )
    invited_by: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
        doc="User ID of account steward who issued the invite (nullable for offline mode)",
    )
    invitee_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Display name of the invited individual (e.g. Grandma, Caregiver John)",
    )
    role: Mapped[str] = mapped_column(
        String(32),
        default="viewer",
        nullable=False,
        doc="Access role to grant upon acceptance: viewer",
    )
    view_clinical: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether viewer is authorized to view clinical notes and prep guides",
    )
    view_paperwork: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether viewer is authorized to view administrative paperwork and insurance documents",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Timestamp when the invitation expires (UTC)",
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the invitation was accepted (UTC)",
    )
    accepted_by: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
        doc="User ID of the member who accepted the invite",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    # Relationships
    profile: Mapped[Profile] = relationship("Profile", back_populates="viewer_invites", lazy="selectin")
    inviter: Mapped[Optional[User]] = relationship(
        "User",
        foreign_keys=[invited_by],
        back_populates="sent_invites",
        lazy="selectin",
    )
    acceptor: Mapped[Optional[User]] = relationship(
        "User",
        foreign_keys=[accepted_by],
        back_populates="accepted_invites",
        lazy="selectin",
    )

    def is_expired(self) -> bool:
        """Determines if the invitation has passed its expiration time."""
        now = datetime.now(timezone.utc)
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return now > exp

    def is_accepted(self) -> bool:
        """Determines if the invitation has been redeemed."""
        return self.accepted_at is not None

    def __repr__(self) -> str:
        return (
            f"<ViewerInvite id={self.id!r} code={self.invite_code!r} "
            f"profile_id={self.profile_id!r} invitee={self.invitee_name!r}>"
        )


class Note(Base):
    """Note entity for user clinical visit notes, prep items, and summaries."""

    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_profile_id_type", "profile_id", "type"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique note identifier (UUID)",
    )
    type: Mapped[str] = mapped_column(
        String(32),
        default="scratchpad",
        nullable=False,
        index=True,
        doc="Note category: scratchpad, clinical_prep, visit_summary, general",
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        doc="Referenced User identifier (nullable for single-user offline mode)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    slug: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        doc="Note slug or filename identifier",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Note title",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        doc="Markdown content of the note",
    )
    tags_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        doc="Serialized JSON array of note tags",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    linked_appointment_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Referenced Appointment identifier (nullable foreign key)",
    )

    user: Mapped[Optional[User]] = relationship("User", back_populates="notes")
    profile: Mapped[Profile] = relationship("Profile", back_populates="notes")
    appointment: Mapped[Optional[Appointment]] = relationship(
        "Appointment",
        back_populates="notes",
        foreign_keys=[linked_appointment_id],
    )
    linked_appointment = synonym("appointment")

    @property
    def tags(self) -> List[str]:
        """List of tags deserialized from tags_json."""
        return self.get_tags()

    @tags.setter
    def tags(self, value: Optional[List[str]]) -> None:
        """Serializes list of tags into tags_json."""
        self.set_tags(value if value is not None else [])

    def get_tags(self) -> List[str]:
        return json.loads(self.tags_json) if self.tags_json else []

    def set_tags(self, tags: List[str]) -> None:
        self.tags_json = json.dumps(tags)

    def __repr__(self) -> str:
        return f"<Note id={self.id!r} slug={self.slug!r} title={self.title!r}>"


class Attachment(Base):
    """Attachment document entity uploaded by users."""

    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique attachment identifier (UUID)",
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        doc="Owner user identifier; None for offline single-user mode",
    )
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        doc="Owner profile identifier; None for unassigned/legacy attachments",
    )
    storage_key: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        index=True,
        doc="Canonical storage key used by StoragePort (e.g. user_id/profile_id/filename)",
    )
    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        doc="Sanitized unique filename on disk/storage",
    )
    original_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Original uploaded filename from client",
    )
    content_type: Mapped[str] = mapped_column(
        String(128),
        default="application/octet-stream",
        nullable=False,
        doc="MIME content type of attachment (alias: mime_type)",
    )
    size_bytes: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="File size in bytes (alias: size, byte_size, file_size)",
    )
    sha256_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        doc="SHA-256 hex digest for cryptographic integrity and deduplication",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Upload timestamp (UTC)",
    )
    extracted_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Extracted plain text layer (from PDFs, Markdown, TXT, CSV)",
    )
    source: Mapped[str] = mapped_column(
        String(64),
        default="upload",
        server_default="upload",
        nullable=False,
        index=True,
        doc="Origin of attachment: upload, connector, agent, export",
    )
    source_ref: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="External reference tracking: connector stream ID, remote document URI, or message ID",
    )
    extraction_status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
        server_default="pending",
        nullable=False,
        index=True,
        doc="Processing lifecycle state: pending, completed, failed, not_applicable",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    # Relationships
    user: Mapped[Optional[User]] = relationship("User", back_populates="attachments")
    profile: Mapped[Optional[Profile]] = relationship("Profile", back_populates="attachments")

    def __init__(self, **kwargs: Any) -> None:
        """Initializes Attachment, mapping backward-compatible aliases to canonical columns."""
        # Normalize legacy and unified field aliases
        if "file_name" in kwargs and "filename" not in kwargs:
            kwargs["filename"] = kwargs.pop("file_name")
        if "file_size" in kwargs and "size_bytes" not in kwargs:
            kwargs["size_bytes"] = kwargs.pop("file_size")
        if "byte_size" in kwargs and "size_bytes" not in kwargs:
            kwargs["size_bytes"] = kwargs.pop("byte_size")
        if "size" in kwargs and "size_bytes" not in kwargs:
            kwargs["size_bytes"] = kwargs.pop("size")
        if "mime_type" in kwargs and "content_type" not in kwargs:
            kwargs["content_type"] = kwargs.pop("mime_type")
        if "mime" in kwargs and "content_type" not in kwargs:
            kwargs["content_type"] = kwargs.pop("mime")
        if "sha256" in kwargs and "sha256_hash" not in kwargs:
            kwargs["sha256_hash"] = kwargs.pop("sha256")
        if "file_path" in kwargs and "storage_key" not in kwargs:
            kwargs["storage_key"] = kwargs.pop("file_path")
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    # -------------------------------------------------------------------------
    # Backward Compatibility & Unified Properties
    # -------------------------------------------------------------------------

    @property
    def mime(self) -> str:
        """Unified standard alias for content_type."""
        return self.content_type

    @mime.setter
    def mime(self, value: str) -> None:
        self.content_type = value

    @property
    def size(self) -> int:
        """Unified standard alias for size_bytes."""
        return self.size_bytes

    @size.setter
    def size(self, value: int) -> None:
        self.size_bytes = value

    @property
    def sha256(self) -> Optional[str]:
        """Unified standard alias for sha256_hash."""
        return self.sha256_hash

    @sha256.setter
    def sha256(self, value: Optional[str]) -> None:
        self.sha256_hash = value

    @property
    def file_path(self) -> str:
        """Backward compatibility alias returning storage_key or synthesizing path from scoping."""
        return self.get_storage_key()

    @file_path.setter
    def file_path(self, value: Optional[str]) -> None:
        """Updates storage_key when legacy file_path is modified."""
        self.storage_key = value

    @property
    def file_name(self) -> str:
        """Backward compatibility alias for filename."""
        return self.filename

    @file_name.setter
    def file_name(self, value: str) -> None:
        self.filename = value

    @property
    def file_size(self) -> int:
        """Backward compatibility alias for size_bytes."""
        return self.size_bytes

    @file_size.setter
    def file_size(self, value: int) -> None:
        self.size_bytes = value

    @property
    def byte_size(self) -> int:
        """Standard R3 alias for size_bytes."""
        return self.size_bytes

    @byte_size.setter
    def byte_size(self, value: int) -> None:
        self.size_bytes = value

    @property
    def mime_type(self) -> str:
        """Standard R3 alias for content_type."""
        return self.content_type

    @mime_type.setter
    def mime_type(self, value: str) -> None:
        self.content_type = value

    def get_storage_key(self) -> str:
        """Returns storage_key if present, or synthesizes a partitioned key based on tenant scoping."""
        if self.storage_key:
            return self.storage_key
        if self.user_id and self.profile_id:
            return f"{self.user_id}/{self.profile_id}/{self.filename}"
        elif self.user_id:
            return f"{self.user_id}/{self.filename}"
        elif self.profile_id:
            return f"{self.profile_id}/{self.filename}"
        return self.filename

    def __repr__(self) -> str:
        return (
            f"<Attachment id={self.id!r} filename={self.filename!r} "
            f"storage_key={self.storage_key!r} user_id={self.user_id!r} "
            f"sha256={self.sha256_hash!r}>"
        )


class ChatThread(Base):
    """Conversation thread tracking entity for session persistence and access control."""

    __tablename__ = "chat_threads"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        doc="Unique thread identifier (thread_id matching SQLite checkpointer)",
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        doc="Owner user identifier; None for offline single-user mode",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Owner profile identifier (strictly scoped, non-nullable)",
    )
    agent_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Specialist agent identifier (e.g. visit-steward, cardiology-guide)",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        default="New Consultation",
        nullable=False,
        doc="Conversation session display title",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    user: Mapped[Optional[User]] = relationship("User", back_populates="chat_threads")
    profile: Mapped[Profile] = relationship("Profile", back_populates="chat_threads")

    def __repr__(self) -> str:
        return f"<ChatThread id={self.id!r} agent_id={self.agent_id!r} user_id={self.user_id!r}>"


class AuditEventRecord(Base):
    """Database-backed audit logging entity for clinical safety and tool execution auditing."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique audit record UUID",
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
        nullable=False,
        doc="Event issuance UTC timestamp",
    )
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Referenced CareProfile identifier",
    )
    actor_user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Authenticated user UUID who triggered the action",
    )
    principal: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="user",
        doc="Execution principal: user, agent, orchestrator, connector",
    )
    run_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        doc="Workflow execution or LangGraph thread/run identifier",
    )
    event: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Event type: run, tool, refuse, error, boundary_warning",
    )
    tool: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        doc="Invoked tool name if event is tool execution",
    )
    risk: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
        doc="Risk class classification at execution time",
    )
    decision: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
        doc="Policy decision: allow, refuse, modify, error",
    )
    payload_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="Cryptographic SHA-256 digest of input parameters/payload",
    )
    external_ref: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="External stream identifier, connector sync ID, or message ID",
    )
    detail_redacted: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Serialized JSON dictionary containing sanitized metadata and durations",
    )
    prev_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="Previous audit event SHA-256 entry_hash in the profile chain ('GENESIS' for first event)",
    )
    entry_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        doc="Tamper-evident SHA-256 hash chaining this audit record to prev_hash",
    )

    profile: Mapped[Optional[Profile]] = relationship("Profile")
    actor: Mapped[Optional[User]] = relationship("User")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "ts" not in kwargs:
            kwargs["ts"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<AuditEventRecord id={self.id!r} event={self.event!r} tool={self.tool!r} profile_id={self.profile_id!r}>"


class ConnectionState(str, enum.Enum):
    """Lifecycle states for external connectors bound to patient profiles."""

    PENDING_AUTH = "pending_auth"
    ACTIVE = "active"
    DEGRADED = "degraded"
    NEEDS_REAUTH = "needs_reauth"
    REVOKED = "revoked"
    DELETED = "deleted"


class Connection(Base):
    """External connector link bound to a patient profile with a state machine."""

    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique connection identifier (UUID v4)",
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        doc="Owner user ID",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        doc="Associated patient profile ID",
    )
    connector_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        doc="Connector identifier matching ConnectorManifest.id (e.g. 'epic-mychart')",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending_auth",
        nullable=False,
        index=True,
        doc="State machine: pending_auth, active, degraded, needs_reauth, revoked, deleted",
    )
    state = synonym("status")
    label: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Human display label (e.g. 'City General Hospital')",
    )
    status_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Explanation of degraded or error state",
    )
    sync_cursor: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Opaque sync checkpoint cursor",
    )
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of last successful stream ingestion (UTC)",
    )
    config_json: Mapped[str] = mapped_column(
        Text,
        default="{}",
        nullable=False,
        doc="Serialized connector configuration JSON",
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Consecutive sync failures counter (3 failures transition active -> degraded)",
    )
    consented_version: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
        doc="Connector manifest version under which active consent was granted",
    )
    autonomy_level: Mapped[str] = mapped_column(
        String(16),
        default="inherit",
        server_default="inherit",
        nullable=False,
        doc="Per-connector autonomy level override: inherit, A0, A1, A2 (AU-58)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="connections")
    profile: Mapped[Profile] = relationship("Profile", back_populates="connections")
    credentials: Mapped[List[Credential]] = relationship(
        "Credential",
        back_populates="connection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    consent_grants: Mapped[List[ConsentGrant]] = relationship(
        "ConsentGrant",
        back_populates="connection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sync_runs: Mapped[List[SyncRun]] = relationship(
        "SyncRun",
        back_populates="connection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    routines: Mapped[List[Routine]] = relationship(
        "Routine",
        back_populates="connection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    mcp_tool_pins: Mapped[List[McpToolPin]] = relationship(
        "McpToolPin",
        back_populates="connection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "state" in kwargs and "status" not in kwargs:
            kwargs["status"] = kwargs.pop("state")
        if "consecutive_failures" not in kwargs:
            kwargs["consecutive_failures"] = 0
        if "autonomy_level" not in kwargs:
            kwargs["autonomy_level"] = "inherit"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<Connection id={self.id!r} connector_id={self.connector_id!r} state={self.state!r} profile_id={self.profile_id!r}>"


class Credential(Base):
    """Encrypted credential vault entry with token_version optimistic concurrency and AAD binding."""

    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique credential identifier (UUID v4)",
    )
    connection_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("connections.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        doc="Parent connection ID",
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
        doc="User ID",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        doc="Patient profile ID",
    )
    encrypted_blob: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Encrypted credential payload (ciphertext)",
    )
    encrypted_data = synonym("encrypted_blob")
    token_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        doc="Optimistic concurrency version for rotating refresh tokens",
    )
    dek_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        doc="Data Encryption Key version under which this credential was encrypted",
    )
    aad_binding: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Cryptographic Additional Authenticated Data binding string (e.g. carefold:p:{profile_id}:c:{connection_id})",
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Access token expiration timestamp (UTC)",
    )
    rotated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Last token rotation timestamp (UTC)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    # Relationships
    connection: Mapped[Connection] = relationship("Connection", back_populates="credentials")
    user: Mapped[Optional[User]] = relationship("User", back_populates="credentials")
    profile: Mapped[Profile] = relationship("Profile", back_populates="credentials")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "encrypted_data" in kwargs and "encrypted_blob" not in kwargs:
            kwargs["encrypted_blob"] = kwargs.pop("encrypted_data")
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<Credential id={self.id!r} connection_id={self.connection_id!r} token_version={self.token_version} dek_version={self.dek_version}>"


class ProfileKey(Base):
    """Cryptographic Data Encryption Key (DEK) envelope storage per profile."""

    __tablename__ = "profile_keys"
    __table_args__ = (
        UniqueConstraint("profile_id", "dek_version", name="uq_profile_keys_profile_id_dek_version"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique profile key identifier (UUID v4)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        doc="Patient profile ID (foreign key with cascade crypto-shredding)",
    )
    encrypted_dek: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Encrypted DEK ciphertext (12-byte nonce + 32-byte ct + 16-byte tag, stored as text/hex)",
    )
    dek_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        doc="Data Encryption Key version number",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Key generation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Key last modification timestamp (UTC)",
    )

    # Relationships
    profile: Mapped[Profile] = relationship("Profile", back_populates="profile_keys")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "encrypted_dek" in kwargs and isinstance(kwargs["encrypted_dek"], bytes):
            kwargs["encrypted_dek"] = kwargs["encrypted_dek"].hex()
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    @property
    def encrypted_dek_bytes(self) -> bytes:
        """Helper returning ciphertext bytes whether stored as hex or raw string."""
        if isinstance(self.encrypted_dek, bytes):
            return self.encrypted_dek
        try:
            return bytes.fromhex(self.encrypted_dek)
        except ValueError:
            return self.encrypted_dek.encode("utf-8")

    def __repr__(self) -> str:
        return f"<ProfileKey id={self.id!r} profile_id={self.profile_id!r} dek_version={self.dek_version}>"


class Approval(Base):
    """Human-in-the-loop tool execution approval record with single-use token semantics (AU-18)."""

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique approval request identifier (UUID v4)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        doc="Target profile ID",
    )
    run_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
        doc="Workflow execution run identifier",
    )
    thread_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        index=True,
        nullable=True,
        doc="LangGraph conversation thread identifier",
    )
    tool_name: Mapped[str] = mapped_column(
        String(128),
        index=True,
        nullable=False,
        doc="Target tool specification name",
    )
    args_redacted: Mapped[str] = mapped_column(
        Text,
        default="{}",
        nullable=False,
        doc="Redacted tool invocation arguments serialized as canonical JSON",
    )
    payload_hash: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
        doc="SHA-256 digest of canonical JSON tool arguments",
    )
    destination_hosts: Mapped[Optional[str]] = mapped_column(
        Text,
        default="[]",
        nullable=True,
        doc="Allowed outbound destination hostnames as JSON list",
    )
    risk_tier: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="Tool risk tier: read, write_local, write_external, irreversible",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
        index=True,
        nullable=False,
        doc="Lifecycle state: pending, approved, rejected, consumed, expired",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=False,
        doc="Approval expiration timestamp (UTC)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Approval creation timestamp (UTC)",
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Steward decision timestamp (UTC)",
    )
    decided_by: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        doc="Identifier of user/steward granting or rejecting approval",
    )

    # Relationships
    profile: Mapped[Profile] = relationship("Profile", back_populates="approvals")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "args_redacted" in kwargs and isinstance(kwargs["args_redacted"], (dict, list)):
            kwargs["args_redacted"] = json.dumps(kwargs["args_redacted"])
        if "destination_hosts" in kwargs and isinstance(kwargs["destination_hosts"], (list, tuple)):
            kwargs["destination_hosts"] = json.dumps(list(kwargs["destination_hosts"]))
        if "expires_at" in kwargs and isinstance(kwargs["expires_at"], (int, float)):
            kwargs["expires_at"] = datetime.fromtimestamp(kwargs["expires_at"], tz=timezone.utc)
        if "decided_at" in kwargs and isinstance(kwargs["decided_at"], (int, float)):
            kwargs["decided_at"] = datetime.fromtimestamp(kwargs["decided_at"], tz=timezone.utc)
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        super().__init__(**kwargs)

    @property
    def args_dict(self) -> Dict[str, Any]:
        """Parsed arguments dictionary."""
        try:
            return json.loads(self.args_redacted)
        except Exception:
            return {}

    @property
    def hosts_list(self) -> List[str]:
        """Parsed destination hosts list."""
        try:
            return json.loads(self.destination_hosts or "[]")
        except Exception:
            return []

    def __repr__(self) -> str:
        return f"<Approval id={self.id!r} tool={self.tool_name!r} status={self.status!r} risk={self.risk_tier!r}>"


class Job(Base):
    """Wall-clock scheduled and background routine job entity with atomic leasing (AU-21)."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique job identifier (UUID v4)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        doc="Target profile ID",
    )
    kind: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
        doc="Job kind: routine, connector_sync, reminder",
    )
    routine_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        index=True,
        nullable=True,
        doc="Associated routine definition identifier",
    )
    connection_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        index=True,
        nullable=True,
        doc="Associated connector connection identifier",
    )
    payload: Mapped[str] = mapped_column(
        Text,
        default="{}",
        nullable=False,
        doc="Serialized parameters and context for job execution",
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="UTC",
        nullable=False,
        doc="IANA timezone string for recurrence evaluation",
    )
    rrule: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="RFC 5545 recurrence rule string",
    )
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=False,
        doc="Next scheduled execution timestamp (UTC)",
    )
    lease_owner: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="Worker ID currently holding execution lease lock",
    )
    lease_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=True,
        doc="Lease expiration timestamp (UTC)",
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Failed execution retry counter",
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(255),
        index=True,
        nullable=True,
        doc="Unique idempotency key for job scheduling deduplication",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
        index=True,
        nullable=False,
        doc="Execution state: pending, active, completed, failed, missed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Job creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Job modification timestamp (UTC)",
    )

    # Relationships
    profile: Mapped[Profile] = relationship("Profile", back_populates="jobs")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "payload" in kwargs and isinstance(kwargs["payload"], (dict, list)):
            kwargs["payload"] = json.dumps(kwargs["payload"])
        if "next_run_at" in kwargs and isinstance(kwargs["next_run_at"], (int, float)):
            kwargs["next_run_at"] = datetime.fromtimestamp(kwargs["next_run_at"], tz=timezone.utc)
        if "lease_until" in kwargs and isinstance(kwargs["lease_until"], (int, float)):
            kwargs["lease_until"] = datetime.fromtimestamp(kwargs["lease_until"], tz=timezone.utc)
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    @property
    def payload_dict(self) -> Dict[str, Any]:
        """Parsed payload dictionary."""
        try:
            return json.loads(self.payload)
        except Exception:
            return {}

    def __repr__(self) -> str:
        return f"<Job id={self.id!r} kind={self.kind!r} status={self.status!r} next_run_at={self.next_run_at!s}>"


# ---------------------------------------------------------------------------
# Clinical and Temporal Foundations (Autonomy Batch 3)
# ---------------------------------------------------------------------------


class HealthResource(Base):
    """Clinical health resource entity representing FHIR R4 Observations, vitals, and metrics."""

    __tablename__ = "health_resources"
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "source_type", "source_ref", "source_id",
            name="uq_health_resources_source",
        ),
        Index("ix_health_resources_profile_type_effective", "profile_id", "resource_type", "effective_at"),
        Index("ix_health_resources_effective_at", "effective_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique health resource identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    resource_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="FHIR resource category (e.g. observation)",
    )
    source_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Origin source type: manual, device, note_extracted",
    )
    source_ref: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Source document reference identifier or external URI",
    )
    source_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="External identifier in source system for idempotency",
    )
    content_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="SHA-256 digest of clinical content",
    )
    data: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        doc="Complete FHIR R4 JSON representation of the resource",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="active",
        nullable=False,
        doc="Status: active, amended, tombstone",
    )
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Clinically relevant observation timestamp (UTC)",
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="System ingestion or entry timestamp (UTC)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    # Relationships
    profile: Mapped[Profile] = relationship("Profile", back_populates="health_resources")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "status" not in kwargs:
            kwargs["status"] = "active"
        if "recorded_at" not in kwargs:
            kwargs["recorded_at"] = utc_now()
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<HealthResource id={self.id!r} profile_id={self.profile_id!r} type={self.resource_type!r} status={self.status!r}>"


class Appointment(Base):
    """Clinical appointment and scheduling navigation entity."""

    __tablename__ = "appointments"
    __table_args__ = (
        Index("ix_appointments_start_time", "start_time"),
        Index("ix_appointments_status", "status"),
        Index("ix_appointments_profile_start", "profile_id", "start_time"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique appointment identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Appointment title or encounter description",
    )
    provider_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Healthcare provider or clinic name",
    )
    specialty: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
        doc="Medical specialty (e.g. Cardiology, Endocrinology)",
    )
    location: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Physical clinic address, department, or telehealth URL",
    )
    clinic_phone: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="Clinic or scheduler contact phone number",
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Scheduled appointment start timestamp (UTC)",
    )
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Scheduled appointment end timestamp (UTC)",
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="UTC",
        nullable=False,
        doc="Local appointment IANA timezone identifier",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="scheduled",
        nullable=False,
        doc="Appointment status: requested, scheduled, confirmed, completed, cancelled",
    )
    reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Chief complaint or purpose of appointment",
    )
    preparation_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Pre-visit preparation checklist or instructions",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    # Relationships
    profile: Mapped[Profile] = relationship("Profile", back_populates="appointments")
    notes: Mapped[List[Note]] = relationship(
        "Note",
        back_populates="appointment",
        passive_deletes=True,
    )

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "timezone" not in kwargs:
            kwargs["timezone"] = "UTC"
        if "status" not in kwargs:
            kwargs["status"] = "scheduled"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<Appointment id={self.id!r} profile_id={self.profile_id!r} title={self.title!r} status={self.status!r}>"


class Reminder(Base):
    """Clinical and administrative reminder entity supporting RFC 5545 RRULE recurrence."""

    __tablename__ = "reminders"
    __table_args__ = (
        Index("ix_reminders_next_due_at", "next_due_at"),
        Index("ix_reminders_status", "status"),
        Index("ix_reminders_category", "category"),
        Index("ix_reminders_profile_status_due", "profile_id", "status", "next_due_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique reminder identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Reminder prompt or directive title",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Detailed context, instructions, or medication dosage guidelines",
    )
    category: Mapped[str] = mapped_column(
        String(64),
        default="general",
        nullable=False,
        doc="Reminder category: medication, vitals, appointment, prep, general",
    )
    rrule: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="RFC 5545 recurrence rule specification string",
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="UTC",
        nullable=False,
        doc="Local profile IANA timezone for recurrence evaluation",
    )
    next_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Next scheduled trigger timestamp (UTC)",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
        nullable=False,
        doc="Status: pending, completed, snoozed, missed, cancelled",
    )
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of most recent execution (UTC)",
    )
    snooze_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Snoozed wake timestamp (UTC)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    # Relationships
    profile: Mapped[Profile] = relationship("Profile", back_populates="reminders")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "category" not in kwargs:
            kwargs["category"] = "general"
        if "timezone" not in kwargs:
            kwargs["timezone"] = "UTC"
        if "status" not in kwargs:
            kwargs["status"] = "pending"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<Reminder id={self.id!r} profile_id={self.profile_id!r} title={self.title!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# Preventive Care, Clinical Imports & Pediatric Forms (Autonomy Batch 4)
# ---------------------------------------------------------------------------


class PreventiveRecord(Base):
    """Per-profile preventive screening and immunisation tracking entity (AU-36)."""

    __tablename__ = "preventive_records"
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "rule_id",
            name="uq_preventive_records_profile_rule",
        ),
        Index("ix_preventive_records_profile_status", "profile_id", "status"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique preventive record identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    rule_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        doc="Preventive rule identifier from YAML rule pack (e.g. uspstf-colorectal-screening)",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="due",
        nullable=False,
        index=True,
        doc="Status: due, completed, not_applicable, declined",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when screening or immunisation was completed (UTC)",
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Optional user or provider notes for this preventive item",
    )
    schedule_source: Mapped[str] = mapped_column(
        String(32),
        default="aap_2026",
        nullable=False,
        doc="Immunisation schedule source setting: aap_2026 or cdc",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    profile: Mapped[Profile] = relationship("Profile", back_populates="preventive_records")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "status" not in kwargs:
            kwargs["status"] = "due"
        if "schedule_source" not in kwargs:
            kwargs["schedule_source"] = "aap_2026"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<PreventiveRecord id={self.id!r} profile_id={self.profile_id!r} "
            f"rule_id={self.rule_id!r} status={self.status!r}>"
        )


class ImportBatch(Base):
    """Clinical and wearable file import staging and provenance batch entity (AU-38)."""

    __tablename__ = "import_batches"
    __table_args__ = (
        Index("ix_import_batches_profile_status", "profile_id", "status"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique import batch identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    attachment_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Source CAS attachment identifier (E13)",
    )
    format: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="Import file format: fhir_r4, ccda, apple_health",
    )
    source_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Human-readable provenance origin (e.g. 'Apple Health Export', 'Epic C-CDA')",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="staged",
        nullable=False,
        index=True,
        doc="Lifecycle status: staged, committed, discarded",
    )
    summary_json: Mapped[str] = mapped_column(
        Text,
        default="{}",
        nullable=False,
        doc="Serialized JSON summary of parsed counts, categories, and date ranges",
    )
    staged_records_json: Mapped[str] = mapped_column(
        Text,
        default="[]",
        nullable=False,
        doc="Serialized JSON array of normalized FHIR records staged for review-before-save",
    )
    committed_resource_ids_json: Mapped[str] = mapped_column(
        Text,
        default="[]",
        nullable=False,
        doc="Serialized JSON array of health_resources IDs created on commit (for undo)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Staging creation timestamp (UTC)",
    )
    committed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Commit timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    profile: Mapped[Profile] = relationship("Profile", back_populates="import_batches")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "status" not in kwargs:
            kwargs["status"] = "staged"
        if "summary_json" not in kwargs:
            kwargs["summary_json"] = "{}"
        if "staged_records_json" not in kwargs:
            kwargs["staged_records_json"] = "[]"
        if "committed_resource_ids_json" not in kwargs:
            kwargs["committed_resource_ids_json"] = "[]"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<ImportBatch id={self.id!r} profile_id={self.profile_id!r} "
            f"format={self.format!r} status={self.status!r}>"
        )


class SchoolForm(Base):
    """Pediatric and school health form tracking and draft prefill entity (AU-39)."""

    __tablename__ = "school_forms"
    __table_args__ = (
        Index("ix_school_forms_profile_status", "profile_id", "status"),
        Index("ix_school_forms_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique school form identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    attachment_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Optional linked CAS attachment ID for the uploaded PDF/image form",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Form display title (e.g. 'Annual School Physical & Immunization Form')",
    )
    school_or_camp_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="School, daycare, or camp institution name",
    )
    form_type: Mapped[str] = mapped_column(
        String(64),
        default="general",
        nullable=False,
        doc="Form classification: physical, immunization, medication_authorization, sports_clearance, general",
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Form expiration or renewal due date (UTC)",
    )
    reminder_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("reminders.id", ondelete="SET NULL"),
        nullable=True,
        doc="Associated renewal reminder ID (AU-28)",
    )
    prefill_draft_json: Mapped[str] = mapped_column(
        Text,
        default="{}",
        nullable=False,
        doc="Serialized JSON of compiled draft prefill fields from profile records",
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Optional notes or instructions for the school health form",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="draft",
        nullable=False,
        index=True,
        doc="Lifecycle status: draft, active, expired, archived",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    profile: Mapped[Profile] = relationship("Profile", back_populates="school_forms")

    def __init__(self, **kwargs: Any) -> None:
        if "institution_name" in kwargs and "school_or_camp_name" not in kwargs:
            kwargs["school_or_camp_name"] = kwargs.pop("institution_name")
        else:
            kwargs.pop("institution_name", None)
        kwargs.pop("issued_at", None)
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "form_type" not in kwargs:
            kwargs["form_type"] = "general"
        if "prefill_draft_json" not in kwargs:
            kwargs["prefill_draft_json"] = "{}"
        if "status" not in kwargs:
            kwargs["status"] = "draft"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    @property
    def institution_name(self) -> Optional[str]:
        return self.school_or_camp_name

    @institution_name.setter
    def institution_name(self, value: Optional[str]) -> None:
        self.school_or_camp_name = value

    def __repr__(self) -> str:
        return (
            f"<SchoolForm id={self.id!r} profile_id={self.profile_id!r} "
            f"title={self.title!r} status={self.status!r}>"
        )


# ---------------------------------------------------------------------------
# Connector Consent Matrix & Sync Runs Health (Autonomy Batch 5: AU-52, AU-53)
# ---------------------------------------------------------------------------


class ConsentGrant(Base):
    """Granular connector × profile × data category × purpose consent grant entity (AU-53)."""

    __tablename__ = "consent_grants"
    __table_args__ = (
        Index("ix_consent_grants_profile_connector_status", "profile_id", "connector_id", "status"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique consent grant identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    connection_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("connections.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        doc="Optional bound Connection identifier",
    )
    connector_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        doc="Connector manifest identifier (e.g. withings, google-calendar, caldav, epic-smart)",
    )
    granted_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Authenticated user or guardian who granted consent",
    )
    categories_json: Mapped[str] = mapped_column(
        Text,
        default="[]",
        nullable=False,
        doc="Serialized JSON array of consented data categories (e.g. ['vitals', 'calendar'])",
    )
    scopes_json: Mapped[str] = mapped_column(
        Text,
        default="[]",
        nullable=False,
        doc="Serialized JSON array of consented OAuth/API scopes",
    )
    allowed_hosts_json: Mapped[str] = mapped_column(
        Text,
        default="[]",
        nullable=False,
        doc="Serialized JSON array of consented outbound network hosts",
    )
    purpose: Mapped[str] = mapped_column(
        String(64),
        default="sync_and_assist",
        nullable=False,
        doc="Purpose of consent grant (e.g. sync_and_assist, read_only, calendar_write)",
    )
    terms_version: Mapped[str] = mapped_column(
        String(32),
        default="1.0.0",
        nullable=False,
        doc="Consent terms text version string",
    )
    connector_version: Mapped[str] = mapped_column(
        String(32),
        default="0.1.0",
        nullable=False,
        doc="Connector manifest version at the time consent was granted",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="active",
        nullable=False,
        index=True,
        doc="Lifecycle status: active, revoked",
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Timestamp when consent was granted (UTC)",
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when consent was revoked (UTC)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    profile: Mapped[Profile] = relationship("Profile", back_populates="consent_grants")
    connection: Mapped[Optional[Connection]] = relationship("Connection", back_populates="consent_grants")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "categories" in kwargs and "categories_json" not in kwargs:
            kwargs["categories_json"] = json.dumps(list(kwargs.pop("categories")))
        if "scopes" in kwargs and "scopes_json" not in kwargs:
            kwargs["scopes_json"] = json.dumps(list(kwargs.pop("scopes")))
        if "allowed_hosts" in kwargs and "allowed_hosts_json" not in kwargs:
            kwargs["allowed_hosts_json"] = json.dumps(list(kwargs.pop("allowed_hosts")))
        if "categories_json" not in kwargs:
            kwargs["categories_json"] = "[]"
        if "scopes_json" not in kwargs:
            kwargs["scopes_json"] = "[]"
        if "allowed_hosts_json" not in kwargs:
            kwargs["allowed_hosts_json"] = "[]"
        if "purpose" not in kwargs:
            kwargs["purpose"] = "sync_and_assist"
        if "terms_version" not in kwargs:
            kwargs["terms_version"] = "1.0.0"
        if "connector_version" not in kwargs:
            kwargs["connector_version"] = "0.1.0"
        if "status" not in kwargs:
            kwargs["status"] = "active"
        if "granted_at" not in kwargs:
            kwargs["granted_at"] = utc_now()
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    @property
    def categories(self) -> List[str]:
        try:
            return json.loads(self.categories_json or "[]")
        except Exception:
            return []

    @property
    def scopes(self) -> List[str]:
        try:
            return json.loads(self.scopes_json or "[]")
        except Exception:
            return []

    @property
    def allowed_hosts(self) -> List[str]:
        try:
            return json.loads(self.allowed_hosts_json or "[]")
        except Exception:
            return []

    def __repr__(self) -> str:
        return (
            f"<ConsentGrant id={self.id!r} profile_id={self.profile_id!r} "
            f"connector_id={self.connector_id!r} status={self.status!r}>"
        )


class SyncRun(Base):
    """Per-connection synchronization run telemetry and health record (AU-52)."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        Index("ix_sync_runs_connection_started", "connection_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique sync run identifier (UUID v4 string)",
    )
    connection_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Connection identifier",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier",
    )
    connector_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        doc="Connector manifest identifier",
    )
    stream: Mapped[str] = mapped_column(
        String(128),
        default="all",
        nullable=False,
        doc="Synchronized stream name (e.g. measures, events, uscdi)",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="running",
        nullable=False,
        index=True,
        doc="Execution status: running, succeeded, partial, failed",
    )
    records_fetched: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Number of raw records fetched from upstream source",
    )
    records_upserted: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Number of normalized records persisted/updated in health_resources",
    )
    records_quarantined: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Number of malformed records quarantined without aborting batch",
    )
    error_code: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="Machine-readable error classification (e.g. invalid_grant, rate_limited, network_error)",
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Redacted error message details",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Sync run start timestamp (UTC)",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Sync run completion timestamp (UTC)",
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Total sync run duration in milliseconds",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )

    connection: Mapped[Connection] = relationship("Connection", back_populates="sync_runs")
    profile: Mapped[Profile] = relationship("Profile", back_populates="sync_runs")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "stream" not in kwargs:
            kwargs["stream"] = "all"
        if "status" not in kwargs:
            kwargs["status"] = "running"
        if "records_fetched" not in kwargs:
            kwargs["records_fetched"] = 0
        if "records_upserted" not in kwargs:
            kwargs["records_upserted"] = 0
        if "records_quarantined" not in kwargs:
            kwargs["records_quarantined"] = 0
        if "started_at" not in kwargs:
            kwargs["started_at"] = utc_now()
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<SyncRun id={self.id!r} connection_id={self.connection_id!r} "
            f"status={self.status!r} upserted={self.records_upserted}>"
        )


# ---------------------------------------------------------------------------
# Autonomy Batch 6 Models (AU-57 through AU-63)
# ---------------------------------------------------------------------------


class Routine(Base):
    """Named, scoped A2 standing routine with <=90-day expiry and fire-time re-check (AU-58)."""

    __tablename__ = "routines"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique routine identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier",
    )
    connection_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("connections.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        doc="Optional bound Connection identifier",
    )
    created_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Authenticated steward/guardian who created the standing routine",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Human-readable routine name",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Optional routine description",
    )
    tool_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        doc="Authorized ToolSpec identifier to invoke",
    )
    args_json: Mapped[str] = mapped_column(
        Text,
        default="{}",
        nullable=False,
        doc="Canonical JSON arguments template for the routine",
    )
    rrule: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="RFC 5545 recurrence rule string",
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="UTC",
        nullable=False,
        doc="IANA timezone identifier for recurrence expansion",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="active",
        nullable=False,
        index=True,
        doc="Lifecycle status: active, paused, revoked, expired",
    )
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Last execution timestamp (UTC)",
    )
    next_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="Next scheduled execution timestamp (UTC)",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Mandatory routine expiration timestamp (<= 90 days from creation)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    profile: Mapped[Profile] = relationship("Profile", back_populates="routines")
    connection: Mapped[Optional[Connection]] = relationship("Connection", back_populates="routines")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "args" in kwargs and "args_json" not in kwargs:
            kwargs["args_json"] = json.dumps(kwargs.pop("args"))
        if "args_json" not in kwargs:
            kwargs["args_json"] = "{}"
        if "timezone" not in kwargs:
            kwargs["timezone"] = "UTC"
        if "status" not in kwargs:
            kwargs["status"] = "active"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    @property
    def args(self) -> Dict[str, Any]:
        try:
            return json.loads(self.args_json or "{}")
        except Exception:
            return {}

    def __repr__(self) -> str:
        return (
            f"<Routine id={self.id!r} profile_id={self.profile_id!r} "
            f"tool_name={self.tool_name!r} status={self.status!r}>"
        )


class McpToolPin(Base):
    """Schema-hash pin for a curated remote MCP tool on a connection (AU-57 / Titan S7)."""

    __tablename__ = "mcp_tool_pins"
    __table_args__ = (
        UniqueConstraint("connection_id", "tool_name", name="uq_mcp_tool_pins_conn_tool"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique MCP tool pin identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier",
    )
    connection_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Connection identifier",
    )
    tool_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        doc="Remote MCP tool identifier",
    )
    risk_tier: Mapped[str] = mapped_column(
        String(32),
        default="read",
        nullable=False,
        doc="Assigned Carefold risk tier: read, write_local, write_external, irreversible",
    )
    schema_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="SHA-256 digest of canonical (name, description, inputSchema)",
    )
    schema_json: Mapped[str] = mapped_column(
        Text,
        default="{}",
        nullable=False,
        doc="Serialized canonical tool schema snapshot",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="pinned",
        nullable=False,
        index=True,
        doc="Pin status: pinned, drift_blocked",
    )
    pinned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Initial pin timestamp (UTC)",
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Last schema verification timestamp (UTC)",
    )

    profile: Mapped[Profile] = relationship("Profile", back_populates="mcp_tool_pins")
    connection: Mapped[Connection] = relationship("Connection", back_populates="mcp_tool_pins")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "risk_tier" not in kwargs:
            kwargs["risk_tier"] = "read"
        if "schema_json" not in kwargs:
            kwargs["schema_json"] = "{}"
        if "status" not in kwargs:
            kwargs["status"] = "pinned"
        if "pinned_at" not in kwargs:
            kwargs["pinned_at"] = utc_now()
        if "verified_at" not in kwargs:
            kwargs["verified_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<McpToolPin id={self.id!r} connection_id={self.connection_id!r} "
            f"tool_name={self.tool_name!r} status={self.status!r}>"
        )


class EmailDraft(Base):
    """Local-only email draft prepared by Carefold with no automatic send capability (AU-60)."""

    __tablename__ = "email_drafts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique email draft identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier",
    )
    created_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="User who requested or created the draft",
    )
    recipient: Mapped[Optional[str]] = mapped_column(
        String(320),
        nullable=True,
        doc="Optional recipient email address",
    )
    subject: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        doc="Email subject line",
    )
    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Email plaintext body",
    )
    category: Mapped[str] = mapped_column(
        String(64),
        default="general",
        nullable=False,
        doc="Draft category: appointment, school, insurance, general",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="draft",
        nullable=False,
        index=True,
        doc="Lifecycle status: draft, exported, sent_via_approved_mcp, archived",
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when draft was sent via approved gmail_send_message (UTC)",
    )
    external_message_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="External Gmail message ID when sent via approved gmail_send_message",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    profile: Mapped[Profile] = relationship("Profile", back_populates="email_drafts")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "category" not in kwargs:
            kwargs["category"] = "general"
        if "status" not in kwargs:
            kwargs["status"] = "draft"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<EmailDraft id={self.id!r} profile_id={self.profile_id!r} "
            f"subject={self.subject!r} status={self.status!r}>"
        )


class SchoolIcsFeed(Base):
    """Per-child read-only school calendar ICS subscription feed (AU-61 / E4.4)."""

    __tablename__ = "school_ics_feeds"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique school ICS feed identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced child/student Profile identifier",
    )
    label: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="School or calendar feed display name (e.g. 'Oakridge Elementary Calendar')",
    )
    feed_url: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        doc="Public HTTPS/webcal .ics subscription URL",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="active",
        nullable=False,
        index=True,
        doc="Feed sync status: active, paused, error",
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Last successful feed synchronization timestamp (UTC)",
    )
    events_synced: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Count of calendar events synchronized from this feed",
    )
    last_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Redacted error message if last sync failed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    profile: Mapped[Profile] = relationship("Profile", back_populates="school_ics_feeds")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "status" not in kwargs:
            kwargs["status"] = "active"
        if "events_synced" not in kwargs:
            kwargs["events_synced"] = 0
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<SchoolIcsFeed id={self.id!r} profile_id={self.profile_id!r} "
            f"label={self.label!r} status={self.status!r}>"
        )


class CompanionDevice(Base):
    """Paired iOS companion device with pinned TLS certificate fingerprint and scoped profile permissions (AU-62)."""

    __tablename__ = "companion_devices"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique companion device identifier (UUID v4 string)",
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Owner User identifier",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Scoped Profile identifier",
    )
    device_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Human-readable device label (e.g. 'Priya iPhone 16 Pro')",
    )
    platform: Mapped[str] = mapped_column(
        String(32),
        default="ios",
        nullable=False,
        doc="Companion platform ('ios' in v1)",
    )
    pairing_code_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="SHA-256 digest of one-time pairing code (cleared once paired)",
    )
    token_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        doc="SHA-256 digest of issued companion device bearer token",
    )
    cert_fingerprint_sha256: Mapped[str] = mapped_column(
        String(95),
        nullable=False,
        doc="Pinned TLS server certificate SHA-256 fingerprint",
    )
    allowed_categories_json: Mapped[str] = mapped_column(
        Text,
        default='["vitals", "clinical_records", "reminders"]',
        nullable=False,
        doc="Serialized JSON array of consented companion sync categories",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending_pair",
        nullable=False,
        index=True,
        doc="Device status: pending_pair, active, revoked",
    )
    paired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when QR pairing completed (UTC)",
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Last companion sync or notification poll timestamp (UTC)",
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Pairing code or device token expiration timestamp (UTC)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    profile: Mapped[Profile] = relationship("Profile", back_populates="companion_devices")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "allowed_categories" in kwargs and "allowed_categories_json" not in kwargs:
            kwargs["allowed_categories_json"] = json.dumps(list(kwargs.pop("allowed_categories")))
        if "allowed_categories_json" not in kwargs:
            kwargs["allowed_categories_json"] = '["vitals", "clinical_records", "reminders"]'
        if "platform" not in kwargs:
            kwargs["platform"] = "ios"
        if "status" not in kwargs:
            kwargs["status"] = "pending_pair"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    @property
    def allowed_categories(self) -> List[str]:
        try:
            return json.loads(self.allowed_categories_json or "[]")
        except Exception:
            return []

    def __repr__(self) -> str:
        return (
            f"<CompanionDevice id={self.id!r} profile_id={self.profile_id!r} "
            f"device_name={self.device_name!r} status={self.status!r}>"
        )





