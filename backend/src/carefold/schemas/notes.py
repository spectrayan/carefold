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

"""Pydantic schemas for workspace notes, typed notes, and after-visit extraction (AU-35)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

NoteCategoryLiteral = Literal[
    "visit",
    "symptom",
    "question",
    "after_visit",
    "school",
    "scratchpad",
    "general",
]


class WorkspaceNoteSummary(BaseModel):
    """Summary of a workspace note for catalog/library listing."""

    slug: str = Field(description="Unique note slug (filename stem without .md extension)")
    title: str = Field(description="Human-readable title parsed from frontmatter, # heading, or slug")
    agent: Optional[str] = Field(default=None, description="Agent ID that created the note")
    type: Optional[str] = Field(default=None, description="Canonical note category")
    profile_id: Optional[str] = Field(default=None, description="Associated care profile ID")
    linked_appointment_id: Optional[str] = Field(default=None, description="Optional linked appointment UUID")
    created_at: str = Field(description="ISO-8601 UTC creation timestamp")
    size_bytes: int = Field(description="File size in bytes")
    tags: list[str] = Field(default_factory=list, description="List of note tags")
    tags_json: str = Field(default="[]", description="Serialized JSON array of note tags")


class WorkspaceNoteDetail(BaseModel):
    """Full detail of a workspace note including markdown body and frontmatter metadata."""

    slug: str = Field(description="Unique note slug")
    title: str = Field(description="Human-readable title")
    agent: Optional[str] = Field(default=None, description="Agent ID that created the note")
    type: Optional[str] = Field(default=None, description="Canonical note category")
    profile_id: Optional[str] = Field(default=None, description="Associated care profile ID")
    linked_appointment_id: Optional[str] = Field(default=None, description="Optional linked appointment UUID")
    created_at: str = Field(description="ISO-8601 UTC creation timestamp")
    size_bytes: int = Field(description="File size in bytes")
    content: str = Field(description="Markdown body content with frontmatter stripped")
    raw_content: str = Field(description="Raw file content including YAML frontmatter")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Parsed YAML frontmatter metadata")
    path: str = Field(description="Relative workspace path to note")
    tags: list[str] = Field(default_factory=list, description="List of note tags")
    tags_json: str = Field(default="[]", description="Serialized JSON array of note tags")


class NoteCreateRequest(BaseModel):
    title: str
    content: str
    slug: Optional[str] = None
    type: str = "scratchpad"
    profile_id: Optional[str] = None
    linked_appointment_id: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class NoteUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    type: Optional[str] = None
    profile_id: Optional[str] = None
    linked_appointment_id: Optional[str] = None
    tags: Optional[list[str]] = None


class TypedNoteCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Note title")
    content: str = Field(..., min_length=1, description="Markdown body content")
    type: NoteCategoryLiteral = Field("general", description="Note category (one of 7 valid types)")
    slug: Optional[str] = Field(None, max_length=128, description="Optional custom slug")
    linked_appointment_id: Optional[str] = Field(None, description="Optional linked appointment UUID")
    tags: List[str] = Field(default_factory=list, description="Optional tags list")


class TypedNoteUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    content: Optional[str] = Field(None, min_length=1)
    type: Optional[NoteCategoryLiteral] = None
    linked_appointment_id: Optional[str] = None
    tags: Optional[List[str]] = None


class TypedNoteSummaryResponse(BaseModel):
    id: str
    profile_id: str
    slug: str
    title: str
    type: str
    linked_appointment_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    size_bytes: int
    created_at: str
    updated_at: str


class TypedNoteDetailResponse(BaseModel):
    id: str
    profile_id: str
    slug: str
    title: str
    type: str
    content: str
    linked_appointment_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    tags_json: str = "[]"
    created_at: str
    updated_at: str


class TypedNoteListResponse(BaseModel):
    notes: List[TypedNoteSummaryResponse]
    total: int
    limit: int
    offset: int


class AfterVisitExtractionResponse(BaseModel):
    note_id: str
    diagnoses: List[Dict[str, Any]]
    medication_adjustments: List[Dict[str, Any]]
    ordered_tests: List[Dict[str, Any]]
    follow_up_timeline: List[Dict[str, Any]]
    recommended_reminders: List[Dict[str, Any]] = Field(default_factory=list)
    disclaimer: str = Field(
        default="Extracted from your notes, not formal medical advice.",
        description="Mandatory non-clinical boundary disclaimer",
    )
    extracted_items_count: int = 0


# Backward-compatibility aliases
NoteSummary = WorkspaceNoteSummary
NoteDetailResponse = WorkspaceNoteDetail

__all__ = [
    "AfterVisitExtractionResponse",
    "NoteCategoryLiteral",
    "NoteCreateRequest",
    "NoteDetailResponse",
    "NoteSummary",
    "NoteUpdateRequest",
    "TypedNoteCreateRequest",
    "TypedNoteDetailResponse",
    "TypedNoteListResponse",
    "TypedNoteSummaryResponse",
    "TypedNoteUpdateRequest",
    "WorkspaceNoteDetail",
    "WorkspaceNoteSummary",
]
