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

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
    notes: Mapped[List[Note]] = relationship(
        "Note",
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


class Note(Base):
    """Note entity for user clinical visit notes, prep items, and summaries."""

    __tablename__ = "note"

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

    user: Mapped[Optional[User]] = relationship("User", back_populates="notes")

    def get_tags(self) -> List[str]:
        return json.loads(self.tags_json) if self.tags_json else []

    def set_tags(self, tags: List[str]) -> None:
        self.tags_json = json.dumps(tags)

    def __repr__(self) -> str:
        return f"<Note id={self.id!r} slug={self.slug!r} title={self.title!r}>"

