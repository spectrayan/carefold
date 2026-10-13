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

"""Autonomy Batch 2 schema evolution: Deep Entity Scoping (notes & chat_threads profile_id NOT NULL).

Revision ID: 0004_autonomy_batch_2
Revises: 0003_autonomy_batch_1
Create Date: 2026-10-12 23:30:00.000000

"""
from datetime import datetime, timezone
from typing import Sequence, Union
import uuid

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_autonomy_batch_2"
down_revision: Union[str, None] = "0003_autonomy_batch_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        existing_tables = {"notes", "chat_threads", "profiles"}
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())

    # Safe data backfilling (online mode)
    if not context.is_offline_mode() and "profiles" in existing_tables:
        bind = op.get_bind()

        # Step 0: Ensure at least one profile exists if any unassigned notes or threads exist
        has_null_notes = False
        has_null_threads = False

        if "notes" in existing_tables:
            null_notes_count = bind.execute(
                sa.text("SELECT COUNT(*) FROM notes WHERE profile_id IS NULL")
            ).scalar()
            has_null_notes = (null_notes_count or 0) > 0

        if "chat_threads" in existing_tables:
            null_threads_count = bind.execute(
                sa.text("SELECT COUNT(*) FROM chat_threads WHERE profile_id IS NULL")
            ).scalar()
            has_null_threads = (null_threads_count or 0) > 0

        if has_null_notes or has_null_threads:
            any_profile = bind.execute(sa.text("SELECT id FROM profiles LIMIT 1")).fetchone()
            if any_profile is None:
                fallback_profile_id = str(uuid.uuid4())
                now_iso = datetime.now(timezone.utc).isoformat()
                bind.execute(
                    sa.text("""
                        INSERT INTO profiles (
                            id, name, relationship, role, avatar_color, is_primary, created_at, updated_at
                        ) VALUES (
                            :id, 'Default Profile', 'self', 'self', '1', 1, :now, :now
                        )
                    """),
                    {"id": fallback_profile_id, "now": now_iso},
                )

        # Step 1: Backfill notes
        if "notes" in existing_tables and has_null_notes:
            # 1a: Match user primary profile
            bind.execute(
                sa.text("""
                    UPDATE notes
                    SET profile_id = (
                        SELECT p.id FROM profiles p
                        WHERE p.user_id = notes.user_id AND p.is_primary = 1
                        LIMIT 1
                    )
                    WHERE profile_id IS NULL AND user_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM profiles p
                        WHERE p.user_id = notes.user_id AND p.is_primary = 1
                    );
                """)
            )
            # 1b: Match user any profile
            bind.execute(
                sa.text("""
                    UPDATE notes
                    SET profile_id = (
                        SELECT p.id FROM profiles p
                        WHERE p.user_id = notes.user_id
                        ORDER BY p.created_at ASC
                        LIMIT 1
                    )
                    WHERE profile_id IS NULL AND user_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM profiles p
                        WHERE p.user_id = notes.user_id
                    );
                """)
            )
            # 1c: Match global primary or first profile
            bind.execute(
                sa.text("""
                    UPDATE notes
                    SET profile_id = (
                        SELECT p.id FROM profiles p
                        ORDER BY p.is_primary DESC, p.created_at ASC
                        LIMIT 1
                    )
                    WHERE profile_id IS NULL;
                """)
            )

        # Step 2: Backfill chat_threads
        if "chat_threads" in existing_tables and has_null_threads:
            # 2a: Match user primary profile
            bind.execute(
                sa.text("""
                    UPDATE chat_threads
                    SET profile_id = (
                        SELECT p.id FROM profiles p
                        WHERE p.user_id = chat_threads.user_id AND p.is_primary = 1
                        LIMIT 1
                    )
                    WHERE profile_id IS NULL AND user_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM profiles p
                        WHERE p.user_id = chat_threads.user_id AND p.is_primary = 1
                    );
                """)
            )
            # 2b: Match user any profile
            bind.execute(
                sa.text("""
                    UPDATE chat_threads
                    SET profile_id = (
                        SELECT p.id FROM profiles p
                        WHERE p.user_id = chat_threads.user_id
                        ORDER BY p.created_at ASC
                        LIMIT 1
                    )
                    WHERE profile_id IS NULL AND user_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM profiles p
                        WHERE p.user_id = chat_threads.user_id
                    );
                """)
            )
            # 2c: Match global primary or first profile
            bind.execute(
                sa.text("""
                    UPDATE chat_threads
                    SET profile_id = (
                        SELECT p.id FROM profiles p
                        ORDER BY p.is_primary DESC, p.created_at ASC
                        LIMIT 1
                    )
                    WHERE profile_id IS NULL;
                """)
            )

    copy_notes = None
    copy_threads = None
    if context.is_offline_mode():
        from carefold.db.base import Base
        copy_notes = Base.metadata.tables.get("notes")
        copy_threads = Base.metadata.tables.get("chat_threads")

    # Step 3: Apply NOT NULL constraint via batch rebuild (SQLite) or ALTER COLUMN (PostgreSQL)
    if "notes" in existing_tables:
        with op.batch_alter_table("notes", copy_from=copy_notes) as batch_op:
            batch_op.alter_column(
                "profile_id",
                existing_type=sa.String(36),
                nullable=False,
                existing_nullable=True,
            )

    if "chat_threads" in existing_tables:
        with op.batch_alter_table("chat_threads", copy_from=copy_threads) as batch_op:
            batch_op.alter_column(
                "profile_id",
                existing_type=sa.String(36),
                nullable=False,
                existing_nullable=True,
            )


def downgrade() -> None:
    if context.is_offline_mode():
        existing_tables = {"notes", "chat_threads"}
    else:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        existing_tables = set(insp.get_table_names())

    copy_notes = None
    copy_threads = None
    if context.is_offline_mode():
        from carefold.db.base import Base
        copy_notes = Base.metadata.tables.get("notes")
        copy_threads = Base.metadata.tables.get("chat_threads")

    # Revert chat_threads.profile_id to nullable=True
    if "chat_threads" in existing_tables:
        with op.batch_alter_table("chat_threads", copy_from=copy_threads) as batch_op:
            batch_op.alter_column(
                "profile_id",
                existing_type=sa.String(36),
                nullable=True,
                existing_nullable=False,
            )

    # Revert notes.profile_id to nullable=True
    if "notes" in existing_tables:
        with op.batch_alter_table("notes", copy_from=copy_notes) as batch_op:
            batch_op.alter_column(
                "profile_id",
                existing_type=sa.String(36),
                nullable=True,
                existing_nullable=False,
            )
