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

"""Carefold defaults and boundary constants.

Defines file limits, pagination boundaries, retry thresholds, SQLite settings,
and runtime bounds.
"""

from __future__ import annotations

from typing import FrozenSet, Tuple

# ============================================================================
# 1. File Size & Ingestion Limits
# ============================================================================

MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB (10,485,760 bytes)
MAX_ATTACHMENT_SIZE: int = MAX_FILE_SIZE_BYTES  # Alias expected by tests
MAX_FILE_SIZE_MB: int = 10
MAX_ATTACHMENT_SIZE_MB: int = 10

ALLOWED_TEXT_EXTENSIONS: FrozenSet[str] = frozenset({
    ".txt", ".md", ".json", ".csv", ".tsv", ".yaml", ".yml"
})
ALLOWED_ATTACHMENT_EXTENSIONS: FrozenSet[str] = frozenset({
    ".txt", ".md", ".json", ".csv", ".tsv", ".yaml", ".yml", ".pdf"
})
ALLOWED_SKILL_DOC_EXTENSIONS: FrozenSet[str] = frozenset({
    ".md", ".txt", ".json", ".yaml", ".yml"
})


# ============================================================================
# 2. Reflection Retries & Tool Iterations
# ============================================================================

DEFAULT_MAX_RETRIES: int = 3
MAX_RETRIES: int = 3
DEFAULT_MAX_REFLECTIONS: int = 3
MAX_REFLECTION_RETRIES: int = 3  # Expected by tests

MAX_TOOL_ITERATIONS: int = 5
MAX_TOOL_OUTPUT_CHARS: int = 100_000  # Max tool output characters before truncation


# ============================================================================
# 3. Pagination & Thread History Limits
# ============================================================================

DEFAULT_PAGE_SIZE: int = 50
DEFAULT_AUDIT_LIMIT: int = 50
MIN_AUDIT_LIMIT: int = 1
MAX_AUDIT_LIMIT: int = 1000

MAX_THREAD_HISTORY: int = 50


# ============================================================================
# 4. Workspace Note Defaults
# ============================================================================

MAX_NOTE_SLUG_LENGTH: int = 80
DEFAULT_NOTE_SLUG: str = "note"
DEFAULT_NOTE_AGENT_ID: str = "carefold-agent"


# ============================================================================
# 5. SQLite & Checkpointer Defaults
# ============================================================================

SQLITE_BUSY_TIMEOUT_MS: int = 10000  # 10,000 ms = 10 seconds
SQLITE_CONNECT_TIMEOUT_SECONDS: float = 30.0
SQLITE_JOURNAL_MODE: str = "WAL"


# ============================================================================
# 6. Server & Network Defaults
# ============================================================================

DEFAULT_HOST: str = "0.0.0.0"
DEFAULT_PORT: int = 8010
DEFAULT_VERSION: str = "0.1.0"
APP_TITLE: str = "Carefold Local-First AI Runtime"
APP_DESCRIPTION: str = (
    "Local-first agentic runtime, tools sandbox, safety refusal, and audit logging for health specialists."
)

DEFAULT_CORS_ORIGINS: Tuple[str, ...] = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3010",
    "http://127.0.0.1:3010",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8010",
    "http://127.0.0.1:8010",
)


# ============================================================================
# 7. Bundled Reference Packs & Phase 0 Tools
# ============================================================================

BUNDLED_AGENT_IDS: FrozenSet[str] = frozenset({
    "orchestrator",
    "visit-steward",
    "benefits-guide",
    "habit-companion",
    "document-extractor",
    "suggestion-generator",
})


BUNDLED_SKILL_IDS: FrozenSet[str] = frozenset({
    "visit-prep",
    "benefits-explainer",
    "habit-checkin",
})

PHASE_0_TOOLS: FrozenSet[str] = frozenset({
    "attach-read",
    "workspace-note",
    "skill-docs",
    "delegate_to_agent",
    "list_agents",
    "sanitize_pii",
    "extract_structured_data",
    "validate_grounding",
})


# ============================================================================
# 8. Clinical Safety Classifier Defaults
# ============================================================================

FORBIDDEN_INTENT_PREFIX: str = "forbidden_intent:"
DEFAULT_FORBIDDEN_INTENTS: Tuple[str, ...] = (
    "diagnose",
    "prescribe",
    "dose",
    "replace_emergency_care",
    "instruct_stop_medication",
)
