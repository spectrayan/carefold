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

"""Tier 3: Cross-Feature Combinations — Pairwise Interactions.

Tests pairwise feature interactions across Keyring Vault, ToolSpec Registry,
Policy Gate, HITL Approvals, Monotone Taint, and Wall-Clock Job Runner.
"""

from __future__ import annotations

import time
from typing import Dict
import pytest

from tests.e2e_autonomy.contracts import (
    ApprovalStore,
    DecryptionError,
    InMemoryProfileKeyStore,
    Job,
    JobRunner,
    ToolContext,
    ToolSpec,
    ToolSpecRegistry,
    UntrustedResult,
    compute_aad_binding,
    compute_payload_hash,
    decrypt,
    derive_argon2id_kek,
    encrypt,
    evaluate_policy_gate,
    execute_tool_call,
)


@pytest.mark.asyncio
async def test_t3_pairwise_vault_dek_and_choke_point_execution(
    make_context,
    profile_key_store: InMemoryProfileKeyStore,
    sample_kek: bytes,
    sample_profile_id: str,
    sample_connection_id: str,
):
    """Pairwise 1: Vault DEK + Choke Point Execution (F1 x F3).

    Encrypted connector token decrypted at runtime and passed through choke point.
    """
    ctx = make_context(profile_id=sample_profile_id, autonomy="A1")
    dek, ver = profile_key_store.get_or_create_dek(sample_profile_id, sample_kek)
    aad = compute_aad_binding(sample_profile_id, sample_connection_id, ver)

    token_plaintext = b"bearer_oauth_token_quest_diagnostics"
    encrypted_token = encrypt(dek, token_plaintext, aad)

    # Tool executor that decrypts token in sandbox
    def _fetch_records(args):
        decrypted_auth = decrypt(dek, args["enc_token"], aad)
        return {"records": ["CBC", "Lipid Panel"], "auth_len": len(decrypted_auth)}

    spec = ToolSpec("fetch_lab_results", "", {}, risk_tier="read", executor=_fetch_records)
    res = await execute_tool_call(ctx, spec, {"enc_token": encrypted_token})

    assert res.success is True
    assert res.output["records"] == ["CBC", "Lipid Panel"]
    assert res.output["auth_len"] == len(token_plaintext)


@pytest.mark.asyncio
async def test_t3_pairwise_policy_gate_and_hitl_approval_lifecycle(
    make_context,
    approval_store: ApprovalStore,
    sample_profile_id: str,
):
    """Pairwise 2: Policy Gate + HITL Approvals Engine (F3 x F4).

    Policy gate halts on needs_approval -> pending approval -> admin approved -> atomic resume.
    """
    ctx = make_context(profile_id=sample_profile_id, autonomy="A1")
    spec = ToolSpec(
        name="send_physician_referral",
        risk_tier="write_external",
        data_flows=("referrals.hospital.org",),
        executor=lambda args: {"referral_id": "REF-7711", "status": "sent"},
    )
    args = {"url": "https://referrals.hospital.org/submit", "specialty": "Cardiology"}

    # 1. Execute triggers approval requirement
    res1 = await execute_tool_call(ctx, spec, args, approval_store=approval_store)
    assert res1.needs_approval is True
    app_id = res1.approval_id

    # 2. Manager reviews pending approvals
    pending = approval_store.list_pending(sample_profile_id, caller_permissions=["manage"])
    assert any(r.id == app_id for r in pending)

    # 3. Manager approves
    approval_store.decide(app_id, sample_profile_id, "approved", None, "admin-1", ["manage"])

    # 4. Resume tool execution
    res2 = await execute_tool_call(
        ctx, spec, args, approval_store=approval_store, approval_id=app_id
    )
    assert res2.success is True
    assert res2.output["referral_id"] == "REF-7711"


@pytest.mark.asyncio
async def test_t3_pairwise_monotone_taint_and_policy_gate_escalation(make_context):
    """Pairwise 3: Monotone Taint + Policy Gate Escalation (F5 x F3).

    Untrusted tool output taints context; external write that was allowed in A2 now forced into approval.
    """
    ctx = make_context(autonomy="A2", tainted=False)
    consents = {"external_write_consent": True}

    t_untrusted = ToolSpec(
        name="web_search_symptoms",
        risk_tier="read",
        trust="untrusted",
        executor=lambda args: UntrustedResult(data="Public medical forum comments"),
    )
    t_export = ToolSpec(
        name="export_care_plan",
        risk_tier="write_external",
        data_flows=("careplans.org",),
        executor=lambda args: {"exported": True},
    )

    # Before taint: A2 with consent is allowed
    assert evaluate_policy_gate(ctx, t_export, {}, consents=consents).decision == "allow"

    # Step 1: Run untrusted tool -> taints context
    res1 = await execute_tool_call(ctx, t_untrusted, {"q": "angina"})
    assert res1.success is True
    assert ctx.taint.is_tainted is True

    # Step 2: Policy gate on export now escalates to needs_approval
    decision_after = evaluate_policy_gate(ctx, t_export, {}, consents=consents)
    assert decision_after.decision == "needs_approval"
    assert "FORCED APPROVAL" in decision_after.reason


