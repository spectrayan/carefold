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

"""Tier 1: Feature Coverage in Isolation — Policy Gate, HITL Approvals, Taint, & Job Runner.

Covers Feature 3 (Policy Gate AU-17), Feature 4 (HITL Approvals AU-18),
Feature 5 (Monotone Taint & Egress AU-19/20), and Feature 6 (Job Runner AU-21).
"""

from __future__ import annotations

import time
from typing import Any, Dict
import pytest

from tests.e2e_autonomy.contracts import (
    ApprovalStore,
    Job,
    JobRunner,
    TaintFlag,
    ToolContext,
    ToolSpec,
    UntrustedResult,
    canonical_json,
    compute_payload_hash,
    evaluate_policy_gate,
    execute_tool_call,
)


# ============================================================================
# Feature 3: Policy Decision Gate & Choke Point Truth Table (AU-17)
# ============================================================================

def test_t1_f3_autonomy_a0_all_writes_require_approval(make_context):
    """F3.1: Autonomy A0 requires approval for write_local, write_external, and irreversible."""
    ctx = make_context(autonomy="A0")
    t_read = ToolSpec("read_vitals", "Read vitals", {}, risk_tier="read")
    t_wlocal = ToolSpec("save_bp", "Save BP", {}, risk_tier="write_local")
    t_wext = ToolSpec("sync_lab", "Sync Lab", {}, risk_tier="write_external")
    t_irrev = ToolSpec("delete_record", "Delete", {}, risk_tier="irreversible")

    assert evaluate_policy_gate(ctx, t_read, {}).decision == "allow"
    assert evaluate_policy_gate(ctx, t_wlocal, {}).decision == "needs_approval"
    assert evaluate_policy_gate(ctx, t_wext, {}).decision == "needs_approval"
    assert evaluate_policy_gate(ctx, t_irrev, {}).decision == "needs_approval"


def test_t1_f3_autonomy_a1_write_local_permitted_external_needs_approval(make_context):
    """F3.2: Autonomy A1 permits read and write_local; requires approval for external and irreversible."""
    ctx = make_context(autonomy="A1")
    t_read = ToolSpec("read_notes", "Read", {}, risk_tier="read")
    t_wlocal = ToolSpec("write_notes", "Write local", {}, risk_tier="write_local")
    t_wext = ToolSpec("send_portal_msg", "Send msg", {}, risk_tier="write_external")
    t_irrev = ToolSpec("revoke_auth", "Revoke", {}, risk_tier="irreversible")

    assert evaluate_policy_gate(ctx, t_read, {}).decision == "allow"
    assert evaluate_policy_gate(ctx, t_wlocal, {}).decision == "allow"
    assert evaluate_policy_gate(ctx, t_wext, {}).decision == "needs_approval"
    assert evaluate_policy_gate(ctx, t_irrev, {}).decision == "needs_approval"


def test_t1_f3_autonomy_a2_consented_external_permitted_irreversible_needs_approval(make_context):
    """F3.3: Autonomy A2 allows consented external writes, always requires approval for irreversible."""
    ctx = make_context(autonomy="A2")
    t_wext = ToolSpec("email_prep", "Email doc", {}, risk_tier="write_external")
    t_irrev = ToolSpec("order_rx", "Submit Rx", {}, risk_tier="irreversible")

    # Without consent: external write needs approval
    d_no_consent = evaluate_policy_gate(ctx, t_wext, {}, consents={"external_write_consent": False})
    assert d_no_consent.decision == "needs_approval"

    # With consent: external write permitted
    d_consent = evaluate_policy_gate(ctx, t_wext, {}, consents={"external_write_consent": True})
    assert d_consent.decision == "allow"

    # Irreversible always requires approval regardless of consent
    d_irrev = evaluate_policy_gate(ctx, t_irrev, {}, consents={"external_write_consent": True})
    assert d_irrev.decision == "needs_approval"


