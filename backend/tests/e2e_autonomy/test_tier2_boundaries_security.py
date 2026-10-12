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

"""Tier 2: Boundary & Corner Cases — Adversarial, Fail-Closed & Tamper Detection.

Verifies boundary conditions, fail-closed security invariants, tamper detection,
injection defense, and error cascades across all 6 Autonomy features.
"""

from __future__ import annotations

import os
import time
from typing import Dict
import pytest

from tests.e2e_autonomy.contracts import (
    ApprovalStore,
    DecryptionError,
    Job,
    JobRunner,
    TaintFlag,
    ToolContext,
    ToolSpec,
    ToolSpecRegistry,
    VaultLockedError,
    compute_aad_binding,
    compute_payload_hash,
    decrypt,
    derive_argon2id_kek,
    encrypt,
    evaluate_policy_gate,
    execute_tool_call,
    resolve_kek,
)


# ============================================================================
# Feature 1 Boundaries: Keyring Vault Crypto & Hierarchy
# ============================================================================

def test_t2_f1_bit_flipped_ciphertext_raises_decryption_error(sample_kek: bytes):
    """F1.B1: Tampered ciphertext (single bit flipped) triggers tag validation failure."""
    aad = b"prof-1|conn-1|1"
    ct = encrypt(sample_kek, b"secret_data", aad)

    # Flip single byte in the middle of ciphertext
    tampered = bytearray(ct)
    tampered[15] ^= 0x01

    with pytest.raises(DecryptionError, match="tag verification failed|AAD mismatch"):
        decrypt(sample_kek, bytes(tampered), aad)


def test_t2_f1_truncated_ciphertext_rejected(sample_kek: bytes):
    """F1.B2: Ciphertext shorter than minimum 28 bytes (12-byte nonce + 16-byte tag) rejected."""
    with pytest.raises(DecryptionError, match="too short"):
        decrypt(sample_kek, b"short_bytes_123", b"aad")


def test_t2_f1_aad_tampered_profile_id_rejected(sample_kek: bytes):
    """F1.B3: Ciphertext relocation across profiles prevented by AAD binding."""
    aad_prof_1 = compute_aad_binding("prof-patient-1", "conn-1", 1)
    aad_prof_2 = compute_aad_binding("prof-patient-2", "conn-1", 1)

    ct = encrypt(sample_kek, b"patient_1_records", aad_prof_1)

    # Attempting to decrypt under profile 2's AAD fails closed
    with pytest.raises(DecryptionError):
        decrypt(sample_kek, ct, aad_prof_2)


def test_t2_f1_aad_tampered_connection_id_rejected(sample_kek: bytes):
    """F1.B4: Ciphertext relocation across connections prevented by AAD binding."""
    aad_conn_1 = compute_aad_binding("prof-1", "conn-epic", 1)
    aad_conn_2 = compute_aad_binding("prof-1", "conn-cerner", 1)

    ct = encrypt(sample_kek, b"token", aad_conn_1)
    with pytest.raises(DecryptionError):
        decrypt(sample_kek, ct, aad_conn_2)


def test_t2_f1_aad_tampered_dek_version_rejected(sample_kek: bytes):
    """F1.B5: Mismatched DEK version in AAD prevents stale key replay."""
    aad_v1 = compute_aad_binding("prof-1", "conn-1", 1)
    aad_v2 = compute_aad_binding("prof-1", "conn-1", 2)

    ct = encrypt(sample_kek, b"token", aad_v1)
    with pytest.raises(DecryptionError):
        decrypt(sample_kek, ct, aad_v2)


def test_t2_f1_empty_or_whitespace_passphrase_raises_vault_locked():
    """F1.B6: Empty, whitespace-only, or missing passphrase fails closed."""
    with pytest.raises(VaultLockedError, match="Passphrase cannot be empty"):
        derive_argon2id_kek("")

    with pytest.raises(VaultLockedError, match="Passphrase cannot be empty"):
        derive_argon2id_kek("   ")


def test_t2_f1_missing_kek_file_raises_vault_locked():
    """F1.B7: Non-existent secret file path raises VaultLockedError."""
    with pytest.raises(VaultLockedError):
        resolve_kek(mode="server", kek_file_path="/tmp/non_existent_carefold_kek.secret")


def test_t2_f1_empty_keyring_value_raises_vault_locked():
    """F1.B8: Empty or whitespace-only OS keychain entry raises VaultLockedError."""
    with pytest.raises(VaultLockedError):
        resolve_kek(mode="local", keyring_store={"carefold_kek": "   "})


