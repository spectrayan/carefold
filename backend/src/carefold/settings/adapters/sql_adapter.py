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

"""SQL-backed implementation of SettingsPort with in-memory caching and secret masking."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from carefold.db.models import SystemSetting
from carefold.db.session import get_session_factory
from carefold.settings.ports import SECRET_MASK, SettingsPort

logger = logging.getLogger(__name__)


class SqlSettingsAdapter(SettingsPort):
    """Hexagonal SQL adapter implementing SettingsPort via SQLAlchemy 2.0 Async."""

    def __init__(
        self,
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
    ) -> None:
        self._session_factory = session_factory
        self._cache: Dict[str, Any] = {}
        self._cache_is_secret: Dict[str, bool] = {}
        self._lock = asyncio.Lock()

    def _get_session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is not None:
            return self._session_factory
        return get_session_factory()

    def invalidate_cache(self, key: Optional[str] = None) -> None:
        """Evicts cache entries to force fresh database reads."""
        if key is None:
            self._cache.clear()
            self._cache_is_secret.clear()
        else:
            self._cache.pop(key, None)
            self._cache_is_secret.pop(key, None)

    async def get_setting(self, key: str, default: Optional[Any] = None) -> Any:
        if not key:
            return default

        async with self._lock:
            if key in self._cache:
                return self._cache[key]

        session_factory = self._get_session_factory()
        async with session_factory() as session:
            stmt = select(SystemSetting).where(SystemSetting.key == key)
            setting = (await session.scalars(stmt)).first()

            if setting is None:
                return default

            try:
                val = setting.get_value()
            except Exception as err:
                logger.warning("settings_deserialization_failed", key=key, error=str(err))
                return default

            async with self._lock:
                self._cache[key] = val
                self._cache_is_secret[key] = setting.is_secret

            return val

    async def set_setting(
        self,
        key: str,
        value: Any,
        is_secret: bool = False,
        updated_by: Optional[str] = None,
    ) -> None:
        if not key or not key.strip():
            raise ValueError("Setting key cannot be empty.")

        clean_key = key.strip()
        serialized = json.dumps(value)
        now = datetime.now(timezone.utc)

        session_factory = self._get_session_factory()
        async with session_factory() as session:
            stmt = select(SystemSetting).where(SystemSetting.key == clean_key)
            existing = (await session.scalars(stmt)).first()

            if existing is not None:
                existing.value_json = serialized
                existing.is_secret = is_secret
                existing.updated_at = now
                existing.updated_by = updated_by
            else:
                new_setting = SystemSetting(
                    key=clean_key,
                    value_json=serialized,
                    is_secret=is_secret,
                    updated_at=now,
                    updated_by=updated_by,
                )
                session.add(new_setting)

            await session.commit()

        async with self._lock:
            self._cache[clean_key] = value
            self._cache_is_secret[clean_key] = is_secret

    async def get_all_settings(
        self,
        mask_secrets: bool = True,
        include_secrets: Optional[bool] = None,
    ) -> Dict[str, Any]:
        if include_secrets is not None:
            mask_secrets = not include_secrets

        session_factory = self._get_session_factory()
        async with session_factory() as session:
            stmt = select(SystemSetting).order_by(SystemSetting.key.asc())
            rows = (await session.scalars(stmt)).all()

            results: Dict[str, Any] = {}
            async with self._lock:
                for row in rows:
                    try:
                        val = row.get_value()
                    except Exception:
                        val = None

                    self._cache[row.key] = val
                    self._cache_is_secret[row.key] = row.is_secret

                    if mask_secrets and row.is_secret:
                        results[row.key] = SECRET_MASK
                    else:
                        results[row.key] = val

            return results

    async def delete_setting(self, key: str) -> bool:
        if not key:
            return False

        clean_key = key.strip()
        session_factory = self._get_session_factory()
        async with session_factory() as session:
            stmt = delete(SystemSetting).where(SystemSetting.key == clean_key)
            result = await session.execute(stmt)
            await session.commit()
            deleted = bool(result.rowcount and result.rowcount > 0)

        async with self._lock:
            self._cache.pop(clean_key, None)
            self._cache_is_secret.pop(clean_key, None)

        return deleted
