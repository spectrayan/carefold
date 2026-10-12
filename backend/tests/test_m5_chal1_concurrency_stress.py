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

"""Milestone 5 Challenger 1 Adversarial Concurrency & Atomic Leasing Stress Suite.

Empirical verification of:
1. Real SQLite file-based WAL mode multi-worker concurrency (zero double-leasing).
2. Expired lease reclamation under worker crash simulation.
3. Database locking under high contention (no unhandled OperationalError crashes).
4. Poison pill isolation: crashing jobs increment attempts and transition to 'failed' without crashing the runner loop.
5. Heartbeat lease extension and stolen lease rejection.
6. Universal choke point execution invariant (principal='job').
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Set
from unittest.mock import MagicMock
import uuid
import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from carefold.db.models import AuditEventRecord, Base, Job as DBJob, Profile, User
from carefold.engine.job_runner import (
    DEFAULT_LEASE_DURATION,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_POLL_INTERVAL,
    JobRunner,
)
from carefold.engine.tool_exec import ToolContext, execute_tool_call
from carefold.engine.tool_registry import ToolSpec
from carefold.schemas.tool import ToolResult


@pytest.fixture
async def real_sqlite_wal_session_factory(
    tmp_path: Path,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Real on-disk SQLite database file with WAL journal mode and busy_timeout."""
    db_file = tmp_path / "carefold_wal_stress.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_async_engine(
        db_url,
        poolclass=NullPool,
        connect_args={"check_same_thread": False, "timeout": 30.0},
        echo=False,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA busy_timeout = 10000;")
        cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Seed baseline user, system user, and profile
    async with session_factory() as session:
        u = User(
            id="user-stress-01",
            email="stress@carefold.local",
            username="stress_user",
            hashed_password="hashed-stress-pwd",
        )
        u_sys = User(
            id="system-job-runner",
            email="system-runner@carefold.local",
            username="system_job_runner",
            hashed_password="system-runner-pwd",
        )
        p = Profile(
            id="prof-stress-01",
            user_id="user-stress-01",
            name="Stress Test Profile",
            relationship="self",
        )
        session.add_all([u, u_sys, p])
        await session.commit()

    yield session_factory
    await engine.dispose()


@pytest.fixture
def stress_profile_id() -> str:
    return "prof-stress-01"


# ============================================================================
# Section 1: Real File SQLite WAL Multi-Worker Concurrency Stress
# ============================================================================


@pytest.mark.asyncio
async def test_wal_multi_worker_concurrency_zero_double_leasing(
    real_sqlite_wal_session_factory: async_sessionmaker[AsyncSession],
    stress_profile_id: str,
):
    """Stress 1.1: 10 concurrent workers competing for 50 due jobs in SQLite WAL mode.

    Asserts:
    1. Zero double-leasing: each job is acquired by exactly ONE worker.
    2. Zero lost jobs: all 50 jobs are leased across the workers.
    3. All jobs transition to status='active' with a valid lease_owner and unexpired lease_until.
    4. SQLite WAL handles concurrent writes without unhandled OperationalError.
    """
    now_dt = datetime.now(timezone.utc)
    num_jobs = 50
    num_workers = 10
    batch_size = 5

    # 1. Seed 50 pending jobs in real SQLite WAL database
    job_ids = [f"job-wal-stress-{i:03d}" for i in range(num_jobs)]
    async with real_sqlite_wal_session_factory() as session:
        jobs = [
            DBJob(
                id=jid,
                profile_id=stress_profile_id,
                kind="routine",
                next_run_at=now_dt - timedelta(seconds=100 - i),
                status="pending",
                payload=json.dumps({"index": i}),
            )
            for i, jid in enumerate(job_ids)
        ]
        session.add_all(jobs)
        await session.commit()

    # 2. Spawn 10 concurrent worker routines competing in parallel
    worker_leases: Dict[str, List[str]] = {f"worker-{w}": [] for w in range(num_workers)}

    async def _worker_loop(wid: str) -> None:
        runner = JobRunner(
            session_factory=real_sqlite_wal_session_factory,
            worker_id=wid,
            lease_duration=60.0,
            batch_size=batch_size,
        )
        # Attempt to lease in bursts until no more jobs are returned
        for _ in range(15):
            leased = await runner.lease_batch(worker_id=wid, now=now_dt, batch_size=batch_size)
            if not leased:
                await asyncio.sleep(0.01)
                continue
            for j in leased:
                worker_leases[wid].append(j.id)
            await asyncio.sleep(0.005)

    workers = [_worker_loop(f"worker-{w}") for w in range(num_workers)]
    await asyncio.gather(*workers)

    # 3. Assert zero double-leasing
    all_leased_ids: List[str] = []
    for wid, leased_list in worker_leases.items():
        all_leased_ids.extend(leased_list)

    assert len(all_leased_ids) == num_jobs, (
        f"Expected exactly {num_jobs} leased jobs, but got {len(all_leased_ids)}"
    )
    assert len(set(all_leased_ids)) == num_jobs, (
        f"Double-leasing detected! Unique jobs ({len(set(all_leased_ids))}) != total ({len(all_leased_ids)})"
    )
    assert set(all_leased_ids) == set(job_ids), "All seed jobs must be accounted for"

    # 4. Verify database state
    async with real_sqlite_wal_session_factory() as session:
        stmt = select(DBJob).where(DBJob.id.in_(job_ids))
        res = await session.execute(stmt)
        persisted_jobs = res.scalars().all()
        for pj in persisted_jobs:
            assert pj.status == "active"
            assert pj.lease_owner is not None
            assert pj.lease_owner.startswith("worker-")
            assert pj.lease_until > now_dt


