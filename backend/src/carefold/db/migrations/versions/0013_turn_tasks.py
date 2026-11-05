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

"""Store orchestration hand-offs: ``turn_tasks`` table and audit hand-off columns.

Adds ``turn_id``, ``task_id``, ``parent_task_id``, ``input_hash``,
``output_hash`` and ``error_code`` to ``audit_events``, and creates
``turn_tasks`` with one row per subagent hand-off of a turn. Both steps are
idempotent so databases created from the current models upgrade cleanly.

Revision ID: 0013_turn_tasks
Revises: 0012_agent_extensions
Create Date: 2026-11-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

from yarvelle_core.scope.context import DEFAULT_SCOPE

revision: str = "0013_turn_tasks"
down_revision: Union[str, None] = "0012_agent_extensions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_AUDIT = "audit_events"
_TASKS = "turn_tasks"

_AUDIT_COLUMNS = (
    ("turn_id", 64),
    ("task_id", 128),
    ("parent_task_id", 128),
    ("input_hash", 64),
    ("output_hash", 64),
    ("error_code", 64),
)
_AUDIT_INDEXES = (("ix_audit_events_turn_id", "turn_id"), ("ix_audit_events_task_id", "task_id"))


def _inspector() -> sa.Inspector | None:
    """Returns an inspector, or None in offline mode."""
    if context.is_offline_mode():
        return None
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    insp = _inspector()
    tables = set(insp.get_table_names()) if insp is not None else {_AUDIT}

    if _AUDIT in tables:
        cols = {c["name"] for c in insp.get_columns(_AUDIT)} if insp is not None else set()
        indexes = {i["name"] for i in insp.get_indexes(_AUDIT)} if insp is not None else set()
        missing = [(name, size) for name, size in _AUDIT_COLUMNS if name not in cols]
        new_indexes = [(ix, col) for ix, col in _AUDIT_INDEXES if ix not in indexes]
        if missing or new_indexes:
            with op.batch_alter_table(_AUDIT, recreate="auto") as batch_op:
                for name, size in missing:
                    batch_op.add_column(sa.Column(name, sa.String(length=size), nullable=True))
                for ix, col in new_indexes:
                    batch_op.create_index(ix, [col], unique=False)

    if _TASKS not in tables or insp is None:
        op.create_table(
            _TASKS,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("turn_id", sa.String(length=64), nullable=False),
            sa.Column("task_id", sa.String(length=128), nullable=False),
            sa.Column("thread_id", sa.String(length=64), nullable=True),
            sa.Column("parent_task_id", sa.String(length=128), nullable=True),
            sa.Column("agent_id", sa.String(length=64), nullable=False),
            sa.Column("agent_title", sa.String(length=255), nullable=False),
            sa.Column("state", sa.String(length=16), nullable=False),
            sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("input_hash", sa.String(length=64), nullable=True),
            sa.Column("output_hash", sa.String(length=64), nullable=True),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("scope", sa.String(length=64), nullable=False, server_default=DEFAULT_SCOPE),
            sa.UniqueConstraint("turn_id", "task_id", name="uq_turn_tasks_turn_task"),
        )
        op.create_index("ix_turn_tasks_turn_id", _TASKS, ["turn_id"], unique=False)
        op.create_index("ix_turn_tasks_thread_id", _TASKS, ["thread_id"], unique=False)
        op.create_index("ix_turn_tasks_agent_id", _TASKS, ["agent_id"], unique=False)
        op.create_index("ix_turn_tasks_scope", _TASKS, ["scope"], unique=False)


def downgrade() -> None:
    insp = _inspector()
    tables = set(insp.get_table_names()) if insp is not None else {_AUDIT, _TASKS}

    if _TASKS in tables:
        op.drop_table(_TASKS)

    if _AUDIT in tables:
        cols = {c["name"] for c in insp.get_columns(_AUDIT)} if insp is not None else {n for n, _ in _AUDIT_COLUMNS}
        indexes = {i["name"] for i in insp.get_indexes(_AUDIT)} if insp is not None else {ix for ix, _ in _AUDIT_INDEXES}
        drop_ix = [ix for ix, _ in _AUDIT_INDEXES if ix in indexes]
        drop_cols = [n for n, _ in _AUDIT_COLUMNS if n in cols]
        if drop_ix or drop_cols:
            with op.batch_alter_table(_AUDIT, recreate="auto") as batch_op:
                for ix in drop_ix:
                    batch_op.drop_index(ix)
                for name in drop_cols:
                    batch_op.drop_column(name)
