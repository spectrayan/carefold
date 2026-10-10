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

"""Unit tests for Carefold home storage isolation (~/.carefold), path resolution, and auto-migration."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import pytest

from carefold.config import Settings, resolve_carefold_home
from carefold.constants.paths import (
    DEFAULT_HOME_DIR,
    DEFAULT_CATALOG_DB,
    DEFAULT_CHECKPOINTS_DB,
    SQL_DB_FILENAME,
    UPLOADS_DIR,
)
from carefold.engine.graph import resolve_checkpointer_path
from carefold.migration.runtime_migrator import (
    _checkpoint_sqlite_database,
    _parse_markdown_note,
    run_first_launch_migration,
)


def test_resolve_carefold_home_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that resolve_carefold_home returns Path.home() / .carefold when no overrides are set."""
    monkeypatch.delenv("CAREFOLD_HOME", raising=False)
    monkeypatch.delenv("CAREFOLD_HOME_DIR", raising=False)
    monkeypatch.delenv("CAREFOLD_WORKSPACE_ROOT", raising=False)

    resolved = resolve_carefold_home()
    expected = (Path.home() / DEFAULT_HOME_DIR).resolve()
    assert resolved == expected


def test_resolve_carefold_home_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verifies CAREFOLD_HOME environment variable override."""
    custom_home = tmp_path / "custom_carefold_home"
    monkeypatch.setenv("CAREFOLD_HOME", str(custom_home))

    resolved = resolve_carefold_home()
    assert resolved == custom_home.resolve()


def test_settings_home_paths_rooting(tmp_path: Path) -> None:
    """Verifies that Settings helper methods properly root persistent storage to home_dir."""
    test_home = tmp_path / "test_home"
    s = Settings(home_dir=test_home)

    assert s.get_home_dir() == test_home
    assert s.get_uploads_dir() == test_home / UPLOADS_DIR
    assert s.get_catalog_db_path() == test_home / DEFAULT_CATALOG_DB
    assert s.get_checkpointer_path() == test_home / DEFAULT_CHECKPOINTS_DB
    assert s.get_audit_log_path() == test_home / "logs" / "audit.jsonl"
    assert s.get_notes_dir() == test_home / "notes"
    assert f"{test_home}/{SQL_DB_FILENAME}" in s.get_database_url()


def test_resolve_checkpointer_path_uses_home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that resolve_checkpointer_path uses settings.get_checkpointer_path() by default."""
    test_home = tmp_path / "checkpointer_home"
    monkeypatch.setenv("CAREFOLD_HOME", str(test_home))
    monkeypatch.delenv("CAREFOLD_DB_PATH", raising=False)

    from carefold.config import settings

    settings.home_dir = test_home
    settings.db_path = None

    resolved = resolve_checkpointer_path()
    assert resolved == test_home / DEFAULT_CHECKPOINTS_DB
    assert resolved.parent.is_dir()


def test_migration_fresh_install(tmp_path: Path) -> None:
    """Verifies that run_first_launch_migration on fresh install creates dirs and writes sentinel."""
    target_home = tmp_path / "new_home"
    empty_workspace = tmp_path / "empty_ws"
    empty_workspace.mkdir(parents=True)

    result = run_first_launch_migration(target_home, empty_workspace)
    assert result is False
    assert (target_home / ".migration_done").is_file()
    assert (target_home / "uploads").is_dir()
    assert (target_home / "logs").is_dir()

    # Second run should be a no-op
    result2 = run_first_launch_migration(target_home, empty_workspace)
    assert result2 is False


def test_migration_with_legacy_data(tmp_path: Path) -> None:
    """Verifies that legacy databases, notes, and audit logs are migrated properly."""
    target_home = tmp_path / "migrated_home"
    legacy_ws = tmp_path / "legacy_ws"
    ws_dir = legacy_ws / "workspace"
    ws_dir.mkdir(parents=True)
    (ws_dir / "chats").mkdir(parents=True)
    (ws_dir / "notes").mkdir(parents=True)
    (legacy_ws / "logs").mkdir(parents=True)

    # 1. Create a dummy carefold.db with note table
    db_file = ws_dir / "carefold.db"
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute(
            """
            CREATE TABLE note (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                slug TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

    # 2. Create sample notes
    note1 = ws_dir / "notes" / "blood-pressure-log.md"
    note1.write_text(
        "---\ntitle: 'Blood Pressure Log'\nagent_id: 'cardiology-guide'\n---\n# Daily BP\nValues normal.",
        encoding="utf-8",
    )

    # 3. Create dummy checkpoints.db
    cp_file = ws_dir / "chats" / "checkpoints.db"
    with sqlite3.connect(str(cp_file)) as conn:
        conn.execute("CREATE TABLE checkpoints (thread_id TEXT PRIMARY KEY, checkpoint BLOB);")
        conn.execute("INSERT INTO checkpoints VALUES ('thread-1', X'1234');")
        conn.commit()

    # 4. Create dummy audit log
    audit_file = legacy_ws / "logs" / "audit.jsonl"
    audit_file.write_text('{"event": "test_event_1"}\n', encoding="utf-8")

    # Run migration
    migrated = run_first_launch_migration(target_home, legacy_ws)
    assert migrated is True
    assert (target_home / ".migration_done").is_file()
    assert (target_home / "carefold.db").is_file()
    assert (target_home / "checkpoints.db").is_file()
    assert (target_home / "logs" / "audit.jsonl").is_file()

    # Verify notes were ingested into carefold.db
    with sqlite3.connect(str(target_home / "carefold.db")) as conn:
        rows = conn.execute("SELECT slug, title, content FROM note").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "blood-pressure-log"
        assert rows[0][1] == "Blood Pressure Log"
        assert "Daily BP" in rows[0][2]

    # Verify audit log content
    content = (target_home / "logs" / "audit.jsonl").read_text(encoding="utf-8")
    assert "test_event_1" in content


def test_parse_markdown_note(tmp_path: Path) -> None:
    """Verifies markdown note parsing with frontmatter."""
    sample_file = tmp_path / "sample-note.md"
    sample_file.write_text(
        "---\ntitle: 'Cardio Prep'\nagent_id: 'cardiology-guide'\nprofile_id: 'prof-123'\n---\n# Overview\nPatient history.",
        encoding="utf-8",
    )

    parsed = _parse_markdown_note(sample_file)
    assert parsed["slug"] == "sample-note"
    assert parsed["title"] == "Cardio Prep"
    assert parsed["profile_id"] == "prof-123"
    assert "cardiology-guide" in parsed["tags"]
    assert "# Overview" in parsed["content"]


def test_wal_checkpoint_truncation(tmp_path: Path) -> None:
    """Verifies that WAL checkpoint runs without errors."""
    db_file = tmp_path / "test_wal.db"
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("CREATE TABLE t (x INT);")
        conn.execute("INSERT INTO t VALUES (42);")
        conn.commit()

    res = _checkpoint_sqlite_database(db_file)
    assert res[0] == 0  # busy == 0 means successful checkpoint
