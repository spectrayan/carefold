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

"""Carefold configuration settings via Pydantic Settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from carefold.constants.defaults import DEFAULT_CORS_ORIGINS
from carefold.constants.models import (
    DEFAULT_MODEL,
    DEFAULT_MODEL_TIMEOUT_SECONDS,
    DEFAULT_OLLAMA_URL,
    ENV_OLLAMA_URLS,
)
from carefold.constants.paths import (
    AGENTS_DIR,
    ATTACHMENTS_DIR,
    DEFAULT_AUDIT_LOG_FILE,
    DEFAULT_CATALOG_DB,
    ENV_WORKSPACE_ROOT,
    LOGS_DIR,
    NOTES_DIR,
    SKILLS_DIR,
    WORKSPACE_DIR,
    WORKSPACE_NOTES_DIR,
)


def get_default_workspace_root() -> Path:
    """Finds repository workspace root or defaults to cwd."""
    # Check CAREFOLD_WORKSPACE_ROOT env var
    env_root = os.getenv(ENV_WORKSPACE_ROOT)
    if env_root and os.path.isdir(env_root):
        return Path(env_root).resolve()

    # If backend/ is subdirectory of workspace
    current = Path.cwd().resolve()
    if (current / AGENTS_DIR).is_dir() and (current / SKILLS_DIR).is_dir():
        return current
    if (current.parent / AGENTS_DIR).is_dir() and (current.parent / SKILLS_DIR).is_dir():
        return current.parent.resolve()

    return current


def get_default_ollama_url() -> str:
    """Resolves default Ollama URL from environment variables or constant."""
    for var in ENV_OLLAMA_URLS:
        val = os.getenv(var)
        if val and val.strip():
            return val.strip()
    return DEFAULT_OLLAMA_URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAREFOLD_",
        env_file=".env",
        extra="ignore"
    )

    workspace_root: Path = get_default_workspace_root()
    ollama_url: str = Field(default_factory=get_default_ollama_url)
    default_model: str = DEFAULT_MODEL
    model_timeout_seconds: float = DEFAULT_MODEL_TIMEOUT_SECONDS

    # Logging configuration
    log_level: str = "INFO"
    log_json: bool = False

    # Audit logging configuration
    audit_log_path: Optional[Path] = None
    audit_store_bodies: bool = False

    # SQLite checkpointer database path
    db_path: Optional[Path] = None

    # Relational Database configuration (R1)
    database_url: Optional[str] = Field(
        default=None,
        description="Database URL supporting SQLite and PostgreSQL (CAREFOLD_DATABASE_URL or DATABASE_URL)",
    )

    # Memory and Catalog abstraction configuration (R2)
    memory_backend: str = "sqlite"
    spector_url: str = "http://localhost:7070"
    catalog_db_path: Optional[Path] = None
    memory_fallback_to_sqlite: bool = Field(
        default=True,
        description="Fallback to local SQLite/InMemory store if Spector is unreachable",
    )

    # Authentication provider configuration (R2)
    auth_provider: str = Field(
        default="local",
        description="Active authentication provider (local, disabled, oidc)",
    )

    # CORS configuration
    cors_origins: List[str] = list(DEFAULT_CORS_ORIGINS)

    @model_validator(mode="after")
    def _resolve_database_url(self) -> "Settings":
        if not self.database_url:
            env_cf = os.getenv("CAREFOLD_DATABASE_URL")
            if env_cf and env_cf.strip():
                self.database_url = env_cf.strip()
            else:
                env_db = os.getenv("DATABASE_URL")
                if env_db and env_db.strip():
                    self.database_url = env_db.strip()
                else:
                    self.database_url = f"sqlite+aiosqlite:///{self.workspace_root}/workspace/carefold.db"
        return self

    def get_database_url(self) -> str:
        """Resolves active database URL, honoring environment overrides or workspace root."""
        env_cf = os.getenv("CAREFOLD_DATABASE_URL")
        if env_cf and env_cf.strip():
            return env_cf.strip()
        env_db = os.getenv("DATABASE_URL")
        if env_db and env_db.strip():
            return env_db.strip()
        if self.database_url and not self.database_url.endswith("/workspace/carefold.db"):
            return self.database_url
        return f"sqlite+aiosqlite:///{self.workspace_root}/workspace/carefold.db"


    def get_catalog_db_path(self) -> Path:
        """Resolves catalog database path, defaulting to workspace_root / DEFAULT_CATALOG_DB."""
        if self.catalog_db_path is not None:
            return self.catalog_db_path
        return self.workspace_root / DEFAULT_CATALOG_DB

    def get_agents_dir(self) -> Path:
        return self.workspace_root / AGENTS_DIR

    def get_skills_dir(self) -> Path:
        return self.workspace_root / SKILLS_DIR

    def get_attachments_dir(self) -> Path:
        return self.workspace_root / ATTACHMENTS_DIR

    def get_notes_dir(self) -> Path:
        ws_notes = self.workspace_root / WORKSPACE_NOTES_DIR
        if (self.workspace_root / WORKSPACE_DIR).is_dir():
            return ws_notes
        return self.workspace_root / NOTES_DIR

    def get_audit_log_path(self) -> Path:
        if self.audit_log_path is not None:
            return self.audit_log_path
        return self.workspace_root / LOGS_DIR / DEFAULT_AUDIT_LOG_FILE


settings = Settings()
