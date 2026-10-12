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

"""Single tool execution choke point and immutable runtime context.

Defines:
- TaintFlag: Monotone per-run untrusted data taint tracking
- ToolContext: Immutable, fail-closed runtime execution context
- ToolSpec: Declarative specification, data flows, and risk tiers for tools
- execute_tool_call: Universal choke point for all tool invocations
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import inspect
import logging
from pathlib import Path
import time
from typing import (
    Any,
    Callable,
    Dict,
    Literal,
    Mapping,
    Optional,
    Sequence,
)
from urllib.parse import urlparse

from carefold.schemas.tool import ToolResult

logger = logging.getLogger("carefold.engine.tool_exec")

try:
    from connectors.base import (
        ToolContext as ConnectorToolContext,
        ToolSpec as ConnectorToolSpec,
    )
except ImportError:
    ConnectorToolContext = ()  # type: ignore
    ConnectorToolSpec = ()  # type: ignore

RiskTier = Literal["read", "write_local", "write_external", "irreversible"]
TrustLevel = Literal["trusted", "untrusted"]


class TaintFlag:
    """Monotone per-run taint flag. Once set, can never be cleared."""

    def __init__(self, initial: bool = False) -> None:
        self._tainted: bool = bool(initial)

    @property
    def is_tainted(self) -> bool:
        return self._tainted

    def set(self) -> None:
        self._tainted = True

    def __bool__(self) -> bool:
        return self._tainted

    def __repr__(self) -> str:
        return f"TaintFlag(tainted={self._tainted})"


@dataclass(frozen=True)
class ToolContext:
    """Immutable, fail-closed runtime context for all tool executions."""

    user_id: str
    profile_id: str
    principal: Literal["user", "job"] = "user"
    run_id: str = ""
    mode: Literal["local", "server"] = "local"
    autonomy: Literal["A0", "A1", "A2"] = "A1"
    taint: TaintFlag = field(default_factory=TaintFlag)

    # Sandbox compatibility fields
    workspace_root: Optional[Path] = None
    skills_dir: Optional[Path] = None
    agent: Optional[Any] = None
    effective_tools: Sequence[str] = field(default_factory=tuple)
    skills: Sequence[Any] = field(default_factory=tuple)
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Enforce strict fail-closed security invariants."""
        if not self.profile_id or not str(self.profile_id).strip():
            raise ValueError(
                "Security invariant violation: ToolContext requires a non-empty 'profile_id'. Fail-closed."
            )
        if not self.user_id or not str(self.user_id).strip():
            raise ValueError(
                "Security invariant violation: ToolContext requires a non-empty 'user_id'. Fail-closed."
            )


@dataclass(frozen=True)
class ToolSpec:
    """Specification and security policy for an executable tool."""

    name: str
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    risk_tier: RiskTier = "read"
    trust: TrustLevel = "trusted"
    data_flows: Sequence[str] = field(default_factory=tuple)  # Allowed hostnames for external egress
    executor: Optional[Callable[..., Any]] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


