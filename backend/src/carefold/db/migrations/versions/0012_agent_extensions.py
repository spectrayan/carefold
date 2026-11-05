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

"""Replace the agent ``care_stages_json`` column with a generic ``extensions_json`` object.

Existing non-empty care stages are preserved as ``{"care_stages": [...]}``.

Revision ID: 0012_agent_extensions
Revises: 0011_scopes
Create Date: 2026-11-05 12:15:00.000000

"""
import json
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

revision: str = "0012_agent_extensions"
down_revision: Union[str, None] = "0011_scopes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "agent"
_OLD = "care_stages_json"
_NEW = "extensions_json"
_KEY = "care_stages"


def _agent_cols() -> set[str] | None:
    """Returns the agent table's columns, or None in offline mode or when it is missing."""
    if context.is_offline_mode():
        return None
    insp = sa.inspect(op.get_bind())
    if _TABLE not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(_TABLE)}


def _loads(raw: object, fallback: object) -> object:
    if raw in (None, ""):
        return fallback
    try:
        return json.loads(str(raw))
    except ValueError:
        return fallback


def upgrade() -> None:
    cols = _agent_cols()
    if cols is not None and not cols:
        return
    offline = cols is None

    if offline or _NEW not in cols:
        with op.batch_alter_table(_TABLE, recreate="auto") as batch_op:
            batch_op.add_column(sa.Column(_NEW, sa.Text(), nullable=False, server_default="{}"))

    if offline or _OLD not in cols:
        return

    bind = op.get_bind()
    rows = bind.execute(sa.text(f"SELECT id, {_OLD}, {_NEW} FROM {_TABLE};")).fetchall()
    for agent_id, old_raw, new_raw in rows:
        stages = _loads(old_raw, [])
        if not isinstance(stages, list) or not stages:
            continue
        ext = _loads(new_raw, {})
        if not isinstance(ext, dict):
            ext = {}
        ext.setdefault(_KEY, stages)
        bind.execute(
            sa.text(f"UPDATE {_TABLE} SET {_NEW} = :ext WHERE id = :id;"),
            {"ext": json.dumps(ext), "id": agent_id},
        )

    with op.batch_alter_table(_TABLE, recreate="auto") as batch_op:
        batch_op.drop_column(_OLD)


def downgrade() -> None:
    cols = _agent_cols()
    if cols is not None and not cols:
        return
    offline = cols is None

    if offline or _OLD not in cols:
        with op.batch_alter_table(_TABLE, recreate="auto") as batch_op:
            batch_op.add_column(sa.Column(_OLD, sa.Text(), nullable=False, server_default="[]"))

    if offline or _NEW not in cols:
        return

    bind = op.get_bind()
    rows = bind.execute(sa.text(f"SELECT id, {_NEW} FROM {_TABLE};")).fetchall()
    for agent_id, new_raw in rows:
        ext = _loads(new_raw, {})
        stages = ext.get(_KEY) if isinstance(ext, dict) else None
        if isinstance(stages, list) and stages:
            bind.execute(
                sa.text(f"UPDATE {_TABLE} SET {_OLD} = :stages WHERE id = :id;"),
                {"stages": json.dumps(stages), "id": agent_id},
            )

    with op.batch_alter_table(_TABLE, recreate="auto") as batch_op:
        batch_op.drop_column(_NEW)
