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

"""Empirical adversarial stress test suite for ToolContext and execute_tool_call (R2).

Validates:
1. Fail-closed instantiation of ToolContext on empty, whitespace, None, missing, or invalid profile_id / user_id.
2. Complete immutability of frozen ToolContext (FrozenInstanceError on attribute mutation or deletion).
3. Fail-closed rejection of dicts, non-ToolContext instances, duck-typed objects, and forged instances in execute_tool_call.
4. Monotonicity of TaintFlag: once tainted, it cannot be cleared, reset, or overwritten.
"""

from dataclasses import FrozenInstanceError
import inspect
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


# ============================================================================
# 1. Stress Tests: ToolContext Construction Fail-Closed Invariants
# ============================================================================

class TestToolContextFailClosedConstructionStress:
    """Adversarial stress testing of ToolContext construction inputs."""

    @pytest.mark.parametrize(
        "invalid_profile_id",
        [
            "",
            " ",
            "   ",
            "\t",
            "\n",
            "\r\n",
            "  \t \n \r  ",
            None,
            False,
            [],
            {},
        ],
    )
    def test_invalid_profile_id_must_raise_value_error(self, invalid_profile_id):
        """Attempting to instantiate ToolContext with empty, whitespace, None, or falsy profile_id must raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            ToolContext(user_id="valid_user_001", profile_id=invalid_profile_id)  # type: ignore[arg-type]
        assert "Security invariant violation" in str(exc_info.value)
        assert "profile_id" in str(exc_info.value)

    @pytest.mark.parametrize(
        "invalid_user_id",
        [
            "",
            " ",
            "   ",
            "\t",
            "\n",
            "\r\n",
            "  \t \n \r  ",
            None,
            False,
            [],
            {},
        ],
    )
    def test_invalid_user_id_must_raise_value_error(self, invalid_user_id):
        """Attempting to instantiate ToolContext with empty, whitespace, None, or falsy user_id must raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            ToolContext(user_id=invalid_user_id, profile_id="valid_profile_001")  # type: ignore[arg-type]
        assert "Security invariant violation" in str(exc_info.value)

    def test_missing_positional_arguments_raises_type_error(self):
        """Missing required profile_id or user_id parameters at call site must fail closed."""
        with pytest.raises(TypeError):
            ToolContext()  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            ToolContext(user_id="valid_user")  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            ToolContext(profile_id="valid_profile")  # type: ignore[call-arg]

    @pytest.mark.parametrize(
        "u, p",
        [
            ("", ""),
            ("  ", "  "),
            (None, None),
            ("", "   "),
            ("   ", ""),
            (None, ""),
            ("", None),
        ],
    )
    def test_both_identifiers_invalid_must_raise_value_error(self, u, p):
        """When both user_id and profile_id are invalid, must fail closed immediately."""
        with pytest.raises(ValueError) as exc_info:
            ToolContext(user_id=u, profile_id=p)  # type: ignore[arg-type]
        assert "Security invariant violation" in str(exc_info.value)


# ============================================================================
# 2. Stress Tests: ToolContext Immutability (FrozenInstanceError)
# ============================================================================