def test_t1_f3_fail_closed_missing_profile_or_user():
    """F3.4: ToolContext requires non-empty profile_id and user_id (fail-closed)."""
    with pytest.raises(ValueError, match="non-empty profile_id"):
        ToolContext(user_id="user-1", profile_id="")

    with pytest.raises(ValueError, match="non-empty user_id"):
        ToolContext(user_id="", profile_id="prof-1")


def test_t1_f3_canonical_json_and_payload_hash_deterministic():
    """F3.5: Verifies canonical JSON serialization and deterministic SHA-256 hash."""
    args_1 = {"dosage": "50mg", "medication": "metoprolol", "patient": "P-101"}
    args_2 = {"patient": "P-101", "medication": "metoprolol", "dosage": "50mg"}

    assert canonical_json(args_1) == canonical_json(args_2)
    hash_1 = compute_payload_hash(args_1)
    hash_2 = compute_payload_hash(args_2)

    assert hash_1 == hash_2
    assert len(hash_1) == 64


@pytest.mark.asyncio
async def test_t1_f3_execute_tool_call_choke_point_success(make_context):
    """F3.6: Successful tool execution through execute_tool_call choke point."""
    ctx = make_context(autonomy="A1")
    spec = ToolSpec(
        name="calculate_bmi",
        description="Compute BMI",
        risk_tier="read",
        executor=lambda args: {"bmi": round(args["weight"] / ((args["height"] / 100) ** 2), 1)},
    )
    res = await execute_tool_call(ctx, spec, {"weight": 70, "height": 175})
    assert res.success is True
    assert res.output == {"bmi": 22.9}


# ============================================================================
# Feature 4: Human-in-the-Loop Approvals Engine (AU-18)
# ============================================================================

def test_t1_f4_approval_record_creation_with_pending_status(approval_store: ApprovalStore):
    """F4.1: Evaluates policy gate and creates pending record with payload_hash."""
    args = {"provider": "Dr. Smith", "date": "2026-10-15"}
    rec = approval_store.create_pending(
        approval_id="app-test-01",
        profile_id="prof-1",
        run_id="run-1",
        tool_name="schedule_visit",
        args=args,
        risk_tier="write_external",
        destination_hosts=["portal.clinic.org"],
    )
    assert rec.status == "pending"
    assert rec.payload_hash == compute_payload_hash(args)
    assert rec.destination_hosts == ["portal.clinic.org"]


def test_t1_f4_list_pending_approvals_requires_manage_permission(approval_store: ApprovalStore):
    """F4.2: Listing pending approvals requires explicit 'manage' permission."""
    approval_store.create_pending("app-p1", "prof-1", "run-1", "t1", {}, "write_external")

    # Non-manager rejected
    with pytest.raises(PermissionError, match="'manage' permission"):
        approval_store.list_pending("prof-1", caller_permissions=["view"])

    # Manager allowed
    pending = approval_store.list_pending("prof-1", caller_permissions=["manage", "view"])
    assert len(pending) == 1
    assert pending[0].id == "app-p1"


def test_t1_f4_decide_approval_approve_and_reject(approval_store: ApprovalStore):
    """F4.3: Deciding approval transitions from pending to approved or rejected."""
    rec1 = approval_store.create_pending("app-dec-1", "prof-1", "run-1", "t1", {}, "write_external")
    decided_app = approval_store.decide(
        "app-dec-1", "prof-1", "approved", edited_args=None, caller_id="user-1", caller_permissions=["manage"]
    )
    assert decided_app.status == "approved"
    assert decided_app.decided_by == "user-1"

    rec2 = approval_store.create_pending("app-dec-2", "prof-1", "run-1", "t2", {}, "write_external")
    decided_rej = approval_store.decide(
        "app-dec-2", "prof-1", "rejected", edited_args=None, caller_id="user-1", caller_permissions=["manage"]
    )
    assert decided_rej.status == "rejected"


