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

"""Curated Remote MCP Bridge with Schema-Hash Pinning and Untrusted Taint Wrapping (AU-57 / DESIGN §6 / Titan S7).

Enforces:
- Remote HTTPS MCP transport only (local `stdio://`, `file://`, and shell transports are forbidden).
- Explicit per-tool allowlisting (`manifest.mcp_tools`); un-allowlisted remote tools are ignored.
- Canonical SHA-256 schema-hash pinning (`McpToolPin`) on `(name, description, input_schema)`.
- Automatic drift blocking (`McpSchemaDriftError`), `Connection.status = 'needs_reauth'`, and audit logging
  when an upstream MCP server mutates a tool's description or input schema.
- Wrapping curated MCP tools as `ToolSpec` with `trust='untrusted'` and `UntrustedResult` output tainting
  so remote MCP tools are never bound directly to the model outside `execute_tool_call`.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.db.models import (
    AuditEventRecord,
    Connection,
    McpToolPin,
    utc_now,
)
from carefold.engine.tool_exec import TaintFlag, UntrustedResult
from carefold.engine.tool_registry import ToolSpec
from connectors.manifest import ConnectorManifest, McpToolAllowlistEntry

CURATED_REMOTE_MCP_IDS = ("google-workspace-gmail",)


class McpSchemaDriftError(PermissionError):
    """Raised when a remote MCP tool's live schema or description diverges from its pinned SHA-256 hash."""


