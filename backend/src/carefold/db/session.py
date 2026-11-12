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

"""Database session and dual-chain Alembic migration runner delegating core pooling to yarvelle_core."""

from __future__ import annotations

import asyncio
import contextlib
try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]
import os
from pathlib import Path
from typing import AsyncIterator, Optional

import alembic.command
import alembic.script
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Connection, URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from yarvelle_core.db.base import Base
import yarvelle_core.db.session as _yc_session
from yarvelle_core.db.session import (
    _run_schema_migrations,
    close_db,
    normalize_database_url,
    reset_engine,
    sanitize_db_url,
)

from carefold.config import settings
from carefold.constants.paths import ENV_DATABASE_URL, ENV_DATABASE_URL_FALLBACK
from carefold.logging import get_logger

logger = get_logger("carefold.db")

_init_lock: Optional[asyncio.Lock] = None
_init_lock_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_init_lock() -> asyncio.Lock:
    global _init_lock, _init_lock_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _init_lock is None or (_init_lock_loop is not None and _init_lock_loop is not loop):
        _init_lock = asyncio.Lock()
        _init_lock_loop = loop
    return _init_lock


def resolve_database_url(url: Optional[str] = None) -> str:
    """Resolves the database URL honoring CAREFOLD_DATABASE_URL, YARVELLE_DATABASE_URL, and settings."""
    if url is not None and url.strip():
        return normalize_database_url(url)
    for env_key in (ENV_DATABASE_URL, "YARVELLE_DATABASE_URL", ENV_DATABASE_URL_FALLBACK):
        env_val = os.getenv(env_key)
        if env_val and env_val.strip():
            return normalize_database_url(env_val)
    return normalize_database_url(settings.get_database_url())


_yc_session.resolve_database_url = resolve_database_url


def create_db_engine(url: Optional[str] = None) -> AsyncEngine:
    return _yc_session.create_db_engine(resolve_database_url(url))


def get_engine(url: Optional[str] = None) -> AsyncEngine:
    return _yc_session.get_engine(resolve_database_url(url))


def get_session_factory(engine: Optional[AsyncEngine] = None) -> async_sessionmaker[AsyncSession]:
    return _yc_session.get_session_factory(engine if engine is not None else get_engine())


get_db = _yc_session.get_db


def get_alembic_config(connection: Optional[Connection] = None) -> Config:
    """Constructs Alembic Config pointing to yarvelle_core's core migration chain."""
    import yarvelle_core.db

    backend_dir = Path(__file__).resolve().parents[3]
    for candidate in (backend_dir / "alembic.ini", Path.cwd() / "alembic.ini", Path.cwd() / "backend" / "alembic.ini"):
        if candidate.is_file():
            cfg = Config(str(candidate))
            break
    else:
        cfg = Config()

    migrations_dir = Path(yarvelle_core.db.__file__).resolve().parent / "migrations"
    cfg.set_main_option("script_location", str(migrations_dir))
    if cfg.get_main_option("sqlalchemy.url") == "sqlite:///carefold.db":
        cfg.set_main_option("sqlalchemy.url", "")
    if connection is not None:
        cfg.attributes["connection"] = connection
    cfg.attributes["configure_logger"] = False
    return cfg


def is_core_revision_satisfied(required_revision: str, active_revisions: set[str]) -> bool:
    if required_revision in active_revisions:
        return True
    if not active_revisions:
        return False
    try:
        script = alembic.script.ScriptDirectory.from_config(get_alembic_config())
        satisfied: set[str] = set()
        for rev in active_revisions:
            try:
                for step in script.iterate_revisions(rev, "base"):
                    satisfied.add(step.revision)
            except Exception:
                continue
        return required_revision in satisfied
    except Exception:
        return False


def get_pack_alembic_config(
    migrations_dir: Path | str,
    version_table: str = "alembic_version_health",
    connection: Optional[Connection] = None,
) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir))
    cfg.set_main_option("version_table", version_table)
    if connection is not None:
        cfg.attributes["connection"] = connection
    cfg.attributes["version_table"] = version_table
    cfg.attributes["configure_logger"] = False
    return cfg


