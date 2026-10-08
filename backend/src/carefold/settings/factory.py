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

"""Factory and lifecycle management for hexagonal SettingsPort adapters."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from carefold.settings.adapters.sql_adapter import SqlSettingsAdapter
from carefold.settings.ports import SettingsPort

logger = logging.getLogger(__name__)

_CACHED_SETTINGS_PORT: Optional[SettingsPort] = None


def create_settings_port(
    backend_name: Optional[str] = None,
    session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
) -> SettingsPort:
    """Instantiates a SettingsPort adapter.

    Args:
        backend_name: Optional backend name ('sql', 'sqlite', 'postgres').
        session_factory: Optional SQLAlchemy sessionmaker for SQL adapter.

    Returns:
        Instance implementing SettingsPort.
    """
    backend = (backend_name or "sql").lower().strip()
    if backend in ("sql", "sqlite", "postgres", "default"):
        return SqlSettingsAdapter(session_factory=session_factory)
    raise ValueError(f"Unsupported settings backend: '{backend}'. Supported: 'sql'.")


def get_settings_port() -> SettingsPort:
    """Returns the singleton SettingsPort instance, instantiating it on first call."""
    global _CACHED_SETTINGS_PORT
    if _CACHED_SETTINGS_PORT is None:
        _CACHED_SETTINGS_PORT = create_settings_port()
    return _CACHED_SETTINGS_PORT


def set_settings_port(port: SettingsPort) -> None:
    """Overrides the global SettingsPort singleton."""
    global _CACHED_SETTINGS_PORT
    _CACHED_SETTINGS_PORT = port


def reset_settings_port() -> None:
    """Resets the global SettingsPort singleton reference to None."""
    global _CACHED_SETTINGS_PORT
    _CACHED_SETTINGS_PORT = None


def reset_settings_ports() -> None:
    """Alias for reset_settings_port for plural parity."""
    reset_settings_port()
