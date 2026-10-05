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

"""SQLite catalog adapter implementing CatalogPort with FTS5 and category trees."""

from __future__ import annotations

import asyncio
import json
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
from carefold.memory.ports.catalog_port import CatalogPort
from carefold.schemas.manifest import AgentManifest, SkillManifest

CANONICAL_DOMAINS = ["clinical", "therapy", "wellness", "navigation", "education"]


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


def sanitize_fts_query(raw_query: Optional[str], operator: str = "OR") -> str:
    """Sanitizes raw query text into safe FTS5 boolean match expression."""
    if not raw_query or not raw_query.strip():
        return ""
    tokens = re.findall(r"[\w\-]+", raw_query.strip())
    clean_tokens = [t.strip("-") for t in tokens if t.strip("-")]
    if not clean_tokens:
        return ""
    return f" {operator} ".join(f'"{t}"*' for t in clean_tokens)


def build_category_tree_from_rows(
    rows: List[Dict[str, Any]],
    domain_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Assembles hierarchical domain -> category -> subcategory tree."""
    tree: Dict[str, Any] = {
        d: {"count": 0, "categories": {}} for d in CANONICAL_DOMAINS
    }
    total = 0

    for r in rows:
        domain = (r.get("domain") or "wellness").lower().strip()
        cat = (r.get("category") or "").strip()

        if domain not in tree:
            tree[domain] = {"count": 0, "categories": {}}

        tree[domain]["count"] += 1
        total += 1

        if not cat:
            continue

        # Strip redundant leading domain prefix (e.g. 'navigation.insurance' -> 'insurance')
        if cat.startswith(domain + "."):
            sub_path = cat[len(domain) + 1:]
        elif cat == domain:
            continue
        else:
            sub_path = cat

        parts = [p.strip() for p in sub_path.split(".") if p.strip()]
        curr = tree[domain]["categories"]
        for part in parts:
            if part not in curr:
                curr[part] = {"count": 0, "subcategories": {}}
            curr[part]["count"] += 1
            curr = curr[part]["subcategories"]

    if domain_filter:
        df = domain_filter.lower().strip()
        filtered = {df: tree.get(df, {"count": 0, "categories": {}})}
        return {"total": filtered[df]["count"], "domains": filtered}

    return {"total": total, "domains": tree}


class SqliteCatalogAdapter(CatalogPort):
    """SQLite-backed catalog adapter supporting FTS5 search and taxonomy aggregation."""

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
                    await conn.execute("SELECT 1 FROM agents_fts LIMIT 0;")
                    await conn.execute("SELECT 1 FROM skills_fts LIMIT 0;")

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
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT '0.1.0',
                domain TEXT NOT NULL DEFAULT 'wellness',
                category TEXT NOT NULL DEFAULT '',
                risk_class TEXT NOT NULL DEFAULT 'wellness',
                tags TEXT NOT NULL DEFAULT '[]',
                description TEXT NOT NULL DEFAULT '',
                hidden INTEGER NOT NULL DEFAULT 0,
                manifest_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_domain ON agents(domain);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_category ON agents(category);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_domain_cat ON agents(domain, category);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_hidden ON agents(hidden);")

            await conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS agents_fts USING fts5(
                id UNINDEXED,
                title,
                description,
                tags,
                category,
                content,
                tokenize = 'porter unicode61'
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT '0.1.0',
                domain TEXT NOT NULL DEFAULT 'wellness',
                category TEXT NOT NULL DEFAULT '',
                risk_class TEXT NOT NULL DEFAULT 'wellness',
                tags TEXT NOT NULL DEFAULT '[]',
                description TEXT NOT NULL DEFAULT '',
                manifest_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_skills_domain_cat ON skills(domain, category);")

            await conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
                id UNINDEXED,
                name,
                description,
                tags,
                category,
                instructions,
                tokenize = 'porter unicode61'
            );
            """)
            await conn.commit()

        await _run_write_with_retry(_do_init, conn=conn)

    async def index_agent(self, manifest: AgentManifest) -> None:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        domain_val = manifest.domain.value if hasattr(manifest.domain, "value") else str(manifest.domain)
        risk_val = manifest.risk_class.value if hasattr(manifest.risk_class, "value") else str(manifest.risk_class)
        tags_str = " ".join(manifest.tags)
        tags_json = json.dumps(manifest.tags)
        hidden_int = 1 if manifest.hidden else 0

        persona_content = ""
        if isinstance(manifest.persona, str):
            persona_content = manifest.persona
        elif hasattr(manifest.persona, "instructions"):
            persona_content = f"{manifest.persona.role or ''} {manifest.persona.instructions or ''}"

        async def _do_index_agent():
            async with self._lock:
                await conn.execute("""
                INSERT INTO agents (id, title, version, domain, category, risk_class, tags, description, hidden, manifest_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    version = excluded.version,
                    domain = excluded.domain,
                    category = excluded.category,
                    risk_class = excluded.risk_class,
                    tags = excluded.tags,
                    description = excluded.description,
                    hidden = excluded.hidden,
                    manifest_json = excluded.manifest_json,
                    updated_at = excluded.updated_at;
                """, (
                    manifest.id,
                    manifest.title,
                    manifest.version,
                    domain_val,
                    manifest.category,
                    risk_val,
                    tags_json,
                    manifest.description,
                    hidden_int,
                    manifest.model_dump_json(),
                    now,
                ))
                await conn.execute("DELETE FROM agents_fts WHERE id = ?;", (manifest.id,))
                await conn.execute("""
                INSERT INTO agents_fts (id, title, description, tags, category, content)
                VALUES (?, ?, ?, ?, ?, ?);
                """, (manifest.id, manifest.title, manifest.description, tags_str, manifest.category, persona_content))
                await conn.commit()

        await _run_write_with_retry(_do_index_agent, conn=conn)

    async def index_skill(self, manifest: SkillManifest) -> None:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        domain_val = manifest.domain.value if hasattr(manifest.domain, "value") else str(manifest.domain)
        risk_val = manifest.risk_class.value if hasattr(manifest.risk_class, "value") else str(manifest.risk_class)
        tags_str = " ".join(manifest.tags)
        tags_json = json.dumps(manifest.tags)

        async def _do_index_skill():
            async with self._lock:
                await conn.execute("""
                INSERT INTO skills (id, name, version, domain, category, risk_class, tags, description, manifest_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    version = excluded.version,
                    domain = excluded.domain,
                    category = excluded.category,
                    risk_class = excluded.risk_class,
                    tags = excluded.tags,
                    description = excluded.description,
                    manifest_json = excluded.manifest_json,
                    updated_at = excluded.updated_at;
                """, (
                    manifest.id,
                    manifest.name,
                    manifest.version,
                    domain_val,
                    manifest.category,
                    risk_val,
                    tags_json,
                    manifest.description,
                    manifest.model_dump_json(),
                    now,
                ))
                await conn.execute("DELETE FROM skills_fts WHERE id = ?;", (manifest.id,))
                await conn.execute("""
                INSERT INTO skills_fts (id, name, description, tags, category, instructions)
                VALUES (?, ?, ?, ?, ?, ?);
                """, (manifest.id, manifest.name, manifest.description, tags_str, manifest.category, manifest.instructions or ""))
                await conn.commit()

        await _run_write_with_retry(_do_index_skill, conn=conn)

    async def search_agents(
        self,
        query: Optional[str] = None,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
        *,
        offset: int = 0,
        tags: Optional[List[str]] = None,
        include_hidden: bool = False,
    ) -> List[AgentManifest]:
        conn = await self._get_conn()
        sanitized = sanitize_fts_query(query) if query else ""
        cat_prefix = f"{category}.%" if category else None
        hidden_clause = "1 = 1" if include_hidden else "a.hidden = 0"

        clean_tags = [t.lower().strip() for t in tags if t and t.strip()] if tags else []
        tag_clause = ""
        if clean_tags:
            placeholders = ", ".join("?" for _ in clean_tags)
            tag_clause = f"AND EXISTS (SELECT 1 FROM json_each(a.tags) WHERE LOWER(value) IN ({placeholders}))"

        async def _do_search_agents():
            async with self._lock:
                if sanitized:
                    sql = f"""
                    SELECT a.manifest_json, (bm25(fts.agents_fts) * -1.0) AS score
                    FROM agents_fts fts
                    JOIN agents a ON a.id = fts.id
                    WHERE fts.agents_fts MATCH ?
                      AND (? IS NULL OR LOWER(a.domain) = LOWER(?))
                      AND (? IS NULL OR LOWER(a.category) = LOWER(?) OR LOWER(a.category) LIKE LOWER(?))
                      AND {hidden_clause}
                      {tag_clause}
                    ORDER BY score DESC
                    LIMIT ? OFFSET ?;
                    """
                    params = [sanitized, domain, domain, category, category, cat_prefix] + clean_tags + [limit, offset]
                else:
                    sql = f"""
                    SELECT a.manifest_json
                    FROM agents a
                    WHERE (? IS NULL OR LOWER(a.domain) = LOWER(?))
                      AND (? IS NULL OR LOWER(a.category) = LOWER(?) OR LOWER(a.category) LIKE LOWER(?))
                      AND {hidden_clause}
                      {tag_clause}
                    ORDER BY a.title ASC
                    LIMIT ? OFFSET ?;
                    """
                    params = [domain, domain, category, category, cat_prefix] + clean_tags + [limit, offset]

                async with conn.execute(sql, params) as cur:
                    rows = await cur.fetchall()

                return [AgentManifest.model_validate_json(r["manifest_json"]) for r in rows]

        return await _run_write_with_retry(_do_search_agents, conn=conn)

    async def search_skills(
        self,
        query: Optional[str] = None,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
        *,
        offset: int = 0,
        tags: Optional[List[str]] = None,
    ) -> List[SkillManifest]:
        conn = await self._get_conn()
        sanitized = sanitize_fts_query(query) if query else ""
        cat_prefix = f"{category}.%" if category else None

        clean_tags = [t.lower().strip() for t in tags if t and t.strip()] if tags else []
        tag_clause = ""
        if clean_tags:
            placeholders = ", ".join("?" for _ in clean_tags)
            tag_clause = f"AND EXISTS (SELECT 1 FROM json_each(s.tags) WHERE LOWER(value) IN ({placeholders}))"

        async def _do_search_skills():
            async with self._lock:
                if sanitized:
                    sql = f"""
                    SELECT s.manifest_json, (bm25(fts.skills_fts) * -1.0) AS score
                    FROM skills_fts fts
                    JOIN skills s ON s.id = fts.id
                    WHERE fts.skills_fts MATCH ?
                      AND (? IS NULL OR LOWER(s.domain) = LOWER(?))
                      AND (? IS NULL OR LOWER(s.category) = LOWER(?) OR LOWER(s.category) LIKE LOWER(?))
                      {tag_clause}
                    ORDER BY score DESC
                    LIMIT ? OFFSET ?;
                    """
                    params = [sanitized, domain, domain, category, category, cat_prefix] + clean_tags + [limit, offset]
                else:
                    sql = f"""
                    SELECT s.manifest_json
                    FROM skills s
                    WHERE (? IS NULL OR LOWER(s.domain) = LOWER(?))
                      AND (? IS NULL OR LOWER(s.category) = LOWER(?) OR LOWER(s.category) LIKE LOWER(?))
                      {tag_clause}
                    ORDER BY s.name ASC
                    LIMIT ? OFFSET ?;
                    """
                    params = [domain, domain, category, category, cat_prefix] + clean_tags + [limit, offset]

                async with conn.execute(sql, params) as cur:
                    rows = await cur.fetchall()

                return [SkillManifest.model_validate_json(r["manifest_json"]) for r in rows]

        return await _run_write_with_retry(_do_search_skills, conn=conn)

    async def get_category_tree(
        self,
        domain: Optional[str] = None,
        include_hidden: bool = False,
    ) -> Dict[str, Any]:
        conn = await self._get_conn()
        hidden_clause = "1 = 1" if include_hidden else "hidden = 0"
        async with self._lock:
            sql = f"SELECT domain, category FROM agents WHERE {hidden_clause};"
            async with conn.execute(sql) as cur:
                rows = await cur.fetchall()
            row_dicts = [{"domain": r["domain"], "category": r["category"]} for r in rows]
            return build_category_tree_from_rows(row_dicts, domain_filter=domain)

    async def get_agent(self, agent_id: str) -> Optional[AgentManifest]:
        conn = await self._get_conn()
        async with self._lock:
            async with conn.execute("SELECT manifest_json FROM agents WHERE id = ?;", (agent_id,)) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                return AgentManifest.model_validate_json(row["manifest_json"])

    async def get_skill(self, skill_id: str) -> Optional[SkillManifest]:
        conn = await self._get_conn()
        async with self._lock:
            async with conn.execute("SELECT manifest_json FROM skills WHERE id = ?;", (skill_id,)) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                return SkillManifest.model_validate_json(row["manifest_json"])

    async def delete_agent(self, agent_id: str) -> bool:
        conn = await self._get_conn()

        async def _do_delete_agent():
            async with self._lock:
                cur = await conn.execute("DELETE FROM agents WHERE id = ?;", (agent_id,))
                await conn.execute("DELETE FROM agents_fts WHERE id = ?;", (agent_id,))
                await conn.commit()
                return cur.rowcount > 0

        return await _run_write_with_retry(_do_delete_agent, conn=conn)

    async def delete_skill(self, skill_id: str) -> bool:
        conn = await self._get_conn()

        async def _do_delete_skill():
            async with self._lock:
                cur = await conn.execute("DELETE FROM skills WHERE id = ?;", (skill_id,))
                await conn.execute("DELETE FROM skills_fts WHERE id = ?;", (skill_id,))
                await conn.commit()
                return cur.rowcount > 0

        return await _run_write_with_retry(_do_delete_skill, conn=conn)

    async def count_agents(self, include_hidden: bool = False) -> int:
        conn = await self._get_conn()
        hidden_clause = "1 = 1" if include_hidden else "hidden = 0"
        async with self._lock:
            async with conn.execute(f"SELECT COUNT(*) FROM agents WHERE {hidden_clause};") as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    async def count_skills(self) -> int:
        conn = await self._get_conn()
        async with self._lock:
            async with conn.execute("SELECT COUNT(*) FROM skills;") as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    async def __aenter__(self) -> SqliteCatalogAdapter:
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

