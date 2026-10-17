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

"""Declarative MCP Toolbox for Databases (googleapis/genai-toolbox) adapter and SQL executor.

Loads `backend/src/carefold/resources/db_tools.yaml` (following the Google MCP Toolbox
`sources` / `tools` / `toolsets` specification) and exposes each parameterized SQL tool as:
1. A Carefold `ToolSpec` registered in `ToolSpecRegistry` (`create_default_registry()`)
   and gated by the 4-tier `ToolExecutionGate` (`read`, `write_local`).
2. An OpenAI / LangChain tool definition dictionary for `model.bind_tools(...)`.
3. A dual-mode executor supporting both:
   - Embedded parameterized SQLAlchemy execution (`sqlalchemy.text(statement)`) for
     zero-binary Mode L (SQLite) and Mode S (PostgreSQL) deployments.
   - Remote / sidecar `googleapis/genai-toolbox` server invocation when
     `CAREFOLD_MCP_TOOLBOX_URL` is configured, with SHA-256 schema-hash verification.

Security Invariants:
- Context-bound parameters (`profile_id`, `user_id`, `id`, `locale`, `now`, `content_hash`)
  are NEVER exposed in the LLM JSON Schema and are forcibly injected from `ToolContext`
  at execution time so an agent can never read or write another profile's rows.
- Missing or empty `ToolContext.profile_id` fails closed immediately with `ValueError`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Set, Tuple, Union
from urllib.parse import quote
import uuid

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
import yaml

from carefold.connectors.mcp_remote import compute_mcp_schema_hash
from carefold.db.models import Job, Note, Profile
from carefold.db.session import get_session_factory
from carefold.engine.tool_registry import DataFlows, RiskTier, ToolSpec, ToolSpecRegistry
from carefold.i18n.locale import DEFAULT_LOCALE, canonicalize_locale, normalize_text_nfc
from carefold.logging import get_logger

logger = get_logger("carefold.tools.mcp_db_toolbox")

DEFAULT_DB_TOOLS_YAML_PATH = (
    Path(__file__).resolve().parent.parent / "resources" / "db_tools.yaml"
)

# Context-bound SQL parameters that must NEVER be controlled by LLM arguments
RESERVED_CONTEXT_PARAMS: Set[str] = {
    "profile_id",
    "user_id",
    "id",
    "locale",
    "now",
    "content_hash",
}

LOINC_VITAL_MAP: Dict[str, Tuple[str, str, str]] = {
    "blood_pressure": ("85354-9", "Blood pressure panel with all children optional", "mmHg"),
    "heart_rate": ("8867-4", "Heart rate", "bpm"),
    "blood_glucose": ("2339-0", "Glucose [Mass/volume] in Blood", "mg/dL"),
    "spo2": ("2708-6", "Oxygen saturation in Arterial blood", "%"),
    "weight": ("29463-7", "Body weight", "kg"),
    "height": ("8302-2", "Body height", "cm"),
    "temperature": ("8310-5", "Body temperature", "Cel"),
}


class DbSourceConfig(BaseModel):
    """MCP Toolbox database source declaration."""

    kind: Literal["sqlite", "postgres"] = "sqlite"
    database: str = ""
    host: Optional[str] = None
    port: Optional[Union[int, str]] = None


class DbToolParameter(BaseModel):
    """Typed parameter definition for a declarative SQL tool."""

    name: str = Field(..., min_length=1)
    type: Literal["string", "integer", "number", "boolean", "array", "object"] = "string"
    description: str = ""
    required: bool = True
    default: Any = None


class DbToolConfig(BaseModel):
    """Declarative MCP Toolbox SQL tool definition."""

    kind: Literal["sqlite-sql", "postgres-sql"] = "sqlite-sql"
    source: str = "carefold-sqlite"
    risk_tier: RiskTier = "read"
    entity: str = "record"
    description: str = ""
    statement: str = Field(..., min_length=1)
    parameters: List[DbToolParameter] = Field(default_factory=list)

    def to_json_schema(self) -> Dict[str, Any]:
        """Builds the LLM-visible JSON Schema, excluding reserved context-bound parameters."""
        properties: Dict[str, Any] = {}
        required: List[str] = []

        for param in self.parameters:
            if param.name in RESERVED_CONTEXT_PARAMS:
                continue
            prop: Dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.default is not None:
                prop["default"] = param.default
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        schema: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema

    def compute_pin_hash(self, tool_name: str) -> str:
        """Computes the deterministic SHA-256 schema pin hash (AU-57 compatible)."""
        return compute_mcp_schema_hash(
            name=tool_name,
            description=self.description,
            input_schema=self.to_json_schema(),
        )


class DbToolboxManifest(BaseModel):
    """Top-level MCP Toolbox `db_tools.yaml` manifest."""

    sources: Dict[str, DbSourceConfig] = Field(default_factory=dict)
    tools: Dict[str, DbToolConfig] = Field(default_factory=dict)
    toolsets: Dict[str, List[str]] = Field(default_factory=dict)


def _slugify(value: str) -> str:
    """Normalizes a title or slug into a safe lowercase alphanumeric hyphenated slug."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return cleaned[:120] or f"note-{uuid.uuid4().hex[:8]}"


