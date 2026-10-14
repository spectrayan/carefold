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
