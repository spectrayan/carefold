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
    ]


def create_default_registry() -> ToolSpecRegistry:
    """Creates a ToolSpecRegistry populated with all 10 Carefold built-in tools."""
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
