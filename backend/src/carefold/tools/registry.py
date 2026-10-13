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

"""Registry and execution dispatcher for Phase 0 closed tools."""

from __future__ import annotations

from typing import Any, Callable, Coroutine, Dict, List, Optional

from carefold.schemas.manifest import PHASE_0_REGISTRY
from carefold.schemas.tool import ToolResult


CLOSED_TOOL_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "attach-read": {
        "name": "attach-read",
        "description": "Read a text or PDF file located in the workspace attachments directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": 'Filename or path of the attachment in the attachments folder (e.g. "blood_work.txt", "benefits.pdf").',
                }
            },
            "required": ["path"],
        },
    },
    "workspace-note": {
        "name": "workspace-note",
        "description": "Save a new markdown note into the workspace notes directory and return its saved relative and absolute paths. Only use this when explicitly asked to record, save, or write a note. Do NOT call this tool when the user is merely asking questions about existing notes, their locations, or their file paths.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title for the note (letters, numbers, hyphens).",
                },
                "content": {
                    "type": "string",
                    "description": "Markdown formatted note content to record.",
                },
            },
            "required": ["title", "content"],
        },
    },
    "skill-docs": {
        "name": "skill-docs",
        "description": "Read documentation or reference files from an installed skill references directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id": {
                    "type": "string",
                    "description": "The ID of the skill owning the reference document.",
                },
                "doc": {
                    "type": "string",
                    "description": 'Filename of the reference document (e.g. "checklist.md").',
                },
            },
            "required": ["skill_id", "doc"],
        },
    },
    "search_records": {
        "name": "search_records",
        "description": "Search patient medical records, attachments, and clinical notes.",
        "parameters": {
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
                },
            },
            "required": ["query"],
        },
    },
}

from carefold.tools.attach_read import execute_attach_read
from carefold.tools.search_records import execute_search_records
from carefold.tools.skill_docs import execute_skill_docs
from carefold.tools.workspace_note import execute_workspace_note

TOOL_EXECUTORS: Dict[str, Callable[[Dict[str, Any], Any], Coroutine[Any, Any, ToolResult]]] = {
    "attach-read": execute_attach_read,
    "workspace-note": execute_workspace_note,
    "skill-docs": execute_skill_docs,
    "search_records": execute_search_records,
}


def get_closed_tool(name: str) -> Optional[Dict[str, Any]]:
    """Returns the closed tool definition if available in Phase 0 registry."""
    return CLOSED_TOOL_DEFINITIONS.get(name)


def get_all_tool_definitions() -> List[Dict[str, Any]]:
    """Returns all Phase 0 closed tool definitions."""
    return list(CLOSED_TOOL_DEFINITIONS.values())


async def execute_tool(name: str, params: Dict[str, Any], context: Any) -> ToolResult:
    """Dispatches and executes a tool safely."""
    executor = TOOL_EXECUTORS.get(name)
    if not executor:
        return ToolResult(
            success=False,
            output=None,
            error=f'Tool "{name}" is not recognized or not available in the Phase 0 closed tool registry.',
        )

    try:
        return await executor(params, context)
    except Exception as err:
        return ToolResult(
            success=False,
            output=None,
            error=f"Tool execution failed: {err}",
        )