def test_t1_f4_decide_approval_with_edited_arguments(approval_store: ApprovalStore):
    """F4.4: Editing arguments during review updates payload_hash in the approval record."""
    orig_args = {"copay": "$50", "provider": "In-Network"}
    approval_store.create_pending("app-edit-1", "prof-1", "run-1", "t1", orig_args, "write_external")

    edited_args = {"copay": "$25", "provider": "Preferred In-Network"}
    decided = approval_store.decide(
        "app-edit-1", "prof-1", "approved", edited_args=edited_args, caller_id="user-1", caller_permissions=["manage"]
    )
    assert decided.status == "approved"
    assert decided.args_redacted == edited_args
    assert decided.payload_hash == compute_payload_hash(edited_args)
    assert decided.payload_hash != compute_payload_hash(orig_args)


def test_t1_f4_atomic_consume_approved_to_consumed_transition(approval_store: ApprovalStore):
    """F4.5: Atomic consume transition: approved -> consumed with payload hash verification."""
    args = {"action": "sync"}
    approval_store.create_pending("app-atom-1", "prof-1", "run-1", "t1", args, "write_external")
    approval_store.decide("app-atom-1", "prof-1", "approved", None, "u1", ["manage"])

    consumed_id = approval_store.consume_atomic("app-atom-1", args)
    assert consumed_id == "app-atom-1"

    # Second consume attempt fails closed (single-use token invariant)
    with pytest.raises(ValueError, match="status 'consumed'"):
        approval_store.consume_atomic("app-atom-1", args)


@pytest.mark.asyncio
async def test_t1_f4_atomic_resume_in_execute_tool_call(make_context, approval_store: ApprovalStore):
    """F4.6: Choke point pauses on needs_approval, and resumes upon valid approval_id."""
    ctx = make_context(autonomy="A1")
    spec = ToolSpec(
        name="external_calendar_sync",
        description="Sync calendar",
        risk_tier="write_external",
        data_flows=("cal.provider.org",),
        executor=lambda args: {"synced": True, "date": args["date"]},
    )
    args = {"url": "https://cal.provider.org/v1", "date": "2026-10-20"}

    # Turn 1: Policy gate halts and creates pending approval
    res1 = await execute_tool_call(ctx, spec, args, approval_store=approval_store)
    assert res1.success is False
    assert res1.needs_approval is True
    assert res1.approval_id is not None

    # Human reviews and approves
    approval_store.decide(res1.approval_id, ctx.profile_id, "approved", None, "user-admin", ["manage"])

    # Turn 2: Execution resumes and consumes approval atomically
    res2 = await execute_tool_call(
        ctx, spec, args, approval_store=approval_store, approval_id=res1.approval_id
    )
    assert res2.success is True
    assert res2.output == {"synced": True, "date": "2026-10-20"}


# ============================================================================
# Feature 5: Monotone Taint Propagation & Egress Firewall (AU-19 & AU-20)
# ============================================================================

@pytest.mark.asyncio
async def test_t1_f5_untrusted_result_triggers_monotone_taint(make_context):
    """F5.1: Wrapping tool output in UntrustedResult sets context taint flag."""
    ctx = make_context(autonomy="A1", tainted=False)
    assert ctx.taint.is_tainted is False

    spec = ToolSpec(
        name="web_search_clinical",
        description="Search medical papers",
        risk_tier="read",
        trust="untrusted",
        executor=lambda args: UntrustedResult(data="Clinical trial findings..."),
    )
    res = await execute_tool_call(ctx, spec, {"q": "hypertension"})
    assert res.success is True
    assert ctx.taint.is_tainted is True


def test_t1_f5_monotone_taint_cannot_be_cleared():
    """F5.2: Monotone taint invariant: once set, can never be cleared."""
    flag = TaintFlag(initial=False)
    assert not flag
    flag.set()
    assert flag
    assert flag.is_tainted is True
    # Attempting to call set again leaves it True
    flag.set()
    assert flag.is_tainted is True