@pytest.mark.asyncio
async def test_t3_pairwise_job_runner_and_policy_choke_point(
    job_runner: JobRunner,
    sample_profile_id: str,
):
    """Pairwise 4: Job Runner + Choke Point Execution (F6 x F3).

    Background worker executes routine sync through choke point with principal='job'.
    """
    job = Job(
        id="job-nightly-01",
        profile_id=sample_profile_id,
        kind="connector_sync",
        routine_id="r-nightly",
        connection_id="c-fitbit",
        payload={"url": "https://api.fitbit.com/sync", "days": 1},
    )
    job_runner.add_job(job)

    spec = ToolSpec(
        name="fitbit_sync",
        risk_tier="write_local",
        data_flows=("api.fitbit.com",),
        executor=lambda args: {"synced_steps": 8500},
    )

    res = await job_runner.execute_job(job, spec)
    assert res.success is True
    assert job.status == "completed"
    assert res.output["synced_steps"] == 8500


@pytest.mark.asyncio
async def test_t3_pairwise_hitl_approval_editing_and_hash_enforcement(
    make_context,
    approval_store: ApprovalStore,
    sample_profile_id: str,
):
    """Pairwise 5: HITL Approvals Argument Editing + Payload Hash Verification (F4 x F3).

    Reviewer modifies arguments during approval; resume requires matching edited arguments.
    """
    ctx = make_context(profile_id=sample_profile_id, autonomy="A1")
    spec = ToolSpec(
        name="adjust_medication_reminder",
        risk_tier="write_external",
        data_flows=("reminders.corp.com",),
        executor=lambda args: {"applied_dose": args["dosage"]},
    )
    orig_args = {"url": "https://reminders.corp.com", "dosage": "40mg"}
    edited_args = {"url": "https://reminders.corp.com", "dosage": "20mg"}

    # Step 1: Tool call halts
    res1 = await execute_tool_call(ctx, spec, orig_args, approval_store=approval_store)
    app_id = res1.approval_id

    # Step 2: Doctor modifies dose to 20mg and approves
    approval_store.decide(
        app_id, sample_profile_id, "approved", edited_args=edited_args, caller_id="dr-smith", caller_permissions=["manage"]
    )

    # Step 3: Attempting to resume with old 40mg args fails closed
    res_bad = await execute_tool_call(
        ctx, spec, orig_args, approval_store=approval_store, approval_id=app_id
    )
    assert res_bad.success is False
    assert "Payload hash mismatch" in (res_bad.error or "")

    # Step 4: Resuming with approved 20mg args succeeds
    res_ok = await execute_tool_call(
        ctx, spec, edited_args, approval_store=approval_store, approval_id=app_id
    )
    assert res_ok.success is True
    assert res_ok.output["applied_dose"] == "20mg"


def test_t3_pairwise_child_profile_and_egress_firewall():
    """Pairwise 6: Child Profile Age Band + Egress Firewall (F2 x F5).

    Child under 13 profile blocks external writes even if destination is allowlisted.
    """
    reg = ToolSpecRegistry()
    t_wext = ToolSpec("portal_share", "", {}, risk_tier="write_external", data_flows=("safe-portal.org",))
    reg.register(t_wext)

    # Child under 13 cannot see or execute write_external
    tools = reg.list_for_profile("p-child", age_band="child_under_13")
    assert len(tools) == 0


def test_t3_pairwise_crypto_shredding_and_job_execution(
    profile_key_store: InMemoryProfileKeyStore,
    sample_kek: bytes,
    sample_profile_id: str,
    sample_connection_id: str,
):
    """Pairwise 7: Crypto-Shredding + Job Execution (F1 x F6).

    Deleting profile drops DEK; background job attempting decryption fails closed.
    """
    dek, ver = profile_key_store.get_or_create_dek(sample_profile_id, sample_kek)
    aad = compute_aad_binding(sample_profile_id, sample_connection_id, ver)
    encrypted_secret = encrypt(dek, b"confidential_ehr_cache", aad)

    # Profile deleted
    profile_key_store.delete_profile_keys(sample_profile_id)

    # Background worker attempts decrypt with freshly generated DEK
    new_dek, _ = profile_key_store.get_or_create_dek(sample_profile_id, sample_kek)
    with pytest.raises(DecryptionError):
        decrypt(new_dek, encrypted_secret, aad)