class TestToolContextImmutabilityStress:
    """Stress testing immutability guarantees across all attributes and mutation vectors."""

    @pytest.fixture
    def frozen_context(self) -> ToolContext:
        return ToolContext(
            user_id="usr_stress_100",
            profile_id="prf_stress_200",
            principal="user",
            run_id="run_stress_300",
            mode="local",
            autonomy="A1",
            workspace_root=Path("/tmp/carefold_workspace"),
            skills_dir=Path("/tmp/carefold_skills"),
            agent={"id": "test_agent"},
            effective_tools=("workspace-note", "attach-read"),
            skills=("cardiology-prep",),
            extra={"session_token": "secret_abc"},
        )

    @pytest.mark.parametrize(
        "attr_name, new_value",
        [
            ("profile_id", "malicious_profile_999"),
            ("user_id", "attacker_user_666"),
            ("principal", "job"),
            ("run_id", "hijacked_run_id"),
            ("mode", "server"),
            ("autonomy", "A2"),
            ("taint", TaintFlag(True)),
            ("workspace_root", Path("/etc")),
            ("skills_dir", Path("/root")),
            ("agent", {"id": "evil_agent"}),
            ("effective_tools", ("exec_cmd",)),
            ("skills", ("evil_skill",)),
            ("extra", {"hijacked": True}),
        ],
    )
    def test_cannot_mutate_declared_attributes(self, frozen_context, attr_name, new_value):
        """Direct attribute reassignment on frozen ToolContext must raise FrozenInstanceError."""
        with pytest.raises(FrozenInstanceError):
            setattr(frozen_context, attr_name, new_value)

    def test_cannot_inject_arbitrary_attributes(self, frozen_context):
        """Injecting arbitrary non-declared attributes on frozen ToolContext must raise FrozenInstanceError."""
        with pytest.raises(FrozenInstanceError):
            frozen_context.injected_escalation_flag = True  # type: ignore[attr-defined]

        with pytest.raises(FrozenInstanceError):
            setattr(frozen_context, "injected_role", "admin")

    @pytest.mark.parametrize(
        "attr_name",
        [
            "profile_id",
            "user_id",
            "principal",
            "run_id",
            "mode",
            "autonomy",
            "taint",
            "workspace_root",
        ],
    )
    def test_cannot_delete_attributes(self, frozen_context, attr_name):
        """Deleting attributes on frozen ToolContext must raise FrozenInstanceError."""
        with pytest.raises(FrozenInstanceError):
            delattr(frozen_context, attr_name)


# ============================================================================
# 3. Stress Tests: execute_tool_call Fail-Closed on Dicts & Non-ToolContext
# ============================================================================

class TestExecuteToolCallNonContextRejection:
    """Stress testing execute_tool_call rejection of dicts, non-ToolContext objects, and forged instances."""

    @pytest.fixture
    def echo_tool_spec(self) -> ToolSpec:
        def _echo(args: Dict[str, Any], ctx: Any) -> ToolResult:
            return ToolResult(success=True, output=args)

        return ToolSpec(name="echo_tool", executor=_echo)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "non_context_input",
        [
            # Dictionaries masquerading as ToolContext
            {"user_id": "u1", "profile_id": "p1"},
            {"user_id": "u1", "profile_id": "p1", "autonomy": "A2", "mode": "local"},
            {},
            # NoneType
            None,
            # Primitives
            "ToolContext(user_id='u1', profile_id='p1')",
            12345,
            True,
            False,
            # Sequences
            ["u1", "p1"],
            ("u1", "p1"),
        ],
    )
    async def test_non_tool_context_rejected_fail_closed(self, echo_tool_spec, non_context_input):
        """Passing dict, None, primitives, or sequences to execute_tool_call must fail closed with error ToolResult."""
        result = await execute_tool_call(non_context_input, echo_tool_spec, {"test": "data"})  # type: ignore[arg-type]
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert result.output is None
        assert "Security violation" in result.error
        assert "ToolContext instance is required" in result.error

    @pytest.mark.asyncio
    async def test_duck_typed_masquerade_rejected(self, echo_tool_spec):
        """Passing a duck-typed class with identical attributes to execute_tool_call must fail closed."""
        class DuckToolContext:
            def __init__(self):
                self.user_id = "duck_user"
                self.profile_id = "duck_profile"
                self.principal = "user"
                self.run_id = "duck_run"
                self.mode = "local"
                self.autonomy = "A1"
                self.taint = TaintFlag()

        duck = DuckToolContext()
        result = await execute_tool_call(duck, echo_tool_spec, {})  # type: ignore[arg-type]
        assert result.success is False
        assert "ToolContext instance is required" in result.error

    @pytest.mark.asyncio
    async def test_forged_instance_with_empty_identifiers_fails_closed(self, echo_tool_spec):
        """If an attacker bypasses __post_init__ via object.__new__ and object.__setattr__, execute_tool_call must fail closed."""
        forged_ctx = object.__new__(ToolContext)
        object.__setattr__(forged_ctx, "user_id", "")
        object.__setattr__(forged_ctx, "profile_id", "")
        object.__setattr__(forged_ctx, "principal", "user")
        object.__setattr__(forged_ctx, "run_id", "forged_run")
        object.__setattr__(forged_ctx, "mode", "local")
        object.__setattr__(forged_ctx, "autonomy", "A1")
        object.__setattr__(forged_ctx, "taint", TaintFlag())

        result = await execute_tool_call(forged_ctx, echo_tool_spec, {})
        assert result.success is False
        assert (
            "profile_id is missing or empty (fail-closed)" in result.error
            or "user_id is missing or empty (fail-closed)" in result.error
        )


