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

"""REST API endpoints for External Connections, OAuth 2.0 PKCE Broker, Sync Health, and Data Flows (AU-51, AU-52, AU-53)."""

from __future__ import annotations

import json
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, get_db, resolve_owner_user_id
from carefold.api.profiles import get_user_profile_access
from carefold.auth.ports import UserProfile
from carefold.connectors.lifecycle import (
    check_under_13_connection_guard,
    get_connector_manifest,
    get_profile_data_flows,
    grant_connector_consent,
    list_connector_manifests,
    revoke_connection,
    serialize_connector_manifest,
)
from carefold.connectors.oauth import (
    build_authorization_url,
    create_oauth_state,
    generate_pkce_pair,
    resolve_oauth_kek,
    resolve_redirect_uri,
    store_connection_tokens,
    verify_oauth_state,
)
from carefold.connectors.sync import run_connection_sync
from carefold.db.models import (
    Connection,
    ConsentGrant,
    Job,
    Profile,
    SyncRun,
    utc_now,
)
from carefold.logging import get_logger
from carefold.vault import get_kek

logger = get_logger("carefold.api.connections")

router = APIRouter(tags=["connections"])


# ============================================================================
# Section 1: Pydantic Request / Response Schemas
# ============================================================================


class CreateConnectionRequest(BaseModel):
    """Request payload for creating a profile connection and consent grant."""

    connector_id: str = Field(..., min_length=1, max_length=128, description="Connector manifest ID")
    label: Optional[str] = Field(None, max_length=255, description="Optional human-readable label")
    categories: Optional[List[str]] = Field(None, description="Consented data categories")
    scopes: Optional[List[str]] = Field(None, description="Consented OAuth/API scopes")
    allowed_hosts: Optional[List[str]] = Field(None, description="Consented outbound network hosts")
    purpose: str = Field("sync_and_assist", max_length=64, description="Consent purpose")
    terms_version: str = Field("1.0.0", max_length=32, description="Terms version string")
    client_id: Optional[str] = Field(None, max_length=255, description="Optional BYO OAuth client ID")
    client_secret: Optional[str] = Field(None, max_length=512, description="Optional BYO OAuth client secret")
    redirect_uri: Optional[str] = Field(None, max_length=512, description="Optional explicit redirect URI")
    deployment_mode: str = Field("local", description="Deployment mode ('local' or 'server')")
    external_base_url: Optional[str] = Field(None, description="HTTPS external base URL in server mode")
    initial_tokens: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional initial token or Basic/API key credentials to store immediately in Vault",
    )
    config: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional non-secret connector configuration dictionary",
    )


class OAuthCallbackRequest(BaseModel):
    """Request payload for completing an OAuth 2.0 PKCE callback."""

    code: str = Field(..., min_length=1, description="Authorization code from OAuth provider")
    state: str = Field(..., min_length=1, description="Signed HMAC state token")
    code_verifier: Optional[str] = Field(None, description="Optional explicit PKCE code_verifier")
    token_payload: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional exchanged token payload (access_token, refresh_token, expires_in)",
    )


class RevokeConnectionRequest(BaseModel):
    """Request payload for executing the 4-step revoke cascade."""

    delete_imported_data: bool = Field(
        False,
        description="When True, also deletes imported HealthResource records from this connection",
    )


# ============================================================================
# Section 2: Serialization Helpers
# ============================================================================


def _serialize_sync_run(run: SyncRun) -> Dict[str, Any]:
    """Serializes a `SyncRun` ORM record to a JSON dictionary."""
    return {
        "id": run.id,
        "connection_id": run.connection_id,
        "profile_id": run.profile_id,
        "connector_id": run.connector_id,
        "stream": run.stream,
        "status": run.status,
        "records_fetched": run.records_fetched,
        "records_upserted": run.records_upserted,
        "records_quarantined": run.records_quarantined,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "duration_ms": run.duration_ms,
    }


