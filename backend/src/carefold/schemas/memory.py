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

"""Pydantic schemas for REST memory management endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class MemoryRecordResponse(BaseModel):
    """Schema representing an individual cognitive memory record."""

    model_config = ConfigDict(extra="ignore")

    key: str = Field(..., description="Unique memory identifier within namespace")
    value: Any = Field(..., description="Memory payload content or structured value")
    tier: str = Field(..., description="Cognitive tier (working, episodic, semantic, procedural)")
    namespace: str = Field(default="default", description="Memory isolation namespace")
    created_at: Optional[datetime] = Field(
        default=None, description="UTC timestamp when the memory record was created"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional metadata dictionary, tags, and provenance"
    )
    score: Optional[float] = Field(
        default=None, description="Relevance or BM25 retrieval score"
    )
    salience: Optional[float] = Field(
        default=None, description="Salience retrieval weight of the memory record"
    )

    @field_validator("created_at", mode="before")
    @classmethod
    def parse_created_at(cls, v: Any) -> Optional[datetime]:
        """Parses ISO-8601 strings, timestamps, or preserves datetime objects."""
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None
        if isinstance(v, (int, float)):
            try:
                return datetime.fromtimestamp(v, tz=timezone.utc)
            except (ValueError, TypeError, OverflowError):
                return None
        return None


class MemoryDeleteResponse(BaseModel):
    """Schema representing the outcome of a memory deletion request."""

    deleted: bool = Field(..., description="Whether the record was found and deleted")
    key: str = Field(..., description="Key of the requested memory record")
    namespace: str = Field(default="default", description="Namespace of the requested memory record")


class MemoryStatusResponse(BaseModel):
    """Schema reporting active cognitive memory backend health and configuration."""

    backend: str = Field(..., description="Active memory backend name ('spector', 'sqlite')")
    healthy: bool = Field(..., description="Health status of the primary memory backend")
    fallback_active: bool = Field(
        ..., description="True if resilient fallback storage is currently serving requests"
    )
    spector_url: str = Field(..., description="Configured Spector Synapse service endpoint URL")
    cooldown_seconds: float = Field(
        ..., description="Circuit breaker cooldown duration before re-probing Spector"
    )


class MemoryUpdateRequest(BaseModel):
    """Schema representing an update or upsert request for a cognitive memory record."""

    model_config = ConfigDict(extra="ignore")

    value: Any = Field(..., description="Memory payload content or structured value")
    tier: Optional[str] = Field(
        default=None,
        description="Optional cognitive tier (working, episodic, semantic, procedural)",
    )
    namespace: Optional[str] = Field(
        default="default",
        description="Memory isolation namespace",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional metadata dictionary, tags, and provenance",
    )


class MemoryBulkDeleteResponse(BaseModel):
    """Schema representing the outcome of a bulk memory deletion request."""

    deleted: bool = Field(default=True, description="Whether the bulk deletion operation succeeded")
    deleted_count: int = Field(..., description="Number of memory records deleted")
    namespace: str = Field(default="default", description="Namespace from which records were deleted")


__all__ = [
    "MemoryRecordResponse",
    "MemoryDeleteResponse",
    "MemoryStatusResponse",
    "MemoryUpdateRequest",
    "MemoryBulkDeleteResponse",
]
