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

"""Baseline database schema capturing initial 14 Carefold tables.

Revision ID: 0001_baseline_schema
Revises:
Create Date: 2026-10-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_baseline_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        existing_tables = set()
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())

    # 1. users
    if "users" not in existing_tables:
        op.create_table(
            "users",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("username", sa.String(64), nullable=False),
            sa.Column("hashed_password", sa.String(255), nullable=False),
            sa.Column("full_name", sa.String(255), nullable=True),
            sa.Column("role", sa.String(32), nullable=False, server_default="steward"),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("auth_provider", sa.String(32), nullable=False, server_default="local"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)
        op.create_index("ix_users_username", "users", ["username"], unique=True)

    # 2. sessions
    if "sessions" not in existing_tables:
        op.create_table(
            "sessions",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("client_ip", sa.String(45), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)
        op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"], unique=False)

    # 3. password_resets
    if "password_resets" not in existing_tables:
        op.create_table(
            "password_resets",
            sa.Column("token_hash", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_password_resets_user_id", "password_resets", ["user_id"], unique=False)
        op.create_index("ix_password_resets_expires_at", "password_resets", ["expires_at"], unique=False)

    # 4. system_settings
    if "system_settings" not in existing_tables:
        op.create_table(
            "system_settings",
            sa.Column("key", sa.String(128), primary_key=True),
            sa.Column("value_json", sa.Text(), nullable=False),
            sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_by", sa.String(255), nullable=True),
        )

    # 5. agent
    if "agent" not in existing_tables:
        op.create_table(
            "agent",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("type", sa.String(32), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("persona", sa.Text(), nullable=False),
            sa.Column("model", sa.String(128), nullable=False),
            sa.Column("skills_json", sa.Text(), nullable=False),
            sa.Column("tools_json", sa.Text(), nullable=False),
            sa.Column("starters_json", sa.Text(), nullable=False),
            sa.Column("domain", sa.String(64), nullable=False),
            sa.Column("category", sa.String(64), nullable=False),
            sa.Column("risk_class", sa.String(32), nullable=False),
            sa.Column("tags_json", sa.Text(), nullable=False),
            sa.Column("care_stages_json", sa.Text(), nullable=False),
            sa.Column("target_audience_json", sa.Text(), nullable=False),
            sa.Column("forbidden_json", sa.Text(), nullable=False),
            sa.Column("icon", sa.String(64), nullable=False),
            sa.Column("maturity", sa.String(32), nullable=False),
            sa.Column("can_delegate", sa.Boolean(), nullable=False),
            sa.Column("max_iterations", sa.Integer(), nullable=False),
            sa.Column("hidden", sa.Boolean(), nullable=False),
            sa.Column("is_public", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_agent_type", "agent", ["type"], unique=False)
        op.create_index("ix_agent_user_id", "agent", ["user_id"], unique=False)

    # 6. skill
    if "skill" not in existing_tables:
        op.create_table(
            "skill",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("type", sa.String(32), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("domain", sa.String(64), nullable=False),
            sa.Column("category", sa.String(64), nullable=False),
            sa.Column("risk_class", sa.String(32), nullable=False),
            sa.Column("tags_json", sa.Text(), nullable=False),
            sa.Column("tools_json", sa.Text(), nullable=False),
            sa.Column("instructions", sa.Text(), nullable=False),
            sa.Column("forbidden_json", sa.Text(), nullable=False),
            sa.Column("is_verified", sa.Boolean(), nullable=False),
            sa.Column("is_public", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_skill_type", "skill", ["type"], unique=False)
        op.create_index("ix_skill_user_id", "skill", ["user_id"], unique=False)

    # 7. knowledge_base
    if "knowledge_base" not in existing_tables:
        op.create_table(
            "knowledge_base",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("type", sa.String(32), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("target_type", sa.String(32), nullable=False),
            sa.Column("target_id", sa.String(64), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("format", sa.String(32), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("metadata_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("target_type", "target_id", "name", name="uq_kb_target_name"),
        )
        op.create_index("ix_knowledge_base_type", "knowledge_base", ["type"], unique=False)
        op.create_index("ix_knowledge_base_user_id", "knowledge_base", ["user_id"], unique=False)
        op.create_index("ix_knowledge_base_target_type", "knowledge_base", ["target_type"], unique=False)
        op.create_index("ix_knowledge_base_target_id", "knowledge_base", ["target_id"], unique=False)
        op.create_index("ix_knowledge_base_name", "knowledge_base", ["name"], unique=False)

    # 8. profiles
    if "profiles" not in existing_tables:
        op.create_table(
            "profiles",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("relationship", sa.String(64), nullable=False),
            sa.Column("role", sa.String(32), nullable=False),
            sa.Column("date_of_birth", sa.String(10), nullable=True),
            sa.Column("avatar_color", sa.String(32), nullable=False),
            sa.Column("short_name", sa.String(64), nullable=True),
            sa.Column("avatar_url", sa.String(512), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_profiles_user_id", "profiles", ["user_id"], unique=False)

    # 9. profile_access
    if "profile_access" not in existing_tables:
        op.create_table(
            "profile_access",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
            sa.Column("granted_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("role", sa.String(32), nullable=False),
            sa.Column("access_level", sa.String(32), nullable=False),
            sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("profile_id", "user_id", name="uq_profile_access_user"),
        )
        op.create_index("ix_profile_access_profile_id", "profile_access", ["profile_id"], unique=False)
        op.create_index("ix_profile_access_user_id", "profile_access", ["user_id"], unique=False)

    # 10. profile_consents
    if "profile_consents" not in existing_tables:
        op.create_table(
            "profile_consents",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("terms_version", sa.String(32), nullable=False, server_default="v1.0"),
            sa.Column("allow_clinical", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("teen_handover_notified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_profile_consents_profile_id", "profile_consents", ["profile_id"], unique=True)

    # 11. viewer_invites
    if "viewer_invites" not in existing_tables:
        op.create_table(
            "viewer_invites",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("invite_code", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("invited_by", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
            sa.Column("invitee_name", sa.String(255), nullable=False),
            sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
            sa.Column("view_clinical", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("view_paperwork", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("accepted_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_viewer_invites_invite_code", "viewer_invites", ["invite_code"], unique=True)
        op.create_index("ix_viewer_invites_profile_id", "viewer_invites", ["profile_id"], unique=False)
        op.create_index("ix_viewer_invites_invited_by", "viewer_invites", ["invited_by"], unique=False)
        op.create_index("ix_viewer_invites_accepted_by", "viewer_invites", ["accepted_by"], unique=False)

    # 12. notes
    if "notes" not in existing_tables:
        op.create_table(
            "notes",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("type", sa.String(32), nullable=False, server_default="scratchpad"),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=True),
            sa.Column("slug", sa.String(128), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_notes_type", "notes", ["type"], unique=False)
        op.create_index("ix_notes_user_id", "notes", ["user_id"], unique=False)
        op.create_index("ix_notes_profile_id", "notes", ["profile_id"], unique=False)
        op.create_index("ix_notes_slug", "notes", ["slug"], unique=False)

    # 13. attachments (Baseline schema before CAS additions)
    if "attachments" not in existing_tables:
        op.create_table(
            "attachments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=True),
            sa.Column("storage_key", sa.String(512), nullable=True),
            sa.Column("filename", sa.String(255), nullable=False),
            sa.Column("original_name", sa.String(255), nullable=False),
            sa.Column("content_type", sa.String(128), nullable=False, server_default="application/octet-stream"),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256_hash", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_attachments_user_id", "attachments", ["user_id"], unique=False)
        op.create_index("ix_attachments_profile_id", "attachments", ["profile_id"], unique=False)
        op.create_index("ix_attachments_storage_key", "attachments", ["storage_key"], unique=False)
        op.create_index("ix_attachments_filename", "attachments", ["filename"], unique=False)
        op.create_index("ix_attachments_sha256_hash", "attachments", ["sha256_hash"], unique=False)

    # 14. chat_threads
    if "chat_threads" not in existing_tables:
        op.create_table(
            "chat_threads",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=True),
            sa.Column("agent_id", sa.String(64), nullable=False),
            sa.Column("title", sa.String(255), nullable=False, server_default="New Consultation"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_chat_threads_user_id", "chat_threads", ["user_id"], unique=False)
        op.create_index("ix_chat_threads_profile_id", "chat_threads", ["profile_id"], unique=False)
        op.create_index("ix_chat_threads_agent_id", "chat_threads", ["agent_id"], unique=False)


def downgrade() -> None:
    if context.is_offline_mode():
        existing_tables = {
            "chat_threads",
            "attachments",
            "notes",
            "viewer_invites",
            "profile_consents",
            "profile_access",
            "profiles",
            "knowledge_base",
            "skill",
            "agent",
            "system_settings",
            "password_resets",
            "sessions",
            "users",
        }
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())

    for table in [
        "chat_threads",
        "attachments",
        "notes",
        "viewer_invites",
        "profile_consents",
        "profile_access",
        "profiles",
        "knowledge_base",
        "skill",
        "agent",
        "system_settings",
        "password_resets",
        "sessions",
        "users",
    ]:
        if table in existing_tables:
            op.drop_table(table)
