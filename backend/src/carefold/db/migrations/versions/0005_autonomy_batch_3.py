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

"""Autonomy Batch 3 schema evolution: health_resources, appointments, reminders, notes.linked_appointment_id.

Revision ID: 0005_autonomy_batch_3
Revises: 0004_autonomy_batch_2
Create Date: 2026-10-13 04:30:00.000000

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005_autonomy_batch_3"
down_revision: Union[str, None] = "0004_autonomy_batch_2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        existing_tables = set()
        notes_cols = set()
        notes_indexes = set()
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())
        notes_cols = {c["name"] for c in insp.get_columns("notes")} if "notes" in existing_tables else set()
        notes_indexes = {idx["name"] for idx in insp.get_indexes("notes")} if "notes" in existing_tables else set()

    # 1. health_resources table (AU-30, AU-31)
    if "health_resources" not in existing_tables:
        op.create_table(
            "health_resources",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("resource_type", sa.String(64), nullable=False),
            sa.Column("source_type", sa.String(64), nullable=False),
            sa.Column("source_ref", sa.String(255), nullable=True),
            sa.Column("source_id", sa.String(255), nullable=True),
            sa.Column("content_hash", sa.String(64), nullable=True),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("profile_id", "source_type", "source_ref", "source_id", name="uq_health_resources_source"),
        )
        op.create_index("ix_health_resources_profile_id", "health_resources", ["profile_id"], unique=False)
        op.create_index("ix_health_resources_effective_at", "health_resources", ["effective_at"], unique=False)
        op.create_index(
            "ix_health_resources_profile_type_effective",
            "health_resources",
            ["profile_id", "resource_type", "effective_at"],
            unique=False,
        )

    # 2. appointments table (AU-29)
    if "appointments" not in existing_tables:
        op.create_table(
            "appointments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("provider_name", sa.String(255), nullable=True),
            sa.Column("specialty", sa.String(128), nullable=True),
            sa.Column("location", sa.String(255), nullable=True),
            sa.Column("clinic_phone", sa.String(64), nullable=True),
            sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
            sa.Column("status", sa.String(32), nullable=False, server_default="scheduled"),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("preparation_notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_appointments_profile_id", "appointments", ["profile_id"], unique=False)
        op.create_index("ix_appointments_start_time", "appointments", ["start_time"], unique=False)
        op.create_index("ix_appointments_status", "appointments", ["status"], unique=False)
        op.create_index("ix_appointments_profile_start", "appointments", ["profile_id", "start_time"], unique=False)

    # 3. reminders table (AU-28)
    if "reminders" not in existing_tables:
        op.create_table(
            "reminders",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category", sa.String(64), nullable=False, server_default="general"),
            sa.Column("rrule", sa.String(255), nullable=True),
            sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
            sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("snooze_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_reminders_profile_id", "reminders", ["profile_id"], unique=False)
        op.create_index("ix_reminders_next_due_at", "reminders", ["next_due_at"], unique=False)
        op.create_index("ix_reminders_status", "reminders", ["status"], unique=False)
        op.create_index("ix_reminders_category", "reminders", ["category"], unique=False)
        op.create_index(
            "ix_reminders_profile_status_due",
            "reminders",
            ["profile_id", "status", "next_due_at"],
            unique=False,
        )

    copy_notes = None
    if context.is_offline_mode():
        from carefold.db.base import Base
        copy_notes = Base.metadata.tables.get("notes")

    # 4. notes table evolution (AU-35)
    if "notes" in existing_tables or context.is_offline_mode():
        with op.batch_alter_table("notes", copy_from=copy_notes) as batch_op:
            if "linked_appointment_id" not in notes_cols:
                batch_op.add_column(
                    sa.Column(
                        "linked_appointment_id",
                        sa.String(36),
                        sa.ForeignKey(
                            "appointments.id",
                            ondelete="SET NULL",
                            name="fk_notes_linked_appointment_id",
                        ),
                        nullable=True,
                    )
                )
            if "ix_notes_linked_appointment_id" not in notes_indexes:
                batch_op.create_index("ix_notes_linked_appointment_id", ["linked_appointment_id"], unique=False)
            if "ix_notes_profile_id_type" not in notes_indexes:
                batch_op.create_index("ix_notes_profile_id_type", ["profile_id", "type"], unique=False)


def downgrade() -> None:
    if context.is_offline_mode():
        existing_tables = {"health_resources", "appointments", "reminders", "notes"}
        existing_notes_cols = {"linked_appointment_id"}
        existing_notes_indexes = {"ix_notes_linked_appointment_id", "ix_notes_profile_id_type"}
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())
        existing_notes_cols = {c["name"] for c in insp.get_columns("notes")} if "notes" in existing_tables else set()
        existing_notes_indexes = {idx["name"] for idx in insp.get_indexes("notes")} if "notes" in existing_tables else set()

    copy_notes = None
    if context.is_offline_mode():
        from carefold.db.base import Base
        copy_notes = Base.metadata.tables.get("notes")

    # 1. Revert notes additions via batch alter
    if "notes" in existing_tables:
        with op.batch_alter_table("notes", copy_from=copy_notes) as batch_op:
            if "ix_notes_profile_id_type" in existing_notes_indexes:
                batch_op.drop_index("ix_notes_profile_id_type")
            if "ix_notes_linked_appointment_id" in existing_notes_indexes:
                batch_op.drop_index("ix_notes_linked_appointment_id")
            if "linked_appointment_id" in existing_notes_cols:
                batch_op.drop_column("linked_appointment_id")

    # 2. Drop reminders table
    if "reminders" in existing_tables:
        op.drop_table("reminders")

    # 3. Drop appointments table (must drop after notes drops FK column)
    if "appointments" in existing_tables:
        op.drop_table("appointments")

    # 4. Drop health_resources table
    if "health_resources" in existing_tables:
        op.drop_table("health_resources")
