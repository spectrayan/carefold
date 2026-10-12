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
