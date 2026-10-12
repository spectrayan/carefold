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

"""Autonomy Foundations schema evolution (CAS attachments, audit_events, connections, credentials).

Revision ID: 0002_autonomy_foundations
Revises: 0001_baseline_schema
Create Date: 2026-10-12 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_autonomy_foundations"
down_revision: Union[str, None] = "0001_baseline_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        existing_tables = {"attachments"}
        existing_cols = set()
        existing_indices = set()
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())
        existing_cols = {c["name"] for c in insp.get_columns("attachments")} if "attachments" in existing_tables else set()
        existing_indices = {idx["name"] for idx in insp.get_indexes("attachments")} if "attachments" in existing_tables else set()

    # 1. CAS columns on attachments
    if "attachments" in existing_tables:
        with op.batch_alter_table("attachments") as batch_op:
            if "extracted_text" not in existing_cols:
                batch_op.add_column(sa.Column("extracted_text", sa.Text(), nullable=True))
            if "source" not in existing_cols:
                batch_op.add_column(sa.Column("source", sa.String(64), nullable=False, server_default="upload"))
            if "source_ref" not in existing_cols:
                batch_op.add_column(sa.Column("source_ref", sa.String(255), nullable=True))
            if "extraction_status" not in existing_cols:
                batch_op.add_column(sa.Column("extraction_status", sa.String(32), nullable=False, server_default="pending"))
            if "updated_at" not in existing_cols:
                batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

            if "ix_attachments_source" not in existing_indices:
                batch_op.create_index("ix_attachments_source", ["source"])
            if "ix_attachments_extraction_status" not in existing_indices:
                batch_op.create_index("ix_attachments_extraction_status", ["extraction_status"])

    # 2. audit_events
    if "audit_events" not in existing_tables:
        op.create_table(
            "audit_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True),
            sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("principal", sa.String(64), nullable=False, server_default="user"),
            sa.Column("run_id", sa.String(64), nullable=True),
            sa.Column("event", sa.String(64), nullable=False),
            sa.Column("tool", sa.String(64), nullable=True),
            sa.Column("risk", sa.String(32), nullable=True),
            sa.Column("decision", sa.String(32), nullable=True),
            sa.Column("payload_hash", sa.String(64), nullable=True),
            sa.Column("external_ref", sa.String(255), nullable=True),
            sa.Column("detail_redacted", sa.Text(), nullable=True),
        )
        op.create_index("ix_audit_events_ts", "audit_events", ["ts"], unique=False)
        op.create_index("ix_audit_events_profile_id", "audit_events", ["profile_id"], unique=False)
        op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"], unique=False)
        op.create_index("ix_audit_events_run_id", "audit_events", ["run_id"], unique=False)
        op.create_index("ix_audit_events_event", "audit_events", ["event"], unique=False)
        op.create_index("ix_audit_events_tool", "audit_events", ["tool"], unique=False)

    # 3. connections
    if "connections" not in existing_tables:
        op.create_table(
            "connections",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("connector_id", sa.String(128), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending_auth"),
            sa.Column("label", sa.String(255), nullable=True),
            sa.Column("status_message", sa.Text(), nullable=True),
            sa.Column("sync_cursor", sa.Text(), nullable=True),
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_connections_user_id", "connections", ["user_id"], unique=False)
        op.create_index("ix_connections_profile_id", "connections", ["profile_id"], unique=False)
        op.create_index("ix_connections_connector_id", "connections", ["connector_id"], unique=False)
        op.create_index("ix_connections_status", "connections", ["status"], unique=False)
    else:
        conn_cols = {c["name"] for c in insp.get_columns("connections")} if not context.is_offline_mode() else set()
        with op.batch_alter_table("connections") as batch_op:
            if "label" not in conn_cols:
                batch_op.add_column(sa.Column("label", sa.String(255), nullable=True))
            if "status_message" not in conn_cols:
                batch_op.add_column(sa.Column("status_message", sa.Text(), nullable=True))
            if "sync_cursor" not in conn_cols:
                batch_op.add_column(sa.Column("sync_cursor", sa.Text(), nullable=True))
            if "last_sync_at" not in conn_cols:
                batch_op.add_column(sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True))

    # 4. credentials
    if "credentials" not in existing_tables:
        op.create_table(
            "credentials",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("connection_id", sa.String(36), sa.ForeignKey("connections.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("encrypted_blob", sa.Text(), nullable=False),
            sa.Column("aad_binding", sa.String(255), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_credentials_connection_id", "credentials", ["connection_id"], unique=False)
        op.create_index("ix_credentials_profile_id", "credentials", ["profile_id"], unique=False)
        op.create_index("ix_credentials_user_id", "credentials", ["user_id"], unique=False)
    else:
        cred_cols = {c["name"] for c in insp.get_columns("credentials")} if not context.is_offline_mode() else set()
        with op.batch_alter_table("credentials") as batch_op:
            if "user_id" not in cred_cols:
                batch_op.add_column(sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True))
                batch_op.create_index("ix_credentials_user_id", ["user_id"])
            if "aad_binding" not in cred_cols:
                batch_op.add_column(sa.Column("aad_binding", sa.String(255), nullable=True))
            if "rotated_at" not in cred_cols:
                batch_op.add_column(sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    if context.is_offline_mode():
        existing_tables = {"credentials", "connections", "audit_events", "attachments"}
        existing_cols = {"updated_at", "extraction_status", "source_ref", "source", "extracted_text"}
        existing_indices = {"ix_attachments_extraction_status", "ix_attachments_source"}
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())
        existing_cols = {c["name"] for c in insp.get_columns("attachments")} if "attachments" in existing_tables else set()
        existing_indices = {idx["name"] for idx in insp.get_indexes("attachments")} if "attachments" in existing_tables else set()

    if "credentials" in existing_tables:
        op.drop_table("credentials")
    if "connections" in existing_tables:
        op.drop_table("connections")
    if "audit_events" in existing_tables:
        op.drop_table("audit_events")

    if "attachments" in existing_tables:
        with op.batch_alter_table("attachments") as batch_op:
            if "ix_attachments_extraction_status" in existing_indices:
                batch_op.drop_index("ix_attachments_extraction_status")
            if "ix_attachments_source" in existing_indices:
                batch_op.drop_index("ix_attachments_source")
            if "updated_at" in existing_cols:
                batch_op.drop_column("updated_at")
            if "extraction_status" in existing_cols:
                batch_op.drop_column("extraction_status")
            if "source_ref" in existing_cols:
                batch_op.drop_column("source_ref")
            if "source" in existing_cols:
                batch_op.drop_column("source")
            if "extracted_text" in existing_cols:
                batch_op.drop_column("extracted_text")
