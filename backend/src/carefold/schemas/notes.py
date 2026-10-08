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

"""Pydantic schemas for workspace notes."""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class WorkspaceNoteSummary(BaseModel):
    """Summary of a workspace note for catalog/library listing."""

    slug: str = Field(description="Unique note slug (filename stem without .md extension)")
    title: str = Field(description="Human-readable title parsed from frontmatter, # heading, or slug")
    agent: Optional[str] = Field(default=None, description="Agent ID that created the note")
    created_at: str = Field(description="ISO-8601 UTC creation timestamp")
    size_bytes: int = Field(description="File size in bytes")


class WorkspaceNoteDetail(BaseModel):
    """Full detail of a workspace note including markdown body and frontmatter metadata."""

    slug: str = Field(description="Unique note slug")
    title: str = Field(description="Human-readable title")
    agent: Optional[str] = Field(default=None, description="Agent ID that created the note")
    created_at: str = Field(description="ISO-8601 UTC creation timestamp")
    size_bytes: int = Field(description="File size in bytes")
    content: str = Field(description="Markdown body content with frontmatter stripped")
    raw_content: str = Field(description="Raw file content including YAML frontmatter")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Parsed YAML frontmatter metadata")
    path: str = Field(description="Relative workspace path to note")


# Backward-compatibility aliases
NoteSummary = WorkspaceNoteSummary
NoteDetailResponse = WorkspaceNoteDetail

__all__ = [
    "WorkspaceNoteSummary",
    "WorkspaceNoteDetail",
    "NoteSummary",
    "NoteDetailResponse",
]
