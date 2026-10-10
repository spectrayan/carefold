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

API_V1_PREFIX: str = "/api/v1"
API_PREFIX: str = "/api"

# Canonical Version 1 endpoint paths
API_V1_HEALTH: str = f"{API_V1_PREFIX}/health"
API_V1_CHAT: str = f"{API_V1_PREFIX}/chat"
API_V1_CHAT_THREADS: str = f"{API_V1_PREFIX}/chat/threads/{{thread_id}}"
API_V1_AGENTS: str = f"{API_V1_PREFIX}/agents"
API_V1_AGENTS_CATEGORIES: str = f"{API_V1_PREFIX}/agents/categories"
API_V1_AGENT_DETAIL: str = f"{API_V1_PREFIX}/agents/{{agent_id}}"
API_V1_SKILLS: str = f"{API_V1_PREFIX}/skills"
API_V1_SKILL_DETAIL: str = f"{API_V1_PREFIX}/skills/{{skill_id}}"
API_V1_AUDIT: str = f"{API_V1_PREFIX}/audit"
API_V1_MODELS: str = f"{API_V1_PREFIX}/models"
API_V1_ATTACHMENTS: str = f"{API_V1_PREFIX}/attachments"
API_V1_NOTES: str = f"{API_V1_PREFIX}/notes"
API_V1_NOTE_DETAIL: str = f"{API_V1_PREFIX}/notes/{{slug}}"
API_V1_PROFILES: str = f"{API_V1_PREFIX}/profiles"
API_V1_MEMORY: str = f"{API_V1_PREFIX}/memory"
API_V1_MEMORY_STATUS: str = f"{API_V1_PREFIX}/memory/status"
API_V1_AUTH: str = f"{API_V1_PREFIX}/auth"
API_V1_AUTH_PROVIDERS: str = f"{API_V1_PREFIX}/auth/providers"
API_V1_AUTH_SETUP_STATUS: str = f"{API_V1_PREFIX}/auth/setup-status"
API_V1_AUTH_STATUS: str = f"{API_V1_PREFIX}/auth/status"
API_V1_AUTH_REGISTER: str = f"{API_V1_PREFIX}/auth/register"
API_V1_AUTH_LOGIN: str = f"{API_V1_PREFIX}/auth/login"
API_V1_AUTH_LOGOUT: str = f"{API_V1_PREFIX}/auth/logout"
API_V1_AUTH_ME: str = f"{API_V1_PREFIX}/auth/me"
API_V1_ADMIN: str = f"{API_V1_PREFIX}/admin"
API_V1_ADMIN_SETTINGS: str = f"{API_V1_PREFIX}/admin/settings"
API_V1_ADMIN_USERS: str = f"{API_V1_PREFIX}/admin/users"
API_V1_ADMIN_DIAGNOSTICS: str = f"{API_V1_PREFIX}/admin/diagnostics"

# Legacy unversioned endpoint paths (maintained for backward compatibility)
API_HEALTH: str = f"{API_PREFIX}/health"
HEALTH_ENDPOINT: str = API_HEALTH

API_CHAT: str = f"{API_PREFIX}/chat"
CHAT_ENDPOINT: str = API_CHAT

API_CHAT_THREADS: str = f"{API_PREFIX}/chat/threads/{{thread_id}}"
CHAT_THREADS_ENDPOINT: str = API_CHAT_THREADS

API_AGENTS: str = f"{API_PREFIX}/agents"
AGENTS_ENDPOINT: str = API_AGENTS

API_AGENTS_CATEGORIES: str = f"{API_PREFIX}/agents/categories"
AGENTS_CATEGORIES_ENDPOINT: str = API_AGENTS_CATEGORIES

API_AGENT_DETAIL: str = f"{API_PREFIX}/agents/{{agent_id}}"
AGENT_DETAIL_ENDPOINT: str = API_AGENT_DETAIL

API_SKILLS: str = f"{API_PREFIX}/skills"
SKILLS_ENDPOINT: str = API_SKILLS

API_SKILL_DETAIL: str = f"{API_PREFIX}/skills/{{skill_id}}"
SKILL_DETAIL_ENDPOINT: str = API_SKILL_DETAIL

API_AUDIT: str = f"{API_PREFIX}/audit"
AUDIT_ENDPOINT: str = API_AUDIT

API_MODELS: str = f"{API_PREFIX}/models"
MODELS_ENDPOINT: str = API_MODELS

API_ATTACHMENTS: str = f"{API_PREFIX}/attachments"
ATTACHMENTS_ENDPOINT: str = API_ATTACHMENTS

API_NOTES: str = f"{API_PREFIX}/notes"
NOTES_ENDPOINT: str = API_NOTES

API_NOTE_DETAIL: str = f"{API_PREFIX}/notes/{{slug}}"
NOTE_DETAIL_ENDPOINT: str = API_NOTE_DETAIL

API_PROFILES: str = f"{API_PREFIX}/profiles"
PROFILES_ENDPOINT: str = API_PROFILES

API_MEMORY: str = f"{API_PREFIX}/memory"
MEMORY_ENDPOINT: str = API_MEMORY

API_MEMORY_STATUS: str = f"{API_PREFIX}/memory/status"

API_AUTH: str = f"{API_PREFIX}/auth"
AUTH_ENDPOINT: str = API_AUTH

API_AUTH_PROVIDERS: str = f"{API_PREFIX}/auth/providers"
API_AUTH_SETUP_STATUS: str = f"{API_PREFIX}/auth/setup-status"
API_AUTH_STATUS: str = f"{API_PREFIX}/auth/status"

API_ADMIN: str = f"{API_PREFIX}/admin"
ADMIN_ENDPOINT: str = API_ADMIN

# Sub-router relative paths (used in APIRouter decorators)
ROUTE_HEALTH: str = "/health"
ROUTE_ROOT_HEALTH: str = "/health"
ROUTE_AGENTS: str = "/agents"
ROUTE_AGENTS_CATEGORIES: str = "/agents/categories"
ROUTE_AGENT_DETAIL: str = "/agents/{agent_id}"
ROUTE_AGENT_DOCS: str = "/agents/{agent_id}/docs"
ROUTE_AGENT_DOC_DETAIL: str = "/agents/{agent_id}/docs/{doc_name}"
ROUTE_SKILLS: str = "/skills"
ROUTE_SKILL_DETAIL: str = "/skills/{skill_id}"
ROUTE_SKILL_DOCS: str = "/skills/{skill_id}/docs"
ROUTE_SKILL_DOC_DETAIL: str = "/skills/{skill_id}/docs/{doc_name}"
ROUTE_AUDIT: str = "/audit"
ROUTE_CHAT: str = "/chat"
ROUTE_CHAT_THREADS: str = "/chat/threads/{thread_id}"
ROUTE_MODELS: str = "/models"
ROUTE_ATTACHMENTS: str = "/attachments"
ROUTE_NOTES: str = "/notes"
ROUTE_NOTE_DETAIL: str = "/notes/{slug}"
ROUTE_PROFILES: str = "/profiles"


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
