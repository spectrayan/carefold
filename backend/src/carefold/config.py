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
    DEFAULT_CHECKPOINTS_DB,
    DEFAULT_HOME_DIR,
    ENV_AUDIT_LOG_PATH,
    ENV_CATALOG_DB_PATH,
    ENV_DB_PATH,
    ENV_WORKSPACE_ROOT,
    LOGS_DIR,
    NOTES_DIR,
    SKILLS_DIR,
    SQL_DB_FILENAME,
    UPLOADS_DIR,
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


def resolve_carefold_home() -> Path:
    """Resolves the canonical Carefold home storage directory (~/.carefold).

    Resolution Precedence:
    1. CAREFOLD_HOME environment variable (or CAREFOLD_HOME_DIR)
    2. CAREFOLD_WORKSPACE_ROOT environment variable (if explicitly pointing to
       a .carefold directory or non-repository test sandbox)
    3. Cross-platform user home default: Path.home() / DEFAULT_HOME_DIR
       - Linux:   /home/<user>/.carefold
       - macOS:   /Users/<user>/.carefold
       - Windows: C:\\Users\\<user>\\.carefold (via %USERPROFILE%)

    Returns:
        Path: Absolute resolved filesystem path to the Carefold home directory.
    """
    # 1. Primary override: CAREFOLD_HOME or CAREFOLD_HOME_DIR
    env_home = os.getenv("CAREFOLD_HOME") or os.getenv("CAREFOLD_HOME_DIR")
    if env_home and env_home.strip():
        return Path(env_home.strip()).expanduser().resolve()

    # 2. Secondary override: CAREFOLD_WORKSPACE_ROOT
    env_ws = os.getenv("CAREFOLD_WORKSPACE_ROOT")
    if env_ws and env_ws.strip():
        ws_path = Path(env_ws.strip()).expanduser().resolve()
        # If explicitly pointed at a .carefold folder
        if ws_path.name == DEFAULT_HOME_DIR:
            return ws_path
        # If containing a .carefold subfolder
        if (ws_path / DEFAULT_HOME_DIR).is_dir():
            return (ws_path / DEFAULT_HOME_DIR).resolve()
        # If pointing to an isolated sandbox/test path (does not contain repository agents/skills)
        if not (ws_path / AGENTS_DIR).is_dir() and not (ws_path / "backend").is_dir():
            return ws_path

    # 3. Default: cross-platform user home directory
    return (Path.home() / DEFAULT_HOME_DIR).resolve()


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
    home_dir: Path = Field(default_factory=resolve_carefold_home)

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
        """Initializes database_url if not explicitly set."""
        if not self.database_url:
            env_cf = os.getenv("CAREFOLD_DATABASE_URL")
            if env_cf and env_cf.strip():
                self.database_url = env_cf.strip()
            else:
                env_db = os.getenv("DATABASE_URL")
                if env_db and env_db.strip():
                    self.database_url = env_db.strip()
                else:
                    self.database_url = f"sqlite+aiosqlite:///{self.home_dir}/{SQL_DB_FILENAME}"
        return self

    def get_home_dir(self) -> Path:
        """Returns the resolved root home storage directory (~/.carefold)."""
        return self.home_dir

    def get_uploads_dir(self) -> Path:
        """Returns the uploads directory (~/.carefold/uploads) managed via StoragePort."""
        return self.home_dir / UPLOADS_DIR

    def get_database_url(self) -> str:
        """Resolves active database URL, honoring environment overrides or home_dir."""
        env_cf = os.getenv("CAREFOLD_DATABASE_URL")
        if env_cf and env_cf.strip():
            return env_cf.strip()
        env_db = os.getenv("DATABASE_URL")
        if env_db and env_db.strip():
            return env_db.strip()
        # If database_url was set to a custom external DB (e.g. Postgres), preserve it.
        # Otherwise, dynamically evaluate against self.home_dir to support test isolation.
        if (
            self.database_url
            and not self.database_url.endswith("/workspace/carefold.db")
            and not (self.database_url.startswith("sqlite+aiosqlite:///") and self.database_url.endswith(f"/{SQL_DB_FILENAME}"))
        ):
            return self.database_url
        return f"sqlite+aiosqlite:///{self.home_dir}/{SQL_DB_FILENAME}"

    def get_catalog_db_path(self) -> Path:
        """Resolves catalog database path, defaulting to home_dir / DEFAULT_CATALOG_DB."""
        if self.catalog_db_path is not None:
            return self.catalog_db_path
        env_cat = os.getenv(ENV_CATALOG_DB_PATH)
        if env_cat and env_cat.strip():
            return Path(env_cat.strip()).resolve()
        return self.home_dir / DEFAULT_CATALOG_DB

    def get_checkpointer_path(self) -> Path:
        """Resolves LangGraph checkpointer SQLite database path, defaulting to home_dir / DEFAULT_CHECKPOINTS_DB."""
        if self.db_path is not None:
            return self.db_path.resolve()
        env_db = os.getenv(ENV_DB_PATH)
        if env_db and env_db.strip():
            return Path(env_db.strip()).resolve()
        return self.home_dir / DEFAULT_CHECKPOINTS_DB

    def get_audit_log_path(self) -> Path:
        """Resolves audit log path, defaulting to home_dir / logs / audit.jsonl."""
        if self.audit_log_path is not None:
            return self.audit_log_path
        env_audit = os.getenv(ENV_AUDIT_LOG_PATH)
        if env_audit and env_audit.strip():
            return Path(env_audit.strip()).resolve()
        return self.home_dir / LOGS_DIR / DEFAULT_AUDIT_LOG_FILE

    def get_agents_dir(self) -> Path:
        """Returns bundled agent definition directory (in repository)."""
        return self.workspace_root / AGENTS_DIR

    def get_skills_dir(self) -> Path:
        """Returns bundled skill packs directory (in repository)."""
        return self.workspace_root / SKILLS_DIR

    def get_attachments_dir(self) -> Path:
        """Returns attachments directory. In M1, aliases to get_uploads_dir()."""
        return self.get_uploads_dir()

    def get_notes_dir(self) -> Path:
        """Returns notes directory, rooted under home_dir to prevent writing to repository."""
        if not (self.workspace_root / "backend").is_dir() and (self.workspace_root / WORKSPACE_NOTES_DIR).is_dir():
            return self.workspace_root / WORKSPACE_NOTES_DIR
        notes_path = self.home_dir / NOTES_DIR
        notes_path.mkdir(parents=True, exist_ok=True)
        return notes_path


settings = Settings()
