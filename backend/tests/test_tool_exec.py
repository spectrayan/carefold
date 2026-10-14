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

"""Unit and security verification suite for ToolContext and execute_tool_call choke point."""

import asyncio
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, Dict
import pytest

from carefold.engine.tool_exec import (
    RiskTier,
    TaintFlag,
    ToolContext,
    ToolSpec,
    TrustLevel,
    execute_tool_call,
)
from carefold.schemas.tool import ToolResult
from carefold.workflows.nodes.tool_node import ToolNode


# ============================================================================
# 1. ToolContext Fail-Closed Validation Tests
# ============================================================================

class TestToolContextValidation:
    """Verifies fail-closed validation of ToolContext construction."""

    def test_missing_or_empty_profile_id_raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            ToolContext(user_id="user_123", profile_id="")
        assert "Security invariant violation: ToolContext requires a non-empty 'profile_id'. Fail-closed." in str(exc_info.value)

    def test_whitespace_profile_id_raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            ToolContext(user_id="user_123", profile_id="   \t\n  ")
        assert "Security invariant violation: ToolContext requires a non-empty 'profile_id'. Fail-closed." in str(exc_info.value)

    def test_missing_or_empty_user_id_raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            ToolContext(user_id="", profile_id="profile_456")
        assert "Security invariant violation: ToolContext requires a non-empty 'user_id'. Fail-closed." in str(exc_info.value)

    def test_whitespace_user_id_raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            ToolContext(user_id="   ", profile_id="profile_456")
        assert "Security invariant violation: ToolContext requires a non-empty 'user_id'. Fail-closed." in str(exc_info.value)

    def test_valid_instantiation_sets_defaults(self):
        ctx = ToolContext(user_id="user_123", profile_id="profile_456")
        assert ctx.user_id == "user_123"
        assert ctx.profile_id == "profile_456"
        assert ctx.principal == "user"
        assert ctx.run_id == ""
        assert ctx.mode == "local"
        assert ctx.autonomy == "A1"
        assert isinstance(ctx.taint, TaintFlag)
        assert bool(ctx.taint) is False
        assert ctx.workspace_root is None
        assert ctx.skills_dir is None
        assert ctx.effective_tools == ()
        assert ctx.skills == ()


# ============================================================================
# 2. ToolContext Immutability Tests
# ============================================================================

class TestToolContextImmutability:
    """Verifies that ToolContext instances are frozen and cannot be mutated."""

    def test_cannot_mutate_profile_id(self):
        ctx = ToolContext(user_id="user_123", profile_id="profile_456")
        with pytest.raises(FrozenInstanceError):
            ctx.profile_id = "attacker_profile"  # type: ignore[misc]

    def test_cannot_mutate_user_id(self):
        ctx = ToolContext(user_id="user_123", profile_id="profile_456")
        with pytest.raises(FrozenInstanceError):
            ctx.user_id = "attacker_user"  # type: ignore[misc]

    def test_cannot_mutate_autonomy(self):
        ctx = ToolContext(user_id="user_123", profile_id="profile_456")
        with pytest.raises(FrozenInstanceError):
            ctx.autonomy = "A2"  # type: ignore[misc]


# ============================================================================
# 3. TaintFlag Monotone State Tests
# ============================================================================

class TestTaintFlag:
    """Verifies monotone per-run untrusted data taint behavior."""

    def test_initial_state_clean(self):
        tf = TaintFlag()
        assert tf.is_tainted is False
        assert bool(tf) is False

    def test_set_marks_tainted_monotonically(self):
        tf = TaintFlag()
        tf.set()
        assert tf.is_tainted is True
        assert bool(tf) is True
        # Setting again preserves True
        tf.set()
        assert tf.is_tainted is True


# ============================================================================
# 4. execute_tool_call Choke Point & Egress Checks
# ============================================================================

