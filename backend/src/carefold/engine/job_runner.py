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

"""Wall-Clock Job Runner with Atomic Leasing, Sleep/Wake Coalescing, and Universal Choke Point Routing (AU-21, R8)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from carefold.db.models import Job as DBJob
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
        """Processes a leased job; placeholder hook for routine/sync dispatch."""
        pass

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
                await session.commit()
                missed_count += len(rows)

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
                else:
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
            else:
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
            return res

        # Handle Failure (Retry with Exponential Backoff or Terminal Failure)
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

        return res


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
]