def run_pack_migrations(
    connection: Connection,
    migrations_dir: Path | str,
    version_table: str = "alembic_version_health",
    target: str = "head",
    depends_on_core: Optional[str] = "0013_turn_tasks",
) -> None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if depends_on_core:
        if "alembic_version" not in tables:
            raise RuntimeError(
                f"Cannot run pack migrations ({version_table}): core migration table 'alembic_version' does not exist."
            )
        core_revs = {
            r[0] for r in connection.exec_driver_sql("SELECT version_num FROM alembic_version;").fetchall() if r and r[0]
        }
        if not is_core_revision_satisfied(depends_on_core, core_revs):
            raise RuntimeError(
                f"Pack migration ({version_table}) requires core revision '{depends_on_core}', "
                f"but found core revisions: {sorted(core_revs)}."
            )

    cfg = get_pack_alembic_config(migrations_dir, version_table, connection)
    script = alembic.script.ScriptDirectory.from_config(cfg)
    heads = set(script.get_heads())
    if version_table in tables:
        current_revs = {
            r[0] for r in connection.exec_driver_sql(f"SELECT version_num FROM {version_table};").fetchall() if r and r[0]
        }
        if heads and heads.issubset(current_revs):
            return
    alembic.command.upgrade(cfg, target)


def resolve_health_migrations_dir() -> Path:
    return Path(__file__).resolve().parent / "health_migrations"


def _ensure_approvals_schema(connection: Connection) -> None:
    inspector = inspect(connection)
    if "approvals" not in inspector.get_table_names():
        return
    if "agent_id" not in {c["name"] for c in inspector.get_columns("approvals")}:
        connection.exec_driver_sql("ALTER TABLE approvals ADD COLUMN agent_id VARCHAR(64);")
    if "ix_approvals_agent_id" not in {i["name"] for i in inspector.get_indexes("approvals") if i.get("name")}:
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_approvals_agent_id ON approvals (agent_id);")


def run_alembic_migrations(connection: Connection) -> None:
    _yc_session.run_alembic_migrations(connection)
    _ensure_approvals_schema(connection)


def run_all_migrations(connection: Connection, enabled_packs: Optional[list[str]] = None) -> None:
    run_alembic_migrations(connection)
    for pack_id in (enabled_packs or ["health"]):
        if pack_id == "health":
            pack_dir = resolve_health_migrations_dir()
            if pack_dir.is_dir():
                run_pack_migrations(
                    connection=connection,
                    migrations_dir=pack_dir,
                    version_table="alembic_version_health",
                    depends_on_core="0013_turn_tasks",
                )


def _sqlite_db_file(engine: AsyncEngine) -> Optional[Path]:
    url: URL = engine.url
    if "sqlite" in getattr(url, "drivername", "") and url.database and url.database != ":memory:":
        p = Path(url.database)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p.resolve()
    return None


@contextlib.asynccontextmanager
async def _file_lock(db_path: Optional[Path]):
    if db_path is None or fcntl is None:
        yield
        return
    lock_path = Path(f"{db_path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        yield
        return
    try:
        await asyncio.to_thread(fcntl.flock, fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(fcntl.flock, fd, fcntl.LOCK_UN)
    finally:
        with contextlib.suppress(Exception):
            os.close(fd)


async def init_db(engine: Optional[AsyncEngine] = None) -> None:
    import carefold.db.models  # noqa: F401

    target_engine = engine or get_engine()
    db_path = _sqlite_db_file(target_engine)
    async with _get_init_lock():
        async with _file_lock(db_path):
            async with target_engine.begin() as conn:
                await conn.run_sync(run_all_migrations)
                await conn.run_sync(Base.metadata.create_all)
    logger.info("database_initialized", dialect=target_engine.dialect.name, url=sanitize_db_url(target_engine.url))