def _serialize_connection(
    conn: Connection,
    latest_sync_run: Optional[SyncRun] = None,
) -> Dict[str, Any]:
    """Serializes a `Connection` ORM record to a JSON dictionary."""
    manifest = get_connector_manifest(conn.connector_id)
    default_label = manifest.name if manifest is not None else conn.connector_id
    return {
        "id": conn.id,
        "profile_id": conn.profile_id,
        "connector_id": conn.connector_id,
        "label": conn.label or default_label,
        "status": conn.status,
        "status_message": conn.status_message,
        "consecutive_failures": int(conn.consecutive_failures or 0),
        "consented_version": conn.consented_version or (manifest.version if manifest else "0.1.0"),
        "last_sync_at": conn.last_sync_at.isoformat() if conn.last_sync_at else None,
        "created_at": conn.created_at.isoformat() if conn.created_at else None,
        "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
        "latest_sync_run": _serialize_sync_run(latest_sync_run) if latest_sync_run is not None else None,
    }


def _serialize_consent_grant(grant: ConsentGrant) -> Dict[str, Any]:
    """Serializes a `ConsentGrant` ORM record to a JSON dictionary."""
    return {
        "id": grant.id,
        "profile_id": grant.profile_id,
        "connection_id": grant.connection_id or "",
        "connector_id": grant.connector_id,
        "categories": list(grant.categories),
        "scopes": list(grant.scopes),
        "allowed_hosts": list(grant.allowed_hosts),
        "purpose": grant.purpose,
        "terms_version": grant.terms_version,
        "connector_version": grant.connector_version,
        "status": grant.status,
        "granted_at": grant.granted_at.isoformat() if grant.granted_at else None,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
    }


# ============================================================================
# Section 3: Profile Access Dependency
# ============================================================================


def require_profile_access(
    required_access: Literal["manage", "view_clinical"] = "view_clinical",
) -> Callable[..., Coroutine[Any, Any, Profile]]:
    """FastAPI dependency enforcing profile-scoped clinical/management permissions."""

    async def _dependency(
        profile_id: str,
        user: UserProfile = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> Profile:
        clean_id = (profile_id or "").strip()
        if not clean_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="profile_id path parameter is required.",
            )

        stmt = select(Profile).where(Profile.id == clean_id)
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile '{clean_id}' not found.",
            )

        access = await get_user_profile_access(profile, user, db)
        if access is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: you do not have permission for this profile.",
            )

        if required_access == "manage" and access != "manage":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: management permissions required to modify connections.",
            )

        if required_access == "view_clinical" and access not in ("manage", "view_clinical"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: clinical view permissions required to inspect connections.",
            )

        return profile

    return _dependency


# ============================================================================
# Section 4: REST Endpoints
# ============================================================================


