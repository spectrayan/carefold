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

"""Dynamic loader and registry for Carefold starter connectors (AU-50)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional

from connectors.base import Connector
from connectors.errors import ConnectorError
from connectors.manifest import ConnectorManifest
from connectors.starters.calendar import CalDavConnector, GoogleCalendarConnector
from connectors.starters.ehr_smart_v2 import (
    AthenahealthConnector,
    CmsBlueButtonConnector,
    OracleHealthConnector,
)
from connectors.starters.epic_smart import EpicSmartConnector
from connectors.starters.wearables_v2 import (
    GoogleHealthConnector,
    MicrosoftGraphCalendarConnector,
    OuraConnector,
)
from connectors.starters.withings import WithingsConnector
from connectors.starters.zocdoc import ZocdocConnector

_STARTER_MANIFESTS_DIR = Path(__file__).resolve().parent / "starters" / "manifests"

_STARTER_FACTORIES: Dict[str, Callable[[ConnectorManifest], Connector]] = {
    "withings": lambda manifest: WithingsConnector(manifest=manifest),
    "google-calendar": lambda manifest: GoogleCalendarConnector(manifest=manifest),
    "caldav": lambda manifest: CalDavConnector(manifest=manifest),
    "epic-smart": lambda manifest: EpicSmartConnector(manifest=manifest),
    "zocdoc": lambda manifest: ZocdocConnector(manifest=manifest),
    "oracle-health": lambda manifest: OracleHealthConnector(manifest=manifest),
    "athenahealth": lambda manifest: AthenahealthConnector(manifest=manifest),
    "cms-blue-button": lambda manifest: CmsBlueButtonConnector(manifest=manifest),
    "oura": lambda manifest: OuraConnector(manifest=manifest),
    "google-health": lambda manifest: GoogleHealthConnector(manifest=manifest),
    "microsoft-graph": lambda manifest: MicrosoftGraphCalendarConnector(manifest=manifest),
}

_STARTER_MANIFEST_FILES = (
    "withings.yaml",
    "google_calendar.yaml",
    "caldav.yaml",
    "epic_smart.yaml",
)

_V1_STARTER_IDS = frozenset({"withings", "google-calendar", "caldav", "epic-smart"})


class ConnectorRegistry:
    """Registry that discovers, validates, and instantiates Carefold starter connectors."""

    def __init__(self, manifests_dir: Optional[Path] = None) -> None:
        self._manifests_dir = manifests_dir or _STARTER_MANIFESTS_DIR
        self._manifests: Dict[str, ConnectorManifest] = {}
        self._factories: Dict[str, Callable[[ConnectorManifest], Connector]] = dict(
            _STARTER_FACTORIES
        )
        self._discover_builtin_manifests()

    def _discover_builtin_manifests(self) -> None:
        """Loads and validates all starter YAML manifests from disk."""
        for filename in _STARTER_MANIFEST_FILES:
            manifest_path = self._manifests_dir / filename
            if manifest_path.is_file():
                manifest = ConnectorManifest.from_yaml(manifest_path)
                self._manifests[manifest.id] = manifest

        if self._manifests_dir.is_dir():
            for yaml_path in sorted(self._manifests_dir.glob("*.yaml")):
                manifest = ConnectorManifest.from_yaml(yaml_path)
                if manifest.id not in self._manifests:
                    self._manifests[manifest.id] = manifest

    def register(
        self,
        manifest: ConnectorManifest,
        factory: Callable[[ConnectorManifest], Connector],
    ) -> None:
        """Registers a connector manifest and its instantiation factory."""
        self._manifests[manifest.id] = manifest
        self._factories[manifest.id] = factory

    def list_manifests(
        self,
        include_mcp: bool = False,
        include_v2: bool = False,
    ) -> List[ConnectorManifest]:
        """Returns registered connector manifests in deterministic order."""
        items = list(self._manifests.values())
        if not include_mcp:
            items = [m for m in items if getattr(m, "kind", "rest") != "mcp"]
        if not include_v2 and self._manifests_dir == _STARTER_MANIFESTS_DIR:
            items = [
                m
                for m in items
                if m.id in _V1_STARTER_IDS
                or (include_mcp and getattr(m, "kind", "rest") == "mcp")
                or m.id not in _STARTER_FACTORIES
            ]
        return items

    def get_manifest(self, connector_id: str) -> ConnectorManifest:
        """Returns the validated ConnectorManifest for `connector_id`."""
        if connector_id not in self._manifests:
            raise ConnectorError(f"Unknown connector id '{connector_id}'.")
        return self._manifests[connector_id]

    def load(self, connector_id: str) -> Connector:
        """Instantiates and returns the Connector implementation for `connector_id`."""
        manifest = self.get_manifest(connector_id)
        factory = self._factories.get(connector_id)
        if factory is None:
            raise ConnectorError(f"No connector implementation registered for '{connector_id}'.")
        return factory(manifest)


_DEFAULT_REGISTRY: Optional[ConnectorRegistry] = None


def get_connector_registry() -> ConnectorRegistry:
    """Returns the singleton starter ConnectorRegistry."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = ConnectorRegistry()
    return _DEFAULT_REGISTRY


def list_starter_manifests() -> List[ConnectorManifest]:
    """Returns all built-in starter connector manifests."""
    return get_connector_registry().list_manifests()


def load_connector(connector_id: str) -> Connector:
    """Loads and instantiates a starter connector by its manifest ID."""
    return get_connector_registry().load(connector_id)


__all__ = [
    "ConnectorRegistry",
    "get_connector_registry",
    "list_starter_manifests",
    "load_connector",
]
