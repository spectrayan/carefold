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

"""SMART on FHIR App Launch v2 Discovery, Scope Negotiation, Pagination & Persistent Sync (#286).

Implements:
- Dynamic SMART on FHIR v2 discovery via `{fhir_base_url}/.well-known/smart-configuration`
  with automatic fallback to `{fhir_base_url}/metadata` (`CapabilityStatement.rest[].security.extension`).
- Strict PKCE `S256` support verification and launch parameter validation (`aud`, `code_challenge_method=S256`).
- SMART App Launch v2 granular `.rs` clinical scopes alongside backward-compatible v1 `.read` scopes.
- Deterministic multi-page `Bundle.link[relation="next"]` traversal over `ScopedHttp` with host allowlist
  enforcement, anti-SSRF protection, loop detection, and configurable `max_pages` safety cap.
- Persistent sync routing into the `#282`/`#283` FHIR R4 repository (`upsert_fhir_resource_with_history`)
  populating `health_resources`, `health_resource_versions`, `health_resource_codings`, and
  `health_resource_references` with cross-portal deduplication.
- Redaction helpers ensuring OAuth tokens, refresh tokens, client secrets, and PKCE verifiers never leak to logs.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import urlencode, urljoin, urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.engine.tool_exec import UntrustedResult
from carefold.fhir.repository import upsert_fhir_resource_with_history
from carefold.models.health import HealthResource
from yarvelle_core.connectors.base import NormalisedRecord, ToolContext
from yarvelle_core.connectors.errors import ConnectorError, EgressBlockedError
from yarvelle_core.connectors.http import ScopedHttp

SMART_OAUTH_URIS_EXTENSION_URL = (
    "http://fhir-registry.smarthealthit.org/StructureDefinition/oauth-uris"
)
SMART_CAPABILITIES_EXTENSION_URL = (
    "http://fhir-registry.smarthealthit.org/StructureDefinition/capabilities"
)

SMART_V2_CLINICAL_SCOPES: Tuple[str, ...] = (
    "launch/patient",
    "openid",
    "fhirUser",
    "offline_access",
    "patient/Patient.rs",
    "patient/Condition.rs",
    "patient/MedicationRequest.rs",
    "patient/AllergyIntolerance.rs",
    "patient/Immunization.rs",
    "patient/Observation.rs",
    "patient/DiagnosticReport.rs",
    "patient/Procedure.rs",
    "patient/CarePlan.rs",
    "patient/Encounter.rs",
    "patient/DocumentReference.rs",
)

SMART_V1_CLINICAL_SCOPES: Tuple[str, ...] = (
    "openid",
    "fhirUser",
    "launch/patient",
    "patient/Patient.read",
    "patient/Condition.read",
    "patient/MedicationRequest.read",
    "patient/AllergyIntolerance.read",
    "patient/Immunization.read",
    "patient/Observation.read",
    "patient/DiagnosticReport.read",
    "patient/Procedure.read",
    "patient/CarePlan.read",
    "patient/Encounter.read",
    "patient/DocumentReference.read",
)

SMART_COMBINED_CLINICAL_SCOPES: Tuple[str, ...] = tuple(
    dict.fromkeys((*SMART_V2_CLINICAL_SCOPES, *SMART_V1_CLINICAL_SCOPES))
)

DEFAULT_MAX_BUNDLE_PAGES: int = 10

_SENSITIVE_TOKEN_KEYS: frozenset[str] = frozenset({
    "access_token",
    "refresh_token",
    "id_token",
    "client_secret",
    "code_verifier",
    "code",
    "authorization",
    "password",
    "secret",
})

_BEARER_PATTERN = re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]+")
_KV_SECRET_PATTERN = re.compile(
    r"(?i)\b(access_token|refresh_token|id_token|client_secret|code_verifier|code)=([^&\s\"']+)"
)


def redact_smart_auth_secrets(value: Any) -> Any:
    """Scrubs OAuth tokens, refresh tokens, PKCE verifiers, and secrets from dicts, lists, and log strings."""
    if isinstance(value, str):
        redacted = _BEARER_PATTERN.sub(r"\1[REDACTED]", value)
        redacted = _KV_SECRET_PATTERN.sub(r"\1=[REDACTED]", redacted)
        return redacted
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            key_str = str(k)
            if key_str.strip().lower() in _SENSITIVE_TOKEN_KEYS:
                out[key_str] = "[REDACTED]"
            else:
                out[key_str] = redact_smart_auth_secrets(v)
        return out
    if isinstance(value, list):
        return [redact_smart_auth_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_smart_auth_secrets(item) for item in value)
    return value


@dataclass
class SmartUntrustedResult(UntrustedResult):
    """UntrustedResult subclass that also provides Mapping-style `.get()`, `.keys()`, `.items()` access."""

    def get(self, key: str, default: Any = None) -> Any:
        if isinstance(self.data, Mapping):
            return self.data.get(key, default)
        return default

    def keys(self) -> Any:
        if isinstance(self.data, Mapping):
            return self.data.keys()
        return ()

    def items(self) -> Any:
        if isinstance(self.data, Mapping):
            return self.data.items()
        return ()

    def values(self) -> Any:
        if isinstance(self.data, Mapping):
            return self.data.values()
        return ()

    def to_dict(self) -> Dict[str, Any]:
        if isinstance(self.data, dict):
            return dict(self.data)
        return {"data": self.data}


@dataclass(frozen=True)
class SmartConfiguration:
    """Validated SMART on FHIR server discovery metadata."""

    fhir_base_url: str
    authorization_endpoint: str
    token_endpoint: str
    revocation_endpoint: Optional[str] = None
    introspection_endpoint: Optional[str] = None
    capabilities: Tuple[str, ...] = ()
    scopes_supported: Tuple[str, ...] = ()
    code_challenge_methods_supported: Tuple[str, ...] = ("S256",)
    grant_types_supported: Tuple[str, ...] = ()
    discovery_source: str = "well-known"

    @property
    def supports_pkce_s256(self) -> bool:
        return any(m.strip().upper() == "S256" for m in self.code_challenge_methods_supported)

    @property
    def supports_smart_v2_scopes(self) -> bool:
        if "permission-v2" in self.capabilities:
            return True
        for scope in self.scopes_supported:
            if scope.endswith((".rs", ".r", ".s", ".cruds")):
                return True
        return False

    def negotiate_scopes(
        self,
        requested_scopes: Optional[Sequence[str]] = None,
        *,
        prefer_v2: bool = True,
    ) -> List[str]:
        """Negotiates SMART v2 `.rs` scopes vs v1 `.read` scopes based on server capabilities."""
        base_requested = list(
            requested_scopes
            if requested_scopes is not None
            else (SMART_V2_CLINICAL_SCOPES if prefer_v2 else SMART_V1_CLINICAL_SCOPES)
        )
        if not self.scopes_supported:
            return list(dict.fromkeys(s.strip() for s in base_requested if s and s.strip()))

        supported_set = {s.strip() for s in self.scopes_supported if s and s.strip()}
        has_v2_on_server = self.supports_smart_v2_scopes
        has_v1_on_server = any(
            s.endswith(".read") or s == "patient/*.read" for s in supported_set
        )

        negotiated: List[str] = []
        for raw_scope in base_requested:
            s = (raw_scope or "").strip()
            if not s:
                continue
            if s in supported_set:
                negotiated.append(s)
                continue
            # Convert .rs <-> .read when server only advertises one generation
            if s.endswith(".rs") and not has_v2_on_server and has_v1_on_server:
                v1_equiv = s[:-3] + ".read"
                if v1_equiv in supported_set or "patient/*.read" in supported_set:
                    negotiated.append(v1_equiv)
                    continue
            if s.endswith(".read") and prefer_v2 and has_v2_on_server:
                v2_equiv = s[:-5] + ".rs"
                if v2_equiv in supported_set or "patient/*.rs" in supported_set:
                    negotiated.append(v2_equiv)
                    continue
            negotiated.append(s)

        return list(dict.fromkeys(negotiated))


def _validate_oauth_endpoint_url(url: Any, field_name: str) -> str:
    """Validates an OAuth endpoint URL discovered from SMART metadata."""
    clean = str(url or "").strip()
    if not clean:
        raise ValueError(f"SMART discovery metadata is missing required '{field_name}'.")
    parsed = urlparse(clean)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme not in ("https", "http") or not host:
        raise ValueError(f"SMART discovery '{field_name}' must be a valid HTTP(S) URL.")
    if scheme == "http" and host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(
            f"SMART discovery '{field_name}' must use https:// for non-loopback hosts (got '{scheme}://{host}')."
        )
    return clean


def _parse_capability_statement_smart_config(
    fhir_base_url: str,
    payload: Mapping[str, Any],
) -> SmartConfiguration:
    """Extracts SMART OAuth endpoints and capabilities from a FHIR R4 CapabilityStatement (`/metadata`)."""
    if str(payload.get("resourceType") or "").strip() != "CapabilityStatement":
        raise ValueError(
            "Fallback /metadata response is not a valid FHIR CapabilityStatement."
        )

    auth_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None
    revoke_endpoint: Optional[str] = None
    introspect_endpoint: Optional[str] = None
    capabilities: List[str] = []

    rest_entries = payload.get("rest")
    if isinstance(rest_entries, list):
        for rest in rest_entries:
            if not isinstance(rest, Mapping):
                continue
            security = rest.get("security")
            if not isinstance(security, Mapping):
                continue
            extensions = security.get("extension")
            if not isinstance(extensions, list):
                continue
            for ext in extensions:
                if not isinstance(ext, Mapping):
                    continue
                ext_url = str(ext.get("url") or "").strip()
                if ext_url == SMART_OAUTH_URIS_EXTENSION_URL or ext_url.endswith("/oauth-uris"):
                    nested = ext.get("extension")
                    if isinstance(nested, list):
                        for item in nested:
                            if not isinstance(item, Mapping):
                                continue
                            sub_url = str(item.get("url") or "").strip().lower()
                            val = (
                                item.get("valueUri")
                                or item.get("valueUrl")
                                or item.get("valueString")
                            )
                            if not val:
                                continue
                            if sub_url == "authorize":
                                auth_endpoint = str(val).strip()
                            elif sub_url == "token":
                                token_endpoint = str(val).strip()
                            elif sub_url == "revoke":
                                revoke_endpoint = str(val).strip()
                            elif sub_url == "introspect":
                                introspect_endpoint = str(val).strip()
                elif ext_url == SMART_CAPABILITIES_EXTENSION_URL or ext_url.endswith("/capabilities"):
                    cap_val = ext.get("valueCode") or ext.get("valueString")
                    if cap_val and str(cap_val).strip():
                        capabilities.append(str(cap_val).strip())

    validated_auth = _validate_oauth_endpoint_url(auth_endpoint, "authorization_endpoint")
    validated_token = _validate_oauth_endpoint_url(token_endpoint, "token_endpoint")

    return SmartConfiguration(
        fhir_base_url=fhir_base_url,
        authorization_endpoint=validated_auth,
        token_endpoint=validated_token,
        revocation_endpoint=revoke_endpoint,
        introspection_endpoint=introspect_endpoint,
        capabilities=tuple(dict.fromkeys(capabilities)),
        scopes_supported=(),
        code_challenge_methods_supported=("S256",),
        grant_types_supported=("authorization_code", "refresh_token"),
        discovery_source="capability-statement",
    )


async def discover_smart_configuration(
    fhir_base_url: str,
    http: ScopedHttp,
    *,
    require_pkce_s256: bool = True,
) -> SmartConfiguration:
    """Discovers SMART on FHIR v2 endpoints via `.well-known/smart-configuration` with `/metadata` fallback.

    Args:
        fhir_base_url: Base URL of the FHIR R4 server (e.g. `https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4`).
        http: `ScopedHttp` client enforcing the connector's `allowed_hosts` policy.
        require_pkce_s256: When True (default), fails closed if the server advertises
            `code_challenge_methods_supported` without `S256`.

    Returns:
        Validated `SmartConfiguration` instance.
    """
    clean_base = (fhir_base_url or "").strip().rstrip("/")
    if not clean_base:
        raise ValueError("fhir_base_url is required for SMART configuration discovery.")

    well_known_url = f"{clean_base}/.well-known/smart-configuration"
    resp = await http.get(
        well_known_url,
        headers={"Accept": "application/json, application/fhir+json"},
    )

    if resp.status_code == 200:
        try:
            payload = resp.json()
        except Exception as err:
            raise ValueError(
                f"Malformed JSON in SMART .well-known/smart-configuration response: {err}"
            ) from err
        if not isinstance(payload, Mapping):
            raise ValueError("SMART .well-known/smart-configuration payload must be a JSON object.")

        auth_endpoint = _validate_oauth_endpoint_url(
            payload.get("authorization_endpoint"),
            "authorization_endpoint",
        )
        token_endpoint = _validate_oauth_endpoint_url(
            payload.get("token_endpoint"),
            "token_endpoint",
        )

        raw_methods = payload.get("code_challenge_methods_supported")
        if raw_methods is not None:
            if not isinstance(raw_methods, list):
                raise ValueError("SMART code_challenge_methods_supported must be a list.")
            methods = tuple(str(m).strip() for m in raw_methods if m and str(m).strip())
            if require_pkce_s256 and not any(m.upper() == "S256" for m in methods):
                raise ValueError(
                    "SMART server does not support required PKCE 'S256' code_challenge_method "
                    f"(advertised: {list(methods)})."
                )
        else:
            methods = ("S256",)

        capabilities = tuple(
            str(c).strip()
            for c in (payload.get("capabilities") or ())
            if c and str(c).strip()
        )
        scopes_supported = tuple(
            str(s).strip()
            for s in (payload.get("scopes_supported") or ())
            if s and str(s).strip()
        )
        grant_types = tuple(
            str(g).strip()
            for g in (payload.get("grant_types_supported") or ())
            if g and str(g).strip()
        )
        revoke_ep = (
            str(payload["revocation_endpoint"]).strip()
            if payload.get("revocation_endpoint")
            else None
        )
        introspect_ep = (
            str(payload["introspection_endpoint"]).strip()
            if payload.get("introspection_endpoint")
            else None
        )

        return SmartConfiguration(
            fhir_base_url=clean_base,
            authorization_endpoint=auth_endpoint,
            token_endpoint=token_endpoint,
            revocation_endpoint=revoke_ep,
            introspection_endpoint=introspect_ep,
            capabilities=capabilities,
            scopes_supported=scopes_supported,
            code_challenge_methods_supported=methods,
            grant_types_supported=grant_types,
            discovery_source="well-known",
        )

    if resp.status_code in (404, 405, 501):
        metadata_url = f"{clean_base}/metadata"
        meta_resp = await http.get(
            metadata_url,
            headers={"Accept": "application/fhir+json, application/json"},
        )
        if meta_resp.status_code >= 400:
            raise ConnectorError(
                f"SMART discovery failed: .well-known returned HTTP {resp.status_code} "
                f"and fallback /metadata returned HTTP {meta_resp.status_code}."
            )
        try:
            meta_payload = meta_resp.json()
        except Exception as err:
            raise ValueError(f"Malformed JSON in fallback /metadata response: {err}") from err
        if not isinstance(meta_payload, Mapping):
            raise ValueError("Fallback /metadata payload must be a JSON object.")

        return _parse_capability_statement_smart_config(clean_base, meta_payload)

    raise ConnectorError(
        f"SMART .well-known/smart-configuration discovery failed with HTTP {resp.status_code}."
    )


def build_smart_authorization_url(
    *,
    smart_config: SmartConfiguration,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_verifier: Optional[str] = None,
    scopes: Optional[Sequence[str]] = None,
    launch: Optional[str] = None,
    extra_params: Optional[Mapping[str, str]] = None,
) -> str:
    """Constructs a SMART on FHIR v2 authorization URL with PKCE S256 verification and `aud` binding."""
    from carefold.connectors.oauth import verify_pkce_challenge

    if not smart_config.supports_pkce_s256:
        raise ValueError("SMART configuration does not support PKCE S256.")

    clean_challenge = (code_challenge or "").strip()
    if not clean_challenge:
        raise ValueError("PKCE code_challenge is required for SMART on FHIR launch.")

    if code_verifier is not None:
        if not verify_pkce_challenge(code_verifier, clean_challenge):
            raise ValueError("PKCE S256 code_verifier does not match code_challenge.")

    negotiated_scopes = smart_config.negotiate_scopes(scopes)
    params: Dict[str, str] = {
        "response_type": "code",
        "client_id": (client_id or "").strip(),
        "redirect_uri": (redirect_uri or "").strip(),
        "state": (state or "").strip(),
        "code_challenge": clean_challenge,
        "code_challenge_method": "S256",
        "aud": smart_config.fhir_base_url,
    }
    if negotiated_scopes:
        params["scope"] = " ".join(negotiated_scopes)
    if launch and str(launch).strip():
        params["launch"] = str(launch).strip()
    if extra_params:
        for k, v in extra_params.items():
            if k not in params and v is not None:
                params[str(k)] = str(v)

    sep = "&" if "?" in smart_config.authorization_endpoint else "?"
    return f"{smart_config.authorization_endpoint}{sep}{urlencode(params)}"


def _extract_bundle_next_link(bundle: Mapping[str, Any], current_url: str) -> Optional[str]:
    """Extracts and resolves `Bundle.link[relation='next'].url` from a FHIR R4 Bundle."""
    links = bundle.get("link")
    if not isinstance(links, list):
        return None
    for link in links:
        if not isinstance(link, Mapping):
            continue
        relation = str(link.get("relation") or "").strip().lower()
        raw_url = str(link.get("url") or "").strip()
        if relation == "next" and raw_url:
            if "://" in raw_url:
                return raw_url
            return urljoin(current_url, raw_url)
    return None


async def fetch_paginated_fhir_bundle_resources(
    *,
    http: ScopedHttp,
    initial_url: str,
    params: Optional[Mapping[str, str]] = None,
    max_pages: int = DEFAULT_MAX_BUNDLE_PAGES,
    connector_label: str = "SMART on FHIR",
    stream_name: str = "Resource",
) -> Tuple[List[Dict[str, Any]], Optional[str], bool, int]:
    """Fetches a FHIR R4 Bundle stream and follows `Bundle.link[relation='next']` across pages via `ScopedHttp`.

    Enforces:
    - Every page request traverses `ScopedHttp.get()`, which validates host allowlists and blocks SSRF/open redirects.
    - Duplicate `next` URLs terminate pagination deterministically to prevent infinite server loops.
    - Stops after `max_pages` (default 10) and returns `(records, next_cursor, has_more, pages_fetched)`.
    """
    effective_max_pages = max(1, int(max_pages or DEFAULT_MAX_BUNDLE_PAGES))
    accumulated: List[Dict[str, Any]] = []
    visited_urls: Set[str] = set()
    current_url = initial_url
    current_params: Optional[Mapping[str, str]] = dict(params) if params else None
    pages_fetched = 0
    next_cursor: Optional[str] = None
    has_more = False

    while pages_fetched < effective_max_pages:
        if current_params:
            response = await http.get(
                current_url,
                params=current_params,
                headers={"Accept": "application/fhir+json"},
            )
        else:
            response = await http.get(
                current_url,
                headers={"Accept": "application/fhir+json"},
            )

        if response.status_code >= 400:
            raise ConnectorError(
                f"{connector_label} fetch failed for '{stream_name}' with HTTP {response.status_code}"
            )

        bundle = response.json()
        if not isinstance(bundle, Mapping):
            raise ConnectorError(
                f"{connector_label} returned a non-object Bundle payload for '{stream_name}'."
            )

        entries = bundle.get("entry", [])
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, Mapping) and isinstance(entry.get("resource"), dict):
                    accumulated.append(dict(entry["resource"]))

        pages_fetched += 1
        visited_urls.add(str(response.url) if getattr(response, "url", None) else current_url)
        visited_urls.add(current_url)

        next_url = _extract_bundle_next_link(bundle, current_url)
        if not next_url or next_url in visited_urls:
            next_cursor = None
            has_more = False
            break

        # Validate next_url eagerly against ScopedHttp allowlist even if max_pages is reached
        http.validate_url(next_url)

        if pages_fetched >= effective_max_pages:
            next_cursor = next_url
            has_more = True
            break

        current_url = next_url
        current_params = None

    return accumulated, next_cursor, has_more, pages_fetched


async def persist_smart_fhir_records(
    session: AsyncSession,
    *,
    profile_id: str,
    records: Sequence[NormalisedRecord],
    connection_id: Optional[str] = None,
    connector_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> List[HealthResource]:
    """Persists mapped SMART on FHIR `NormalisedRecord` items into the `#282`/`#283` FHIR R4 repository.

    Routes each record through `upsert_fhir_resource_with_history`, populating:
    - `health_resources`
    - `health_resource_versions`
    - `health_resource_codings`
    - `health_resource_references`
    and executing cross-portal deduplication (`find_dedup_matches_in_repository`).
    """
    persisted: List[HealthResource] = []
    source_ref = (connection_id or connector_id or "smart_fhir").strip()

    for norm in records:
        payload = norm.data if isinstance(norm.data, Mapping) else {}
        fhir_raw = payload.get("fhir_resource") if isinstance(payload.get("fhir_resource"), Mapping) else payload
        if not isinstance(fhir_raw, Mapping) or not fhir_raw.get("resourceType"):
            continue

        fhir_dict = copy.deepcopy(dict(fhir_raw))
        rtype = str(fhir_dict.get("resourceType") or norm.record_type).strip()
        prov = (
            fhir_dict.setdefault("_carefold_provenance", {})
            if isinstance(fhir_dict.get("_carefold_provenance"), dict)
            else {}
        )
        if not isinstance(prov, dict):
            prov = {}
            fhir_dict["_carefold_provenance"] = prov

        prov["trust"] = str(payload.get("trust") or "untrusted")
        prov["source_type"] = "connector"
        prov["source_ref"] = source_ref
        if connector_id:
            prov["connector_id"] = connector_id
        for extra_key in (
            "source_display",
            "code_display",
            "effective_date",
            "claim_total",
            "provider_display",
            "payor_display",
            "subscriber_id",
        ):
            if payload.get(extra_key) is not None:
                prov[extra_key] = payload[extra_key]

        hr, _ver, _created = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type=rtype,
            fhir_data=fhir_dict,
            source_type="connector",
            source_ref=source_ref,
            source_id=f"{rtype}:{norm.id}",
            effective_at=norm.timestamp,
            actor_user_id=actor_user_id,
            strict_patient_matching=False,
            enable_dedup=True,
        )
        persisted.append(hr)

    return persisted


def _build_record_dict_from_health_resource(
    hr: HealthResource,
    *,
    default_source_label: str,
) -> Dict[str, Any]:
    """Reconstructs a connector search record dictionary from a persisted `HealthResource` row."""
    raw_data = dict(hr.data) if isinstance(hr.data, Mapping) else {}
    prov = raw_data.get("_carefold_provenance") if isinstance(raw_data.get("_carefold_provenance"), Mapping) else {}

    # If hr.data already wraps fhir_resource, use it; otherwise hr.data IS the normalized FHIR resource
    if isinstance(raw_data.get("fhir_resource"), Mapping):
        fhir_res = dict(raw_data["fhir_resource"])
    else:
        fhir_res = {k: v for k, v in raw_data.items() if k != "_carefold_provenance"}

    rtype = str(fhir_res.get("resourceType") or hr.resource_type or "Resource")
    eff_date = (
        str(prov.get("effective_date") or "")
        or (hr.effective_at.date().isoformat() if isinstance(hr.effective_at, datetime) else "")
        or datetime.now(timezone.utc).date().isoformat()
    )
    source_display = (
        str(prov.get("source_display") or raw_data.get("source_display") or "")
        or f"From {default_source_label}, {eff_date}"
    )

    code_display = str(prov.get("code_display") or raw_data.get("code_display") or "")
    if not code_display:
        for concept_field in ("code", "medicationCodeableConcept", "vaccineCode", "type"):
            concept = fhir_res.get(concept_field)
            if isinstance(concept, Mapping):
                if concept.get("text"):
                    code_display = str(concept["text"])
                    break
                codings = concept.get("coding")
                if isinstance(codings, list) and codings and isinstance(codings[0], Mapping):
                    code_display = str(codings[0].get("display") or codings[0].get("code") or "")
                    if code_display:
                        break
            elif isinstance(concept, list) and concept and isinstance(concept[0], Mapping):
                code_display = str(concept[0].get("text") or "")
                if code_display:
                    break
        if not code_display:
            code_display = rtype

    result: Dict[str, Any] = {
        "resourceType": rtype,
        "fhir_resource": fhir_res,
        "code_display": code_display,
        "effective_date": eff_date,
        "source_display": source_display,
        "trust": "untrusted",
    }
    for claim_key in ("claim_total", "provider_display", "payor_display", "subscriber_id"):
        val = prov.get(claim_key) if prov.get(claim_key) is not None else raw_data.get(claim_key)
        if val is not None:
            result[claim_key] = val

    if rtype == "ExplanationOfBenefit":
        if "provider_display" not in result and isinstance(fhir_res.get("provider"), Mapping):
            p_disp = fhir_res["provider"].get("display")
            if p_disp:
                result["provider_display"] = str(p_disp)
        if "claim_total" not in result and isinstance(fhir_res.get("total"), list) and fhir_res["total"]:
            first_tot = fhir_res["total"][0]
            if isinstance(first_tot, Mapping) and isinstance(first_tot.get("amount"), Mapping):
                amt_val = first_tot["amount"].get("value")
                if amt_val is not None:
                    try:
                        result["claim_total"] = float(amt_val)
                    except (TypeError, ValueError):
                        pass
    elif rtype == "Coverage":
        if "payor_display" not in result and isinstance(fhir_res.get("payor"), list) and fhir_res["payor"]:
            first_payor = fhir_res["payor"][0]
            if isinstance(first_payor, Mapping) and first_payor.get("display"):
                result["payor_display"] = str(first_payor["display"])
        if "subscriber_id" not in result and fhir_res.get("subscriberId"):
            result["subscriber_id"] = str(fhir_res["subscriberId"])

    return result


async def _load_persisted_records_for_profile(
    profile_id: str,
    *,
    session: Optional[AsyncSession] = None,
    resource_type_filter: str = "",
    default_source_label: str = "SMART on FHIR",
) -> List[Dict[str, Any]]:
    """Loads persisted `HealthResource` rows for `profile_id` from the database when available."""
    clean_profile = (profile_id or "").strip()
    if not clean_profile:
        return []

    async def _run_query(db: AsyncSession) -> List[Dict[str, Any]]:
        stmt = (
            select(HealthResource)
            .where(
                HealthResource.profile_id == clean_profile,
                HealthResource.status == "active",
            )
            .order_by(HealthResource.effective_at.desc(), HealthResource.updated_at.desc())
            .execution_options(include_all_scopes=True)
        )
        rows = list((await db.execute(stmt)).scalars().all())
        out: List[Dict[str, Any]] = []
        for hr in rows:
            if hr.resource_type == "Patient" and hr.source_type == "profile_anchor":
                continue
            if resource_type_filter and hr.resource_type.lower() != resource_type_filter.lower():
                continue
            out.append(_build_record_dict_from_health_resource(hr, default_source_label=default_source_label))
        return out

    if session is not None:
        return await _run_query(session)

    try:
        from carefold.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as db_sess:
            return await _run_query(db_sess)
    except Exception:
        return []


async def search_smart_fhir_records(
    ctx: ToolContext,
    args: Mapping[str, Any],
    *,
    fallback_indexed_records: Sequence[NormalisedRecord] = (),
    default_source_label: str = "SMART on FHIR",
    connector_source: str = "smart_fhir",
) -> SmartUntrustedResult:
    """Queries persisted `HealthResource` rows (with fallback to in-memory records) and wraps in `SmartUntrustedResult`."""
    query = str(args.get("query") or "").strip().lower()
    resource_type = str(args.get("resource_type") or "").strip()
    limit = max(1, min(int(args.get("limit", 20)), 100))
    explicit_session: Optional[AsyncSession] = (
        args.get("session")
        if isinstance(args.get("session"), AsyncSession)
        else getattr(ctx, "session", None)
    )

    persisted_dicts = await _load_persisted_records_for_profile(
        ctx.profile_id,
        session=explicit_session,
        resource_type_filter=resource_type,
        default_source_label=default_source_label,
    )

    candidates: List[Dict[str, Any]] = list(persisted_dicts)
    seen_keys: Set[str] = set()
    for item in candidates:
        fhir_res = item.get("fhir_resource") if isinstance(item.get("fhir_resource"), Mapping) else {}
        seen_keys.add(f"{item.get('resourceType')}:{fhir_res.get('id') or ''}")

    # Merge any in-memory mapped records not yet flushed to DB (preserves standalone unit test compatibility)
    for rec in fallback_indexed_records:
        if rec.profile_id != ctx.profile_id:
            continue
        if resource_type and rec.record_type.lower() != resource_type.lower():
            continue
        rec_data = dict(rec.data) if isinstance(rec.data, Mapping) else {}
        fhir_res = rec_data.get("fhir_resource") if isinstance(rec_data.get("fhir_resource"), Mapping) else {}
        dedup_key = f"{rec.record_type}:{fhir_res.get('id') or rec.id}"
        if dedup_key not in seen_keys:
            seen_keys.add(dedup_key)
            candidates.append(rec_data)

    matches: List[Dict[str, Any]] = []
    for data in candidates:
        if query:
            haystack = json.dumps(data, sort_keys=True, default=str).lower()
            if query not in haystack:
                continue
        matches.append(data)
        if len(matches) >= limit:
            break

    # Mark tool context tainted when present
    taint_obj = getattr(ctx, "taint", None)
    if taint_obj is not None:
        if hasattr(taint_obj, "set") and callable(taint_obj.set):
            taint_obj.set()
        elif hasattr(taint_obj, "mark_tainted") and callable(taint_obj.mark_tainted):
            taint_obj.mark_tainted(reason=f"untrusted_tool:{connector_source}")

    payload = {
        "profile_id": ctx.profile_id,
        "count": len(matches),
        "trust": "untrusted",
        "records": matches,
    }
    return SmartUntrustedResult(
        data=payload,
        taint=True,
        source=connector_source,
    )


__all__ = [
    "DEFAULT_MAX_BUNDLE_PAGES",
    "SMART_CAPABILITIES_EXTENSION_URL",
    "SMART_COMBINED_CLINICAL_SCOPES",
    "SMART_OAUTH_URIS_EXTENSION_URL",
    "SMART_V1_CLINICAL_SCOPES",
    "SMART_V2_CLINICAL_SCOPES",
    "SmartConfiguration",
    "SmartUntrustedResult",
    "build_smart_authorization_url",
    "discover_smart_configuration",
    "fetch_paginated_fhir_bundle_resources",
    "persist_smart_fhir_records",
    "redact_smart_auth_secrets",
    "search_smart_fhir_records",
]
