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

"""Internationalization (i18n) storage schema evolution: BCP 47 locale columns on users, profiles, notes, attachments, and health_resources.

Revision ID: 0010_i18n_and_locale_storage
Revises: 0009_companion_and_handover
Create Date: 2026-10-14 10:25:00.000000

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0010_i18n_and_locale_storage"
down_revision: Union[str, None] = "0009_companion_and_handover"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_cols(insp: sa.Inspector, existing_tables: set[str], table_name: str) -> set[str]:
    if table_name not in existing_tables:
        return set()
    return {c["name"] for c in insp.get_columns(table_name)}


def upgrade() -> None:
    if context.is_offline_mode():
        existing_tables: set[str] = set()
        user_cols: set[str] = set()
        profile_cols: set[str] = set()
        note_cols: set[str] = set()
        att_cols: set[str] = set()
        hr_cols: set[str] = set()
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())
        user_cols = _table_cols(insp, existing_tables, "users")
        profile_cols = _table_cols(insp, existing_tables, "profiles")
        note_cols = _table_cols(insp, existing_tables, "notes")
        att_cols = _table_cols(insp, existing_tables, "attachments")
        hr_cols = _table_cols(insp, existing_tables, "health_resources")

    # 1. users.preferred_locale (BCP 47 tag, default 'en-US')
    if context.is_offline_mode() or "users" in existing_tables:
        with op.batch_alter_table("users", recreate="auto") as batch_op:
            if context.is_offline_mode() or "preferred_locale" not in user_cols:
                batch_op.add_column(
                    sa.Column(
                        "preferred_locale",
                        sa.String(length=16),
                        nullable=False,
                        server_default="en-US",
                    )
                )

    # 2. profiles.preferred_locale (BCP 47 tag, default 'en-US')
    if context.is_offline_mode() or "profiles" in existing_tables:
        with op.batch_alter_table("profiles", recreate="auto") as batch_op:
            if context.is_offline_mode() or "preferred_locale" not in profile_cols:
                batch_op.add_column(
                    sa.Column(
                        "preferred_locale",
                        sa.String(length=16),
                        nullable=False,
                        server_default="en-US",
                    )
                )

    # 3. notes.locale (BCP 47 tag, default 'en-US', indexed)
    if context.is_offline_mode() or "notes" in existing_tables:
        with op.batch_alter_table("notes", recreate="auto") as batch_op:
            if context.is_offline_mode() or "locale" not in note_cols:
                batch_op.add_column(
                    sa.Column(
                        "locale",
                        sa.String(length=16),
                        nullable=False,
                        server_default="en-US",
                    )
                )
                batch_op.create_index("ix_notes_locale", ["locale"], unique=False)

    # 4. attachments.locale (BCP 47 tag, default 'en-US')
    if context.is_offline_mode() or "attachments" in existing_tables:
        with op.batch_alter_table("attachments", recreate="auto") as batch_op:
            if context.is_offline_mode() or "locale" not in att_cols:
                batch_op.add_column(
                    sa.Column(
                        "locale",
                        sa.String(length=16),
                        nullable=False,
                        server_default="en-US",
                    )
                )

    # 5. health_resources.locale (BCP 47 tag, default 'en-US')
    if context.is_offline_mode() or "health_resources" in existing_tables:
        with op.batch_alter_table("health_resources", recreate="auto") as batch_op:
            if context.is_offline_mode() or "locale" not in hr_cols:
                batch_op.add_column(
                    sa.Column(
                        "locale",
                        sa.String(length=16),
                        nullable=False,
                        server_default="en-US",
                    )
                )


def downgrade() -> None:
    if context.is_offline_mode():
        existing_tables: set[str] = set()
        user_cols: set[str] = set()
        profile_cols: set[str] = set()
        note_cols: set[str] = set()
        att_cols: set[str] = set()
        hr_cols: set[str] = set()
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())
        user_cols = _table_cols(insp, existing_tables, "users")
        profile_cols = _table_cols(insp, existing_tables, "profiles")
        note_cols = _table_cols(insp, existing_tables, "notes")
        att_cols = _table_cols(insp, existing_tables, "attachments")
        hr_cols = _table_cols(insp, existing_tables, "health_resources")

    if context.is_offline_mode() or "health_resources" in existing_tables:
        with op.batch_alter_table("health_resources", recreate="auto") as batch_op:
            if context.is_offline_mode() or "locale" in hr_cols:
                batch_op.drop_column("locale")

    if context.is_offline_mode() or "attachments" in existing_tables:
        with op.batch_alter_table("attachments", recreate="auto") as batch_op:
            if context.is_offline_mode() or "locale" in att_cols:
                batch_op.drop_column("locale")

    if context.is_offline_mode() or "notes" in existing_tables:
        with op.batch_alter_table("notes", recreate="auto") as batch_op:
            if context.is_offline_mode() or "locale" in note_cols:
                batch_op.drop_index("ix_notes_locale")
                batch_op.drop_column("locale")

    if context.is_offline_mode() or "profiles" in existing_tables:
        with op.batch_alter_table("profiles", recreate="auto") as batch_op:
            if context.is_offline_mode() or "preferred_locale" in profile_cols:
                batch_op.drop_column("preferred_locale")

    if context.is_offline_mode() or "users" in existing_tables:
        with op.batch_alter_table("users", recreate="auto") as batch_op:
            if context.is_offline_mode() or "preferred_locale" in user_cols:
                batch_op.drop_column("preferred_locale")
