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

"""Autonomy Batch 7 schema evolution: tamper-evident audit hash chain columns and email_drafts delivery tracking.

Revision ID: 0009_companion_and_handover
Revises: 0008_routines_mcp_and_drafts
Create Date: 2026-10-13 22:05:00.000000

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0009_companion_and_handover"
down_revision: Union[str, None] = "0008_routines_mcp_and_drafts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        existing_tables: set[str] = set()
        audit_cols: set[str] = set()
        draft_cols: set[str] = set()
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())
        audit_cols = (
            {c["name"] for c in insp.get_columns("audit_events")}
            if "audit_events" in existing_tables
            else set()
        )
        draft_cols = (
            {c["name"] for c in insp.get_columns("email_drafts")}
            if "email_drafts" in existing_tables
            else set()
        )

    # 1. Extend audit_events with tamper-evident hash chain columns (AU-78)
    if context.is_offline_mode() or "audit_events" in existing_tables:
        with op.batch_alter_table("audit_events", recreate="auto") as batch_op:
            if context.is_offline_mode() or "prev_hash" not in audit_cols:
                batch_op.add_column(sa.Column("prev_hash", sa.String(length=64), nullable=True))
            if context.is_offline_mode() or "entry_hash" not in audit_cols:
                batch_op.add_column(sa.Column("entry_hash", sa.String(length=64), nullable=True))
                batch_op.create_index("ix_audit_events_entry_hash", ["entry_hash"], unique=False)

    # 2. Extend email_drafts with sent_at and external_message_id (AU-76)
    if context.is_offline_mode() or "email_drafts" in existing_tables:
        with op.batch_alter_table("email_drafts", recreate="auto") as batch_op:
            if context.is_offline_mode() or "sent_at" not in draft_cols:
                batch_op.add_column(sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
            if context.is_offline_mode() or "external_message_id" not in draft_cols:
                batch_op.add_column(sa.Column("external_message_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    if context.is_offline_mode():
        existing_tables: set[str] = set()
        audit_cols: set[str] = set()
        draft_cols: set[str] = set()
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())
        audit_cols = (
            {c["name"] for c in insp.get_columns("audit_events")}
            if "audit_events" in existing_tables
            else set()
        )
        draft_cols = (
            {c["name"] for c in insp.get_columns("email_drafts")}
            if "email_drafts" in existing_tables
            else set()
        )

    if context.is_offline_mode() or "email_drafts" in existing_tables:
        with op.batch_alter_table("email_drafts", recreate="auto") as batch_op:
            if context.is_offline_mode() or "external_message_id" in draft_cols:
                batch_op.drop_column("external_message_id")
            if context.is_offline_mode() or "sent_at" in draft_cols:
                batch_op.drop_column("sent_at")

    if context.is_offline_mode() or "audit_events" in existing_tables:
        with op.batch_alter_table("audit_events", recreate="auto") as batch_op:
            if context.is_offline_mode() or "entry_hash" in audit_cols:
                batch_op.drop_index("ix_audit_events_entry_hash")
                batch_op.drop_column("entry_hash")
            if context.is_offline_mode() or "prev_hash" in audit_cols:
                batch_op.drop_column("prev_hash")