def compute_mcp_schema_hash(
    name: str,
    description: str,
    input_schema: Dict[str, Any],
) -> str:
    """Computes the canonical SHA-256 schema hash over `(name, description.strip(), input_schema)`."""
    canonical_payload = json.dumps(
        {
            "name": str(name).strip(),
            "description": str(description or "").strip(),
            "input_schema": input_schema if isinstance(input_schema, dict) else {},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


def validate_curated_mcp_manifest(manifest: ConnectorManifest) -> None:
    """Validates that a `ConnectorManifest` is a curated remote HTTPS MCP manifest (`AU-57`).

    Raises:
        ValueError: If `kind != 'mcp'`, if a local `stdio`/`file`/`shell` transport is used,
            if `mcp_endpoint` does not use `https://`, or if its hostname is not in
            `manifest.data_flows.allowed_hosts`.
    """
    if getattr(manifest, "kind", "rest") != "mcp":
        raise ValueError(f"Connector '{manifest.id}' is not an MCP manifest (kind='{manifest.kind}').")

    entrypoint = str(getattr(manifest, "entrypoint", "") or "").strip().lower()
    if any(tok in entrypoint for tok in ("stdio", "subprocess", "shell", "local_mcp")):
        raise ValueError("Local stdio or shell MCP entrypoints are forbidden in Carefold.")

    endpoint = str(getattr(manifest, "mcp_endpoint", "") or "").strip()
    if not endpoint:
        raise ValueError(f"MCP connector '{manifest.id}' must declare a non-empty mcp_endpoint.")

    lower_ep = endpoint.lower()
    if lower_ep.startswith(("stdio:", "file:", "shell:", "ws:")):
        raise ValueError("Local stdio or file MCP transports are forbidden; curated remote MCP requires HTTPS.")

    if not lower_ep.startswith("https://"):
        raise ValueError(f"Curated remote MCP endpoint '{endpoint}' must start with 'https://'.")

    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError(f"Curated remote MCP endpoint '{endpoint}' must include a valid hostname.")

    allowed_hosts = {
        h.strip().lower()
        for h in (manifest.data_flows.allowed_hosts or [])
        if h and h.strip()
    }
    if host not in allowed_hosts:
        raise ValueError(
            f"MCP endpoint host '{host}' must be declared in manifest.data_flows.allowed_hosts."
        )


async def pin_mcp_tools(
    session: AsyncSession,
    profile_id: str,
    connection_id: str,
    manifest: ConnectorManifest,
    live_tool_schemas: Optional[List[Dict[str, Any]]] = None,
) -> List[McpToolPin]:
    """Pins each allowlisted tool in `manifest.mcp_tools` into `McpToolPin` (`status='pinned'`).

    Any un-allowlisted tools present in `live_tool_schemas` from the remote MCP server are strictly ignored.
    """
    validate_curated_mcp_manifest(manifest)

    clean_profile_id = (profile_id or "").strip()
    clean_connection_id = (connection_id or "").strip()
    if not clean_profile_id or not clean_connection_id:
        raise ValueError("profile_id and connection_id are required to pin MCP tools.")

    live_by_name: Dict[str, Dict[str, Any]] = {}
    if live_tool_schemas:
        for item in live_tool_schemas:
            if isinstance(item, dict) and item.get("name"):
                live_by_name[str(item["name"]).strip()] = item

    now = utc_now()
    pinned_records: List[McpToolPin] = []

    for entry in manifest.mcp_tools:
        live_item = live_by_name.get(entry.name)
        if live_item is not None:
            desc = str(live_item.get("description", entry.description) or "")
            raw_schema = (
                live_item.get("input_schema")
                if "input_schema" in live_item
                else live_item.get("inputSchema", entry.input_schema)
            )
            schema_dict = dict(raw_schema) if isinstance(raw_schema, dict) else dict(entry.input_schema)
        else:
            desc = entry.description
            schema_dict = dict(entry.input_schema)

        schema_hash = compute_mcp_schema_hash(entry.name, desc, schema_dict)
        schema_json = json.dumps(
            {
                "name": entry.name,
                "description": desc.strip(),
                "input_schema": schema_dict,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        stmt = select(McpToolPin).where(
            McpToolPin.connection_id == clean_connection_id,
            McpToolPin.tool_name == entry.name,
        )
        res = await session.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing is not None:
            existing.profile_id = clean_profile_id
            existing.risk_tier = entry.risk_tier
            existing.schema_hash = schema_hash
            existing.schema_json = schema_json
            existing.status = "pinned"
            existing.pinned_at = now
            existing.verified_at = now
            pin = existing
        else:
            pin = McpToolPin(
                id=str(uuid.uuid4()),
                profile_id=clean_profile_id,
                connection_id=clean_connection_id,
                tool_name=entry.name,
                risk_tier=entry.risk_tier,
                schema_hash=schema_hash,
                schema_json=schema_json,
                status="pinned",
                pinned_at=now,
                verified_at=now,
            )
            session.add(pin)

        pinned_records.append(pin)

    await session.commit()
    for pin in pinned_records:
        await session.refresh(pin)

    return pinned_records


async def verify_mcp_tool_pin(
    session: AsyncSession,
    connection_id: str,
    tool_name: str,
    live_description: str,
    live_input_schema: Dict[str, Any],
) -> McpToolPin:
    """Verifies a remote MCP tool's live schema against its pinned SHA-256 hash (`Titan S7`).

    If the live hash differs from `pin.schema_hash`:
    - Sets `pin.status = 'drift_blocked'`
    - Transitions `Connection.status = 'needs_reauth'` with explanatory `status_message`
    - Records an `AuditEventRecord` (`event='mcp_schema_drift'`, `decision='deny'`)
    - Commits and raises `McpSchemaDriftError`.
    """
    clean_connection_id = (connection_id or "").strip()
    clean_tool_name = (tool_name or "").strip()

    stmt = select(McpToolPin).where(
        McpToolPin.connection_id == clean_connection_id,
        McpToolPin.tool_name == clean_tool_name,
    )
    res = await session.execute(stmt)
    pin = res.scalar_one_or_none()
    if pin is None:
        raise McpSchemaDriftError(
            f"MCP tool '{clean_tool_name}' is not pinned or allowlisted for connection '{clean_connection_id}'."
        )

    now = utc_now()
    live_hash = compute_mcp_schema_hash(clean_tool_name, live_description, live_input_schema)

    if live_hash != pin.schema_hash or pin.status == "drift_blocked":
        pin.status = "drift_blocked"

        conn_stmt = select(Connection).where(Connection.id == clean_connection_id)
        conn_res = await session.execute(conn_stmt)
        conn = conn_res.scalar_one_or_none()
        if conn is not None:
            conn.status = "needs_reauth"
            conn.status_message = (
                f"MCP tool '{clean_tool_name}' schema changed upstream; re-approval required."
            )
            conn.updated_at = now

        audit = AuditEventRecord(
            id=str(uuid.uuid4()),
            ts=now,
            profile_id=pin.profile_id,
            actor_user_id=None,
            principal="connector",
            event="mcp_schema_drift",
            tool=clean_tool_name,
            risk=pin.risk_tier,
            decision="deny",
            payload_hash=live_hash,
            external_ref=f"connection:{clean_connection_id}",
            detail_redacted=json.dumps({
                "connection_id": clean_connection_id,
                "tool_name": clean_tool_name,
                "expected_hash": pin.schema_hash,
                "live_hash": live_hash,
            }),
        )
        session.add(audit)
        await session.commit()
        raise McpSchemaDriftError(
            f"MCP tool '{clean_tool_name}' disabled due to upstream schema drift."
        )

    pin.verified_at = now
    await session.commit()
    await session.refresh(pin)
    return pin


async def reapprove_mcp_tool_pin(
    session: AsyncSession,
    profile_id: str,
    connection_id: str,
    tool_name: str,
    new_description: str,
    new_input_schema: Dict[str, Any],
    actor_user_id: Optional[str] = None,
) -> McpToolPin:
    """Re-approves a drift-blocked MCP tool pin with its updated schema and restores connection status."""
    clean_profile_id = (profile_id or "").strip()
    clean_connection_id = (connection_id or "").strip()
    clean_tool_name = (tool_name or "").strip()

    stmt = select(McpToolPin).where(
        McpToolPin.profile_id == clean_profile_id,
        McpToolPin.connection_id == clean_connection_id,
        McpToolPin.tool_name == clean_tool_name,
    )
    res = await session.execute(stmt)
    pin = res.scalar_one_or_none()
    if pin is None:
        raise ValueError(
            f"MCP tool pin '{clean_tool_name}' not found for connection '{clean_connection_id}'."
        )

    now = utc_now()
    new_hash = compute_mcp_schema_hash(clean_tool_name, new_description, new_input_schema)
    schema_json = json.dumps(
        {
            "name": clean_tool_name,
            "description": str(new_description or "").strip(),
            "input_schema": new_input_schema if isinstance(new_input_schema, dict) else {},
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    pin.schema_hash = new_hash
    pin.schema_json = schema_json
    pin.status = "pinned"
    pin.verified_at = now

    all_pins_stmt = select(McpToolPin).where(McpToolPin.connection_id == clean_connection_id)
    all_pins_res = await session.execute(all_pins_stmt)
    all_pins = list(all_pins_res.scalars().all())

    if all(p.status == "pinned" for p in all_pins):
        conn_stmt = select(Connection).where(
            Connection.id == clean_connection_id,
            Connection.profile_id == clean_profile_id,
        )
        conn_res = await session.execute(conn_stmt)
        conn = conn_res.scalar_one_or_none()
        if conn is not None:
            conn.status = "active"
            conn.status_message = None
            conn.updated_at = now

    audit = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=clean_profile_id,
        actor_user_id=actor_user_id,
        principal="user",
        event="mcp_pin_reapproved",
        tool=clean_tool_name,
        risk=pin.risk_tier,
        decision="allow",
        payload_hash=new_hash,
        external_ref=f"connection:{clean_connection_id}",
        detail_redacted=json.dumps({
            "connection_id": clean_connection_id,
            "tool_name": clean_tool_name,
            "schema_hash": new_hash,
        }),
    )
    session.add(audit)
    await session.commit()
    await session.refresh(pin)
    return pin


def wrap_mcp_tool_as_spec(
    manifest: ConnectorManifest,
    connection_id: str,
    tool_entry: McpToolAllowlistEntry,
    invoker: Callable[..., Any],
) -> ToolSpec:
    """Wraps a curated remote MCP tool as a Carefold `ToolSpec` with `trust='untrusted'` and taint propagation."""
    validate_curated_mcp_manifest(manifest)

    async def _mcp_handler(args: Dict[str, Any], ctx: Any = None) -> UntrustedResult:
        if ctx is not None:
            taint_attr = getattr(ctx, "taint", None)
            if taint_attr is not None and hasattr(taint_attr, "set"):
                taint_attr.set()
            else:
                try:
                    setattr(ctx, "taint", True)
                except Exception:
                    try:
                        object.__setattr__(ctx, "taint", TaintFlag(True))
                    except Exception:
                        pass

        try:
            sig = inspect.signature(invoker)
            param_count = len(sig.parameters)
        except (ValueError, TypeError):
            param_count = 2

        if param_count >= 2:
            raw = invoker(args or {}, ctx)
        elif param_count == 1:
            raw = invoker(args or {})
        else:
            raw = invoker()

        if asyncio.iscoroutine(raw):
            raw = await raw

        if isinstance(raw, UntrustedResult):
            return raw

        return UntrustedResult(
            data=raw,
            taint=True,
            source=f"mcp:{manifest.id}:{tool_entry.name}",
        )

    return ToolSpec(
        name=tool_entry.name,
        description=tool_entry.description,
        parameters=dict(tool_entry.input_schema or {"type": "object", "properties": {}}),
        risk_tier=tool_entry.risk_tier,
        trust="untrusted",
        data_flows=tuple(manifest.data_flows.allowed_hosts),
        executor=_mcp_handler,
        handler=_mcp_handler,
        metadata={
            "connector_id": manifest.id,
            "connection_id": connection_id,
            "kind": "mcp",
            "risk": tool_entry.risk_tier,
            "taints_context": True,
        },
    )


__all__ = [
    "CURATED_REMOTE_MCP_IDS",
    "McpSchemaDriftError",
    "compute_mcp_schema_hash",
    "pin_mcp_tools",
    "reapprove_mcp_tool_pin",
    "validate_curated_mcp_manifest",
    "verify_mcp_tool_pin",
    "wrap_mcp_tool_as_spec",
]
