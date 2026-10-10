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

"""Carefold path and filesystem constants.

Defines canonical folder names, manifest filenames, default file paths,
and environment variable keys for workspace resolution.
"""

from __future__ import annotations

# ============================================================================
# 1. Directory Names
# ============================================================================

DEFAULT_WORKSPACE_ROOT: str = "."
WORKSPACE_DIR: str = "workspace"

# Dedicated user home storage directory (M1)
DEFAULT_HOME_DIR: str = ".carefold"
UPLOADS_DIR: str = "uploads"

AGENTS_DIR: str = "agents"
SYSTEM_AGENTS_DIR: str = "_system"
TEMPLATE_DIR: str = "_template"
SKILLS_DIR: str = "skills"
ATTACHMENTS_DIR: str = "attachments"
NOTES_DIR: str = "notes"
WORKSPACE_NOTES_DIR: str = "workspace/notes"
LOGS_DIR: str = "logs"
CHATS_DIR: str = "chats"
RESOURCES_DIR: str = "resources"
REFERENCES_DIR: str = "references"


# ============================================================================
# 2. Database & Audit Log Filenames
# ============================================================================

AUDIT_LOG_FILENAME: str = "audit.jsonl"
DEFAULT_AUDIT_LOG: str = "logs/audit.jsonl"
DEFAULT_AUDIT_LOG_FILE: str = "audit.jsonl"

SQLITE_DB_FILENAME: str = "checkpoints.db"
DEFAULT_DB_PATH: str = "checkpoints.db"
DEFAULT_CHECKPOINTS_DB: str = "checkpoints.db"

CATALOG_DB_FILENAME: str = "catalog.db"
DEFAULT_CATALOG_DB: str = "catalog.db"

SQL_DB_FILENAME: str = "carefold.db"
DEFAULT_SQL_DB_PATH: str = "carefold.db"
DEFAULT_SQL_DB_FILE: str = "carefold.db"


# ============================================================================
# 3. Manifest & Asset Filenames
# ============================================================================

AGENT_MANIFEST_FILENAME: str = "agent.yaml"
AGENT_MANIFEST_FILE: str = "agent.yaml"

SKILL_MANIFEST_FILENAME: str = "SKILL.md"
SKILL_MANIFEST_FILE: str = "SKILL.md"

CAREFOLD_YAML_FILENAME: str = "carefold.yaml"
CAREFOLD_YAML_FILE: str = "carefold.yaml"
CAREFOLD_YAML_MIGRATED_FILENAME: str = "carefold.yaml.migrated"
CAREFOLD_YAML_MIGRATED_FILE: str = "carefold.yaml.migrated"

STARTERS_FILENAME: str = "starters.json"
STARTERS_FILE: str = "starters.json"

README_FILENAME: str = "README.md"
README_FILE: str = "README.md"


# ============================================================================
# 4. YAML Resource Filenames (under carefold/resources/)
# ============================================================================

DISCLAIMERS_YAML_FILE: str = "disclaimers.yaml"
REFUSAL_PATTERNS_YAML_FILE: str = "refusal_patterns.yaml"
PROMPTS_YAML_FILE: str = "prompts.yaml"
ERRORS_YAML_FILE: str = "errors.yaml"
ROUTING_PATTERNS_YAML_FILE: str = "routing_patterns.yaml"

DISCLAIMERS_YAML: str = "disclaimers.yaml"
REFUSAL_PATTERNS_YAML: str = "refusal_patterns.yaml"
PROMPTS_YAML: str = "prompts.yaml"
ERRORS_YAML: str = "errors.yaml"
ROUTING_PATTERNS_YAML: str = "routing_patterns.yaml"



# ============================================================================
# 5. Environment Variable Names
# ============================================================================

ENV_HOME_DIR: str = "CAREFOLD_HOME"
CAREFOLD_HOME: str = "CAREFOLD_HOME"
ENV_WORKSPACE_ROOT: str = "CAREFOLD_WORKSPACE_ROOT"
ENV_DB_PATH: str = "CAREFOLD_DB_PATH"
ENV_AUDIT_LOG_PATH: str = "CAREFOLD_AUDIT_LOG_PATH"
ENV_MEMORY_BACKEND: str = "CAREFOLD_MEMORY_BACKEND"
ENV_SPECTOR_URL: str = "CAREFOLD_SPECTOR_URL"
ENV_CATALOG_DB_PATH: str = "CAREFOLD_CATALOG_DB_PATH"
ENV_DATABASE_URL: str = "CAREFOLD_DATABASE_URL"
ENV_DATABASE_URL_FALLBACK: str = "DATABASE_URL"