@pytest.mark.asyncio
async def test_wal_extreme_contention_single_job_20_workers(
    real_sqlite_wal_session_factory: async_sessionmaker[AsyncSession],
    stress_profile_id: str,
):
    """Stress 1.2: 20 concurrent workers simultaneously competing for a single due job.

    Asserts:
    1. Exactly one worker acquires the job (len(winner) == 1).
    2. Nineteen workers receive empty batches.
    3. Zero unhandled OperationalError: database is locked exceptions.
    """
    now_dt = datetime.now(timezone.utc)
    target_job_id = "job-single-contention-01"

    async with real_sqlite_wal_session_factory() as session:
        job = DBJob(
            id=target_job_id,
            profile_id=stress_profile_id,
            kind="connector_sync",
            next_run_at=now_dt - timedelta(seconds=10),
            status="pending",
        )
        session.add(job)
        await session.commit()

    num_workers = 20

    async def _compete(wid: str) -> List[Any]:
        runner = JobRunner(
            session_factory=real_sqlite_wal_session_factory,
            worker_id=wid,
            lease_duration=30.0,
            batch_size=1,
        )
        return await runner.lease_batch(worker_id=wid, now=now_dt, batch_size=1)

    results = await asyncio.gather(*(_compete(f"contender-{i:02d}") for i in range(num_workers)))

    acquired = [b for b in results if len(b) > 0]
    empty = [b for b in results if len(b) == 0]

    assert len(acquired) == 1, f"Expected exactly 1 winner, but got {len(acquired)}"
    assert len(empty) == num_workers - 1, f"Expected {num_workers - 1} empty batches, got {len(empty)}"
    winner_job = acquired[0][0]
    assert winner_job.id == target_job_id
    assert winner_job.lease_owner.startswith("contender-")


def _run_thread_worker(db_path: str, worker_id: str, results_dict: Dict[str, List[str]]) -> None:
    """Helper running on an independent OS thread with its own asyncio loop and SQLite connection."""
    async def _thread_async_work():
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            poolclass=NullPool,
            connect_args={"check_same_thread": False, "timeout": 30.0},
        )

        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA busy_timeout = 10000;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
            cursor.close()

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        runner = JobRunner(
            session_factory=session_factory,
            worker_id=worker_id,
            lease_duration=30.0,
            batch_size=3,
        )
        now_dt = datetime.now(timezone.utc)
        leased_ids = []
        for _ in range(12):
            leased = await runner.lease_batch(worker_id=worker_id, now=now_dt, batch_size=3)
            for j in leased:
                leased_ids.append(j.id)
            await asyncio.sleep(0.01)

        await engine.dispose()
        results_dict[worker_id] = leased_ids

    asyncio.run(_thread_async_work())


