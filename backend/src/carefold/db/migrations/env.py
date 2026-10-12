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

"""Alembic environment configuration for Carefold schema migrations."""

from logging.config import fileConfig
import os
from typing import Optional

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection, create_engine
from sqlalchemy.engine.url import make_url

from carefold.config import settings
from carefold.db.base import Base
import carefold.db.models  # noqa: F401
from carefold.db.session import resolve_database_url

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    try:
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    except Exception:
        pass

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata


def get_sync_url(raw_url: Optional[str] = None) -> str:
    """Translates async database URLs to sync equivalents for Alembic."""
    url_str = raw_url or resolve_database_url()
    parsed = make_url(url_str)
    driver = parsed.drivername
    if "+aiosqlite" in driver:
        driver = "sqlite"
    elif "+asyncpg" in driver:
        driver = "postgresql"
    elif driver.startswith("sqlite+"):
        driver = "sqlite"
    elif driver.startswith("postgresql+"):
        driver = "postgresql"
    return str(parsed.set(drivername=driver))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    if not url or "carefold.db" in url:
        url = get_sync_url()

    output_buffer = config.attributes.get("output_buffer", None)

    context.configure(
        url=url,
        output_buffer=output_buffer,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    connectable = config.attributes.get("connection", None)

    if connectable is not None:
        context.configure(
            connection=connectable,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()
    else:
        sync_url = get_sync_url()
        connectable = create_engine(sync_url, poolclass=pool.NullPool)

        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                compare_type=True,
                compare_server_default=True,
            )

            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
