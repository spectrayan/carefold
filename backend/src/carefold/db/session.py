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

from sqlalchemy import event
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


async def init_db(engine: Optional[AsyncEngine] = None) -> None:
    """Initializes database tables via Base.metadata.create_all."""
    target_engine = engine or get_engine()
    _ensure_sqlite_dir(str(target_engine.url))

    async with target_engine.begin() as conn:
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
