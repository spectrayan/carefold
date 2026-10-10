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

"""Multi-database async SQLAlchemy engine, connection pooling, and session management."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import AsyncIterator, Optional

from sqlalchemy import event, inspect
from sqlalchemy.engine.url import make_url, URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool, StaticPool

from carefold.config import settings
from carefold.constants.paths import ENV_DATABASE_URL, ENV_DATABASE_URL_FALLBACK
from carefold.db.base import Base
from carefold.logging import get_logger

logger = get_logger("carefold.db")

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def normalize_database_url(url: str) -> str:
    """Normalizes database URLs to async drivers for SQLite and PostgreSQL."""
    cleaned = url.strip()
    if cleaned == ":memory:":
        return "sqlite+aiosqlite:///:memory:"

    if cleaned.startswith("postgres://"):
        return "postgresql+asyncpg://" + cleaned[len("postgres://"):]
    if cleaned.startswith("postgresql://"):
        return "postgresql+asyncpg://" + cleaned[len("postgresql://"):]
    if cleaned.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + cleaned[len("postgresql+psycopg2://"):]

    if cleaned.startswith("sqlite://") and not cleaned.startswith("sqlite+"):
        return "sqlite+aiosqlite://" + cleaned[len("sqlite://"):]

    return cleaned


def sanitize_db_url(url: str | URL) -> str:
    """Masks credentials in database connection strings for safe logging."""
    url_str = str(url)
    try:
        parsed = make_url(url_str)
        return parsed.render_as_string(hide_password=True)
    except Exception:
        return re.sub(r"://([^:@]+):([^@]+)@", r"://\1:***@", url_str)


def resolve_database_url(url: Optional[str] = None) -> str:
    """Resolves the database URL adhering to priority rules:

    1. Explicit parameter
    2. CAREFOLD_DATABASE_URL environment variable
    3. DATABASE_URL environment variable
    4. settings.get_database_url()
    """
    if url is not None and url.strip():
        return normalize_database_url(url)

    env_cf = os.getenv(ENV_DATABASE_URL)
    if env_cf and env_cf.strip():
        return normalize_database_url(env_cf)

    env_db = os.getenv(ENV_DATABASE_URL_FALLBACK)
    if env_db and env_db.strip():
        return normalize_database_url(env_db)

    return normalize_database_url(settings.get_database_url())


def _ensure_sqlite_dir(url: str) -> None:
    """Ensures the parent directory exists for file-based SQLite databases."""
    if ":memory:" in url:
        return
    if "sqlite" in url:
        try:
            parsed = make_url(url)
            if parsed.database and parsed.database != ":memory:":
                db_path = Path(parsed.database)
                db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def create_db_engine(url: Optional[str] = None) -> AsyncEngine:
    """Creates a configured AsyncEngine with dialect-specific connection pooling."""
    resolved_url = resolve_database_url(url)
    _ensure_sqlite_dir(resolved_url)

    is_sqlite = "sqlite" in resolved_url
    is_memory = ":memory:" in resolved_url

    if is_sqlite:
        if is_memory:
            poolclass = StaticPool
            connect_args = {"check_same_thread": False}
        else:
            poolclass = NullPool
            connect_args = {"check_same_thread": False, "timeout": 30.0}

        engine = create_async_engine(
            resolved_url,
            poolclass=poolclass,
            connect_args=connect_args,
            echo=False,
        )

        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA busy_timeout = 10000;")
            cursor.execute("PRAGMA foreign_keys = ON;")
            cursor.close()

        return engine

    # PostgreSQL / other dialects: AsyncAdaptedQueuePool with pre-ping and recycling
    engine = create_async_engine(
        resolved_url,
        poolclass=AsyncAdaptedQueuePool,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30.0,
        pool_recycle=1800,
        pool_pre_ping=True,
        echo=False,
    )
    return engine


def get_engine(url: Optional[str] = None) -> AsyncEngine:
    """Returns the singleton AsyncEngine instance, creating it if needed."""
    global _engine
    if _engine is None:
        _engine = create_db_engine(url)
    return _engine


def get_session_factory(
    engine: Optional[AsyncEngine] = None,
) -> async_sessionmaker[AsyncSession]:
    """Returns an async_sessionmaker bound to the engine."""
    global _session_factory
    if engine is not None:
        return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


def reset_engine() -> None:
    """Resets global engine and sessionmaker references."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async session with auto-commit and rollback."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _run_schema_migrations(connection) -> None:
    """Safely adds missing columns and renames tables in existing SQLite / PostgreSQL databases without data loss."""
    inspector = inspect(connection)
    tables = inspector.get_table_names()

    # 1. Milestone 2: Table rename 'note' -> 'notes'
    if "note" in tables and "notes" not in tables:
        connection.exec_driver_sql("ALTER TABLE note RENAME TO notes;")
        tables.remove("note")
        tables.append("notes")
    elif "note" in tables and "notes" in tables:
        count_notes = connection.exec_driver_sql("SELECT count(*) FROM notes;").scalar()
        if count_notes == 0:
            connection.exec_driver_sql("DROP TABLE notes;")
            connection.exec_driver_sql("ALTER TABLE note RENAME TO notes;")
            tables.remove("note")
        else:
            cols_note = [c["name"] for c in inspector.get_columns("note")]
            cols_notes = [c["name"] for c in inspector.get_columns("notes")]
            common_cols = [c for c in cols_note if c in cols_notes]
            if common_cols:
                cols_str = ", ".join(common_cols)
                connection.exec_driver_sql(
                    f"INSERT OR IGNORE INTO notes ({cols_str}) SELECT {cols_str} FROM note;"
                )
            connection.exec_driver_sql("DROP TABLE note;")
            tables.remove("note")

    # 2. Agent column migrations (existing)
    if "agent" in tables:
        columns = [c["name"] for c in inspector.get_columns("agent")]
        if "care_stages_json" not in columns:
            connection.exec_driver_sql("ALTER TABLE agent ADD COLUMN care_stages_json TEXT NOT NULL DEFAULT '[]'")
        if "target_audience_json" not in columns:
            connection.exec_driver_sql("ALTER TABLE agent ADD COLUMN target_audience_json TEXT NOT NULL DEFAULT '[]'")
        if "forbidden_json" not in columns:
            connection.exec_driver_sql("ALTER TABLE agent ADD COLUMN forbidden_json TEXT NOT NULL DEFAULT '[]'")

    # 3. Milestone 2: Profile columns (short_name, avatar_url)
    if "profiles" in tables:
        profile_cols = [c["name"] for c in inspector.get_columns("profiles")]
        if "short_name" not in profile_cols:
            connection.exec_driver_sql("ALTER TABLE profiles ADD COLUMN short_name VARCHAR(64)")
        if "avatar_url" not in profile_cols:
            connection.exec_driver_sql("ALTER TABLE profiles ADD COLUMN avatar_url VARCHAR(512)")

    # 4. Milestone 2: ProfileAccess column (role)
    if "profile_access" in tables:
        pa_cols = [c["name"] for c in inspector.get_columns("profile_access")]
        if "role" not in pa_cols:
            connection.exec_driver_sql("ALTER TABLE profile_access ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'viewer'")

    # 5. Profile_id column migrations across notes, attachments, chat_threads
    for tbl in ("notes", "note", "attachments", "chat_threads"):
        if tbl in tables:
            cols = [c["name"] for c in inspector.get_columns(tbl)]
            if "profile_id" not in cols:
                connection.exec_driver_sql(f"ALTER TABLE {tbl} ADD COLUMN profile_id VARCHAR(36)")

    # 6. Milestone 2: Ensure table 'viewer_invites' is created with its unique index
    if "viewer_invites" not in tables:
        if "viewer_invites" in Base.metadata.tables:
            Base.metadata.tables["viewer_invites"].create(connection, checkfirst=True)
            tables.append("viewer_invites")
        else:
            connection.exec_driver_sql("""
                CREATE TABLE IF NOT EXISTS viewer_invites (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    invite_code VARCHAR(64) NOT NULL,
                    profile_id VARCHAR(36) NOT NULL,
                    invited_by VARCHAR(36),
                    invitee_name VARCHAR(255) NOT NULL,
                    role VARCHAR(32) NOT NULL DEFAULT 'viewer',
                    view_clinical BOOLEAN NOT NULL DEFAULT 1,
                    view_paperwork BOOLEAN NOT NULL DEFAULT 0,
                    expires_at DATETIME NOT NULL,
                    accepted_at DATETIME,
                    accepted_by VARCHAR(36),
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES profiles (id) ON DELETE CASCADE,
                    FOREIGN KEY(invited_by) REFERENCES users (id) ON DELETE CASCADE,
                    FOREIGN KEY(accepted_by) REFERENCES users (id) ON DELETE SET NULL
                );
            """)
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_viewer_invites_invite_code ON viewer_invites (invite_code);"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_viewer_invites_profile_id ON viewer_invites (profile_id);"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_viewer_invites_invited_by ON viewer_invites (invited_by);"
            )
            tables.append("viewer_invites")

    # 7. Milestone 3: Attachments schema evolution (storage_key, sha256_hash, indices & backfill)
    if "attachments" in tables:
        # Determine existing columns using dialect-specific pragma or inspector
        if connection.dialect.name == "sqlite":
            table_info = connection.exec_driver_sql("PRAGMA table_info(attachments);").fetchall()
            attachment_cols = [row[1] for row in table_info]  # row[1] is column name
        else:
            attachment_cols = [c["name"] for c in inspector.get_columns("attachments")]

        # 7a. Add missing storage_key column
        if "storage_key" not in attachment_cols:
            connection.exec_driver_sql("ALTER TABLE attachments ADD COLUMN storage_key VARCHAR(512);")
            attachment_cols.append("storage_key")
            logger.info("migration_added_column", table="attachments", column="storage_key")

        # 7b. Add missing sha256_hash column
        if "sha256_hash" not in attachment_cols:
            connection.exec_driver_sql("ALTER TABLE attachments ADD COLUMN sha256_hash VARCHAR(64);")
            attachment_cols.append("sha256_hash")
            logger.info("migration_added_column", table="attachments", column="sha256_hash")

        # 7c. Ensure missing filename column is added if legacy table only had file_path / filepath
        if "filename" not in attachment_cols:
            connection.exec_driver_sql("ALTER TABLE attachments ADD COLUMN filename VARCHAR(255);")
            logger.info("migration_added_column", table="attachments", column="filename")
            if "original_name" in attachment_cols:
                connection.exec_driver_sql(
                    "UPDATE attachments SET filename = original_name WHERE filename IS NULL AND original_name IS NOT NULL AND original_name != '';"
                )
            if "file_path" in attachment_cols:
                connection.exec_driver_sql(
                    "UPDATE attachments SET filename = file_path WHERE filename IS NULL AND file_path IS NOT NULL AND file_path != '';"
                )
            elif "filepath" in attachment_cols:
                connection.exec_driver_sql(
                    "UPDATE attachments SET filename = filepath WHERE filename IS NULL AND filepath IS NOT NULL AND filepath != '';"
                )
            connection.exec_driver_sql(
                "UPDATE attachments SET filename = 'unnamed_attachment' WHERE filename IS NULL OR filename = '';"
            )
            attachment_cols.append("filename")

        # 7d. Ensure indices exist for query performance and deduplication lookups
        existing_indices = {
            idx["name"] for idx in inspector.get_indexes("attachments") if idx.get("name")
        }
        if "ix_attachments_storage_key" not in existing_indices:
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_attachments_storage_key ON attachments (storage_key);"
            )
        if "ix_attachments_sha256_hash" not in existing_indices:
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_attachments_sha256_hash ON attachments (sha256_hash);"
            )

        # 7e. Backfill legacy records where storage_key is NULL
        # Direct backfill from legacy file_path or filepath column if present
        if "file_path" in attachment_cols:
            connection.exec_driver_sql("""
                UPDATE attachments
                SET storage_key = file_path
                WHERE storage_key IS NULL AND file_path IS NOT NULL AND file_path != '';
            """)
        if "filepath" in attachment_cols:
            connection.exec_driver_sql("""
                UPDATE attachments
                SET storage_key = filepath
                WHERE storage_key IS NULL AND filepath IS NOT NULL AND filepath != '';
            """)

        # Fallback scoping backfill if storage_key is still NULL and columns exist
        has_user = "user_id" in attachment_cols
        has_prof = "profile_id" in attachment_cols
        has_name = "filename" in attachment_cols

        if has_name:
            if has_user and has_prof:
                connection.exec_driver_sql("""
                    UPDATE attachments
                    SET storage_key = user_id || '/' || profile_id || '/' || filename
                    WHERE storage_key IS NULL AND user_id IS NOT NULL AND user_id != '' AND profile_id IS NOT NULL AND profile_id != '';
                """)
            if has_user:
                connection.exec_driver_sql("""
                    UPDATE attachments
                    SET storage_key = user_id || '/' || filename
                    WHERE storage_key IS NULL AND user_id IS NOT NULL AND user_id != '';
                """)
            if has_prof:
                connection.exec_driver_sql("""
                    UPDATE attachments
                    SET storage_key = profile_id || '/' || filename
                    WHERE storage_key IS NULL AND profile_id IS NOT NULL AND profile_id != '';
                """)
            connection.exec_driver_sql("""
                UPDATE attachments
                SET storage_key = filename
                WHERE storage_key IS NULL;
            """)


async def init_db(engine: Optional[AsyncEngine] = None) -> None:
    """Initializes database tables via Base.metadata.create_all and automated migrations."""
    import carefold.db.models  # noqa: F401
    target_engine = engine or get_engine()
    _ensure_sqlite_dir(str(target_engine.url))

    async with target_engine.begin() as conn:
        await conn.run_sync(_run_schema_migrations)
        await conn.run_sync(Base.metadata.create_all)

    logger.info(
        "database_initialized",
        dialect=target_engine.dialect.name,
        url=sanitize_db_url(target_engine.url),
    )


async def close_db() -> None:
    """Closes and disposes of the global database engine."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("database_connection_closed")
        _engine = None
        _session_factory = None
