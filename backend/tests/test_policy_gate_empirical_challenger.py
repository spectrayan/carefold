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

"""Adversarial empirical challenge test harness for Carefold Policy Gate & Monotone Taint (AU-17, AU-19).

Challenger Mission:
1. Adversarially challenge monotone taint:
   - Verify TaintFlag has ZERO reset or clear methods (reflection & AST inspection).
   - Test that tainted context forces approval on all write_external tool calls,
     regardless of autonomy level (even A2) and consent.
   - Verify that once tainted, sequential tool executions remain tainted across multi-step chains.
2. Adversarially challenge child under 13 boundary:
   - Test that write_external is unconditionally blocked for child_under_13 across all autonomies,
     consents, and taint states.
   - Test that unconsented write_local requires guardian approval.
3. Stress-test choke point fail-closed invariants and Egress firewall anti-bypass.
"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
import inspect
import pytest
from typing import Any, Dict, List, Mapping, Optional

from carefold.engine.tool_exec import (
    EgressBlockedError,
    PolicyDecision,
    RiskTier,
    TaintFlag,
    ToolContext,
    ToolResult,
    ToolSpec,
    UntrustedResult,
    canonical_json,
    compute_payload_hash,
    evaluate_policy_gate,
    execute_tool_call,
)
from carefold.engine.tool_registry import DataFlows


# ============================================================================
# Section 1: Monotone Taint Adversarial Challenges (AU-19)
# ============================================================================

class TestMonotoneTaintAdversarialChallenges:
    """Rigorous stress-testing of TaintFlag and monotone taint propagation."""

    def test_taint_flag_has_zero_reset_or_clear_methods(self):
        """Reflection audit: TaintFlag must have ZERO reset, clear, revert, or unset methods."""
        flag = TaintFlag(initial=False)

        forbidden_substrings = [
            "clear",
            "reset",
            "revert",
            "unset",
            "untaint",
            "clean",
            "false",
            "toggle",
            "delete",
            "drop",
            "zero",
        ]

        all_attrs = dir(flag) + dir(TaintFlag)
        for attr in all_attrs:
            attr_lower = attr.lower()
            for forbidden in forbidden_substrings:
                assert forbidden not in attr_lower, (
                    f"Security violation: TaintFlag exposes forbidden attribute or method '{attr}' "
                    f"matching '{forbidden}'."
                )

    def test_taint_flag_set_rejects_arguments(self):
        """Calling flag.set(False) or flag.set(0) must raise TypeError (set takes 0 positional args)."""
        flag = TaintFlag(initial=False)
        with pytest.raises(TypeError):
            flag.set(False)  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            flag.set(True)  # type: ignore[call-arg]

    def test_taint_flag_idempotent_monotonicity_under_rapid_calls(self):
        """Calling set() repeatedly retains True; bool() and is_tainted stay True."""
        flag = TaintFlag(initial=False)
        assert flag.is_tainted is False
        assert bool(flag) is False

        for _ in range(50):
            flag.set()
            assert flag.is_tainted is True
            assert bool(flag) is True

    def test_tool_context_is_frozen_preventing_taint_flag_replacement(self):
        """ToolContext is immutable; adversarial attempts to replace ctx.taint raise FrozenInstanceError."""
        flag = TaintFlag(initial=True)
        ctx = ToolContext(
            user_id="usr-adv-1",
            profile_id="prof-adv-1",
            autonomy="A2",
            taint=flag,
        )

        with pytest.raises(FrozenInstanceError):
            ctx.taint = TaintFlag(initial=False)  # type: ignore[misc]

        with pytest.raises(FrozenInstanceError):
            ctx.autonomy = "A2"  # type: ignore[misc]

    @pytest.mark.parametrize("autonomy", ["A0", "A1", "A2", "supervised", "autonomous", "UNKNOWN"])
    @pytest.mark.parametrize(
        "consents",
        [
            None,
            {},
            {"external_write_consent": True},
            {"external_write_consent": False},
            {"guardian_consent": True, "external_write_consent": True},
            {"arbitrary_consent": True},
        ],
    )
    @pytest.mark.parametrize("age_band", ["adult", "teen"])
    def test_tainted_context_forces_approval_on_all_write_external_calls(
        self,
        autonomy: str,
        consents: Optional[Mapping[str, bool]],
        age_band: str,
    ):
        """Tainted context MUST force approval on all write_external calls, overriding A2 and consent."""
        ctx = ToolContext(
            user_id="usr-adv-2",
            profile_id="prof-adv-2",
            autonomy=autonomy,  # type: ignore[arg-type]
            taint=TaintFlag(initial=True),
        )
        spec = ToolSpec(
            name="export_external_data",
            risk_tier="write_external",
            data_flows=("api.healthcare.org",),
        )

        decision = evaluate_policy_gate(
            ctx=ctx,
            spec=spec,
            args={"endpoint": "https://api.healthcare.org/sync"},
            consents=consents,
            age_band=age_band,
        )

        assert decision.decision == "needs_approval", (
            f"Failed for autonomy={autonomy}, consents={consents}, age_band={age_band}: "
            f"expected 'needs_approval', got '{decision.decision}'"
        )
        assert decision.needs_approval is True
        assert decision.allowed is False
        assert "FORCED APPROVAL" in decision.reason or "tainted" in decision.reason.lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("autonomy", ["A0", "A1", "A2"])
    async def test_tainted_context_execute_tool_call_halts_with_needs_approval(self, autonomy: str):
        """In execute_tool_call, a tainted context halts write_external with needs_approval=True."""
        ctx = ToolContext(
            user_id="usr-adv-3",
            profile_id="prof-adv-3",
            autonomy=autonomy,  # type: ignore[arg-type]
            taint=TaintFlag(initial=True),
        )

        executed = False

        def _handler(args):
            nonlocal executed
            executed = True
            return {"synced": True}

        spec = ToolSpec(
            name="sync_calendar_events",
            risk_tier="write_external",
            data_flows=("calendar.google.com",),
            executor=_handler,
        )

        res = await execute_tool_call(
            ctx=ctx,
            spec=spec,
            args={"endpoint": "https://calendar.google.com/event/new"},
            consents={"external_write_consent": True},
        )

        assert res.success is False
        assert res.needs_approval is True
        assert executed is False  # Zero tool handler execution
        assert "ApprovalRequired" in (res.error or "")

    @pytest.mark.asyncio
    async def test_monotone_taint_sequential_persistence_10_step_chain(self):
        """Adversarial 10-step execution chain: taint once set never clears, even across trusted steps."""
        ctx = ToolContext(
            user_id="usr-seq-1",
            profile_id="prof-seq-1",
            autonomy="A2",
            taint=TaintFlag(initial=False),
        )
        consents = {"external_write_consent": True}

        # Step 1: Initial state is clean
        assert ctx.taint.is_tainted is False

        # Step 2: Trusted Read tool -> clean
        spec_read1 = ToolSpec(
            name="trusted_read_1",
            risk_tier="read",
            executor=lambda args: {"records": [1, 2, 3]},
        )
        r1 = await execute_tool_call(ctx, spec_read1, {})
        assert r1.success is True
        assert ctx.taint.is_tainted is False

        # Step 3: Trusted write_local under A2 -> clean
        spec_local1 = ToolSpec(
            name="trusted_local_1",
            risk_tier="write_local",
            executor=lambda args: {"saved": True},
        )
        r2 = await execute_tool_call(ctx, spec_local1, {})
        assert r2.success is True
        assert ctx.taint.is_tainted is False

        # Step 4: Untrusted Read tool (returns UntrustedResult) -> TAINT ACTIVATES
        spec_untrusted = ToolSpec(
            name="untrusted_fetch",
            risk_tier="read",
            executor=lambda args: UntrustedResult(data="Adversarial web page payload", source="web"),
        )
        r3 = await execute_tool_call(ctx, spec_untrusted, {})
        assert r3.success is True
        assert ctx.taint.is_tainted is True

        # Step 5: Subsequent trusted read -> taint remains True
        spec_read2 = ToolSpec(
            name="trusted_read_2",
            risk_tier="read",
            executor=lambda args: {"cached": True},
        )
        r4 = await execute_tool_call(ctx, spec_read2, {})
        assert r4.success is True
        assert ctx.taint.is_tainted is True

        # Step 6: Trusted write_local under A2 -> taint remains True
        r5 = await execute_tool_call(ctx, spec_local1, {})
        assert r5.success is True
        assert ctx.taint.is_tainted is True

        # Step 7: External write with consent under A2 -> FORCED APPROVAL due to taint!
        spec_ext = ToolSpec(
            name="external_push",
            risk_tier="write_external",
            data_flows=("api.partner.org",),
            executor=lambda args: {"pushed": True},
        )
        r6 = await execute_tool_call(
            ctx, spec_ext, {"endpoint": "https://api.partner.org/push"}, consents=consents
        )
        assert r6.success is False
        assert r6.needs_approval is True
        assert ctx.taint.is_tainted is True

        # Step 8: Tool declared with trust="untrusted" -> taint remains True
        spec_untrusted_spec = ToolSpec(
            name="untrusted_spec_tool",
            risk_tier="read",
            trust="untrusted",
            executor=lambda args: {"data": "external note"},
        )
        r7 = await execute_tool_call(ctx, spec_untrusted_spec, {})
        assert r7.success is True
        assert ctx.taint.is_tainted is True

        # Step 9: Tool that throws an exception -> taint remains True
        def _failing_exec(args):
            raise RuntimeError("Explosion inside tool")

        spec_fail = ToolSpec(
            name="exploding_tool",
            risk_tier="read",
            executor=_failing_exec,
        )
        r8 = await execute_tool_call(ctx, spec_fail, {})
        assert r8.success is False
        assert ctx.taint.is_tainted is True

        # Step 10: Final external write attempt under A2 with full consent -> STILL FORCED APPROVAL!
        r9 = await execute_tool_call(
            ctx, spec_ext, {"endpoint": "https://api.partner.org/push"}, consents=consents
        )
        assert r9.success is False
        assert r9.needs_approval is True
        assert ctx.taint.is_tainted is True


# ============================================================================
# Section 2: Child Under 13 Boundary Adversarial Challenges
# ============================================================================

class TestChildUnder13AdversarialChallenges:
    """Stress-testing COPPA and pediatric safety boundaries for child_under_13."""

    @pytest.mark.parametrize("autonomy", ["A0", "A1", "A2", "supervised", "autonomous"])
    @pytest.mark.parametrize("tainted", [False, True])
    @pytest.mark.parametrize(
        "consents",
        [
            None,
            {},
            {"external_write_consent": True},
            {"external_write_consent": False},
            {"guardian_consent": True},
            {"guardian_consent": True, "external_write_consent": True},
            {"bypass_safety": True, "full_access": True},
        ],
    )
    def test_child_under_13_write_external_unconditionally_blocked(
        self,
        autonomy: str,
        tainted: bool,
        consents: Optional[Mapping[str, bool]],
    ):
        """write_external is UNCONDITIONALLY BLOCKED for child_under_13 across all parameters."""
        ctx = ToolContext(
            user_id="usr-child-1",
            profile_id="prof-child-1",
            autonomy=autonomy,  # type: ignore[arg-type]
            taint=TaintFlag(initial=tainted),
        )
        spec = ToolSpec(
            name="send_external_telehealth_message",
            risk_tier="write_external",
            data_flows=("portal.hospital.org",),
        )

        decision = evaluate_policy_gate(
            ctx=ctx,
            spec=spec,
            args={"endpoint": "https://portal.hospital.org/msg"},
            consents=consents,
            age_band="child_under_13",
        )

        assert decision.decision == "blocked", (
            f"Security violation: child_under_13 write_external was not blocked for "
            f"autonomy={autonomy}, tainted={tainted}, consents={consents}."
        )
        assert decision.allowed is False
        assert decision.needs_approval is False
        assert "Child under 13" in decision.reason

    @pytest.mark.asyncio
    @pytest.mark.parametrize("autonomy", ["A0", "A1", "A2"])
    async def test_child_under_13_execute_tool_call_never_executes_external_write(self, autonomy: str):
        """execute_tool_call fails closed with PolicyBlocked; executor is never invoked (0 network bytes)."""
        ctx = ToolContext(
            user_id="usr-child-2",
            profile_id="prof-child-2",
            autonomy=autonomy,  # type: ignore[arg-type]
            taint=TaintFlag(initial=False),
        )

        executed = False

        def _malicious_exfiltration(args):
            nonlocal executed
            executed = True
            return {"sent": True}

        spec = ToolSpec(
            name="external_sync",
            risk_tier="write_external",
            data_flows=("external.cloud.com",),
            executor=_malicious_exfiltration,
        )

        res = await execute_tool_call(
            ctx=ctx,
            spec=spec,
            args={"endpoint": "https://external.cloud.com/push"},
            consents={"external_write_consent": True, "guardian_consent": True},
            age_band="child_under_13",
        )

        assert res.success is False
        assert res.needs_approval is False  # Must NOT be paused for approval; it is BLOCKED outright
        assert executed is False
        assert "PolicyBlocked: Child under 13 external write blocked by policy" in (res.error or "")

    @pytest.mark.parametrize("autonomy", ["A0", "A1", "A2"])
    @pytest.mark.parametrize(
        "unconsented",
        [
            None,
            {},
            {"guardian_consent": False},
            {"external_write_consent": True},  # Missing guardian_consent
        ],
    )
    def test_child_under_13_unconsented_write_local_requires_guardian_approval(
        self,
        autonomy: str,
        unconsented: Optional[Mapping[str, bool]],
    ):
        """write_local for child_under_13 without guardian_consent requires human approval."""
        ctx = ToolContext(
            user_id="usr-child-3",
            profile_id="prof-child-3",
            autonomy=autonomy,  # type: ignore[arg-type]
        )
        spec = ToolSpec(name="record_pediatric_note", risk_tier="write_local")

        decision = evaluate_policy_gate(
            ctx=ctx,
            spec=spec,
            args={"text": "Vitals note"},
            consents=unconsented,
            age_band="child_under_13",
        )

        assert decision.decision == "needs_approval"
        assert decision.needs_approval is True
        assert decision.allowed is False
        assert (
            "Guardian consent required" in decision.reason
            or "A0 autonomy requires approval" in decision.reason
        )

    def test_child_under_13_consented_write_local_permits_a1_a2_but_requires_a0(self):
        """write_local for child_under_13 with guardian_consent is allowed under A1/A2, but requires approval under A0."""
        consents = {"guardian_consent": True}
        spec = ToolSpec(name="record_pediatric_note", risk_tier="write_local")

        # Under A1: allowed
        ctx_a1 = ToolContext(user_id="u", profile_id="p", autonomy="A1")
        d_a1 = evaluate_policy_gate(ctx_a1, spec, {}, consents=consents, age_band="child_under_13")
        assert d_a1.decision == "allow"
        assert d_a1.allowed is True

        # Under A2: allowed
        ctx_a2 = ToolContext(user_id="u", profile_id="p", autonomy="A2")
        d_a2 = evaluate_policy_gate(ctx_a2, spec, {}, consents=consents, age_band="child_under_13")
        assert d_a2.decision == "allow"
        assert d_a2.allowed is True

        # Under A0: requires approval (all writes under A0 require approval)
        ctx_a0 = ToolContext(user_id="u", profile_id="p", autonomy="A0")
        d_a0 = evaluate_policy_gate(ctx_a0, spec, {}, consents=consents, age_band="child_under_13")
        assert d_a0.decision == "needs_approval"
        assert d_a0.needs_approval is True


# ============================================================================
# Section 3: Choke Point Fail-Closed & Egress Boundary Challenges
# ============================================================================

class TestChokePointFailClosedChallenges:
    """Stress-testing fail-closed properties of execute_tool_call and verify_egress_firewall."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("empty_val", ["", "   ", "\t\n"])
    async def test_tool_context_empty_profile_id_or_user_id_fails_closed(self, empty_val: str):
        """Empty profile_id or user_id raises ValueError during ToolContext creation."""
        with pytest.raises(ValueError, match="profile_id"):
            ToolContext(user_id="valid-user", profile_id=empty_val)

        with pytest.raises(ValueError, match="user_id"):
            ToolContext(user_id=empty_val, profile_id="valid-profile")

    @pytest.mark.asyncio
    async def test_execute_tool_call_rejects_non_tool_spec(self):
        """execute_tool_call fails closed if spec is not a ToolSpec instance."""
        ctx = ToolContext(user_id="u", profile_id="p")
        res = await execute_tool_call(ctx, spec="not_a_spec", args={})  # type: ignore[arg-type]
        assert res.success is False
        assert "ToolSpec instance is required" in (res.error or "")

    @pytest.mark.asyncio
    async def test_egress_firewall_blocks_ssrf_and_case_variants(self):
        """Egress firewall normalizes hostnames and strictly prevents SSRF attempts."""
        ctx = ToolContext(user_id="u", profile_id="p", autonomy="A2")
        spec = ToolSpec(
            name="api_client",
            risk_tier="write_external",
            data_flows=("api.health.gov",),
            executor=lambda args: {"done": True},
        )

        # Disallowed host
        res1 = await execute_tool_call(ctx, spec, {"url": "https://169.254.169.254/metadata"})
        assert res1.success is False
        assert "EgressBlockedError" in (res1.error or "")

        # Mixed-case allowed host passes
        res2 = await execute_tool_call(ctx, spec, {"url": "https://API.HEALTH.GOV/v1/data"}, consents={"external_write_consent": True})
        assert res2.success is True

        # Custom port on allowed host passes
        res3 = await execute_tool_call(ctx, spec, {"url": "https://api.health.gov:9443/v1/data"}, consents={"external_write_consent": True})
        assert res3.success is True

        # Custom port on disallowed host fails closed
        res4 = await execute_tool_call(ctx, spec, {"url": "https://evil.org:9443/v1/data"}, consents={"external_write_consent": True})
        assert res4.success is False
        assert "EgressBlockedError" in (res4.error or "")
