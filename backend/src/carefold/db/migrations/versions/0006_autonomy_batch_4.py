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

"""Autonomy Batch 4 schema evolution: preventive_records, import_batches, school_forms.

Revision ID: 0006_autonomy_batch_4
Revises: 0005_autonomy_batch_3
Create Date: 2026-10-13 12:05:00.000000

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0006_autonomy_batch_4"
down_revision: Union[str, None] = "0005_autonomy_batch_3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        existing_tables = set()
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())

    # 1. preventive_records table (AU-36)
    if "preventive_records" not in existing_tables:
        op.create_table(
            "preventive_records",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("rule_id", sa.String(128), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="due"),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("schedule_source", sa.String(32), nullable=False, server_default="aap_2026"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("profile_id", "rule_id", name="uq_preventive_records_profile_rule"),
        )
        op.create_index("ix_preventive_records_profile_id", "preventive_records", ["profile_id"], unique=False)
        op.create_index("ix_preventive_records_rule_id", "preventive_records", ["rule_id"], unique=False)
        op.create_index("ix_preventive_records_status", "preventive_records", ["status"], unique=False)
        op.create_index(
            "ix_preventive_records_profile_status",
            "preventive_records",
            ["profile_id", "status"],
            unique=False,
        )

    # 2. import_batches table (AU-38)
    if "import_batches" not in existing_tables:
        op.create_table(
            "import_batches",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("attachment_id", sa.String(36), sa.ForeignKey("attachments.id", ondelete="SET NULL"), nullable=True),
            sa.Column("format", sa.String(32), nullable=False),
            sa.Column("source_name", sa.String(255), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="staged"),
            sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("staged_records_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("committed_resource_ids_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_import_batches_profile_id", "import_batches", ["profile_id"], unique=False)
        op.create_index("ix_import_batches_attachment_id", "import_batches", ["attachment_id"], unique=False)
        op.create_index("ix_import_batches_status", "import_batches", ["status"], unique=False)
        op.create_index(
            "ix_import_batches_profile_status",
            "import_batches",
            ["profile_id", "status"],
            unique=False,
        )

    # 3. school_forms table (AU-39)
    if "school_forms" not in existing_tables:
        op.create_table(
            "school_forms",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("attachment_id", sa.String(36), sa.ForeignKey("attachments.id", ondelete="SET NULL"), nullable=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("school_or_camp_name", sa.String(255), nullable=True),
            sa.Column("form_type", sa.String(64), nullable=False, server_default="general"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reminder_id", sa.String(36), sa.ForeignKey("reminders.id", ondelete="SET NULL"), nullable=True),
            sa.Column("prefill_draft_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_school_forms_profile_id", "school_forms", ["profile_id"], unique=False)
        op.create_index("ix_school_forms_attachment_id", "school_forms", ["attachment_id"], unique=False)
        op.create_index("ix_school_forms_status", "school_forms", ["status"], unique=False)
        op.create_index("ix_school_forms_expires_at", "school_forms", ["expires_at"], unique=False)
        op.create_index(
            "ix_school_forms_profile_status",
            "school_forms",
            ["profile_id", "status"],
            unique=False,
        )


def downgrade() -> None:
    if context.is_offline_mode():
        existing_tables = {"preventive_records", "import_batches", "school_forms"}
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())

    if "school_forms" in existing_tables:
        op.drop_table("school_forms")

    if "import_batches" in existing_tables:
        op.drop_table("import_batches")

    if "preventive_records" in existing_tables:
        op.drop_table("preventive_records")