def test_wal_multithreaded_worker_concurrency(tmp_path: Path):
    """Stress 1.3: 6 concurrent OS threads competing for 30 jobs on a real SQLite WAL file.

    Tests true OS-level thread concurrency and database lock handling.
    Asserts:
    1. Zero double-leasing across distinct OS threads.
    2. Zero unhandled sqlite3.OperationalError locks.
    3. Exactly 30 unique jobs leased across all threads.
    """
    import concurrent.futures

    db_file = tmp_path / "carefold_wal_threads.db"
    db_path = str(db_file)

    # Initialize schema synchronously
    init_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        poolclass=NullPool,
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )

    @event.listens_for(init_engine.sync_engine, "connect")
    def set_init_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA busy_timeout = 10000;")
        cursor.close()

    async def _init_db():
        async with init_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        s_fact = async_sessionmaker(init_engine, expire_on_commit=False)
        async with s_fact() as session:
            u = User(id="user-th-01", email="th@local", username="th_user", hashed_password="pw")
            p = Profile(id="prof-th-01", user_id="user-th-01", name="Thread Profile", relationship="self")
            session.add_all([u, p])
            now_dt = datetime.now(timezone.utc)
            jobs = [
                DBJob(
                    id=f"job-thread-{i:02d}",
                    profile_id="prof-th-01",
                    kind="routine",
                    status="pending",
                    next_run_at=now_dt - timedelta(seconds=50 - i),
                )
                for i in range(30)
            ]
            session.add_all(jobs)
            await session.commit()
        await init_engine.dispose()

    asyncio.run(_init_db())

    num_threads = 6
    thread_results: Dict[str, List[str]] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [
            executor.submit(_run_thread_worker, db_path, f"thread-worker-{t}", thread_results)
            for t in range(num_threads)
        ]
        for f in concurrent.futures.as_completed(futures):
            f.result()  # will raise if thread worker threw unhandled exception

    all_thread_leased: List[str] = []
    for wid, leased_list in thread_results.items():
        all_thread_leased.extend(leased_list)

    assert len(all_thread_leased) == 30, (
        f"Expected exactly 30 leased jobs across threads, got {len(all_thread_leased)}"
    )
    assert len(set(all_thread_leased)) == 30, (
        f"Double-leasing detected across threads! Unique={len(set(all_thread_leased))}, total={len(all_thread_leased)}"
    )


@pytest.mark.asyncio
async def test_wal_expired_lease_clean_reclamation(
    real_sqlite_wal_session_factory: async_sessionmaker[AsyncSession],
    stress_profile_id: str,
):
    """Stress 1.3: Dead-worker orphaned job reclamation.

    Simulates a worker dying abruptly without heartbeating or finishing.
    Asserts:
    1. Active unexpired lease cannot be stolen.
    2. Once lease expires (time advances past lease_until), a live worker cleanly reclaims it.
    3. Status remains 'active' with new lease_owner and refreshed lease_until.
    """
    now_dt = datetime.now(timezone.utc)
    crashed_worker_id = "worker-crashed-dead-pid-9999"
    reclaiming_worker_id = "worker-live-rescuer-pid-1111"
    job_id = "job-orphaned-lease-01"

    # Insert job with lease that expired 60 seconds ago
    async with real_sqlite_wal_session_factory() as session:
        job = DBJob(
            id=job_id,
            profile_id=stress_profile_id,
            kind="routine",
            status="active",
            lease_owner=crashed_worker_id,
            lease_until=now_dt - timedelta(seconds=60),
            next_run_at=now_dt - timedelta(seconds=200),
        )
        session.add(job)
        await session.commit()

    runner = JobRunner(
        session_factory=real_sqlite_wal_session_factory,
        worker_id=reclaiming_worker_id,
        lease_duration=45.0,
    )

    # Live worker leases
    leased = await runner.lease_batch(worker_id=reclaiming_worker_id, now=now_dt, batch_size=5)

    assert len(leased) == 1
    reclaimed_job = leased[0]
    assert reclaimed_job.id == job_id
    assert reclaimed_job.lease_owner == reclaiming_worker_id
    assert reclaimed_job.status == "active"
    assert reclaimed_job.lease_until > now_dt

    # Second worker cannot steal newly reclaimed active lease
    runner_thief = JobRunner(
        session_factory=real_sqlite_wal_session_factory,
        worker_id="worker-thief",
        lease_duration=45.0,
    )
    thief_leased = await runner_thief.lease_batch(worker_id="worker-thief", now=now_dt, batch_size=5)
    assert len(thief_leased) == 0, "Active unexpired lease must not be stolen"


