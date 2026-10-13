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

"""Declarative manifest schema for Carefold connectors."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, ValidationError
import yaml

from connectors.errors import ManifestValidationError


class DataFlowSpec(BaseModel):
    """Declares permitted outbound destinations and network egress parameters."""

    allowed_hosts: List[str] = Field(
        ...,
        description="List of fully-qualified hostnames permitted for egress",
    )
    allowed_schemes: List[Literal["https", "http"]] = Field(
        default_factory=lambda: ["https"],
        description="Permitted URL schemes (default: https)",
    )
    allowed_ports: List[int] = Field(
        default_factory=lambda: [443],
        description="Permitted destination ports (default: 443)",
    )
    egress_direction: Literal["egress_only", "bidirectional"] = Field(
        default="egress_only",
        description="Network traffic flow orientation",
    )
    pii_types_transferred: List[str] = Field(
        default_factory=list,
        description="Classes of PII transferred across external boundary",
    )


class AuthConfig(BaseModel):
    """Authentication and credential requirements for the connector."""

    type: Literal["oauth2", "api_key", "basic", "mtls", "none"] = Field(
        ...,
        description="Authentication mechanism type",
    )
    scopes: List[str] = Field(
        default_factory=list,
        description="Required OAuth2 or API scopes",
    )
    authorization_url: Optional[str] = Field(
        default=None,
        description="OAuth2 authorization endpoint URL",
    )
    token_url: Optional[str] = Field(
        default=None,
        description="OAuth2 token endpoint URL",
    )
    token_rotation: bool = Field(
        default=True,
        description="Whether refresh tokens rotate on exchange",
    )
    pkce: bool = Field(
        default=True,
        description="Whether PKCE (S256) is required for OAuth2 authorization code flows",
    )
    client_source: Literal["byo", "bundled"] = Field(
        default="byo",
        description="Source of OAuth client credentials ('byo' or 'bundled')",
    )
    rotating_refresh: bool = Field(
        default=True,
        description="Whether refresh tokens rotate on each token refresh exchange",
    )
    scope_details: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Human-readable metadata for requested OAuth scopes",
    )


class ToolDeclaration(BaseModel):
    """Metadata for an agent tool declared on the connector."""

    name: str = Field(..., description="Unique tool identifier")
    description: str = Field(..., description="Human-readable description of tool capability")
    risk_class: Literal["read_only", "clinical_assist", "admin"] = Field(
        default="read_only",
        description="Clinical and operational risk classification",
    )


class TrustConfig(BaseModel):
    """Trust and provenance verification metadata."""

    publisher: str = Field(..., min_length=1, description="Publishing organization or author")
    verified: bool = Field(default=False, description="Whether publisher signature has been verified")
    sandbox_level: Literal["strict", "standard"] = Field(
        default="strict",
        description="Sandbox isolation level",
    )
    trust_level: Literal["trusted", "untrusted"] = Field(
        default="trusted",
        description="Data taint and provenance trust level ('trusted' or 'untrusted')",
    )


class PolicyConfig(BaseModel):
    """Runtime limits and enforcement policies."""

    rate_limit_rpm: int = Field(default=60, description="Requests per minute rate limit")
    timeout_seconds: float = Field(default=30.0, description="Default request timeout in seconds")
    retry_max_attempts: int = Field(default=3, description="Maximum automated retry attempts")


class TermsConfig(BaseModel):
    """Legal, license, and privacy terms."""

    license: str = Field(default="Apache-2.0", description="Software license identifier")
    privacy_policy_url: Optional[str] = Field(default=None, description="URL of privacy policy")
    terms_of_service_url: Optional[str] = Field(default=None, description="URL of terms of service")
    ai_use_allowed: bool = Field(
        default=True,
        description="Whether external API terms allow local AI agent processing",
    )


class ConnectorManifest(BaseModel):
    """Declarative manifest schema for metadata-only connector.yaml."""

    id: str = Field(..., description="Unique connector identifier (e.g. 'epic-mychart')")
    version: str = Field(..., description="Semantic version string (e.g. '1.0.0')")
    name: str = Field(..., description="Human display name")
    description: str = Field(default="", description="Detailed description of connector functionality")
    categories: List[str] = Field(
        default_factory=list,
        description="Clinical or administrative categories provided by this connector",
    )
    entrypoint: Optional[str] = Field(
        default=None,
        description="Optional dotted entrypoint path for the connector implementation class",
    )
    data_flows: DataFlowSpec = Field(..., description="Outbound host and network flow declarations")
    auth: AuthConfig = Field(..., description="Authentication requirements and endpoints")
    tools: List[ToolDeclaration] = Field(default_factory=list, description="Exposed agent tools")
    trust: TrustConfig = Field(
        default_factory=lambda: TrustConfig(publisher="Spectrayan"),
        description="Provenance and trust verification",
    )
    policy: PolicyConfig = Field(default_factory=PolicyConfig, description="Rate limits and timeouts")
    terms: TermsConfig = Field(default_factory=TermsConfig, description="License and terms")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ConnectorManifest:
        """Parses and validates a ConnectorManifest from a Python dictionary."""
        try:
            return cls.model_validate(data)
        except ValidationError as err:
            raise ManifestValidationError(f"Invalid connector manifest: {err}") from err

    @classmethod
    def from_yaml(cls, path_or_content: Union[str, Path]) -> ConnectorManifest:
        """Loads and validates a ConnectorManifest from a YAML file path or YAML string."""
        content: str
        if isinstance(path_or_content, Path):
            content = path_or_content.read_text(encoding="utf-8")
        else:
            content = str(path_or_content)

        try:
            parsed = yaml.safe_load(content)
        except Exception as err:
            raise ManifestValidationError(f"YAML parsing error in manifest: {err}") from err

        if not isinstance(parsed, dict):
            raise ManifestValidationError("Manifest YAML must deserialize to a dictionary object.")

        return cls.from_dict(parsed)


__all__ = [
    "AuthConfig",
    "ConnectorManifest",
    "DataFlowSpec",
    "PolicyConfig",
    "TermsConfig",
    "ToolDeclaration",
    "TrustConfig",
]
