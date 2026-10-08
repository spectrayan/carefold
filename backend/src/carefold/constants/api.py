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

"""Carefold API constants.

Defines route endpoints, HTTP status codes, and Server-Sent Events (SSE) names.
"""

from __future__ import annotations

# ============================================================================
# 1. API Route Prefixes & Paths
# ============================================================================

API_PREFIX: str = "/api"

# Canonical full endpoint paths (used in tests, clients, and API documentation)
API_HEALTH: str = "/api/health"
HEALTH_ENDPOINT: str = "/api/health"

API_CHAT: str = "/api/chat"
CHAT_ENDPOINT: str = "/api/chat"

API_AGENTS: str = "/api/agents"
AGENTS_ENDPOINT: str = "/api/agents"

API_AGENTS_CATEGORIES: str = "/api/agents/categories"
AGENTS_CATEGORIES_ENDPOINT: str = "/api/agents/categories"

API_SKILLS: str = "/api/skills"
SKILLS_ENDPOINT: str = "/api/skills"

API_AUDIT: str = "/api/audit"
AUDIT_ENDPOINT: str = "/api/audit"

API_CHAT_THREADS: str = "/api/chat/threads/{thread_id}"
CHAT_THREADS_ENDPOINT: str = "/api/chat/threads/{thread_id}"

API_AGENT_DETAIL: str = "/api/agents/{agent_id}"
AGENT_DETAIL_ENDPOINT: str = "/api/agents/{agent_id}"

API_SKILL_DETAIL: str = "/api/skills/{skill_id}"
SKILL_DETAIL_ENDPOINT: str = "/api/skills/{skill_id}"

API_MODELS: str = "/api/models"
MODELS_ENDPOINT: str = "/api/models"

API_ATTACHMENTS: str = "/api/attachments"
ATTACHMENTS_ENDPOINT: str = "/api/attachments"

API_NOTES: str = "/api/notes"
NOTES_ENDPOINT: str = "/api/notes"

API_NOTE_DETAIL: str = "/api/notes/{slug}"
NOTE_DETAIL_ENDPOINT: str = "/api/notes/{slug}"

# Sub-router relative paths (used in APIRouter decorators)
ROUTE_HEALTH: str = "/health"
ROUTE_ROOT_HEALTH: str = "/health"
ROUTE_AGENTS: str = "/agents"
ROUTE_AGENTS_CATEGORIES: str = "/agents/categories"
ROUTE_AGENT_DETAIL: str = "/agents/{agent_id}"
ROUTE_SKILLS: str = "/skills"
ROUTE_SKILL_DETAIL: str = "/skills/{skill_id}"
ROUTE_AUDIT: str = "/audit"
ROUTE_CHAT: str = "/chat"
ROUTE_CHAT_THREADS: str = "/chat/threads/{thread_id}"
ROUTE_MODELS: str = "/models"
ROUTE_ATTACHMENTS: str = "/attachments"
ROUTE_NOTES: str = "/notes"
ROUTE_NOTE_DETAIL: str = "/notes/{slug}"


# ============================================================================
# 2. HTTP Status Codes
# ============================================================================

HTTP_OK: int = 200
HTTP_BAD_REQUEST: int = 400
HTTP_FORBIDDEN: int = 403
HTTP_NOT_FOUND: int = 404
HTTP_INTERNAL_SERVER_ERROR: int = 500

# Explicit HTTPStatus-style aliases
HTTP_200_OK: int = 200
HTTP_400_BAD_REQUEST: int = 400
HTTP_403_FORBIDDEN: int = 403
HTTP_404_NOT_FOUND: int = 404
HTTP_500_INTERNAL_SERVER_ERROR: int = 500


# ============================================================================
# 3. Server-Sent Events (SSE) Protocol Constants
# ============================================================================

# Primary event names
SSE_EVENT_MESSAGE: str = "message"
SSE_EVENT_TOKEN: str = "token"
SSE_EVENT_TEXT_DELTA: str = "token"  # Alias required by E2E tests (tier1 & tier2)
SSE_EVENT_TOOL_START: str = "tool_start"
SSE_EVENT_TOOL_END: str = "tool_end"
SSE_EVENT_TOOL_CALL: str = "tool_call"
SSE_EVENT_REFUSAL: str = "refusal"
SSE_EVENT_SUGGESTIONS: str = "suggestions"
SSE_EVENT_DONE: str = "done"
SSE_EVENT_ERROR: str = "error"

# Aliases without SSE_ prefix (for convenience and backward-compatibility)
EVENT_MESSAGE: str = SSE_EVENT_MESSAGE
EVENT_TOKEN: str = SSE_EVENT_TOKEN
EVENT_TEXT_DELTA: str = SSE_EVENT_TEXT_DELTA
EVENT_TOOL_START: str = SSE_EVENT_TOOL_START
EVENT_TOOL_END: str = SSE_EVENT_TOOL_END
EVENT_TOOL_CALL: str = SSE_EVENT_TOOL_CALL
EVENT_REFUSAL: str = SSE_EVENT_REFUSAL
EVENT_SUGGESTIONS: str = SSE_EVENT_SUGGESTIONS
EVENT_DONE: str = SSE_EVENT_DONE
EVENT_ERROR: str = SSE_EVENT_ERROR

SSE_ALL_EVENTS: tuple[str, ...] = (
    SSE_EVENT_MESSAGE,
    SSE_EVENT_TOKEN,
    SSE_EVENT_TEXT_DELTA,
    SSE_EVENT_TOOL_START,
    SSE_EVENT_TOOL_END,
    SSE_EVENT_TOOL_CALL,
    SSE_EVENT_REFUSAL,
    SSE_EVENT_SUGGESTIONS,
    SSE_EVENT_DONE,
    SSE_EVENT_ERROR,
)

# SSE Streaming headers and wire protocol formatting
SSE_MEDIA_TYPE: str = "text/event-stream"
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
SSE_DONE_MARKER: str = "[DONE]"
