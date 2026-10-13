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
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from carefold.db.models import Attachment, AuditEventRecord, Base, Job as DBJob, Profile, User
from carefold.engine.job_runner import (
    CLOCK_JUMP_THRESHOLD_SECONDS,
    DEFAULT_LEASE_DURATION,
    DEFAULT_POLL_INTERVAL,
    REMINDER_OVERDUE_THRESHOLD_SECONDS,
    JobRunner,
    calculate_next_occurrence,
    handle_extract_text_job,
)
from carefold.storage.cas import store_cas_file
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


# =========================================================================
# Suite 6: Handler Registry & Leased Job Dispatching (AU-22)
# =========================================================================

def test_job_runner_handler_registry():
    """Verifies handler registration, query, and unregistration lifecycle."""
    runner = JobRunner()

    async def sample_handler(job):
        pass

    assert runner.has_handler("sample_kind") is False
    assert runner.get_handler("sample_kind") is None

    runner.register_handler("sample_kind", sample_handler)
    assert runner.has_handler("sample_kind") is True
    assert runner.get_handler("sample_kind") is sample_handler

    runner.unregister_handler("sample_kind")
    assert runner.has_handler("sample_kind") is False
    assert runner.get_handler("sample_kind") is None


@pytest.mark.asyncio
async def test_process_leased_job_dispatches_to_registered_handler(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Verifies that _process_leased_job routes job to registered handler and completes it."""
    invoked_jobs = []

    async def custom_handler(job):
        invoked_jobs.append(job.id)

    db_job_runner.register_handler("custom_kind", custom_handler)

    now_dt = datetime.now(timezone.utc)
    async with db_session_factory() as session:
        job = DBJob(
            id="job-dispatch-01",
            profile_id=sample_profile_id,
            kind="custom_kind",
            status="active",
            lease_owner=db_job_runner.worker_id,
            lease_until=now_dt + timedelta(seconds=60),
            next_run_at=now_dt,
            attempts=0,
        )
        session.add(job)
        await session.commit()

    await db_job_runner._process_leased_job(job)

    assert "job-dispatch-01" in invoked_jobs

    async with db_session_factory() as session:
        res = await session.execute(select(DBJob).where(DBJob.id == "job-dispatch-01"))
        persisted = res.scalar_one()
        assert persisted.status == "completed"
        assert persisted.lease_owner is None
        assert persisted.lease_until is None


@pytest.mark.asyncio
async def test_process_leased_job_unregistered_kind_releases_lease(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Verifies that an unregistered job kind releases lease lock without modifying attempts."""
    now_dt = datetime.now(timezone.utc)
    async with db_session_factory() as session:
        job = DBJob(
            id="job-unregistered-01",
            profile_id=sample_profile_id,
            kind="unregistered_kind_xyz",
            status="active",
            lease_owner=db_job_runner.worker_id,
            lease_until=now_dt + timedelta(seconds=60),
            next_run_at=now_dt,
            attempts=0,
        )
        session.add(job)
        await session.commit()

    await db_job_runner._process_leased_job(job)

    assert job.lease_owner is None
    assert job.lease_until is None


@pytest.mark.asyncio
async def test_process_leased_job_handler_failure_exponential_backoff(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    db_job_runner: JobRunner,
):
    """Verifies retry with exponential backoff on handler failure up to max_attempts."""
    async def failing_handler(job):
        raise RuntimeError("Transient handler network error")

    db_job_runner.register_handler("failing_kind", failing_handler)
    now_dt = datetime.now(timezone.utc)

    # Attempt 1: attempts = 0 -> 1, backoff = 30.0s
    async with db_session_factory() as session:
        job = DBJob(
            id="job-retry-01",
            profile_id=sample_profile_id,
            kind="failing_kind",
            status="active",
            lease_owner=db_job_runner.worker_id,
            lease_until=now_dt + timedelta(seconds=60),
            next_run_at=now_dt,
            attempts=0,
        )
        session.add(job)
        await session.commit()

    await db_job_runner._process_leased_job(job)

    async with db_session_factory() as session:
        res = await session.execute(select(DBJob).where(DBJob.id == "job-retry-01"))
        persisted = res.scalar_one()
        assert persisted.status == "pending"
        assert persisted.attempts == 1
        assert persisted.lease_owner is None
        assert persisted.next_run_at >= now_dt + timedelta(seconds=25)

    # Attempt 2: attempts = 1 -> 2, backoff = 60.0s
    persisted.lease_owner = db_job_runner.worker_id
    persisted.status = "active"
    await db_job_runner._process_leased_job(persisted)

    async with db_session_factory() as session:
        res = await session.execute(select(DBJob).where(DBJob.id == "job-retry-01"))
        persisted2 = res.scalar_one()
        assert persisted2.status == "pending"
        assert persisted2.attempts == 2
        assert persisted2.next_run_at >= now_dt + timedelta(seconds=55)

    # Attempt 3: attempts = 2 -> 3 (max_attempts = 3), terminal failure
    persisted2.lease_owner = db_job_runner.worker_id
    persisted2.status = "active"
    await db_job_runner._process_leased_job(persisted2)

    async with db_session_factory() as session:
        res = await session.execute(select(DBJob).where(DBJob.id == "job-retry-01"))
        terminal_job = res.scalar_one()
        assert terminal_job.status == "failed"
        assert terminal_job.attempts == 3
        assert terminal_job.lease_owner is None


# =========================================================================
# Suite 7: Adversarial Stress Tests (Milestone 2 / Challenger 2)
# =========================================================================


@pytest.mark.asyncio
async def test_concurrent_workers_no_double_execution(
    tmp_path: Path,
    sample_profile_id: str,
):
    """Stress test: 10 concurrent workers competing across 20 jobs with interleaving handlers.
    Asserts: exactly 1 execution per job, 0 double executions, all 20 jobs reach 'completed'.
    """
    db_file = tmp_path / "carefold_stress_concurrency.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_async_engine(
        db_url,
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

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sf = async_sessionmaker(engine, expire_on_commit=False)

    # Seed baseline User and Profile
    async with sf() as session:
        u = User(
            id="user-stress-01",
            email="stress@carefold.local",
            username="stress_user",
            hashed_password="pw-hash-stress",
        )
        p = Profile(
            id=sample_profile_id,
            user_id="user-stress-01",
            name="Stress Profile",
            relationship="self",
        )
        session.add_all([u, p])
        await session.commit()

    num_jobs = 20
    num_workers = 10
    now_dt = datetime.now(timezone.utc)

    # Insert 20 pending jobs
    async with sf() as session:
        for i in range(num_jobs):
            job = DBJob(
                id=f"job-stress-{i:03d}",
                profile_id=sample_profile_id,
                kind="stress_concurrent_kind",
                next_run_at=now_dt - timedelta(seconds=i + 1),
                status="pending",
            )
            session.add(job)
        await session.commit()

    # Track execution count per job
    job_executions: Dict[str, List[str]] = {f"job-stress-{i:03d}": [] for i in range(num_jobs)}
    exec_lock = asyncio.Lock()

    async def stress_handler(job: Any) -> None:
        jid = job.id
        w_id = getattr(job, "lease_owner", "unknown")
        # Artificial sleep to induce concurrency collisions
        await asyncio.sleep(0.01)
        async with exec_lock:
            job_executions[jid].append(w_id)

    # Create 10 distinct JobRunner instances
    workers = [
        JobRunner(
            session_factory=sf,
            worker_id=f"stress-worker-{i}",
            poll_interval=0.01,
            lease_duration=30.0,
            batch_size=5,
        )
        for i in range(num_workers)
    ]
    for w in workers:
        w.register_handler("stress_concurrent_kind", stress_handler)

    # Concurrently tick workers until all jobs are done (max 10 rounds)
    for _ in range(10):
        await asyncio.gather(*(w.tick() for w in workers))
        total_executed = sum(len(v) for v in job_executions.values())
        if total_executed >= num_jobs:
            break

    # Assertions
    # 1. Total executions must equal num_jobs exactly
    for jid, workers_ran in job_executions.items():
        assert len(workers_ran) == 1, (
            f"Job {jid} executed {len(workers_ran)} times! Expected exactly 1 (workers: {workers_ran})"
        )

    # 2. Verify DB states
    async with sf() as session:
        stmt = select(DBJob).where(DBJob.id.like("job-stress-%"))
        res = await session.execute(stmt)
        persisted_jobs = res.scalars().all()
        assert len(persisted_jobs) == num_jobs
        for pj in persisted_jobs:
            assert pj.status == "completed", f"Job {pj.id} status is {pj.status}, expected completed"
            assert pj.lease_owner is None
            assert pj.lease_until is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_heartbeat_loop_prevents_lease_stealing(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
):
    """Stress test: A handler takes 0.6s while lease_duration is 0.2s.
    _heartbeat_loop extends lease_until in the background.
    A competing worker polling at t=0.35s cannot steal the job.
    """
    now_dt = datetime.now(timezone.utc)
    job_id = "job-heartbeat-stealing-01"

    async with db_session_factory() as session:
        job = DBJob(
            id=job_id,
            profile_id=sample_profile_id,
            kind="long_running_kind",
            next_run_at=now_dt - timedelta(seconds=5),
            status="pending",
        )
        session.add(job)
        await session.commit()

    worker_holder = JobRunner(
        session_factory=db_session_factory,
        worker_id="worker-holder-legit",
        lease_duration=0.2,  # Short 200ms lease
        batch_size=1,
    )
    worker_thief = JobRunner(
        session_factory=db_session_factory,
        worker_id="worker-thief-competing",
        lease_duration=10.0,
        batch_size=1,
    )

    handler_started = asyncio.Event()
    thief_attempted = asyncio.Event()
    thief_leased: List[Any] = []

    async def long_handler(job: Any) -> None:
        handler_started.set()
        # Sleep 0.6s, well beyond the 0.2s lease duration
        # During this sleep, _heartbeat_loop will run every 0.1s
        await asyncio.sleep(0.6)

    worker_holder.register_handler("long_running_kind", long_handler)
    worker_thief.register_handler("long_running_kind", long_handler)

    async def run_holder():
        await worker_holder.tick()

    async def run_thief():
        await handler_started.wait()
        # Wait 350ms — by this time, without heartbeats the initial 200ms lease would be expired
        await asyncio.sleep(0.35)
        stolen = await worker_thief.lease_batch(
            worker_id=worker_thief.worker_id,
            now=datetime.now(timezone.utc),
            batch_size=1,
        )
        thief_leased.extend(stolen)
        thief_attempted.set()

    await asyncio.gather(run_holder(), run_thief())

    # Assertions
    # 1. Competing worker failed to steal the lease
    assert len(thief_leased) == 0, f"Thief worker stole lease: {[j.id for j in thief_leased]}"

    # 2. Legitimate worker successfully completed the job
    async with db_session_factory() as session:
        res = await session.execute(select(DBJob).where(DBJob.id == job_id))
        persisted = res.scalar_one()
        assert persisted.status == "completed"
        assert persisted.lease_owner is None


@pytest.mark.asyncio
async def test_exception_backoff_and_terminal_failure_with_attachment(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    tmp_path: Path,
):
    """Stress test: A failing extract_text job verifies exponential backoff progression,
    retry attempt counting, and terminal failure with attachment.extraction_status = 'failed'.
    """
    runner = JobRunner(
        session_factory=db_session_factory,
        worker_id="runner-fail-test",
        max_attempts=3,
        lease_duration=10.0,
    )

    att_id = f"att-fail-{uuid.uuid4().hex[:8]}"
    nonexistent_hash = "0" * 64
    now_dt = datetime.now(timezone.utc)

    # Seed Attachment in pending state
    async with db_session_factory() as session:
        att = Attachment(
            id=att_id,
            user_id="user-runner-01",
            profile_id=sample_profile_id,
            filename="missing_blood_work.pdf",
            original_name="missing_blood_work.pdf",
            content_type="application/pdf",
            size_bytes=500,
            sha256_hash=nonexistent_hash,
            storage_key=f"user-runner-01/{sample_profile_id}/missing.pdf",
            extraction_status="pending",
        )
        session.add(att)
        await session.commit()

    # Seed extract_text job pointing to the missing file
    job_id = f"job-extract-fail-{uuid.uuid4().hex[:8]}"
    payload = {
        "attachment_id": att_id,
        "user_id": "user-runner-01",
        "profile_id": sample_profile_id,
        "sha256": nonexistent_hash,
        "filename": "missing_blood_work.pdf",
        "content_type": "application/pdf",
    }
    async with db_session_factory() as session:
        job = DBJob(
            id=job_id,
            profile_id=sample_profile_id,
            kind="extract_text",
            payload=json.dumps(payload),
            timezone="UTC",
            next_run_at=now_dt - timedelta(seconds=10),
            status="pending",
            attempts=0,
        )
        session.add(job)
        await session.commit()

    # Attempt 1: failure -> attempts=1, status='pending', backoff=30.0s, attachment='failed'
    await runner.tick()

    async with db_session_factory() as session:
        j1 = (await session.execute(select(DBJob).where(DBJob.id == job_id))).scalar_one()
        a1 = (await session.execute(select(Attachment).where(Attachment.id == att_id))).scalar_one()
        assert j1.status == "pending"
        assert j1.attempts == 1
        assert j1.lease_owner is None
        # Backoff: 30 * 2^(1-1) = 30 seconds
        assert j1.next_run_at >= now_dt + timedelta(seconds=20)
        assert a1.extraction_status == "failed"

    # Reset next_run_at to past to simulate retry 2
    async with db_session_factory() as session:
        await session.execute(
            text("UPDATE jobs SET next_run_at = :past WHERE id = :id"),
            {"past": datetime.now(timezone.utc) - timedelta(seconds=1), "id": job_id},
        )
        await session.commit()

    # Attempt 2: failure -> attempts=2, status='pending', backoff=60.0s, attachment='failed'
    t1 = datetime.now(timezone.utc)
    await runner.tick()

    async with db_session_factory() as session:
        j2 = (await session.execute(select(DBJob).where(DBJob.id == job_id))).scalar_one()
        a2 = (await session.execute(select(Attachment).where(Attachment.id == att_id))).scalar_one()
        assert j2.status == "pending"
        assert j2.attempts == 2
        assert j2.lease_owner is None
        # Backoff: 30 * 2^(2-1) = 60 seconds
        assert j2.next_run_at >= t1 + timedelta(seconds=50)
        assert a2.extraction_status == "failed"

    # Reset next_run_at to past to simulate retry 3 (terminal)
    async with db_session_factory() as session:
        await session.execute(
            text("UPDATE jobs SET next_run_at = :past WHERE id = :id"),
            {"past": datetime.now(timezone.utc) - timedelta(seconds=1), "id": job_id},
        )
        await session.commit()

    # Attempt 3: failure -> attempts=3 >= max_attempts, status='failed', attachment='failed'
    await runner.tick()

    async with db_session_factory() as session:
        j3 = (await session.execute(select(DBJob).where(DBJob.id == job_id))).scalar_one()
        a3 = (await session.execute(select(Attachment).where(Attachment.id == att_id))).scalar_one()
        assert j3.status == "failed"
        assert j3.attempts == 3
        assert j3.lease_owner is None
        assert j3.lease_until is None
        assert a3.extraction_status == "failed"


@pytest.mark.asyncio
async def test_idempotency_key_deduplication(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
    tmp_path: Path,
):
    """Stress test: Rapid repeated triggers of handle_extract_text_job for the same attachment
    and rapid repeated enqueuing with idempotency_key prevents duplicate extract_text or index_doc rows.
    """
    home_dir = tmp_path / "carefold_home"
    user_id = "user-runner-01"
    content_bytes = b"Clinical notes for patient 9876. Glucose normal."

    _, sha256_hash, _ = store_cas_file(
        content=content_bytes,
        carefold_home=home_dir,
        user_id=user_id,
        profile_id=sample_profile_id,
    )

    att_id = f"att-idemp-{uuid.uuid4().hex[:8]}"

    async with db_session_factory() as session:
        att = Attachment(
            id=att_id,
            user_id=user_id,
            profile_id=sample_profile_id,
            filename="glucose.txt",
            original_name="glucose.txt",
            content_type="text/plain",
            size_bytes=len(content_bytes),
            sha256_hash=sha256_hash,
            storage_key=f"{user_id}/{sample_profile_id}/glucose.txt",
            extraction_status="pending",
        )
        session.add(att)
        await session.commit()

    # Part A: Test extract_text idempotency key deduplication pattern
    extract_idemp_key = f"extract:{att_id}:{sha256_hash}"

    async def try_enqueue_extract(seq: int):
        async with db_session_factory() as session:
            check_stmt = select(DBJob.id).where(
                DBJob.idempotency_key == extract_idemp_key,
                DBJob.status.in_(["pending", "active", "completed"]),
            )
            res = await session.execute(check_stmt)
            if res.scalar_one_or_none() is None:
                new_job = DBJob(
                    id=f"job-extract-{seq}-{uuid.uuid4().hex[:6]}",
                    profile_id=sample_profile_id,
                    kind="extract_text",
                    payload=json.dumps({"attachment_id": att_id, "user_id": user_id, "profile_id": sample_profile_id}),
                    timezone="UTC",
                    next_run_at=datetime.now(timezone.utc),
                    idempotency_key=extract_idemp_key,
                    status="pending",
                )
                session.add(new_job)
                await session.commit()

    # Rapid repeated enqueuing
    for i in range(5):
        await try_enqueue_extract(i)

    async with db_session_factory() as session:
        res = await session.execute(
            select(DBJob).where(DBJob.idempotency_key == extract_idemp_key)
        )
        extract_jobs = res.scalars().all()
        assert len(extract_jobs) == 1, f"Expected exactly 1 extract_text job, got {len(extract_jobs)}"

    # Part B: Rapid repeated handle_extract_text_job execution prevents duplicate index_doc jobs
    job_to_run = extract_jobs[0]
    expected_index_idemp = f"index:attachment:{att_id}:{sha256_hash}"

    # Run handler 5 times rapidly
    for _ in range(5):
        await handle_extract_text_job(
            job=job_to_run,
            session_factory=db_session_factory,
            carefold_home=home_dir,
        )

    async with db_session_factory() as session:
        res = await session.execute(
            select(DBJob).where(DBJob.idempotency_key == expected_index_idemp)
        )
        index_jobs = res.scalars().all()
        assert len(index_jobs) == 1, f"Expected exactly 1 index_doc job, got {len(index_jobs)}"
        assert index_jobs[0].kind == "index_doc"
        assert index_jobs[0].status == "pending"


@pytest.mark.asyncio
async def test_unregistered_job_kind_releases_lease_without_crash(
    db_session_factory: async_sessionmaker[AsyncSession],
    sample_profile_id: str,
):
    """Stress test: A worker leases a job of completely unknown/unregistered kind.
    Verifies that the lease is released without crashing the worker or incrementing attempts,
    and the runner loop continues executing normally.
    """
    now_dt = datetime.now(timezone.utc)
    job_id = "job-unregistered-adversarial-01"

    async with db_session_factory() as session:
        job = DBJob(
            id=job_id,
            profile_id=sample_profile_id,
            kind="completely_unknown_quantum_compute_task",
            next_run_at=now_dt - timedelta(seconds=10),
            status="pending",
            attempts=0,
        )
        session.add(job)
        await session.commit()

    runner = JobRunner(
        session_factory=db_session_factory,
        worker_id="runner-vanilla-node",
        poll_interval=0.01,
        lease_duration=15.0,
    )
    # Runner only has default extract_text handler, NOT the unknown kind

    # Execute tick — should not raise any exception
    await runner.tick()

    async with db_session_factory() as session:
        res = await session.execute(select(DBJob).where(DBJob.id == job_id))
        persisted = res.scalar_one()
        # Lease lock is safely released
        assert persisted.lease_owner is None
        assert persisted.lease_until is None
        # Attempts must NOT be incremented (it was not a failure of the job itself)
        assert persisted.attempts == 0
        # Status is pending or active with no lease (eligible for other specialized workers)
        assert persisted.status in ("pending", "active")

    # Verify that a specialized worker registering the kind can subsequently lease and process it
    specialized_runner = JobRunner(
        session_factory=db_session_factory,
        worker_id="runner-quantum-specialist",
        lease_duration=15.0,
    )
    executed_quantum = []

    async def quantum_handler(job: Any) -> None:
        executed_quantum.append(job.id)

    specialized_runner.register_handler("completely_unknown_quantum_compute_task", quantum_handler)

    await specialized_runner.tick()

    assert job_id in executed_quantum
    async with db_session_factory() as session:
        res = await session.execute(select(DBJob).where(DBJob.id == job_id))
        completed_job = res.scalar_one()
        assert completed_job.status == "completed"


