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

"""Exception hierarchy for Carefold connectors framework."""

from __future__ import annotations


class ConnectorError(Exception):
    """Base exception for all connector-related errors."""


class EgressBlockedError(PermissionError, ConnectorError):
    """Raised when an outbound HTTP request targets a host, scheme, or port prohibited by policy."""

    def __init__(self, message: str, host: str | None = None) -> None:
        super().__init__(message)
        self.host = host


class AuthExpiredError(ConnectorError):
    """Raised when connector authentication credentials have expired or require reauthorization."""


class ManifestValidationError(ConnectorError, ValueError):
    """Raised when a connector manifest fails schema validation."""


__all__ = [
    "AuthExpiredError",
    "ConnectorError",
    "EgressBlockedError",
    "ManifestValidationError",
]