@pytest.mark.asyncio
async def test_wal_heartbeat_lease_extension_and_stolen_detection(
    real_sqlite_wal_session_factory: async_sessionmaker[AsyncSession],
    stress_profile_id: str,
):
    """Stress 1.4: Heartbeat extends lease_until; stolen/expired lease returns False.

    Asserts:
    1. heartbeat() on owned active job extends lease_until into future.
    2. heartbeat() returns False if lease was reassigned or job completed.
    """
    now_dt = datetime.now(timezone.utc)
    job_id = "job-heartbeat-01"
    worker_id = "worker-heartbeat-master"

    async with real_sqlite_wal_session_factory() as session:
        job = DBJob(
            id=job_id,
            profile_id=stress_profile_id,
            kind="routine",
            status="active",
            lease_owner=worker_id,
            lease_until=now_dt + timedelta(seconds=10),
            next_run_at=now_dt - timedelta(seconds=10),
        )
        session.add(job)
        await session.commit()

    runner = JobRunner(
        session_factory=real_sqlite_wal_session_factory,
        worker_id=worker_id,
        lease_duration=60.0,
    )

    # 1. Successful heartbeat
    ok = await runner.heartbeat(job_id)
    assert ok is True

    async with real_sqlite_wal_session_factory() as session:
        persisted = (await session.execute(select(DBJob).where(DBJob.id == job_id))).scalar_one()
        assert persisted.lease_until > now_dt + timedelta(seconds=50)

    # 2. Another worker attempting heartbeat fails
    stranger_runner = JobRunner(
        session_factory=real_sqlite_wal_session_factory,
        worker_id="worker-stranger",
        lease_duration=60.0,
    )
    ok_stranger = await stranger_runner.heartbeat(job_id)
    assert ok_stranger is False, "Stranger worker must not extend unowned lease"

    # 3. If job status transitions to completed, heartbeat returns False
    async with real_sqlite_wal_session_factory() as session:
        await session.execute(
            text("UPDATE jobs SET status = 'completed' WHERE id = :id"),
            {"id": job_id},
        )
        await session.commit()

    ok_completed = await runner.heartbeat(job_id)
    assert ok_completed is False, "Completed job lease cannot be heartbeated"


# ============================================================================
# Section 2: Poison Pill Isolation & Runner Loop Resilience
# ============================================================================


@pytest.mark.asyncio
async def test_poison_pill_repeated_crashes_increment_attempts_to_failed(
    real_sqlite_wal_session_factory: async_sessionmaker[AsyncSession],
    stress_profile_id: str,
):
    """Stress 2.1: A job raising fatal exceptions repeatedly increments attempts and reaches 'failed'.

    Asserts:
    1. Fatal exception in tool execution does NOT escape unhandled.
    2. attempts increments 1 -> 2 -> 3.
    3. At attempts >= max_attempts, job status permanently becomes 'failed'.
    4. lease_owner and lease_until are cleared on failure.
    """
    now_dt = datetime.now(timezone.utc)
    job_id = "job-poison-pill-01"

    async with real_sqlite_wal_session_factory() as session:
        job = DBJob(
            id=job_id,
            profile_id=stress_profile_id,
            kind="routine",
            status="active",
            lease_owner="worker-poison-test",
            attempts=0,
            next_run_at=now_dt,
        )
        session.add(job)
        await session.commit()

    runner = JobRunner(
        session_factory=real_sqlite_wal_session_factory,
        worker_id="worker-poison-test",
        max_attempts=3,
    )

    poison_spec = ToolSpec(
        name="crashing_tool",
        risk_tier="write_local",
        executor=MagicMock(side_effect=RuntimeError("FATAL: Memory access violation / divide by zero")),
    )

    # Run 1: attempt 1 -> reschedules to pending with backoff
    res1 = await runner.execute_job(job, poison_spec)
    assert res1.success is False

    async with real_sqlite_wal_session_factory() as session:
        j1 = (await session.execute(select(DBJob).where(DBJob.id == job_id))).scalar_one()
        assert j1.attempts == 1
        assert j1.status == "pending"
        assert j1.lease_owner is None
        assert j1.lease_until is None

    # Run 2: attempt 2 -> reschedules to pending with backoff
    j1.lease_owner = runner.worker_id
    j1.status = "active"
    res2 = await runner.execute_job(j1, poison_spec)
    assert res2.success is False

    async with real_sqlite_wal_session_factory() as session:
        j2 = (await session.execute(select(DBJob).where(DBJob.id == job_id))).scalar_one()
        assert j2.attempts == 2
        assert j2.status == "pending"
        assert j2.lease_owner is None

    # Run 3: attempt 3 (reaches max_attempts) -> terminal status 'failed'
    j2.lease_owner = runner.worker_id
    j2.status = "active"
    res3 = await runner.execute_job(j2, poison_spec)
    assert res3.success is False

    async with real_sqlite_wal_session_factory() as session:
        j3 = (await session.execute(select(DBJob).where(DBJob.id == job_id))).scalar_one()
        assert j3.attempts == 3
        assert j3.status == "failed", f"Expected terminal status 'failed', got {j3.status}"
        assert j3.lease_owner is None
        assert j3.lease_until is None


