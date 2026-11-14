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

"""Filesystem and environment constants re-exported from yarvelle_core with Carefold defaults."""

from __future__ import annotations

from yarvelle_core.constants.paths import *  # noqa: F401, F403

DEFAULT_HOME_DIR: str = ".carefold"
SQL_DB_FILENAME: str = "carefold.db"
DEFAULT_SQL_DB_PATH: str = SQL_DB_FILENAME
DEFAULT_SQL_DB_FILE: str = SQL_DB_FILENAME
CAREFOLD_YAML_FILENAME: str = "carefold.yaml"
CAREFOLD_YAML_FILE: str = CAREFOLD_YAML_FILENAME
CAREFOLD_YAML_MIGRATED_FILENAME: str = "carefold.yaml.migrated"
CAREFOLD_YAML_MIGRATED_FILE: str = CAREFOLD_YAML_MIGRATED_FILENAME
CAREFOLD_HOME: str = "CAREFOLD_HOME"
CAREFOLD_DATA_DIR: str = "CAREFOLD_DATA_DIR"
ENV_DATA_DIR: str = "CAREFOLD_DATA_DIR"
WEBVIEW_DIR: str = "webview"
DAEMON_MANIFEST_FILENAME: str = "daemon.json"
DAEMON_LOCK_FILENAME: str = "daemon.lock"
ENV_DATABASE_URL: str = "CAREFOLD_DATABASE_URL"

import yarvelle_core.constants.paths as _yc_mod

def __getattr__(name: str):
    return getattr(_yc_mod, name)