@router.get(
    "/connectors/catalog",
    summary="List starter connector manifests in the catalog",
)
@router.get(
    "/connectors",
    include_in_schema=False,
)
async def get_connectors_catalog(
    _user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Returns all starter connector manifests (`withings`, `google-calendar`, `caldav`, `epic-smart`)."""
    manifests = [serialize_connector_manifest(m) for m in list_connector_manifests()]
    return {
        "connectors": manifests,
        "items": manifests,
        "total": len(manifests),
    }


@router.get(
    "/profiles/{profile_id}/connections",
    summary="List external connections for a care profile with latest sync status",
)
async def list_profile_connections(
    profile_id: str,
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Lists all `Connection` rows for `profile_id` with their most recent `SyncRun` telemetry."""
    stmt = (
        select(Connection)
        .where(
            Connection.profile_id == profile.id,
            Connection.status != "deleted",
        )
        .order_by(Connection.created_at.desc())
    )
    res = await db.execute(stmt)
    connections = list(res.scalars().all())

    serialized_list: List[Dict[str, Any]] = []
    for conn in connections:
        run_stmt = (
            select(SyncRun)
            .where(SyncRun.connection_id == conn.id)
            .order_by(SyncRun.started_at.desc())
            .limit(1)
        )
        run_res = await db.execute(run_stmt)
        latest_run = run_res.scalar_one_or_none()
        serialized_list.append(_serialize_connection(conn, latest_sync_run=latest_run))

    return {
        "connections": serialized_list,
        "items": serialized_list,
        "total": len(serialized_list),
    }


@router.post(
    "/profiles/{profile_id}/connections",
    status_code=status.HTTP_201_CREATED,
    summary="Create a profile connection, record granular consent, and initiate OAuth PKCE flow",
)
async def create_profile_connection(
    profile_id: str,
    payload: CreateConnectionRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Creates a `Connection` + `ConsentGrant`, schedules a recurring `sync` `Job` (at most 1 per connection),
    and returns the OAuth 2.0 PKCE authorization URL and signed `state`.
    """
    user_role = getattr(user, "role", None) or "steward"
    try:
        check_under_13_connection_guard(profile, user_role)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    manifest = get_connector_manifest(payload.connector_id)
    connector_version = manifest.version if manifest is not None else "0.1.0"
    default_categories = list(manifest.categories) if manifest is not None else ["general"]
    default_scopes = list(manifest.auth.scopes) if manifest is not None else []
    default_hosts = list(manifest.data_flows.allowed_hosts) if manifest is not None else []
    default_label = manifest.name if manifest is not None else payload.connector_id

    consented_categories = payload.categories if payload.categories is not None else default_categories
    consented_scopes = payload.scopes if payload.scopes is not None else default_scopes
    consented_hosts = payload.allowed_hosts if payload.allowed_hosts is not None else default_hosts

    owner_id = resolve_owner_user_id(user) or profile.user_id or getattr(user, "id", "local-steward")
    now = utc_now()

    config_data: Dict[str, Any] = dict(payload.config or {})
    if payload.client_id:
        config_data["client_id"] = payload.client_id

    connection = Connection(
        id=str(uuid.uuid4()),
        user_id=owner_id,
        profile_id=profile.id,
        connector_id=payload.connector_id.strip(),
        status="pending_auth",
        label=(payload.label or default_label).strip(),
        consented_version=connector_version,
        consecutive_failures=0,
        config_json=json.dumps(config_data),
        created_at=now,
        updated_at=now,
    )
    db.add(connection)
    await db.flush()

    grant = await grant_connector_consent(
        session=db,
        profile_id=profile.id,
        connector_id=connection.connector_id,
        categories=consented_categories,
        scopes=consented_scopes,
        allowed_hosts=consented_hosts,
        granted_by_user_id=owner_id if owner_id != "local-steward" else None,
        connection_id=connection.id,
        purpose=payload.purpose,
        terms_version=payload.terms_version,
        connector_version=connector_version,
    )

    # Optionally store BYO client_secret or initial_tokens in Vault
    vault_payload: Dict[str, Any] = {}
    if payload.client_id:
        vault_payload["client_id"] = payload.client_id
    if payload.client_secret:
        vault_payload["client_secret"] = payload.client_secret
    if payload.initial_tokens and isinstance(payload.initial_tokens, dict):
        vault_payload.update(payload.initial_tokens)

    if vault_payload:
        await store_connection_tokens(
            session=db,
            profile_id=profile.id,
            connection_id=connection.id,
            user_id=owner_id if owner_id != "local-steward" else None,
            token_payload=vault_payload,
        )
        # If only client_secret was provided (no access_token/password yet) for OAuth2, keep pending_auth
        if (
            manifest is not None
            and manifest.auth.type == "oauth2"
            and not (payload.initial_tokens and payload.initial_tokens.get("access_token"))
        ):
            connection.status = "pending_auth"
            await db.commit()

    # Schedule recurring sync Job (ensuring at most 1 active sync job per connection)
    existing_job_stmt = select(Job).where(
        Job.profile_id == profile.id,
        Job.connection_id == connection.id,
        Job.kind == "sync",
        Job.status.in_(("pending", "active")),
    )
    existing_job_res = await db.execute(existing_job_stmt)
    existing_job = existing_job_res.scalars().first()
    if existing_job is None:
        sync_job = Job(
            id=str(uuid.uuid4()),
            profile_id=profile.id,
            connection_id=connection.id,
            kind="sync",
            payload=json.dumps({
                "connection_id": connection.id,
                "connector_id": connection.connector_id,
                "profile_id": profile.id,
            }),
            timezone="UTC",
            rrule="FREQ=HOURLY;INTERVAL=6",
            next_run_at=now,
            idempotency_key=f"sync:connection:{connection.id}",
            status="pending",
            created_at=now,
            updated_at=now,
        )
        db.add(sync_job)
        await db.commit()

    # Build OAuth 2.0 PKCE state & authorization URL if OAuth2 connector
    authorization_url: Optional[str] = None
    state_token: Optional[str] = None
    code_verifier: Optional[str] = None
    redirect_uri: Optional[str] = None

    if manifest is None or manifest.auth.type == "oauth2":
        try:
            redirect_uri = payload.redirect_uri or resolve_redirect_uri(
                deployment_mode=payload.deployment_mode,
                external_base_url=payload.external_base_url,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        code_verifier, code_challenge = generate_pkce_pair()
        state_token = create_oauth_state(
            user_id=str(owner_id),
            profile_id=profile.id,
            connection_id=connection.id,
            code_verifier=code_verifier,
            secret_key=resolve_oauth_kek(),
        )
        auth_endpoint = (
            manifest.auth.authorization_url
            if manifest is not None and manifest.auth.authorization_url
            else "https://localhost/oauth2/authorize"
        )
        authorization_url = build_authorization_url(
            authorization_endpoint=auth_endpoint,
            client_id=payload.client_id or f"carefold-{connection.connector_id}",
            redirect_uri=redirect_uri,
            state=state_token,
            code_challenge=code_challenge,
            scopes=consented_scopes,
        )

    await db.refresh(connection)
    serialized_conn = _serialize_connection(connection)
    serialized_grant = _serialize_consent_grant(grant)

    return {
        "id": connection.id,
        "status": connection.status,
        "connection": serialized_conn,
        "consent_grant": serialized_grant,
        "authorization_url": authorization_url,
        "state": state_token,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
    }


@router.post(
    "/profiles/{profile_id}/connections/{connection_id}/oauth-callback",
    summary="Complete OAuth 2.0 PKCE callback, store tokens in Vault, and activate connection",
)
@router.post(
    "/profiles/{profile_id}/connections/{connection_id}/oauth/callback",
    include_in_schema=False,
)
async def complete_connection_oauth_callback(
    profile_id: str,
    connection_id: str,
    payload: OAuthCallbackRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Verifies the HMAC-signed PKCE `state` token, stores tokens in Vault, and activates the connection."""
    conn_stmt = select(Connection).where(
        Connection.id == connection_id.strip(),
        Connection.profile_id == profile.id,
    )
    conn_res = await db.execute(conn_stmt)
    connection = conn_res.scalar_one_or_none()
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{connection_id}' not found for profile '{profile.id}'.",
        )

    owner_id = resolve_owner_user_id(user) or profile.user_id or getattr(user, "id", "local-steward")
    try:
        state_data = verify_oauth_state(
            state_token=payload.state,
            secret_key=resolve_oauth_kek(),
            expected_user_id=str(owner_id),
            expected_profile_id=profile.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if state_data.get("connection_id") != connection.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state connection_id does not match the target connection.",
        )

    token_data: Dict[str, Any] = dict(payload.token_payload or {})
    if not token_data.get("access_token"):
        token_data["access_token"] = f"oauth_access_{payload.code}"
    token_data.setdefault("refresh_token", f"oauth_refresh_{payload.code}")
    token_data.setdefault("token_type", "Bearer")
    token_data["code_verifier"] = payload.code_verifier or state_data.get("code_verifier")

    await store_connection_tokens(
        session=db,
        profile_id=profile.id,
        connection_id=connection.id,
        user_id=owner_id if owner_id != "local-steward" else None,
        token_payload=token_data,
    )
    await db.refresh(connection)
    serialized_conn = _serialize_connection(connection)
    return {
        "id": connection.id,
        "status": connection.status,
        "connection": serialized_conn,
    }


@router.post(
    "/profiles/{profile_id}/connections/{connection_id}/sync",
    summary="Trigger an immediate synchronization run for a connection",
)
async def trigger_profile_connection_sync(
    profile_id: str,
    connection_id: str,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Triggers `run_connection_sync` for `(profile_id, connection_id)` and returns the `SyncRun` summary."""
    conn_stmt = select(Connection).where(
        Connection.id == connection_id.strip(),
        Connection.profile_id == profile.id,
    )
    conn_res = await db.execute(conn_stmt)
    connection = conn_res.scalar_one_or_none()
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{connection_id}' not found for profile '{profile.id}'.",
        )

    sync_run = await run_connection_sync(session=db, connection_id=connection.id)
    await db.refresh(connection)
    serialized_run = _serialize_sync_run(sync_run)
    serialized_conn = _serialize_connection(connection, latest_sync_run=sync_run)

    return {
        **serialized_run,
        "sync_run": serialized_run,
        "connection": serialized_conn,
    }


@router.get(
    "/profiles/{profile_id}/connections/{connection_id}/sync-runs",
    summary="List synchronization run telemetry history for a connection",
)
async def list_connection_sync_runs(
    profile_id: str,
    connection_id: str,
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Returns `SyncRun` history for `(profile_id, connection_id)` ordered by `started_at` descending (`AU-52`)."""
    conn_stmt = select(Connection).where(
        Connection.id == connection_id.strip(),
        Connection.profile_id == profile.id,
    )
    conn_res = await db.execute(conn_stmt)
    connection = conn_res.scalar_one_or_none()
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{connection_id}' not found for profile '{profile.id}'.",
        )

    stmt = (
        select(SyncRun)
        .where(
            SyncRun.connection_id == connection.id,
            SyncRun.profile_id == profile.id,
        )
        .order_by(SyncRun.started_at.desc())
    )
    res = await db.execute(stmt)
    runs = [_serialize_sync_run(r) for r in res.scalars().all()]
    return {
        "sync_runs": runs,
        "items": runs,
        "total": len(runs),
    }


@router.post(
    "/profiles/{profile_id}/connections/{connection_id}/revoke",
    summary="Execute the 4-step revoke cascade for a connection",
)
async def revoke_profile_connection(
    profile_id: str,
    connection_id: str,
    payload: Optional[RevokeConnectionRequest] = Body(default=None),
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Runs the 4-step `revoke_connection` cascade (`Titan S2`)."""
    delete_imported = bool(payload.delete_imported_data) if payload is not None else False
    owner_id = resolve_owner_user_id(user) or profile.user_id

    try:
        result = await revoke_connection(
            session=db,
            profile_id=profile.id,
            connection_id=connection_id.strip(),
            actor_user_id=owner_id,
            delete_imported_data=delete_imported,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return {
        **result,
        "deleted_records_count": result["resources_deleted"],
    }


@router.get(
    "/profiles/{profile_id}/consents",
    summary="List granular connector consent grants for a care profile",
)
async def list_profile_consents(
    profile_id: str,
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Lists all `ConsentGrant` records for `profile_id` (`AU-53`)."""
    stmt = (
        select(ConsentGrant)
        .where(ConsentGrant.profile_id == profile.id)
        .order_by(ConsentGrant.granted_at.desc())
    )
    res = await db.execute(stmt)
    items = [_serialize_consent_grant(g) for g in res.scalars().all()]
    return {
        "consents": items,
        "items": items,
        "total": len(items),
    }


@router.get(
    "/profiles/{profile_id}/data-flows",
    summary="Get Settings › Data Flows outbound network and privacy transparency matrix",
)
async def get_profile_data_flows_endpoint(
    profile_id: str,
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Returns the Settings › Data Flows inventory (`model_provider`, `search_provider`, `connections`) (`AU-53`)."""
    return await get_profile_data_flows(db, profile.id)