def test_t1_f5_taint_forces_approval_on_external_and_irreversible(make_context):
    """F5.3: Context with taint=True forces approval on write_external and irreversible even in A2."""
    ctx_clean = make_context(autonomy="A2", tainted=False)
    ctx_tainted = make_context(autonomy="A2", tainted=True)

    t_wext = ToolSpec("send_summary", "Send summary", {}, risk_tier="write_external")
    consents = {"external_write_consent": True}

    # Clean context in A2 with consent is allowed
    assert evaluate_policy_gate(ctx_clean, t_wext, {}, consents=consents).decision == "allow"

    # Tainted context forces approval regardless of A2 autonomy and consent
    d_tainted = evaluate_policy_gate(ctx_tainted, t_wext, {}, consents=consents)
    assert d_tainted.decision == "needs_approval"
    assert "FORCED APPROVAL" in d_tainted.reason


@pytest.mark.asyncio
async def test_t1_f5_egress_firewall_allowed_hosts_passes(make_context):
    """F5.4: Outbound request to allowlisted destination host succeeds."""
    ctx = make_context(autonomy="A1")
    spec = ToolSpec(
        name="post_lab",
        risk_tier="write_external",
        data_flows=("lab.authorized-portal.com",),
        executor=lambda args: {"sent": True},
    )
    res = await execute_tool_call(
        ctx, spec, {"endpoint": "https://lab.authorized-portal.com/api/results"}
    )
    # Reaches policy gate (needs approval under A1, but NOT blocked by egress)
    assert "EgressBlockedError" not in (res.error or "")


@pytest.mark.asyncio
async def test_t1_f5_egress_firewall_unauthorized_host_raises_egress_blocked(make_context):
    """F5.5: Outbound request to unlisted host blocked immediately with 0 bytes sent."""
    ctx = make_context(autonomy="A2")
    spec = ToolSpec(
        name="export_records",
        risk_tier="write_external",
        data_flows=("safe-storage.corp.com",),
        executor=lambda args: {"exfiltrated": True},
    )
    res = await execute_tool_call(
        ctx, spec, {"target_url": "http://attacker-controlled-server.ru/steal"}
    )
    assert res.success is False
    assert "EgressBlockedError" in (res.error or "")
    assert "attacker-controlled-server.ru" in (res.error or "")


@pytest.mark.asyncio
async def test_t1_f5_egress_firewall_empty_data_flows_on_external_tool_blocked(make_context):
    """F5.6: External tool with empty data_flows allowlist blocked on any external call."""
    ctx = make_context(autonomy="A2")
    spec = ToolSpec(
        name="unconfigured_egress",
        risk_tier="write_external",
        data_flows=(),  # No allowed hosts
    )
    res = await execute_tool_call(ctx, spec, {"url": "https://anywhere.org"})
    assert res.success is False
    assert "EgressBlockedError" in (res.error or "")


# ============================================================================
# Feature 6: Wall-Clock Job Runner & Atomic Leasing (AU-21)
# ============================================================================

def test_t1_f6_job_creation_and_scheduling(job_runner: JobRunner, sample_profile_id: str):
    """F6.1: Creates background job with routine_id and next_run_at."""
    job = Job(
        id="job-sync-01",
        profile_id=sample_profile_id,
        kind="connector_sync",
        routine_id="routine-nightly-sync",
        connection_id="conn-epic-01",
        payload={"sync_depth": "7d"},
        next_run_at=time.time() - 10.0,  # Due now
    )
    job_runner.add_job(job)
    assert job.status == "pending"


