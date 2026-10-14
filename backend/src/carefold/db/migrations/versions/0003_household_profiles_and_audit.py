# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Autonomy Batch 1 schema evolution (profile_keys, approvals, jobs, credentials.dek_version).

Revision ID: 0003_household_profiles_and_audit
Revises: 0002_autonomy_foundations
Create Date: 2026-10-12 17:15:00.000000

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_household_profiles_and_audit"
down_revision: Union[str, None] = "0002_autonomy_foundations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        existing_tables = set()
        cred_cols = set()
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())
        cred_cols = {c["name"] for c in insp.get_columns("credentials")} if "credentials" in existing_tables else set()

    # 1. profile_keys table (AU-14 DEK storage)
    if "profile_keys" not in existing_tables:
        op.create_table(
            "profile_keys",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("encrypted_dek", sa.Text(), nullable=False),
            sa.Column("dek_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("profile_id", "dek_version", name="uq_profile_keys_profile_id_dek_version"),
        )
        op.create_index("ix_profile_keys_profile_id", "profile_keys", ["profile_id"], unique=False)

    # 2. approvals table (AU-18 HITL policy decisions)
    if "approvals" not in existing_tables:
        op.create_table(
            "approvals",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("run_id", sa.String(64), nullable=False),
            sa.Column("thread_id", sa.String(64), nullable=True),
            sa.Column("tool_name", sa.String(128), nullable=False),
            sa.Column("args_redacted", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("destination_hosts", sa.Text(), nullable=True, server_default="[]"),
            sa.Column("risk_tier", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decided_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_approvals_profile_id", "approvals", ["profile_id"], unique=False)
        op.create_index("ix_approvals_run_id", "approvals", ["run_id"], unique=False)
        op.create_index("ix_approvals_thread_id", "approvals", ["thread_id"], unique=False)
        op.create_index("ix_approvals_tool_name", "approvals", ["tool_name"], unique=False)
        op.create_index("ix_approvals_payload_hash", "approvals", ["payload_hash"], unique=False)
        op.create_index("ix_approvals_status", "approvals", ["status"], unique=False)
        op.create_index("ix_approvals_expires_at", "approvals", ["expires_at"], unique=False)

    # 3. jobs table (AU-21 Wall-clock scheduled jobs)
    if "jobs" not in existing_tables:
        op.create_table(
            "jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(64), nullable=False),
            sa.Column("routine_id", sa.String(64), nullable=True),
            sa.Column("connection_id", sa.String(36), nullable=True),
            sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
            sa.Column("rrule", sa.String(255), nullable=True),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("lease_owner", sa.String(64), nullable=True),
            sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("idempotency_key", sa.String(255), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_jobs_profile_id", "jobs", ["profile_id"], unique=False)
        op.create_index("ix_jobs_kind", "jobs", ["kind"], unique=False)
        op.create_index("ix_jobs_routine_id", "jobs", ["routine_id"], unique=False)
        op.create_index("ix_jobs_connection_id", "jobs", ["connection_id"], unique=False)
        op.create_index("ix_jobs_next_run_at", "jobs", ["next_run_at"], unique=False)
        op.create_index("ix_jobs_lease_until", "jobs", ["lease_until"], unique=False)
        op.create_index("ix_jobs_idempotency_key", "jobs", ["idempotency_key"], unique=False)
        op.create_index("ix_jobs_status", "jobs", ["status"], unique=False)

    # 4. Add dek_version to credentials (SQLite batch alter mode)
    if "credentials" in existing_tables or context.is_offline_mode():
        if "dek_version" not in cred_cols:
            with op.batch_alter_table("credentials") as batch_op:
                batch_op.add_column(
                    sa.Column("dek_version", sa.Integer(), nullable=False, server_default="1")
                )


def downgrade() -> None:
    if context.is_offline_mode():
        existing_tables = {"jobs", "approvals", "profile_keys", "credentials"}
        cred_cols = {"dek_version"}
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())
        cred_cols = {c["name"] for c in insp.get_columns("credentials")} if "credentials" in existing_tables else set()

    # 1. Drop dek_version column from credentials via SQLite batch rebuild
    if "credentials" in existing_tables and "dek_version" in cred_cols:
        with op.batch_alter_table("credentials") as batch_op:
            batch_op.drop_column("dek_version")

    # 2. Drop jobs table
    if "jobs" in existing_tables:
        op.drop_table("jobs")

    # 3. Drop approvals table
    if "approvals" in existing_tables:
        op.drop_table("approvals")

    # 4. Drop profile_keys table
    if "profile_keys" in existing_tables:
        op.drop_table("profile_keys")