# ============================================================================
# Feature 2 Boundaries: ToolSpec Registry & Profile Filtering
# ============================================================================

def test_t2_f2_unknown_tool_returns_none(tool_registry: ToolSpecRegistry):
    """F2.B1: Querying for unmanifested tool returns None without exception."""
    assert tool_registry.get("non_existent_clinical_tool_xyz") is None


def test_t2_f2_tool_with_empty_parameters_registers_cleanly(tool_registry: ToolSpecRegistry):
    """F2.B2: ToolSpec with empty parameters dict registers and executes."""
    spec = ToolSpec(name="ping_agent", description="Health check", parameters={}, risk_tier="read")
    tool_registry.register(spec)
    assert tool_registry.get("ping_agent") is not None


def test_t2_f2_child_under_13_explicit_false_vs_none_consent():
    """F2.B3: Child under 13 with explicit False guardian consent strictly blocks write_local."""
    reg = ToolSpecRegistry()
    reg.register(ToolSpec("save_log", "", {}, risk_tier="write_local"))

    # Explicit False
    t_false = reg.list_for_profile("p1", consents={"guardian_consent": False}, age_band="child_under_13")
    assert len(t_false) == 0

    # None consent dict
    t_none = reg.list_for_profile("p1", consents=None, age_band="child_under_13")
    assert len(t_none) == 0


def test_t2_f2_empty_age_band_defaults_to_adult(tool_registry: ToolSpecRegistry):
    """F2.B4: Empty string or adult age band retains full tools list."""
    tools_empty = tool_registry.list_for_profile("p1", age_band="")
    tools_adult = tool_registry.list_for_profile("p1", age_band="adult")
    assert len(tools_empty) == len(tools_adult)


def test_t2_f2_duplicate_tool_registration_overwrites_cleanly(tool_registry: ToolSpecRegistry):
    """F2.B5: Re-registering tool cleanly updates specification without registry pollution."""
    s1 = ToolSpec("vitals_tool", "v1", {}, risk_tier="read")
    s2 = ToolSpec("vitals_tool", "v2 updated", {}, risk_tier="write_local")
    tool_registry.register(s1)
    assert tool_registry.get("vitals_tool").description == "v1"
    tool_registry.register(s2)
    assert tool_registry.get("vitals_tool").description == "v2 updated"
    assert tool_registry.get("vitals_tool").risk_tier == "write_local"


# ============================================================================
# Feature 3 Boundaries: Policy Gate & Choke Point Invariants
# ============================================================================

def test_t2_f3_empty_args_dict_evaluates_policy_cleanly(make_context):
    """F3.B1: Empty args dict evaluates policy without KeyError or crash."""
    ctx = make_context(autonomy="A1")
    spec = ToolSpec("read_all", "", {}, risk_tier="read")
    decision = evaluate_policy_gate(ctx, spec, {})
    assert decision.decision == "allow"


def test_t2_f3_nested_args_with_special_characters_deterministic_hash():
    """F3.B2: Deeply nested dict with unicode, punctuation, and emojis computes stable hash."""
    args = {
        "notes": "Patient reports severe migraine (10/10) with photophobia 🚨 & nausea.",
        "metadata": {
            "tags": ["urgent", "triage", "<script>alert('xss')</script>"],
            "vitals": {"bp": "140/90", "hr": 88},
        },
    }
    h1 = compute_payload_hash(args)
    h2 = compute_payload_hash(args)
    assert h1 == h2
    assert len(h1) == 64


def test_t2_f3_whitespace_only_profile_or_user_fails_closed():
    """F3.B3: Whitespace-only profile_id or user_id in ToolContext raises ValueError."""
    with pytest.raises(ValueError, match="non-empty profile_id"):
        ToolContext(user_id="user-valid", profile_id="   ")

    with pytest.raises(ValueError, match="non-empty user_id"):
        ToolContext(user_id="   ", profile_id="prof-valid")


@pytest.mark.asyncio
async def test_t2_f3_choke_point_catches_crashing_tool_executor(make_context):
    """F3.B4: Choke point captures unexpected tool exception and returns ToolResult(success=False)."""
    ctx = make_context(autonomy="A1")

    def _exploding_executor(args):
        raise ZeroDivisionError("Simulated unhandled runtime crash")

    spec = ToolSpec("exploding_tool", "", {}, risk_tier="read", executor=_exploding_executor)
    res = await execute_tool_call(ctx, spec, {})
    assert res.success is False
    assert "Tool execution failed" in (res.error or "")
    assert "ZeroDivisionError" in (res.error or "")