async def execute_tool_call(
    ctx: ToolContext,
    spec: ToolSpec,
    args: Dict[str, Any],
) -> ToolResult:
    """Single execution choke point for all tool invocations across Carefold.

    Enforces:
    1. Fail-closed validation of ToolContext, user_id, and profile_id.
    2. ToolSpec validation and callable executor availability.
    3. Network egress allowlist checking against spec.data_flows.
    4. Execution under sandboxed context with exception containment.
    5. Monotone taint flag propagation when untrusted tools execute.
    6. Audit event logging with execution timing and error details.
    """
    t0 = time.time()

    # 1. Fail-closed ToolContext Validation
    if not isinstance(ctx, (ToolContext, ConnectorToolContext)):
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: Tool execution denied. ToolContext instance is required.",
        )

    if not ctx.profile_id or not str(ctx.profile_id).strip():
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: Tool execution denied. profile_id is missing or empty (fail-closed).",
        )

    if not ctx.user_id or not str(ctx.user_id).strip():
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: Tool execution denied. user_id is missing or empty (fail-closed).",
        )

    # 2. ToolSpec Validation
    if not isinstance(spec, (ToolSpec, ConnectorToolSpec)):
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: Tool execution denied. ToolSpec instance is required.",
        )

    executor = getattr(spec, "executor", None) or getattr(spec, "handler", None)
    if not callable(executor):
        return ToolResult(
            success=False,
            output=None,
            error=f"Tool '{spec.name}' has no valid executor.",
        )

    # 3. Network Egress Validation against spec.data_flows
    spec_data_flows = tuple(getattr(spec, "data_flows", ()))
    spec_risk_tier = getattr(spec, "risk_tier", "read")

    for key in ("url", "endpoint", "host", "target_url", "base_url"):
        target = args.get(key)
        if target and isinstance(target, str):
            clean_target = target.strip()
            parsed = urlparse(clean_target if "://" in clean_target else f"http://{clean_target}")
            dest_host = parsed.hostname or clean_target
            if spec_data_flows and dest_host not in spec_data_flows:
                dur_ms = round((time.time() - t0) * 1000, 2)
                err_msg = (
                    f"Security violation: Network egress to host '{dest_host}' "
                    f"denied by tool '{spec.name}' data_flows policy."
                )
                await _record_tool_audit(ctx, spec, False, dur_ms, err_msg)
                return ToolResult(
                    success=False,
                    output=None,
                    error=err_msg,
                )
            if not spec_data_flows and spec_risk_tier == "write_external":
                dur_ms = round((time.time() - t0) * 1000, 2)
                err_msg = (
                    f"Security violation: External egress tool '{spec.name}' "
                    "has no authorized data_flows configured."
                )
                await _record_tool_audit(ctx, spec, False, dur_ms, err_msg)
                return ToolResult(
                    success=False,
                    output=None,
                    error=err_msg,
                )

    # 4. Tool Execution under Sandboxed Context
    try:
        if inspect.iscoroutinefunction(executor):
            sig = inspect.signature(executor)
            params = list(sig.parameters.keys())
            if len(params) >= 2 and params[0] in ("args", "params"):
                raw_res = await executor(args, ctx)
            elif len(params) == 1:
                raw_res = await executor(args)
            else:
                try:
                    raw_res = await executor(ctx, args)
                except TypeError:
                    raw_res = await executor(args, ctx)
        else:
            sig = inspect.signature(executor)
            params = list(sig.parameters.keys())
            if len(params) >= 2 and params[0] in ("args", "params"):
                raw_res = executor(args, ctx)
            elif len(params) == 1:
                raw_res = executor(args)
            else:
                try:
                    raw_res = executor(ctx, args)
                except TypeError:
                    raw_res = executor(args, ctx)
            if asyncio.iscoroutine(raw_res):
                raw_res = await raw_res

    except Exception as exc:
        dur_ms = round((time.time() - t0) * 1000, 2)
        logger.exception("Error executing tool '%s': %s", spec.name, exc)
        err_msg = f"Tool '{spec.name}' execution failed: {exc}"
        await _record_tool_audit(ctx, spec, False, dur_ms, err_msg)
        return ToolResult(
            success=False,
            output=None,
            error=err_msg,
        )

    dur_ms = round((time.time() - t0) * 1000, 2)

    # Standardize result into ToolResult
    if isinstance(raw_res, ToolResult):
        result = raw_res
    elif isinstance(raw_res, dict) and "success" in raw_res:
        result = ToolResult(
            success=bool(raw_res.get("success")),
            output=raw_res.get("output"),
            error=raw_res.get("error"),
        )
    else:
        result = ToolResult(success=True, output=raw_res, error=None)

    # 5. Untrusted Data Taint Tracking
    if (
        getattr(spec, "trust", "trusted") == "untrusted"
        and getattr(ctx, "taint", None) is not None
        and hasattr(ctx.taint, "set")
    ):
        ctx.taint.set()

    # 6. Audit Event Logging
    await _record_tool_audit(
        ctx,
        spec,
        allowed=True,
        dur_ms=dur_ms,
        reason=result.error if not result.success else None,
    )

    return result


async def _record_tool_audit(
    ctx: ToolContext,
    spec: ToolSpec,
    allowed: bool,
    dur_ms: float,
    reason: Optional[str] = None,
) -> None:
    """Best-effort audit recording through carefold.audit.logger."""
    try:
        from carefold.audit.logger import record_audit
        from carefold.config import settings
        from carefold.constants.paths import DEFAULT_AUDIT_LOG_FILE, LOGS_DIR
        from carefold.schemas.audit import AuditEvent

        ws_root = getattr(ctx, "workspace_root", None) or Path(settings.workspace_root)
        log_path = (
            Path(settings.audit_log_path)
            if settings.audit_log_path
            else (ws_root / LOGS_DIR / DEFAULT_AUDIT_LOG_FILE)
        )
        agent_obj = getattr(ctx, "agent", None)
        agent_id = getattr(agent_obj, "id", None) or "carefold-agent"

        await record_audit(
            AuditEvent(
                agent_id=str(agent_id),
                event="tool",
                tool=spec.name,
                allowed=allowed,
                duration_ms=dur_ms,
                profile_id=ctx.profile_id,
                thread_id=getattr(ctx, "run_id", "") or None,
                reason=reason,
            ),
            log_path=log_path,
            store_bodies=bool(settings.audit_store_bodies),
        )
    except Exception as err:
        logger.debug("Choke point audit recording failed: %s", err)


__all__ = [
    "RiskTier",
    "TaintFlag",
    "ToolContext",
    "ToolSpec",
    "TrustLevel",
    "execute_tool_call",
]