@pytest.mark.asyncio
async def test_poison_pill_does_not_crash_runner_loop(
    real_sqlite_wal_session_factory: async_sessionmaker[AsyncSession],
    stress_profile_id: str,
):
    """Stress 2.2: Unhandled exception in leased job processing does not kill the runner background loop.

    Asserts:
    1. When _process_leased_job raises an uncaught RuntimeError / ZeroDivisionError, runner catches it.
    2. runner.is_running remains True.
    3. Other concurrent jobs continue processing and completing.
    """
    now_dt = datetime.now(timezone.utc)
    poison_id = "job-loop-poison-01"
    healthy_id = "job-loop-healthy-01"

    async with real_sqlite_wal_session_factory() as session:
        j_poison = DBJob(
            id=poison_id,
            profile_id=stress_profile_id,
            kind="routine",
            status="pending",
            next_run_at=now_dt - timedelta(seconds=10),
            payload=json.dumps({"should_crash": True}),
        )
        j_healthy = DBJob(
            id=healthy_id,
            profile_id=stress_profile_id,
            kind="routine",
            status="pending",
            next_run_at=now_dt - timedelta(seconds=10),
            payload=json.dumps({"should_crash": False}),
        )
        session.add_all([j_poison, j_healthy])
        await session.commit()

    processed_healthy: List[str] = []
    crashed_poison: List[str] = []

    class PoisonResilientRunner(JobRunner):
        async def _process_leased_job(self, job: Any) -> None:
            payload = json.loads(getattr(job, "payload", "{}"))
            if payload.get("should_crash"):
                crashed_poison.append(job.id)
                raise RuntimeError("POISON PILL EXPLODED IN WORKER PROCESSOR!")
            processed_healthy.append(job.id)
            # Mark healthy as completed
            if self.session_factory:
                async with self.session_factory() as s:
                    stmt = text("UPDATE jobs SET status='completed', lease_owner=NULL, lease_until=NULL WHERE id=:id")
                    await s.execute(stmt, {"id": job.id})
                    await s.commit()

    runner = PoisonResilientRunner(
        session_factory=real_sqlite_wal_session_factory,
        poll_interval=0.05,
        lease_duration=10.0,
        worker_id="worker-poison-resilience",
    )

    task = await runner.start()
    assert runner.is_running is True

    # Allow polling loop to tick multiple times
    await asyncio.sleep(0.3)

    # Assert runner loop is STILL running despite poison pill exception
    assert runner.is_running is True
    assert not task.done()
    assert len(crashed_poison) >= 1
    assert healthy_id in processed_healthy

    # Stop runner cleanly
    await runner.stop(timeout=2.0)
    assert runner.is_running is False


# ============================================================================
# Section 3: High Contention & DB Locking Resilience
# ============================================================================


