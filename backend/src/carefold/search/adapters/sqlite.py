# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""SQLite FTS5 implementation of SearchIndex port with fail-closed profile isolation."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Literal, Optional, Union

import aiosqlite

from carefold.constants.defaults import (
    SQLITE_BUSY_TIMEOUT_MS,
    SQLITE_CONNECT_TIMEOUT_SECONDS,
    SQLITE_JOURNAL_MODE,
)
from carefold.search.base import SearchIndex, SearchResult
from carefold.search.chunker import ClinicalChunker

logger = logging.getLogger("carefold.search.adapters.sqlite")


def _sanitize_fts_query(raw_query: Optional[str], operator: str = "OR") -> str:
    """Sanitizes raw query text into safe FTS5 boolean match expression."""
    if not raw_query or not raw_query.strip():
        return ""
    tokens = re.findall(r"[\w]+", raw_query.strip())
    clean_tokens = [t for t in tokens if t]
    if not clean_tokens:
        return ""
    return f" {operator} ".join(f'"{t}"*' for t in clean_tokens)


class SqliteSearchIndex(SearchIndex):
    """SQLite FTS5-backed search index providing fail-closed lexical and BM25 search."""

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        timeout: float = SQLITE_CONNECT_TIMEOUT_SECONDS,
        chunker: Optional[ClinicalChunker] = None,
    ) -> None:
        if db_path is None:
            try:
                from carefold.config import settings
                if hasattr(settings, "get_catalog_db_path"):
                    db_path = settings.get_catalog_db_path()
                elif hasattr(settings, "workspace_root"):
                    db_path = settings.workspace_root / "catalog.db"
                else:
                    db_path = Path("catalog.db")
            except Exception:
                db_path = Path("catalog.db")

        self._db_path = str(db_path)
        self._timeout = timeout
        self._chunker = chunker or ClinicalChunker()
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def _get_conn(self) -> aiosqlite.Connection:
        async with self._lock:
            if self._conn is None:
                if self._db_path != ":memory:":
                    Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
                conn = await aiosqlite.connect(self._db_path, timeout=self._timeout)
                conn.row_factory = aiosqlite.Row

                await conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};")
                if self._db_path != ":memory:":
                    await conn.execute(f"PRAGMA journal_mode = {SQLITE_JOURNAL_MODE};")
                await self._init_db(conn)
                self._conn = conn
            return self._conn

    async def _init_db(self, conn: aiosqlite.Connection) -> None:
        await conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
            content,
            metadata_json UNINDEXED,
            profile_id UNINDEXED,
            document_id UNINDEXED,
            chunk_id UNINDEXED,
            tokenize = 'unicode61'
        );
        """)
        await conn.commit()

    async def index_document(
        self,
        document_id: str,
        text: str,
        metadata: Dict[str, Any],
        profile_id: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Chunks and indexes document text into SQLite FTS5 table."""
        if not profile_id or not str(profile_id).strip():
            raise ValueError("profile_id is required")
        if not document_id or not str(document_id).strip():
            raise ValueError("document_id is required")

        pid = str(profile_id).strip()
        doc_id = str(document_id).strip()
        conn = await self._get_conn()

        # Delete any pre-existing chunks for this document under profile (idempotency)
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM document_chunks_fts WHERE document_id = ? AND profile_id = ?;",
                (doc_id, pid),
            )

        if not text or not text.strip():
            await conn.commit()
            return

        chunks = self._chunker.chunk(document_id=doc_id, text=text, metadata=metadata)
        if not chunks:
            await conn.commit()
            return

        insert_rows = []
        for ch in chunks:
            chunk_meta = {
                **metadata,
                "document_id": doc_id,
                "profile_id": pid,
                "user_id": user_id,
                "section": ch.section_name,
                "token_count": ch.token_count,
            }
            insert_rows.append((
                ch.text,
                json.dumps(chunk_meta),
                pid,
                doc_id,
                ch.chunk_id,
            ))

        async with conn.cursor() as cur:
            await cur.executemany(
                """
                INSERT INTO document_chunks_fts (content, metadata_json, profile_id, document_id, chunk_id)
                VALUES (?, ?, ?, ?, ?);
                """,
                insert_rows,
            )
        await conn.commit()

    async def search(
        self,
        query: str,
        profile_id: str,
        limit: int = 10,
        mode: Union[Literal["hybrid", "lexical", "semantic"], str] = "hybrid",
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Executes lexical BM25 search with strict profile scoping."""
        if not profile_id or not str(profile_id).strip():
            raise ValueError("profile_id is required")
        pid = str(profile_id).strip()

        if not query or not str(query).strip():
            return []

        sanitized = _sanitize_fts_query(query)
        if not sanitized:
            return []

        conn = await self._get_conn()
        fetch_limit = limit if not filters else max(limit * 3, 50)

        query_sql = """
        SELECT chunk_id, document_id, profile_id, content, metadata_json, rank
        FROM document_chunks_fts
        WHERE document_chunks_fts MATCH ?
          AND profile_id = ?
        ORDER BY rank
        LIMIT ?;
        """

        results: List[SearchResult] = []
        async with conn.execute(query_sql, (sanitized, pid, fetch_limit)) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                meta = {}
                if r["metadata_json"]:
                    try:
                        meta = json.loads(r["metadata_json"])
                    except Exception:
                        meta = {}

                # Apply metadata filters
                if filters:
                    match = True
                    for k, v in filters.items():
                        if k == "document_id" and r["document_id"] != v:
                            match = False
                            break
                        if k in meta and meta[k] != v:
                            match = False
                            break
                    if not match:
                        continue

                # In SQLite FTS5 BM25, lower rank is more relevant (e.g. -2.5 is better than -0.5).
                raw_rank = float(r["rank"])
                relevance_score = -1.0 * raw_rank if raw_rank < 0 else raw_rank

                results.append(
                    SearchResult(
                        document_id=r["document_id"],
                        chunk_id=r["chunk_id"],
                        content=r["content"],
                        score=relevance_score,
                        lexical_score=relevance_score,
                        semantic_score=0.0,
                        metadata=meta,
                        profile_id=r["profile_id"],
                        source=meta.get("source", "search"),
                    )
                )

                if len(results) >= limit:
                    break

        return results

    async def delete_document(self, document_id: str, profile_id: str) -> bool:
        """Deletes all chunks for document_id within profile_id."""
        if not profile_id or not str(profile_id).strip():
            raise ValueError("profile_id is required")
        if not document_id or not str(document_id).strip():
            return False

        pid = str(profile_id).strip()
        doc_id = str(document_id).strip()
        conn = await self._get_conn()
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM document_chunks_fts WHERE document_id = ? AND profile_id = ?;",
                (doc_id, pid),
            )
            deleted_count = cur.rowcount
        await conn.commit()
        return deleted_count > 0

    async def delete_profile_index(self, profile_id: str) -> int:
        """Purges all chunks belonging to profile_id during crypto-shredding."""
        if not profile_id or not str(profile_id).strip():
            raise ValueError("profile_id is required")

        pid = str(profile_id).strip()
        conn = await self._get_conn()
        async with conn.cursor() as cur:
            # First count how many will be deleted
            await cur.execute(
                "SELECT COUNT(*) FROM document_chunks_fts WHERE profile_id = ?;",
                (pid,),
            )
            row = await cur.fetchone()
            count = row[0] if row else 0

            await cur.execute(
                "DELETE FROM document_chunks_fts WHERE profile_id = ?;",
                (pid,),
            )
        await conn.commit()
        return max(0, count)

    async def purge_profile(self, profile_id: str) -> int:
        """Alias for delete_profile_index per api/profiles.py hook."""
        return await self.delete_profile_index(profile_id)

    async def reindex_all(self, profile_id: str) -> int:
        """Rebuilds and optimizes FTS5 index, returning count of indexed chunks."""
        if not profile_id or not str(profile_id).strip():
            raise ValueError("profile_id is required")

        pid = str(profile_id).strip()
        conn = await self._get_conn()
        async with conn.cursor() as cur:
            try:
                await cur.execute("INSERT INTO document_chunks_fts(document_chunks_fts) VALUES('rebuild');")
                await cur.execute("INSERT INTO document_chunks_fts(document_chunks_fts) VALUES('optimize');")
            except Exception as e:
                logger.debug("FTS5 rebuild/optimize warning: %s", e)
            await cur.execute(
                "SELECT COUNT(*) FROM document_chunks_fts WHERE profile_id = ?;",
                (pid,),
            )
            row = await cur.fetchone()
            count = row[0] if row else 0
        await conn.commit()
        return count

    async def close(self) -> None:
        """Closes the underlying aiosqlite connection."""
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None
