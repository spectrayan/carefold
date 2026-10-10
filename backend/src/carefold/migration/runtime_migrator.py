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

"""Runtime auto-migration service for Carefold home storage isolation (~/.carefold).

Migrates legacy repository assets (workspace/carefold.db, workspace/chats/checkpoints.db,
workspace/notes/*.md, and logs/audit.jsonl) into the user-isolated home directory.
Operates idempotently via ~/.carefold/.migration_done sentinel.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
import uuid
import yaml

from carefold import __version__
from carefold.logging import get_logger

logger = get_logger("carefold.migration.runtime_migrator")

SENTINEL_FILENAME = ".migration_done"
FRONTMATTER_PATTERN = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)$", re.DOTALL)
HEADING_PATTERN = re.compile(r"^#\s+(.+)$", re.MULTILINE)
REQUIRED_DISK_HEADROOM_BYTES = 2_500_000_000  # 2.5 GB safety buffer


def run_first_launch_migration(home_dir: Path, workspace_root: Path) -> bool:
    """Executes safe, idempotent migration from workspace_root to home_dir (~/.carefold).

    Args:
        home_dir: Canonical home directory for Carefold data (e.g. ~/.carefold).
        workspace_root: Repository or execution workspace root.

    Returns:
        True if migration migrated legacy data, False if skipped or no legacy data found.
    """
    home_dir = Path(home_dir).resolve()
    workspace_root = Path(workspace_root).resolve()

    sentinel_path = home_dir / SENTINEL_FILENAME
    if sentinel_path.is_file():
        logger.debug("migration_sentinel_present_skipping", sentinel=str(sentinel_path))
        return False

    _ensure_directory_tree(home_dir)

    # Detect whether legacy workspace exists
    legacy_workspace = workspace_root / "workspace"
    legacy_chats_db = legacy_workspace / "chats" / "checkpoints.db"
    legacy_sql_db = legacy_workspace / "carefold.db"
    legacy_notes_dir = legacy_workspace / "notes"
    root_audit_log = workspace_root / "logs" / "audit.jsonl"
    root_catalog_db = workspace_root / "catalog.db"
    legacy_catalog_db = legacy_workspace / "catalog.db"

    has_legacy_data = any([
        legacy_sql_db.is_file(),
        legacy_chats_db.is_file(),
        legacy_notes_dir.is_dir(),
        root_audit_log.is_file(),
        root_catalog_db.is_file(),
        legacy_catalog_db.is_file(),
    ])

    if not has_legacy_data:
        logger.info("no_legacy_workspace_detected_initializing_fresh_home", home=str(home_dir))
        _write_sentinel_file(
            sentinel_path,
            {
                "migrated_at": datetime.now(timezone.utc).isoformat(),
                "carefold_version": __version__,
                "type": "fresh_install",
                "source_workspace_root": str(workspace_root),
                "target_home_dir": str(home_dir),
            },
        )
        return False

    logger.info("initiating_first_launch_migration", source=str(workspace_root), target=str(home_dir))

    migration_report: Dict[str, Any] = {
        "migrated_at": datetime.now(timezone.utc).isoformat(),
        "carefold_version": __version__,
        "type": "upgraded_workspace",
        "source_workspace_root": str(workspace_root),
        "target_home_dir": str(home_dir),
        "databases": {},
        "notes": {},
        "audit_log": {},
        "attachments": {},
    }

    try:
        # 1. Migrate Checkpoints DB (~1.1GB)
        cp_result = _migrate_checkpoints_db(workspace_root, home_dir)
        migration_report["databases"]["checkpoints_db"] = cp_result

        # 2. Migrate carefold.db and Ingest Notes
        db_result = _migrate_carefold_db_and_notes(workspace_root, home_dir)
        migration_report["databases"]["carefold_db"] = db_result["database"]
        migration_report["notes"] = db_result["notes"]

        # 3. Migrate catalog.db (if present)
        cat_result = _migrate_catalog_db(workspace_root, home_dir)
        migration_report["databases"]["catalog_db"] = cat_result

        # 4. Migrate and Merge Audit Logs
        audit_result = _migrate_audit_log(workspace_root, home_dir)
        migration_report["audit_log"] = audit_result

        # 5. Migrate Attachments to Uploads (if any)
        att_result = _migrate_attachments(workspace_root, home_dir)
        migration_report["attachments"] = att_result

        # 6. Write Sentinel Marker
        _write_sentinel_file(sentinel_path, migration_report)
        logger.info("first_launch_migration_completed_successfully", report=migration_report)
        return True

    except Exception as err:
        logger.error("first_launch_migration_failed", error=str(err), exc_info=True)
        # Sentinel file is not written on error so that retry remains possible
        raise


def _ensure_directory_tree(home_dir: Path) -> None:
    """Pre-creates ~/.carefold directory structure with secure permissions."""
    home_dir.mkdir(parents=True, exist_ok=True)
    (home_dir / "uploads").mkdir(exist_ok=True)
    (home_dir / "logs").mkdir(exist_ok=True)
    try:
        # Enforce user-only read/write/execute where supported
        os.chmod(home_dir, 0o700)
    except OSError:
        pass


def _checkpoint_sqlite_database(db_path: Path) -> Tuple[int, int, int]:
    """Flushes SQLite WAL frames into primary file via PRAGMA wal_checkpoint(TRUNCATE)."""
    if not db_path.is_file() or db_path.stat().st_size == 0:
        return (0, 0, 0)
    try:
        with sqlite3.connect(str(db_path), timeout=10.0) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            res = cursor.fetchone()
            return tuple(res) if res else (0, 0, 0)
    except sqlite3.Error as err:
        logger.warning("wal_checkpoint_warning", db=str(db_path), error=str(err))
        return (-1, -1, -1)


def _copy_sqlite_database_safely(src: Path, dst: Path, is_large: bool = False) -> bool:
    """Safely copies SQLite database to destination using a staging temp file and integrity checks."""
    if not src.is_file():
        return False
    if dst.is_file():
        logger.info("destination_database_exists_skipping_copy", target=str(dst))
        return False

    # Check available disk space
    src_size = src.stat().st_size
    usage = shutil.disk_usage(dst.parent)
    required_space = (src_size * 2) if is_large else src_size
    if usage.free < required_space:
        raise RuntimeError(
            f"Insufficient disk space to copy {src.name}: required {required_space} bytes, free {usage.free} bytes."
        )

    # 1. Flush WAL on source
    _checkpoint_sqlite_database(src)

    # 2. Copy to temporary file
    tmp_dst = dst.with_suffix(f"{dst.suffix}.tmp")
    if tmp_dst.exists():
        tmp_dst.unlink(missing_ok=True)

    try:
        shutil.copy2(src, tmp_dst)

        # 3. Integrity Check
        with sqlite3.connect(str(tmp_dst)) as conn:
            cur = conn.cursor()
            res = cur.execute("PRAGMA integrity_check;").fetchall()
            if res != [("ok",)]:
                raise RuntimeError(f"Integrity check failed on copied database {tmp_dst}: {res}")

        # 4. Atomic Rename
        tmp_dst.replace(dst)
        return True
    finally:
        if tmp_dst.exists():
            tmp_dst.unlink(missing_ok=True)


def _migrate_checkpoints_db(workspace_root: Path, home_dir: Path) -> Dict[str, Any]:
    """Migrates large LangGraph checkpoints.db (~1.1GB) to ~/.carefold/checkpoints.db."""
    target_path = home_dir / "checkpoints.db"
    if target_path.is_file():
        return {"migrated": False, "reason": "already_exists", "size_bytes": target_path.stat().st_size}

    candidate_sources = [
        workspace_root / "workspace" / "chats" / "checkpoints.db",
        workspace_root / "chats" / "checkpoints.db",
    ]
    source_path = next((p for p in candidate_sources if p.is_file()), None)
    if not source_path:
        return {"migrated": False, "reason": "source_not_found"}

    src_size = source_path.stat().st_size
    chk_res = _checkpoint_sqlite_database(source_path)
    copied = _copy_sqlite_database_safely(source_path, target_path, is_large=True)

    return {
        "migrated": copied,
        "source": str(source_path),
        "size_bytes": src_size,
        "wal_checkpoint": list(chk_res),
    }


def _migrate_catalog_db(workspace_root: Path, home_dir: Path) -> Dict[str, Any]:
    """Migrates catalog.db to ~/.carefold/catalog.db."""
    target_path = home_dir / "catalog.db"
    if target_path.is_file():
        return {"migrated": False, "reason": "already_exists"}

    candidate_sources = [
        workspace_root / "catalog.db",
        workspace_root / "workspace" / "catalog.db",
    ]
    source_path = next((p for p in candidate_sources if p.is_file()), None)
    if not source_path:
        return {"migrated": False, "reason": "source_not_found"}

    chk_res = _checkpoint_sqlite_database(source_path)
    copied = _copy_sqlite_database_safely(source_path, target_path, is_large=False)
    return {
        "migrated": copied,
        "source": str(source_path),
        "size_bytes": target_path.stat().st_size if copied else 0,
        "wal_checkpoint": list(chk_res),
    }


def _migrate_carefold_db_and_notes(workspace_root: Path, home_dir: Path) -> Dict[str, Any]:
    """Copies workspace/carefold.db, ingests 31 loose markdown notes, and verifies integrity."""
    target_db = home_dir / "carefold.db"
    candidate_sources = [
        workspace_root / "workspace" / "carefold.db",
        workspace_root / "carefold.db",
    ]
    source_db = next((p for p in candidate_sources if p.is_file()), None)

    notes_dirs = [
        workspace_root / "workspace" / "notes",
        workspace_root / "notes",
    ]

    db_report: Dict[str, Any] = {"migrated": False}
    notes_report: Dict[str, Any] = {"ingested_count": 0, "scanned_files": 0}

    # If carefold.db does not exist at destination, stage and copy from source
    if not target_db.is_file() and source_db:
        chk_res = _checkpoint_sqlite_database(source_db)
        tmp_db = target_db.with_suffix(".db.tmp")
        if tmp_db.exists():
            tmp_db.unlink(missing_ok=True)

        try:
            shutil.copy2(source_db, tmp_db)
            # Ingest loose notes directly into staged temporary DB
            ingested = _ingest_notes_into_db(tmp_db, notes_dirs)
            notes_report["ingested_count"] = ingested

            # Integrity check
            with sqlite3.connect(str(tmp_db)) as conn:
                res = conn.execute("PRAGMA integrity_check;").fetchall()
                if res != [("ok",)]:
                    raise RuntimeError(f"Integrity check failed for staged carefold.db: {res}")

            tmp_db.replace(target_db)
            db_report = {
                "migrated": True,
                "source": str(source_db),
                "size_bytes": target_db.stat().st_size,
                "wal_checkpoint": list(chk_res),
            }
        finally:
            if tmp_db.exists():
                tmp_db.unlink(missing_ok=True)
    elif target_db.is_file():
        # Destination already exists; ingest any remaining loose notes directly
        ingested = _ingest_notes_into_db(target_db, notes_dirs)
        notes_report["ingested_count"] = ingested
        db_report = {"migrated": False, "reason": "already_exists", "size_bytes": target_db.stat().st_size}
    else:
        db_report = {"migrated": False, "reason": "source_not_found"}

    return {"database": db_report, "notes": notes_report}


def _ingest_notes_into_db(db_path: Path, notes_dirs: List[Path]) -> int:
    """Ingests loose markdown notes into the SQLite note/notes table idempotently."""
    if not db_path.is_file():
        return 0

    # Collect note files
    note_files: List[Path] = []
    for nd in notes_dirs:
        if nd.is_dir():
            for f in nd.glob("*.md"):
                if not f.name.startswith("."):
                    note_files.append(f)

    if not note_files:
        return 0

    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        cursor = conn.cursor()

        # 1. Determine active table name ('notes' or 'note')
        tables = [
            r[0]
            for r in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('notes', 'note')"
            ).fetchall()
        ]
        if "notes" in tables:
            table_name = "notes"
        elif "note" in tables:
            table_name = "note"
        else:
            logger.warning("neither_notes_nor_note_table_found", db=str(db_path))
            return 0

        # 2. Inspect table columns
        cols = [c[1] for c in cursor.execute(f"PRAGMA table_info({table_name});").fetchall()]
        tags_col = "tags_json" if "tags_json" in cols else ("tags" if "tags" in cols else None)

        # 3. Resolve primary user ID (if any)
        user_id: Optional[str] = None
        has_users = cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        if has_users:
            user_row = cursor.execute("SELECT id FROM users LIMIT 1").fetchone()
            if user_row:
                user_id = user_row[0]

        # 4. Ingest each markdown note
        ingested_count = 0
        for nf in note_files:
            parsed = _parse_markdown_note(nf)
            slug = parsed["slug"]

            # Check if slug exists across any candidate note table
            existing = None
            for tbl in tables:
                existing = cursor.execute(f"SELECT id FROM {tbl} WHERE slug = ?", (slug,)).fetchone()
                if existing:
                    break
            if existing:
                continue

            note_id = str(uuid.uuid4())
            title = parsed["title"]
            content = parsed["content"]
            profile_id = parsed["profile_id"]
            created_at = parsed["created_at"]
            updated_at = parsed["updated_at"]
            tags_val = json.dumps(parsed["tags"]) if tags_col else ""

            # Build insert query dynamically based on column presence
            insert_cols = ["id", "type", "slug", "title", "content", "created_at", "updated_at"]
            insert_vals: List[Any] = [note_id, "scratchpad", slug, title, content, created_at, updated_at]

            if "user_id" in cols:
                insert_cols.append("user_id")
                insert_vals.append(user_id)
            if "profile_id" in cols:
                insert_cols.append("profile_id")
                insert_vals.append(profile_id)
            if tags_col:
                insert_cols.append(tags_col)
                insert_vals.append(tags_val)

            placeholders = ", ".join(["?"] * len(insert_cols))
            col_names = ", ".join(insert_cols)
            cursor.execute(f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})", tuple(insert_vals))
            ingested_count += 1

        conn.commit()
        logger.info("ingested_legacy_notes_to_database", count=ingested_count, table=table_name)
        return ingested_count


def _parse_markdown_note(file_path: Path) -> Dict[str, Any]:
    """Parses a markdown note file extracting YAML frontmatter, title, and body."""
    raw_content = file_path.read_text(encoding="utf-8", errors="replace")
    stat = file_path.stat()
    slug = file_path.stem

    match = FRONTMATTER_PATTERN.match(raw_content)
    if match:
        fm_raw, body = match.group(1), match.group(2)
        try:
            meta = yaml.safe_load(fm_raw)
            if not isinstance(meta, dict):
                meta = {}
        except Exception:
            meta = {}
    else:
        meta = {}
        body = raw_content

    # Title Resolution: frontmatter title > markdown H1 > titleized slug
    fm_title = meta.get("title")
    heading_match = HEADING_PATTERN.search(body)
    heading_title = heading_match.group(1).strip() if heading_match else None
    slug_title = slug.replace("-", " ").replace("_", " ").strip().title()

    if fm_title and isinstance(fm_title, str) and fm_title.strip() != slug:
        title = fm_title.strip()
    elif heading_title:
        title = heading_title
    else:
        title = slug_title

    # Tags & Agent
    agent_id = meta.get("agent_id") or meta.get("agent")
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    elif not isinstance(tags, list):
        tags = []
    if agent_id and isinstance(agent_id, str) and agent_id not in tags:
        tags.append(agent_id)

    # Profile ID
    profile_id = meta.get("profile_id")
    if profile_id and not isinstance(profile_id, str):
        profile_id = str(profile_id)

    # Timestamps
    created_str = meta.get("created_at")
    if created_str and isinstance(created_str, str):
        try:
            dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            created_at = dt.strftime("%Y-%m-%d %H:%M:%S.%f")
        except Exception:
            created_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
    else:
        created_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")

    return {
        "slug": slug,
        "title": title,
        "content": body.strip(),
        "tags": tags,
        "profile_id": profile_id,
        "created_at": created_at,
        "updated_at": created_at,
    }


def _migrate_audit_log(workspace_root: Path, home_dir: Path) -> Dict[str, Any]:
    """Merges root and workspace audit logs into ~/.carefold/logs/audit.jsonl."""
    target_log = home_dir / "logs" / "audit.jsonl"
    if target_log.is_file() and target_log.stat().st_size > 0:
        return {"migrated": False, "reason": "already_exists"}

    candidate_sources = [
        workspace_root / "logs" / "audit.jsonl",
        workspace_root / "workspace" / "logs" / "audit.jsonl",
    ]
    existing_sources = [p for p in candidate_sources if p.is_file() and p.stat().st_size > 0]
    if not existing_sources:
        return {"migrated": False, "reason": "no_source_logs_found"}

    tmp_log = target_log.with_suffix(".jsonl.tmp")
    if tmp_log.exists():
        tmp_log.unlink(missing_ok=True)

    lines_written = 0
    seen_lines = set()
    try:
        with open(tmp_log, "w", encoding="utf-8") as out_f:
            for src in existing_sources:
                with open(src, "r", encoding="utf-8", errors="replace") as in_f:
                    for line in in_f:
                        trimmed = line.strip()
                        if trimmed and trimmed not in seen_lines:
                            seen_lines.add(trimmed)
                            out_f.write(trimmed + "\n")
                            lines_written += 1

        tmp_log.replace(target_log)
        return {"migrated": True, "lines_written": lines_written, "sources": [str(s) for s in existing_sources]}
    finally:
        if tmp_log.exists():
            tmp_log.unlink(missing_ok=True)


def _migrate_attachments(workspace_root: Path, home_dir: Path) -> Dict[str, Any]:
    """Copies any existing legacy attachments to ~/.carefold/uploads/."""
    uploads_dir = home_dir / "uploads"
    candidate_dirs = [
        workspace_root / "attachments",
        workspace_root / "workspace" / "attachments",
    ]

    copied_count = 0
    for ad in candidate_dirs:
        if ad.is_dir():
            for item in ad.iterdir():
                if item.is_file() and not item.name.startswith("."):
                    target_file = uploads_dir / item.name
                    if not target_file.exists():
                        shutil.copy2(item, target_file)
                        copied_count += 1

    return {"migrated": copied_count > 0, "copied_count": copied_count}


def _write_sentinel_file(sentinel_path: Path, metadata: Dict[str, Any]) -> None:
    """Atomically writes the migration completion sentinel marker."""
    tmp_sentinel = sentinel_path.with_suffix(".tmp")
    content = json.dumps(metadata, indent=2) + "\n"
    tmp_sentinel.write_text(content, encoding="utf-8")
    tmp_sentinel.replace(sentinel_path)
