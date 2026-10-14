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

"""Wall-Clock Job Runner with Atomic Leasing, Sleep/Wake Coalescing, and Universal Choke Point Routing (AU-21, R8)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple, Union
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from carefold.config import settings
from carefold.db.models import Attachment, Job as DBJob, Note
from carefold.engine.tool_exec import ToolContext, ToolSpec, execute_tool_call
from carefold.schemas.tool import ToolResult

logger = logging.getLogger("carefold.engine.job_runner")

DEFAULT_POLL_INTERVAL: float = 30.0
DEFAULT_LEASE_DURATION: float = 60.0
DEFAULT_BATCH_SIZE: int = 10
DEFAULT_MAX_ATTEMPTS: int = 3
REMINDER_OVERDUE_THRESHOLD_SECONDS: float = 86400.0  # 24 hours
CLOCK_JUMP_THRESHOLD_SECONDS: float = 120.0


class AwaitableTuple(tuple):
    """Subclass of tuple that implements __await__ for dual sync/async compatibility."""

    def __await__(self):
        async def _async_self():
            return self

        return _async_self().__await__()


def _to_timestamp(val: Any) -> Optional[float]:
    """Converts a datetime or numeric timestamp into UTC epoch seconds."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.timestamp()
    return None


def _to_datetime(val: Any) -> Optional[datetime]:
    """Converts a numeric timestamp or datetime into timezone-aware UTC datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(float(val), tz=timezone.utc)
    return None


def calculate_next_occurrence(
    rrule_str: Optional[str],
    now: Union[float, datetime],
    tz_name: str = "UTC",
    base_time: Optional[Union[float, datetime]] = None,
) -> Optional[datetime]:
    """Calculates the next recurrence occurrence strictly after `now` without external dateutil dependency.

    Guarantees next occurrence > now to prevent backlog bursts upon sleep/wake.
    Supports RFC 5545 tokens: FREQ (MINUTELY, HOURLY, DAILY, WEEKLY), INTERVAL, UNTIL.
    """
    if not rrule_str or not str(rrule_str).strip():
        return None

    now_dt = _to_datetime(now) or datetime.now(timezone.utc)
    base_dt = _to_datetime(base_time) if base_time else now_dt

    rule = str(rrule_str).strip()
    parts: Dict[str, str] = {}
    if ";" in rule or "=" in rule:
        for segment in rule.split(";"):
            if "=" in segment:
                k, v = segment.split("=", 1)
                parts[k.strip().upper()] = v.strip()
    elif rule.isdigit():
        parts["INTERVAL_SECONDS"] = rule

    freq = parts.get("FREQ", "").upper()
    try:
        interval = int(parts.get("INTERVAL", 1))
    except ValueError:
        interval = 1

    if "INTERVAL_SECONDS" in parts:
        delta = timedelta(seconds=int(parts["INTERVAL_SECONDS"]))
    elif freq == "MINUTELY":
        delta = timedelta(minutes=interval)
    elif freq == "HOURLY":
        delta = timedelta(hours=interval)
    elif freq == "DAILY":
        delta = timedelta(days=interval)
    elif freq == "WEEKLY":
        delta = timedelta(weeks=interval)
    else:
        delta = timedelta(hours=interval)

    candidate = base_dt + delta
    while candidate <= now_dt:
        candidate += delta

    if "UNTIL" in parts:
        until_val = parts["UNTIL"]
        try:
            if until_val.endswith("Z"):
                until_dt = datetime.fromisoformat(until_val[:-1]).replace(tzinfo=timezone.utc)
            else:
                until_dt = datetime.fromisoformat(until_val)
                if until_dt.tzinfo is None:
                    until_dt = until_dt.replace(tzinfo=timezone.utc)
            if candidate > until_dt:
                return None
        except Exception:
            pass

    return candidate


class JobRunner:
    """Production wall-clock job runner with atomic leasing, sleep/wake coalescing, and universal choke point execution (AU-21)."""

    def __init__(
        self,
        session_factory: Optional[Any] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        lease_duration: float = DEFAULT_LEASE_DURATION,
        batch_size: int = DEFAULT_BATCH_SIZE,
        worker_id: Optional[str] = None,
        jump_threshold: float = CLOCK_JUMP_THRESHOLD_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self.session_factory = session_factory
        self.poll_interval = float(poll_interval)
        self.lease_duration = float(lease_duration)
        self.batch_size = int(batch_size)
        self.worker_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.jump_threshold = float(jump_threshold)
        self.max_attempts = int(max_attempts)

        self._is_running: bool = False
        self._task: Optional[asyncio.Task[None]] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._last_tick: float = time.time()

        # In-memory store for contract testing and backwards compatibility
        self._jobs: Dict[str, Any] = {}
        self._in_memory_lock: asyncio.Lock = asyncio.Lock()

        # Handler registry mapping job.kind -> async handler coroutine
        self._handlers: Dict[str, Callable[[Any], Coroutine[Any, Any, None]]] = {}
        self.register_handler("extract_text", self._default_extract_text_handler)
        self.register_handler("index_doc", self._default_index_doc_handler)
        self.register_handler("delete_doc", self._default_delete_doc_handler)
        self.register_handler("reminder", self._default_reminder_handler)
        self.register_handler("sync", self._default_sync_handler)
        self.register_handler("routine", self._default_routine_handler)

    def register_handler(self, kind: str, handler: Callable[..., Any]) -> None:
        """Registers an asynchronous handler function for a specific job kind.

        Args:
            kind: The job kind identifier (e.g. 'extract_text', 'index_doc', 'delete_doc').
            handler: An async callable accepting the leased Job object and returning a coroutine.
        """
        if not kind or not str(kind).strip():
            raise ValueError("Job kind cannot be empty")
        if not callable(handler):
            raise ValueError(f"Handler for kind '{kind}' must be callable")
        self._handlers[kind.strip()] = handler
        logger.info("job_handler_registered: kind=%s worker=%s", kind.strip(), self.worker_id)

    def unregister_handler(self, kind: str) -> bool:
        """Unregisters the handler for a specific job kind. Returns True if removed."""
        removed = self._handlers.pop(kind, None) is not None
        if removed:
            logger.info("job_handler_unregistered: kind=%s worker=%s", kind, self.worker_id)
        return removed

    def has_handler(self, kind: str) -> bool:
        """Returns True if a handler is registered for the specified job kind."""
        return kind in self._handlers

    def get_handler(self, kind: str) -> Optional[Callable[..., Any]]:
        """Returns the registered handler for the specified job kind, if any."""
        return self._handlers.get(kind)

    async def _default_extract_text_handler(self, job: Any) -> None:
        """Default extract_text handler bound to JobRunner instance."""
        await handle_extract_text_job(job=job, session_factory=self.session_factory)

    async def _default_index_doc_handler(self, job: Any) -> None:
        """Default index_doc handler bound to JobRunner instance."""
        await handle_index_doc_job(job=job, session_factory=self.session_factory)

    async def _default_delete_doc_handler(self, job: Any) -> None:
        """Default delete_doc handler bound to JobRunner instance."""
        await handle_delete_doc_job(job=job, session_factory=self.session_factory)

    async def _default_reminder_handler(self, job: Any) -> None:
        """Default reminder handler bound to JobRunner instance."""
        from carefold.clinical.reminders import handle_reminder_job
        await handle_reminder_job(job=job, session_factory=self.session_factory)

    async def _default_sync_handler(self, job: Any) -> None:
        """Default connector sync handler bound to JobRunner instance (AU-52)."""
        connection_id = getattr(job, "connection_id", None)
        if not connection_id and hasattr(job, "payload"):
            try:
                payload = json.loads(job.payload) if isinstance(job.payload, str) else (job.payload or {})
                connection_id = payload.get("connection_id")
            except Exception:
                connection_id = None
        if not connection_id or self.session_factory is None:
            return
        from carefold.connectors.sync import run_connection_sync
        async with self.session_factory() as session:
            await run_connection_sync(session=session, connection_id=str(connection_id))

    async def _default_routine_handler(self, job: Any) -> None:
        """Default A2 standing routine handler bound to JobRunner instance (AU-58 / E1.10)."""
        routine_id = getattr(job, "routine_id", None)
        if not routine_id and hasattr(job, "payload"):
            try:
                payload = json.loads(job.payload) if isinstance(job.payload, str) else (job.payload or {})
                routine_id = payload.get("routine_id")
            except Exception:
                routine_id = None
        if not routine_id or self.session_factory is None:
            return
        from carefold.clinical.routines import execute_standing_routine
        async with self.session_factory() as session:
            await execute_standing_routine(session=session, routine_id=str(routine_id))

    @property
    def is_running(self) -> bool:
        """Returns True if the background polling loop is actively running."""
        return self._is_running and self._task is not None and not self._task.done()

    def add_job(self, job: Any) -> None:
        """Registers a job in the in-memory store for contract tests."""
        self._jobs[job.id] = job

    async def start(self) -> asyncio.Task[None]:
        """Starts the wall-clock polling loop."""
        if self._is_running and self._task is not None and not self._task.done():
            return self._task

        self._is_running = True
        self._stop_event = asyncio.Event()
        self._last_tick = time.time()
        self._task = asyncio.create_task(self._run_loop(), name="job_runner")
        return self._task

    async def stop(self, timeout: float = 10.0) -> None:
        """Gracefully halts the background polling loop with bounded timeout."""
        if not self._is_running and (self._task is None or self._task.done()):
            return

        self._is_running = False
        if self._stop_event is not None:
            self._stop_event.set()

        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=timeout)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

    async def _run_loop(self) -> None:
        """Main polling loop with clock jump detection and non-blocking cancellation."""
        logger.info("job_runner_started: worker=%s interval=%s", self.worker_id, self.poll_interval)
        try:
            while self._is_running and not (self._stop_event and self._stop_event.is_set()):
                t0 = time.time()
                try:
                    await self.tick()
                except Exception as exc:
                    logger.error("job_runner_tick_failed: %s", exc, exc_info=True)

                elapsed = time.time() - t0
                sleep_time = max(0.01, self.poll_interval - elapsed)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_time)
                    break
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            logger.info("job_runner_loop_cancelled: worker=%s", self.worker_id)
            raise
        finally:
            self._is_running = False
            logger.info("job_runner_stopped: worker=%s", self.worker_id)

    async def tick(self) -> None:
        """Single wall-clock evaluation tick."""
        now = time.time()
        elapsed = now - self._last_tick

        # 1. Sleep/wake clock jump detection
        if elapsed > self.jump_threshold:
            logger.warning(
                "sleep_wake_clock_jump_detected: last_tick=%s now=%s jump=%s",
                self._last_tick,
                now,
                elapsed,
            )
            res = self.handle_wake_jump(self._last_tick, now)
            if asyncio.iscoroutine(res):
                await res
        elif elapsed < -10.0:
            logger.warning(
                "clock_skew_backwards_detected: last_tick=%s now=%s skew=%s",
                self._last_tick,
                now,
                elapsed,
            )

        self._last_tick = now

        # 2. Sweep overdue reminders > 24 hours
        await self._sweep_overdue_reminders(now)

        # 3. Atomically lease and process due jobs
        leased = await self.lease_batch(
            worker_id=self.worker_id,
            now=now,
            batch_size=self.batch_size,
            lease_duration=self.lease_duration,
        )
        for job in leased:
            try:
                await self._process_leased_job(job)
            except Exception as exc:
                logger.error("job_execution_failed: job=%s error=%s", getattr(job, "id", None), exc)

    async def _process_leased_job(self, job: Any) -> None:
        """Dispatches a leased job to its registered kind handler with heartbeat and retry backoff."""
        job_id = getattr(job, "id", None)
        kind = getattr(job, "kind", None)
        now_dt = datetime.now(timezone.utc)

        if not kind or kind not in self._handlers:
            logger.debug("no_handler_registered_for_job: kind=%s job_id=%s", kind, job_id)
            await self._release_lease(job, now_dt)
            return

        handler = self._handlers[kind]
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(job_id))
        handler_failed = False
        error_exc: Optional[Exception] = None

        try:
            await handler(job)
        except Exception as exc:
            handler_failed = True
            error_exc = exc
            logger.error(
                "job_handler_execution_failed: kind=%s job_id=%s error=%s",
                kind,
                job_id,
                exc,
                exc_info=True,
            )
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        if not handler_failed:
            await self._mark_job_completed(job, now_dt)
        else:
            await self._handle_job_failure(job, now_dt, error_exc)

    async def _mark_job_completed(self, job: Any, now_dt: datetime) -> None:
        """Marks a job completed or reschedules it if it has an RFC 5545 rrule recurrence."""
        job_id = getattr(job, "id", str(uuid.uuid4()))
        rrule = getattr(job, "rrule", None)

        if rrule:
            next_run = calculate_next_occurrence(rrule, now_dt, getattr(job, "timezone", "UTC"))
            if next_run:
                next_run_val = next_run if isinstance(getattr(job, "next_run_at", None), datetime) else next_run.timestamp()
                setattr(job, "status", "pending")
                setattr(job, "next_run_at", next_run_val)
                setattr(job, "attempts", 0)
                setattr(job, "lease_owner", None)
                setattr(job, "lease_until", None)

                if self.session_factory is not None:
                    async with self.session_factory() as session:
                        stmt = text("""
                            UPDATE jobs
                            SET status = 'pending',
                                next_run_at = :next_run,
                                attempts = 0,
                                lease_owner = NULL,
                                lease_until = NULL,
                                updated_at = :now
                            WHERE id = :id;
                        """)
                        await session.execute(stmt, {"id": job_id, "next_run": next_run, "now": now_dt})
                        await session.commit()
                return

        # Terminal completion for one-off jobs or exhausted recurrences
        setattr(job, "status", "completed")
        setattr(job, "lease_owner", None)
        setattr(job, "lease_until", None)

        if self.session_factory is not None:
            async with self.session_factory() as session:
                stmt = text("""
                    UPDATE jobs
                    SET status = 'completed',
                        lease_owner = NULL,
                        lease_until = NULL,
                        updated_at = :now
                    WHERE id = :id;
                """)
                await session.execute(stmt, {"id": job_id, "now": now_dt})
                await session.commit()

    async def _handle_job_failure(
        self,
        job: Any,
        now_dt: datetime,
        exc: Optional[Exception] = None,
    ) -> None:
        """Handles job failure: increments attempts, applies exponential backoff, or marks failed."""
        job_id = getattr(job, "id", str(uuid.uuid4()))
        attempts = getattr(job, "attempts", 0) + 1
        setattr(job, "attempts", attempts)

        if attempts < self.max_attempts:
            backoff_sec = min(3600.0, 30.0 * (2 ** (attempts - 1)))
            retry_dt = now_dt + timedelta(seconds=backoff_sec)
            retry_val = retry_dt if isinstance(getattr(job, "next_run_at", None), datetime) else retry_dt.timestamp()

            setattr(job, "status", "pending")
            setattr(job, "next_run_at", retry_val)
            setattr(job, "lease_owner", None)
            setattr(job, "lease_until", None)

            if self.session_factory is not None:
                async with self.session_factory() as session:
                    stmt = text("""
                        UPDATE jobs
                        SET status = 'pending',
                            next_run_at = :next_run,
                            attempts = :attempts,
                            lease_owner = NULL,
                            lease_until = NULL,
                            updated_at = :now
                        WHERE id = :id;
                    """)
                    await session.execute(
                        stmt,
                        {"id": job_id, "next_run": retry_dt, "attempts": attempts, "now": now_dt},
                    )
                    await session.commit()
            logger.info(
                "job_rescheduled_with_backoff: job_id=%s attempts=%d/%d next_run_at=%s backoff_sec=%.1f",
                job_id,
                attempts,
                self.max_attempts,
                retry_dt.isoformat(),
                backoff_sec,
            )
        else:
            setattr(job, "status", "failed")
            setattr(job, "lease_owner", None)
            setattr(job, "lease_until", None)

            if self.session_factory is not None:
                async with self.session_factory() as session:
                    stmt = text("""
                        UPDATE jobs
                        SET status = 'failed',
                            attempts = :attempts,
                            lease_owner = NULL,
                            lease_until = NULL,
                            updated_at = :now
                        WHERE id = :id;
                    """)
                    await session.execute(stmt, {"id": job_id, "attempts": attempts, "now": now_dt})
                    await session.commit()
            logger.error(
                "job_permanently_failed_max_attempts_exceeded: job_id=%s attempts=%d/%d",
                job_id,
                attempts,
                self.max_attempts,
            )

    async def _release_lease(self, job: Any, now_dt: datetime) -> None:
        """Releases the lease lock without changing job status or attempts."""
        job_id = getattr(job, "id", None)
        if not job_id:
            return
        setattr(job, "lease_owner", None)
        setattr(job, "lease_until", None)

        if self.session_factory is not None:
            async with self.session_factory() as session:
                stmt = text("""
                    UPDATE jobs
                    SET lease_owner = NULL,
                        lease_until = NULL,
                        updated_at = :now
                    WHERE id = :id AND lease_owner = :worker_id;
                """)
                await session.execute(stmt, {"id": job_id, "worker_id": self.worker_id, "now": now_dt})
                await session.commit()

    async def _sweep_overdue_reminders(self, now: float) -> int:
        """Sweeps and marks reminders overdue by >24 hours as 'missed'."""
        cutoff_dt = datetime.fromtimestamp(now - REMINDER_OVERDUE_THRESHOLD_SECONDS, tz=timezone.utc)
        now_dt = datetime.fromtimestamp(now, tz=timezone.utc)

        missed_count = 0

        # In-memory sweep
        for job in list(self._jobs.values()):
            if getattr(job, "kind", "") == "reminder" and getattr(job, "status", "") == "pending":
                next_ts = _to_timestamp(getattr(job, "next_run_at", None))
                if next_ts is not None and (now - next_ts) > REMINDER_OVERDUE_THRESHOLD_SECONDS:
                    setattr(job, "status", "missed")
                    setattr(job, "lease_owner", None)
                    setattr(job, "lease_until", None)
                    missed_count += 1

        # Database sweep
        if self.session_factory is not None:
            async with self.session_factory() as session:
                stmt = text("""
                    UPDATE jobs
                    SET status = 'missed',
                        lease_owner = NULL,
                        lease_until = NULL,
                        updated_at = :now
                    WHERE kind = 'reminder'
                      AND status = 'pending'
                      AND next_run_at <= :cutoff
                    RETURNING id;
                """)
                res = await session.execute(stmt, {"now": now_dt, "cutoff": cutoff_dt})
                rows = res.fetchall()
                missed_count += len(rows)

                # Sync reminders table
                stmt_rem = text("""
                    UPDATE reminders
                    SET status = 'missed',
                        updated_at = :now
                    WHERE status IN ('pending', 'snoozed')
                      AND (
                        (status = 'pending' AND next_due_at <= :cutoff)
                        OR
                        (status = 'snoozed' AND COALESCE(snooze_until, next_due_at) <= :cutoff)
                      );
                """)
                await session.execute(stmt_rem, {"now": now_dt, "cutoff": cutoff_dt})
                await session.commit()

        return missed_count

    def handle_wake_jump(self, last_tick: float, now: float) -> Any:
        """Detects clock jump on laptop wake (>120s diff), coalesces connector syncs, and tags missed reminders.

        Supports both synchronous in-memory calls and asynchronous database calls.
        Returns an AwaitableTuple((coalesced_count, missed_count)) for dual sync/async compatibility.
        """
        jump = now - last_tick
        coalesced_count = 0
        missed_count = 0

        if jump > self.jump_threshold:
            # 1. In-memory processing
            active_syncs_by_conn: Set[str] = set()
            for job in list(self._jobs.values()):
                kind = getattr(job, "kind", "")
                status = getattr(job, "status", "")
                next_ts = _to_timestamp(getattr(job, "next_run_at", None))

                # Reminders overdue by >24 hours
                if kind == "reminder" and status == "pending":
                    if next_ts is not None and (now - next_ts) > REMINDER_OVERDUE_THRESHOLD_SECONDS:
                        setattr(job, "status", "missed")
                        setattr(job, "lease_owner", None)
                        setattr(job, "lease_until", None)
                        missed_count += 1

                # Connector sync coalescing: max 1 active/pending sync per connection
                elif kind == "connector_sync" and status in ("pending", "active"):
                    cid = getattr(job, "connection_id", "")
                    if cid in active_syncs_by_conn:
                        setattr(job, "status", "completed")
                        setattr(job, "coalesced", True)
                        setattr(job, "lease_owner", None)
                        setattr(job, "lease_until", None)
                        coalesced_count += 1
                    else:
                        active_syncs_by_conn.add(cid)

            # 2. Database processing
            if self.session_factory is not None:
                return self._handle_wake_jump_db(last_tick, now)

        self._last_tick = now
        return AwaitableTuple((coalesced_count, missed_count))

    async def _handle_wake_jump_db(self, last_tick: float, now: float) -> Tuple[int, int]:
        """Database implementation of sleep/wake jump handling."""
        now_dt = datetime.fromtimestamp(now, tz=timezone.utc)
        cutoff_dt = now_dt - timedelta(seconds=REMINDER_OVERDUE_THRESHOLD_SECONDS)
        coalesced_count = 0
        missed_count = 0

        async with self.session_factory() as session:
            # Rule 1: Reminders overdue by >24 hours marked missed
            stmt_missed = text("""
                UPDATE jobs
                SET status = 'missed',
                    lease_owner = NULL,
                    lease_until = NULL,
                    updated_at = :now
                WHERE kind = 'reminder'
                  AND status = 'pending'
                  AND next_run_at <= :cutoff
                RETURNING id;
            """)
            res_m = await session.execute(stmt_missed, {"now": now_dt, "cutoff": cutoff_dt})
            missed_count = len(res_m.fetchall())

            # Sync reminders table
            stmt_rem_wake = text("""
                UPDATE reminders
                SET status = 'missed',
                    updated_at = :now
                WHERE status IN ('pending', 'snoozed')
                  AND (
                    (status = 'pending' AND next_due_at <= :cutoff)
                    OR
                    (status = 'snoozed' AND COALESCE(snooze_until, next_due_at) <= :cutoff)
                  );
            """)
            await session.execute(stmt_rem_wake, {"now": now_dt, "cutoff": cutoff_dt})

            # Rule 2: Coalesce duplicate connector syncs
            stmt_syncs = text("""
                SELECT id, connection_id
                FROM jobs
                WHERE kind = 'connector_sync'
                  AND status IN ('pending', 'active')
                ORDER BY next_run_at DESC;
            """)
            res_s = await session.execute(stmt_syncs)
            rows = res_s.fetchall()
            seen_conn: Set[str] = set()
            coalesce_ids = []
            for jid, cid in rows:
                if cid in seen_conn:
                    coalesce_ids.append(jid)
                else:
                    seen_conn.add(cid)

            if coalesce_ids:
                stmt_coal = text("""
                    UPDATE jobs
                    SET status = 'completed',
                        lease_owner = NULL,
                        lease_until = NULL,
                        updated_at = :now
                    WHERE id = :id;
                """)
                for cid_job in coalesce_ids:
                    await session.execute(stmt_coal, {"id": cid_job, "now": now_dt})
                coalesced_count = len(coalesce_ids)

            await session.commit()

        self._last_tick = now
        return coalesced_count, missed_count

    def lease_batch_sync(
        self,
        worker_id: Optional[str] = None,
        now: Optional[Union[float, datetime]] = None,
        batch_size: Optional[int] = None,
        lease_duration: Optional[float] = None,
    ) -> List[Any]:
        """Synchronous in-memory lease_batch for contract test compatibility."""
        now_ts = _to_timestamp(now) if now is not None else time.time()
        lease_dur = lease_duration if lease_duration is not None else self.lease_duration
        batch_sz = batch_size if batch_size is not None else self.batch_size
        w_id = worker_id or self.worker_id

        leased: List[Any] = []
        for job in list(self._jobs.values()):
            if len(leased) >= batch_sz:
                break
            status = getattr(job, "status", "")
            if status not in ("pending", "active"):
                continue

            next_ts = _to_timestamp(getattr(job, "next_run_at", None))
            if next_ts is None or next_ts > now_ts:
                continue

            # Exclude reminders overdue by > 24 hours
            if getattr(job, "kind", "") == "reminder" and (now_ts - next_ts) > REMINDER_OVERDUE_THRESHOLD_SECONDS:
                continue

            lease_until_ts = _to_timestamp(getattr(job, "lease_until", None))
            if lease_until_ts is not None and lease_until_ts > now_ts:
                continue

            # Acquire lease
            new_lease_until = now_ts + lease_dur
            if isinstance(getattr(job, "next_run_at", None), datetime):
                new_lease_until_val = datetime.fromtimestamp(new_lease_until, tz=timezone.utc)
            else:
                new_lease_until_val = new_lease_until

            setattr(job, "lease_owner", w_id)
            setattr(job, "lease_until", new_lease_until_val)
            setattr(job, "status", "active")
            if hasattr(job, "updated_at"):
                setattr(job, "updated_at", datetime.fromtimestamp(now_ts, tz=timezone.utc))
            leased.append(job)

        return leased

    async def lease_batch(
        self,
        worker_id: Optional[str] = None,
        now: Optional[Union[float, datetime]] = None,
        batch_size: Optional[int] = None,
        lease_duration: Optional[float] = None,
    ) -> List[Any]:
        """Atomically leases a batch of due jobs using dialect-specific atomic SQL or synchronized in-memory access."""
        now_ts = _to_timestamp(now) if now is not None else time.time()
        now_dt = _to_datetime(now) or datetime.fromtimestamp(now_ts, tz=timezone.utc)
        lease_dur = lease_duration if lease_duration is not None else self.lease_duration
        batch_sz = batch_size if batch_size is not None else self.batch_size
        w_id = worker_id or self.worker_id

        if batch_sz <= 0:
            return []

        # 1. In-memory path
        if self.session_factory is None:
            async with self._in_memory_lock:
                return self.lease_batch_sync(
                    worker_id=w_id,
                    now=now_ts,
                    batch_size=batch_sz,
                    lease_duration=lease_dur,
                )

        # 2. Database path (SQLite / PostgreSQL atomic leasing)
        lease_until_dt = now_dt + timedelta(seconds=lease_dur)
        cutoff_dt = now_dt - timedelta(seconds=REMINDER_OVERDUE_THRESHOLD_SECONDS)

        async with self.session_factory() as session:
            bind = getattr(session, "bind", None) or getattr(session.sync_session, "bind", None)
            dialect_name = bind.dialect.name if bind is not None else "sqlite"

            if dialect_name == "postgresql":
                sql = text("""
                    WITH candidate AS (
                        SELECT id
                        FROM jobs
                        WHERE next_run_at <= :now
                          AND status IN ('pending', 'active')
                          AND (lease_until IS NULL OR lease_until <= :now)
                          AND NOT (kind = 'reminder' AND next_run_at <= :cutoff_24h)
                        ORDER BY next_run_at ASC
                        LIMIT :batch_size
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE jobs
                    SET lease_owner = :worker_id,
                        lease_until = :lease_until,
                        status = 'active',
                        updated_at = :now
                    FROM candidate
                    WHERE jobs.id = candidate.id
                    RETURNING jobs.id;
                """)
            else:  # sqlite and others
                sql = text("""
                    UPDATE jobs
                    SET lease_owner = :worker_id,
                        lease_until = :lease_until,
                        status = 'active',
                        updated_at = :now
                    WHERE id IN (
                        SELECT id
                        FROM jobs
                        WHERE next_run_at <= :now
                          AND status IN ('pending', 'active')
                          AND (lease_until IS NULL OR lease_until <= :now)
                          AND NOT (kind = 'reminder' AND next_run_at <= :cutoff_24h)
                        ORDER BY next_run_at ASC
                        LIMIT :batch_size
                    )
                    AND next_run_at <= :now
                    AND status IN ('pending', 'active')
                    AND (lease_until IS NULL OR lease_until <= :now)
                    AND NOT (kind = 'reminder' AND next_run_at <= :cutoff_24h)
                    RETURNING id;
                """)

            res = await session.execute(
                sql,
                {
                    "worker_id": w_id,
                    "lease_until": lease_until_dt,
                    "now": now_dt,
                    "cutoff_24h": cutoff_dt,
                    "batch_size": batch_sz,
                },
            )
            leased_ids = [row[0] for row in res.fetchall()]
            await session.commit()

            if not leased_ids:
                return []

            stmt = select(DBJob).where(DBJob.id.in_(leased_ids))
            result = await session.execute(stmt)
            job_map = {j.id: j for j in result.scalars().all()}
            return [job_map[jid] for jid in leased_ids if jid in job_map]

    async def heartbeat(self, job_id: str) -> bool:
        """Extends the lease for an active long-running job. Returns False if lease was stolen/lost."""
        now_dt = datetime.now(timezone.utc)
        new_lease_until_dt = now_dt + timedelta(seconds=self.lease_duration)

        # In-memory heartbeat
        if self.session_factory is None:
            job = self._jobs.get(job_id)
            if job and getattr(job, "lease_owner", None) == self.worker_id:
                if isinstance(getattr(job, "lease_until", None), datetime):
                    setattr(job, "lease_until", new_lease_until_dt)
                else:
                    setattr(job, "lease_until", new_lease_until_dt.timestamp())
                return True
            return False

        # Database heartbeat
        async with self.session_factory() as session:
            sql = text("""
                UPDATE jobs
                SET lease_until = :new_lease_until,
                    updated_at = :now
                WHERE id = :job_id
                  AND lease_owner = :worker_id
                  AND status IN ('active', 'running')
                RETURNING id;
            """)
            res = await session.execute(
                sql,
                {
                    "job_id": job_id,
                    "worker_id": self.worker_id,
                    "new_lease_until": new_lease_until_dt,
                    "now": now_dt,
                },
            )
            row = res.fetchone()
            await session.commit()
            return row is not None

    async def _heartbeat_loop(self, job_id: str) -> None:
        """Background coroutine that extends lease_until every lease_duration / 3.0."""
        interval = max(0.1, self.lease_duration / 3.0)
        try:
            while True:
                await asyncio.sleep(interval)
                alive = await self.heartbeat(job_id)
                if not alive:
                    logger.warning("Heartbeat extension failed for job %s; aborting heartbeat loop", job_id)
                    break
        except asyncio.CancelledError:
            pass

    async def execute_job(
        self,
        job: Any,
        spec: Any,
        approval_store: Optional[Any] = None,
    ) -> ToolResult:
        """Routes background job execution strictly through the execute_tool_call choke point with principal='job'."""
        if not isinstance(spec, ToolSpec):
            spec = ToolSpec(
                name=getattr(spec, "name", "tool"),
                description=getattr(spec, "description", ""),
                parameters=getattr(spec, "parameters", {}),
                risk_tier=getattr(spec, "risk_tier", "read"),
                trust=getattr(spec, "trust", "trusted"),
                data_flows=getattr(spec, "data_flows", ()),
                executor=getattr(spec, "executor", None),
                metadata=getattr(spec, "metadata", {}),
            )

        profile_id = getattr(job, "profile_id", "prof-default")
        job_id = getattr(job, "id", str(uuid.uuid4()))
        payload = getattr(job, "payload", {})

        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        elif hasattr(job, "payload_dict"):
            payload = job.payload_dict

        ctx = ToolContext(
            user_id="system-job-runner",
            profile_id=profile_id,
            principal="job",
            run_id=f"job-run-{job_id}",
            autonomy="A2",
            extra={"session_factory": self.session_factory} if self.session_factory else {},
        )

        # Launch lease heartbeat for the duration of execution
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(job_id))
        try:
            res = await execute_tool_call(ctx, spec, payload, approval_store=approval_store)
        finally:
            heartbeat_task.cancel()

        now_dt = datetime.now(timezone.utc)
        now_ts = now_dt.timestamp()

        # Handle Policy Decision Halts (Human Approval Required or Security/Policy Blocks)
        is_security_violation = bool(
            res.error
            and any(
                err_type in str(res.error)
                for err_type in ("EgressBlockedError", "PolicyBlocked", "Security violation")
            )
        )
        if getattr(res, "needs_approval", False) or is_security_violation:
            setattr(job, "status", "failed")
            setattr(job, "lease_owner", None)
            setattr(job, "lease_until", None)
            if self.session_factory is not None:
                async with self.session_factory() as session:
                    stmt = text("""
                        UPDATE jobs
                        SET status = 'failed',
                            lease_owner = NULL,
                            lease_until = NULL,
                            updated_at = :now
                        WHERE id = :id;
                    """)
                    await session.execute(stmt, {"id": job_id, "now": now_dt})
                    await session.commit()
            return res

        # Handle Success
        if res.success:
            await self._mark_job_completed(job, now_dt)
            return res

        # Handle Failure (Retry with Exponential Backoff or Terminal Failure)
        await self._handle_job_failure(job, now_dt, exc=Exception(res.error) if res.error else None)
        return res



async def handle_extract_text_job(
    job: Any,
    session_factory: Optional[Any] = None,
    carefold_home: Optional[Path] = None,
) -> None:
    """Executes the extract_text lifecycle:
    1. Parse payload.
    2. Transition Attachment status to 'extracting'.
    3. Read CAS file and extract text.
    4. Transition Attachment status to 'completed' with extracted_text (or 'failed').
    5. On completion, enqueue downstream 'index_doc' job.
    """
    home_dir = carefold_home or settings.home_dir

    payload = getattr(job, "payload", {})
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    elif hasattr(job, "payload_dict"):
        payload = job.payload_dict

    attachment_id = payload.get("attachment_id")
    if not attachment_id:
        raise ValueError(f"Job {getattr(job, 'id', None)} missing 'attachment_id' in payload")

    sf = session_factory
    if sf is None and hasattr(job, "_session_factory"):
        sf = job._session_factory
    if sf is None:
        try:
            from carefold.db.session import get_session_factory
            sf = get_session_factory()
        except Exception:
            sf = None

    user_id = payload.get("user_id")
    profile_id = payload.get("profile_id") or getattr(job, "profile_id", None)
    sha256_hash = payload.get("sha256")
    filename = payload.get("filename")
    content_type = payload.get("content_type")

    # Step 1: Transition status to 'extracting'
    if sf is not None:
        async with sf() as session:
            stmt = select(Attachment).where(Attachment.id == attachment_id)
            res = await session.execute(stmt)
            attachment = res.scalar_one_or_none()
            if attachment is None:
                raise ValueError(f"Attachment '{attachment_id}' not found in database")

            attachment.extraction_status = "extracting"
            attachment.updated_at = datetime.now(timezone.utc)
            await session.commit()

            user_id = user_id or attachment.user_id
            profile_id = profile_id or attachment.profile_id
            sha256_hash = sha256_hash or attachment.sha256_hash
            filename = filename or attachment.filename
            content_type = content_type or attachment.content_type

    # Step 2: Read CAS file and extract text
    extraction_success = False
    extracted_text = ""
    error_msg = None

    try:
        from carefold.storage.cas import read_cas_file
        from carefold.storage.extract import extract_document_text

        if not sha256_hash:
            raise ValueError(f"Attachment '{attachment_id}' has no sha256_hash")

        content = read_cas_file(
            carefold_home=home_dir,
            user_id=user_id,
            profile_id=profile_id,
            sha256_hash=sha256_hash,
        )

        result = extract_document_text(
            content=content,
            filename=filename or "attachment",
            mime_type=content_type,
        )

        extracted_text = result.text
        if result.status == "completed" or (result.status == "empty" and "error" not in result.metadata):
            extraction_success = True
        else:
            extraction_success = False
            error_msg = result.metadata.get("error", "Extraction failed")
    except Exception as exc:
        logger.error(
            "extract_text_processing_failed: attachment_id=%s error=%s",
            attachment_id,
            exc,
            exc_info=True,
        )
        extraction_success = False
        error_msg = str(exc)

    # Step 3: Update Attachment and enqueue index_doc job
    if sf is not None:
        async with sf() as session:
            stmt = select(Attachment).where(Attachment.id == attachment_id)
            res = await session.execute(stmt)
            attachment = res.scalar_one_or_none()
            if attachment is not None:
                if extraction_success:
                    attachment.extracted_text = extracted_text
                    attachment.extraction_status = "completed"
                    attachment.updated_at = datetime.now(timezone.utc)

                    # Enqueue index_doc job
                    index_payload = {
                        "document_id": attachment.id,
                        "profile_id": attachment.profile_id,
                        "user_id": attachment.user_id,
                        "doc_type": "attachment",
                        "filename": attachment.filename,
                        "sha256": attachment.sha256_hash,
                        "source": attachment.source or "upload",
                    }
                    idempotency_key = f"index:attachment:{attachment.id}:{attachment.sha256_hash}"

                    check_stmt = select(DBJob.id).where(
                        DBJob.idempotency_key == idempotency_key,
                        DBJob.status.in_(["pending", "active", "completed"]),
                    )
                    check_res = await session.execute(check_stmt)
                    if check_res.scalar_one_or_none() is None:
                        index_job = DBJob(
                            id=str(uuid.uuid4()),
                            profile_id=attachment.profile_id or "prof-default",
                            kind="index_doc",
                            payload=json.dumps(index_payload),
                            timezone="UTC",
                            next_run_at=datetime.now(timezone.utc),
                            idempotency_key=idempotency_key,
                            status="pending",
                        )
                        session.add(index_job)
                        logger.info(
                            "index_doc_job_enqueued: doc_id=%s profile_id=%s job_id=%s",
                            attachment.id,
                            attachment.profile_id,
                            index_job.id,
                        )
                else:
                    attachment.extraction_status = "failed"
                    attachment.updated_at = datetime.now(timezone.utc)

                await session.commit()

    if not extraction_success:
        raise RuntimeError(f"Text extraction failed for attachment {attachment_id}: {error_msg}")


def create_extract_text_handler(
    session_factory: Optional[Any] = None,
    carefold_home: Optional[Path] = None,
) -> Callable[[Any], Coroutine[Any, Any, None]]:
    """Factory creating an extract_text job handler with injected dependencies."""
    async def extract_text_job_handler(job: Any) -> None:
        await handle_extract_text_job(
            job=job,
            session_factory=session_factory,
            carefold_home=carefold_home,
        )
    return extract_text_job_handler


async def handle_index_doc_job(
    job: Any,
    session_factory: Optional[Any] = None,
) -> None:
    """Executes the index_doc lifecycle:
    1. Parse payload: document_id, profile_id, doc_type.
    2. Load note or attachment from DB/CAS (if text not in payload).
    3. Call get_search_index().index_document(...) with extracted/authored text and metadata.
    """
    if isinstance(job, dict):
        payload = job
    else:
        payload = getattr(job, "payload", {})
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        elif hasattr(job, "payload_dict"):
            payload = job.payload_dict

    document_id = payload.get("document_id")
    if not document_id:
        raise ValueError(f"Job missing 'document_id' in payload")

    profile_id = payload.get("profile_id") or getattr(job, "profile_id", None)
    if not profile_id or not str(profile_id).strip():
        raise ValueError(f"Job missing 'profile_id'")
    clean_profile_id = str(profile_id).strip()

    doc_type = payload.get("doc_type")
    user_id = payload.get("user_id")

    sf = session_factory
    if sf is None and hasattr(job, "_session_factory"):
        sf = job._session_factory
    if sf is None:
        try:
            from carefold.db.session import get_session_factory
            sf = get_session_factory()
        except Exception:
            sf = None

    text_to_index: Optional[str] = payload.get("text")
    metadata: Dict[str, Any] = dict(payload.get("metadata") or {})

    if text_to_index is None and sf is not None:
        async with sf() as session:
            # 1. Try loading as Note if doc_type is 'note' or unspecified
            if doc_type in ("note", None):
                n_stmt = select(Note).where(Note.id == document_id)
                n_res = await session.execute(n_stmt)
                note = n_res.scalar_one_or_none()
                if note is not None:
                    doc_type = "note"
                    clean_profile_id = str(note.profile_id or clean_profile_id).strip()
                    user_id = user_id or note.user_id
                    title_prefix = f"# {note.title}\n\n" if note.title else ""
                    text_to_index = f"{title_prefix}{note.content or ''}"
                    metadata.update({
                        "title": note.title or "",
                        "slug": note.slug or "",
                        "type": note.type or "scratchpad",
                        "source": "clinical_note",
                        "doc_type": "note",
                        "created_at": note.created_at.isoformat() if hasattr(note.created_at, "isoformat") else str(note.created_at),
                        "updated_at": note.updated_at.isoformat() if hasattr(note.updated_at, "isoformat") else str(note.updated_at),
                    })

            # 2. Try loading as Attachment if doc_type is 'attachment' or unspecified
            if text_to_index is None and doc_type in ("attachment", None):
                a_stmt = select(Attachment).where(Attachment.id == document_id)
                a_res = await session.execute(a_stmt)
                att = a_res.scalar_one_or_none()
                if att is not None:
                    doc_type = "attachment"
                    clean_profile_id = str(att.profile_id or clean_profile_id).strip()
                    user_id = user_id or att.user_id
                    metadata.update({
                        "filename": att.filename or att.original_name or "attachment",
                        "sha256": att.sha256_hash or "",
                        "source": att.source or "upload",
                        "doc_type": "attachment",
                        "content_type": att.content_type or "",
                        "created_at": att.created_at.isoformat() if hasattr(att.created_at, "isoformat") else str(att.created_at),
                    })
                    if att.extracted_text and att.extracted_text.strip():
                        text_to_index = att.extracted_text
                    elif att.sha256_hash:
                        try:
                            from carefold.storage.cas import read_cas_file
                            from carefold.storage.extract import extract_document_text
                            raw_content = read_cas_file(
                                carefold_home=settings.home_dir,
                                user_id=att.user_id,
                                profile_id=att.profile_id,
                                sha256_hash=att.sha256_hash,
                            )
                            ext_res = extract_document_text(
                                content=raw_content,
                                filename=att.filename or "attachment",
                                mime_type=att.content_type,
                            )
                            text_to_index = ext_res.text
                        except Exception as cas_err:
                            logger.debug("cas_read_fallback_failed: %s", cas_err)
                            text_to_index = ""

    if text_to_index is None or not text_to_index.strip():
        logger.info(
            "index_doc_skipped_no_content: doc_id=%s profile_id=%s doc_type=%s",
            document_id,
            clean_profile_id,
            doc_type,
        )
        return

    from carefold.search.factory import get_search_index
    search_index = get_search_index()
    await search_index.index_document(
        document_id=document_id,
        text=text_to_index,
        metadata=metadata,
        profile_id=clean_profile_id,
        user_id=user_id,
    )
    logger.info(
        "index_doc_completed: doc_id=%s profile_id=%s doc_type=%s",
        document_id,
        clean_profile_id,
        doc_type,
    )


async def handle_delete_doc_job(
    job: Any,
    session_factory: Optional[Any] = None,
) -> None:
    """Executes the delete_doc lifecycle:
    1. Parse payload: document_id, profile_id.
    2. Call get_search_index().delete_document(document_id, profile_id).
    """
    if isinstance(job, dict):
        payload = job
    else:
        payload = getattr(job, "payload", {})
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        elif hasattr(job, "payload_dict"):
            payload = job.payload_dict

    document_id = payload.get("document_id")
    if not document_id:
        raise ValueError(f"Job missing 'document_id' in payload")

    profile_id = payload.get("profile_id") or getattr(job, "profile_id", None)
    if not profile_id or not str(profile_id).strip():
        raise ValueError(f"Job missing 'profile_id'")
    clean_profile_id = str(profile_id).strip()

    from carefold.search.factory import get_search_index
    search_index = get_search_index()
    deleted = await search_index.delete_document(
        document_id=document_id,
        profile_id=clean_profile_id,
    )
    logger.info(
        "delete_doc_completed: doc_id=%s profile_id=%s deleted=%s",
        document_id,
        clean_profile_id,
        deleted,
    )


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_LEASE_DURATION",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_POLL_INTERVAL",
    "REMINDER_OVERDUE_THRESHOLD_SECONDS",
    "CLOCK_JUMP_THRESHOLD_SECONDS",
    "AwaitableTuple",
    "JobRunner",
    "calculate_next_occurrence",
    "extract_text_handler",
    "handle_extract_text_job",
    "create_extract_text_handler",
    "handle_index_doc_job",
    "handle_delete_doc_job",
]
