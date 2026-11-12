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

"""Initial Health Pack baseline schema: idempotently claims and verifies the 7 health ORM tables.

Revision ID: health_0001_baseline
Revises: None
Create Date: 2026-10-18 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "health_0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = ("health",)
depends_on: Union[str, Sequence[str], None] = None

REQUIRED_CORE_REVISION = "0013_turn_tasks"
DEFAULT_SCOPE = "health"

HEALTH_TABLES = [
    "health_resources",
    "appointments",
    "reminders",
    "preventive_records",
    "import_batches",
    "school_forms",
    "school_ics_feeds",
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind) if not context.is_offline_mode() else None
    existing_tables = set(insp.get_table_names()) if insp else set()

    # 1. Verify Core Baseline Prerequisite
    if not context.is_offline_mode():
        if "alembic_version" not in existing_tables:
            raise RuntimeError(
                "Core database migrations must be initialized before Health Pack migrations. "
                "Table 'alembic_version' was not found."
            )
        rows = [r[0] for r in bind.exec_driver_sql("SELECT version_num FROM alembic_version;").fetchall()]
        from carefold.db.session import is_core_revision_satisfied

        if not is_core_revision_satisfied(REQUIRED_CORE_REVISION, {str(r) for r in rows if r}):
            raise RuntimeError(
                f"Health Pack requires core migration revision '{REQUIRED_CORE_REVISION}', "
                f"but found core revisions: {rows}. Run core migrations first."
            )

    # 2. Idempotent Table Definition for the 7 Health Tables
    # If upgrading an existing Carefold database where core 0001..0011 already ran,
    # tables already exist and create_table is skipped.
    # If running against a greenfield pack environment, tables are created with full schemas.

    # Table 1: health_resources
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
            sa.Column("scope", sa.String(64), nullable=False, server_default=DEFAULT_SCOPE),
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
        op.create_index("ix_health_resources_scope", "health_resources", ["scope"], unique=False)

    # Table 2: appointments
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
            sa.Column("scope", sa.String(64), nullable=False, server_default=DEFAULT_SCOPE),
        )
        op.create_index("ix_appointments_profile_id", "appointments", ["profile_id"], unique=False)
        op.create_index("ix_appointments_start_time", "appointments", ["start_time"], unique=False)
        op.create_index("ix_appointments_status", "appointments", ["status"], unique=False)
        op.create_index("ix_appointments_profile_start", "appointments", ["profile_id", "start_time"], unique=False)
        op.create_index("ix_appointments_scope", "appointments", ["scope"], unique=False)

    # Table 3: reminders
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
            sa.Column("scope", sa.String(64), nullable=False, server_default=DEFAULT_SCOPE),
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
        op.create_index("ix_reminders_scope", "reminders", ["scope"], unique=False)

    # Table 4: preventive_records
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
            sa.Column("scope", sa.String(64), nullable=False, server_default=DEFAULT_SCOPE),
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
        op.create_index("ix_preventive_records_scope", "preventive_records", ["scope"], unique=False)

    # Table 5: import_batches
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
            sa.Column("scope", sa.String(64), nullable=False, server_default=DEFAULT_SCOPE),
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
        op.create_index("ix_import_batches_scope", "import_batches", ["scope"], unique=False)

    # Table 6: school_forms
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
            sa.Column("scope", sa.String(64), nullable=False, server_default=DEFAULT_SCOPE),
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
        op.create_index("ix_school_forms_scope", "school_forms", ["scope"], unique=False)

    # Table 7: school_ics_feeds
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
            sa.Column("scope", sa.String(64), nullable=False, server_default=DEFAULT_SCOPE),
        )
        op.create_index("ix_school_ics_feeds_profile_id", "school_ics_feeds", ["profile_id"], unique=False)
        op.create_index("ix_school_ics_feeds_status", "school_ics_feeds", ["status"], unique=False)
        op.create_index("ix_school_ics_feeds_scope", "school_ics_feeds", ["scope"], unique=False)

    # 3. Defensive Check: Ensure scope Column Exists on All 7 Tables
    # In case tables existed from pre-0011_scopes without the scope column
    if not context.is_offline_mode():
        for tbl in HEALTH_TABLES:
            if tbl in existing_tables:
                cols = {c["name"] for c in insp.get_columns(tbl)}
                if "scope" not in cols:
                    with op.batch_alter_table(tbl, recreate="auto") as batch_op:
                        batch_op.add_column(
                            sa.Column("scope", sa.String(64), nullable=False, server_default=DEFAULT_SCOPE)
                        )
                        batch_op.create_index(f"ix_{tbl}_scope", ["scope"], unique=False)


def downgrade() -> None:
    # Downgrade drops the 7 health tables if pack is uninstalled
    for tbl in reversed(HEALTH_TABLES):
        op.drop_table(tbl)