@pytest.mark.asyncio
async def test_wal_heavy_contention_concurrent_updates_no_operational_error(
    real_sqlite_wal_session_factory: async_sessionmaker[AsyncSession],
    stress_profile_id: str,
):
    """Stress 3.1: 15 workers performing 100 rapid concurrent lease + heartbeat + commit cycles.

    Simulates peak load spikes on real SQLite file in WAL mode.
    Asserts:
    1. Zero unhandled sqlite3.OperationalError: database is locked exceptions.
    2. Consistent database state at conclusion of load spike.
    """
    now_dt = datetime.now(timezone.utc)
    num_jobs = 30
    num_workers = 15

    # Seed 30 jobs
    job_ids = [f"job-spike-{i:03d}" for i in range(num_jobs)]
    async with real_sqlite_wal_session_factory() as session:
        jobs = [
            DBJob(
                id=jid,
                profile_id=stress_profile_id,
                kind="connector_sync",
                status="pending",
                next_run_at=now_dt - timedelta(seconds=i),
            )
            for i, jid in enumerate(job_ids)
        ]
        session.add_all(jobs)
        await session.commit()

    errors: List[Exception] = []

    async def _worker_spike(wid: str) -> None:
        runner = JobRunner(
            session_factory=real_sqlite_wal_session_factory,
            worker_id=wid,
            lease_duration=15.0,
            batch_size=2,
        )
        try:
            for _ in range(10):
                leased = await runner.lease_batch(worker_id=wid, now=now_dt, batch_size=2)
                for j in leased:
                    # Immediately heartbeat
                    await runner.heartbeat(j.id)
                await asyncio.sleep(0.002)
        except Exception as exc:
            errors.append(exc)

    spike_workers = [_worker_spike(f"spiker-{w}") for w in range(num_workers)]
    await asyncio.gather(*spike_workers)

    assert len(errors) == 0, f"Spike contention resulted in unhandled errors: {errors}"

    # Verify no corrupted jobs exist
    async with real_sqlite_wal_session_factory() as session:
        res = await session.execute(select(DBJob).where(DBJob.id.in_(job_ids)))
        persisted = res.scalars().all()
        for pj in persisted:
            assert pj.status in ("pending", "active", "completed")


# ============================================================================
# Section 4: Choke Point Execution Invariant (principal='job')
# ============================================================================


@pytest.mark.asyncio
async def test_job_execution_audit_logs_principal_job(
    real_sqlite_wal_session_factory: async_sessionmaker[AsyncSession],
    stress_profile_id: str,
):
    """Stress 4.1: Background job execution records AuditEventRecord with principal='job' in database.

    Asserts:
    1. ToolContext.principal is 'job'.
    2. AuditEventRecord persisted in DB has principal == 'job'.
    """
    now_dt = datetime.now(timezone.utc)
    job_id = "job-audit-principal-01"

    async with real_sqlite_wal_session_factory() as session:
        job = DBJob(
            id=job_id,
            profile_id=stress_profile_id,
            kind="routine",
            status="active",
            lease_owner="worker-audit-01",
            next_run_at=now_dt,
            payload=json.dumps({"input_num": 42}),
        )
        session.add(job)
        await session.commit()

    runner = JobRunner(
        session_factory=real_sqlite_wal_session_factory,
        worker_id="worker-audit-01",
    )

    spec = ToolSpec(
        name="stress_audit_tool",
        risk_tier="write_local",
        executor=lambda args: {"output_num": args.get("input_num", 0) * 2},
    )

    res = await runner.execute_job(job, spec)
    assert res.success is True
    assert res.output == {"output_num": 84}

    # Verify AuditEventRecord in database
    async with real_sqlite_wal_session_factory() as session:
        stmt = (
            select(AuditEventRecord)
            .where(AuditEventRecord.profile_id == stress_profile_id)
            .order_by(AuditEventRecord.ts.desc())
        )
        res_audit = await session.execute(stmt)
        record = res_audit.scalar_one_or_none()
        assert record is not None, "AuditEventRecord must be persisted in database"
        assert record.principal == "job", (
            f"Expected AuditEventRecord.principal to be 'job', got '{record.principal}'"
        )
        assert record.tool == "stress_audit_tool"
        assert record.decision == "allow"