# ============================================================================
# Feature 4 Boundaries: HITL Approvals Engine
# ============================================================================

def test_t2_f4_replay_attack_on_consumed_approval_rejected(approval_store: ApprovalStore):
    """F4.B1: Replay attack: attempting to re-consume an already consumed approval fails closed."""
    args = {"action": "book_appointment"}
    rec = approval_store.create_pending("app-replay", "prof-1", "run-1", "tool-1", args, "write_external")
    approval_store.decide("app-replay", "prof-1", "approved", None, "u1", ["manage"])

    # First consume succeeds
    c1 = approval_store.consume_atomic("app-replay", args)
    assert c1 == "app-replay"

    # Second consume attempt rejected
    with pytest.raises(ValueError, match="status 'consumed'"):
        approval_store.consume_atomic("app-replay", args)


def test_t2_f4_cross_profile_approval_decide_rejected(approval_store: ApprovalStore):
    """F4.B2: Caller cannot decide an approval belonging to a different profile."""
    approval_store.create_pending("app-prof-a", "prof-A", "run-1", "t1", {}, "write_external")

    # Mismatched profile_id raises KeyError
    with pytest.raises(KeyError, match="not found"):
        approval_store.decide("app-prof-a", "prof-B", "approved", None, "u1", ["manage"])


def test_t2_f4_expired_approval_cannot_be_consumed(approval_store: ApprovalStore):
    """F4.B3: Expired approval record fails closed upon consume attempt."""
    args = {"action": "export"}
    rec = approval_store.create_pending("app-exp", "prof-1", "run-1", "t1", args, "write_external")
    approval_store.decide("app-exp", "prof-1", "approved", None, "u1", ["manage"])

    # Force expiration
    rec.expires_at = time.time() - 10.0

    with pytest.raises(ValueError, match="expired"):
        approval_store.consume_atomic("app-exp", args)


def test_t2_f4_tampered_args_at_resume_fails_payload_hash_check(approval_store: ApprovalStore):
    """F4.B4: Resuming with tampered arguments mismatches payload hash and fails closed."""
    orig_args = {"recipient": "doctor@hospital.org", "dosage": "10mg"}
    tampered_args = {"recipient": "attacker@evil.org", "dosage": "10mg"}

    approval_store.create_pending("app-tamper", "prof-1", "run-1", "t1", orig_args, "write_external")
    approval_store.decide("app-tamper", "prof-1", "approved", None, "u1", ["manage"])

    with pytest.raises(ValueError, match="Payload hash mismatch"):
        approval_store.consume_atomic("app-tamper", tampered_args)


def test_t2_f4_attempt_to_decide_already_decided_approval_fails(approval_store: ApprovalStore):
    """F4.B5: Deciding an approval that is already approved or rejected fails."""
    approval_store.create_pending("app-double", "prof-1", "run-1", "t1", {}, "write_external")
    approval_store.decide("app-double", "prof-1", "approved", None, "u1", ["manage"])

    with pytest.raises(ValueError, match="cannot be decided from status 'approved'"):
        approval_store.decide("app-double", "prof-1", "rejected", None, "u1", ["manage"])


def test_t2_f4_non_manager_cannot_decide_approvals(approval_store: ApprovalStore):
    """F4.B6: Caller lacking 'manage' permission receives PermissionError on decide."""
    approval_store.create_pending("app-perm", "prof-1", "run-1", "t1", {}, "write_external")

    with pytest.raises(PermissionError, match="'manage' permission"):
        approval_store.decide("app-perm", "prof-1", "approved", None, "u1", caller_permissions=["view", "edit"])


# ============================================================================
# Feature 5 Boundaries: Monotone Taint & Egress Firewall
# ============================================================================

@pytest.mark.asyncio
async def test_t2_f5_egress_url_with_port_and_query_param_extracts_clean_host(make_context):
    """F5.B1: Destination URL with port, path, and query params extracts host accurately."""
    ctx = make_context(autonomy="A2")
    spec = ToolSpec(
        name="fhir_connector",
        risk_tier="write_external",
        data_flows=("fhir.hospital.org",),
        executor=lambda args: {"synced": True},
    )
    # Valid allowlisted host with port and complex query string
    res = await execute_tool_call(
        ctx,
        spec,
        {"url": "https://fhir.hospital.org:8443/Observation?patient=101&_format=json"},
        consents={"external_write_consent": True},
    )
    assert res.success is True