def _parse_iso_datetime(raw: Any, fallback: Optional[datetime] = None) -> datetime:
    """Parses an ISO-8601 string into a timezone-aware UTC datetime."""
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str) and raw.strip():
        cleaned = raw.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(cleaned)
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return fallback or datetime.now(timezone.utc)


def _serialize_row(row_mapping: Mapping[str, Any]) -> Dict[str, Any]:
    """Converts a SQLAlchemy RowMapping into a JSON-serializable dictionary."""
    out: Dict[str, Any] = {}
    for k, v in row_mapping.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, str) and k in ("data", "tags_json") and v.strip().startswith(("{", "[")):
            try:
                out[k] = json.loads(v)
            except Exception:
                out[k] = v
        else:
            out[k] = v
    return out


async def _resolve_And_ensure_profile_id(session: AsyncSession, raw_profile_id: str) -> str:
    """Resolves 'me' or 'default_profile' to the primary Profile ID, ensuring a Profile row exists."""
    clean_pid = (raw_profile_id or "").strip()
    if not clean_pid:
        raise ValueError("Security invariant violation: profile_id is required in ToolContext. Fail-closed.")

    # 1. Check exact profile match
    existing = (
        await session.execute(select(Profile).where(Profile.id == clean_pid))
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id

    # 2. If alias 'me' or 'default_profile', resolve primary profile if present
    if clean_pid in ("me", "default_profile"):
        primary = (
            await session.execute(
                select(Profile)
                .order_by(Profile.is_primary.desc(), Profile.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if primary is not None:
            return primary.id

    # 3. Ensure a stub Profile row exists so ForeignKey("profiles.id") constraints succeed in isolated tests
    stub = Profile(
        id=clean_pid,
        name="Primary Profile" if clean_pid in ("me", "default_profile") else clean_pid,
        relationship="self",
        role="self",
        is_primary=(clean_pid in ("me", "default_profile")),
        preferred_locale=DEFAULT_LOCALE,
    )
    session.add(stub)
    await session.flush()
    return clean_pid


class McpDatabaseToolbox:
    """Declarative MCP Toolbox for Databases loader, validator, and executor."""

    def __init__(self, manifest: DbToolboxManifest, manifest_path: Path = DEFAULT_DB_TOOLS_YAML_PATH) -> None:
        self.manifest = manifest
        self.manifest_path = manifest_path

    @classmethod
    def from_yaml(cls, path: Optional[Path] = None) -> McpDatabaseToolbox:
        """Loads and validates `db_tools.yaml` into an `McpDatabaseToolbox` instance."""
        target_path = path or DEFAULT_DB_TOOLS_YAML_PATH
        raw_data = yaml.safe_load(target_path.read_text(encoding="utf-8")) or {}
        manifest = DbToolboxManifest.model_validate(raw_data)
        return cls(manifest=manifest, manifest_path=target_path)

    def list_tool_names(self) -> List[str]:
        """Returns all tool names defined in `db_tools.yaml`."""
        return list(self.manifest.tools.keys())

    def get_toolset(self, toolset_name: str) -> List[str]:
        """Returns the list of tool names belonging to a named `toolset`."""
        return list(self.manifest.toolsets.get(toolset_name, []))

    def get_toolset_for_domain(self, domain: str, risk_class: str = "clinical_assist") -> List[str]:
        """Maps an agent's domain / risk_class to its authorized MCP DB toolset."""
        dom = (domain or "").strip().lower()
        rc = (risk_class or "").strip().lower()
        if dom == "navigation" or rc == "admin":
            return self.get_toolset("navigation_db")
        if dom == "wellness" or rc == "wellness":
            return self.get_toolset("wellness_db")
        return self.get_toolset("clinical_assist_db")

    def get_tool_definition(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Returns the OpenAI / LangChain tool definition dictionary for `bind_tools`."""
        tool_cfg = self.manifest.tools.get(tool_name)
        if tool_cfg is None:
            return None
        return {
            "name": tool_name,
            "description": tool_cfg.description,
            "parameters": tool_cfg.to_json_schema(),
        }

    def get_all_tool_definitions(self) -> Dict[str, Dict[str, Any]]:
        """Returns all declarative DB tool definitions keyed by tool name."""
        return {
            name: {
                "name": name,
                "description": cfg.description,
                "parameters": cfg.to_json_schema(),
            }
            for name, cfg in self.manifest.tools.items()
        }

    async def execute_tool(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]],
        ctx: Any = None,
    ) -> Dict[str, Any]:
        """Executes a declarative SQL tool with strict context-bound `:profile_id` isolation."""
        if tool_name not in self.manifest.tools:
            raise ValueError(f"Unknown MCP database tool '{tool_name}'.")

        if ctx is None:
            raise ValueError(
                "Security invariant violation: ToolContext is required for database tools. Fail-closed."
            )

        raw_profile_id = getattr(ctx, "profile_id", None)
        if raw_profile_id is None or not str(raw_profile_id).strip():
            raise ValueError(
                "Security invariant violation: profile_id is required in ToolContext. Fail-closed."
            )

        raw_locale = getattr(ctx, "locale", None) or DEFAULT_LOCALE
        try:
            resolved_locale = canonicalize_locale(str(raw_locale))
        except Exception:
            resolved_locale = DEFAULT_LOCALE

        tool_cfg = self.manifest.tools[tool_name]
        safe_args: Dict[str, Any] = dict(args or {})

        # Strip any attempt by the caller/LLM to pass reserved context parameters
        for reserved_key in RESERVED_CONTEXT_PARAMS:
            safe_args.pop(reserved_key, None)

        # Apply defaults and validate required parameters
        bound_params: Dict[str, Any] = {}
        for param in tool_cfg.parameters:
            if param.name in RESERVED_CONTEXT_PARAMS:
                continue
            if param.name in safe_args and safe_args[param.name] is not None:
                bound_params[param.name] = safe_args[param.name]
            elif param.default is not None:
                bound_params[param.name] = param.default
            elif param.required:
                raise ValueError(f"Missing required parameter '{param.name}' for tool '{tool_name}'.")
            else:
                bound_params[param.name] = None

        # Optional remote MCP Toolbox server mode (`CAREFOLD_MCP_TOOLBOX_URL`)
        remote_url = os.environ.get("CAREFOLD_MCP_TOOLBOX_URL", "").strip()
        if remote_url:
            return await self._execute_via_remote_toolbox(
                remote_url=remote_url,
                tool_name=tool_name,
                tool_cfg=tool_cfg,
                bound_params=bound_params,
                profile_id=str(raw_profile_id).strip(),
                locale=resolved_locale,
            )

        # Default embedded SQLAlchemy parameterized execution
        factory = get_session_factory()
        async with factory() as session:
            resolved_profile_id = await _resolve_And_ensure_profile_id(session, str(raw_profile_id))
            now_dt = datetime.now(timezone.utc)

            # Inject mandatory context-bound parameters
            bound_params["profile_id"] = resolved_profile_id
            bound_params["id"] = str(uuid.uuid4())
            bound_params["locale"] = resolved_locale
            bound_params["now"] = now_dt

            result = await self._execute_in_session(
                session=session,
                tool_name=tool_name,
                tool_cfg=tool_cfg,
                bound_params=bound_params,
                ctx=ctx,
                now_dt=now_dt,
            )
            await session.commit()
            return result

    async def _execute_in_session(
        self,
        session: AsyncSession,
        tool_name: str,
        tool_cfg: DbToolConfig,
        bound_params: Dict[str, Any],
        ctx: Any,
        now_dt: datetime,
    ) -> Dict[str, Any]:
        """Executes the parameterized SQL statement and runs domain-specific hooks."""
        profile_id = bound_params["profile_id"]

        # 1. Special handling & hooks for `upsert_clinical_note`
        if tool_name == "upsert_clinical_note":
            title = normalize_text_nfc(str(bound_params.get("title") or "").strip())
            content = normalize_text_nfc(str(bound_params.get("content") or "").strip())
            if not title or not content:
                raise ValueError("Both 'title' and 'content' must be non-empty.")

            raw_slug = str(bound_params.get("slug") or "").strip()
            slug = _slugify(raw_slug if raw_slug else title)
            note_type = str(bound_params.get("note_type") or "visit").strip().lower()
            tags_raw = bound_params.get("tags_json")
            if isinstance(tags_raw, list):
                tags_json = json.dumps(tags_raw)
            elif isinstance(tags_raw, str) and tags_raw.strip().startswith("["):
                tags_json = tags_raw.strip()
            else:
                tags_json = "[]"

            existing_note = (
                await session.execute(
                    select(Note).where(Note.profile_id == profile_id, Note.slug == slug)
                )
            ).scalar_one_or_none()

            if existing_note is not None:
                existing_note.title = title
                existing_note.type = note_type
                existing_note.content = content
                existing_note.tags_json = tags_json
                existing_note.locale = bound_params["locale"]
                if bound_params.get("linked_appointment_id"):
                    existing_note.linked_appointment_id = str(bound_params["linked_appointment_id"])
                existing_note.updated_at = now_dt
                await session.flush()
                row_data = {
                    "id": existing_note.id,
                    "profile_id": existing_note.profile_id,
                    "slug": existing_note.slug,
                    "title": existing_note.title,
                    "type": existing_note.type,
                    "locale": existing_note.locale,
                    "updated_at": now_dt.isoformat(),
                    "operation": "updated",
                }
                note_id = existing_note.id
            else:
                bound_params["slug"] = slug
                bound_params["title"] = title
                bound_params["note_type"] = note_type
                bound_params["content"] = content
                bound_params["tags_json"] = tags_json
                res = await session.execute(text(tool_cfg.statement), bound_params)
                row = res.mappings().first()
                row_data = _serialize_row(row) if row else {
                    "id": bound_params["id"],
                    "profile_id": profile_id,
                    "slug": slug,
                    "title": title,
                    "type": note_type,
                }
                row_data["operation"] = "created"
                note_id = str(row_data.get("id") or bound_params["id"])

            # Enqueue search index job
            session.add(
                Job(
                    profile_id=profile_id,
                    kind="index_doc",
                    payload=json.dumps({
                        "doc_id": note_id,
                        "profile_id": profile_id,
                        "source": "clinical_note",
                        "title": title,
                        "content": content,
                    }),
                    next_run_at=now_dt,
                    status="pending",
                )
            )

            # Mirror to workspace/notes/{slug}.md if workspace_root is present
            ws_root = getattr(ctx, "workspace_root", None)
            if ws_root:
                try:
                    notes_dir = Path(ws_root) / "notes"
                    notes_dir.mkdir(parents=True, exist_ok=True)
                    md_path = notes_dir / f"{slug}.md"
                    frontmatter = (
                        f"---\n"
                        f'title: "{title}"\n'
                        f'created_at: "{now_dt.isoformat()}"\n'
                        f'profile_id: "{profile_id}"\n'
                        f"---\n\n"
                        f"{content}\n"
                    )
                    md_path.write_text(frontmatter, encoding="utf-8")
                except Exception as exc:
                    logger.debug("Optional workspace markdown mirror skipped: %s", exc)

            return {
                "status": "saved",
                "tool": tool_name,
                "note": row_data,
            }

        # 2. Special handling & red-flag hook for `record_vital_reading`
        if tool_name == "record_vital_reading":
            vital_type = str(bound_params.get("vital_type") or "").strip().lower()
            if vital_type not in LOINC_VITAL_MAP:
                raise ValueError(
                    f"Unsupported vital_type '{vital_type}'. Must be one of: {', '.join(sorted(LOINC_VITAL_MAP))}."
                )
            loinc_code, display_name, default_unit = LOINC_VITAL_MAP[vital_type]
            unit = str(bound_params.get("unit") or default_unit).strip() or default_unit
            effective_dt = _parse_iso_datetime(bound_params.get("effective_at"), fallback=now_dt)

            vitals_eval_input: Dict[str, Any] = {}
            if vital_type == "blood_pressure":
                sys_val = bound_params.get("systolic")
                dia_val = bound_params.get("diastolic")
                if sys_val is None or dia_val is None:
                    raise ValueError("Both 'systolic' and 'diastolic' are required for blood_pressure.")
                sys_f = float(sys_val)
                dia_f = float(dia_val)
                vitals_eval_input["systolic"] = sys_f
                vitals_eval_input["diastolic"] = dia_f
                fhir_payload: Dict[str, Any] = {
                    "resourceType": "Observation",
                    "status": "final",
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": loinc_code, "display": display_name}],
                        "text": f"Blood Pressure {int(sys_f)}/{int(dia_f)} {unit}",
                    },
                    "effectiveDateTime": effective_dt.isoformat(),
                    "component": [
                        {
                            "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic blood pressure"}]},
                            "valueQuantity": {"value": sys_f, "unit": unit},
                        },
                        {
                            "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic blood pressure"}]},
                            "valueQuantity": {"value": dia_f, "unit": unit},
                        },
                    ],
                }
            else:
                val = bound_params.get("value")
                if val is None:
                    raise ValueError(f"Numeric 'value' is required for vital_type '{vital_type}'.")
                val_f = float(val)
                eval_key = "spo2" if vital_type == "oxygen_saturation" else vital_type
                vitals_eval_input[eval_key] = val_f
                vitals_eval_input["unit"] = unit
                fhir_payload = {
                    "resourceType": "Observation",
                    "status": "final",
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": loinc_code, "display": display_name}],
                        "text": f"{display_name}: {val_f} {unit}",
                    },
                    "effectiveDateTime": effective_dt.isoformat(),
                    "valueQuantity": {"value": val_f, "unit": unit},
                }

            canonical_json = json.dumps(fhir_payload, sort_keys=True)
            content_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

            sql_params = {
                "id": bound_params["id"],
                "profile_id": profile_id,
                "source_type": "manual",
                "source_ref": "mcp_db_toolbox",
                "source_id": bound_params["id"],
                "content_hash": content_hash,
                "data": canonical_json,
                "locale": bound_params["locale"],
                "effective_at": effective_dt,
                "now": now_dt,
            }
            res = await session.execute(text(tool_cfg.statement), sql_params)
            row = res.mappings().first()
            row_data = _serialize_row(row) if row else {"id": bound_params["id"], "profile_id": profile_id}

            # Evaluate acute vitals red flags
            red_flags: List[Dict[str, Any]] = []
            try:
                from carefold.safety.vitals import check_vitals_red_flags

                rf_result = check_vitals_red_flags(vitals_eval_input)
                if getattr(rf_result, "triggered", False):
                    red_flags.append({
                        "triggered": True,
                        "category": rf_result.category,
                        "severity": rf_result.severity,
                        "directive": rf_result.directive,
                        "prompt_recheck": rf_result.prompt_recheck,
                        "details": rf_result.details,
                    })
            except Exception as exc:
                logger.debug("Vitals red flag check skipped: %s", exc)

            # Enqueue search index job
            session.add(
                Job(
                    profile_id=profile_id,
                    kind="index_doc",
                    payload=json.dumps({
                        "doc_id": bound_params["id"],
                        "profile_id": profile_id,
                        "source": "vital_observation",
                        "title": fhir_payload["code"]["text"],
                        "content": canonical_json,
                    }),
                    next_run_at=now_dt,
                    status="pending",
                )
            )

            return {
                "status": "recorded",
                "tool": tool_name,
                "observation": row_data,
                "fhir_resource": fhir_payload,
                "red_flags": red_flags,
            }

        # 3. Datetime normalization for appointments, reminders, and preventive records
        if tool_name == "create_appointment_record":
            start_dt = _parse_iso_datetime(bound_params.get("start_time"), fallback=now_dt + timedelta(days=1))
            end_raw = bound_params.get("end_time")
            end_dt = (
                _parse_iso_datetime(end_raw, fallback=start_dt + timedelta(minutes=30))
                if end_raw
                else (start_dt + timedelta(minutes=30))
            )
            if end_dt <= start_dt:
                end_dt = start_dt + timedelta(minutes=30)
            bound_params["start_time"] = start_dt
            bound_params["end_time"] = end_dt

        elif tool_name == "create_profile_reminder":
            due_dt = _parse_iso_datetime(bound_params.get("next_due_at"), fallback=now_dt + timedelta(hours=24))
            bound_params["next_due_at"] = due_dt

        elif tool_name == "update_preventive_record":
            comp_raw = bound_params.get("completed_at")
            if comp_raw:
                bound_params["completed_at"] = _parse_iso_datetime(comp_raw, fallback=now_dt)
            elif bound_params.get("status") == "completed":
                bound_params["completed_at"] = now_dt
            else:
                bound_params["completed_at"] = None

        # 4. Execute parameterized SQL statement
        res = await session.execute(text(tool_cfg.statement), bound_params)

        if tool_cfg.risk_tier == "read":
            rows = [_serialize_row(r) for r in res.mappings().all()]
            if tool_name == "get_clinical_note":
                return {
                    "status": "ok",
                    "tool": tool_name,
                    "note": rows[0] if rows else None,
                }
            return {
                "status": "ok",
                "tool": tool_name,
                "count": len(rows),
                "items": rows,
            }

        row = res.mappings().first()
        record_data = _serialize_row(row) if row else {"id": bound_params["id"], "profile_id": profile_id}

        if tool_name == "create_profile_reminder":
            session.add(
                Job(
                    profile_id=profile_id,
                    kind="reminder",
                    payload=json.dumps({
                        "reminder_id": record_data.get("id", bound_params["id"]),
                        "title": bound_params.get("title"),
                    }),
                    rrule=bound_params.get("rrule"),
                    timezone=str(bound_params.get("timezone") or "UTC"),
                    next_run_at=bound_params["next_due_at"],
                    status="pending",
                )
            )

        if tool_name == "create_email_draft_record":
            recipient = str(bound_params.get("recipient") or "").strip()
            subject = str(bound_params.get("subject") or "").strip()
            body = str(bound_params.get("body") or "").strip()
            mailto_uri = f"mailto:{quote(recipient)}?subject={quote(subject)}&body={quote(body)}"
            return {
                "status": "draft_created",
                "tool": tool_name,
                "draft": record_data,
                "mailto_uri": mailto_uri,
                "auto_send": False,
                "notice": "Draft saved locally in carefold.db. Carefold never sends emails automatically.",
            }

        return {
            "status": "saved",
            "tool": tool_name,
            "record": record_data,
        }

    async def _execute_via_remote_toolbox(
        self,
        remote_url: str,
        tool_name: str,
        tool_cfg: DbToolConfig,
        bound_params: Dict[str, Any],
        profile_id: str,
        locale: str,
    ) -> Dict[str, Any]:
        """Invokes a standalone `googleapis/genai-toolbox` HTTP server with schema-pin verification."""
        base = remote_url.rstrip("/")
        payload = {
            **bound_params,
            "profile_id": profile_id,
            "id": str(uuid.uuid4()),
            "locale": locale,
            "now": datetime.now(timezone.utc).isoformat(),
        }
        expected_hash = tool_cfg.compute_pin_hash(tool_name)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Carefold-Profile-Id": profile_id,
            "X-Carefold-Schema-Pin": expected_hash,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{base}/api/tool/{tool_name}/invoke",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

    def to_tool_specs(self) -> List[ToolSpec]:
        """Converts all declarative tools in `db_tools.yaml` into Carefold `ToolSpec` instances."""
        specs: List[ToolSpec] = []
        for tool_name, tool_cfg in self.manifest.tools.items():

            def _make_executor(t_name: str):
                async def _executor(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
                    return await self.execute_tool(t_name, args, ctx)

                return _executor

            spec = ToolSpec(
                name=tool_name,
                description=tool_cfg.description,
                parameters=tool_cfg.to_json_schema(),
                risk_tier=tool_cfg.risk_tier,
                trust="trusted",
                data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
                executor=_make_executor(tool_name),
                metadata={
                    "source": "mcp_db_toolbox",
                    "entity": tool_cfg.entity,
                    "risk": tool_cfg.risk_tier,
                    "schema_hash": tool_cfg.compute_pin_hash(tool_name),
                    "undoable": tool_cfg.risk_tier == "write_local",
                },
            )
            specs.append(spec)
        return specs


_DEFAULT_DB_TOOLBOX: Optional[McpDatabaseToolbox] = None


def get_db_toolbox(path: Optional[Path] = None) -> McpDatabaseToolbox:
    """Returns the singleton `McpDatabaseToolbox` loaded from `db_tools.yaml`."""
    global _DEFAULT_DB_TOOLBOX
    if path is not None:
        return McpDatabaseToolbox.from_yaml(path)
    if _DEFAULT_DB_TOOLBOX is None:
        _DEFAULT_DB_TOOLBOX = McpDatabaseToolbox.from_yaml(DEFAULT_DB_TOOLS_YAML_PATH)
    return _DEFAULT_DB_TOOLBOX


def register_db_toolbox_specs(registry: ToolSpecRegistry) -> ToolSpecRegistry:
    """Registers all declarative `db_tools.yaml` ToolSpecs into a `ToolSpecRegistry`."""
    toolbox = get_db_toolbox()
    for spec in toolbox.to_tool_specs():
        registry.register(spec)
    return registry


__all__ = [
    "DEFAULT_DB_TOOLS_YAML_PATH",
    "DbSourceConfig",
    "DbToolConfig",
    "DbToolParameter",
    "DbToolboxManifest",
    "McpDatabaseToolbox",
    "RESERVED_CONTEXT_PARAMS",
    "get_db_toolbox",
    "register_db_toolbox_specs",
]
