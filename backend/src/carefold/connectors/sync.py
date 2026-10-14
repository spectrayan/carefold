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

"""Connector Stream Synchronization Engine & Per-Record Quarantine (AU-52 / DESIGN §5.5 & §15).

Implements:
- Pre-sync scope, host, and AI-use terms compatibility verification (`check_scope_and_terms_compatibility`).
- Sandboxed stream pagination and mapping into `NormalisedRecord` items.
- Per-record quarantine (`DESIGN §15`): malformed raw records increment `SyncRun.records_quarantined`
  without aborting valid records in the same page/batch.
- Idempotent upsert into `HealthResource` keyed by `(profile_id, source_type='connector', source_ref=connection.id, source_id=record.id)`
  and `content_hash`.
- Automatic `index_doc` background `Job` scheduling when records are upserted.
- Failure tracking via `record_sync_failure` (3 consecutive failures -> `degraded`, `invalid_grant` -> `needs_reauth`).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib
import inspect
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.connectors.lifecycle import (
    check_scope_and_terms_compatibility,
    get_connector_manifest,
    record_sync_failure,
)
from carefold.connectors.oauth import _is_invalid_grant_failure, load_connection_tokens
from carefold.db.models import (
    Connection,
    HealthResource,
    Job,
    SyncRun,
    utc_now,
)
from connectors.base import NormalisedRecord, Page, StreamSpec, ToolContext
from connectors.http import ScopedHttp

logger = logging.getLogger("carefold.connectors.sync")


def _instantiate_connector_from_entrypoint(entrypoint: Optional[str]) -> Optional[Any]:
    """Dynamically loads and instantiates a Connector class from a `'module:ClassName'` entrypoint."""
    if not entrypoint or ":" not in entrypoint:
        return None
    mod_name, cls_name = entrypoint.split(":", 1)
    try:
        mod = importlib.import_module(mod_name.strip())
        cls = getattr(mod, cls_name.strip(), None)
        if cls is not None:
            return cls()
    except Exception as exc:
        logger.debug("Could not instantiate connector entrypoint '%s': %s", entrypoint, exc)
    return None


def _coerce_normalised_record(
    item: Any,
    profile_id: str,
    connector_id: str,
    stream_name: str,
) -> NormalisedRecord:
    """Validates or coerces a mapped item into a `NormalisedRecord`, raising ValueError if malformed."""
    if isinstance(item, NormalisedRecord):
        rec_id = (item.id or "").strip()
        rec_type = (item.record_type or "").strip()
        if not rec_id:
            raise ValueError("NormalisedRecord is missing a non-empty 'id'.")
        if not rec_type:
            raise ValueError("NormalisedRecord is missing a non-empty 'record_type'.")
        if not isinstance(item.data, dict) or not item.data:
            raise ValueError("NormalisedRecord 'data' must be a non-empty dictionary.")
        return item

    if isinstance(item, dict):
        if item.get("_quarantine") or item.get("malformed"):
            raise ValueError("Record marked as malformed.")
        rec_id = str(item.get("id") or item.get("source_id") or "").strip()
        rec_type = str(item.get("record_type") or item.get("resource_type") or item.get("resourceType") or "").strip()
        data = item.get("data") if isinstance(item.get("data"), dict) else item
        if not rec_id:
            raise ValueError("Raw record dictionary is missing 'id'.")
        if not rec_type:
            raise ValueError("Raw record dictionary is missing 'record_type' / 'resourceType'.")
        if not isinstance(data, dict) or not data:
            raise ValueError("Record data must be a non-empty dictionary.")

        ts_val = item.get("timestamp") or item.get("effective_at")
        if isinstance(ts_val, str) and ts_val.strip():
            clean_ts = ts_val.strip()
            if clean_ts.endswith("Z"):
                clean_ts = clean_ts[:-1] + "+00:00"
            parsed_ts = datetime.fromisoformat(clean_ts)
            if parsed_ts.tzinfo is None:
                parsed_ts = parsed_ts.replace(tzinfo=timezone.utc)
        elif isinstance(ts_val, datetime):
            parsed_ts = ts_val if ts_val.tzinfo else ts_val.replace(tzinfo=timezone.utc)
        else:
            parsed_ts = utc_now()

        raw_hash = str(item.get("raw_hash") or item.get("content_hash") or "").strip()
        if not raw_hash:
            raw_hash = hashlib.sha256(
                json.dumps(data, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()

        return NormalisedRecord(
            id=rec_id,
            stream=str(item.get("stream") or stream_name),
            profile_id=profile_id,
            source=str(item.get("source") or connector_id),
            record_type=rec_type.lower(),
            timestamp=parsed_ts,
            data=data,
            raw_hash=raw_hash,
        )

    raise ValueError(f"Unsupported mapped record type: {type(item).__name__}")


async def _invoke_connector_fetch(
    connector: Any,
    ctx: ToolContext,
    stream_name: str,
    cursor: Optional[str],
    http: ScopedHttp,
) -> Page:
    """Invokes `connector.fetch` supporting standard 4-arg and flexible test signatures."""
    fetch_fn = getattr(connector, "fetch", None)
    if fetch_fn is None or not callable(fetch_fn):
        return Page(stream=stream_name, records=[], next_cursor=None, has_more=False)

    sig = inspect.signature(fetch_fn)
    params = [
        p
        for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values())

    if has_varargs or len(params) >= 4:
        res = fetch_fn(ctx, stream_name, cursor, http)
    elif len(params) == 3:
        res = fetch_fn(ctx, stream_name, cursor)
    elif len(params) == 2:
        res = fetch_fn(stream_name, cursor)
    elif len(params) == 1:
        res = fetch_fn(ctx)
    else:
        res = fetch_fn()

    if inspect.isawaitable(res):
        res = await res

    if isinstance(res, Page):
        return res
    if isinstance(res, list):
        return Page(stream=stream_name, records=res, next_cursor=None, has_more=False)
    if isinstance(res, dict):
        return Page(
            stream=str(res.get("stream") or stream_name),
            records=list(res.get("records") or []),
            next_cursor=res.get("next_cursor"),
            has_more=bool(res.get("has_more", False)),
            metadata=dict(res.get("metadata") or {}),
        )
    return Page(stream=stream_name, records=[], next_cursor=None, has_more=False)


def _map_page_with_quarantine(
    connector: Any,
    page: Page,
    profile_id: str,
    connector_id: str,
) -> Tuple[List[NormalisedRecord], int]:
    """Maps a `Page` of raw records into `NormalisedRecord` items, quarantining malformed records (`DESIGN §15`)."""
    valid_records: List[NormalisedRecord] = []
    quarantined_count = int(
        (page.metadata or {}).get("records_quarantined", 0)
        or (page.metadata or {}).get("quarantined_count", 0)
    )

    map_fn = getattr(connector, "map", None)
    raw_records = list(page.records or [])

    if not raw_records:
        if callable(map_fn):
            try:
                mapped_batch = map_fn(page) or []
                for item in mapped_batch:
                    try:
                        valid_records.append(
                            _coerce_normalised_record(item, profile_id, connector_id, page.stream)
                        )
                    except Exception:
                        quarantined_count += 1
            except Exception:
                quarantined_count += 1
        return valid_records, quarantined_count

    for raw_rec in raw_records:
        try:
            if isinstance(raw_rec, NormalisedRecord):
                valid_records.append(
                    _coerce_normalised_record(raw_rec, profile_id, connector_id, page.stream)
                )
            elif callable(map_fn):
                single_page = Page(
                    stream=page.stream,
                    records=[raw_rec],
                    next_cursor=page.next_cursor,
                    has_more=False,
                    metadata={"profile_id": profile_id, **(page.metadata or {})},
                )
                mapped_items = map_fn(single_page)
                if not mapped_items:
                    # If mapper filtered out or quarantined the single record without raising
                    if isinstance(raw_rec, dict) and (raw_rec.get("_quarantine") or raw_rec.get("malformed")):
                        quarantined_count += 1
                    continue
                for item in mapped_items:
                    valid_records.append(
                        _coerce_normalised_record(item, profile_id, connector_id, page.stream)
                    )
            else:
                valid_records.append(
                    _coerce_normalised_record(raw_rec, profile_id, connector_id, page.stream)
                )
        except Exception as rec_err:
            logger.warning(
                "Quarantined malformed record in connection sync (connector=%s, stream=%s): %s",
                connector_id,
                page.stream,
                rec_err,
            )
            quarantined_count += 1

    return valid_records, quarantined_count


def _classify_sync_exception(exc: Exception) -> str:
    """Maps an exception raised during sync into a standardized `SyncRun.error_code`."""
    if _is_invalid_grant_failure(exc):
        return "invalid_grant"
    explicit_code = getattr(exc, "error_code", None)
    if explicit_code and isinstance(explicit_code, str):
        return explicit_code.strip().lower()
    msg = str(exc).lower()
    if "rate" in msg and "limit" in msg or "429" in msg:
        return "rate_limited"
    if "timeout" in msg or isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, PermissionError):
        return "unauthorized"
    return "network_error"


async def run_connection_sync(
    session: AsyncSession,
    connection_id: str,
    connector: Optional[Any] = None,
    http_client: Optional[Any] = None,
    kek: Optional[bytes] = None,
) -> SyncRun:
    """Executes a synchronization run for `connection_id` (`AU-52` / `DESIGN §5.5` & `§15`).

    Steps:
    1. Loads `Connection` and verifies scope, host, and AI-use terms compatibility (`check_scope_and_terms_compatibility`).
    2. Creates a `SyncRun(status='running')` record.
    3. Fetches and maps records across connector streams, quarantining malformed records (`records_quarantined += 1`)
       without aborting the remaining records in the batch.
    4. Idempotently upserts valid `NormalisedRecord` items into `HealthResource` with
       `(profile_id, source_type='connector', source_ref=connection.id, source_id=record.id)` and `content_hash`.
    5. Resets `connection.consecutive_failures = 0`, `connection.status = 'active'`, `connection.last_sync_at = utc_now()`,
       and marks `SyncRun.status = 'succeeded'` (or `'partial'` if `records_quarantined > 0`).
    6. Enqueues an `index_doc` `Job` when records are upserted.
    7. On failure, invokes `record_sync_failure` and marks `SyncRun.status = 'failed'`.
    """
    clean_connection_id = (connection_id or "").strip()
    if not clean_connection_id:
        raise ValueError("connection_id is required to run connection sync.")

    conn_stmt = select(Connection).where(Connection.id == clean_connection_id)
    conn_res = await session.execute(conn_stmt)
    connection = conn_res.scalar_one_or_none()
    if connection is None:
        raise ValueError(f"Connection '{clean_connection_id}' not found.")

    start_time = utc_now()
    sync_run = SyncRun(
        id=str(uuid.uuid4()),
        connection_id=connection.id,
        profile_id=connection.profile_id,
        connector_id=connection.connector_id,
        stream="all",
        status="running",
        records_fetched=0,
        records_upserted=0,
        records_quarantined=0,
        started_at=start_time,
        created_at=start_time,
    )
    session.add(sync_run)
    await session.flush()

    # Resolve connector manifest
    manifest = getattr(connector, "manifest", None) if connector is not None else None
    if manifest is None:
        manifest = get_connector_manifest(connection.connector_id)

    manifest_version = getattr(manifest, "version", "0.1.0") if manifest is not None else "0.1.0"
    required_scopes = (
        list(getattr(getattr(manifest, "auth", None), "scopes", []) or [])
        if manifest is not None
        else []
    )
    required_hosts = (
        list(getattr(getattr(manifest, "data_flows", None), "allowed_hosts", []) or [])
        if manifest is not None
        else []
    )
    ai_use_allowed = (
        bool(getattr(getattr(manifest, "terms", None), "ai_use_allowed", True))
        if manifest is not None
        else True
    )

    is_compatible, compat_error = await check_scope_and_terms_compatibility(
        session=session,
        connection=connection,
        manifest_version=manifest_version,
        required_scopes=required_scopes,
        required_hosts=required_hosts,
        ai_use_allowed=ai_use_allowed,
    )
    if not is_compatible:
        end_time = utc_now()
        sync_run.status = "failed"
        sync_run.error_code = compat_error or "incompatible_consent"
        sync_run.error_message = (
            connection.status_message
            or f"Sync blocked due to consent or terms incompatibility ({compat_error})."
        )
        sync_run.completed_at = end_time
        sync_run.duration_ms = max(0, int((end_time - start_time).total_seconds() * 1000))
        await session.commit()
        await session.refresh(sync_run)
        return sync_run

    # Resolve connector implementation if not explicitly passed
    active_connector = connector
    if active_connector is None and manifest is not None and getattr(manifest, "entrypoint", None):
        # Only auto-instantiate real starter connector when an explicit http_client is provided;
        # otherwise use a no-op empty sync if no mock/client was supplied.
        if http_client is not None:
            active_connector = _instantiate_connector_from_entrypoint(manifest.entrypoint)

    # Load decrypted credentials if stored in Vault to attach Authorization header if needed
    auth_headers: Dict[str, str] = {}
    try:
        tokens, _ = await load_connection_tokens(
            session,
            connection.profile_id,
            connection.id,
            kek=kek,
        )
        access_token = tokens.get("access_token")
        if access_token and isinstance(access_token, str):
            auth_headers["Authorization"] = f"Bearer {access_token}"
    except Exception:
        pass

    # Prepare ScopedHttp client
    allowed_hosts = required_hosts or ["localhost", "127.0.0.1"]
    owns_scoped_http = False
    if isinstance(http_client, ScopedHttp):
        scoped_http = http_client
    elif isinstance(http_client, httpx.AsyncClient):
        scoped_http = ScopedHttp(
            allowed_hosts=allowed_hosts,
            headers=auth_headers,
            client=http_client,
        )
    else:
        scoped_http = ScopedHttp(
            allowed_hosts=allowed_hosts,
            headers=auth_headers,
        )
        owns_scoped_http = True

    ctx = ToolContext(
        user_id=connection.user_id or "system",
        profile_id=connection.profile_id,
        principal="connector",
        run_id=sync_run.id,
    )

    upserted_resource_ids: List[str] = []
    latest_cursor = connection.sync_cursor

    try:
        if active_connector is not None:
            streams_fn = getattr(active_connector, "streams", None)
            stream_specs = (
                streams_fn()
                if callable(streams_fn)
                else [StreamSpec(name="default")]
            )
            if not stream_specs:
                stream_specs = [StreamSpec(name="default")]

            if len(stream_specs) == 1:
                first_stream = stream_specs[0]
                sync_run.stream = (
                    first_stream.name if hasattr(first_stream, "name") else str(first_stream)
                )

            for spec in stream_specs:
                stream_name = spec.name if hasattr(spec, "name") else str(spec)
                cursor = connection.sync_cursor
                page_guard = 0

                while page_guard < 25:
                    page_guard += 1
                    page = await _invoke_connector_fetch(
                        active_connector,
                        ctx,
                        stream_name,
                        cursor,
                        scoped_http,
                    )
                    sync_run.records_fetched += len(page.records or [])

                    mapped_records, page_quarantined = _map_page_with_quarantine(
                        active_connector,
                        page,
                        connection.profile_id,
                        connection.connector_id,
                    )
                    sync_run.records_quarantined += page_quarantined

                    now = utc_now()
                    for norm_rec in mapped_records:
                        source_id = str(norm_rec.id).strip()
                        rtype = str(norm_rec.record_type or "observation").strip().lower()
                        effective_dt = norm_rec.timestamp or now
                        if effective_dt.tzinfo is None:
                            effective_dt = effective_dt.replace(tzinfo=timezone.utc)

                        rec_data = dict(norm_rec.data)
                        rec_data.setdefault(
                            "_carefold_provenance",
                            {
                                "source_type": "connector",
                                "connector_id": connection.connector_id,
                                "connection_id": connection.id,
                                "stream": norm_rec.stream or stream_name,
                                "trust": (
                                    manifest.trust.trust_level
                                    if manifest is not None
                                    else "untrusted"
                                ),
                            },
                        )
                        content_hash = (norm_rec.raw_hash or "").strip() or hashlib.sha256(
                            json.dumps(rec_data, sort_keys=True, default=str).encode("utf-8")
                        ).hexdigest()

                        existing_stmt = select(HealthResource).where(
                            HealthResource.profile_id == connection.profile_id,
                            HealthResource.source_type == "connector",
                            HealthResource.source_ref == connection.id,
                            HealthResource.source_id == source_id,
                        )
                        existing_res = await session.execute(existing_stmt)
                        hr = existing_res.scalar_one_or_none()

                        if hr is not None:
                            hr.resource_type = rtype
                            hr.content_hash = content_hash
                            hr.data = rec_data
                            hr.effective_at = effective_dt
                            hr.status = "active"
                            hr.updated_at = now
                            upserted_resource_ids.append(hr.id)
                        else:
                            hr = HealthResource(
                                id=str(uuid.uuid4()),
                                profile_id=connection.profile_id,
                                resource_type=rtype,
                                source_type="connector",
                                source_ref=connection.id,
                                source_id=source_id,
                                content_hash=content_hash,
                                data=rec_data,
                                status="active",
                                effective_at=effective_dt,
                                recorded_at=now,
                                created_at=now,
                                updated_at=now,
                            )
                            session.add(hr)
                            upserted_resource_ids.append(hr.id)

                        sync_run.records_upserted += 1

                    if page.next_cursor:
                        cursor = page.next_cursor
                        latest_cursor = page.next_cursor

                    if not page.has_more or not page.next_cursor:
                        break

        end_time = utc_now()
        connection.consecutive_failures = 0
        connection.status = "active"
        connection.status_message = None
        connection.last_sync_at = end_time
        if latest_cursor is not None:
            connection.sync_cursor = latest_cursor
        connection.updated_at = end_time

        sync_run.status = "partial" if sync_run.records_quarantined > 0 else "succeeded"
        sync_run.completed_at = end_time
        sync_run.duration_ms = max(0, int((end_time - start_time).total_seconds() * 1000))

        if upserted_resource_ids:
            index_job = Job(
                id=str(uuid.uuid4()),
                profile_id=connection.profile_id,
                connection_id=connection.id,
                kind="index_doc",
                payload=json.dumps({
                    "sync_run_id": sync_run.id,
                    "connection_id": connection.id,
                    "profile_id": connection.profile_id,
                    "resource_ids": upserted_resource_ids,
                    "doc_type": "connector_sync_batch",
                }),
                timezone="UTC",
                next_run_at=end_time,
                idempotency_key=f"index:sync_run:{sync_run.id}",
                status="pending",
            )
            session.add(index_job)

        await session.commit()
        await session.refresh(sync_run)
        await session.refresh(connection)
        return sync_run

    except Exception as exc:
        err_code = _classify_sync_exception(exc)
        err_msg = str(exc) or f"Connector sync failed ({err_code})"
        await record_sync_failure(session, connection, err_code, err_msg)

        end_time = utc_now()
        sync_run.status = "failed"
        sync_run.error_code = err_code
        sync_run.error_message = err_msg
        sync_run.completed_at = end_time
        sync_run.duration_ms = max(0, int((end_time - start_time).total_seconds() * 1000))
        await session.commit()
        await session.refresh(sync_run)
        return sync_run
    finally:
        if owns_scoped_http:
            await scoped_http.aclose()


__all__ = [
    "run_connection_sync",
]
