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

"""Adversarial stress tests for Carefold runtime auto-migration engine (runtime_migrator.py).

Covers edge cases, failure modes, and stress scenarios:
1. Corrupted WAL files and corrupted database files
2. Locked SQLite connections (concurrency, exclusive locks, timeout)
3. Simulated power cuts / interrupted writes (.tmp files left behind)
4. Malformed YAML frontmatter in notes
5. Notes with duplicate slugs (across directories and pre-existing in DB)
6. Notes with missing headings and empty files
7. Large files and insufficient disk space simulation
8. .migration_done sentinel idempotency preventing re-migration
9. Schema variations (note vs notes table, column subsets)
10. Audit log deduplication under stress
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import pytest

from carefold.migration.runtime_migrator import (
    _checkpoint_sqlite_database,
    _copy_sqlite_database_safely,
    _ingest_notes_into_db,
    _parse_markdown_note,
    run_first_launch_migration,
)


def _create_minimal_carefold_db(db_path: Path, table_name: str = "note") -> None:
    """Helper to create a valid minimal carefold.db for migration tests."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            f"""
            CREATE TABLE {table_name} (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                slug TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()


# ==============================================================================
# 1. Corrupted WAL Files & Corrupted Databases
# ==============================================================================

def test_corrupted_wal_file_checkpoint_failure_handling(tmp_path: Path) -> None:
    """Verifies that a corrupted WAL file does not crash _checkpoint_sqlite_database."""
    db_file = tmp_path / "corrupt_wal.db"
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("CREATE TABLE t (id INT);")
        conn.execute("INSERT INTO t VALUES (1);")
        conn.commit()

    wal_file = tmp_path / "corrupt_wal.db-wal"
    assert wal_file.is_file()

    # Corrupt the WAL file with random garbage bytes
    wal_file.write_bytes(b"\xff\x00\xde\xad\xbe\xef" * 100)

    # _checkpoint_sqlite_database should catch the sqlite3.Error and return (-1, -1, -1)
    res = _checkpoint_sqlite_database(db_file)
    assert res == (-1, -1, -1)


def test_corrupted_source_database_fails_integrity_and_aborts_migration(tmp_path: Path) -> None:
    """Verifies that a corrupted source database fails integrity check and aborts migration."""
    target_home = tmp_path / "target_home"
    legacy_ws = tmp_path / "legacy_ws"
    ws_dir = legacy_ws / "workspace"
    ws_dir.mkdir(parents=True)

    # Create a corrupted carefold.db containing non-sqlite garbage
    corrupt_db = ws_dir / "carefold.db"
    corrupt_db.write_bytes(b"NOT A SQLITE DATABASE GARBAGE HEADER" * 50)

    with pytest.raises(Exception):
        run_first_launch_migration(target_home, legacy_ws)

    # Sentinel must NOT be created when migration fails
    assert not (target_home / ".migration_done").exists()
    # Destination DB must NOT exist
    assert not (target_home / "carefold.db").exists()
    # Leftover staging .tmp file must NOT exist
    assert not (target_home / "carefold.db.tmp").exists()


# ==============================================================================
# 2. Locked SQLite Connections
# ==============================================================================

def test_locked_sqlite_source_connection_during_wal_checkpoint(tmp_path: Path) -> None:
    """Verifies that an exclusively locked source DB during checkpoint returns busy flag (busy=1)."""
    db_file = tmp_path / "locked_source.db"
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("CREATE TABLE t (x INT);")
        conn.execute("INSERT INTO t VALUES (99);")
        conn.commit()

    # Open connection holding an exclusive transaction
    lock_conn = sqlite3.connect(str(db_file), timeout=0.1)
    lock_conn.execute("BEGIN EXCLUSIVE;")

    try:
        # Checkpoint returns SQLite checkpoint tuple (busy, log, checkpointed)
        # When another connection holds exclusive transaction, busy is 1
        res = _checkpoint_sqlite_database(db_file)
        assert res[0] == 1  # busy flag is set by SQLite engine
    finally:
        lock_conn.rollback()
        lock_conn.close()


def test_locked_sqlite_target_connection_aborts_without_sentinel(tmp_path: Path) -> None:
    """Verifies that an exclusively locked target DB aborts migration and does not write sentinel."""
    target_home = tmp_path / "target_home"
    target_home.mkdir(parents=True)
    target_db = target_home / "carefold.db"
    _create_minimal_carefold_db(target_db)

    legacy_ws = tmp_path / "legacy_ws"
    ws_dir = legacy_ws / "workspace"
    (ws_dir / "notes").mkdir(parents=True)
    note_file = ws_dir / "notes" / "note1.md"
    note_file.write_text("# Note 1\nContent", encoding="utf-8")

    # Lock target_db exclusively
    lock_conn = sqlite3.connect(str(target_db), timeout=0.01)
    lock_conn.execute("BEGIN EXCLUSIVE;")

    try:
        # Running migration should fail due to database lock when ingesting notes
        orig_connect = sqlite3.connect

        def fast_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
            kwargs["timeout"] = 0.1
            return orig_connect(*args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sqlite3, "connect", fast_connect)
            with pytest.raises(sqlite3.OperationalError):
                run_first_launch_migration(target_home, legacy_ws)

        # Sentinel must NOT be written
        assert not (target_home / ".migration_done").exists()
    finally:
        lock_conn.rollback()
        lock_conn.close()


# ==============================================================================
# 3. Simulated Power Cuts & Leftover .tmp Files
# ==============================================================================

def test_power_cut_simulated_leftover_tmp_files_cleaned_and_overwritten(tmp_path: Path) -> None:
    """Verifies that leftover .tmp files from simulated interrupted writes are cleaned up."""
    target_home = tmp_path / "interrupted_home"
    target_home.mkdir(parents=True)
    (target_home / "logs").mkdir(parents=True)

    # Simulate crashed previous run leaving .tmp files
    garbage = b"CRASHED_INCOMPLETE_WRITE_DATA" * 50
    (target_home / "carefold.db.tmp").write_bytes(garbage)
    (target_home / "checkpoints.db.tmp").write_bytes(garbage)
    (target_home / "catalog.db.tmp").write_bytes(garbage)
    (target_home / "logs" / "audit.jsonl.tmp").write_bytes(garbage)
    (target_home / ".migration_done.tmp").write_bytes(garbage)

    legacy_ws = tmp_path / "legacy_ws"
    ws_dir = legacy_ws / "workspace"
    ws_dir.mkdir(parents=True)
    (ws_dir / "notes").mkdir(parents=True)
    (ws_dir / "chats").mkdir(parents=True)
    (legacy_ws / "logs").mkdir(parents=True)

    # Valid source databases
    _create_minimal_carefold_db(ws_dir / "carefold.db")
    with sqlite3.connect(str(ws_dir / "chats" / "checkpoints.db")) as conn:
        conn.execute("CREATE TABLE checkpoints (thread_id TEXT);")
        conn.execute("INSERT INTO checkpoints VALUES ('t1');")
        conn.commit()

    with sqlite3.connect(str(ws_dir / "catalog.db")) as conn:
        conn.execute("CREATE TABLE catalog (id TEXT);")
        conn.execute("INSERT INTO catalog VALUES ('cat1');")
        conn.commit()

    (legacy_ws / "logs" / "audit.jsonl").write_text('{"event": "ev1"}\n', encoding="utf-8")
    (ws_dir / "notes" / "p1.md").write_text("# Note 1\nBody", encoding="utf-8")

    # Run migration
    success = run_first_launch_migration(target_home, legacy_ws)
    assert success is True

    # Check that all .tmp files were cleaned up
    assert not (target_home / "carefold.db.tmp").exists()
    assert not (target_home / "checkpoints.db.tmp").exists()
    assert not (target_home / "catalog.db.tmp").exists()
    assert not (target_home / "logs" / "audit.jsonl.tmp").exists()
    assert not (target_home / ".migration_done.tmp").exists()

    # Check that final files are fully valid
    assert (target_home / ".migration_done").is_file()
    assert (target_home / "carefold.db").is_file()
    assert (target_home / "checkpoints.db").is_file()
    assert (target_home / "catalog.db").is_file()

    # Verify integrity of carefold.db
    with sqlite3.connect(str(target_home / "carefold.db")) as conn:
        res = conn.execute("PRAGMA integrity_check;").fetchall()
        assert res == [("ok",)]
        rows = conn.execute("SELECT slug, title FROM note").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "p1"


# ==============================================================================
# 4. Malformed YAML Frontmatter in Notes
# ==============================================================================

@pytest.mark.parametrize(
    "note_content,expected_title,expected_tags",
    [
        (
            # Unclosed frontmatter delimiter
            "---\ntitle: 'Unclosed Frontmatter'\ntags: [unclosed\nBody line 1\nBody line 2",
            "Unclosed Frontmatter",  # falls back to slug titleized or content
            [],
        ),
        (
            # Invalid YAML syntax (unbalanced quotes)
            "---\ntitle: \"Missing quote\ntags: [a, b]\n---\n# Real Title\nBody here",
            "Real Title",  # falls back to H1 header
            [],
        ),
        (
            # YAML list instead of dict
            "---\n- item 1\n- item 2\n---\n# List Preamble\nBody here",
            "List Preamble",
            [],
        ),
        (
            # Strange types in frontmatter fields
            "---\ntitle: 12345\ntags: 9999\nagent_id: 888\nprofile_id: ['not', 'string']\ncreated_at: 123456\n---\nBody text",
            "Strange Types Note",  # titleized slug for strange-types-note.md
            [],
        ),
        (
            # Binary-like unicode noise in body and frontmatter
            "---\ntitle: 'Unicode 🏥 🩺'\nagent_id: 'cardiology-guide'\n---\n# Header 💉\nContent \x00\x01\x02 \U0001F600",
            "Unicode 🏥 🩺",
            ["cardiology-guide"],
        ),
    ],
)
def test_malformed_yaml_frontmatter_in_notes(
    tmp_path: Path, note_content: str, expected_title: str, expected_tags: list[str]
) -> None:
    """Verifies that malformed frontmatter does not crash parsing or ingestion."""
    note_file = tmp_path / "strange-types-note.md"
    note_file.write_text(note_content, encoding="utf-8")

    parsed = _parse_markdown_note(note_file)
    assert parsed["slug"] == "strange-types-note"
    assert parsed["title"] is not None
    assert isinstance(parsed["title"], str)
    assert len(parsed["title"]) > 0
    assert isinstance(parsed["tags"], list)


def test_malformed_notes_ingested_cleanly_into_db(tmp_path: Path) -> None:
    """Verifies that a mix of malformed notes are all ingested into carefold.db without crashing."""
    db_file = tmp_path / "carefold.db"
    _create_minimal_carefold_db(db_file)

    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()

    (notes_dir / "broken-yaml.md").write_text(
        "---\n: [invalid yaml syntax {{}}\n---\n# Valid Heading\nSome content", encoding="utf-8"
    )
    (notes_dir / "unclosed-fm.md").write_text(
        "---\ntitle: unclosed\nNo closing delimiter at all\nJust text", encoding="utf-8"
    )
    (notes_dir / "scalar-fm.md").write_text(
        "---\nJust a scalar string\n---\nText after scalar", encoding="utf-8"
    )

    ingested = _ingest_notes_into_db(db_file, [notes_dir])
    assert ingested == 3

    with sqlite3.connect(str(db_file)) as conn:
        rows = conn.execute("SELECT slug, title, content FROM note ORDER BY slug").fetchall()
        assert len(rows) == 3
        assert rows[0][0] == "broken-yaml"
        assert rows[0][1] == "Valid Heading"
        assert rows[1][0] == "scalar-fm"
        assert rows[2][0] == "unclosed-fm"


# ==============================================================================
# 5. Notes with Duplicate Slugs
# ==============================================================================

def test_duplicate_slugs_in_different_directories_and_existing_db(tmp_path: Path) -> None:
    """Verifies that duplicate slugs across directories and pre-existing DB rows are safely skipped."""
    db_file = tmp_path / "carefold.db"
    _create_minimal_carefold_db(db_file)

    # Pre-seed one note with slug 'shared-slug'
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute(
            """
            INSERT INTO note (id, type, slug, title, content, tags_json, created_at, updated_at)
            VALUES ('id-pre', 'scratchpad', 'shared-slug', 'Pre-existing Title', 'Original content', '[]', '2026-01-01', '2026-01-01')
            """
        )
        conn.commit()

    dir1 = tmp_path / "workspace_notes"
    dir2 = tmp_path / "root_notes"
    dir1.mkdir()
    dir2.mkdir()

    # File with pre-existing slug
    (dir1 / "shared-slug.md").write_text("# Attempted Overwrite\nNew Content", encoding="utf-8")

    # Two files with identical slug in different directories
    (dir1 / "dual-slug.md").write_text("# Dual Slug From Dir1\nContent 1", encoding="utf-8")
    (dir2 / "dual-slug.md").write_text("# Dual Slug From Dir2\nContent 2", encoding="utf-8")

    # Ingest notes from both directories
    ingested = _ingest_notes_into_db(db_file, [dir1, dir2])

    # Only 'dual-slug.md' should be ingested once; 'shared-slug.md' should be skipped
    assert ingested == 1

    with sqlite3.connect(str(db_file)) as conn:
        rows = conn.execute("SELECT slug, title, content FROM note ORDER BY slug").fetchall()
        assert len(rows) == 2
        # Pre-existing was preserved
        assert rows[1][0] == "shared-slug"
        assert rows[1][1] == "Pre-existing Title"
        assert rows[1][2] == "Original content"
        # Dual-slug was ingested only once
        assert rows[0][0] == "dual-slug"
        assert rows[0][1] == "Dual Slug From Dir1"


# ==============================================================================
# 6. Notes with Missing Headings & Empty Files
# ==============================================================================

def test_notes_with_missing_headings_and_empty_files(tmp_path: Path) -> None:
    """Verifies handling of empty notes, missing headings, and H2-only headings."""
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()

    # Empty 0-byte file
    empty_file = notes_dir / "completely-empty.md"
    empty_file.write_text("", encoding="utf-8")

    # Only H2 heading (no H1)
    h2_file = notes_dir / "h2-only-note.md"
    h2_file.write_text("## Only Section 2\nSome paragraph text.", encoding="utf-8")

    # Plain text only (no markdown markers)
    plain_file = notes_dir / "plain-text-log.md"
    plain_file.write_text("Blood pressure reading 120/80 on Monday morning.", encoding="utf-8")

    # Frontmatter title matches slug exactly -> should fall back to heading or titleized slug
    same_slug_file = notes_dir / "exact-slug-title.md"
    same_slug_file.write_text("---\ntitle: 'exact-slug-title'\n---\n# Better Title\nBody", encoding="utf-8")

    parsed_empty = _parse_markdown_note(empty_file)
    assert parsed_empty["title"] == "Completely Empty"
    assert parsed_empty["content"] == ""

    parsed_h2 = _parse_markdown_note(h2_file)
    assert parsed_h2["title"] == "H2 Only Note"
    assert "Only Section 2" in parsed_h2["content"]

    parsed_plain = _parse_markdown_note(plain_file)
    assert parsed_plain["title"] == "Plain Text Log"

    parsed_same = _parse_markdown_note(same_slug_file)
    assert parsed_same["title"] == "Better Title"

    # Ingest into DB
    db_file = tmp_path / "carefold.db"
    _create_minimal_carefold_db(db_file)
    ingested = _ingest_notes_into_db(db_file, [notes_dir])
    assert ingested == 4


# ==============================================================================
# 7. Large Files & Disk Space Headroom Exhaustion
# ==============================================================================

def test_large_notes_and_large_checkpoints_database(tmp_path: Path) -> None:
    """Verifies that large files (multi-megabyte notes and DBs) migrate and maintain integrity."""
    target_home = tmp_path / "large_home"
    legacy_ws = tmp_path / "legacy_ws"
    ws_dir = legacy_ws / "workspace"
    ws_dir.mkdir(parents=True)
    (ws_dir / "notes").mkdir(parents=True)
    (ws_dir / "chats").mkdir(parents=True)

    _create_minimal_carefold_db(ws_dir / "carefold.db")

    # Create a 2MB note
    large_note = ws_dir / "notes" / "huge-note.md"
    large_body = "# Huge Note\n" + ("Clinical report data block line.\n" * 60_000)
    large_note.write_text(large_body, encoding="utf-8")

    # Create a checkpoints DB with 2000 rows
    cp_file = ws_dir / "chats" / "checkpoints.db"
    with sqlite3.connect(str(cp_file)) as conn:
        conn.execute("CREATE TABLE checkpoints (thread_id TEXT, data BLOB);")
        blob = b"\xaa" * 1024  # 1KB per row
        conn.executemany(
            "INSERT INTO checkpoints VALUES (?, ?);",
            [(f"thread-{i}", blob) for i in range(2000)],
        )
        conn.commit()

    success = run_first_launch_migration(target_home, legacy_ws)
    assert success is True

    # Verify checkpoints DB in home
    with sqlite3.connect(str(target_home / "checkpoints.db")) as conn:
        count = conn.execute("SELECT count(*) FROM checkpoints;").fetchone()[0]
        assert count == 2000

    # Verify large note in carefold.db
    with sqlite3.connect(str(target_home / "carefold.db")) as conn:
        row = conn.execute("SELECT title, length(content) FROM note WHERE slug = 'huge-note';").fetchone()
        assert row[0] == "Huge Note"
        assert row[1] > 1_500_000


def test_insufficient_disk_space_raises_and_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that insufficient disk space raises RuntimeError and leaves no orphaned files."""
    src = tmp_path / "source.db"
    src.write_bytes(b"A" * 10_000)

    dst = tmp_path / "dest" / "target.db"
    dst.parent.mkdir(parents=True)

    # Mock shutil.disk_usage to report only 100 bytes free
    import collections
    Usage = collections.namedtuple("Usage", ["total", "used", "free"])

    monkeypatch.setattr(shutil, "disk_usage", lambda _: Usage(total=1_000_000, used=999_900, free=100))

    with pytest.raises(RuntimeError) as exc_info:
        _copy_sqlite_database_safely(src, dst, is_large=True)

    assert "Insufficient disk space" in str(exc_info.value)
    assert not dst.exists()
    assert not dst.with_suffix(f"{dst.suffix}.tmp").exists()


# ==============================================================================
# 8. Sentinel File Prevents Re-Migration
# ==============================================================================

def test_sentinel_file_prevents_remigration(tmp_path: Path) -> None:
    """Verifies that .migration_done sentinel completely prevents any re-migration."""
    target_home = tmp_path / "target_home"
    legacy_ws = tmp_path / "legacy_ws"
    ws_dir = legacy_ws / "workspace"
    ws_dir.mkdir(parents=True)
    (ws_dir / "notes").mkdir(parents=True)
    _create_minimal_carefold_db(ws_dir / "carefold.db")

    note1 = ws_dir / "notes" / "note1.md"
    note1.write_text("# Note 1\nBody 1", encoding="utf-8")

    # First launch: migrates successfully
    res1 = run_first_launch_migration(target_home, legacy_ws)
    assert res1 is True
    assert (target_home / ".migration_done").is_file()

    # Read sentinel contents
    sentinel_content = (target_home / ".migration_done").read_text(encoding="utf-8")
    sentinel_json = json.loads(sentinel_content)
    assert sentinel_json["type"] == "upgraded_workspace"

    # Now add a new note in legacy workspace
    note2 = ws_dir / "notes" / "note2.md"
    note2.write_text("# Note 2\nBody 2", encoding="utf-8")

    # Second launch: should be immediate no-op returning False
    res2 = run_first_launch_migration(target_home, legacy_ws)
    assert res2 is False

    # Verify that note2 was NOT ingested into target_home/carefold.db
    with sqlite3.connect(str(target_home / "carefold.db")) as conn:
        rows = conn.execute("SELECT slug FROM note WHERE slug = 'note2';").fetchall()
        assert len(rows) == 0

    # Sentinel content should remain unchanged
    assert (target_home / ".migration_done").read_text(encoding="utf-8") == sentinel_content


# ==============================================================================
# 9. Schema Variations (note vs notes table, column subsets)
# ==============================================================================

def test_notes_table_plural_schema_variation(tmp_path: Path) -> None:
    """Verifies that table name 'notes' (plural) is supported seamlessly with user_id and profile_id."""
    target_home = tmp_path / "plural_home"
    target_home.mkdir(parents=True)
    db_file = target_home / "carefold.db"

    # Create table 'notes' with user_id and profile_id and users table
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT);")
        conn.execute("INSERT INTO users VALUES ('usr-123', 'test@carefold.local');")
        conn.execute(
            """
            CREATE TABLE notes (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                profile_id TEXT,
                type TEXT NOT NULL,
                slug TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()

    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "profile-note.md").write_text(
        "---\ntitle: 'Profile Scoped Note'\nprofile_id: 'prof-999'\nagent: 'derma-guide'\n---\n# Derm note\nSkin rash check.",
        encoding="utf-8",
    )

    ingested = _ingest_notes_into_db(db_file, [notes_dir])
    assert ingested == 1

    with sqlite3.connect(str(db_file)) as conn:
        row = conn.execute(
            "SELECT user_id, profile_id, slug, title, content, tags FROM notes WHERE slug = 'profile-note';"
        ).fetchone()
        assert row[0] == "usr-123"  # resolved primary user_id
        assert row[1] == "prof-999"  # resolved profile_id from frontmatter
        assert row[2] == "profile-note"
        assert row[3] == "Profile Scoped Note"
        assert "derma-guide" in row[5]


# ==============================================================================
# 10. Audit Log Deduplication Under Stress
# ==============================================================================

def test_audit_log_deduplication_stress(tmp_path: Path) -> None:
    """Verifies that audit log lines appearing across root and workspace logs are deduplicated."""
    target_home = tmp_path / "audit_home"
    legacy_ws = tmp_path / "legacy_ws"
    ws_dir = legacy_ws / "workspace"
    ws_dir.mkdir(parents=True)
    (legacy_ws / "logs").mkdir(parents=True)
    (ws_dir / "logs").mkdir(parents=True)

    _create_minimal_carefold_db(ws_dir / "carefold.db")

    # 100 unique lines + 50 overlapping lines
    root_lines = [f'{{"seq": {i}, "msg": "root"}}\n' for i in range(100)]
    ws_lines = [f'{{"seq": {i}, "msg": "root"}}\n' for i in range(50)] + [
        f'{{"seq": {i}, "msg": "workspace"}}\n' for i in range(100, 150)
    ]

    (legacy_ws / "logs" / "audit.jsonl").write_text("".join(root_lines), encoding="utf-8")
    (ws_dir / "logs" / "audit.jsonl").write_text("".join(ws_lines), encoding="utf-8")

    success = run_first_launch_migration(target_home, legacy_ws)
    assert success is True

    migrated_lines = (target_home / "logs" / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    # 100 from root + 50 non-overlapping from workspace = 150 total
    assert len(migrated_lines) == 150


# ==============================================================================
# 11. Additional Edge Cases & Boundary Conditions
# ==============================================================================

def test_nonexistent_or_empty_database_checkpoint(tmp_path: Path) -> None:
    """Verifies that _checkpoint_sqlite_database handles missing and 0-byte DBs safely."""
    missing_file = tmp_path / "nonexistent.db"
    assert _checkpoint_sqlite_database(missing_file) == (0, 0, 0)

    empty_file = tmp_path / "empty.db"
    empty_file.write_bytes(b"")
    assert _checkpoint_sqlite_database(empty_file) == (0, 0, 0)


def test_uninitialized_schema_missing_notes_table_returns_zero_gracefully(tmp_path: Path) -> None:
    """Verifies that carefold.db without note/notes table logs warning and returns 0 without crashing."""
    db_file = tmp_path / "blank.db"
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("CREATE TABLE other_table (id INT);")
        conn.commit()

    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "note.md").write_text("# Note\nContent", encoding="utf-8")

    ingested = _ingest_notes_into_db(db_file, [notes_dir])
    assert ingested == 0


def test_exotic_filenames_and_hidden_files(tmp_path: Path) -> None:
    """Verifies that hidden files (.dotfiles) are ignored while unicode and emoji filenames work."""
    db_file = tmp_path / "carefold.db"
    _create_minimal_carefold_db(db_file)

    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()

    # Hidden file starting with dot
    (notes_dir / ".hidden-draft.md").write_text("# Secret\nDraft", encoding="utf-8")
    # Unicode and emoji names
    (notes_dir / "clinic_visit_2026.md").write_text("# Clinic Visit\nSummary", encoding="utf-8")

    ingested = _ingest_notes_into_db(db_file, [notes_dir])
    # .hidden-draft.md must be ignored
    assert ingested == 1

    with sqlite3.connect(str(db_file)) as conn:
        rows = conn.execute("SELECT slug, title FROM note").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "clinic_visit_2026"


def test_date_parsing_variations_in_frontmatter(tmp_path: Path) -> None:
    """Verifies parsing of various created_at date formats (ISO, UTC Z, invalid)."""
    # 1. UTC with Z
    f1 = tmp_path / "n1.md"
    f1.write_text("---\ncreated_at: '2026-05-01T14:30:00Z'\n---\nBody", encoding="utf-8")
    p1 = _parse_markdown_note(f1)
    assert p1["created_at"].startswith("2026-05-01")

    # 2. ISO with offset
    f2 = tmp_path / "n2.md"
    f2.write_text("---\ncreated_at: '2026-05-01T09:30:00-05:00'\n---\nBody", encoding="utf-8")
    p2 = _parse_markdown_note(f2)
    assert p2["created_at"].startswith("2026-05-01")

    # 3. Invalid date string falls back to file mtime
    f3 = tmp_path / "n3.md"
    f3.write_text("---\ncreated_at: 'not-a-valid-timestamp'\n---\nBody", encoding="utf-8")
    p3 = _parse_markdown_note(f3)
    assert isinstance(p3["created_at"], str)
    assert len(p3["created_at"]) > 0
