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

"""Autonomy Batch 5 schema evolution: consent_grants, sync_runs, and connections extensions.

Revision ID: 0007_autonomy_batch_5
Revises: 0006_autonomy_batch_4
Create Date: 2026-10-13 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0007_autonomy_batch_5"
down_revision: Union[str, None] = "0006_autonomy_batch_4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        existing_tables = set()
        conn_cols: set[str] = set()
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())
        conn_cols = (
            {c["name"] for c in insp.get_columns("connections")}
            if "connections" in existing_tables
            else set()
        )

    # 1. Extend connections table with consecutive_failures and consented_version (AU-52)
    if context.is_offline_mode() or "connections" in existing_tables:
        needs_consecutive = context.is_offline_mode() or "consecutive_failures" not in conn_cols
        needs_consented_ver = context.is_offline_mode() or "consented_version" not in conn_cols
        if needs_consecutive or needs_consented_ver:
            with op.batch_alter_table("connections", recreate="auto") as batch_op:
                if needs_consecutive:
                    batch_op.add_column(
                        sa.Column(
                            "consecutive_failures",
                            sa.Integer(),
                            nullable=False,
                            server_default="0",
                        )
                    )
                if needs_consented_ver:
                    batch_op.add_column(
                        sa.Column(
                            "consented_version",
                            sa.String(32),
                            nullable=True,
                        )
                    )

    # 2. consent_grants table (AU-53)
    if "consent_grants" not in existing_tables:
        op.create_table(
            "consent_grants",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("connection_id", sa.String(36), sa.ForeignKey("connections.id", ondelete="CASCADE"), nullable=True),
            sa.Column("connector_id", sa.String(128), nullable=False),
            sa.Column("granted_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("categories_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("scopes_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("allowed_hosts_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("purpose", sa.String(64), nullable=False, server_default="sync_and_assist"),
            sa.Column("terms_version", sa.String(32), nullable=False, server_default="1.0.0"),
            sa.Column("connector_version", sa.String(32), nullable=False, server_default="0.1.0"),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_consent_grants_profile_id", "consent_grants", ["profile_id"], unique=False)
        op.create_index("ix_consent_grants_connection_id", "consent_grants", ["connection_id"], unique=False)
        op.create_index("ix_consent_grants_connector_id", "consent_grants", ["connector_id"], unique=False)
        op.create_index("ix_consent_grants_status", "consent_grants", ["status"], unique=False)
        op.create_index(
            "ix_consent_grants_profile_connector_status",
            "consent_grants",
            ["profile_id", "connector_id", "status"],
            unique=False,
        )

    # 3. sync_runs table (AU-52)
    if "sync_runs" not in existing_tables:
        op.create_table(
            "sync_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("connection_id", sa.String(36), sa.ForeignKey("connections.id", ondelete="CASCADE"), nullable=False),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("connector_id", sa.String(128), nullable=False),
            sa.Column("stream", sa.String(128), nullable=False, server_default="all"),
            sa.Column("status", sa.String(32), nullable=False, server_default="running"),
            sa.Column("records_fetched", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("records_upserted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("records_quarantined", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_code", sa.String(64), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_sync_runs_connection_id", "sync_runs", ["connection_id"], unique=False)
        op.create_index("ix_sync_runs_profile_id", "sync_runs", ["profile_id"], unique=False)
        op.create_index("ix_sync_runs_connector_id", "sync_runs", ["connector_id"], unique=False)
        op.create_index("ix_sync_runs_status", "sync_runs", ["status"], unique=False)
        op.create_index(
            "ix_sync_runs_connection_started",
            "sync_runs",
            ["connection_id", "started_at"],
            unique=False,
        )


def downgrade() -> None:
    if context.is_offline_mode():
        existing_tables = {"consent_grants", "sync_runs", "connections"}
        conn_cols = {"consecutive_failures", "consented_version"}
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())
        conn_cols = (
            {c["name"] for c in insp.get_columns("connections")}
            if "connections" in existing_tables
            else set()
        )

    if "sync_runs" in existing_tables:
        op.drop_table("sync_runs")

    if "consent_grants" in existing_tables:
        op.drop_table("consent_grants")

    if "connections" in existing_tables and (
        "consecutive_failures" in conn_cols or "consented_version" in conn_cols
    ):
        with op.batch_alter_table("connections", recreate="auto") as batch_op:
            if "consented_version" in conn_cols:
                batch_op.drop_column("consented_version")
            if "consecutive_failures" in conn_cols:
                batch_op.drop_column("consecutive_failures")
