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

"""SQLite cognitive memory adapter implementing MemoryPort with FTS5."""

from __future__ import annotations

import asyncio
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import aiosqlite
import sqlite3

from carefold.constants.defaults import (
    SQLITE_BUSY_TIMEOUT_MS,
    SQLITE_CONNECT_TIMEOUT_SECONDS,
    SQLITE_JOURNAL_MODE,
)
from carefold.memory.ports.memory_port import MemoryPort, MemoryTier


async def _run_write_with_retry(
    fn,
    max_retries: int = 10,
    base_delay: float = 0.05,
    conn: Optional[aiosqlite.Connection] = None,
):
    """Executes a write coroutine with exponential backoff retry on SQLite locking conflicts."""
    for attempt in range(max_retries):
        try:
            return await fn()
        except (sqlite3.OperationalError, aiosqlite.OperationalError) as err:
            err_msg = str(err).lower()
            if (
                "locked" in err_msg
                or "busy" in err_msg
                or "vtable constructor failed" in err_msg
            ) and attempt < max_retries - 1:
                target_conn = conn
                if target_conn is None:
                    if hasattr(fn, "__self__") and hasattr(fn.__self__, "_conn"):
                        target_conn = getattr(fn.__self__, "_conn")
                    elif hasattr(fn, "__closure__") and fn.__closure__:
                        for cell in fn.__closure__:
                            try:
                                cell_contents = cell.cell_contents
                                if isinstance(cell_contents, aiosqlite.Connection):
                                    target_conn = cell_contents
                                    break
                                elif hasattr(cell_contents, "_conn") and isinstance(cell_contents._conn, aiosqlite.Connection):
                                    target_conn = cell_contents._conn
                                    break
                            except (ValueError, AttributeError):
                                pass
                if target_conn is not None:
                    try:
                        res = target_conn.rollback()
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception:
                        pass
                await asyncio.sleep(base_delay * (1.5 ** attempt))
                continue
            raise


def _sanitize_fts_query(raw_query: Optional[str], operator: str = "OR") -> str:
    """Sanitizes raw query text into safe FTS5 boolean match expression."""
    if not raw_query or not raw_query.strip():
        return ""
    tokens = re.findall(r"[\w\-]+", raw_query.strip())
    clean_tokens = [t.strip("-") for t in tokens if t.strip("-")]
    if not clean_tokens:
        return ""
    return f" {operator} ".join(f'"{t}"*' for t in clean_tokens)


