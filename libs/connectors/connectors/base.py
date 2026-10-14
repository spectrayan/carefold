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

"""Core data structures and runtime protocol for Carefold connectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Literal,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)

if TYPE_CHECKING:
    from connectors.http import ScopedHttp
    from connectors.manifest import ConnectorManifest


@dataclass(frozen=True)
class ToolContext:
    """Immutable, fail-closed runtime context for tool and connector execution."""

    user_id: str
    profile_id: str
    principal: str = "user"
    run_id: str = ""
    mode: str = "direct"
    autonomy: str = "supervised"
    taint: Any = "untrusted"

    def __post_init__(self) -> None:
        """Enforces fail-closed invariants: user_id and profile_id must be non-empty."""
        if not self.profile_id or not str(self.profile_id).strip():
            raise ValueError("ToolContext security invariant: profile_id cannot be empty (fail-closed).")
        if not self.user_id or not str(self.user_id).strip():
            raise ValueError("ToolContext security invariant: user_id cannot be empty (fail-closed).")


@dataclass(frozen=True)
class StreamSpec:
    """Specification of an exported data stream provided by a connector."""

    name: str
    description: str = ""
    read_mode: Literal["full_refresh", "incremental"] = "incremental"
    primary_key: List[str] = field(default_factory=lambda: ["id"])
    cursor_field: Optional[str] = None
    schema: Optional[Dict[str, Any]] = None


@dataclass
class Page:
    """A page of raw records retrieved from an external data source."""

    stream: str
    records: List[Dict[str, Any]]
    next_cursor: Optional[str] = None
    has_more: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalisedRecord:
    """Standardized, patient-scoped clinical or administrative record."""

    id: str
    stream: str
    profile_id: str
    source: str
    record_type: str  # e.g. observation, medication, condition, encounter, document
    timestamp: Optional[datetime]
    data: Dict[str, Any]
    raw_hash: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ToolSpec:
    """Specification of an AI agent tool exposed by a connector."""

    name: str
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    risk_class: str = "read_only"
    handler: Optional[Callable[..., Coroutine[Any, Any, Any] | Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    risk_tier: str = "read"
    trust: str = "trusted"
    data_flows: Sequence[str] = field(default_factory=tuple)
    executor: Optional[Callable[..., Coroutine[Any, Any, Any] | Any]] = None

    def __post_init__(self) -> None:
        """Harmonizes handler and executor aliases for engine compatibility."""
        if self.executor is not None and self.handler is None:
            object.__setattr__(self, "handler", self.executor)
        elif self.handler is not None and self.executor is None:
            object.__setattr__(self, "executor", self.handler)


@runtime_checkable
class Connector(Protocol):
    """Core protocol for all Carefold external data source and EHR connectors."""

    @property
    def manifest(self) -> ConnectorManifest:
        """Declarative manifest declaring data flows, allowed hosts, and auth requirements."""
        ...

    def streams(self) -> List[StreamSpec]:
        """Returns the list of streams supported by this connector."""
        ...

    async def fetch(
        self,
        ctx: ToolContext,
        stream: str,
        cursor: Optional[str],
        http: ScopedHttp,
    ) -> Page:
        """Fetches a page of raw records from the external source using the sandboxed ScopedHttp client."""
        ...

    def map(self, page: Page) -> List[NormalisedRecord]:
        """Transforms raw source records from a page into standardized NormalisedRecords."""
        ...

    def tools(self) -> List[ToolSpec]:
        """Returns the list of agent tool specifications exposed by this connector."""
        ...


__all__ = [
    "Connector",
    "NormalisedRecord",
    "Page",
    "StreamSpec",
    "ToolContext",
    "ToolSpec",
]
