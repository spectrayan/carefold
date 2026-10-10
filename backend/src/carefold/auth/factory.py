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

"""Factory and lifecycle management for hexagonal AuthPort adapters."""

from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from carefold.auth.adapters.disabled_adapter import DisabledAuthAdapter
from carefold.auth.adapters.oidc_adapter import OidcAuthAdapter
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.ports import AuthPort

logger = logging.getLogger(__name__)

ENV_AUTH_PROVIDER = "CAREFOLD_AUTH_PROVIDER"
DEFAULT_AUTH_PROVIDER = "local"

_CACHED_AUTH_PORT: Optional[AuthPort] = None


def create_auth_port(
    provider_name: Optional[str] = None,
    session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
) -> AuthPort:
    """Instantiates an AuthPort adapter based on provider name.

    Args:
        provider_name: Optional provider ('disabled', 'local', 'oidc').
                       Defaults to CAREFOLD_AUTH_PROVIDER or 'disabled'.
        session_factory: Optional SQLAlchemy sessionmaker for SQL-backed adapters.

    Returns:
        Instance implementing AuthPort.

    Raises:
        ValueError: If provider is unrecognized.
    """
    raw_provider = provider_name
    if raw_provider is None:
        raw_provider = os.getenv(ENV_AUTH_PROVIDER)
    if raw_provider is None:
        try:
            from carefold.config import settings
            raw_provider = getattr(settings, "auth_provider", DEFAULT_AUTH_PROVIDER)
        except Exception:
            raw_provider = DEFAULT_AUTH_PROVIDER

    provider = (raw_provider or DEFAULT_AUTH_PROVIDER).lower().strip()

    if provider in ("disabled", "bypass", "none"):
        return DisabledAuthAdapter()
    elif provider in ("local", "sql", "sqlite", "postgres"):
        return SqlAuthAdapter(session_factory=session_factory)
    elif provider in ("oidc", "sso"):
        sql_ad = SqlAuthAdapter(session_factory=session_factory)
        return OidcAuthAdapter(sql_adapter=sql_ad)
    else:
        raise ValueError(
            f"Unsupported auth provider: '{provider}'. "
            "Supported providers: 'disabled', 'local', 'oidc'."
        )


def get_auth_port() -> AuthPort:
    """Returns the singleton AuthPort instance, instantiating it on first call."""
    global _CACHED_AUTH_PORT
    if _CACHED_AUTH_PORT is None:
        _CACHED_AUTH_PORT = create_auth_port()
    return _CACHED_AUTH_PORT


def set_auth_port(port: AuthPort) -> None:
    """Overrides the global AuthPort singleton (useful for testing or dynamic switching)."""
    global _CACHED_AUTH_PORT
    _CACHED_AUTH_PORT = port


def reset_auth_port() -> None:
    """Resets the global AuthPort singleton reference to None."""
    global _CACHED_AUTH_PORT
    _CACHED_AUTH_PORT = None


def reset_auth_ports() -> None:
    """Alias for reset_auth_port to conform with memory factory conventions."""
    reset_auth_port()
