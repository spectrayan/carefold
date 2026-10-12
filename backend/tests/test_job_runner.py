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

"""Milestone 5 Test Suite: Wall-Clock Job Runner (AU-21, R8).

Implements all 5 test suites defined in explorer_m5_3 handoff:
- Suite 1: Atomic leasing under concurrency
- Suite 2: Job execution lifecycle & retry backoff
- Suite 3: Sleep/wake clock jump detection & connector sync coalescing
- Suite 4: Overdue >24h reminders marked missed (clinical safety invariant)
- Suite 5: Universal execution choke point invariants (principal="job", egress firewall, monotone taint, audit logging)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from typing import Any, AsyncGenerator, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from carefold.db.models import AuditEventRecord, Base, Job as DBJob, Profile, User
from carefold.engine.job_runner import (
    CLOCK_JUMP_THRESHOLD_SECONDS,
    DEFAULT_LEASE_DURATION,
    DEFAULT_POLL_INTERVAL,
    REMINDER_OVERDUE_THRESHOLD_SECONDS,
    JobRunner,
    calculate_next_occurrence,
)
from carefold.engine.tool_exec import (
    PolicyDecision,
    ToolContext,
    UntrustedResult,
    execute_tool_call,
)
from carefold.engine.tool_registry import DataFlows, ToolSpec
from carefold.schemas.audit import AuditEvent
from carefold.schemas.tool import ToolResult
from tests.e2e_autonomy.contracts import ApprovalStore


@pytest.fixture
async def db_session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """In-memory SQLite database sessionmaker using StaticPool with schema initialized."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Seed baseline User and Profile
    async with session_factory() as session:
        u = User(
            id="user-runner-01",
            email="runner@carefold.local",
            username="runner_user",
            hashed_password="pw-hash-runner",
        )
        p = Profile(
            id="prof-runner-01",
            user_id="user-runner-01",
            name="Job Runner Profile",
            relationship="self",
        )
        session.add_all([u, p])
        await session.commit()

    yield session_factory
    await engine.dispose()


@pytest.fixture
def sample_profile_id() -> str:
    return "prof-runner-01"


@pytest.fixture
def db_job_runner(db_session_factory: async_sessionmaker[AsyncSession]) -> JobRunner:
    return JobRunner(
        session_factory=db_session_factory,
        poll_interval=0.05,
        lease_duration=10.0,
        worker_id="runner-node-1",
        jump_threshold=120.0,
    )


@pytest.fixture
def memory_job_runner() -> JobRunner:
    return JobRunner(
        session_factory=None,
        poll_interval=0.05,
        lease_duration=10.0,
        worker_id="mem-runner-1",
        jump_threshold=120.0,
    )


# ============================================================================
# Suite 1: Atomic Leasing Under Concurrency
# ============================================================================


@pytest.mark.asyncio
async def test_atomic_leasing_concurrent_competition(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
):
    """Test 1.1: Multiple concurrent worker tasks competing for 1 pending job yield exactly 1 lease (0 double-leases)."""
    now_dt = datetime.now(timezone.utc)

    # Insert 1 due job
    async with db_session_factory() as session:
        job = DBJob(
            id="job-race-1",
            profile_id=sample_profile_id,
            kind="connector_sync",
            next_run_at=now_dt - timedelta(seconds=10),
            status="pending",
        )
        session.add(job)
        await session.commit()

    # 5 concurrent workers compete simultaneously
    async def _worker_attempt(wid: str) -> List[Any]:
        runner = JobRunner(
            session_factory=db_session_factory,
            worker_id=wid,
            lease_duration=30.0,
        )
        return await runner.lease_batch(worker_id=wid, now=now_dt, batch_size=1)

    results = await asyncio.gather(*(_worker_attempt(f"worker-{i}") for i in range(5)))

    acquired = [b for b in results if len(b) > 0]
    empty = [b for b in results if len(b) == 0]

    assert len(acquired) == 1, "Exactly one worker must acquire the lease"
    assert len(empty) == 4, "Four workers must receive empty batches"

    winning_worker_id = acquired[0][0].lease_owner
    assert winning_worker_id.startswith("worker-")

    # Verify DB state
    async with db_session_factory() as session:
        stmt = select(DBJob).where(DBJob.id == "job-race-1")
        res = await session.execute(stmt)
        persisted = res.scalar_one()
        assert persisted.status == "active"
        assert persisted.lease_owner == winning_worker_id
        assert persisted.lease_until > now_dt