class TestExecuteToolCallChokePoint:
    """Verifies single choke point validation, egress checking, and execution."""

    @pytest.mark.asyncio
    async def test_denied_when_context_is_not_tool_context(self):
        dummy_spec = ToolSpec(name="dummy", executor=lambda args, ctx: ToolResult(success=True))
        result = await execute_tool_call(None, dummy_spec, {})  # type: ignore[arg-type]
        assert result.success is False
        assert "ToolContext instance is required" in result.error

    @pytest.mark.asyncio
    async def test_denied_when_spec_has_no_executor(self):
        ctx = ToolContext(user_id="u1", profile_id="p1")
        spec = ToolSpec(name="no_exec", executor=None)
        result = await execute_tool_call(ctx, spec, {})
        assert result.success is False
        assert "has no valid executor" in result.error

    @pytest.mark.asyncio
    async def test_network_egress_allowed_host_succeeds(self):
        ctx = ToolContext(user_id="u1", profile_id="p1")

        async def mock_fetch(args, c):
            return ToolResult(success=True, output={"status": 200, "data": "healthy"})

        spec = ToolSpec(
            name="fetch_records",
            risk_tier="read",
            data_flows=("api.hospital.org",),
            executor=mock_fetch,
        )

        result = await execute_tool_call(ctx, spec, {"url": "https://api.hospital.org/v1/patient"})
        assert result.success is True
        assert result.output["data"] == "healthy"

    @pytest.mark.asyncio
    async def test_network_egress_unauthorized_host_fails_closed(self):
        ctx = ToolContext(user_id="u1", profile_id="p1")

        async def mock_fetch(args, c):
            return ToolResult(success=True, output={"leaked": True})

        spec = ToolSpec(
            name="fetch_records",
            risk_tier="read",
            data_flows=("api.hospital.org",),
            executor=mock_fetch,
        )

        result = await execute_tool_call(ctx, spec, {"url": "https://evil.exfiltration.com/leak"})
        assert result.success is False
        assert "Security violation: Network egress to host 'evil.exfiltration.com' denied" in result.error

    @pytest.mark.asyncio
    async def test_external_egress_without_data_flows_fails_closed(self):
        ctx = ToolContext(user_id="u1", profile_id="p1")

        async def mock_post(args, c):
            return ToolResult(success=True)

        spec = ToolSpec(
            name="external_sync",
            risk_tier="write_external",
            data_flows=(),
            executor=mock_post,
        )

        result = await execute_tool_call(ctx, spec, {"endpoint": "https://arbitrary.net/webhook"})
        assert result.success is False
        assert "has no authorized data_flows configured" in result.error

    @pytest.mark.asyncio
    async def test_untrusted_tool_propagates_taint_to_context(self):
        ctx = ToolContext(user_id="u1", profile_id="p1")
        assert ctx.taint.is_tainted is False

        async def mock_scrape(args, c):
            return ToolResult(success=True, output="public text")

        spec = ToolSpec(
            name="web_scrape",
            trust="untrusted",
            executor=mock_scrape,
        )

        result = await execute_tool_call(ctx, spec, {})
        assert result.success is True
        assert ctx.taint.is_tainted is True

    @pytest.mark.asyncio
    async def test_executor_exception_contained_safely(self):
        ctx = ToolContext(user_id="u1", profile_id="p1")

        async def exploding_tool(args, c):
            raise RuntimeError("Unexpected subsystem explosion")

        spec = ToolSpec(name="exploder", executor=exploding_tool)
        result = await execute_tool_call(ctx, spec, {})
        assert result.success is False
        assert "Tool 'exploder' execution failed: Unexpected subsystem explosion" in result.error


# ============================================================================
# 5. ToolNode Integration & Fail-Closed Scoping Tests
# ============================================================================

class TestToolNodeIntegration:
    """Verifies ToolNode execution through choke point and fail-closed profile_id invariant."""

    @pytest.mark.asyncio
    async def test_tool_node_missing_profile_id_fails_closed(self):
        node = ToolNode()
        state = {
            "tool_calls": [{"id": "call_1", "name": "workspace-note", "args": {"title": "T", "content": "C"}}],
            "effective_tools": ["workspace-note"],
        }
        # Calling without ToolContext and without profile_id in config
        with pytest.raises(ValueError) as exc_info:
            await node.execute(state, config={"configurable": {"user_id": "u1", "profile_id": ""}})
        assert "Security invariant violation: ToolContext requires a non-empty 'profile_id'. Fail-closed." in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_tool_node_with_valid_tool_context_executes_successfully(self, tmp_path: Path):
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)

        ctx = ToolContext(
            user_id="test_user",
            profile_id="test_profile",
            workspace_root=tmp_path,
        )
        node = ToolNode(allowed_tools=["workspace-note"], tool_context=ctx)
        state = {
            "tool_calls": [{"id": "call_1", "name": "workspace-note", "args": {"title": "ValidNote", "content": "TestContent"}}],
            "workspace_root": str(tmp_path),
        }
        res = await node.execute(state, config={"configurable": {"tool_context": ctx}})

        assert "messages" in res
        assert len(res["messages"]) == 1
        msg = res["messages"][0]
        assert msg.status == "success"
        assert "tool_traces" in res
        assert res["tool_traces"][0]["success"] is True
