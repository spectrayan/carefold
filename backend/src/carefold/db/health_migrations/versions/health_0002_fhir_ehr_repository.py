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

"""Relational FHIR R4 version history, terminology coding index, and reference graph tables (#282).

Revision ID: health_0002_fhir_ehr_repository
Revises: health_0001_baseline
Create Date: 2026-11-08 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "health_0002_fhir_ehr_repository"
down_revision: Union[str, None] = "health_0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_SCOPE = "health.clinical"

REPOSITORY_TABLES = (
    "health_resource_versions",
    "health_resource_codings",
    "health_resource_references",
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind) if not context.is_offline_mode() else None
    existing_tables = set(insp.get_table_names()) if insp else set()

    # 1. Table: health_resource_versions
    if "health_resource_versions" not in existing_tables:
        op.create_table(
            "health_resource_versions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "resource_id",
                sa.String(36),
                sa.ForeignKey("health_resources.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "profile_id",
                sa.String(36),
                sa.ForeignKey("profiles.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("resource_type", sa.String(64), nullable=False),
            sa.Column("version_id", sa.Integer(), nullable=False),
            sa.Column("operation", sa.String(16), nullable=False, server_default="create"),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("fhir_json", sa.JSON(), nullable=False),
            sa.Column(
                "source_batch_id",
                sa.String(36),
                sa.ForeignKey("import_batches.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("actor_user_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("scope", sa.String(64), nullable=False, server_default=DEFAULT_SCOPE),
            sa.UniqueConstraint(
                "resource_id",
                "version_id",
                name="uq_health_resource_versions_resource_version",
            ),
        )
        op.create_index(
            "ix_health_resource_versions_resource_id",
            "health_resource_versions",
            ["resource_id"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_versions_profile_id",
            "health_resource_versions",
            ["profile_id"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_versions_resource_type",
            "health_resource_versions",
            ["resource_type"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_versions_source_batch_id",
            "health_resource_versions",
            ["source_batch_id"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_versions_scope",
            "health_resource_versions",
            ["scope"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_versions_profile_scope_type",
            "health_resource_versions",
            ["profile_id", "scope", "resource_type"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_versions_resource_version",
            "health_resource_versions",
            ["resource_id", "version_id"],
            unique=False,
        )

    # 2. Table: health_resource_codings
    if "health_resource_codings" not in existing_tables:
        op.create_table(
            "health_resource_codings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "resource_id",
                sa.String(36),
                sa.ForeignKey("health_resources.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "profile_id",
                sa.String(36),
                sa.ForeignKey("profiles.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("resource_type", sa.String(64), nullable=False),
            sa.Column("element_path", sa.String(128), nullable=False, server_default="code"),
            sa.Column("system", sa.String(255), nullable=True),
            sa.Column("code", sa.String(128), nullable=False),
            sa.Column("display", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("scope", sa.String(64), nullable=False, server_default=DEFAULT_SCOPE),
            sa.UniqueConstraint(
                "resource_id",
                "element_path",
                "system",
                "code",
                name="uq_health_resource_codings_res_path_sys_code",
            ),
        )
        op.create_index(
            "ix_health_resource_codings_resource_id",
            "health_resource_codings",
            ["resource_id"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_codings_profile_id",
            "health_resource_codings",
            ["profile_id"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_codings_resource_type",
            "health_resource_codings",
            ["resource_type"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_codings_scope",
            "health_resource_codings",
            ["scope"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_codings_profile_sys_code",
            "health_resource_codings",
            ["profile_id", "system", "code"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_codings_profile_scope_code",
            "health_resource_codings",
            ["profile_id", "scope", "code"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_codings_profile_type_code",
            "health_resource_codings",
            ["profile_id", "resource_type", "code"],
            unique=False,
        )

    # 3. Table: health_resource_references
    if "health_resource_references" not in existing_tables:
        op.create_table(
            "health_resource_references",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "source_resource_id",
                sa.String(36),
                sa.ForeignKey("health_resources.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "profile_id",
                sa.String(36),
                sa.ForeignKey("profiles.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source_type", sa.String(64), nullable=False),
            sa.Column("reference_field", sa.String(128), nullable=False),
            sa.Column("target_type", sa.String(64), nullable=False),
            sa.Column("target_id", sa.String(128), nullable=False),
            sa.Column(
                "target_resource_id",
                sa.String(36),
                sa.ForeignKey("health_resources.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("raw_reference", sa.String(255), nullable=False),
            sa.Column("is_external", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("scope", sa.String(64), nullable=False, server_default=DEFAULT_SCOPE),
            sa.UniqueConstraint(
                "source_resource_id",
                "reference_field",
                "target_type",
                "target_id",
                "raw_reference",
                name="uq_health_resource_references_edge",
            ),
        )
        op.create_index(
            "ix_health_resource_references_source_resource_id",
            "health_resource_references",
            ["source_resource_id"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_references_profile_id",
            "health_resource_references",
            ["profile_id"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_references_source_type",
            "health_resource_references",
            ["source_type"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_references_target_type",
            "health_resource_references",
            ["target_type"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_references_target_id",
            "health_resource_references",
            ["target_id"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_references_scope",
            "health_resource_references",
            ["scope"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_refs_profile_target",
            "health_resource_references",
            ["profile_id", "target_type", "target_id"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_refs_profile_scope_source",
            "health_resource_references",
            ["profile_id", "scope", "source_resource_id"],
            unique=False,
        )
        op.create_index(
            "ix_health_resource_refs_target_resource_id",
            "health_resource_references",
            ["target_resource_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind) if not context.is_offline_mode() else None
    existing_tables = set(insp.get_table_names()) if insp else set(REPOSITORY_TABLES)

    for tbl in reversed(REPOSITORY_TABLES):
        if context.is_offline_mode() or tbl in existing_tables:
            op.drop_table(tbl)
