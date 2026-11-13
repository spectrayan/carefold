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

"""Automated 1:1 FastAPI <-> MCP tool parity registry and contract verifiers (#344).

Enforces at test/CI time that:
1. Every FastAPI route mounted on `carefold.main:app` either maps 1:1 to a
   declarative MCP tool wrapper in `ENDPOINT_MCP_PARITY_REGISTRY`, resolves via
   an explicit alias in `ALIAS_ROUTE_MAP`, or is explicitly justified in
   `TRANSPORT_ONLY_ENDPOINT_ALLOWLIST`.
2. Every REST endpoint and its corresponding MCP `ToolSpec` share identical
   input schemas (property names, required sets, types, enums, and defaults)
   modulo server-bound `RESERVED_TOOL_CONTEXT_PARAMS` and documented `context_remaps`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from fastapi.routing import APIRoute

from carefold.clinical.api_contracts import (
    ApiMcpOperationContract,
    _build_contract_for_spec,
    get_api_mcp_contracts_by_route,
    walk_fastapi_api_routes,
)
from carefold.engine.tool_registry import create_default_registry

FASTAPI_BUILTIN_DOC_PATHS: FrozenSet[str] = frozenset(
    {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
)

# Explicit, documented allowlist of transport-only HTTP routes that have no MCP tool twin (#344 AC 1).
TRANSPORT_ONLY_ENDPOINT_ALLOWLIST: Dict[Tuple[str, str], str] = {
    ("GET", "/health"): "Root container/orchestrator HTTP liveness probe alias.",
    ("GET", "/api/v1/health"): "Backend HTTP readiness/liveness probe.",
    ("GET", "/api/v1/i18n/locales"): "Browser Accept-Language UI locale negotiation endpoint.",
    ("GET", "/api/v1/i18n/catalog/{locale}"): "Static frontend translation bundle loader.",
    ("GET", "/api/v1/system/service-descriptors"): "Local desktop mDNS/port discovery descriptor endpoint.",
    ("GET", "/api/v1/auth/setup-status"): "Pre-login HTTP auth bootstrap probe.",
    ("GET", "/api/v1/auth/status"): "Frontend alias for pre-login HTTP auth bootstrap probe.",
    ("GET", "/api/v1/auth/providers"): "Login UI OAuth/OIDC/local identity provider discovery.",
    ("GET", "/api/v1/auth/me"): "Browser HTTP cookie/bearer session introspection.",
    ("POST", "/api/v1/auth/login"): "Interactive user password login issuing HTTP session/JWT credentials.",
    ("POST", "/api/v1/auth/logout"): "Browser HTTP session/cookie logout endpoint.",
    ("POST", "/api/v1/auth/register"): "Interactive local user account registration.",
    ("POST", "/api/v1/auth/change-password"): "Interactive user password rotation.",
    ("POST", "/api/v1/auth/forgot-password"): "Interactive password recovery token request.",
    ("POST", "/api/v1/auth/reset-password"): "Interactive password recovery token redemption.",
    ("GET", "/api/v1/admin/diagnostics"): "Host-level system administrator diagnostics endpoint (require_admin).",
    ("GET", "/api/v1/admin/settings"): "Host-level runtime configuration inspection (require_admin).",
    ("PUT", "/api/v1/admin/settings"): "Host-level runtime configuration update (require_admin).",
    ("GET", "/api/v1/admin/users"): "Host-level multi-user account directory listing (require_admin).",
    ("POST", "/api/v1/admin/users"): "Host-level user provisioning endpoint (require_admin).",
    ("PATCH", "/api/v1/admin/users/{user_id}"): "Host-level user role/status update (require_admin).",
    ("DELETE", "/api/v1/admin/users/{user_id}"): "Host-level user account deletion (require_admin).",
    ("POST", "/api/v1/admin/users/{user_id}/reset-password"): "Host-level administrator password reset (require_admin).",
    ("POST", "/api/v1/chat"): "Server-Sent Events (text/event-stream) interactive agent chat turn stream.",
    ("POST", "/api/v1/chat/resume"): "Server-Sent Events (text/event-stream) approval-resume chat stream.",
    ("POST", "/api/v1/v1/chat/resume"): "Legacy path alias for SSE approval-resume chat stream.",
    (
        "POST",
        "/api/v1/profiles/{profile_id}/connections/{connection_id}/oauth-callback",
    ): "Browser OAuth2 PKCE redirect callback completing external authorization code exchange.",
    (
        "POST",
        "/api/v1/profiles/{profile_id}/connections/{connection_id}/oauth/callback",
    ): "Legacy path alias for browser OAuth2 PKCE redirect callback.",
    ("POST", "/api/v1/attachments"): "Multipart form-data (UploadFile) binary stream upload endpoint.",
    ("POST", "/api/v1/attachments/upload"): "Legacy multipart form-data (UploadFile) upload alias.",
    ("GET", "/api/v1/attachments/{attachment_id}/download"): "Binary FileResponse attachment download stream.",
    ("GET", "/api/v1/attachments/{attachment_id}/content"): "Legacy binary FileResponse attachment download alias.",
    (
        "GET",
        "/api/v1/profiles/{profile_id}/reminders/feed.ics",
    ): "External calendar client WebCal (text/calendar) subscription feed.",
}

# Explicit alias routes mapping hidden/trailing-slash/secondary-mount routes to their canonical (method, path).
ALIAS_ROUTE_MAP: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("GET", "/api/v1/approvals/"): ("GET", "/api/v1/approvals"),
    ("GET", "/api/v1/profiles/{profile_id}/approvals"): ("GET", "/api/v1/approvals"),
    ("GET", "/api/v1/profiles/{profile_id}/approvals/"): ("GET", "/api/v1/approvals"),
    ("GET", "/api/v1/profiles/{profile_id}/approvals/{approval_id}"): (
        "GET",
        "/api/v1/approvals/{approval_id}",
    ),
    ("POST", "/api/v1/profiles/{profile_id}/approvals/{approval_id}/decide"): (
        "POST",
        "/api/v1/approvals/{approval_id}/decide",
    ),
    ("GET", "/api/v1/connectors"): ("GET", "/api/v1/connectors/catalog"),
    ("GET", "/api/v1/memory/"): ("GET", "/api/v1/memory"),
    ("DELETE", "/api/v1/memory/"): ("DELETE", "/api/v1/memory"),
    ("GET", "/api/v1/memory/recall"): ("GET", "/api/v1/memory"),
    ("GET", "/api/v1/memories"): ("GET", "/api/v1/memory"),
    ("DELETE", "/api/v1/memories"): ("DELETE", "/api/v1/memory"),
    ("GET", "/api/v1/memories/"): ("GET", "/api/v1/memory"),
    ("DELETE", "/api/v1/memories/"): ("DELETE", "/api/v1/memory"),
    ("GET", "/api/v1/memories/recall"): ("GET", "/api/v1/memory"),
    ("GET", "/api/v1/memories/status"): ("GET", "/api/v1/memory/status"),
    ("GET", "/api/v1/memories/{key}"): ("GET", "/api/v1/memory/{key}"),
    ("PUT", "/api/v1/memories/{key}"): ("PUT", "/api/v1/memory/{key}"),
    ("DELETE", "/api/v1/memories/{key}"): ("DELETE", "/api/v1/memory/{key}"),
    ("GET", "/api/v1/profiles/"): ("GET", "/api/v1/profiles"),
    ("POST", "/api/v1/profiles/"): ("POST", "/api/v1/profiles"),
    ("GET", "/api/v1/profiles/{profile_id}/search/"): (
        "GET",
        "/api/v1/profiles/{profile_id}/search",
    ),
    ("GET", "/api/v1/profiles/profiles/{profile_id}/search"): (
        "GET",
        "/api/v1/profiles/{profile_id}/search",
    ),
    ("GET", "/api/v1/profiles/profiles/{profile_id}/search/"): (
        "GET",
        "/api/v1/profiles/{profile_id}/search",
    ),
    ("GET", "/api/v1/{profile_id}/search"): (
        "GET",
        "/api/v1/profiles/{profile_id}/search",
    ),
    ("GET", "/api/v1/{profile_id}/search/"): (
        "GET",
        "/api/v1/profiles/{profile_id}/search",
    ),
    ("GET", "/api/v1/fhir/r4/Patient/{id}/$export"): (
        "POST",
        "/api/v1/fhir/r4/Patient/{id}/$export",
    ),
}


class ParityViolationError(AssertionError):
    """Raised when a Carefold FastAPI domain route lacks a 1:1 MCP tool wrapper."""


class SchemaParityViolationError(AssertionError):
    """Raised when a REST endpoint schema diverges from its MCP ToolSpec inputSchema."""


@dataclass(frozen=True)
class ParityVerificationReport:
    """Summary returned by `verify_fastapi_mcp_parity`."""

    total_inspected_routes: int
    canonical_domain_routes: int
    alias_routes: int
    transport_allowlisted_routes: int
    unversioned_mirror_routes: int


def get_endpoint_mcp_parity_registry() -> Dict[Tuple[str, str], ApiMcpOperationContract]:
    """Returns the canonical `(HTTP_METHOD, '/api/v1/...') -> ApiMcpOperationContract` registry."""
    return get_api_mcp_contracts_by_route()


def verify_fastapi_mcp_parity(
    app: Any = None,
    registry: Any = None,
) -> ParityVerificationReport:
    """Verifies every FastAPI route on `app` has a registered MCP tool or documented transport rationale."""
    if app is None:
        from carefold.main import app as default_app

        app = default_app
    if registry is None:
        registry = create_default_registry()

    parity_map = get_endpoint_mcp_parity_registry()

    # Validate allowlist rationales are non-empty
    for key, rationale in TRANSPORT_ONLY_ENDPOINT_ALLOWLIST.items():
        if not isinstance(rationale, str) or not rationale.strip():
            raise ParityViolationError(
                f"Transport allowlist entry {key} must provide a non-empty rationale."
            )
        if key in parity_map:
            raise ParityViolationError(
                f"Route {key} cannot appear in both ENDPOINT_MCP_PARITY_REGISTRY and TRANSPORT_ONLY_ENDPOINT_ALLOWLIST."
            )

    # Validate alias targets exist in canonical parity registry
    for alias_key, target_key in ALIAS_ROUTE_MAP.items():
        if target_key not in parity_map:
            raise ParityViolationError(
                f"Alias route {alias_key} references unknown canonical target {target_key}."
            )

    walked = walk_fastapi_api_routes(app.routes, prefix="", include_in_schema=True)
    discovered_keys: Set[Tuple[str, str]] = set()
    for route, full_path, _ in walked:
        if full_path in FASTAPI_BUILTIN_DOC_PATHS:
            continue
        for method in (route.methods or ()):
            if method in ("HEAD", "OPTIONS"):
                continue
            discovered_keys.add((method.upper(), full_path))

    unmapped: List[str] = []
    canonical_seen = 0
    alias_seen = 0
    allowlist_seen = 0
    unversioned_seen = 0

    for method, full_path in sorted(discovered_keys):
        key = (method, full_path)
        if key in parity_map:
            canonical_seen += 1
            continue
        if key in ALIAS_ROUTE_MAP:
            alias_seen += 1
            continue
        if key in TRANSPORT_ONLY_ENDPOINT_ALLOWLIST:
            allowlist_seen += 1
            continue
        if full_path.startswith("/api/") and not full_path.startswith("/api/v1/"):
            v1_mirror = (method, f"/api/v1{full_path[len('/api'):]}")
            if (
                v1_mirror in parity_map
                or v1_mirror in ALIAS_ROUTE_MAP
                or v1_mirror in TRANSPORT_ONLY_ENDPOINT_ALLOWLIST
            ):
                unversioned_seen += 1
                continue
        unmapped.append(f"{method} {full_path}")

    if unmapped:
        raise ParityViolationError(
            "Unmapped Carefold domain API route(s) missing a 1:1 declarative MCP tool wrapper "
            f"or TRANSPORT_ONLY_ENDPOINT_ALLOWLIST entry: {unmapped}"
        )

    missing_tools: List[str] = []
    for (method, path), contract in sorted(parity_map.items()):
        if (method, path) not in discovered_keys:
            missing_tools.append(
                f"{method} {path} -> '{contract.spec.tool_name}' (route missing on FastAPI app)"
            )
            continue
        tool_spec = registry.get(contract.spec.tool_name)
        if tool_spec is None:
            missing_tools.append(
                f"{method} {path} -> '{contract.spec.tool_name}' (not registered in ToolSpecRegistry)"
            )
        elif not callable(tool_spec.executor) and not callable(tool_spec.handler):
            missing_tools.append(
                f"{method} {path} -> '{contract.spec.tool_name}' (missing callable executor)"
            )

    if missing_tools:
        raise ParityViolationError(
            f"Parity registry references missing/unbound routes or MCP tools: {missing_tools}"
        )

    return ParityVerificationReport(
        total_inspected_routes=len(discovered_keys),
        canonical_domain_routes=canonical_seen,
        alias_routes=alias_seen,
        transport_allowlisted_routes=allowlist_seen,
        unversioned_mirror_routes=unversioned_seen,
    )


def _extract_comparable_property_signature(prop_schema: Dict[str, Any]) -> Dict[str, Any]:
    """Extracts canonical structural attributes of a JSON Schema property for drift comparison."""
    sig: Dict[str, Any] = {}
    if "type" in prop_schema:
        sig["type"] = prop_schema["type"]
    if "anyOf" in prop_schema:
        sig["anyOf"] = [
            _extract_comparable_property_signature(b)
            for b in prop_schema["anyOf"]
            if isinstance(b, dict)
        ]
    if "enum" in prop_schema:
        sig["enum"] = list(prop_schema["enum"])
    if "default" in prop_schema:
        sig["default"] = prop_schema["default"]
    if "minimum" in prop_schema:
        sig["minimum"] = prop_schema["minimum"]
    if "maximum" in prop_schema:
        sig["maximum"] = prop_schema["maximum"]
    return sig


def verify_rest_mcp_schema_parity(
    app: Any = None,
    registry: Any = None,
) -> List[str]:
    """Verifies every `(REST endpoint, MCP ToolSpec)` pair shares identical input schemas."""
    if app is None:
        from carefold.main import app as default_app

        app = default_app
    if registry is None:
        registry = create_default_registry()

    live_routes: Dict[Tuple[str, str], APIRoute] = {}
    for route, full_path, inc in walk_fastapi_api_routes(app.routes, prefix="", include_in_schema=True):
        if not full_path.startswith("/api/v1"):
            continue
        for method in (route.methods or ()):
            if method in ("HEAD", "OPTIONS"):
                continue
            key = (method.upper(), full_path)
            if key not in live_routes or inc:
                live_routes[key] = route

    parity_map = get_endpoint_mcp_parity_registry()
    divergences: List[str] = []
    verified_tools: List[str] = []

    for (method, path), cached_contract in sorted(parity_map.items()):
        live_contract = (
            _build_contract_for_spec(cached_contract.spec, live_routes)
            if (method, path) in live_routes
            else cached_contract
        )
        expected_schema = live_contract.input_schema
        tool_name = live_contract.spec.tool_name
        tool_spec = registry.get(tool_name)
        if tool_spec is None:
            divergences.append(f"{tool_name} ({method} {path}): missing from ToolSpecRegistry")
            continue

        actual_schema = dict(tool_spec.parameters or {})
        exp_props = dict(expected_schema.get("properties") or {})
        act_props = dict(actual_schema.get("properties") or {})
        if set(exp_props.keys()) != set(act_props.keys()):
            missing = sorted(set(exp_props.keys()) - set(act_props.keys()))
            extra = sorted(set(act_props.keys()) - set(exp_props.keys()))
            divergences.append(
                f"{tool_name} ({method} {path}): property mismatch (missing={missing}, extra={extra})"
            )
            continue

        exp_req = sorted(expected_schema.get("required") or [])
        act_req = sorted(actual_schema.get("required") or [])
        if exp_req != act_req:
            divergences.append(
                f"{tool_name} ({method} {path}): required mismatch (expected={exp_req}, actual={act_req})"
            )
            continue

        for prop_name in sorted(exp_props.keys()):
            exp_sig = _extract_comparable_property_signature(exp_props[prop_name])
            act_sig = _extract_comparable_property_signature(act_props[prop_name])
            if exp_sig != act_sig:
                divergences.append(
                    f"{tool_name}.{prop_name} ({method} {path}): schema mismatch "
                    f"(expected={exp_sig}, actual={act_sig})"
                )

        verified_tools.append(tool_name)

    if divergences:
        raise SchemaParityViolationError(
            "REST <-> MCP schema drift detected:\n  - " + "\n  - ".join(divergences)
        )

    return verified_tools


__all__ = [
    "ALIAS_ROUTE_MAP",
    "FASTAPI_BUILTIN_DOC_PATHS",
    "ParityVerificationReport",
    "ParityViolationError",
    "SchemaParityViolationError",
    "TRANSPORT_ONLY_ENDPOINT_ALLOWLIST",
    "get_endpoint_mcp_parity_registry",
    "verify_fastapi_mcp_parity",
    "verify_rest_mcp_schema_parity",
]
