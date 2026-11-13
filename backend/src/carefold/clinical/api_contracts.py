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

"""Canonical shared Pydantic API <-> MCP contracts for Carefold domain endpoints (#344).

Introspects Carefold's mounted FastAPI `APIRoute` definitions (`carefold.api.router`)
without importing `carefold.main`, constructing shared Pydantic input/output models,
authorization dependency bindings, and MCP JSON Schemas so REST endpoints and
declarative MCP tool wrappers cannot drift.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
    get_args,
    get_origin,
)

from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, create_model
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined
from yarvelle_core.schemas.tool_spec import (
    RESERVED_TOOL_CONTEXT_PARAMS,
    ToolDataSensitivity,
    ToolRiskTier,
    validate_tool_json_schema,
)


def walk_fastapi_api_routes(
    router_or_routes: Any,
    prefix: str = "",
    include_in_schema: bool = True,
) -> List[Tuple[APIRoute, str, bool]]:
    """Recursively walks FastAPI `APIRoute` and `_IncludedRouter` trees without losing prefixes."""
    out: List[Tuple[APIRoute, str, bool]] = []
    routes = getattr(router_or_routes, "routes", router_or_routes)
    for route in routes:
        if isinstance(route, APIRoute):
            full_path = f"{prefix}{route.path}"
            effective_inc = bool(include_in_schema and route.include_in_schema)
            out.append((route, full_path, effective_inc))
        elif hasattr(route, "original_router") and hasattr(route, "include_context"):
            ctx = route.include_context
            sub_prefix = f"{prefix}{getattr(ctx, 'prefix', '') or ''}"
            sub_inc = bool(include_in_schema and getattr(ctx, "include_in_schema", True))
            out.extend(walk_fastapi_api_routes(route.original_router, sub_prefix, sub_inc))
    return out


def unwrap_body_model_type(annotation: Any) -> Tuple[Optional[Type[BaseModel]], bool]:
    """Unwraps `Model` or `Optional[Model]` into `(ModelClass, is_optional)`."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation, False
    origin = get_origin(annotation)
    if origin is Union:
        args = get_args(annotation)
        models = [a for a in args if isinstance(a, type) and issubclass(a, BaseModel)]
        has_none = type(None) in args
        if len(models) == 1:
            return models[0], has_none
    return None, False


def _inline_json_schema_defs(
    node: Any,
    defs: Dict[str, Any],
    *,
    in_properties_map: bool = False,
) -> Any:
    """Recursively resolves local `#/$defs/<Name>` references and strips noisy schema `title` keys."""
    if isinstance(node, list):
        return [_inline_json_schema_defs(item, defs) for item in node]
    if not isinstance(node, dict):
        return node

    if not in_properties_map and "$ref" in node and isinstance(node["$ref"], str) and node["$ref"].startswith("#/$defs/"):
        def_name = node["$ref"].split("#/$defs/", 1)[1]
        target = copy.deepcopy(defs.get(def_name, {"type": "object"}))
        merged = _inline_json_schema_defs(target, defs)
        for k, v in node.items():
            if k not in ("$ref", "title"):
                merged[k] = _inline_json_schema_defs(
                    v, defs, in_properties_map=(k == "properties")
                )
        return merged

    cleaned: Dict[str, Any] = {}
    for key, val in node.items():
        if not in_properties_map and key in ("$defs", "title"):
            continue
        cleaned[key] = _inline_json_schema_defs(
            val, defs, in_properties_map=(not in_properties_map and key == "properties")
        )
    return cleaned


def build_mcp_input_schema(model_cls: Type[BaseModel]) -> Dict[str, Any]:
    """Generates a validated Draft 2020-12 MCP `inputSchema` directly from a shared Pydantic model."""
    raw = model_cls.model_json_schema()
    defs = dict(raw.get("$defs") or {})
    inlined = _inline_json_schema_defs(raw, defs)
    inlined["type"] = "object"
    inlined.setdefault("properties", {})
    if "required" in inlined and not inlined["required"]:
        inlined.pop("required", None)
    return validate_tool_json_schema(
        inlined,
        require_object_root=True,
        forbid_reserved_context_params=True,
    )


@dataclass(frozen=True)
class CanonicalRouteSpec:
    """Declarative specification pairing one canonical FastAPI route to its 1:1 MCP tool."""

    method: str
    path: str
    tool_name: str
    category: str
    risk_tier: ToolRiskTier
    data_sensitivity: ToolDataSensitivity = "restricted"
    context_remaps: Dict[str, str] = field(default_factory=dict)
    extra_fields: Dict[str, Tuple[Any, FieldInfo]] = field(default_factory=dict)
    human_decision_only: bool = False
    allowed_hosts: Tuple[str, ...] = ()
    fhir_toolbox_tool: Optional[str] = None