class SqliteMemoryAdapter(MemoryPort):
    """SQLite-backed memory adapter supporting working, episodic, semantic, and procedural tiers."""

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        timeout: float = SQLITE_CONNECT_TIMEOUT_SECONDS,
    ) -> None:
        if db_path is None:
            try:
                from carefold.config import settings
                if hasattr(settings, "get_catalog_db_path"):
                    db_path = settings.get_catalog_db_path()
                else:
                    db_path = settings.workspace_root / "catalog.db"
            except Exception:
                db_path = Path("catalog.db")
        self._db_path = str(db_path)
        self._timeout = timeout
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def _get_conn(self) -> aiosqlite.Connection:
        async with self._lock:
            if self._conn is None:
                if self._db_path != ":memory:":
                    Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
                conn = await aiosqlite.connect(self._db_path, timeout=self._timeout)
                conn.row_factory = aiosqlite.Row

                async def _init_connection():
                    await conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};")
                    await conn.execute(f"PRAGMA journal_mode = {SQLITE_JOURNAL_MODE};")
                    await conn.execute("PRAGMA foreign_keys = ON;")
                    await self._init_db(conn)
                    await conn.execute("SELECT 1 FROM memories_fts LIMIT 0;")

                try:
                    await _run_write_with_retry(_init_connection, conn=conn)
                except Exception:
                    await conn.close()
                    raise
                self._conn = conn
            return self._conn

    async def _init_db(self, conn: aiosqlite.Connection) -> None:
        async def _do_init():
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT NOT NULL,
                key TEXT NOT NULL,
                namespace TEXT NOT NULL,
                tier TEXT NOT NULL,
                value TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                salience REAL NOT NULL DEFAULT 1.0,
                access_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_accessed_at TEXT,
                PRIMARY KEY (namespace, key)
            );
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_id ON memories(id);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_ns_tier ON memories(namespace, tier);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_ns_key ON memories(namespace, key);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_ns_salience ON memories(namespace, salience DESC);")
            await conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                id UNINDEXED,
                namespace UNINDEXED,
                content,
                tokenize = 'porter unicode61'
            );
            """)
            await conn.commit()

        await _run_write_with_retry(_do_init, conn=conn)

    async def remember(
        self,
        key: str,
        value: Any,
        tier: MemoryTier,
        namespace: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        conn = await self._get_conn()
        mem_id = f"{len(namespace)}:{namespace}:{key}"
        tier_val = tier.value if isinstance(tier, MemoryTier) else str(tier)

        if isinstance(value, bytes):
            val_str = json.dumps(str(value))
        else:
            try:
                val_str = json.dumps(value)
            except (TypeError, ValueError):
                val_str = json.dumps(str(value))

        meta_str = json.dumps(metadata or {})
        now = datetime.now(timezone.utc).isoformat()
        if isinstance(value, str):
            content = f"{key} {value}"
        elif isinstance(value, (dict, list)):
            content = f"{key} {json.dumps(value)}"
        else:
            content = f"{key} {value}"

        async def _do_remember():
            async with self._lock:
                await conn.execute("""
                INSERT INTO memories (id, key, namespace, tier, value, metadata, salience, access_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1.0, 0, ?, ?)
                ON CONFLICT(namespace, key) DO UPDATE SET
                    id = excluded.id,
                    tier = excluded.tier,
                    value = excluded.value,
                    metadata = excluded.metadata,
                    updated_at = excluded.updated_at;
                """, (mem_id, key, namespace, tier_val, val_str, meta_str, now, now))
                await conn.execute("DELETE FROM memories_fts WHERE id = ?;", (mem_id,))
                await conn.execute(
                    "INSERT INTO memories_fts (id, namespace, content) VALUES (?, ?, ?);",
                    (mem_id, namespace, content),
                )
                await conn.commit()

        await _run_write_with_retry(_do_remember, conn=conn)

    async def recall(
        self,
        query: str,
        tier: Optional[MemoryTier] = None,
        namespace: str = "default",
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        conn = await self._get_conn()
        tier_val = tier.value if isinstance(tier, MemoryTier) else (str(tier) if tier else None)
        sanitized = _sanitize_fts_query(query)

        async def _do_recall():
            async with self._lock:
                if sanitized:
                    sql = """
                    SELECT m.*, (bm25(fts.memories_fts) * -1.0) * m.salience AS score
                    FROM memories_fts fts
                    JOIN memories m ON m.id = fts.id AND m.namespace = ?
                    WHERE fts.memories_fts MATCH ?
                      AND m.namespace = ?
                      AND (? IS NULL OR m.tier = ?)
                    ORDER BY score DESC
                    LIMIT ?;
                    """
                    params = (namespace, sanitized, namespace, tier_val, tier_val, limit)
                else:
                    sql = """
                    SELECT m.*, m.salience AS score
                    FROM memories m
                    WHERE m.namespace = ?
                      AND (? IS NULL OR m.tier = ?)
                    ORDER BY m.salience DESC, m.updated_at DESC
                    LIMIT ?;
                    """
                    params = (namespace, tier_val, tier_val, limit)

                async with conn.execute(sql, params) as cur:
                    rows = await cur.fetchall()

                results: List[Dict[str, Any]] = []
                for r in rows:
                    val = r["value"]
                    try:
                        val = json.loads(val)
                    except Exception:
                        pass
                    results.append({
                        "key": r["key"],
                        "value": val,
                        "tier": r["tier"],
                        "namespace": r["namespace"],
                        "metadata": json.loads(r["metadata"]),
                        "salience": r["salience"],
                        "access_count": r["access_count"],
                        "created_at": r["created_at"],
                        "updated_at": r["updated_at"],
                        "last_accessed_at": r["last_accessed_at"],
                        "score": r["score"],
                    })
                return results

        return await _run_write_with_retry(_do_recall, conn=conn)

    async def forget(self, key: str, namespace: str = "default") -> bool:
        conn = await self._get_conn()
        mem_id = f"{len(namespace)}:{namespace}:{key}"

        async def _do_forget():
            async with self._lock:
                cur = await conn.execute(
                    "DELETE FROM memories WHERE namespace = ? AND key = ?;",
                    (namespace, key),
                )
                await conn.execute("DELETE FROM memories_fts WHERE id = ?;", (mem_id,))
                await conn.commit()
                return cur.rowcount > 0

        return await _run_write_with_retry(_do_forget, conn=conn)

    async def reinforce(self, key: str, namespace: str = "default", delta: float = 0.1) -> None:
        if not math.isfinite(delta):
            raise ValueError(f"delta must be a finite float, got: {delta}")
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()

        async def _do_reinforce():
            async with self._lock:
                await conn.execute("""
                UPDATE memories
                SET salience = MAX(0.0, salience + ?),
                    access_count = access_count + 1,
                    last_accessed_at = ?
                WHERE namespace = ? AND key = ?;
                """, (delta, now, namespace, key))
                await conn.commit()

        await _run_write_with_retry(_do_reinforce, conn=conn)

    async def get(self, key: str, namespace: str = "default") -> Optional[Dict[str, Any]]:
        conn = await self._get_conn()
        async with self._lock:
            async with conn.execute(
                "SELECT * FROM memories WHERE namespace = ? AND key = ?;",
                (namespace, key),
            ) as cur:
                r = await cur.fetchone()
                if not r:
                    return None
                val = r["value"]
                try:
                    val = json.loads(val)
                except Exception:
                    pass
                return {
                    "key": r["key"],
                    "value": val,
                    "tier": r["tier"],
                    "namespace": r["namespace"],
                    "metadata": json.loads(r["metadata"]),
                    "salience": r["salience"],
                    "access_count": r["access_count"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "last_accessed_at": r["last_accessed_at"],
                }

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    async def __aenter__(self) -> SqliteMemoryAdapter:
        await self._get_conn()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    def __del__(self) -> None:
        if hasattr(self, "_conn") and self._conn is not None:
            try:
                self._conn.stop()
            except Exception:
                pass

