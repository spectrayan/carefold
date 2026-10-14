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

"""Spector cognitive search index adapter with profile isolation and RRF hybrid search."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
import urllib.error

from spector_client import AsyncSpectorClient
from spector_client.exceptions import (
    MemoryNotFoundError,
    SpectorClientError,
    SpectorServerError,
    TransportError,
)
from spector_client.models import MemoryTier, RecallRecord, SearchRecord

from carefold.config import Settings, settings as global_settings
from carefold.search.base import SearchIndex, SearchResult
from carefold.search.chunker import ClinicalChunk, ClinicalChunker

logger = logging.getLogger("carefold.search.adapters.spector")


class SpectorSearchIndex(SearchIndex):
    """Hexagonal search adapter backed by Spector Cognitive Memory with RRF hybrid fusion.

    Features:
    1. Per-profile client caching with physical namespace partition isolation (X-Namespace).
    2. Document chunking preserving clinical section boundaries via ClinicalChunker.
    3. Ingestion of rich chunk metadata (chunk index, section header, token count, source doc ID).
    4. Hybrid search fusing BM25 lexical rank and HNSW vector rank via Reciprocal Rank Fusion (k=60).
    5. Resilient circuit breaker falling back transparently to SqliteSearchIndex on network faults.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 5.0,
        fallback_to_sqlite: bool = True,
        fallback_index: Optional[SearchIndex] = None,
        client: Optional[Any] = None,
        chunker: Optional[ClinicalChunker] = None,
        cooldown_seconds: float = 30.0,
        rrf_k: int = 60,
    ) -> None:
        cfg = global_settings
        self.base_url = (base_url or getattr(cfg, "spector_url", "http://localhost:7070")).rstrip("/")
        self.timeout = timeout
        self.fallback_to_sqlite = fallback_to_sqlite
        self._fallback_index = fallback_index
        self._client = client  # Direct client override (for test doubles)
        self._chunker = chunker or ClinicalChunker()
        self.cooldown_seconds = cooldown_seconds
        self.rrf_k = rrf_k

        # Per-profile client cache: profile_id -> AsyncSpectorClient
        self._clients: Dict[str, Any] = {}
        self._is_degraded: bool = False
        self._cooldown_until: float = 0.0
        self._lock = asyncio.Lock()

    def _get_client_for_profile(self, profile_id: str) -> Any:
        """Resolves or creates an AsyncSpectorClient partitioned by profile_id."""
        if not profile_id or not str(profile_id).strip():
            raise ValueError("profile_id is required")
        pid = str(profile_id).strip()

        if self._client is not None:
            return self._client

        if pid not in self._clients:
            self._clients[pid] = (
                AsyncSpectorClient.builder()
                .with_rest(
                    base_url=self.base_url,
                    namespace=pid,
                    headers={"X-Namespace": pid},
                    timeout=self.timeout,
                )
                .build()
            )
        return self._clients[pid]

    def _get_fallback_index(self) -> SearchIndex:
        """Lazily creates fallback SqliteSearchIndex instance."""
        if self._fallback_index is None:
            from carefold.search.adapters.sqlite import SqliteSearchIndex
            self._fallback_index = SqliteSearchIndex()
        return self._fallback_index

    async def probe_health(self, profile_id: str = "default") -> bool:
        """Probes Spector server health status."""
        try:
            client = self._get_client_for_profile(profile_id)
            mem = getattr(client, "memory", client)
            if hasattr(mem, "status"):
                status = await asyncio.wait_for(mem.status(), timeout=min(self.timeout, 2.0))
                return status is not None
            return True
        except Exception:
            return False

    async def _check_degraded_state(self, profile_id: str) -> bool:
        """Evaluates circuit breaker state. Returns True if degraded fallback must be used."""
        if not self._is_degraded:
            return False
        now = time.time()
        if now < self._cooldown_until:
            return True
        if await self.probe_health(profile_id):
            logger.info("Spector service reconnected. Exiting degraded search state.")
            self._is_degraded = False
            return False
        else:
            self._cooldown_until = now + self.cooldown_seconds
            return True

    def _trigger_degraded(self, error: Exception) -> None:
        """Trips the circuit breaker into degraded fallback state."""
        logger.warning("Spector search error (%s). Activating fallback to SqliteSearchIndex.", error)
        self._is_degraded = True
        self._cooldown_until = time.time() + self.cooldown_seconds

    async def index_document(
        self,
        document_id: str,
        text: str,
        metadata: Dict[str, Any],
        profile_id: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Chunks document and indexes chunk metadata into Spector and fallback SQLite."""
        if not profile_id or not str(profile_id).strip():
            raise ValueError("profile_id is required")
        if not document_id or not str(document_id).strip():
            raise ValueError("document_id is required")
        pid = str(profile_id).strip()
        doc_id = str(document_id).strip()

        # Dual-write into fallback index so offline search remains complete
        if self.fallback_to_sqlite:
            try:
                fallback = self._get_fallback_index()
                await fallback.index_document(
                    document_id=doc_id,
                    text=text,
                    metadata=metadata,
                    profile_id=pid,
                    user_id=user_id,
                )
            except Exception as fb_err:
                logger.debug("Fallback SQLite index_document failed: %s", fb_err)

        if await self._check_degraded_state(pid):
            return

        chunks = self._chunker.chunk(document_id=doc_id, text=text, metadata=metadata)
        if not chunks:
            return

        client = self._get_client_for_profile(pid)
        mem = getattr(client, "memory", client)
        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            for idx, chunk in enumerate(chunks):
                chunk_tags = [
                    f"doc:{doc_id}",
                    f"chunk:{chunk.chunk_id}",
                    f"profile:{pid}",
                    f"source:{metadata.get('source', 'upload')}",
                ]
                if chunk.section_name:
                    chunk_tags.append(f"section:{chunk.section_name.lower()}")

                chunk_meta: Dict[str, Any] = {
                    **metadata,
                    "document_id": doc_id,
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": getattr(chunk, "chunk_index", idx),
                    "section_header": chunk.section_name,
                    "token_count": chunk.token_count,
                    "source_doc_id": doc_id,
                    "profile_id": pid,
                    "user_id": user_id,
                    "created_at": metadata.get("created_at", now_iso),
                    "id": chunk.chunk_id,
                    "_id": chunk.chunk_id,
                }

                # High-level memory remember
                if hasattr(mem, "remember"):
                    kwargs: Dict[str, Any] = {
                        "text": chunk.text,
                        "metadata": chunk_meta,
                    }
                    # Support both signature styles
                    import inspect
                    sig = inspect.signature(mem.remember)
                    if "tier" in sig.parameters:
                        kwargs["tier"] = MemoryTier.SEMANTIC
                    if "tags" in sig.parameters:
                        kwargs["tags"] = chunk_tags
                    if "chunk_id" in sig.parameters:
                        kwargs["chunk_id"] = chunk.chunk_id
                    if "namespace" in sig.parameters:
                        kwargs["namespace"] = pid

                    await mem.remember(**kwargs)
        except (
            TransportError,
            SpectorServerError,
            urllib.error.URLError,
            TimeoutError,
            asyncio.TimeoutError,
            OSError,
            ConnectionError,
        ) as err:
            if not self.fallback_to_sqlite:
                raise
            self._trigger_degraded(err)

    async def search(
        self,
        query: str,
        profile_id: str,
        limit: int = 10,
        mode: Union[Literal["hybrid", "lexical", "semantic"], str] = "hybrid",
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Executes profile-scoped hybrid, lexical, or semantic search."""
        if not profile_id or not str(profile_id).strip():
            raise ValueError("profile_id is required")
        pid = str(profile_id).strip()

        clean_query = query.strip() if query else ""
        if not clean_query:
            return []

        if await self._check_degraded_state(pid):
            fallback = self._get_fallback_index()
            return await fallback.search(
                query=query,
                profile_id=pid,
                limit=limit,
                mode=mode,
                filters=filters,
            )

        client = self._get_client_for_profile(pid)
        fetch_k = max(limit * 2, 20)

        try:
            if mode == "lexical":
                return await self._search_lexical(client, clean_query, pid, limit, filters)
            elif mode == "semantic":
                return await self._search_semantic(client, clean_query, pid, limit, filters)
            else:  # hybrid
                return await self._search_hybrid(client, clean_query, pid, limit, fetch_k, filters)
        except (
            TransportError,
            SpectorServerError,
            urllib.error.URLError,
            TimeoutError,
            asyncio.TimeoutError,
            OSError,
            ConnectionError,
        ) as err:
            if not self.fallback_to_sqlite:
                raise
            self._trigger_degraded(err)
            fallback = self._get_fallback_index()
            return await fallback.search(
                query=query,
                profile_id=pid,
                limit=limit,
                mode=mode,
                filters=filters,
            )

    async def _search_lexical(
        self,
        client: Any,
        query: str,
        profile_id: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        mem = getattr(client, "memory", client)
        if hasattr(mem, "search"):
            hits = await mem.search(query=query, top_k=limit)
        elif hasattr(mem, "recall"):
            hits = await mem.recall(query=query, top_k=limit)
        else:
            hits = []

        results: List[SearchResult] = []
        for hit in hits:
            meta = hit.metadata if isinstance(getattr(hit, "metadata", None), dict) else {}
            if filters and not self._matches_filters(meta, filters):
                continue
            cid = str(meta.get("chunk_id") or getattr(hit, "id", "unknown"))
            doc_id = str(meta.get("document_id") or meta.get("source_doc_id") or cid.split("#")[0])
            score = float(getattr(hit, "score", 1.0))
            results.append(
                SearchResult(
                    document_id=doc_id,
                    chunk_id=cid,
                    content=getattr(hit, "text", ""),
                    score=score,
                    lexical_score=score,
                    semantic_score=0.0,
                    metadata=meta,
                    profile_id=profile_id,
                    source=meta.get("source", "search"),
                )
            )
            if len(results) >= limit:
                break
        return results

    async def _search_semantic(
        self,
        client: Any,
        query: str,
        profile_id: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        mem = getattr(client, "memory", client)
        if hasattr(mem, "recall"):
            hits = await mem.recall(query=query, top_k=limit, profile="BALANCED")
        else:
            hits = []

        results: List[SearchResult] = []
        for hit in hits:
            meta = hit.metadata if isinstance(getattr(hit, "metadata", None), dict) else {}
            if filters and not self._matches_filters(meta, filters):
                continue
            cid = str(meta.get("chunk_id") or getattr(hit, "id", "unknown"))
            doc_id = str(meta.get("document_id") or meta.get("source_doc_id") or cid.split("#")[0])
            sim = getattr(hit, "similarity", None)
            score = float(sim if sim is not None else getattr(hit, "score", 1.0))
            results.append(
                SearchResult(
                    document_id=doc_id,
                    chunk_id=cid,
                    content=getattr(hit, "text", ""),
                    score=score,
                    lexical_score=0.0,
                    semantic_score=score,
                    metadata=meta,
                    profile_id=profile_id,
                    source=meta.get("source", "search"),
                )
            )
            if len(results) >= limit:
                break
        return results

    async def _search_hybrid(
        self,
        client: Any,
        query: str,
        profile_id: str,
        limit: int,
        fetch_k: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Concurrently retrieves BM25 and vector hits, then computes RRF scores."""
        mem = getattr(client, "memory", client)

        bm25_task = mem.search(query=query, top_k=fetch_k) if hasattr(mem, "search") else asyncio.sleep(0, result=[])
        vector_task = mem.recall(query=query, top_k=fetch_k, profile="BALANCED") if hasattr(mem, "recall") else asyncio.sleep(0, result=[])

        bm25_hits, vector_hits = await asyncio.gather(bm25_task, vector_task)

        bm25_ranks: Dict[str, int] = {}
        bm25_scores: Dict[str, float] = {}
        bm25_records: Dict[str, Any] = {}

        for rank, hit in enumerate(bm25_hits or [], start=1):
            meta = hit.metadata if isinstance(getattr(hit, "metadata", None), dict) else {}
            cid = str(meta.get("chunk_id") or meta.get("id") or getattr(hit, "id", None) or f"hit_{rank}")
            bm25_ranks[cid] = rank
            bm25_scores[cid] = float(getattr(hit, "score", 0.0))
            bm25_records[cid] = hit

        vector_ranks: Dict[str, int] = {}
        vector_scores: Dict[str, float] = {}
        vector_records: Dict[str, Any] = {}

        for rank, hit in enumerate(vector_hits or [], start=1):
            meta = hit.metadata if isinstance(getattr(hit, "metadata", None), dict) else {}
            cid = str(meta.get("chunk_id") or meta.get("id") or getattr(hit, "id", None) or f"hit_{rank}")
            vector_ranks[cid] = rank
            sim = getattr(hit, "similarity", None)
            vector_scores[cid] = float(sim if sim is not None else getattr(hit, "score", 0.0))
            vector_records[cid] = hit

        all_chunk_ids = list(set(bm25_ranks.keys()) | set(vector_ranks.keys()))
        rrf_k = self.rrf_k

        # Calculate normalized RRF scores:
        # raw_rrf(d) = (0.5 / (k + rank_bm25(d))) + (0.5 / (k + rank_vector(d)))
        # max_raw = 1.0 / (k + 1)
        # normalized = raw_rrf * (k + 1)
        scored_candidates: List[Dict[str, Any]] = []

        for cid in all_chunk_ids:
            raw_rrf = 0.0
            if cid in bm25_ranks:
                raw_rrf += 0.5 / (rrf_k + bm25_ranks[cid])
            if cid in vector_ranks:
                raw_rrf += 0.5 / (rrf_k + vector_ranks[cid])

            norm_score = raw_rrf * (rrf_k + 1)

            rec = vector_records.get(cid) or bm25_records.get(cid)
            meta = rec.metadata if isinstance(getattr(rec, "metadata", None), dict) else {}
            if filters and not self._matches_filters(meta, filters):
                continue

            doc_id = str(meta.get("document_id") or meta.get("source_doc_id") or cid.split("#")[0])
            lex_score = bm25_scores.get(cid, 0.0)
            sem_score = vector_scores.get(cid, 0.0)
            text_content = getattr(rec, "text", "")

            scored_candidates.append({
                "document_id": doc_id,
                "chunk_id": cid,
                "content": text_content,
                "score": round(norm_score, 6),
                "lexical_score": lex_score,
                "semantic_score": sem_score,
                "metadata": meta,
                "profile_id": profile_id,
                "source": meta.get("source", "search"),
            })

        # Deterministic multi-tier tie-breaking:
        # 1. score desc, 2. lexical_score desc, 3. chunk_id asc
        scored_candidates.sort(
            key=lambda x: (-x["score"], -x["lexical_score"], x["chunk_id"])
        )

        results: List[SearchResult] = [
            SearchResult(
                document_id=c["document_id"],
                chunk_id=c["chunk_id"],
                content=c["content"],
                score=c["score"],
                lexical_score=c["lexical_score"],
                semantic_score=c["semantic_score"],
                metadata=c["metadata"],
                profile_id=c["profile_id"],
                source=c["source"],
            )
            for c in scored_candidates[:limit]
        ]
        return results

    def _matches_filters(self, metadata: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        for k, v in filters.items():
            if k == "document_id" and metadata.get("document_id") != v:
                return False
            if k in metadata and metadata[k] != v:
                return False
        return True

    async def delete_document(self, document_id: str, profile_id: str) -> bool:
        """Removes all indexed chunks for a document."""
        if not profile_id or not str(profile_id).strip():
            raise ValueError("profile_id is required")
        if not document_id or not str(document_id).strip():
            return False
        pid = str(profile_id).strip()
        doc_id = str(document_id).strip()

        if self.fallback_to_sqlite:
            try:
                fallback = self._get_fallback_index()
                await fallback.delete_document(document_id=doc_id, profile_id=pid)
            except Exception as fb_err:
                logger.debug("Fallback SQLite delete_document error: %s", fb_err)

        if await self._check_degraded_state(pid):
            return True

        client = self._get_client_for_profile(pid)
        mem = getattr(client, "memory", client)

        try:
            if hasattr(mem, "browse"):
                records = await mem.browse(tags=[f"doc:{doc_id}"])
                for rec in records or []:
                    mem_id = rec.get("id") or rec.get("_id")
                    if mem_id and hasattr(mem, "forget"):
                        await mem.forget(mem_id, reason=f"Document {doc_id} deleted")
            return True
        except (
            TransportError,
            SpectorServerError,
            urllib.error.URLError,
            TimeoutError,
            asyncio.TimeoutError,
            OSError,
            ConnectionError,
        ) as err:
            if not self.fallback_to_sqlite:
                raise
            self._trigger_degraded(err)
            return True

    async def delete_profile_index(self, profile_id: str) -> int:
        """Purges Spector namespace and drops profile client from cache (AU-11)."""
        if not profile_id or not str(profile_id).strip():
            raise ValueError("profile_id is required")
        pid = str(profile_id).strip()

        count = 0
        if self.fallback_to_sqlite:
            try:
                fallback = self._get_fallback_index()
                count = await fallback.delete_profile_index(profile_id=pid)
            except Exception as fb_err:
                logger.debug("Fallback SQLite delete_profile_index error: %s", fb_err)

        if not self._is_degraded:
            try:
                client = self._get_client_for_profile(pid)
                mem = getattr(client, "memory", client)
                if hasattr(mem, "vacuum"):
                    await mem.vacuum()
                self._clients.pop(pid, None)
            except Exception as err:
                logger.warning("Spector vacuum failed for profile %s: %s", pid, err)

        return count

    async def purge_profile(self, profile_id: str) -> int:
        """Alias for delete_profile_index per api/profiles.py hook."""
        return await self.delete_profile_index(profile_id)

    async def reindex_all(self, profile_id: str) -> int:
        """Reindexes all documents in profile namespace."""
        if not profile_id or not str(profile_id).strip():
            raise ValueError("profile_id is required")
        pid = str(profile_id).strip()
        if self.fallback_to_sqlite:
            fallback = self._get_fallback_index()
            return await fallback.reindex_all(profile_id=pid)
        return 0

    async def close(self) -> None:
        """Closes all cached AsyncSpectorClient connections."""
        for pid, client in list(self._clients.items()):
            if hasattr(client, "close"):
                try:
                    res = client.close()
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as e:
                    logger.debug("Error closing client for profile %s: %s", pid, e)
        self._clients.clear()
        if self._fallback_index and hasattr(self._fallback_index, "close"):
            try:
                res = self._fallback_index.close()
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.debug("Error closing fallback index: %s", e)
