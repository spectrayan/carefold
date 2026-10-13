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

"""Central ToolSpec registry, risk classification, and profile filtering (AU-16).

Defines:
- RiskTier: 4 explicit security risk tiers ("read", "write_local", "write_external", "irreversible")
- TrustLevel: "trusted" vs "untrusted" input/output provenance classification
- DataFlows: Outbound network egress and data sensitivity policy metadata
- ToolSpec: Immutable specification declaring parameters, risk tier, data flows, and executor
- ToolSpecRegistry: Tool catalog with age-band and profile capability filtering
- create_default_registry: Factory populating all 9 Carefold built-in tools
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import inspect
import logging
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

logger = logging.getLogger("carefold.engine.tool_registry")

RiskTier = Literal["read", "write_local", "write_external", "irreversible"]
TrustLevel = Literal["trusted", "untrusted"]


@dataclass(frozen=True)
class DataFlows:
    """Outbound network egress allowlist and data sensitivity tagging.

    Implements a dual interface: structured dataclass attributes for engine
    inspection (.allowed_hosts, .allowed_methods, .data_sensitivity) and
    sequence emulation (__iter__, __contains__, __len__, __getitem__, __eq__) for backwards
    compatibility with tuple/list comparisons in existing tests and connectors.
    """

    allowed_hosts: Tuple[str, ...] = field(default_factory=tuple)
    allowed_methods: Tuple[str, ...] = ("GET", "POST")
    data_sensitivity: str = "internal"  # "public", "internal", "confidential", "phi", "pii"

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_hosts, tuple):
            object.__setattr__(
                self,
                "allowed_hosts",
                tuple(str(h).strip() for h in (self.allowed_hosts or ()) if str(h).strip()),
            )
        if not isinstance(self.allowed_methods, tuple):
            object.__setattr__(
                self,
                "allowed_methods",
                tuple(str(m).strip() for m in (self.allowed_methods or ()) if str(m).strip()),
            )

    def __iter__(self):
        """Allows iterating over allowed hostnames directly."""
        return iter(self.allowed_hosts)

    def __contains__(self, item: Any) -> bool:
        """Enables 'host in data_flows' checks."""
        if isinstance(item, str):
            item_clean = item.lower().strip()
            return item_clean in [h.lower().strip() for h in self.allowed_hosts]
        return item in self.allowed_hosts

    def __len__(self) -> int:
        """Enables 'len(data_flows)' checks."""
        return len(self.allowed_hosts)

    def __getitem__(self, index: int) -> str:
        """Enables indexing 'data_flows[0]'."""
        return self.allowed_hosts[index]

    def __eq__(self, other: Any) -> bool:
        """Enables equality comparisons with DataFlows, tuples, or lists of hostnames."""
        if isinstance(other, DataFlows):
            return (
                self.allowed_hosts == other.allowed_hosts
                and self.allowed_methods == other.allowed_methods
                and self.data_sensitivity == other.data_sensitivity
            )
        if isinstance(other, (tuple, list, set)):
            return tuple(self.allowed_hosts) == tuple(other)
        return False


def _normalize_data_flows(df: Union[DataFlows, Sequence[str], None]) -> DataFlows:
    """Converts a sequence of hostnames or None into a typed DataFlows instance."""
    if df is None:
        return DataFlows()
    if isinstance(df, DataFlows):
        return df
    if isinstance(df, (tuple, list, set)):
        return DataFlows(allowed_hosts=tuple(str(h).strip() for h in df if str(h).strip()))
    return DataFlows()


@dataclass(frozen=True)
class ToolSpec:
    """Immutable specification and policy declaration for an executable tool."""

    name: str
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    risk_tier: RiskTier = "read"
    trust: TrustLevel = "trusted"
    data_flows: Union[DataFlows, Sequence[str]] = field(default_factory=DataFlows)
    executor: Optional[Callable[..., Any]] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    handler: Optional[Callable[..., Any]] = None  # Connector protocol alias

    def __post_init__(self) -> None:
        """Harmonizes executor/handler aliases and normalizes data_flows to DataFlows."""
        # 1. Harmonize executor and handler aliases
        if self.executor is not None and self.handler is None:
            object.__setattr__(self, "handler", self.executor)
        elif self.handler is not None and self.executor is None:
            object.__setattr__(self, "executor", self.handler)

        # 2. Normalize data_flows
        if not isinstance(self.data_flows, DataFlows):
            normalized = _normalize_data_flows(self.data_flows)
            object.__setattr__(self, "data_flows", normalized)

        # 3. Guard parameters and metadata
        if self.parameters is None:
            object.__setattr__(self, "parameters", {})
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


class ToolSpecRegistry:
    """Central registry for ToolSpecs with profile-scoped and age-band filtering."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """Registers or updates a tool specification in the registry."""
        if not isinstance(spec, ToolSpec):
            raise TypeError(f"Expected ToolSpec instance, got {type(spec).__name__}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        """Retrieves a ToolSpec by name. Returns None safely if not found."""
        return self._tools.get(name)

    def list_all(self) -> List[ToolSpec]:
        """Returns all registered tool specifications."""
        return list(self._tools.values())

    def resolve(self, names: Sequence[str]) -> List[ToolSpec]:
        """Resolves a list of tool names to matching ToolSpec instances."""
        resolved: List[ToolSpec] = []
        for name in names:
            spec = self._tools.get(name)
            if spec is not None:
                resolved.append(spec)
        return resolved

    def list_for_profile(
        self,
        profile_id: str,
        consents: Optional[Mapping[str, bool]] = None,
        age_band: str = "adult",
        capabilities: Optional[Sequence[str]] = None,
    ) -> List[ToolSpec]:
        """Filters registered tools based on profile age band and capability constraints.

        Rules:
        1. Default age band: empty string or None defaults to 'adult'.
        2. Child under 13 restrictions:
           - 'write_external' tools are strictly excluded.
           - 'untrusted' (unvetted) tools are strictly excluded.
           - 'write_local' tools require explicit guardian consent (consents['guardian_consent'] is True).
           - 'irreversible' tools are strictly excluded.
           - 'read' tools are permitted.
        3. Capability restrictions:
           - If a tool specifies 'required_capabilities' in metadata, the profile must possess them.
        """
        effective_age_band = (age_band or "adult").strip().lower()
        effective_consents = consents or {}
        has_guardian_consent = bool(effective_consents.get("guardian_consent") is True)
        enabled_caps = set(capabilities or ())

        allowed: List[ToolSpec] = []

        for spec in self._tools.values():
            # 1. Capability Check
            required_caps = spec.metadata.get("required_capabilities")
            if required_caps:
                if not any(rc in enabled_caps for rc in required_caps):
                    continue

            # 2. Child under 13 Gate
            if effective_age_band == "child_under_13":
                # External writes strictly forbidden for children under 13
                if spec.risk_tier == "write_external":
                    continue

                # Untrusted/unvetted tools forbidden for children under 13
                if spec.trust == "untrusted":
                    continue

                # Local writes require explicit guardian consent
                if spec.risk_tier == "write_local" and not has_guardian_consent:
                    continue

                # Irreversible actions strictly forbidden for children
                if spec.risk_tier == "irreversible":
                    continue

            allowed.append(spec)

        return allowed


# ============================================================================
# Built-in Tool Adapters & Factory
# ============================================================================

def _make_builtin_specs() -> List[ToolSpec]:
    """Generates ToolSpecs for all 9 Carefold built-in tools with lazy-loaded executors."""

    # 1. attach-read
    async def _exec_attach_read(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.attach_read import execute_attach_read
        return await execute_attach_read(args, ctx)

    spec_attach_read = ToolSpec(
        name="attach-read",
        description="Read a text or PDF file located in the workspace attachments directory.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": 'Filename or path of attachment (e.g. "blood_work.txt", "benefits.pdf").',
                }
            },
            "required": ["path"],
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_attach_read,
    )

    # 2. workspace-note
    async def _exec_workspace_note(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.workspace_note import execute_workspace_note
        return await execute_workspace_note(args, ctx)

    spec_workspace_note = ToolSpec(
        name="workspace-note",
        description="Save a new markdown note into the workspace notes directory.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the note."},
                "content": {"type": "string", "description": "Markdown formatted note content."},
            },
            "required": ["title", "content"],
        },
        risk_tier="write_local",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="internal"),
        executor=_exec_workspace_note,
    )

    # 3. skill-docs
    async def _exec_skill_docs(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.skill_docs import execute_skill_docs
        return await execute_skill_docs(args, ctx)

    spec_skill_docs = ToolSpec(
        name="skill-docs",
        description="Read documentation or reference files from an installed skill references directory.",
        parameters={
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "ID of the skill owning reference doc."},
                "doc": {"type": "string", "description": 'Filename of reference doc (e.g. "checklist.md").'},
            },
            "required": ["skill_id", "doc"],
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="public"),
        executor=_exec_skill_docs,
    )

    # 4. delegate_to_agent
    async def _exec_delegate_to_agent(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.delegation_tools import DelegateToAgentTool
        tool = DelegateToAgentTool()
        agent_id = str(args.get("agent_id", "")).strip()
        instructions = str(args.get("instructions", "")).strip()
        return await tool._arun(agent_id=agent_id, instructions=instructions)

    spec_delegate_to_agent = ToolSpec(
        name="delegate_to_agent",
        description="Delegate the user's request to a specialist agent by ID, providing instructions.",
        parameters={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Target specialist agent ID."},
                "instructions": {"type": "string", "description": "Instructions for specialist agent."},
            },
            "required": ["agent_id"],
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="internal"),
        executor=_exec_delegate_to_agent,
    )

    # 5. list_agents
    async def _exec_list_agents(args: Optional[Dict[str, Any]] = None, ctx: Any = None) -> Any:
        from carefold.tools.delegation_tools import ListAgentsTool
        tool = ListAgentsTool()
        return await tool._arun()

    spec_list_agents = ToolSpec(
        name="list_agents",
        description="List all available specialist agents and their capabilities from the catalog.",
        parameters={"type": "object", "properties": {}},
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="public"),
        executor=_exec_list_agents,
    )

    # 6. sanitize_pii
    async def _exec_sanitize_pii(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.extraction_tools import SanitizePIITool
        tool = SanitizePIITool()
        text = str(args.get("text", ""))
        mask_type = str(args.get("mask_type", "tag"))
        return await tool._arun(text=text, mask_type=mask_type)

    spec_sanitize_pii = ToolSpec(
        name="sanitize_pii",
        description="Mask direct PII (SSN, MRN, phone, address, email) in text before processing.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Source text to mask."},
                "mask_type": {"type": "string", "description": "'tag' or 'redacted'."},
            },
            "required": ["text"],
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="pii"),
        executor=_exec_sanitize_pii,
    )

    # 7. extract_structured_data
    async def _exec_extract_structured_data(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.extraction_tools import ExtractStructuredDataTool
        tool = ExtractStructuredDataTool()
        text = str(args.get("text", ""))
        schema_type = str(args.get("schema_type", "generic"))
        return await tool._arun(text=text, schema_type=schema_type)

    spec_extract_structured_data = ToolSpec(
        name="extract_structured_data",
        description="Extract structured data from text into a typed Pydantic schema.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Sanitized document text."},
                "schema_type": {"type": "string", "description": "'insurance', 'clinical', or 'generic'."},
            },
            "required": ["text"],
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_extract_structured_data,
    )

    # 8. validate_grounding
    async def _exec_validate_grounding(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.extraction_tools import ValidateGroundingTool
        tool = ValidateGroundingTool()
        dossier = args.get("dossier", {})
        source_text = str(args.get("source_text", ""))
        return await tool._arun(dossier=dossier, source_text=source_text)

    spec_validate_grounding = ToolSpec(
        name="validate_grounding",
        description="Validate that extracted numerical values match source document text.",
        parameters={
            "type": "object",
            "properties": {
                "dossier": {"description": "Extracted dossier dictionary or model."},
                "source_text": {"type": "string", "description": "Raw un-sanitized source text."},
            },
            "required": ["dossier", "source_text"],
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_validate_grounding,
    )

    # 9. extract_document_dossier
    async def _exec_extract_document_dossier(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.workflows.subgraphs.extraction.tool import extract_document_dossier
        return await extract_document_dossier._arun(**(args or {}))

    spec_extract_document_dossier = ToolSpec(
        name="extract_document_dossier",
        description="Composite pipeline: ingestion, PII sanitization, schema extraction, and grounding.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Relative path in attachments/."},
                "document_text": {"type": "string", "description": "Raw document text if loaded."},
                "dossier_type": {"type": "string", "description": "'insurance', 'clinical', or 'generic'."},
            },
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_extract_document_dossier,
    )

    # 10. search_records (AU-26)
    async def _exec_search_records(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.search_records import execute_search_records
        return await execute_search_records(args or {}, ctx)

    spec_search_records = ToolSpec(
        name="search_records",
        description="Search patient medical records, attachments, and clinical notes.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query or keywords to search across health records.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of search results to retrieve (default: 5).",
                    "default": 5,
                },
                "mode": {
                    "type": "string",
                    "description": "Search mode: 'hybrid', 'lexical', or 'semantic' (default: 'hybrid').",
                    "default": "hybrid",
                },
                "source": {
                    "type": "string",
                    "description": "Optional filter by record source ('clinical_note', 'upload', 'note', 'connector', 'external').",
                    "default": None,
                },
            },
            "required": ["query"],
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_search_records,
    )

    # 11. record_vitals (AU-30, AU-31, AU-32)
    async def _exec_record_vitals(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.record_vitals import execute_record_vitals
        return await execute_record_vitals(args or {}, ctx)

    spec_record_vitals = ToolSpec(
        name="record_vitals",
        description=(
            "Record vital signs observations (blood pressure, heart rate, blood glucose, "
            "SpO2, weight, height) for a patient profile with automated red-flag safety screening, "
            "adult BMI computation, and CDC pediatric percentiles."
        ),
        parameters={
            "type": "object",
            "properties": {
                "vitals_data": {
                    "type": "object",
                    "description": "Key-value dictionary containing vital sign measurements.",
                },
                "reported_symptoms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of patient-reported concurrent acute or neurological symptoms.",
                },
                "recorded_at": {
                    "type": "string",
                    "description": "Optional ISO-8601 observation timestamp.",
                },
                "source_type": {
                    "type": "string",
                    "enum": ["manual", "device", "note_extracted"],
                    "default": "manual",
                },
                "source_ref": {
                    "type": "string",
                },
                "source_id": {
                    "type": "string",
                },
            },
            "required": ["vitals_data"],
        },
        risk_tier="write_local",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_record_vitals,
        metadata={
            "action": "record_vitals",
            "entity": "health_resource",
            "undoable": True,
            "risk": "write_local",
        },
    )

    # 12. create_appointment
    async def _exec_create_appointment(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.appointments import execute_create_appointment
        return await execute_create_appointment(args or {}, ctx)

    spec_create_appointment = ToolSpec(
        name="create_appointment",
        description=(
            "Schedule and record a clinical or administrative healthcare appointment for a patient "
            "profile with validated start/end timestamps, provider specialty, clinic location, "
            "and pre-visit preparation notes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Appointment title or encounter description (e.g. 'Cardiology Consultation').",
                },
                "start_time": {
                    "type": "string",
                    "description": "Scheduled start timestamp in ISO-8601 format (UTC or with timezone offset).",
                },
                "end_time": {
                    "type": "string",
                    "description": "Scheduled end timestamp in ISO-8601 format (must be strictly after start_time).",
                },
                "provider_name": {
                    "type": "string",
                    "description": "Optional name of clinician, physician, or practice (e.g. 'Dr. Sarah Connor').",
                },
                "specialty": {
                    "type": "string",
                    "description": "Medical specialty (e.g. 'Cardiology', 'Dermatology', 'Endocrinology').",
                },
                "location": {
                    "type": "string",
                    "description": "Physical clinic address, room/suite number, or telehealth URL.",
                },
                "clinic_phone": {
                    "type": "string",
                    "description": "Clinic or scheduling office phone number (e.g. '555-0144').",
                },
                "timezone": {
                    "type": "string",
                    "description": "Local appointment IANA timezone identifier (default: 'UTC').",
                    "default": "UTC",
                },
                "status": {
                    "type": "string",
                    "enum": ["requested", "scheduled", "confirmed"],
                    "default": "scheduled",
                    "description": "Initial appointment status (default: 'scheduled').",
                },
                "reason": {
                    "type": "string",
                    "description": "Chief complaint or primary purpose of appointment.",
                },
                "preparation_notes": {
                    "type": "string",
                    "description": "Pre-visit instructions (e.g. fasting requirement, records to bring).",
                },
            },
            "required": ["title", "start_time", "end_time"],
        },
        risk_tier="write_local",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_create_appointment,
        metadata={
            "action": "create_appointment",
            "entity": "appointment",
            "undoable": True,
            "risk": "write_local",
        },
    )

    # 13. list_appointments
    async def _exec_list_appointments(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.appointments import execute_list_appointments
        return await execute_list_appointments(args or {}, ctx)

    spec_list_appointments = ToolSpec(
        name="list_appointments",
        description=(
            "List upcoming or historical healthcare appointments for a patient profile with optional "
            "filtering by status, start date range, and pagination."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["requested", "scheduled", "confirmed", "completed", "cancelled"],
                    "description": "Filter by appointment lifecycle status.",
                },
                "start_after": {
                    "type": "string",
                    "description": "Filter appointments starting on or after this ISO-8601 timestamp.",
                },
                "start_before": {
                    "type": "string",
                    "description": "Filter appointments starting on or before this ISO-8601 timestamp.",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of appointments to return (default: 20).",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Number of records to skip for pagination (default: 0).",
                },
            },
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_list_appointments,
        metadata={
            "action": "list_appointments",
            "entity": "appointment",
            "risk": "read",
        },
    )

    # 14. update_appointment_status
    async def _exec_update_appointment_status(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.appointments import execute_update_appointment_status
        return await execute_update_appointment_status(args or {}, ctx)

    spec_update_appointment_status = ToolSpec(
        name="update_appointment_status",
        description=(
            "Update the status of an existing patient appointment (e.g. from 'requested' to 'confirmed', "
            "or mark 'completed' or 'cancelled') with audit event tracking."
        ),
        parameters={
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "Unique UUID of the appointment to update.",
                },
                "status": {
                    "type": "string",
                    "enum": ["requested", "scheduled", "confirmed", "completed", "cancelled"],
                    "description": "Target status transition.",
                },
                "cancellation_reason": {
                    "type": "string",
                    "description": "Optional explanation if cancelling the appointment.",
                },
            },
            "required": ["appointment_id", "status"],
        },
        risk_tier="write_local",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_update_appointment_status,
        metadata={
            "action": "update_appointment_status",
            "entity": "appointment",
            "undoable": True,
            "risk": "write_local",
        },
    )

    # 15. create_reminder
    async def _exec_create_reminder(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.reminders import execute_create_reminder
        return await execute_create_reminder(args or {}, ctx)

    spec_create_reminder = ToolSpec(
        name="create_reminder",
        description=(
            "Create a scheduled clinical or administrative reminder with optional RFC 5545 recurrence "
            "and enqueue corresponding wall-clock Job execution."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Reminder prompt or directive title.",
                },
                "next_due_at": {
                    "type": "string",
                    "description": "Scheduled ISO-8601 due timestamp.",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed clinical context, instructions, or medication guidelines.",
                },
                "category": {
                    "type": "string",
                    "enum": ["medication", "vitals", "appointment", "prep", "general"],
                    "default": "general",
                    "description": "Reminder category (default: 'general').",
                },
                "rrule": {
                    "type": "string",
                    "description": "Optional RFC 5545 recurrence rule string (e.g. 'FREQ=DAILY;INTERVAL=1').",
                },
                "timezone": {
                    "type": "string",
                    "default": "UTC",
                    "description": "Local profile IANA timezone identifier (default: 'UTC').",
                },
            },
            "required": ["title", "next_due_at"],
        },
        risk_tier="write_local",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_create_reminder,
        metadata={
            "action": "create_reminder",
            "entity": "reminder",
            "undoable": True,
            "risk": "write_local",
        },
    )

    # 16. list_reminders
    async def _exec_list_reminders(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.reminders import execute_list_reminders
        return await execute_list_reminders(args or {}, ctx)

    spec_list_reminders = ToolSpec(
        name="list_reminders",
        description=(
            "List active or filtered clinical reminders for a patient profile with optional status, "
            "category, and due date filters."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "snoozed", "completed", "missed", "cancelled"],
                    "description": "Optional status filter.",
                },
                "category": {
                    "type": "string",
                    "enum": ["medication", "vitals", "appointment", "prep", "general"],
                    "description": "Optional category filter.",
                },
                "due_before": {
                    "type": "string",
                    "description": "Filter reminders due on or before this ISO-8601 timestamp.",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of reminders to retrieve (default: 50).",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Pagination offset.",
                },
            },
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_list_reminders,
        metadata={
            "action": "list_reminders",
            "entity": "reminder",
            "risk": "read",
        },
    )

    # 17. generate_prep_pack (AU-33, AU-34)
    async def _exec_generate_prep_pack(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.prep_pack import execute_generate_prep_pack
        return await execute_generate_prep_pack(args or {}, ctx)

    spec_generate_prep_pack = ToolSpec(
        name="generate_prep_pack",
        description=(
            "Compile a comprehensive clinical visit preparation pack for an upcoming or planned "
            "consultation, synthesizing chief visit reasons, recent symptoms timeline, 30/90-day vitals "
            "trends, active medications, allergies, and prior clinical records into a structured Markdown "
            "dossier and persisted clinical note."
        ),
        parameters={
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "Optional UUID of the linked clinical appointment.",
                },
                "specialty": {
                    "type": "string",
                    "description": "Medical specialty of the encounter (e.g. 'Cardiology', 'Endocrinology').",
                },
                "visit_reason": {
                    "type": "string",
                    "description": "Primary complaint or purpose of visit (e.g. 'Hypertension follow-up').",
                },
                "doctor_questions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional prioritized list of clinical questions to include (max 5).",
                },
            },
        },
        risk_tier="write_local",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_generate_prep_pack,
        metadata={
            "action": "generate_prep_pack",
            "entity": "note",
            "undoable": True,
            "risk": "write_local",
        },
    )

    # 18. create_typed_note (AU-35)
    async def _exec_create_typed_note(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.notes import execute_create_typed_note
        return await execute_create_typed_note(args or {}, ctx)

    spec_create_typed_note = ToolSpec(
        name="create_typed_note",
        description=(
            "Create and persist a typed clinical or navigation note across 7 canonical categories "
            "('visit', 'symptom', 'question', 'after_visit', 'school', 'scratchpad', 'general') "
            "with optional appointment linking, tag categorization, search indexing, and audit logging."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Human-readable title for the note (min 1, max 255 chars).",
                },
                "content": {
                    "type": "string",
                    "description": "Markdown formatted note body content.",
                },
                "type": {
                    "type": "string",
                    "enum": ["visit", "symptom", "question", "after_visit", "school", "scratchpad", "general"],
                    "default": "general",
                    "description": "Standardized note classification type.",
                },
                "linked_appointment_id": {
                    "type": "string",
                    "description": "Optional UUID of an appointment to associate with this note.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of tag strings for categorization.",
                },
            },
            "required": ["title", "content"],
        },
        risk_tier="write_local",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_create_typed_note,
        metadata={
            "action": "create_typed_note",
            "entity": "note",
            "undoable": True,
            "risk": "write_local",
        },
    )

    # 19. check_preventive_care (AU-36)
    async def _exec_check_preventive_care(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.preventive import execute_check_preventive_care
        return await execute_check_preventive_care(args or {}, ctx)

    spec_check_preventive_care = ToolSpec(
        name="check_preventive_care",
        description=(
            "Evaluate preventive care screenings and immunisations for a patient profile "
            "against cited USPSTF Grade A/B and AAP/CDC pediatric schedules."
        ),
        parameters={
            "type": "object",
            "properties": {
                "schedule_source": {
                    "type": "string",
                    "enum": ["aap_2026", "cdc"],
                    "description": "Optional pediatric immunisation schedule source ('aap_2026' or 'cdc').",
                },
                "sex": {
                    "type": "string",
                    "enum": ["any", "female", "male"],
                    "description": "Optional biological sex filter for adult screening rules.",
                },
                "category": {
                    "type": "string",
                    "enum": ["screening", "immunisation", "well_visit"],
                    "description": "Optional category filter.",
                },
            },
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_check_preventive_care,
        metadata={
            "action": "check_preventive_care",
            "entity": "preventive_record",
            "risk": "read",
        },
    )

    # 20. update_preventive_status (AU-36)
    async def _exec_update_preventive_status(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.preventive import execute_update_preventive_status
        return await execute_update_preventive_status(args or {}, ctx)

    spec_update_preventive_status = ToolSpec(
        name="update_preventive_status",
        description=(
            "Update the status of a preventive care screening or immunisation item "
            "('due', 'completed', 'not_applicable', 'declined') for the active profile."
        ),
        parameters={
            "type": "object",
            "properties": {
                "rule_id": {
                    "type": "string",
                    "description": "Preventive rule ID from the cited YAML rule pack.",
                },
                "status": {
                    "type": "string",
                    "enum": ["due", "completed", "not_applicable", "declined"],
                    "description": "Updated preventive item status.",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional clinical or patient notes.",
                },
                "completed_at": {
                    "type": "string",
                    "description": "Optional ISO-8601 completion timestamp.",
                },
            },
            "required": ["rule_id", "status"],
        },
        risk_tier="write_local",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_update_preventive_status,
        metadata={
            "action": "update_preventive_status",
            "entity": "preventive_record",
            "undoable": True,
            "risk": "write_local",
        },
    )

    # 21. web_search (AU-37)
    async def _exec_web_search(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.web_search import execute_web_search
        return await execute_web_search(args or {}, ctx)

    spec_web_search = ToolSpec(
        name="web_search",
        description=(
            "Execute a privacy-preserving, PHI-sanitised web search via allowlisted SearXNG "
            "or Brave Search endpoints. Automatically strips patient names, DOB, SSN, MRN, "
            "phone, email, and address before any outbound request and marks results untrusted."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string (will be sanitised of PHI/PII before sending).",
                },
                "provider": {
                    "type": "string",
                    "enum": ["searxng", "brave"],
                    "default": "searxng",
                    "description": "Search provider ('searxng' or 'brave').",
                },
                "limit": {
                    "type": "integer",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Maximum number of search results to return.",
                },
                "preview_only": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, returns only the sanitised query preview without network I/O.",
                },
            },
            "required": ["query"],
        },
        risk_tier="read",
        trust="untrusted",
        data_flows=DataFlows(
            allowed_hosts=("api.search.brave.com", "localhost", "127.0.0.1", "searx.be"),
            data_sensitivity="public",
        ),
        executor=_exec_web_search,
        metadata={
            "action": "web_search",
            "risk": "read",
            "taints_context": True,
        },
    )

    # 22. stage_clinical_import (AU-38)
    async def _exec_stage_clinical_import(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.imports import execute_stage_clinical_import
        return await execute_stage_clinical_import(args or {}, ctx)

    spec_stage_clinical_import = ToolSpec(
        name="stage_clinical_import",
        description=(
            "Parse and stage a clinical or wearable export file (FHIR R4 Bundle JSON, "
            "C-CDA XML, or Apple Health export.xml with daily summary aggregation) into "
            "an ImportBatch for Review-Before-Save."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Uploaded file name (e.g. 'bundle.json', 'ccda.xml', 'export.xml').",
                },
                "content": {
                    "type": "string",
                    "description": "Raw JSON or XML content to parse and stage.",
                },
                "format": {
                    "type": "string",
                    "enum": ["fhir_r4", "ccda", "apple_health"],
                    "description": "Optional explicit file format override.",
                },
                "source_name": {
                    "type": "string",
                    "description": "Human-readable provenance origin (e.g. 'Epic MyChart', 'Apple Health').",
                },
            },
            "required": ["filename", "content"],
        },
        risk_tier="write_local",
        trust="untrusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_stage_clinical_import,
        metadata={
            "action": "stage_clinical_import",
            "entity": "import_batch",
            "risk": "write_local",
        },
    )

    # 23. commit_clinical_import (AU-38)
    async def _exec_commit_clinical_import(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.imports import execute_commit_clinical_import
        return await execute_commit_clinical_import(args or {}, ctx)

    spec_commit_clinical_import = ToolSpec(
        name="commit_clinical_import",
        description=(
            "Commit a user-reviewed staged ImportBatch into profile health_resources "
            "with provenance attribution, idempotency, and search indexing."
        ),
        parameters={
            "type": "object",
            "properties": {
                "batch_id": {
                    "type": "string",
                    "description": "UUID of the staged ImportBatch to commit.",
                },
                "selected_indices": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional 0-based indices of staged records to commit; commits all if omitted.",
                },
            },
            "required": ["batch_id"],
        },
        risk_tier="write_local",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_commit_clinical_import,
        metadata={
            "action": "commit_clinical_import",
            "entity": "import_batch",
            "undoable": True,
            "risk": "write_local",
        },
    )

    # 24. create_school_form (AU-39)
    async def _exec_create_school_form(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.school_forms import execute_create_school_form
        return await execute_create_school_form(args or {}, ctx)

    spec_create_school_form = ToolSpec(
        name="create_school_form",
        description=(
            "Create a pediatric school or camp health form with compiled draft prefill "
            "from profile immunisations, allergies, medications, and vitals, plus automatic "
            "30-day renewal reminder scheduling when expires_at is set."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Form title (e.g. 'Annual School Physical & Immunisation Form').",
                },
                "school_or_camp_name": {
                    "type": "string",
                    "description": "Name of school, daycare, or camp institution.",
                },
                "form_type": {
                    "type": "string",
                    "enum": ["physical", "immunization", "medication_authorization", "sports_clearance", "general"],
                    "default": "general",
                },
                "expires_at": {
                    "type": "string",
                    "description": "Optional ISO-8601 expiration or renewal date.",
                },
                "attachment_id": {
                    "type": "string",
                    "description": "Optional linked CAS attachment ID.",
                },
            },
            "required": ["title"],
        },
        risk_tier="write_local",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_create_school_form,
        metadata={
            "action": "create_school_form",
            "entity": "school_form",
            "undoable": True,
            "risk": "write_local",
        },
    )

    # 25. list_school_forms (AU-39)
    async def _exec_list_school_forms(args: Dict[str, Any], ctx: Any = None) -> Any:
        from carefold.tools.school_forms import execute_list_school_forms
        return await execute_list_school_forms(args or {}, ctx)

    spec_list_school_forms = ToolSpec(
        name="list_school_forms",
        description="List tracked pediatric school and camp health forms and their draft prefill data.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["draft", "active", "expired", "archived"],
                    "description": "Optional status filter.",
                },
            },
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_list_school_forms,
        metadata={
            "action": "list_school_forms",
            "entity": "school_form",
            "risk": "read",
        },
    )

    # 26. withings_latest_vitals (AU-54)
    async def _exec_withings_latest_vitals(args: Dict[str, Any], ctx: Any = None) -> Any:
        from connectors.starters.withings import WithingsConnector
        connector = WithingsConnector()
        for t in connector.tools():
            if t.name == "withings_latest_vitals" and t.handler is not None:
                return await t.handler(args or {}, ctx)
        return {"status": "ok", "records": []}

    spec_withings_latest_vitals = ToolSpec(
        name="withings_latest_vitals",
        description=(
            "Retrieve latest synchronized Withings blood pressure, heart rate, SpO2, "
            "and weight observations for the active profile."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(
            allowed_hosts=("wbsapi.withings.net", "account.withings.com"),
            data_sensitivity="phi",
        ),
        executor=_exec_withings_latest_vitals,
        metadata={
            "action": "withings_latest_vitals",
            "connector_id": "withings",
            "risk": "read",
        },
    )

    # 27. calendar_suggest_slots (AU-55 / E4.3, E5.2)
    async def _exec_calendar_suggest_slots(args: Dict[str, Any], ctx: Any = None) -> Any:
        from connectors.starters.calendar import GoogleCalendarConnector
        connector = GoogleCalendarConnector()
        for t in connector.tools():
            if t.name == "calendar_suggest_slots" and t.handler is not None:
                return await t.handler(args or {}, ctx)
        return {"slots": []}

    spec_calendar_suggest_slots = ToolSpec(
        name="calendar_suggest_slots",
        description=(
            "Query connected Google Calendar or CalDAV free/busy windows and suggest "
            "conflict-free candidate appointment times without booking anything."
        ),
        parameters={
            "type": "object",
            "properties": {
                "window_start": {"type": "string", "description": "ISO-8601 window start."},
                "window_end": {"type": "string", "description": "ISO-8601 window end."},
                "duration_minutes": {"type": "integer", "default": 30},
            },
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(
            allowed_hosts=("www.googleapis.com", "caldav.icloud.com", "caldav.fastmail.com", "localhost"),
            data_sensitivity="pii",
        ),
        executor=_exec_calendar_suggest_slots,
        metadata={
            "action": "calendar_suggest_slots",
            "connector_id": "google-calendar",
            "risk": "read",
        },
    )

    # 28. calendar_create_event (AU-55 / E4.3)
    async def _exec_calendar_create_event(args: Dict[str, Any], ctx: Any = None) -> Any:
        from connectors.starters.calendar import GoogleCalendarConnector
        connector = GoogleCalendarConnector()
        for t in connector.tools():
            if t.name == "calendar_create_event" and t.handler is not None:
                return await t.handler(args or {}, ctx)
        return {"status": "created"}

    spec_calendar_create_event = ToolSpec(
        name="calendar_create_event",
        description=(
            "Create an external calendar event on Google Calendar or CalDAV. "
            "Always requires human approval in A0/A1 autonomy modes and strips PHI from titles by default."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title (PHI stripped by default)."},
                "start_time": {"type": "string", "description": "ISO-8601 start timestamp."},
                "end_time": {"type": "string", "description": "ISO-8601 end timestamp."},
                "location": {"type": "string", "description": "Optional clinic address."},
                "strip_phi": {"type": "boolean", "default": True},
            },
            "required": ["title", "start_time", "end_time"],
        },
        risk_tier="write_external",
        trust="trusted",
        data_flows=DataFlows(
            allowed_hosts=("www.googleapis.com", "caldav.icloud.com", "caldav.fastmail.com", "localhost"),
            data_sensitivity="pii",
        ),
        executor=_exec_calendar_create_event,
        metadata={
            "action": "calendar_create_event",
            "connector_id": "google-calendar",
            "risk": "write_external",
        },
    )

    # 29. epic_smart_search_records (AU-56 / E10.3)
    async def _exec_epic_smart_search_records(args: Dict[str, Any], ctx: Any = None) -> Any:
        from connectors.starters.epic_smart import EpicSmartConnector
        connector = EpicSmartConnector()
        for t in connector.tools():
            if t.name == "epic_smart_search_records" and t.handler is not None:
                return await t.handler(args or {}, ctx)
        return {"records": [], "trust": "untrusted"}

    spec_epic_smart_search_records = ToolSpec(
        name="epic_smart_search_records",
        description=(
            "Search read-only USCDI FHIR R4 clinical records synchronized from Epic MyChart "
            "(SMART on FHIR). Results carry provenance attribution and untrusted taint."
        ),
        parameters={
            "type": "object",
            "properties": {
                "resource_type": {
                    "type": "string",
                    "enum": [
                        "Condition",
                        "MedicationRequest",
                        "AllergyIntolerance",
                        "Immunization",
                        "Observation",
                        "Encounter",
                        "DocumentReference",
                    ],
                },
                "query": {"type": "string"},
            },
        },
        risk_tier="read",
        trust="untrusted",
        data_flows=DataFlows(
            allowed_hosts=("fhir.epic.com",),
            data_sensitivity="phi",
        ),
        executor=_exec_epic_smart_search_records,
        metadata={
            "action": "epic_smart_search_records",
            "connector_id": "epic-smart",
            "risk": "read",
            "taints_context": True,
        },
    )

    return [
        spec_attach_read,
        spec_workspace_note,
        spec_skill_docs,
        spec_delegate_to_agent,
        spec_list_agents,
        spec_sanitize_pii,
        spec_extract_structured_data,
        spec_validate_grounding,
        spec_extract_document_dossier,
        spec_search_records,
        spec_record_vitals,
        spec_create_appointment,
        spec_list_appointments,
        spec_update_appointment_status,
        spec_create_reminder,
        spec_list_reminders,
        spec_generate_prep_pack,
        spec_create_typed_note,
        spec_check_preventive_care,
        spec_update_preventive_status,
        spec_web_search,
        spec_stage_clinical_import,
        spec_commit_clinical_import,
        spec_create_school_form,
        spec_list_school_forms,
        spec_withings_latest_vitals,
        spec_calendar_suggest_slots,
        spec_calendar_create_event,
        spec_epic_smart_search_records,
    ]



def create_default_registry() -> ToolSpecRegistry:
    """Creates a ToolSpecRegistry populated with Carefold built-in tools."""
    registry = ToolSpecRegistry()
    for spec in _make_builtin_specs():
        registry.register(spec)
    return registry


__all__ = [
    "DataFlows",
    "RiskTier",
    "ToolSpec",
    "ToolSpecRegistry",
    "TrustLevel",
    "create_default_registry",
]
