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

"""Atomic single-use password-reset token redemption for SqlAuthAdapter."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import weakref

from sqlalchemy import delete, select, update
from yarvelle_core.auth.adapters.sql_adapter import SqlAuthAdapter, _hash_token
from yarvelle_core.db.models import PasswordReset, Session, User

_reset_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)


def _get_reset_lock() -> asyncio.Lock:
    """Returns a per-event-loop lock so StaticPool sessions do not roll back each other."""
    loop = asyncio.get_running_loop()
    lock = _reset_locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _reset_locks[loop] = lock
    return lock


async def atomic_reset_password(
    self: SqlAuthAdapter,
    raw_token: str,
    new_password: str,
) -> bool:
    """Atomically consumes a single-use password reset token and updates the user's password.

    Uses a conditional ``UPDATE ... WHERE token_hash = :hash AND used_at IS NULL
    AND expires_at > :now`` and verifies ``rowcount == 1`` before updating the
    user's password hash and revoking active sessions, eliminating the TOCTOU
    race between concurrent redemption requests.
    """
    if not raw_token or not raw_token.strip():
        return False

    if len(new_password) < 10:
        raise ValueError("New password must be at least 10 characters long.")

    token_hash = _hash_token(raw_token)
    hashed_password = self._hasher.hash(new_password)
    session_factory = self._get_session_factory()

    async with _get_reset_lock():
        async with session_factory() as session:
            now = datetime.now(timezone.utc)
            claim_stmt = (
                update(PasswordReset)
                .where(
                    PasswordReset.token_hash == token_hash,
                    PasswordReset.used_at.is_(None),
                    PasswordReset.expires_at > now,
                )
                .values(used_at=now)
                .execution_options(synchronize_session=False)
            )
            claim_result = await session.execute(claim_stmt)
            if (claim_result.rowcount or 0) != 1:
                await session.rollback()
                return False

            user_id_stmt = select(PasswordReset.user_id).where(
                PasswordReset.token_hash == token_hash
            )
            user_id = (await session.scalars(user_id_stmt)).first()
            if user_id is None:
                await session.rollback()
                return False

            user_update_stmt = (
                update(User)
                .where(User.id == user_id)
                .values(hashed_password=hashed_password, updated_at=now)
                .execution_options(synchronize_session=False)
            )
            user_result = await session.execute(user_update_stmt)
            if (user_result.rowcount or 0) != 1:
                await session.rollback()
                return False

            await session.execute(delete(Session).where(Session.user_id == user_id))
            await session.commit()
            return True


def install_atomic_password_reset() -> None:
    """Installs atomic single-use password reset token redemption on SqlAuthAdapter."""
    SqlAuthAdapter.reset_password = atomic_reset_password  # type: ignore[method-assign]


__all__ = ["atomic_reset_password", "install_atomic_password_reset"]