@pytest.mark.asyncio
async def test_t2_f5_ip_address_egress_blocked_without_explicit_allowlist(make_context):
    """F5.B2: Cloud metadata or LAN IP address destination blocked without allowlist."""
    ctx = make_context(autonomy="A2")
    spec = ToolSpec(
        name="meta_exfil",
        risk_tier="write_external",
        data_flows=("authorized.api.org",),
    )
    # AWS metadata IP
    res = await execute_tool_call(ctx, spec, {"url": "http://169.254.169.254/latest/meta-data"})
    assert res.success is False
    assert "EgressBlockedError" in (res.error or "")


@pytest.mark.asyncio
async def test_t2_f5_subdomain_spoofing_attack_blocked(make_context):
    """F5.B3: Attacker appending allowed domain as prefix to their subdomain is blocked."""
    ctx = make_context(autonomy="A2")
    spec = ToolSpec(
        name="ehr_export",
        risk_tier="write_external",
        data_flows=("epic-fhir.hospital.org",),
    )
    # Malicious domain ending in .evil.com
    res = await execute_tool_call(ctx, spec, {"url": "https://epic-fhir.hospital.org.evil.com/exfil"})
    assert res.success is False
    assert "EgressBlockedError" in (res.error or "")


@pytest.mark.asyncio
async def test_t2_f5_monotone_taint_persists_across_multiple_tool_calls(make_context):
    """F5.B4: Taint flag remains set across multiple subsequent read and write tool calls."""
    ctx = make_context(autonomy="A1", tainted=False)
    assert not ctx.taint.is_tainted

    # Step 1: Untrusted tool call taints context
    t_untrusted = ToolSpec("scrape_forum", "", {}, risk_tier="read", trust="untrusted")
    await execute_tool_call(ctx, t_untrusted, {})
    assert ctx.taint.is_tainted is True

    # Step 2: Next trusted read call executes; context remains tainted
    t_trusted_read = ToolSpec("read_profile", "", {}, risk_tier="read", trust="trusted")
    await execute_tool_call(ctx, t_trusted_read, {})
    assert ctx.taint.is_tainted is True

    # Step 3: Subsequent write_external forces approval due to sticky taint
    t_wext = ToolSpec("send_sms", "", {}, risk_tier="write_external")
    d = evaluate_policy_gate(ctx, t_wext, {})
    assert d.decision == "needs_approval"


# ============================================================================
# Feature 6 Boundaries: Wall-Clock Job Runner
# ============================================================================

def test_t2_f6_expired_lease_acquired_by_new_worker(job_runner: JobRunner):
    """F6.B1: Expired lease (>lease_duration) successfully taken over by another worker."""
    now = 5000.0
    job = Job(
        id="job-exp-lease",
        profile_id="prof-1",
        kind="sync",
        routine_id="r1",
        connection_id="c1",
        payload={},
        next_run_at=now - 100.0,
        lease_owner="worker-dead",
        lease_until=now - 10.0,  # Expired lease
        status="active",
    )
    job._jobs = {"job-exp-lease": job}
    # Reset status to pending to simulate expired lease sweep
    job.status = "pending"
    job_runner.add_job(job)

    leased = job_runner.lease_batch("worker-alive", now, batch_size=1)
    assert len(leased) == 1
    assert leased[0].lease_owner == "worker-alive"


def test_t2_f6_zero_batch_size_returns_empty_list(job_runner: JobRunner):
    """F6.B2: Leasing with batch_size=0 returns empty list without error."""
    job_runner.add_job(Job("j1", "p1", "kind", "r1", "c1", {}, next_run_at=100.0, status="pending"))
    leased = job_runner.lease_batch("worker-1", now=200.0, batch_size=0)
    assert leased == []


def test_t2_f6_clock_moving_backwards_handled_gracefully(job_runner: JobRunner):
    """F6.B3: Negative time jump (NTP clock slew backwards) handled without crash."""
    coalesced, missed = job_runner.handle_wake_jump(last_tick=5000.0, now=4900.0)
    assert coalesced == 0
    assert missed == 0


@pytest.mark.asyncio
async def test_t2_f6_failing_job_increments_attempts(job_runner: JobRunner):
    """F6.B4: Failed job execution increments attempts counter and marks status='failed'."""
    job = Job(
        id="job-fail-01",
        profile_id="prof-1",
        kind="sync",
        routine_id="r1",
        connection_id="c1",
        payload={"url": "http://blocked.com"},
        attempts=0,
    )
    spec = ToolSpec(
        name="crashing_tool",
        risk_tier="write_external",
        data_flows=("allowed.com",),  # blocked.com triggers EgressBlockedError
    )
    res = await job_runner.execute_job(job, spec)
    assert res.success is False
    assert job.status == "failed"
    assert job.attempts == 1