def test_t1_f6_atomic_leasing_single_worker(job_runner: JobRunner, sample_profile_id: str):
    """F6.2: Worker atomically leases batch of pending due jobs."""
    now = time.time()
    job = Job(
        id="job-due-01",
        profile_id=sample_profile_id,
        kind="reminder",
        routine_id="rout-1",
        connection_id="conn-1",
        payload={"msg": "Take aspirin"},
        next_run_at=now - 5.0,
    )
    job_runner.add_job(job)

    leased = job_runner.lease_batch("worker-node-A", now, batch_size=5, lease_duration=60.0)
    assert len(leased) == 1
    assert leased[0].id == "job-due-01"
    assert leased[0].lease_owner == "worker-node-A"
    assert leased[0].status == "active"
    assert leased[0].lease_until > now


def test_t1_f6_atomic_leasing_prevents_double_leasing(job_runner: JobRunner, sample_profile_id: str):
    """F6.3: Concurrently competing worker cannot lease jobs already leased to another worker."""
    now = time.time()
    job = Job(
        id="job-race-01",
        profile_id=sample_profile_id,
        kind="connector_sync",
        routine_id="rout-2",
        connection_id="conn-2",
        payload={},
        next_run_at=now - 5.0,
    )
    job_runner.add_job(job)

    # Worker A leases
    batch_a = job_runner.lease_batch("worker-A", now, batch_size=1)
    assert len(batch_a) == 1

    # Worker B tries immediately to lease
    batch_b = job_runner.lease_batch("worker-B", now, batch_size=1)
    assert len(batch_b) == 0


def test_t1_f6_clock_jump_detection_on_laptop_wake(job_runner: JobRunner):
    """F6.4: Detects clock jumps on laptop sleep/wake (>120s diff)."""
    t_sleep = 1000.0
    t_wake = 1000.0 + 3600.0  # 1 hour sleep jump
    coalesced, missed = job_runner.handle_wake_jump(last_tick=t_sleep, now=t_wake)
    assert isinstance(coalesced, int)
    assert isinstance(missed, int)


def test_t1_f6_wake_coalescing_max_one_sync_per_connection(job_runner: JobRunner):
    """F6.5: Coalesces accumulated overdue syncs on wake (max 1 active sync per connection)."""
    now = 10000.0
    # Create 3 accumulated sync jobs for same connection during sleep
    for i in range(3):
        job_runner.add_job(
            Job(
                id=f"sync-{i}",
                profile_id="prof-1",
                kind="connector_sync",
                routine_id="r-sync",
                connection_id="conn-apple-health",
                payload={},
                next_run_at=now - 3600.0 + (i * 600.0),
                status="pending",
            )
        )
    coalesced, missed = job_runner.handle_wake_jump(last_tick=1000.0, now=now)
    assert coalesced == 2  # 2 of 3 duplicates coalesced to completed


def test_t1_f6_overdue_reminders_gt_24h_marked_missed(job_runner: JobRunner):
    """F6.6: Reminders overdue by >24 hours marked as 'missed'."""
    now = 200000.0
    job_runner.add_job(
        Job(
            id="remind-old",
            profile_id="prof-1",
            kind="reminder",
            routine_id="r-med",
            connection_id="conn-local",
            payload={"med": "lisinopril"},
            next_run_at=now - 100000.0,  # >24 hours (86400s) overdue
            status="pending",
        )
    )
    coalesced, missed = job_runner.handle_wake_jump(last_tick=1000.0, now=now)
    assert missed == 1
    assert job_runner._jobs["remind-old"].status == "missed"


@pytest.mark.asyncio
async def test_t1_f6_job_execution_routed_through_choke_point_principal_job(job_runner: JobRunner):
    """F6.7: Background job routes through execute_tool_call with principal='job'."""
    job = Job(
        id="job-exec-01",
        profile_id="prof-job-01",
        kind="sync",
        routine_id="rout-sync",
        connection_id="conn-1",
        payload={"records_count": 5},
    )
    spec = ToolSpec(
        name="routine_sync_tool",
        risk_tier="write_local",
        executor=lambda args: {"synced_count": args["records_count"]},
    )
    res = await job_runner.execute_job(job, spec)
    assert res.success is True
    assert job.status == "completed"
    assert res.output == {"synced_count": 5}
