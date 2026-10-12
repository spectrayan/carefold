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

"""Manifest validation tests for declarative connector specifications."""

from __future__ import annotations

import pytest

from connectors.errors import ManifestValidationError
from connectors.manifest import (
    AuthConfig,
    ConnectorManifest,
    DataFlowSpec,
    TrustConfig,
)

SAMPLE_VALID_YAML = """
id: quest-diagnostics
version: 1.2.0
name: Quest Diagnostics Lab Connector
description: Ingests clinical laboratory results and panels.
data_flows:
  allowed_hosts:
    - api.questdiagnostics.com
    - fhir.questdiagnostics.com
  allowed_schemes:
    - https
  allowed_ports:
    - 443
  egress_direction: egress_only
  pii_types_transferred:
    - lab_results
    - patient_name
auth:
  type: oauth2
  scopes:
    - patient/Observation.read
  authorization_url: https://auth.questdiagnostics.com/oauth/authorize
  token_url: https://auth.questdiagnostics.com/oauth/token
  token_rotation: true
tools:
  - name: fetch_lab_reports
    description: Retrieves diagnostic lab report panels.
    risk_class: read_only
trust:
  publisher: Quest Diagnostics Inc.
  verified: true
  sandbox_level: strict
policy:
  rate_limit_rpm: 60
  timeout_seconds: 30.0
  retry_max_attempts: 3
terms:
  license: Apache-2.0
  privacy_policy_url: https://www.questdiagnostics.com/privacy
"""


def test_valid_manifest_yaml_parsing():
    """Verify ConnectorManifest loads and validates cleanly from YAML content."""
    manifest = ConnectorManifest.from_yaml(SAMPLE_VALID_YAML)
    assert manifest.id == "quest-diagnostics"
    assert manifest.version == "1.2.0"
    assert manifest.data_flows.allowed_hosts == [
        "api.questdiagnostics.com",
        "fhir.questdiagnostics.com",
    ]
    assert manifest.auth.type == "oauth2"
    assert manifest.auth.token_rotation is True
    assert len(manifest.tools) == 1
    assert manifest.tools[0].name == "fetch_lab_reports"
    assert manifest.trust.verified is True


def test_valid_manifest_from_dict():
    """Verify ConnectorManifest loads cleanly from a valid dictionary."""
    data = {
        "id": "dexcom-cgm",
        "version": "2.0.0",
        "name": "Dexcom G7 Continuous Glucose Monitor",
        "description": "Streaming glucose telemetry data connector.",
        "data_flows": {
            "allowed_hosts": ["api.dexcom.com"],
            "allowed_schemes": ["https"],
            "allowed_ports": [443],
        },
        "auth": {
            "type": "oauth2",
            "scopes": ["offline_access"],
        },
        "trust": {
            "publisher": "Dexcom Inc.",
            "verified": True,
        },
    }
    manifest = ConnectorManifest.from_dict(data)
    assert manifest.id == "dexcom-cgm"
    assert manifest.data_flows.allowed_hosts == ["api.dexcom.com"]
    assert manifest.policy.rate_limit_rpm == 60  # Default


def test_missing_required_fields_raises_manifest_error():
    """Verify missing required fields raise ManifestValidationError."""
    incomplete_data = {
        "id": "incomplete-connector",
        # Missing version, data_flows, auth, trust
    }
    with pytest.raises(ManifestValidationError) as exc:
        ConnectorManifest.from_dict(incomplete_data)
    assert "Invalid connector manifest" in str(exc.value)


def test_invalid_auth_type_raises_manifest_error():
    """Verify unsupported auth type fails validation."""
    invalid_auth_yaml = """
id: invalid-auth
version: 1.0.0
name: Invalid Auth
description: Test
data_flows:
  allowed_hosts: [api.test.com]
auth:
  type: magic_unsupported_auth
trust:
  publisher: Test
"""
    with pytest.raises(ManifestValidationError) as exc:
        ConnectorManifest.from_yaml(invalid_auth_yaml)
    assert "Invalid connector manifest" in str(exc.value)


def test_malformed_yaml_syntax_raises_manifest_error():
    """Verify malformed YAML string raises ManifestValidationError."""
    bad_yaml = "id: [broken yaml: {unbalanced"
    with pytest.raises(ManifestValidationError):
        ConnectorManifest.from_yaml(bad_yaml)
