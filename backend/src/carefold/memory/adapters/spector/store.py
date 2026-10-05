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

"""SpectorStore: LangGraph BaseStore implementation backed by Spector Cognitive Memory."""

from __future__ import annotations

import asyncio
import concurrent.futures
from datetime import datetime, timezone
import inspect
import json
import logging
from pathlib import Path
import time
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)
import urllib.error

from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    MatchCondition,
    Op,
    PutOp,
    Result,
    SearchItem,
    SearchOp,
)
from langgraph.store.memory import InMemoryStore

from spector_client import AsyncSpectorClient, SpectorClient
from spector_client.client import AsyncMemoryClient, MemoryClient
from spector_client.exceptions import (
    MemoryNotFoundError,
    SpectorClientError,
    SpectorServerError,
    TransportError,
)
from spector_client.models import (
    MemoryRecord,
    MemoryTier as SpectorTier,
    RecallRecord,
)

logger = logging.getLogger("carefold.memory.adapters.spector.store")


class SpectorStore(BaseStore):
    """LangGraph BaseStore backed by Spector Cognitive Memory with resilient fallback.

    Subclasses LangGraph's native BaseStore to handle GetOp, PutOp (upsert and delete),
    SearchOp, and ListNamespacesOp across async (abatch) and sync (batch) runtimes.
    """

    supports_ttl: bool = False

    def __init__(
        self,
        base_url: str = "http://localhost:7070",
        *,
        api_key: Optional[str] = None,
        bearer_token: Optional[str] = None,
        timeout: float = 5.0,
        fallback_to_sqlite: bool = True,
        fallback_store: Optional[BaseStore] = None,
        client: Optional[Any] = None,
        sync_client: Optional[Any] = None,
        async_client: Optional[Any] = None,
        cooldown_seconds: float = 30.0,
        fallback_db_path: Optional[Union[str, Path]] = None,
        ttl_config: Optional[Any] = None,
    ) -> None:
        """Initializes SpectorStore with primary Spector clients and fallback storage.

        Args:
            base_url: Base URL of Spector Synapse service (default: http://localhost:7070).
            api_key: Optional API key for authenticated Spector gateway.
            bearer_token: Optional Bearer token.
            timeout: Network connection and read timeout in seconds.
            fallback_to_sqlite: If True, transparently falls back to local storage on errors.
            fallback_store: Optional pre-configured fallback store (defaults to InMemoryStore).
            client: Optional pre-built SpectorClient, AsyncSpectorClient, or simulated memory client.
            sync_client: Optional pre-built synchronous SpectorClient.
            async_client: Optional pre-built asynchronous AsyncSpectorClient.
            cooldown_seconds: Duration in seconds to stay in degraded state before re-probing.
            fallback_db_path: Optional path to SQLite database for fallback storage.
            ttl_config: Optional LangGraph TTL configuration.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.bearer_token = bearer_token
        self.timeout = timeout
        self.fallback_to_sqlite = fallback_to_sqlite
        self.cooldown_seconds = cooldown_seconds
        self.fallback_db_path = fallback_db_path
        self.ttl_config = ttl_config

        # Asynchronous client resolution for abatch()
        if async_client is not None:
            self._async_client = async_client
            self._async_memory: AsyncMemoryClient = getattr(async_client, "memory", async_client)
        elif client is not None:
            self._async_client = client
            self._async_memory: AsyncMemoryClient = getattr(client, "memory", client)
        else:
            self._async_client = (
                AsyncSpectorClient.builder()
                .with_rest(
                    base_url=self.base_url,
                    api_key=self.api_key,
                    bearer_token=self.bearer_token,
                    timeout=self.timeout,
                )
                .build()
            )
            self._async_memory = self._async_client.memory

        # Synchronous client resolution for batch()
        if sync_client is not None:
            self._sync_client = sync_client
            self._sync_memory: Optional[MemoryClient] = getattr(sync_client, "memory", sync_client)
        elif client is not None and not inspect.iscoroutinefunction(getattr(client, "find", None)):
            self._sync_client = client
            self._sync_memory = getattr(client, "memory", client)
        elif client is not None:
            # Client provided was purely async or test double
            self._sync_client = None
            self._sync_memory = None
        else:
            self._sync_client = (
                SpectorClient.builder()
                .with_rest(
                    base_url=self.base_url,
                    api_key=self.api_key,
                    bearer_token=self.bearer_token,
                    timeout=self.timeout,
                )
                .build()
            )
            self._sync_memory = self._sync_client.memory

        # Resilient fallback store & state
        self._fallback_store = fallback_store or InMemoryStore()
        self._is_degraded: bool = False
        self._cooldown_until: float = 0.0

        # In-memory index of seen namespaces for fast ListNamespacesOp resolution
        self._known_namespaces: Set[Tuple[str, ...]] = set()

    # =========================================================================
    # LangGraph BaseStore Core Contracts: abatch & batch
    # =========================================================================

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        """Asynchronously executes a batch of LangGraph operations against Spector.

        Args:
            ops: Iterable of operations (GetOp, PutOp, SearchOp, ListNamespacesOp).

        Returns:
            List of results matching the order and type of requested operations.
        """
        ops_list = list(ops)
        now = time.time()

        # Check circuit breaker cooldown
        if self._is_degraded:
            if now < self._cooldown_until:
                return await self._fallback_store.abatch(ops_list)
            # Cooldown expired: probe health
            if not await self._async_probe_health():
                self._cooldown_until = now + self.cooldown_seconds
                return await self._fallback_store.abatch(ops_list)
            # Reconnected successfully
            logger.info("Spector service reconnected. Exiting degraded fallback state.")
            self._is_degraded = False

        try:
            return await self._execute_async_batch(ops_list)
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
            logger.warning(
                "Spector operation failed: %s. Activating resilient fallback.",
                err,
            )
            self._is_degraded = True
            self._cooldown_until = now + self.cooldown_seconds
            return await self._fallback_store.abatch(ops_list)

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        """Synchronously executes a batch of LangGraph operations against Spector.

        Args:
            ops: Iterable of operations (GetOp, PutOp, SearchOp, ListNamespacesOp).

        Returns:
            List of results matching the order and type of requested operations.
        """
        ops_list = list(ops)

        if self._sync_memory is not None:
            now = time.time()
            if self._is_degraded:
                if now < self._cooldown_until:
                    return self._fallback_store.batch(ops_list)
                if not self._sync_probe_health():
                    self._cooldown_until = now + self.cooldown_seconds
                    return self._fallback_store.batch(ops_list)
                logger.info("Spector service reconnected. Exiting degraded fallback state.")
                self._is_degraded = False

            try:
                return self._execute_sync_batch(ops_list)
            except (
                TransportError,
                SpectorServerError,
                urllib.error.URLError,
                TimeoutError,
                OSError,
                ConnectionError,
            ) as err:
                if not self.fallback_to_sqlite:
                    raise
                logger.warning(
                    "Spector sync operation failed: %s. Activating resilient fallback.",
                    err,
                )
                self._is_degraded = True
                self._cooldown_until = now + self.cooldown_seconds
                return self._fallback_store.batch(ops_list)
        else:
            # Synchronous execution bridge when only async client is available
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(lambda: asyncio.run(self.abatch(ops_list))).result()
            else:
                return asyncio.run(self.abatch(ops_list))

    # =========================================================================
    # Asynchronous Execution Internals
    # =========================================================================

    async def _execute_async_batch(self, ops: Sequence[Op]) -> list[Result]:
        """Executes operations sequentially across async clients."""
        results: list[Result] = []
        for op in ops:
            if isinstance(op, GetOp):
                results.append(await self._async_handle_get(op))
            elif isinstance(op, PutOp):
                results.append(await self._async_handle_put(op))
            elif isinstance(op, SearchOp):
                results.append(await self._async_handle_search(op))
            elif isinstance(op, ListNamespacesOp):
                results.append(self._handle_list_namespaces(op))
            else:
                raise ValueError(f"Unsupported LangGraph operation type: {type(op)}")
        return results

    async def _async_handle_get(self, op: GetOp) -> Optional[Item]:
        """Handles GetOp: Point lookup by deterministic composite memory ID."""
        mem_id = self._make_id(op.namespace, op.key)
        try:
            record = await self._async_memory.find(mem_id)
        except MemoryNotFoundError:
            return None

        if record is None or getattr(record, "tombstoned", False):
            return None

        value = record.metadata.get("value") if isinstance(record.metadata, dict) else None
        if not isinstance(value, dict):
            value = {"text": record.text}

        created_at = self._parse_timestamp(
            (record.metadata.get("created_at") if isinstance(record.metadata, dict) else None)
            or getattr(record, "created_at", None)
        )
        updated_at = self._parse_timestamp(
            (record.metadata.get("updated_at") if isinstance(record.metadata, dict) else None)
            or getattr(record, "updated_at", None)
        )

        return Item(
            value=value,
            key=op.key,
            namespace=op.namespace,
            created_at=created_at,
            updated_at=updated_at,
        )

    async def _async_handle_put(self, op: PutOp) -> None:
        """Handles PutOp: upserts memory or forgets if value is None."""
        mem_id = self._make_id(op.namespace, op.key)

        # Deletion branch
        if op.value is None:
            try:
                await self._async_memory.forget(mem_id, reason="LangGraph delete")
            except MemoryNotFoundError:
                pass
            return None

        # Upsert branch
        text = self._extract_text(op.value)
        tier = self._extract_tier(op.value)
        tags = self._generate_tags(op.namespace, op.key)

        now_iso = datetime.now(timezone.utc).isoformat()
        metadata: Dict[str, Any] = {
            "id": mem_id,
            "_id": mem_id,
            "namespace": list(op.namespace),
            "key": op.key,
            "value": op.value,
            "created_at": op.value.get("created_at", now_iso) if isinstance(op.value, dict) else now_iso,
            "updated_at": now_iso,
        }

        interest = float(op.value.get("interest", 0.0)) if isinstance(op.value, dict) else 0.0
        urgency = float(op.value.get("urgency", 0.0)) if isinstance(op.value, dict) else 0.0
        challenge = float(op.value.get("challenge", 0.0)) if isinstance(op.value, dict) else 0.0
        valence = int(op.value.get("valence", 0)) if isinstance(op.value, dict) else 0
        arousal = int(op.value.get("arousal", 0)) if isinstance(op.value, dict) else 0

        await self._async_memory.remember(
            text=text,
            tier=tier,
            tags=tags,
            interest=interest,
            urgency=urgency,
            challenge=challenge,
            valence=valence,
            arousal=arousal,
            metadata=metadata,
        )
        self._known_namespaces.add(op.namespace)
        return None

    async def _async_handle_search(self, op: SearchOp) -> List[SearchItem]:
        """Handles SearchOp: Cognitive recall with biological scoring & tag filtering."""
        tags: List[str] = []
        if op.namespace_prefix:
            ns_str = ":".join(op.namespace_prefix)
            tags.append(f"nsprefix:{ns_str}")

        offset = op.offset or 0
        limit = op.limit or 10
        fetch_limit = limit + offset
        query_text = (op.query or "").strip() or "*"

        records = await self._async_memory.recall(
            query=query_text,
            top_k=fetch_limit,
            tags=tags if tags else None,
        )

        results: List[SearchItem] = []
        for rec in records:
            meta = rec.metadata if isinstance(rec.metadata, dict) else {}
            val = meta.get("value")
            if not isinstance(val, dict):
                val = {"text": rec.text}

            # Filter evaluation
            if op.filter and not self._evaluate_filter(val, op.filter):
                continue

            rec_ns_list = meta.get("namespace")
            rec_ns = (
                tuple(str(x) for x in rec_ns_list)
                if isinstance(rec_ns_list, list)
                else op.namespace_prefix
            )

            rec_key = meta.get("key")
            if not rec_key:
                rec_key = rec.id.split(":")[-1] if ":" in str(rec.id) else str(rec.id)

            created_at = self._parse_timestamp(
                meta.get("created_at") or getattr(rec, "created_at", None)
            )
            updated_at = self._parse_timestamp(
                meta.get("updated_at") or getattr(rec, "updated_at", None)
            )
            score = float(rec.score) if getattr(rec, "score", None) is not None else None

            results.append(
                SearchItem(
                    namespace=rec_ns,
                    key=str(rec_key),
                    value=val,
                    created_at=created_at,
                    updated_at=updated_at,
                    score=score,
                )
            )

        return results[offset : offset + limit]

    # =========================================================================
    # Synchronous Execution Internals
    # =========================================================================

    def _execute_sync_batch(self, ops: Sequence[Op]) -> list[Result]:
        """Executes operations sequentially using synchronous MemoryClient."""
        results: list[Result] = []
        for op in ops:
            if isinstance(op, GetOp):
                results.append(self._sync_handle_get(op))
            elif isinstance(op, PutOp):
                results.append(self._sync_handle_put(op))
            elif isinstance(op, SearchOp):
                results.append(self._sync_handle_search(op))
            elif isinstance(op, ListNamespacesOp):
                results.append(self._handle_list_namespaces(op))
            else:
                raise ValueError(f"Unsupported LangGraph operation type: {type(op)}")
        return results

    def _sync_handle_get(self, op: GetOp) -> Optional[Item]:
        """Synchronous GetOp handler."""
        if self._sync_memory is None:
            return None
        mem_id = self._make_id(op.namespace, op.key)
        try:
            record = self._sync_memory.find(mem_id)
        except MemoryNotFoundError:
            return None

        if record is None or getattr(record, "tombstoned", False):
            return None

        value = record.metadata.get("value") if isinstance(record.metadata, dict) else None
        if not isinstance(value, dict):
            value = {"text": record.text}

        created_at = self._parse_timestamp(
            (record.metadata.get("created_at") if isinstance(record.metadata, dict) else None)
            or getattr(record, "created_at", None)
        )
        updated_at = self._parse_timestamp(
            (record.metadata.get("updated_at") if isinstance(record.metadata, dict) else None)
            or getattr(record, "updated_at", None)
        )

        return Item(
            value=value,
            key=op.key,
            namespace=op.namespace,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _sync_handle_put(self, op: PutOp) -> None:
        """Synchronous PutOp handler."""
        if self._sync_memory is None:
            return None
        mem_id = self._make_id(op.namespace, op.key)

        if op.value is None:
            try:
                self._sync_memory.forget(mem_id, reason="LangGraph delete")
            except MemoryNotFoundError:
                pass
            return None

        text = self._extract_text(op.value)
        tier = self._extract_tier(op.value)
        tags = self._generate_tags(op.namespace, op.key)

        now_iso = datetime.now(timezone.utc).isoformat()
        metadata: Dict[str, Any] = {
            "id": mem_id,
            "_id": mem_id,
            "namespace": list(op.namespace),
            "key": op.key,
            "value": op.value,
            "created_at": op.value.get("created_at", now_iso) if isinstance(op.value, dict) else now_iso,
            "updated_at": now_iso,
        }

        interest = float(op.value.get("interest", 0.0)) if isinstance(op.value, dict) else 0.0
        urgency = float(op.value.get("urgency", 0.0)) if isinstance(op.value, dict) else 0.0
        challenge = float(op.value.get("challenge", 0.0)) if isinstance(op.value, dict) else 0.0
        valence = int(op.value.get("valence", 0)) if isinstance(op.value, dict) else 0
        arousal = int(op.value.get("arousal", 0)) if isinstance(op.value, dict) else 0

        self._sync_memory.remember(
            text=text,
            tier=tier,
            tags=tags,
            interest=interest,
            urgency=urgency,
            challenge=challenge,
            valence=valence,
            arousal=arousal,
            metadata=metadata,
        )
        self._known_namespaces.add(op.namespace)
        return None

    def _sync_handle_search(self, op: SearchOp) -> List[SearchItem]:
        """Synchronous SearchOp handler."""
        if self._sync_memory is None:
            return []
        tags: List[str] = []
        if op.namespace_prefix:
            ns_str = ":".join(op.namespace_prefix)
            tags.append(f"nsprefix:{ns_str}")

        offset = op.offset or 0
        limit = op.limit or 10
        fetch_limit = limit + offset
        query_text = (op.query or "").strip() or "*"

        records = self._sync_memory.recall(
            query=query_text,
            top_k=fetch_limit,
            tags=tags if tags else None,
        )

        results: List[SearchItem] = []
        for rec in records:
            meta = rec.metadata if isinstance(rec.metadata, dict) else {}
            val = meta.get("value")
            if not isinstance(val, dict):
                val = {"text": rec.text}

            if op.filter and not self._evaluate_filter(val, op.filter):
                continue

            rec_ns_list = meta.get("namespace")
            rec_ns = (
                tuple(str(x) for x in rec_ns_list)
                if isinstance(rec_ns_list, list)
                else op.namespace_prefix
            )

            rec_key = meta.get("key")
            if not rec_key:
                rec_key = rec.id.split(":")[-1] if ":" in str(rec.id) else str(rec.id)

            created_at = self._parse_timestamp(
                meta.get("created_at") or getattr(rec, "created_at", None)
            )
            updated_at = self._parse_timestamp(
                meta.get("updated_at") or getattr(rec, "updated_at", None)
            )
            score = float(rec.score) if getattr(rec, "score", None) is not None else None

            results.append(
                SearchItem(
                    namespace=rec_ns,
                    key=str(rec_key),
                    value=val,
                    created_at=created_at,
                    updated_at=updated_at,
                    score=score,
                )
            )

        return results[offset : offset + limit]

    # =========================================================================
    # Namespace Listing & Matching
    # =========================================================================

    def _handle_list_namespaces(self, op: ListNamespacesOp) -> List[Tuple[str, ...]]:
        """Handles ListNamespacesOp using local index and match conditions."""
        namespaces = list(set(self._known_namespaces))

        if op.match_conditions:
            namespaces = [
                ns
                for ns in namespaces
                if all(
                    self._does_match(condition, ns)
                    for condition in op.match_conditions
                )
            ]

        if op.max_depth is not None:
            namespaces = sorted({ns[: op.max_depth] for ns in namespaces})
        else:
            namespaces = sorted(namespaces)

        offset = op.offset or 0
        limit = op.limit or 100
        return namespaces[offset : offset + limit]

    @staticmethod
    def _does_match(condition: MatchCondition, key: Tuple[str, ...]) -> bool:
        """Evaluates prefix/suffix match conditions with wildcard support."""
        match_type = condition.match_type
        path = condition.path

        if len(key) < len(path):
            return False

        if match_type == "prefix":
            for k_elem, p_elem in zip(key, path):
                if p_elem == "*":
                    continue
                if k_elem != p_elem:
                    return False
            return True
        elif match_type == "suffix":
            for k_elem, p_elem in zip(reversed(key), reversed(path)):
                if p_elem == "*":
                    continue
                if k_elem != p_elem:
                    return False
            return True
        else:
            raise ValueError(f"Unsupported namespace match type: {match_type}")

    # =========================================================================
    # Helper Utilities: Addressing, Formatting & Health Probes
    # =========================================================================

    @staticmethod
    def _make_id(namespace: Tuple[str, ...], key: str) -> str:
        """Serializes (namespace, key) to composite identifier string."""
        ns_str = ":".join(namespace)
        return f"{ns_str}:{key}" if ns_str else key

    @staticmethod
    def _generate_tags(namespace: Tuple[str, ...], key: str) -> List[str]:
        """Generates synaptic tags for exact key lookup and prefix matching."""
        tags = [f"key:{key}"]
        if namespace:
            ns_str = ":".join(namespace)
            tags.append(f"ns:{ns_str}")
            for i in range(1, len(namespace) + 1):
                prefix_str = ":".join(namespace[:i])
                tags.append(f"nsprefix:{prefix_str}")
        return tags

    @staticmethod
    def _extract_text(value: Any) -> str:
        """Extracts plain text content for vector embedding and graph nodes."""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for field in ("text", "content", "summary", "message", "query"):
                if field in value and isinstance(value[field], str) and value[field].strip():
                    return value[field].strip()
            return json.dumps(value, ensure_ascii=False, default=str)
        return str(value)

    @staticmethod
    def _extract_tier(value: Any) -> SpectorTier:
        """Extracts and normalizes cognitive memory tier."""
        if not isinstance(value, dict):
            return SpectorTier.SEMANTIC
        raw_val = value.get("tier", "SEMANTIC")
        raw_tier = getattr(raw_val, "value", raw_val) or "SEMANTIC"
        raw_tier = str(raw_tier).upper()
        mapping = {
            "WORKING": SpectorTier.WORKING,
            "EPISODIC": SpectorTier.EPISODIC,
            "SEMANTIC": SpectorTier.SEMANTIC,
            "PROCEDURAL": SpectorTier.PROCEDURAL,
        }
        return mapping.get(raw_tier, SpectorTier.SEMANTIC)

    @staticmethod
    def _parse_timestamp(ts: Optional[Union[str, datetime]]) -> datetime:
        """Parses string or datetime to UTC-aware datetime instance."""
        if isinstance(ts, datetime):
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _evaluate_filter(item_val: Dict[str, Any], filter_dict: Dict[str, Any]) -> bool:
        """Evaluates dictionary key-value filter conditions against stored item."""
        for k, v in filter_dict.items():
            item_field = item_val.get(k)
            if k == "tier":
                val_tier = getattr(item_field, "value", item_field)
                v_tier = getattr(v, "value", v)
                if str(val_tier).lower() != str(v_tier).lower():
                    return False
            else:
                if item_field != v:
                    return False
        return True

    async def _async_probe_health(self) -> bool:
        """Lightweight asynchronous health check to probe Spector availability."""
        try:
            if hasattr(self._async_memory, "status"):
                status = await asyncio.wait_for(
                    self._async_memory.status(),
                    timeout=min(self.timeout, 2.0),
                )
                return status is not None
            return True
        except Exception:
            return False

    def _sync_probe_health(self) -> bool:
        """Lightweight synchronous health check to probe Spector availability."""
        try:
            if self._sync_memory is not None and hasattr(self._sync_memory, "status"):
                status = self._sync_memory.status()
                return status is not None
            return True
        except Exception:
            return False

    # =========================================================================
    # Lifecycle & Cleanup
    # =========================================================================

    def close(self) -> None:
        """Synchronously closes client transports."""
        if self._sync_client is not None and hasattr(self._sync_client, "close"):
            try:
                self._sync_client.close()
            except Exception as e:
                logger.debug("Error closing Spector sync client: %s", e)

    async def aclose(self) -> None:
        """Asynchronously closes client transports."""
        if self._async_client is not None and hasattr(self._async_client, "close"):
            try:
                res = self._async_client.close()
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.debug("Error closing Spector async client: %s", e)
        self.close()