@dataclass(frozen=True)
class ApiMcpOperationContract:
    """Resolved runtime contract shared identically by FastAPI REST and MCP tool execution."""

    spec: CanonicalRouteSpec
    route: APIRoute
    endpoint: Callable[..., Any]
    input_model: Type[BaseModel]
    input_schema: Dict[str, Any]
    output_model: Optional[Type[BaseModel]]
    body_model: Optional[Type[BaseModel]]
    body_param_name: Optional[str]
    body_is_optional: bool
    path_param_names: Tuple[str, ...]
    query_param_defaults: Dict[str, Any]
    header_param_defaults: Dict[str, Any]
    request_param_name: Optional[str]
    context_params: Tuple[str, ...]
    context_remaps: Dict[str, str]
    description: str


CANONICAL_DOMAIN_ROUTE_SPECS: Tuple[CanonicalRouteSpec, ...] = (
    # --- Activity (list + undo) ---
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/activity", "activity_list_timeline", "activity", "read"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/activity/{event_id}/undo", "activity_undo_event", "activity", "write_local"),
    # --- Handover (viewer sections + teen handover) ---
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/access/{target_user_id}/sections", "handover_get_viewer_sections", "handover", "read"),
    CanonicalRouteSpec("PUT", "/api/v1/profiles/{profile_id}/access/{target_user_id}/sections", "handover_update_viewer_sections", "handover", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/handover", "handover_execute_teen_handover", "handover", "write_local"),
    # --- Companion (devices, pairing, reminders, sync) ---
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/companion/devices", "companion_list_devices", "companion", "read"),
    CanonicalRouteSpec("DELETE", "/api/v1/profiles/{profile_id}/companion/devices/{device_id}", "companion_revoke_device", "companion", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/companion/pair/initiate", "companion_pair_initiate", "companion", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/companion/pair/complete", "companion_pair_complete", "companion", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/companion/reminders", "companion_list_reminders", "companion", "read"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/companion/sync", "companion_sync_records", "companion", "write_local"),
    # --- Routines ---
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/routines", "routines_list", "routines", "read"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/routines", "routines_create", "routines", "write_local"),
    CanonicalRouteSpec("PATCH", "/api/v1/profiles/{profile_id}/routines/{routine_id}", "routines_update", "routines", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/routines/{routine_id}/run", "routines_run", "routines", "write_local"),
    # --- Coordinated care, audit verification, smart scheduling ---
    CanonicalRouteSpec("GET", "/api/v1/connectors/v2-catalog", "connectors_get_v2_catalog", "coordinated", "read", data_sensitivity="public"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/audit/verify", "coordinated_verify_audit_chain", "coordinated", "read"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/email-drafts/{draft_id}/send", "coordinated_send_email_draft", "coordinated", "write_external"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/scheduling/smart-slots", "coordinated_discover_smart_slots", "coordinated", "read"),
    CanonicalRouteSpec(
        "POST",
        "/api/v1/profiles/{profile_id}/scheduling/zocdoc-preview",
        "coordinated_zocdoc_preview",
        "coordinated",
        "write_local",
        context_remaps={"run_id": "preview_run_id"},
    ),
    # --- Approvals (human decision guard enforced on decide) ---
    CanonicalRouteSpec("GET", "/api/v1/approvals", "approvals_list", "approvals", "read"),
    CanonicalRouteSpec("GET", "/api/v1/approvals/{approval_id}", "approvals_get", "approvals", "read"),
    CanonicalRouteSpec(
        "POST",
        "/api/v1/approvals/{approval_id}/decide",
        "approvals_decide",
        "approvals",
        "write_local",
        human_decision_only=True,
    ),
    # --- Memory ---
    CanonicalRouteSpec("GET", "/api/v1/memory", "memory_recall", "memory", "read"),
    CanonicalRouteSpec("DELETE", "/api/v1/memory", "memory_delete_all", "memory", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/memory/status", "memory_get_status", "memory", "read"),
    CanonicalRouteSpec("GET", "/api/v1/memory/{key}", "memory_get", "memory", "read"),
    CanonicalRouteSpec("PUT", "/api/v1/memory/{key}", "memory_put", "memory", "write_local"),
    CanonicalRouteSpec("DELETE", "/api/v1/memory/{key}", "memory_delete", "memory", "write_local"),
    # --- Vitals ---
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/vitals", "vitals_create", "vitals", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/vitals", "vitals_list", "vitals", "read"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/vitals/trends", "vitals_get_trends", "vitals", "read"),
    # --- Appointments ---
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/appointments", "appointments_create", "appointments", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/appointments", "appointments_list", "appointments", "read"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/appointments/draft-booking", "appointments_draft_booking", "appointments", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/appointments/evaluate-transitions", "appointments_evaluate_transitions", "appointments", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/appointments/{appointment_id}", "appointments_get", "appointments", "read"),
    CanonicalRouteSpec("PATCH", "/api/v1/profiles/{profile_id}/appointments/{appointment_id}", "appointments_update", "appointments", "write_local"),
    CanonicalRouteSpec("DELETE", "/api/v1/profiles/{profile_id}/appointments/{appointment_id}", "appointments_delete", "appointments", "write_local"),
    # --- Notes (workspace + profile-scoped typed + entity extraction) ---
    CanonicalRouteSpec("GET", "/api/v1/notes", "notes_list_workspace", "notes", "read"),
    CanonicalRouteSpec(
        "POST",
        "/api/v1/notes",
        "notes_create_workspace",
        "notes",
        "write_local",
        context_remaps={"locale": "note_locale"},
    ),
    CanonicalRouteSpec("GET", "/api/v1/notes/{slug}", "notes_get_workspace", "notes", "read"),
    CanonicalRouteSpec(
        "PUT",
        "/api/v1/notes/{slug}",
        "notes_update_workspace",
        "notes",
        "write_local",
        context_remaps={"profile_id": "target_profile_id", "locale": "note_locale"},
    ),
    CanonicalRouteSpec("DELETE", "/api/v1/notes/{slug}", "notes_delete_workspace", "notes", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/notes/{slug}/extract", "notes_extract_by_slug", "notes", "read"),
    CanonicalRouteSpec(
        "POST",
        "/api/v1/profiles/{profile_id}/notes",
        "notes_create_profile_typed",
        "notes",
        "write_local",
        context_remaps={"locale": "note_locale"},
    ),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/notes", "notes_list_profile_typed", "notes", "read"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/notes/extract", "notes_extract_profile_adhoc", "notes", "read"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/notes/{note_id}", "notes_get_profile_typed", "notes", "read"),
    CanonicalRouteSpec(
        "PATCH",
        "/api/v1/profiles/{profile_id}/notes/{note_id}",
        "notes_update_profile_typed",
        "notes",
        "write_local",
        context_remaps={"locale": "note_locale"},
    ),
    CanonicalRouteSpec("DELETE", "/api/v1/profiles/{profile_id}/notes/{note_id}", "notes_delete_profile_typed", "notes", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/notes/{note_id}/extract", "notes_extract_profile_note", "notes", "read"),
    # --- Reminders ---
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/reminders", "reminders_create", "reminders", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/reminders", "reminders_list", "reminders", "read"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/reminders/export.ics", "reminders_export_ics", "reminders", "read"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/reminders/{reminder_id}", "reminders_get", "reminders", "read"),
    CanonicalRouteSpec("PATCH", "/api/v1/profiles/{profile_id}/reminders/{reminder_id}", "reminders_update", "reminders", "write_local"),
    CanonicalRouteSpec("DELETE", "/api/v1/profiles/{profile_id}/reminders/{reminder_id}", "reminders_delete", "reminders", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/reminders/{reminder_id}/snooze", "reminders_snooze", "reminders", "write_local"),
    # --- Preventive care ---
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/preventive", "preventive_get_checklist", "preventive", "read"),
    CanonicalRouteSpec("PUT", "/api/v1/profiles/{profile_id}/preventive-settings", "preventive_update_settings", "preventive", "write_local"),
    CanonicalRouteSpec("PATCH", "/api/v1/profiles/{profile_id}/preventive/{rule_id}", "preventive_update_rule_status", "preventive", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/preventive/{rule_id}/action", "preventive_trigger_action", "preventive", "write_local"),
    # --- Prep pack ---
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/prep-pack", "prep_pack_generate", "prep_pack", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/prep-pack/{appointment_id}", "prep_pack_get", "prep_pack", "read"),
    # --- Clinical & Gmail staged imports ---
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/imports", "imports_list_batches", "imports", "read"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/imports/stage", "imports_stage_batch", "imports", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/imports/{batch_id}", "imports_get_batch", "imports", "read"),
    CanonicalRouteSpec("DELETE", "/api/v1/profiles/{profile_id}/imports/{batch_id}", "imports_discard_batch", "imports", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/imports/{batch_id}/commit", "imports_commit_batch", "imports", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/gmail/stage", "imports_stage_gmail", "imports", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/gmail/batches/{batch_id}/confirm/{item_index}", "imports_confirm_gmail_item", "imports", "write_local"),
    # --- School forms & school ICS feeds ---
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/school-forms", "school_forms_list", "school", "read"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/school-forms", "school_forms_create", "school", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/school-forms/{form_id}", "school_forms_get", "school", "read"),
    CanonicalRouteSpec("PATCH", "/api/v1/profiles/{profile_id}/school-forms/{form_id}", "school_forms_update", "school", "write_local"),
    CanonicalRouteSpec("DELETE", "/api/v1/profiles/{profile_id}/school-forms/{form_id}", "school_forms_delete", "school", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/school-forms/{form_id}/prefill", "school_forms_regenerate_prefill", "school", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/school-ics", "school_ics_list_feeds", "school", "read"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/school-ics", "school_ics_create_feed", "school", "write_local"),
    CanonicalRouteSpec("DELETE", "/api/v1/profiles/{profile_id}/school-ics/{feed_id}", "school_ics_delete_feed", "school", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/school-ics/{feed_id}/sync", "school_ics_sync_feed", "school", "write_local"),
    # --- Connections, consents, data flows, MCP pins ---
    CanonicalRouteSpec("GET", "/api/v1/connectors/catalog", "connectors_get_catalog", "connections", "read", data_sensitivity="public"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/connections", "connections_list", "connections", "read"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/connections", "connections_create", "connections", "write_local"),
    CanonicalRouteSpec("PATCH", "/api/v1/profiles/{profile_id}/connections/{connection_id}/autonomy", "connections_update_autonomy", "connections", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/connections/{connection_id}/mcp-pins", "connections_list_mcp_pins", "connections", "read"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/connections/{connection_id}/mcp-pins/{tool_name}/reapprove", "connections_reapprove_mcp_pin", "connections", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/connections/{connection_id}/revoke", "connections_revoke", "connections", "write_local"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/connections/{connection_id}/sync", "connections_trigger_sync", "connections", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/connections/{connection_id}/sync-runs", "connections_list_sync_runs", "connections", "read"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/consents", "connections_list_consents", "connections", "read"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/data-flows", "connections_get_data_flows", "connections", "read"),
    # --- Profiles, access grants, consent, viewer invites ---
    CanonicalRouteSpec("GET", "/api/v1/profiles", "profiles_list", "profiles", "read"),
    CanonicalRouteSpec("POST", "/api/v1/profiles", "profiles_create", "profiles", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/invites", "profiles_list_all_invites", "profiles", "read"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/invites/accept", "profiles_accept_invite", "profiles", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}", "profiles_get", "profiles", "read"),
    CanonicalRouteSpec("PUT", "/api/v1/profiles/{profile_id}", "profiles_update", "profiles", "write_local"),
    CanonicalRouteSpec("DELETE", "/api/v1/profiles/{profile_id}", "profiles_delete", "profiles", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/access", "profiles_list_access", "profiles", "read"),
    CanonicalRouteSpec(
        "POST",
        "/api/v1/profiles/{profile_id}/access",
        "profiles_grant_access",
        "profiles",
        "write_local",
        context_remaps={"user_id": "target_user_id"},
    ),
    CanonicalRouteSpec("DELETE", "/api/v1/profiles/{profile_id}/access/{target_user_id}", "profiles_revoke_access", "profiles", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/consent", "profiles_get_consent", "profiles", "read"),
    CanonicalRouteSpec("PUT", "/api/v1/profiles/{profile_id}/consent", "profiles_update_consent", "profiles", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/invites", "profiles_list_invites", "profiles", "read"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/invites", "profiles_create_invite", "profiles", "write_local"),
    CanonicalRouteSpec("DELETE", "/api/v1/profiles/{profile_id}/invites/{invite_id}", "profiles_revoke_invite", "profiles", "write_local"),
    # --- Attachments (metadata list + delete) ---
    CanonicalRouteSpec("GET", "/api/v1/attachments", "attachments_list", "attachments", "read"),
    CanonicalRouteSpec("DELETE", "/api/v1/attachments/{attachment_id}", "attachments_delete", "attachments", "write_local"),
    # --- Email drafts ---
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/email-drafts", "email_drafts_list", "email_drafts", "read"),
    CanonicalRouteSpec("POST", "/api/v1/profiles/{profile_id}/email-drafts", "email_drafts_create", "email_drafts", "write_local"),
    CanonicalRouteSpec("DELETE", "/api/v1/profiles/{profile_id}/email-drafts/{draft_id}", "email_drafts_delete", "email_drafts", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/email-drafts/{draft_id}/eml", "email_drafts_export_eml", "email_drafts", "read"),
    # --- Hybrid search ---
    CanonicalRouteSpec("GET", "/api/v1/profiles/{profile_id}/search", "search_profile_records", "search", "read"),
    # --- Agents & agent docs ---
    CanonicalRouteSpec("GET", "/api/v1/agents", "agents_list", "agents", "read", data_sensitivity="internal"),
    CanonicalRouteSpec("POST", "/api/v1/agents", "agents_create", "agents", "write_local", data_sensitivity="internal"),
    CanonicalRouteSpec("GET", "/api/v1/agents/categories", "agents_list_categories", "agents", "read", data_sensitivity="public"),
    CanonicalRouteSpec("GET", "/api/v1/agents/{agent_id}", "agents_get", "agents", "read", data_sensitivity="internal"),
    CanonicalRouteSpec("PUT", "/api/v1/agents/{agent_id}", "agents_update", "agents", "write_local", data_sensitivity="internal"),
    CanonicalRouteSpec("DELETE", "/api/v1/agents/{agent_id}", "agents_delete", "agents", "write_local", data_sensitivity="internal"),
    CanonicalRouteSpec("GET", "/api/v1/agents/{agent_id}/docs", "agents_list_docs", "agents", "read", data_sensitivity="internal"),
    CanonicalRouteSpec("POST", "/api/v1/agents/{agent_id}/docs", "agents_create_doc", "agents", "write_local", data_sensitivity="internal"),
    CanonicalRouteSpec("GET", "/api/v1/agents/{agent_id}/docs/{doc_name}", "agents_get_doc", "agents", "read", data_sensitivity="internal"),
    CanonicalRouteSpec("PUT", "/api/v1/agents/{agent_id}/docs/{doc_name}", "agents_update_doc", "agents", "write_local", data_sensitivity="internal"),
    CanonicalRouteSpec("DELETE", "/api/v1/agents/{agent_id}/docs/{doc_name}", "agents_delete_doc", "agents", "write_local", data_sensitivity="internal"),
    # --- Skills & skill docs ---
    CanonicalRouteSpec("GET", "/api/v1/skills", "skills_list", "skills", "read", data_sensitivity="internal"),
    CanonicalRouteSpec("POST", "/api/v1/skills", "skills_create", "skills", "write_local", data_sensitivity="internal"),
    CanonicalRouteSpec("GET", "/api/v1/skills/{skill_id}", "skills_get", "skills", "read", data_sensitivity="internal"),
    CanonicalRouteSpec("PUT", "/api/v1/skills/{skill_id}", "skills_update", "skills", "write_local", data_sensitivity="internal"),
    CanonicalRouteSpec("DELETE", "/api/v1/skills/{skill_id}", "skills_delete", "skills", "write_local", data_sensitivity="internal"),
    CanonicalRouteSpec("GET", "/api/v1/skills/{skill_id}/docs", "skills_list_docs", "skills", "read", data_sensitivity="internal"),
    CanonicalRouteSpec("POST", "/api/v1/skills/{skill_id}/docs", "skills_create_doc", "skills", "write_local", data_sensitivity="internal"),
    CanonicalRouteSpec("GET", "/api/v1/skills/{skill_id}/docs/{doc_name}", "skills_get_doc", "skills", "read", data_sensitivity="internal"),
    CanonicalRouteSpec("PUT", "/api/v1/skills/{skill_id}/docs/{doc_name}", "skills_update_doc", "skills", "write_local", data_sensitivity="internal"),
    CanonicalRouteSpec("DELETE", "/api/v1/skills/{skill_id}/docs/{doc_name}", "skills_delete_doc", "skills", "write_local", data_sensitivity="internal"),
    # --- Audit, Models, Chat thread history ---
    CanonicalRouteSpec("GET", "/api/v1/audit", "audit_list_events", "audit", "read"),
    CanonicalRouteSpec("GET", "/api/v1/models", "models_list", "models", "read", data_sensitivity="public"),
    CanonicalRouteSpec("GET", "/api/v1/chat/threads", "chat_get_threads", "chat", "read"),
    CanonicalRouteSpec("DELETE", "/api/v1/chat/threads", "chat_delete_threads", "chat", "write_local"),
    CanonicalRouteSpec("GET", "/api/v1/chat/threads/{thread_id}", "chat_get_thread", "chat", "read"),
    CanonicalRouteSpec("DELETE", "/api/v1/chat/threads/{thread_id}", "chat_delete_thread", "chat", "write_local"),
    # --- FHIR R4 canonical operations ---
    CanonicalRouteSpec(
        "GET",
        "/api/v1/fhir/r4/metadata",
        "fhir_get_capabilities",
        "fhir",
        "read",
        data_sensitivity="public",
        fhir_toolbox_tool="fhir_get_capabilities",
    ),
    CanonicalRouteSpec(
        "GET",
        "/api/v1/fhir/r4/{resource_type}",
        "fhir_r4_search_resources",
        "fhir",
        "read",
        fhir_toolbox_tool="fhir_search_resources",
    ),
    CanonicalRouteSpec(
        "GET",
        "/api/v1/fhir/r4/{resource_type}/{id}",
        "fhir_read_resource",
        "fhir",
        "read",
        fhir_toolbox_tool="fhir_read_resource",
    ),
    CanonicalRouteSpec(
        "POST",
        "/api/v1/fhir/r4/{resource_type}",
        "fhir_create_resource",
        "fhir",
        "write_local",
        fhir_toolbox_tool="fhir_upsert_resource",
        extra_fields={
            "resource": (Dict[str, Any], Field(..., description="Complete HL7 FHIR R4 JSON resource object.")),
            "if_match": (Optional[str], Field(default=None, description="Optional weak ETag (W/\"{versionId}\").")),
            "idempotency_key": (Optional[str], Field(default=None, description="Optional idempotency key.")),
        },
    ),
    CanonicalRouteSpec(
        "PUT",
        "/api/v1/fhir/r4/{resource_type}/{id}",
        "fhir_upsert_resource",
        "fhir",
        "write_local",
        fhir_toolbox_tool="fhir_upsert_resource",
        extra_fields={
            "resource": (Dict[str, Any], Field(..., description="Complete HL7 FHIR R4 JSON resource object.")),
            "if_match": (Optional[str], Field(default=None, description="Optional weak ETag (W/\"{versionId}\") for optimistic concurrency.")),
            "idempotency_key": (Optional[str], Field(default=None, description="Optional idempotency key for safe retries.")),
        },
    ),
    CanonicalRouteSpec(
        "GET",
        "/api/v1/fhir/r4/{resource_type}/{id}/_history",
        "fhir_get_resource_history",
        "fhir",
        "read",
        fhir_toolbox_tool="fhir_get_resource_history",
    ),
    CanonicalRouteSpec(
        "GET",
        "/api/v1/fhir/r4/Patient/{id}/$everything",
        "fhir_get_patient_everything",
        "fhir",
        "read",
        fhir_toolbox_tool="fhir_get_patient_everything",
    ),
    CanonicalRouteSpec(
        "GET",
        "/api/v1/fhir/r4/Patient/{id}/$summary",
        "fhir_r4_patient_summary",
        "fhir",
        "read",
        fhir_toolbox_tool="fhir_get_patient_summary",
    ),
    CanonicalRouteSpec(
        "POST",
        "/api/v1/fhir/r4/Patient/{id}/$export",
        "fhir_start_bulk_export",
        "fhir",
        "write_local",
        fhir_toolbox_tool="fhir_start_bulk_export",
        extra_fields={
            "idempotency_key": (Optional[str], Field(default=None, description="Optional idempotency key.")),
        },
    ),
    CanonicalRouteSpec(
        "GET",
        "/api/v1/fhir/r4/$export-status/{job_id}",
        "fhir_get_bulk_export_status",
        "fhir",
        "read",
        fhir_toolbox_tool="fhir_get_bulk_export_status",
    ),
    CanonicalRouteSpec(
        "GET",
        "/api/v1/fhir/r4/$export-status/{job_id}/files/{resource_file}",
        "fhir_download_bulk_export_file",
        "fhir",
        "read",
        fhir_toolbox_tool="fhir_download_bulk_export_file",
    ),
)


def _clone_field_info(
    finfo: FieldInfo,
    *,
    force_optional: bool = False,
    external_alias: Optional[str] = None,
) -> Tuple[Any, FieldInfo]:
    """Clones a FastAPI/Pydantic FieldInfo cleanly for composed shared InputModel creation."""
    ann = finfo.annotation if finfo.annotation is not None else Any
    is_req = finfo.is_required() and not force_optional
    default_val = None if (force_optional and finfo.is_required()) else finfo.default
    if force_optional and finfo.is_required():
        ann = Optional[ann]  # type: ignore[valid-type]

    kwargs: Dict[str, Any] = {}
    if external_alias:
        kwargs["alias"] = external_alias
        kwargs["serialization_alias"] = external_alias
    if finfo.description:
        kwargs["description"] = finfo.description
    for meta in getattr(finfo, "metadata", ()) or ():
        for attr in ("ge", "gt", "le", "lt", "min_length", "max_length", "pattern"):
            val = getattr(meta, attr, None)
            if val is not None:
                kwargs[attr] = val

    if is_req or default_val is PydanticUndefined:
        if finfo.default_factory is not None and not is_req:
            return ann, Field(default_factory=finfo.default_factory, **kwargs)
        return ann, Field(..., **kwargs)
    return ann, Field(default=default_val, **kwargs)


def _safe_model_field_key(name: str) -> Tuple[str, Optional[str]]:
    """Handles leading-underscore FHIR parameters (e.g. `_count`) via Pydantic field aliases."""
    if name.startswith("_"):
        return f"fhir{name}", name
    return name, None


def _build_contract_for_spec(
    spec: CanonicalRouteSpec,
    route_lookup: Dict[Tuple[str, str], APIRoute],
) -> ApiMcpOperationContract:
    key = (spec.method.upper(), spec.path)
    if key not in route_lookup:
        raise KeyError(f"Canonical FastAPI route {spec.method} {spec.path} not found on api_router.")
    route = route_lookup[key]
    dep = route.dependant

    field_defs: Dict[str, Any] = {}
    path_names: List[str] = []
    query_defaults: Dict[str, Any] = {}
    header_defaults: Dict[str, Any] = {}
    context_params_list: List[str] = ["profile_id", "user_id"]

    for pf in dep.path_params:
        path_names.append(pf.name)
        if pf.name in spec.context_remaps:
            mcp_name = spec.context_remaps[pf.name]
            field_defs[mcp_name] = _clone_field_info(pf.field_info)
        elif pf.name in RESERVED_TOOL_CONTEXT_PARAMS:
            if pf.name not in context_params_list:
                context_params_list.append(pf.name)
        else:
            field_defs[pf.name] = _clone_field_info(pf.field_info)

    for qf in dep.query_params:
        default_v = None if qf.field_info.is_required() else qf.field_info.default
        query_defaults[qf.name] = default_v
        if qf.name in spec.context_remaps:
            mcp_name = spec.context_remaps[qf.name]
            py_key, alias = _safe_model_field_key(mcp_name)
            field_defs[py_key] = _clone_field_info(qf.field_info, external_alias=alias)
        elif qf.name in RESERVED_TOOL_CONTEXT_PARAMS:
            if qf.name not in context_params_list:
                context_params_list.append(qf.name)
        else:
            py_key, alias = _safe_model_field_key(qf.name)
            field_defs[py_key] = _clone_field_info(qf.field_info, external_alias=alias)

    for hf in dep.header_params:
        header_defaults[hf.name] = None if hf.field_info.is_required() else hf.field_info.default

    body_model: Optional[Type[BaseModel]] = None
    body_param_name: Optional[str] = None
    body_is_optional = False
    if dep.body_params:
        bf = dep.body_params[0]
        body_param_name = bf.name
        body_model, unwrapped_opt = unwrap_body_model_type(bf.field_info.annotation)
        body_is_optional = bool(unwrapped_opt or not bf.field_info.is_required())
        if body_model is not None:
            for fname, finfo in body_model.model_fields.items():
                if fname in spec.context_remaps:
                    mcp_name = spec.context_remaps[fname]
                    py_key, alias = _safe_model_field_key(mcp_name)
                    field_defs[py_key] = _clone_field_info(
                        finfo, force_optional=body_is_optional, external_alias=alias
                    )
                elif fname in RESERVED_TOOL_CONTEXT_PARAMS:
                    if fname not in context_params_list:
                        context_params_list.append(fname)
                else:
                    py_key, alias = _safe_model_field_key(fname)
                    field_defs[py_key] = _clone_field_info(
                        finfo, force_optional=body_is_optional, external_alias=alias
                    )

    for extra_name, extra_pair in spec.extra_fields.items():
        field_defs[extra_name] = extra_pair

    model_cls_name = "".join(part.capitalize() for part in spec.tool_name.split("_")) + "InputContract"
    input_model = create_model(
        model_cls_name,
        __config__=ConfigDict(extra="forbid", populate_by_name=True),
        **field_defs,
    )
    input_schema = build_mcp_input_schema(input_model)

    resp_model = route.response_model
    output_model: Optional[Type[BaseModel]] = (
        resp_model if isinstance(resp_model, type) and issubclass(resp_model, BaseModel) else None
    )

    raw_doc = (route.description or route.summary or getattr(route.endpoint, "__doc__", "") or "").strip()
    first_para = " ".join(raw_doc.splitlines()).strip() if raw_doc else ""
    description = first_para or f"Execute Carefold {spec.category} operation ({spec.method} {spec.path})."

    return ApiMcpOperationContract(
        spec=spec,
        route=route,
        endpoint=route.endpoint,
        input_model=input_model,
        input_schema=input_schema,
        output_model=output_model,
        body_model=body_model,
        body_param_name=body_param_name,
        body_is_optional=body_is_optional,
        path_param_names=tuple(path_names),
        query_param_defaults=query_defaults,
        header_param_defaults=header_defaults,
        request_param_name=dep.request_param_name,
        context_params=tuple(context_params_list),
        context_remaps=dict(spec.context_remaps),
        description=description,
    )


_CACHED_CONTRACTS_BY_TOOL: Optional[Dict[str, ApiMcpOperationContract]] = None
_CACHED_CONTRACTS_BY_ROUTE: Optional[Dict[Tuple[str, str], ApiMcpOperationContract]] = None


def _ensure_contracts_loaded() -> Tuple[
    Dict[str, ApiMcpOperationContract],
    Dict[Tuple[str, str], ApiMcpOperationContract],
]:
    global _CACHED_CONTRACTS_BY_TOOL, _CACHED_CONTRACTS_BY_ROUTE
    if _CACHED_CONTRACTS_BY_TOOL is not None and _CACHED_CONTRACTS_BY_ROUTE is not None:
        return _CACHED_CONTRACTS_BY_TOOL, _CACHED_CONTRACTS_BY_ROUTE

    from carefold.api.router import api_router

    route_lookup: Dict[Tuple[str, str], APIRoute] = {}
    for route, rel_path, inc in walk_fastapi_api_routes(api_router, prefix="/api/v1", include_in_schema=True):
        for method in (route.methods or ()):
            if method in ("HEAD", "OPTIONS"):
                continue
            key = (method.upper(), rel_path)
            if key not in route_lookup or inc:
                route_lookup[key] = route

    by_tool: Dict[str, ApiMcpOperationContract] = {}
    by_route: Dict[Tuple[str, str], ApiMcpOperationContract] = {}
    for spec in CANONICAL_DOMAIN_ROUTE_SPECS:
        contract = _build_contract_for_spec(spec, route_lookup)
        if spec.tool_name in by_tool:
            raise ValueError(f"Duplicate canonical MCP tool name '{spec.tool_name}'.")
        by_tool[spec.tool_name] = contract
        by_route[(spec.method.upper(), spec.path)] = contract

    _CACHED_CONTRACTS_BY_TOOL = by_tool
    _CACHED_CONTRACTS_BY_ROUTE = by_route
    return by_tool, by_route


def get_api_mcp_contracts_by_tool() -> Dict[str, ApiMcpOperationContract]:
    """Returns canonical API<->MCP contracts keyed by MCP tool name."""
    by_tool, _ = _ensure_contracts_loaded()
    return dict(by_tool)


def get_api_mcp_contracts_by_route() -> Dict[Tuple[str, str], ApiMcpOperationContract]:
    """Returns canonical API<->MCP contracts keyed by `(HTTP_METHOD, '/api/v1/...')`."""
    _, by_route = _ensure_contracts_loaded()
    return dict(by_route)


def get_api_mcp_contract(tool_name: str) -> ApiMcpOperationContract:
    """Returns a single canonical API<->MCP contract by MCP tool name."""
    by_tool, _ = _ensure_contracts_loaded()
    clean = (tool_name or "").strip()
    if clean not in by_tool:
        raise KeyError(f"Unknown Carefold API<->MCP parity tool '{tool_name}'.")
    return by_tool[clean]


__all__ = [
    "ApiMcpOperationContract",
    "CANONICAL_DOMAIN_ROUTE_SPECS",
    "CanonicalRouteSpec",
    "build_mcp_input_schema",
    "get_api_mcp_contract",
    "get_api_mcp_contracts_by_route",
    "get_api_mcp_contracts_by_tool",
    "unwrap_body_model_type",
    "walk_fastapi_api_routes",
]
