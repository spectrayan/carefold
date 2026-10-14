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

"""Carefold Connectors Framework."""

from connectors.base import (
    Connector,
    NormalisedRecord,
    Page,
    StreamSpec,
    ToolContext,
    ToolSpec,
)
from connectors.errors import (
    AuthExpiredError,
    ConnectorError,
    EgressBlockedError,
    ManifestValidationError,
)
from connectors.http import ScopedHttp
from connectors.loader import (
    ConnectorRegistry,
    get_connector_registry,
    list_starter_manifests,
    load_connector,
)
from connectors.manifest import (
    AuthConfig,
    ConnectorManifest,
    DataFlowSpec,
    PolicyConfig,
    TermsConfig,
    ToolDeclaration,
    TrustConfig,
)

__all__ = [
    "AuthConfig",
    "AuthExpiredError",
    "Connector",
    "ConnectorError",
    "ConnectorManifest",
    "ConnectorRegistry",
    "DataFlowSpec",
    "EgressBlockedError",
    "ManifestValidationError",
    "NormalisedRecord",
    "Page",
    "PolicyConfig",
    "ScopedHttp",
    "StreamSpec",
    "TermsConfig",
    "ToolContext",
    "ToolDeclaration",
    "ToolSpec",
    "TrustConfig",
    "get_connector_registry",
    "list_starter_manifests",
    "load_connector",
]