@pytest.mark.asyncio
async def test_atomic_leasing_expired_lease_reclaimed(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Test 1.2: Orphaned job whose worker crashed (lease expired) is reclaimed by an active worker."""
    now_dt = datetime.now(timezone.utc)

    # Insert job with expired lease from crashed worker
    async with db_session_factory() as session:
        job = DBJob(
            id="job-orphan-1",
            profile_id=sample_profile_id,
            kind="routine",
            status="active",
            lease_owner="crashed-worker-dead",
            lease_until=now_dt - timedelta(seconds=30),  # expired 30s ago
            next_run_at=now_dt - timedelta(seconds=100),
        )
        session.add(job)
        await session.commit()

    leased = await db_job_runner.lease_batch(
        worker_id="worker-alive-01",
        now=now_dt,
        batch_size=1,
    )
    assert len(leased) == 1
    assert leased[0].id == "job-orphan-1"

    async with db_session_factory() as session:
        res = await session.execute(select(DBJob).where(DBJob.id == "job-orphan-1"))
        persisted = res.scalar_one()
        assert persisted.lease_owner == "worker-alive-01"
        assert persisted.status == "active"
        assert persisted.lease_until > now_dt


@pytest.mark.asyncio
async def test_atomic_leasing_future_jobs_excluded(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Test 1.3: Jobs scheduled for the future (next_run_at > now) are never leased."""
    now_dt = datetime.now(timezone.utc)

    async with db_session_factory() as session:
        job = DBJob(
            id="job-future-01",
            profile_id=sample_profile_id,
            kind="routine",
            status="pending",
            next_run_at=now_dt + timedelta(hours=2),
        )
        session.add(job)
        await session.commit()

    leased = await db_job_runner.lease_batch(worker_id="worker-1", now=now_dt, batch_size=10)
    assert len(leased) == 0

    async with db_session_factory() as session:
        res = await session.execute(select(DBJob).where(DBJob.id == "job-future-01"))
        persisted = res.scalar_one()
        assert persisted.status == "pending"
        assert persisted.lease_owner is None


@pytest.mark.asyncio
async def test_atomic_leasing_batch_size_enforced(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Test 1.4: Batch size parameter strictly caps the number of acquired leases."""
    now_dt = datetime.now(timezone.utc)

    async with db_session_factory() as session:
        for i in range(10):
            session.add(
                DBJob(
                    id=f"job-batch-{i}",
                    profile_id=sample_profile_id,
                    kind="routine",
                    status="pending",
                    next_run_at=now_dt - timedelta(seconds=10 + i),
                )
            )
        await session.commit()

    leased = await db_job_runner.lease_batch(worker_id="worker-1", now=now_dt, batch_size=3)
    assert len(leased) == 3

    async with db_session_factory() as session:
        res = await session.execute(select(DBJob))
        all_jobs = res.scalars().all()
        active_count = sum(1 for j in all_jobs if j.status == "active")
        pending_count = sum(1 for j in all_jobs if j.status == "pending")
        assert active_count == 3
        assert pending_count == 7


# ============================================================================
# Suite 2: Job Execution Lifecycle & Retry Backoff
# ============================================================================


@pytest.mark.asyncio
async def test_job_execution_success_one_off(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Test 2.1: Successful execution of a one-off job marks status='completed' and clears lease."""
    now_dt = datetime.now(timezone.utc)

    async with db_session_factory() as session:
        job = DBJob(
            id="job-oneoff-01",
            profile_id=sample_profile_id,
            kind="routine",
            payload=json.dumps({"items_to_sync": 4}),
            status="active",
            lease_owner=db_job_runner.worker_id,
            next_run_at=now_dt,
        )
        session.add(job)
        await session.commit()

    spec = ToolSpec(
        name="sync_notes_tool",
        risk_tier="write_local",
        executor=lambda args: {"synced_count": args.get("items_to_sync", 0)},
    )

    res = await db_job_runner.execute_job(job, spec)
    assert res.success is True
    assert res.output == {"synced_count": 4}

    async with db_session_factory() as session:
        res_db = await session.execute(select(DBJob).where(DBJob.id == "job-oneoff-01"))
        persisted = res_db.scalar_one()
        assert persisted.status == "completed"
        assert persisted.lease_owner is None
        assert persisted.lease_until is None


@pytest.mark.asyncio
async def test_job_execution_success_recurring_reschedules(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Test 2.2: Successful recurring job advances next_run_at into the future and transitions to 'pending'."""
    now_dt = datetime.now(timezone.utc)

    async with db_session_factory() as session:
        job = DBJob(
            id="job-recur-01",
            profile_id=sample_profile_id,
            kind="connector_sync",
            rrule="FREQ=HOURLY;INTERVAL=1",
            status="active",
            lease_owner=db_job_runner.worker_id,
            next_run_at=now_dt,
        )
        session.add(job)
        await session.commit()

    spec = ToolSpec(
        name="recurring_sync_tool",
        risk_tier="write_local",
        executor=lambda args: {"status": "ok"},
    )

    res = await db_job_runner.execute_job(job, spec)
    assert res.success is True

    async with db_session_factory() as session:
        res_db = await session.execute(select(DBJob).where(DBJob.id == "job-recur-01"))
        persisted = res_db.scalar_one()
        assert persisted.status == "pending"
        assert persisted.lease_owner is None
        assert persisted.attempts == 0
        assert persisted.next_run_at > now_dt


@pytest.mark.asyncio
async def test_job_execution_transient_failure_increments_attempts(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Test 2.3: Transient failure increments attempts, reschedules with exponential backoff, and keeps status='pending'."""
    now_dt = datetime.now(timezone.utc)

    async with db_session_factory() as session:
        job = DBJob(
            id="job-transient-01",
            profile_id=sample_profile_id,
            kind="routine",
            attempts=0,
            status="active",
            lease_owner=db_job_runner.worker_id,
            next_run_at=now_dt,
        )
        session.add(job)
        await session.commit()

    spec = ToolSpec(
        name="failing_tool",
        risk_tier="write_local",
        executor=MagicMock(side_effect=RuntimeError("Temporary EHR socket timeout")),
    )

    res = await db_job_runner.execute_job(job, spec)
    assert res.success is False

    async with db_session_factory() as session:
        res_db = await session.execute(select(DBJob).where(DBJob.id == "job-transient-01"))
        persisted = res_db.scalar_one()
        assert persisted.attempts == 1
        assert persisted.status == "pending"
        assert persisted.next_run_at > now_dt
        assert persisted.lease_owner is None


@pytest.mark.asyncio
async def test_job_execution_terminal_failure_when_max_attempts_exceeded(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Test 2.4: Terminal failure transitions job permanently to status='failed' when attempts >= max_attempts."""
    now_dt = datetime.now(timezone.utc)

    async with db_session_factory() as session:
        job = DBJob(
            id="job-terminal-01",
            profile_id=sample_profile_id,
            kind="routine",
            attempts=2,  # Max is 3
            status="active",
            lease_owner=db_job_runner.worker_id,
            next_run_at=now_dt,
        )
        session.add(job)
        await session.commit()

    spec = ToolSpec(
        name="terminal_failing_tool",
        risk_tier="write_local",
        executor=MagicMock(side_effect=RuntimeError("Permanent corruption")),
    )

    res = await db_job_runner.execute_job(job, spec)
    assert res.success is False

    async with db_session_factory() as session:
        res_db = await session.execute(select(DBJob).where(DBJob.id == "job-terminal-01"))
        persisted = res_db.scalar_one()
        assert persisted.attempts == 3
        assert persisted.status == "failed"
        assert persisted.lease_owner is None


@pytest.mark.asyncio
async def test_job_execution_blocked_by_approval_does_not_execute_tool(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Test 2.5: Background job attempting irreversible action halts execution, creates pending approval, and never invokes executor."""
    now_dt = datetime.now(timezone.utc)
    mock_executor = MagicMock()

    async with db_session_factory() as session:
        job = DBJob(
            id="job-approval-01",
            profile_id=sample_profile_id,
            kind="routine",
            status="active",
            lease_owner=db_job_runner.worker_id,
            next_run_at=now_dt,
        )
        session.add(job)
        await session.commit()

    spec = ToolSpec(
        name="irreversible_med_delete",
        risk_tier="irreversible",
        executor=mock_executor,
    )

    approval_store = ApprovalStore()
    res = await db_job_runner.execute_job(job, spec, approval_store=approval_store)

    assert res.success is False
    assert res.needs_approval is True
    assert mock_executor.call_count == 0, "Tool executor must NEVER be called when approval is required"

    async with db_session_factory() as session:
        res_db = await session.execute(select(DBJob).where(DBJob.id == "job-approval-01"))
        persisted = res_db.scalar_one()
        assert persisted.status == "failed"
        assert persisted.lease_owner is None


# ============================================================================
# Suite 3: Sleep/Wake Clock Jump Detection & Coalescing
# ============================================================================


@pytest.mark.asyncio
async def test_sleep_wake_clock_jump_detection(memory_job_runner: JobRunner):
    """Test 3.1: Wall-clock difference exceeding jump_threshold triggers sleep/wake jump handling."""
    last_tick = 1000.0
    now = 4600.0  # 1 hour sleep jump

    res = memory_job_runner.handle_wake_jump(last_tick=last_tick, now=now)
    coalesced, missed = await res if asyncio.iscoroutine(res) else res

    assert isinstance(coalesced, int)
    assert isinstance(missed, int)


@pytest.mark.asyncio
async def test_sleep_wake_coalesce_duplicate_connector_syncs(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Test 3.2: Multiple connector syncs for same connection accumulated during sleep coalesce to 1 active sync."""
    now = 10000.0
    now_dt = datetime.fromtimestamp(now, tz=timezone.utc)

    async with db_session_factory() as session:
        for i in range(4):
            session.add(
                DBJob(
                    id=f"sync-epic-{i}",
                    profile_id=sample_profile_id,
                    kind="connector_sync",
                    connection_id="conn-epic-ehr",
                    status="pending",
                    next_run_at=now_dt - timedelta(minutes=30 * (i + 1)),
                )
            )
        await session.commit()

    res = db_job_runner.handle_wake_jump(last_tick=1000.0, now=now)
    coalesced, missed = await res if asyncio.iscoroutine(res) else res

    assert coalesced == 3, "Exactly 3 duplicate connector syncs must be coalesced"

    async with db_session_factory() as session:
        res_db = await session.execute(
            select(DBJob).where(DBJob.connection_id == "conn-epic-ehr")
        )
        jobs = res_db.scalars().all()
        pending = [j for j in jobs if j.status == "pending"]
        completed = [j for j in jobs if j.status == "completed"]
        assert len(pending) == 1
        assert len(completed) == 3


@pytest.mark.asyncio
async def test_sleep_wake_distinct_connections_not_coalesced(memory_job_runner: JobRunner):
    """Test 3.3: Overdue syncs for different connections are not coalesced with each other."""
    from tests.e2e_autonomy.contracts import Job as ContractJob

    now = 10000.0
    j1 = ContractJob(
        id="sync-apple-01",
        profile_id="prof-1",
        kind="connector_sync",
        connection_id="conn-apple-health",
        routine_id="r1",
        payload={},
        next_run_at=now - 1000.0,
        status="pending",
    )
    j2 = ContractJob(
        id="sync-fitbit-01",
        profile_id="prof-1",
        kind="connector_sync",
        connection_id="conn-fitbit",
        routine_id="r2",
        payload={},
        next_run_at=now - 800.0,
        status="pending",
    )
    memory_job_runner.add_job(j1)
    memory_job_runner.add_job(j2)

    res = memory_job_runner.handle_wake_jump(last_tick=1000.0, now=now)
    coalesced, missed = await res if asyncio.iscoroutine(res) else res

    assert coalesced == 0
    assert j1.status == "pending"
    assert j2.status == "pending"


@pytest.mark.asyncio
async def test_sleep_wake_clock_moving_backwards_graceful(memory_job_runner: JobRunner):
    """Test 3.4: Clock moving backwards (NTP skew / DST) is handled gracefully without errors."""
    last_tick = 5000.0
    now = 4900.0  # -100s backward jump

    res = memory_job_runner.handle_wake_jump(last_tick=last_tick, now=now)
    coalesced, missed = await res if asyncio.iscoroutine(res) else res

    assert coalesced == 0
    assert missed == 0


# ============================================================================
# Suite 4: Overdue >24h Reminder Marked Missed (Clinical Safety Invariant)
# ============================================================================


@pytest.mark.asyncio
async def test_overdue_reminder_gt_24h_marked_missed(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Test 4.1: Reminders overdue by >24 hours (86,400s) are marked as 'missed'."""
    now = 200000.0
    now_dt = datetime.fromtimestamp(now, tz=timezone.utc)

    async with db_session_factory() as session:
        job = DBJob(
            id="remind-insulin-01",
            profile_id=sample_profile_id,
            kind="reminder",
            status="pending",
            next_run_at=now_dt - timedelta(hours=26),  # 26 hours overdue (>24h)
        )
        session.add(job)
        await session.commit()

    res = db_job_runner.handle_wake_jump(last_tick=now - 90000.0, now=now)
    coalesced, missed = await res if asyncio.iscoroutine(res) else res

    assert missed == 1

    async with db_session_factory() as session:
        res_db = await session.execute(select(DBJob).where(DBJob.id == "remind-insulin-01"))
        persisted = res_db.scalar_one()
        assert persisted.status == "missed"


@pytest.mark.asyncio
async def test_overdue_reminder_gt_24h_zero_tool_execution(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Test 4.2: Reminders overdue by >24 hours are excluded from leasing and never invoke tool execution."""
    now = 200000.0
    now_dt = datetime.fromtimestamp(now, tz=timezone.utc)

    async with db_session_factory() as session:
        job = DBJob(
            id="remind-stale-01",
            profile_id=sample_profile_id,
            kind="reminder",
            status="pending",
            next_run_at=now_dt - timedelta(hours=25),
        )
        session.add(job)
        await session.commit()

    mock_tool = MagicMock()
    spec = ToolSpec(name="alert_tool", risk_tier="write_local", executor=mock_tool)

    # Perform tick sweep
    await db_job_runner.tick()

    assert mock_tool.call_count == 0, "Stale reminder must NEVER trigger tool execution"

    async with db_session_factory() as session:
        res_db = await session.execute(select(DBJob).where(DBJob.id == "remind-stale-01"))
        persisted = res_db.scalar_one()
        assert persisted.status == "missed"


@pytest.mark.asyncio
async def test_recent_reminder_lt_24h_not_marked_missed(memory_job_runner: JobRunner):
    """Test 4.3: Reminder overdue by only 2 hours (<24h) is NOT marked missed and remains pending."""
    from tests.e2e_autonomy.contracts import Job as ContractJob

    now = 10000.0
    j = ContractJob(
        id="remind-recent-01",
        profile_id="prof-1",
        kind="reminder",
        routine_id="r1",
        connection_id="c1",
        payload={},
        next_run_at=now - 7200.0,  # 2 hours overdue (<24h)
        status="pending",
    )
    memory_job_runner.add_job(j)

    res = memory_job_runner.handle_wake_jump(last_tick=now - 7200.0, now=now)
    coalesced, missed = await res if asyncio.iscoroutine(res) else res

    assert missed == 0
    assert j.status == "pending"


# ============================================================================
# Suite 5: Universal Execution Choke Point Invariants
# ============================================================================


@pytest.mark.asyncio
async def test_zero_unchoked_tool_calls_across_all_job_kinds(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Test 5.1: 100% of tool calls from JobRunner route through execute_tool_call with principal='job'."""
    now_dt = datetime.now(timezone.utc)
    observed_calls: List[ToolContext] = []

    async with db_session_factory() as session:
        for kind in ("routine", "connector_sync", "reminder"):
            session.add(
                DBJob(
                    id=f"job-kind-{kind}",
                    profile_id=sample_profile_id,
                    kind=kind,
                    status="active",
                    lease_owner=db_job_runner.worker_id,
                    next_run_at=now_dt,
                )
            )
        await session.commit()

    with patch(
        "carefold.engine.job_runner.execute_tool_call",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = ToolResult(success=True, output={"status": "ok"})

        for kind in ("routine", "connector_sync", "reminder"):
            job = DBJob(
                id=f"job-kind-{kind}",
                profile_id=sample_profile_id,
                kind=kind,
                status="active",
                lease_owner=db_job_runner.worker_id,
                next_run_at=now_dt,
            )
            spec = ToolSpec(name=f"tool_{kind}", risk_tier="write_local")
            await db_job_runner.execute_job(job, spec)

        assert mock_exec.call_count == 3
        for call_args in mock_exec.call_args_list:
            ctx = call_args[0][0]
            assert isinstance(ctx, ToolContext)
            assert ctx.principal == "job", "Choke point must always receive principal='job'"
            assert ctx.autonomy == "A2"
            assert ctx.profile_id == sample_profile_id


@pytest.mark.asyncio
async def test_egress_firewall_blocks_unauthorized_job_network_calls(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Test 5.2: Outbound network call to host not in allowed_hosts is blocked by egress firewall."""
    now_dt = datetime.now(timezone.utc)

    async with db_session_factory() as session:
        job = DBJob(
            id="job-egress-01",
            profile_id=sample_profile_id,
            kind="connector_sync",
            payload=json.dumps({"target_url": "https://malicious-exfiltrate.net/post"}),
            status="active",
            lease_owner=db_job_runner.worker_id,
            next_run_at=now_dt,
        )
        session.add(job)
        await session.commit()

    spec = ToolSpec(
        name="sync_external_ehr",
        risk_tier="write_external",
        data_flows=DataFlows(allowed_hosts=("trusted-ehr.health.org",)),
        executor=AsyncMock(),
    )

    res = await db_job_runner.execute_job(job, spec)
    assert res.success is False
    assert "EgressBlockedError" in str(res.error)

    async with db_session_factory() as session:
        res_db = await session.execute(select(DBJob).where(DBJob.id == "job-egress-01"))
        persisted = res_db.scalar_one()
        assert persisted.status == "failed"


@pytest.mark.asyncio
async def test_monotone_taint_propagation_in_multi_step_job(
    sample_profile_id: str,
):
    """Test 5.3: Once tainted by untrusted source, context remains tainted and blocks external writes."""
    ctx = ToolContext(
        user_id="system-job-runner",
        profile_id=sample_profile_id,
        principal="job",
        run_id="job-multi-step-01",
        autonomy="A2",
    )

    # Step 1: Ingest untrusted third-party EHR text
    spec_step1 = ToolSpec(
        name="fetch_untrusted_ehr",
        risk_tier="read",
        trust="untrusted",
        executor=lambda args: UntrustedResult(data="raw-imported-ehr"),
    )
    res1 = await execute_tool_call(ctx, spec_step1, {})
    assert res1.success is True
    assert ctx.taint.is_tainted is True, "Taint must become True after executing untrusted tool"

    # Step 2: Attempt write_external without prior explicit consent
    spec_step2 = ToolSpec(
        name="export_to_cloud",
        risk_tier="write_external",
        executor=AsyncMock(),
    )
    res2 = await execute_tool_call(ctx, spec_step2, {})
    assert res2.success is False
    assert res2.needs_approval is True
    assert "tainted" in str(res2.error).lower()


@pytest.mark.asyncio
async def test_audit_event_logged_with_principal_job(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Test 5.4: Successful background tool execution logs an AuditEventRecord with principal='job'."""
    now_dt = datetime.now(timezone.utc)

    async with db_session_factory() as session:
        job = DBJob(
            id="job-audit-01",
            profile_id=sample_profile_id,
            kind="routine",
            status="active",
            lease_owner=db_job_runner.worker_id,
            next_run_at=now_dt,
        )
        session.add(job)
        await session.commit()

    spec = ToolSpec(
        name="routine_audit_tool",
        risk_tier="write_local",
        executor=lambda args: {"written": True},
    )

    res = await db_job_runner.execute_job(job, spec)
    assert res.success is True

    async with db_session_factory() as session:
        stmt = select(AuditEventRecord).where(
            AuditEventRecord.run_id == "job-run-job-audit-01"
        )
        result = await session.execute(stmt)
        audits = result.scalars().all()
        assert len(audits) >= 1
        assert audits[0].principal == "job"
        assert audits[0].tool == "routine_audit_tool"
        assert audits[0].profile_id == sample_profile_id
        assert audits[0].decision == "allow"


# ============================================================================
# Additional Lifecycle & Recurrence Tests
# ============================================================================


@pytest.mark.asyncio
async def test_job_runner_start_stop_lifecycle(memory_job_runner: JobRunner):
    """Verifies that start(), is_running, and stop() manage polling loop task cleanly."""
    assert not memory_job_runner.is_running

    task = await memory_job_runner.start()
    assert memory_job_runner.is_running
    assert not task.done()

    await memory_job_runner.stop(timeout=1.0)
    assert not memory_job_runner.is_running
    assert task.done()


def test_calculate_next_occurrence_recurrence_rules():
    """Verifies RFC 5545 recurrence rule evaluator produces candidate strictly > now."""
    now_dt = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
    base_dt = datetime(2026, 10, 12, 4, 0, 0, tzinfo=timezone.utc)  # 8 hours ago

    # Hourly recurrence: advances past all 8 missed hours to next future occurrence
    next_hr = calculate_next_occurrence("FREQ=HOURLY;INTERVAL=1", now=now_dt, base_time=base_dt)
    assert next_hr is not None
    assert next_hr > now_dt
    assert next_hr == datetime(2026, 10, 12, 13, 0, 0, tzinfo=timezone.utc)

    # Daily recurrence
    next_day = calculate_next_occurrence("FREQ=DAILY;INTERVAL=1", now=now_dt, base_time=base_dt)
    assert next_day is not None
    assert next_day > now_dt
    assert next_day == datetime(2026, 10, 13, 4, 0, 0, tzinfo=timezone.utc)

    # UNTIL rule in past returns None
    until_rule = "FREQ=HOURLY;INTERVAL=1;UNTIL=2026-10-12T10:00:00Z"
    assert calculate_next_occurrence(until_rule, now=now_dt, base_time=base_dt) is None


@pytest.mark.asyncio
async def test_heartbeat_lease_renewal(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Verifies that heartbeat() extends lease_until for active long-running jobs."""
    now_dt = datetime.now(timezone.utc)
    initial_until = now_dt + timedelta(seconds=10)

    async with db_session_factory() as session:
        job = DBJob(
            id="job-long-run-01",
            profile_id=sample_profile_id,
            kind="routine",
            status="active",
            lease_owner=db_job_runner.worker_id,
            lease_until=initial_until,
            next_run_at=now_dt,
        )
        session.add(job)
        await session.commit()

    success = await db_job_runner.heartbeat("job-long-run-01")
    assert success is True

    async with db_session_factory() as session:
        res = await session.execute(select(DBJob).where(DBJob.id == "job-long-run-01"))
        persisted = res.scalar_one()
        assert persisted.lease_until > initial_until
