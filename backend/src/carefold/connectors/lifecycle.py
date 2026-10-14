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

"""Connection Lifecycle State Machine, 4-Step Revoke Cascade, Granular Consent & Data Flows (AU-52 & AU-53).

Implements:
- 6-state connection lifecycle (`pending_auth`, `active`, `degraded`, `needs_reauth`, `revoked`, `deleted`).
- 3 consecutive sync failures -> `degraded` (`DESIGN §5.5`), `invalid_grant` / `401` -> `needs_reauth`.
- Scope/host expansion re-consent (`needs_reauth`) and `ai_use_allowed=False` vendor terms kill-switch (`revoked`).
- Under-13 pediatric connection guard (`E12.2`).
- 4-Step Revoke Cascade (`Titan S2`):
  1. Revoke `ConsentGrant` rows
  2. Cancel/delete scheduled `sync` `Job` rows
  3. Delete `Credential` rows (crypto-shredding tokens)
  4. Optionally delete imported `HealthResource` rows (`source_type='connector'`)
  5. Record `AuditEventRecord` (`event='connection_revoked'`, `risk='irreversible'`).
- Settings › Data Flows transparency inventory (`get_profile_data_flows`, `AU-53`).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlparse
import uuid

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.config import settings
from carefold.db.models import (
    AuditEventRecord,
    Connection,
    ConsentGrant,
    Credential,
    HealthResource,
    Job,
    Profile,
    SystemSetting,
    utc_now,
)
from carefold.tools.web_search import DEFAULT_ALLOWED_SEARCH_HOSTS
import connectors
from connectors.manifest import ConnectorManifest

UNDER_13_MONTHS: int = 13 * 12  # 156 months
CONSECUTIVE_FAILURES_DEGRADED_THRESHOLD: int = 3

AUTHORIZED_GUARDIAN_ROLES = frozenset({
    "guardian",
    "steward",
    "admin",
    "manage",
    "parent",
    "owner",
})

REAUTH_ERROR_CODES = frozenset({
    "invalid_grant",
    "unauthorized",
    "401",
    "token_expired",
    "needs_reauth",
    "reconsent_required",
    "invalid_token",
})


_FALLBACK_STARTER_MANIFESTS: List[Dict[str, Any]] = [
    {
        "id": "withings",
        "version": "0.1.0",
        "name": "Withings Health Mate",
        "description": "Ingests smart scale weight, blood pressure, heart rate, and SpO2 readings from Withings Health Mate.",
        "categories": ["vitals"],
        "entrypoint": "connectors.starters.withings:WithingsConnector",
        "data_flows": {
            "allowed_hosts": ["wbsapi.withings.net", "account.withings.com"],
            "allowed_schemes": ["https"],
            "allowed_ports": [443],
            "egress_direction": "egress_only",
            "pii_types_transferred": ["vitals"],
        },
        "auth": {
            "type": "oauth2",
            "pkce": True,
            "client_source": "byo",
            "token_rotation": True,
            "rotating_refresh": True,
            "scopes": ["user.metrics"],
            "authorization_url": "https://account.withings.com/oauth2_user/authorize2",
            "token_url": "https://wbsapi.withings.net/v2/oauth2",
        },
        "trust": {
            "publisher": "Spectrayan",
            "verified": True,
            "sandbox_level": "strict",
            "trust_level": "trusted",
        },
        "terms": {
            "license": "Apache-2.0",
            "ai_use_allowed": True,
        },
    },
    {
        "id": "google-calendar",
        "version": "0.1.0",
        "name": "Google Calendar",
        "description": "Syncs busy blocks, suggests conflict-free clinic appointment slots, and creates sanitized appointment events.",
        "categories": ["scheduling", "calendar"],
        "entrypoint": "connectors.starters.calendar:GoogleCalendarConnector",
        "data_flows": {
            "allowed_hosts": ["www.googleapis.com", "oauth2.googleapis.com", "accounts.google.com"],
            "allowed_schemes": ["https"],
            "allowed_ports": [443],
            "egress_direction": "bidirectional",
            "pii_types_transferred": ["appointment_schedule"],
        },
        "auth": {
            "type": "oauth2",
            "pkce": True,
            "client_source": "byo",
            "token_rotation": False,
            "rotating_refresh": False,
            "scopes": [
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/calendar.events",
            ],
            "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
        },
        "trust": {
            "publisher": "Spectrayan",
            "verified": True,
            "sandbox_level": "strict",
            "trust_level": "trusted",
        },
        "terms": {
            "license": "Apache-2.0",
            "ai_use_allowed": True,
        },
    },
    {
        "id": "caldav",
        "version": "0.1.0",
        "name": "CalDAV Calendar",
        "description": "Standards-based CalDAV calendar connector for iCloud, Fastmail, and self-hosted DAV servers.",
        "categories": ["scheduling", "calendar"],
        "entrypoint": "connectors.starters.calendar:CalDavConnector",
        "data_flows": {
            "allowed_hosts": ["caldav.icloud.com", "caldav.fastmail.com", "localhost"],
            "allowed_schemes": ["https", "http"],
            "allowed_ports": [443, 80, 5232, 8008, 8443],
            "egress_direction": "bidirectional",
            "pii_types_transferred": ["appointment_schedule"],
        },
        "auth": {
            "type": "basic",
            "pkce": False,
            "client_source": "byo",
            "token_rotation": False,
            "rotating_refresh": False,
            "scopes": [],
        },
        "trust": {
            "publisher": "Spectrayan",
            "verified": True,
            "sandbox_level": "strict",
            "trust_level": "trusted",
        },
        "terms": {
            "license": "Apache-2.0",
            "ai_use_allowed": True,
        },
    },
    {
        "id": "epic-smart",
        "version": "0.1.0",
        "name": "Epic MyChart (SMART on FHIR)",
        "description": "Patient-facing SMART on FHIR R4 read-only clinical records connector for Epic MyChart.",
        "categories": [
            "clinical_records",
            "medications",
            "allergies",
            "immunisations",
            "vitals",
            "labs",
        ],
        "entrypoint": "connectors.starters.epic_smart:EpicSmartConnector",
        "data_flows": {
            "allowed_hosts": ["fhir.epic.com"],
            "allowed_schemes": ["https"],
            "allowed_ports": [443],
            "egress_direction": "egress_only",
            "pii_types_transferred": [
                "clinical_records",
                "medications",
                "allergies",
                "immunisations",
                "vitals",
                "labs",
            ],
        },
        "auth": {
            "type": "oauth2",
            "pkce": True,
            "client_source": "byo",
            "token_rotation": False,
            "rotating_refresh": False,
            "scopes": [
                "openid",
                "fhirUser",
                "launch/patient",
                "patient/Patient.read",
                "patient/Condition.read",
                "patient/MedicationRequest.read",
                "patient/AllergyIntolerance.read",
                "patient/Immunization.read",
                "patient/Observation.read",
                "patient/Encounter.read",
                "patient/DocumentReference.read",
            ],
            "authorization_url": "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize",
            "token_url": "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token",
        },
        "trust": {
            "publisher": "Spectrayan",
            "verified": True,
            "sandbox_level": "strict",
            "trust_level": "untrusted",
        },
        "terms": {
            "license": "Apache-2.0",
            "ai_use_allowed": True,
        },
    },
]


def list_connector_manifests() -> List[ConnectorManifest]:
    """Discovers and returns all starter `ConnectorManifest` definitions."""
    manifests_by_id: Dict[str, ConnectorManifest] = {}
    for fallback_data in _FALLBACK_STARTER_MANIFESTS:
        manifest = ConnectorManifest.from_dict(fallback_data)
        manifests_by_id[manifest.id] = manifest

    try:
        pkg_root = Path(connectors.__file__).resolve().parent
        manifests_dir = pkg_root / "starters" / "manifests"
        if manifests_dir.is_dir():
            for yaml_path in sorted(manifests_dir.glob("*.yaml")):
                loaded = ConnectorManifest.from_yaml(yaml_path)
                manifests_by_id[loaded.id] = loaded
    except Exception:
        pass

    return list(manifests_by_id.values())


def get_connector_manifest(connector_id: str) -> Optional[ConnectorManifest]:
    """Looks up a `ConnectorManifest` by its unique `connector_id`."""
    clean_id = (connector_id or "").strip().lower()
    if not clean_id:
        return None
    for manifest in list_connector_manifests():
        if manifest.id.lower() == clean_id:
            return manifest
    return None


def serialize_connector_manifest(manifest: ConnectorManifest) -> Dict[str, Any]:
    """Serializes a `ConnectorManifest` into a frontend-compatible catalog summary dictionary."""
    return {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "description": manifest.description,
        "categories": list(manifest.categories),
        "allowed_hosts": list(manifest.data_flows.allowed_hosts),
        "scopes": list(manifest.auth.scopes),
        "scope_details": list(manifest.auth.scope_details),
        "auth_type": manifest.auth.type,
        "authorization_url": manifest.auth.authorization_url,
        "token_url": manifest.auth.token_url,
        "pkce": bool(manifest.auth.pkce),
        "client_source": manifest.auth.client_source,
        "rotating_refresh": bool(manifest.auth.rotating_refresh),
        "trust_level": manifest.trust.trust_level,
        "ai_use_allowed": bool(manifest.terms.ai_use_allowed),
    }


def _is_profile_under_13(profile: Profile, reference_date: Optional[date] = None) -> bool:
    """Determines whether a `Profile` is under 13 years of age (fails closed for child profiles)."""
    ref = reference_date or datetime.now(timezone.utc).date()
    dob_str = getattr(profile, "date_of_birth", None)
    rel_str = str(getattr(profile, "relationship", "") or "").strip().lower()

    if dob_str and isinstance(dob_str, str) and dob_str.strip():
        try:
            clean_dob = dob_str.strip()
            dob_date = (
                datetime.fromisoformat(clean_dob).date()
                if "T" in clean_dob
                else datetime.strptime(clean_dob[:10], "%Y-%m-%d").date()
            )
            months = (ref.year - dob_date.year) * 12 + (ref.month - dob_date.month)
            if ref.day < dob_date.day:
                months -= 1
            return max(0, months) < UNDER_13_MONTHS
        except Exception:
            pass

    return rel_str == "child"


def check_under_13_connection_guard(profile: Profile, user_role: str) -> None:
    """Enforces guardian/steward authorization when managing connections for an under-13 profile (`E12.2`).

    Raises:
        PermissionError: If the profile is under 13 and `user_role` is not an authorized guardian/steward role.
    """
    if not _is_profile_under_13(profile):
        return

    clean_role = (user_role or "").strip().lower()
    if clean_role not in AUTHORIZED_GUARDIAN_ROLES:
        raise PermissionError(
            "Guardian or steward authorization is required to create or manage external connections "
            "for an under-13 pediatric profile (E12.2)."
        )


async def grant_connector_consent(
    session: AsyncSession,
    profile_id: str,
    connector_id: str,
    categories: List[str],
    scopes: List[str],
    allowed_hosts: List[str],
    granted_by_user_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    purpose: str = "sync_and_assist",
    terms_version: str = "1.0.0",
    connector_version: str = "0.1.0",
) -> ConsentGrant:
    """Creates or updates an active `ConsentGrant` record and writes an `AuditEventRecord` (`AU-53`)."""
    clean_profile_id = (profile_id or "").strip()
    clean_connector_id = (connector_id or "").strip()
    if not clean_profile_id or not clean_connector_id:
        raise ValueError("profile_id and connector_id are required to grant connector consent.")

    now = utc_now()
    clean_categories = [str(c).strip() for c in (categories or []) if str(c).strip()]
    clean_scopes = [str(s).strip() for s in (scopes or []) if str(s).strip()]
    clean_hosts = [str(h).strip().lower() for h in (allowed_hosts or []) if str(h).strip()]

    stmt = select(ConsentGrant).where(
        ConsentGrant.profile_id == clean_profile_id,
        ConsentGrant.connector_id == clean_connector_id,
        ConsentGrant.status == "active",
    )
    if connection_id:
        stmt = stmt.where(
            or_(
                ConsentGrant.connection_id == connection_id,
                ConsentGrant.connection_id.is_(None),
            )
        )
    res = await session.execute(stmt)
    existing = res.scalars().first()

    if existing is not None:
        if connection_id:
            existing.connection_id = connection_id
        if granted_by_user_id:
            existing.granted_by_user_id = granted_by_user_id
        existing.categories_json = json.dumps(clean_categories)
        existing.scopes_json = json.dumps(clean_scopes)
        existing.allowed_hosts_json = json.dumps(clean_hosts)
        existing.purpose = purpose
        existing.terms_version = terms_version
        existing.connector_version = connector_version
        existing.status = "active"
        existing.granted_at = now
        existing.revoked_at = None
        existing.updated_at = now
        grant = existing
    else:
        grant = ConsentGrant(
            id=str(uuid.uuid4()),
            profile_id=clean_profile_id,
            connection_id=connection_id,
            connector_id=clean_connector_id,
            granted_by_user_id=granted_by_user_id,
            categories=clean_categories,
            scopes=clean_scopes,
            allowed_hosts=clean_hosts,
            purpose=purpose,
            terms_version=terms_version,
            connector_version=connector_version,
            status="active",
            granted_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(grant)

    if connection_id:
        conn_res = await session.execute(
            select(Connection).where(
                Connection.id == connection_id,
                Connection.profile_id == clean_profile_id,
            )
        )
        conn = conn_res.scalar_one_or_none()
        if conn is not None:
            conn.consented_version = connector_version
            conn.updated_at = now

    payload_hash = hashlib.sha256(
        json.dumps(
            {
                "profile_id": clean_profile_id,
                "connector_id": clean_connector_id,
                "categories": clean_categories,
                "scopes": clean_scopes,
                "allowed_hosts": clean_hosts,
                "purpose": purpose,
                "terms_version": terms_version,
                "connector_version": connector_version,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    audit_record = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=clean_profile_id,
        actor_user_id=granted_by_user_id,
        principal="user",
        event="consent_granted",
        tool="grant_connector_consent",
        risk="admin",
        decision="allow",
        payload_hash=payload_hash,
        external_ref=f"consent:{grant.id}",
        detail_redacted=json.dumps({
            "connector_id": clean_connector_id,
            "connection_id": connection_id,
            "categories": clean_categories,
            "allowed_hosts": clean_hosts,
            "purpose": purpose,
            "terms_version": terms_version,
            "connector_version": connector_version,
        }),
    )
    session.add(audit_record)
    await session.commit()
    await session.refresh(grant)
    return grant


async def check_scope_and_terms_compatibility(
    session: AsyncSession,
    connection: Connection,
    manifest_version: str,
    required_scopes: List[str],
    required_hosts: List[str],
    ai_use_allowed: bool = True,
) -> Tuple[bool, Optional[str]]:
    """Verifies vendor AI-use terms and ensures manifest scopes/hosts do not exceed the active `ConsentGrant`.

    Returns:
        Tuple of `(is_compatible, failure_reason_code)`.
    """
    now = utc_now()
    if not ai_use_allowed:
        connection.status = "revoked"
        connection.status_message = "Connector disabled: vendor terms prohibit AI use."
        connection.updated_at = now
        await session.commit()
        return False, "ai_use_prohibited"

    stmt = (
        select(ConsentGrant)
        .where(
            ConsentGrant.profile_id == connection.profile_id,
            ConsentGrant.connector_id == connection.connector_id,
            ConsentGrant.status == "active",
        )
        .order_by(ConsentGrant.granted_at.desc())
    )
    res = await session.execute(stmt)
    grant = res.scalars().first()

    if grant is None or grant.status != "active":
        return False, "consent_missing"

    consented_scopes = {s.strip() for s in grant.scopes if s and s.strip()}
    consented_hosts = {h.strip().lower() for h in grant.allowed_hosts if h and h.strip()}

    req_scopes = {s.strip() for s in (required_scopes or []) if s and s.strip()}
    req_hosts = {h.strip().lower() for h in (required_hosts or []) if h and h.strip()}

    unconsented_scopes = req_scopes - consented_scopes
    unconsented_hosts = req_hosts - consented_hosts

    if unconsented_scopes or unconsented_hosts:
        connection.status = "needs_reauth"
        connection.status_message = "Connector permissions or data flows changed; re-consent required."
        connection.updated_at = now
        await session.commit()
        return False, "reconsent_required"

    return True, None


async def record_sync_failure(
    session: AsyncSession,
    connection: Connection,
    error_code: str,
    error_message: str,
) -> str:
    """Updates `Connection` state and failure counters following a failed sync run (`DESIGN §5.5`).

    - `invalid_grant` / `unauthorized` / `401` / `token_expired` -> `needs_reauth`.
    - Otherwise increments `consecutive_failures`; when `>= 3`, transitions to `degraded`.
    """
    clean_code = (error_code or "sync_error").strip().lower()
    now = utc_now()

    if clean_code in REAUTH_ERROR_CODES:
        connection.status = "needs_reauth"
        connection.status_message = error_message or "OAuth token expired or revoked; re-authentication required."
        connection.updated_at = now
        await session.commit()
        return connection.status

    connection.consecutive_failures = int(connection.consecutive_failures or 0) + 1
    connection.status_message = error_message or f"Sync failure ({clean_code})"
    if connection.consecutive_failures >= CONSECUTIVE_FAILURES_DEGRADED_THRESHOLD:
        connection.status = "degraded"
    connection.updated_at = now
    await session.commit()
    return connection.status


async def revoke_connection(
    session: AsyncSession,
    profile_id: str,
    connection_id: str,
    actor_user_id: Optional[str] = None,
    delete_imported_data: bool = False,
) -> Dict[str, Any]:
    """Executes the 4-Step Revoke Cascade (`Titan S2` / `AU-52` / `AU-53`).

    Steps:
    1. Marks all `ConsentGrant` rows for `(profile_id, connection_id)` or `(profile_id, connector_id)`
       as `status='revoked'`, `revoked_at=utc_now()`.
    2. Cancels/deletes scheduled `Job` rows where `connection_id == connection.id` and `kind == 'sync'`.
    3. Deletes `Credential` rows where `connection_id == connection.id` (crypto-shredding tokens).
    4. If `delete_imported_data=True`, deletes `HealthResource` rows where `profile_id == profile_id`,
       `source_type == 'connector'`, and `source_ref == connection.id`, and sets `connection.status = 'deleted'`;
       otherwise sets `connection.status = 'revoked'`.
    5. Writes an `AuditEventRecord` (`event='connection_revoked'`, `tool='revoke_connection'`, `risk='irreversible'`).
    """
    clean_profile_id = (profile_id or "").strip()
    clean_connection_id = (connection_id or "").strip()
    if not clean_profile_id or not clean_connection_id:
        raise ValueError("profile_id and connection_id are required.")

    conn_stmt = select(Connection).where(
        Connection.id == clean_connection_id,
        Connection.profile_id == clean_profile_id,
    )
    conn_res = await session.execute(conn_stmt)
    connection = conn_res.scalar_one_or_none()
    if connection is None:
        raise ValueError(f"Connection '{clean_connection_id}' not found for profile '{clean_profile_id}'.")

    now = utc_now()

    # Step 1: Mark ConsentGrant rows as revoked
    consent_stmt = select(ConsentGrant).where(
        ConsentGrant.profile_id == clean_profile_id,
        or_(
            ConsentGrant.connection_id == connection.id,
            ConsentGrant.connector_id == connection.connector_id,
        ),
    )
    consent_res = await session.execute(consent_stmt)
    grants = list(consent_res.scalars().all())
    consents_revoked = 0
    for grant in grants:
        if grant.status != "revoked":
            consents_revoked += 1
        grant.status = "revoked"
        grant.revoked_at = now
        grant.updated_at = now

    # Step 2: Cancel/delete scheduled sync Job rows for this connection
    job_del_stmt = delete(Job).where(
        Job.profile_id == clean_profile_id,
        Job.connection_id == connection.id,
        Job.kind.in_(("sync", "connector_sync")),
    )
    job_del_res = await session.execute(job_del_stmt)
    jobs_cancelled = int(job_del_res.rowcount or 0)

    # Step 3: Delete Credential rows (crypto-shredding OAuth/API tokens)
    cred_del_stmt = delete(Credential).where(
        Credential.connection_id == connection.id,
        Credential.profile_id == clean_profile_id,
    )
    cred_del_res = await session.execute(cred_del_stmt)
    credentials_deleted = int(cred_del_res.rowcount or 0)

    # Step 4: Optionally delete imported HealthResource rows & transition Connection status
    resources_deleted = 0
    if delete_imported_data:
        hr_del_stmt = delete(HealthResource).where(
            HealthResource.profile_id == clean_profile_id,
            HealthResource.source_type == "connector",
            HealthResource.source_ref == connection.id,
        )
        hr_del_res = await session.execute(hr_del_stmt)
        resources_deleted = int(hr_del_res.rowcount or 0)
        connection.status = "deleted"
        connection.status_message = "Connection revoked and imported data purged."
    else:
        connection.status = "revoked"
        connection.status_message = "Connection revoked by user."

    connection.updated_at = now

    # Step 5: Write irreversible AuditEventRecord
    payload_hash = hashlib.sha256(
        json.dumps(
            {
                "profile_id": clean_profile_id,
                "connection_id": connection.id,
                "connector_id": connection.connector_id,
                "delete_imported_data": bool(delete_imported_data),
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    audit_record = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=clean_profile_id,
        actor_user_id=actor_user_id,
        principal="user",
        event="connection_revoked",
        tool="revoke_connection",
        risk="irreversible",
        decision="allow",
        payload_hash=payload_hash,
        external_ref=f"connection:{connection.id}",
        detail_redacted=json.dumps({
            "connection_id": connection.id,
            "connector_id": connection.connector_id,
            "status": connection.status,
            "delete_imported_data": bool(delete_imported_data),
            "consents_revoked": consents_revoked,
            "jobs_cancelled": jobs_cancelled,
            "credentials_deleted": credentials_deleted,
            "resources_deleted": resources_deleted,
        }),
    )
    session.add(audit_record)
    await session.commit()
    await session.refresh(connection)

    return {
        "connection_id": connection.id,
        "profile_id": clean_profile_id,
        "connector_id": connection.connector_id,
        "status": connection.status,
        "delete_imported_data": bool(delete_imported_data),
        "consents_revoked": consents_revoked,
        "jobs_cancelled": jobs_cancelled,
        "credentials_deleted": credentials_deleted,
        "resources_deleted": resources_deleted,
    }


async def get_profile_data_flows(
    session: AsyncSession,
    profile_id: str,
) -> Dict[str, Any]:
    """Builds the Settings › Data Flows transparency matrix for `profile_id` (`AU-53`).

    Returns a dictionary containing:
    - `profile_id`: Care profile identifier
    - `model_provider`: Active LLM provider name, host, `base_url`, `is_local`, and local-default policy
    - `search_provider`: Built-in `web_search` provider (`searxng` / `brave`), allowlisted hosts,
      and outbound PHI query sanitiser status (`enabled: True`)
    - `connections`: List of profile connections with their `connector_id`, `status`, consented
      `categories`, `allowed_hosts`, `purpose`, `terms_version`, and `last_sync_at`.
    """
    clean_profile_id = (profile_id or "").strip()
    if not clean_profile_id:
        raise ValueError("profile_id is required.")

    # 1. Resolve active LLM model provider
    model_str = settings.default_model or "ollama:llama3.2"
    base_url = settings.ollama_url or "http://localhost:11434"
    try:
        setting_res = await session.execute(
            select(SystemSetting).where(SystemSetting.key == "llm.default_model")
        )
        setting_obj = setting_res.scalar_one_or_none()
        if setting_obj is not None:
            val = setting_obj.get_value()
            if isinstance(val, str) and val.strip():
                model_str = val.strip()
    except Exception:
        pass

    provider_name = model_str.split(":", 1)[0].strip().lower() if ":" in model_str else "ollama"
    parsed_llm_url = urlparse(base_url if "://" in base_url else f"http://{base_url}")
    llm_host = (parsed_llm_url.hostname or "localhost").lower()
    is_local_llm = provider_name == "ollama" or llm_host in ("localhost", "127.0.0.1")

    model_provider_info: Dict[str, Any] = {
        "provider": provider_name,
        "model": model_str,
        "base_url": base_url,
        "host": llm_host,
        "is_local": is_local_llm,
        "connector_context_policy": "local_default_when_connector_data_in_context",
    }

    # 2. Resolve built-in web_search provider
    search_provider_name = os.getenv("CAREFOLD_SEARCH_PROVIDER", "searxng").strip().lower()
    if search_provider_name not in ("searxng", "brave"):
        search_provider_name = "searxng"

    search_provider_info: Dict[str, Any] = {
        "provider": search_provider_name,
        "allowed_hosts": list(DEFAULT_ALLOWED_SEARCH_HOSTS),
        "phi_sanitiser_enabled": True,
        "outbound_phi_sanitiser": {
            "enabled": True,
            "mode": "fail_closed",
        },
        "status": "enabled",
    }

    # 3. Resolve profile connections & their ConsentGrants
    conn_stmt = (
        select(Connection)
        .where(Connection.profile_id == clean_profile_id)
        .order_by(Connection.created_at.desc())
    )
    conn_res = await session.execute(conn_stmt)
    connections = list(conn_res.scalars().all())

    grant_stmt = (
        select(ConsentGrant)
        .where(ConsentGrant.profile_id == clean_profile_id)
        .order_by(ConsentGrant.granted_at.desc())
    )
    grant_res = await session.execute(grant_stmt)
    grants = list(grant_res.scalars().all())

    grants_by_connection: Dict[str, ConsentGrant] = {}
    grants_by_connector: Dict[str, ConsentGrant] = {}
    for g in grants:
        if g.connection_id and g.connection_id not in grants_by_connection:
            grants_by_connection[g.connection_id] = g
        if g.connector_id not in grants_by_connector:
            grants_by_connector[g.connector_id] = g

    connection_entries: List[Dict[str, Any]] = []
    for conn in connections:
        manifest = get_connector_manifest(conn.connector_id)
        grant = grants_by_connection.get(conn.id) or grants_by_connector.get(conn.connector_id)

        categories = (
            list(grant.categories)
            if grant is not None and grant.categories
            else (list(manifest.categories) if manifest is not None else [])
        )
        allowed_hosts = (
            list(grant.allowed_hosts)
            if grant is not None and grant.allowed_hosts
            else (list(manifest.data_flows.allowed_hosts) if manifest is not None else [])
        )
        scopes = (
            list(grant.scopes)
            if grant is not None and grant.scopes
            else (list(manifest.auth.scopes) if manifest is not None else [])
        )
        purpose = grant.purpose if grant is not None else "sync_and_assist"
        terms_version = grant.terms_version if grant is not None else "1.0.0"
        connector_version = (
            conn.consented_version
            or (grant.connector_version if grant is not None else None)
            or (manifest.version if manifest is not None else "0.1.0")
        )
        trust_level = manifest.trust.trust_level if manifest is not None else "untrusted"

        connection_entries.append({
            "id": conn.id,
            "connection_id": conn.id,
            "connector_id": conn.connector_id,
            "connector_name": manifest.name if manifest is not None else conn.connector_id,
            "label": conn.label or (manifest.name if manifest is not None else conn.connector_id),
            "status": conn.status,
            "categories": categories,
            "scopes": scopes,
            "allowed_hosts": allowed_hosts,
            "purpose": purpose,
            "terms_version": terms_version,
            "connector_version": connector_version,
            "trust_level": trust_level,
            "last_sync_at": conn.last_sync_at.isoformat() if conn.last_sync_at else None,
        })

    return {
        "profile_id": clean_profile_id,
        "model_provider": model_provider_info,
        "search_provider": search_provider_info,
        "connections": connection_entries,
    }


__all__ = [
    "AUTHORIZED_GUARDIAN_ROLES",
    "CONSECUTIVE_FAILURES_DEGRADED_THRESHOLD",
    "REAUTH_ERROR_CODES",
    "UNDER_13_MONTHS",
    "check_scope_and_terms_compatibility",
    "check_under_13_connection_guard",
    "get_connector_manifest",
    "get_profile_data_flows",
    "grant_connector_consent",
    "list_connector_manifests",
    "record_sync_failure",
    "revoke_connection",
    "serialize_connector_manifest",
]
