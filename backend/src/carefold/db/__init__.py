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

"""Database layer re-exporting yarvelle_core primitives and Carefold dual-migration session."""

from __future__ import annotations

from typing import Any
from yarvelle_core.db.base import Base  # noqa: F401
import yarvelle_core.db as _target_module
from carefold.db.models import *  # noqa: F401, F403
from carefold.db.session import (  # noqa: F401
    close_db, create_db_engine, get_alembic_config, get_db, get_engine, get_pack_alembic_config,
    get_session_factory, init_db, is_core_revision_satisfied, normalize_database_url, reset_engine,
    resolve_database_url, resolve_health_migrations_dir, run_alembic_migrations, run_all_migrations,
    run_pack_migrations, sanitize_db_url,
)


def __getattr__(name: str) -> Any:
    return getattr(_target_module, name)