# ============================================================================
# 4. Stress Tests: TaintFlag Monotonicity & Tamper-Resistance
# ============================================================================

class TestTaintFlagMonotonicityStress:
    """Stress testing the monotone per-run taint tracking invariant."""

    def test_taint_flag_starts_clean_unless_explicitly_set(self):
        tf = TaintFlag()
        assert tf.is_tainted is False
        assert bool(tf) is False

        tf_tainted = TaintFlag(initial=True)
        assert tf_tainted.is_tainted is True
        assert bool(tf_tainted) is True

    def test_set_permanently_latches_taint(self):
        tf = TaintFlag()
        tf.set()
        assert tf.is_tainted is True
        assert bool(tf) is True

        # Setting repeatedly preserves True
        for _ in range(50):
            tf.set()
            assert tf.is_tainted is True

    def test_no_clearing_api_exists_on_taint_flag(self):
        """Verify TaintFlag exposes no clear(), unset(), or reset() methods."""
        tf = TaintFlag()
        tf.set()

        for forbidden_method in ("clear", "reset", "unset", "untaint", "revert"):
            assert not hasattr(tf, forbidden_method), f"TaintFlag must not expose '{forbidden_method}'"

    def test_is_tainted_property_has_no_setter(self):
        """Attempting to directly assign to is_tainted property must raise AttributeError."""
        tf = TaintFlag()
        tf.set()
        assert tf.is_tainted is True

        with pytest.raises(AttributeError):
            tf.is_tainted = False  # type: ignore[misc]

    def test_set_rejects_arguments(self):
        """set() does not take a boolean parameter to toggle state."""
        tf = TaintFlag()
        with pytest.raises(TypeError):
            tf.set(False)  # type: ignore[call-arg]

    @pytest.mark.asyncio
    async def test_subsequent_trusted_tools_do_not_clear_context_taint(self):
        """Once tainted by an untrusted tool, subsequent executions of trusted tools must not clear the taint."""
        ctx = ToolContext(user_id="u1", profile_id="p1")
        assert ctx.taint.is_tainted is False

        # 1. Execute untrusted tool -> triggers taint
        untrusted_spec = ToolSpec(
            name="untrusted_fetch",
            trust="untrusted",
            executor=lambda args, c: ToolResult(success=True, output="untrusted payload"),
        )
        res1 = await execute_tool_call(ctx, untrusted_spec, {})
        assert res1.success is True
        assert ctx.taint.is_tainted is True

        # 2. Execute multiple trusted tools -> taint must remain True
        trusted_spec = ToolSpec(
            name="trusted_calc",
            trust="trusted",
            executor=lambda args, c: ToolResult(success=True, output="sanitized output"),
        )
        for _ in range(5):
            res2 = await execute_tool_call(ctx, trusted_spec, {})
            assert res2.success is True
            assert ctx.taint.is_tainted is True