def test_t3_pairwise_atomic_resume_single_use_replay_prevention(approval_store: ApprovalStore):
    """Pairwise 8: Atomic Resume Replay Prevention Across Sessions (F4 x F4).

    Consumed approval cannot be re-consumed under any circumstances.
    """
    args = {"cmd": "execute"}
    rec = approval_store.create_pending("app-single-use", "prof-1", "run-1", "t1", args, "write_external")
    approval_store.decide("app-single-use", "prof-1", "approved", None, "admin", ["manage"])

    first_consume = approval_store.consume_atomic("app-single-use", args)
    assert first_consume == "app-single-use"

    # Concurrent / second replay attempt
    with pytest.raises(ValueError, match="status 'consumed'"):
        approval_store.consume_atomic("app-single-use", args)


@pytest.mark.asyncio
async def test_t3_pairwise_wall_clock_sleep_wake_and_execution(job_runner: JobRunner):
    """Pairwise 9: Wall-Clock Sleep/Wake Jump + Choke Point Execution (F6 x F3).

    Laptop sleep triggers coalescing, surviving sync executes cleanly.
    """
    now = 50000.0
    for i in range(2):
        job_runner.add_job(
            Job(
                id=f"job-sync-{i}",
                profile_id="prof-1",
                kind="connector_sync",
                routine_id="r-sync",
                connection_id="conn-apple",
                payload={"data": "steps"},
                next_run_at=now - 500.0,
            )
        )

    # Sleep jump: 1000s -> 50000s
    coalesced, _ = job_runner.handle_wake_jump(last_tick=1000.0, now=now)
    assert coalesced == 1

    # Lease surviving job
    leased = job_runner.lease_batch("worker-1", now=now, batch_size=5)
    assert len(leased) == 1

    # Execute surviving job
    spec = ToolSpec("apple_sync", risk_tier="write_local", executor=lambda args: {"synced": True})
    res = await job_runner.execute_job(leased[0], spec)
    assert res.success is True
    assert leased[0].status == "completed"


@pytest.mark.asyncio
async def test_t3_pairwise_monotone_taint_pipeline_propagation(make_context):
    """Pairwise 10: Monotone Taint Across Multiple Pipeline Steps (F5 x F2).

    3-step pipeline: Ingestion (untrusted) -> Local Transform (write_local) -> Export (write_external).
    """
    ctx = make_context(autonomy="A2", tainted=False)
    consents = {"external_write_consent": True}

    t1_ingest = ToolSpec("scrape_external_ehr", "", {}, risk_tier="read", trust="untrusted")
    t2_transform = ToolSpec("save_note", "", {}, risk_tier="write_local")
    t3_export = ToolSpec("push_cloud", "", {}, risk_tier="write_external")

    # Step 1: Ingest untrusted data -> taints context
    await execute_tool_call(ctx, t1_ingest, {})
    assert ctx.taint.is_tainted is True

    # Step 2: Local write permitted
    decision_t2 = evaluate_policy_gate(ctx, t2_transform, {}, consents=consents)
    assert decision_t2.decision == "allow"

    # Step 3: Export forces approval because taint is sticky
    decision_t3 = evaluate_policy_gate(ctx, t3_export, {}, consents=consents)
    assert decision_t3.decision == "needs_approval"


def test_t3_pairwise_argon2id_kek_derivation_and_vault_decryption():
    """Pairwise 11: Vault KEK Hierarchy Fallback + DEK Decryption (F1 x F1).

    Argon2id passphrase derived KEK cleanly decrypts DEK created earlier.
    """
    passphrase = "Spector-Argon2id-Vault-Secret-2026!"
    kek_1 = derive_argon2id_kek(passphrase)

    store = InMemoryProfileKeyStore()
    dek, ver = store.get_or_create_dek("prof-argon", kek_1)

    # Derive same KEK in a new session from same passphrase
    kek_2 = derive_argon2id_kek(passphrase)
    assert kek_1 == kek_2

    # Fetch and decrypt DEK
    recovered_dek, rec_ver = store.get_or_create_dek("prof-argon", kek_2)
    assert recovered_dek == dek
    assert rec_ver == ver


@pytest.mark.asyncio
async def test_t3_pairwise_toolspec_profile_filtering_and_policy_choke_point(make_context):
    """Pairwise 12: ToolSpec Profile Filtering + Policy Gate Choke Point (F2 x F3).

    Child profile blocks write_external at policy gate with clear policy reason.
    """
    ctx = make_context(autonomy="A2")
    spec = ToolSpec("external_portal_blast", "", {}, risk_tier="write_external")

    decision = evaluate_policy_gate(ctx, spec, {}, age_band="child_under_13")
    assert decision.decision == "blocked"
    assert "Child under 13" in decision.reason
