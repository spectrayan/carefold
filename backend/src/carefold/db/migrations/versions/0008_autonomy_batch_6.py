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

"""Autonomy Batch 6 schema evolution: routines, mcp_tool_pins, email_drafts, school_ics_feeds, companion_devices, and connection/access extensions.

Revision ID: 0008_autonomy_batch_6
Revises: 0007_autonomy_batch_5
Create Date: 2026-10-13 14:20:00.000000

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0008_autonomy_batch_6"
down_revision: Union[str, None] = "0007_autonomy_batch_5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        existing_tables: set[str] = set()
        conn_cols: set[str] = set()
        access_cols: set[str] = set()
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())
        conn_cols = (
            {c["name"] for c in insp.get_columns("connections")}
            if "connections" in existing_tables
            else set()
        )
        access_cols = (
            {c["name"] for c in insp.get_columns("profile_access")}
            if "profile_access" in existing_tables
            else set()
        )

    # 1. Extend connections table with autonomy_level (AU-58)
    if context.is_offline_mode() or "connections" in existing_tables:
        if context.is_offline_mode() or "autonomy_level" not in conn_cols:
            with op.batch_alter_table("connections", recreate="auto") as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "autonomy_level",
                        sa.String(16),
                        nullable=False,
                        server_default="inherit",
                    )
                )

    # 2. Extend profile_access table with allowed_sections_json (AU-63)
    if context.is_offline_mode() or "profile_access" in existing_tables:
        if context.is_offline_mode() or "allowed_sections_json" not in access_cols:
            with op.batch_alter_table("profile_access", recreate="auto") as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "allowed_sections_json",
                        sa.Text(),
                        nullable=True,
                    )
                )

    # 3. routines table (AU-58)
    if "routines" not in existing_tables:
        op.create_table(
            "routines",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("connection_id", sa.String(36), sa.ForeignKey("connections.id", ondelete="CASCADE"), nullable=True),
            sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("tool_name", sa.String(128), nullable=False),
            sa.Column("args_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("rrule", sa.String(255), nullable=False),
            sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_routines_profile_id", "routines", ["profile_id"], unique=False)
        op.create_index("ix_routines_connection_id", "routines", ["connection_id"], unique=False)
        op.create_index("ix_routines_created_by_user_id", "routines", ["created_by_user_id"], unique=False)
        op.create_index("ix_routines_status", "routines", ["status"], unique=False)
        op.create_index("ix_routines_next_run_at", "routines", ["next_run_at"], unique=False)

    # 4. mcp_tool_pins table (AU-57)
    if "mcp_tool_pins" not in existing_tables:
        op.create_table(
            "mcp_tool_pins",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("connection_id", sa.String(36), sa.ForeignKey("connections.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tool_name", sa.String(128), nullable=False),
            sa.Column("risk_tier", sa.String(32), nullable=False, server_default="read"),
            sa.Column("schema_hash", sa.String(64), nullable=False),
            sa.Column("schema_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(32), nullable=False, server_default="pinned"),
            sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("connection_id", "tool_name", name="uq_mcp_tool_pins_conn_tool"),
        )
        op.create_index("ix_mcp_tool_pins_profile_id", "mcp_tool_pins", ["profile_id"], unique=False)
        op.create_index("ix_mcp_tool_pins_connection_id", "mcp_tool_pins", ["connection_id"], unique=False)
        op.create_index("ix_mcp_tool_pins_status", "mcp_tool_pins", ["status"], unique=False)

    # 5. email_drafts table (AU-60)
    if "email_drafts" not in existing_tables:
        op.create_table(
            "email_drafts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("recipient", sa.String(320), nullable=True),
            sa.Column("subject", sa.String(500), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("category", sa.String(64), nullable=False, server_default="general"),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_email_drafts_profile_id", "email_drafts", ["profile_id"], unique=False)
        op.create_index("ix_email_drafts_status", "email_drafts", ["status"], unique=False)

    # 6. school_ics_feeds table (AU-61)
    if "school_ics_feeds" not in existing_tables:
        op.create_table(
            "school_ics_feeds",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("label", sa.String(255), nullable=False),
            sa.Column("feed_url", sa.String(1024), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("events_synced", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_school_ics_feeds_profile_id", "school_ics_feeds", ["profile_id"], unique=False)
        op.create_index("ix_school_ics_feeds_status", "school_ics_feeds", ["status"], unique=False)

    # 7. companion_devices table (AU-62)
    if "companion_devices" not in existing_tables:
        op.create_table(
            "companion_devices",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("device_name", sa.String(255), nullable=False),
            sa.Column("platform", sa.String(32), nullable=False, server_default="ios"),
            sa.Column("pairing_code_hash", sa.String(64), nullable=True),
            sa.Column("token_hash", sa.String(64), nullable=True),
            sa.Column("cert_fingerprint_sha256", sa.String(95), nullable=False),
            sa.Column(
                "allowed_categories_json",
                sa.Text(),
                nullable=False,
                server_default='["vitals", "clinical_records", "reminders"]',
            ),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending_pair"),
            sa.Column("paired_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_companion_devices_user_id", "companion_devices", ["user_id"], unique=False)
        op.create_index("ix_companion_devices_profile_id", "companion_devices", ["profile_id"], unique=False)
        op.create_index("ix_companion_devices_token_hash", "companion_devices", ["token_hash"], unique=False)
        op.create_index("ix_companion_devices_status", "companion_devices", ["status"], unique=False)


def downgrade() -> None:
    if context.is_offline_mode():
        existing_tables = {
            "routines",
            "mcp_tool_pins",
            "email_drafts",
            "school_ics_feeds",
            "companion_devices",
            "connections",
            "profile_access",
        }
        conn_cols = {"autonomy_level"}
        access_cols = {"allowed_sections_json"}
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())
        conn_cols = (
            {c["name"] for c in insp.get_columns("connections")}
            if "connections" in existing_tables
            else set()
        )
        access_cols = (
            {c["name"] for c in insp.get_columns("profile_access")}
            if "profile_access" in existing_tables
            else set()
        )

    for tbl in ("companion_devices", "school_ics_feeds", "email_drafts", "mcp_tool_pins", "routines"):
        if tbl in existing_tables:
            op.drop_table(tbl)

    if "profile_access" in existing_tables and "allowed_sections_json" in access_cols:
        with op.batch_alter_table("profile_access", recreate="auto") as batch_op:
            batch_op.drop_column("allowed_sections_json")

    if "connections" in existing_tables and "autonomy_level" in conn_cols:
        with op.batch_alter_table("connections", recreate="auto") as batch_op:
            batch_op.drop_column("autonomy_level")
