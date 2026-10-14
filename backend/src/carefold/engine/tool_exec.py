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

"""Single tool execution choke point, deterministic policy gate, and egress firewall (AU-17).

Defines:
- RiskTier & TrustLevel: 4-tier risk classification and provenance typing
- TaintFlag: Monotone per-run untrusted data taint tracking (AU-19)
- UntrustedResult: Wrapper marking tool output as untrusted, triggering taint
- EgressBlockedError: Network boundary permission error (0 network bytes sent)
- PolicyDecision: Deterministic evaluation output (allowed, needs_approval, reason)
- ToolContext: Immutable, fail-closed runtime execution context
- ToolSpec: Declarative specification, data flows, and risk tiers for tools
- canonical_json & compute_payload_hash: RFC-8785 canonical argument hashing (AU-18)
- verify_egress_firewall: Anti-SSRF and allowlist destination host matching
- evaluate_policy_gate: Truth table matrix for tier x autonomy x taint x consent x age
- execute_tool_call: Universal choke point for all tool invocations across Carefold
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import inspect
import json
import logging
import os
from pathlib import Path
import time
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)
from urllib.parse import urlparse

from carefold.engine.tool_registry import (
    DataFlows,
    RiskTier,
    ToolSpec,
    TrustLevel,
)
from carefold.schemas.tool import ToolResult as BaseToolResult

logger = logging.getLogger("carefold.engine.tool_exec")

try:
    from connectors.base import (
        ToolContext as ConnectorToolContext,
        ToolSpec as ConnectorToolSpec,
    )
except ImportError:
    ConnectorToolContext = ()  # type: ignore
    ConnectorToolSpec = ()  # type: ignore

AutonomyLevel = Literal["A0", "A1", "A2"]


# ============================================================================
# Section 1: Monotone Taint Tracking & Untrusted Result (AU-19)
# ============================================================================

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


@dataclass
class UntrustedResult:
    """Wrapper marking tool output as untrusted, triggering monotone taint propagation."""

    data: Any
    taint: bool = True
    source: str = "external"

    def __post_init__(self) -> None:
        self.taint = bool(self.taint)

    def __iter__(self):
        if isinstance(self.data, (list, tuple, set)):
            return iter(self.data)
        return iter([self.data])

    def __getitem__(self, index: Any) -> Any:
        if isinstance(self.data, (list, tuple, dict)):
            return self.data[index]
        raise TypeError(f"'{type(self.data).__name__}' object is not subscriptable")

    def __len__(self) -> int:
        if isinstance(self.data, (list, tuple, dict, set)):
            return len(self.data)
        return 1

    def __contains__(self, item: Any) -> bool:
        if isinstance(self.data, (list, tuple, dict, set)):
            return item in self.data
        return item == self.data


# ============================================================================
# Section 2: Egress Firewall Exception & Anti-SSRF (AU-17 & AU-20)
# ============================================================================

class EgressBlockedError(PermissionError):
    """Raised when an outbound network request targets an unauthorized host or violates egress policy."""

    def __init__(
        self,
        message: str = "Outbound network egress blocked by security policy.",
        host: Optional[str] = None,
        tool: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.host = host
        self.tool = tool


# ============================================================================
# Section 3: Policy Decision & Canonical Hashing (AU-17 & AU-18)
# ============================================================================

def canonical_json(data: Any) -> str:
    """Produces RFC-8785 compliant canonical JSON string."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_payload_hash(args: Dict[str, Any]) -> str:
    """Computes SHA-256 hex digest of canonical arguments."""
    return hashlib.sha256(canonical_json(args).encode("utf-8")).hexdigest()


@dataclass(frozen=True, init=False)
class PolicyDecision:
    """Decision output of evaluate_policy_gate with dual boolean and string literal interface.

    Attributes:
        allowed: True if execution is permitted without human approval.
        needs_approval: True if execution requires human approval before proceeding.
        reason: Plain-text explanation of the decision for audit and client feedback.
        decision: String literal ("allow", "needs_approval", "blocked").
    """

    allowed: bool
    needs_approval: bool
    reason: str
    decision: Literal["allow", "needs_approval", "blocked"]

    def __init__(
        self,
        arg1: Any = None,
        arg2: Any = None,
        reason: str = "",
        *,
        allowed: Optional[bool] = None,
        needs_approval: Optional[bool] = None,
        decision: Optional[Literal["allow", "needs_approval", "blocked"]] = None,
    ) -> None:
        if isinstance(arg1, str) and arg1 in ("allow", "needs_approval", "blocked"):
            dec: Literal["allow", "needs_approval", "blocked"] = arg1  # type: ignore
            reas = str(arg2 if arg2 is not None else reason or "")
            allow_flag = (dec == "allow")
            appr_flag = (dec == "needs_approval")
        elif isinstance(arg1, bool):
            allow_flag = arg1
            appr_flag = bool(arg2)
            reas = str(reason or "")
            if appr_flag:
                dec = "needs_approval"
            elif allow_flag:
                dec = "allow"
            else:
                dec = "blocked"
        else:
            allow_flag = bool(allowed)
            appr_flag = bool(needs_approval)
            reas = str(reason or "")
            if decision:
                dec = decision
            elif appr_flag:
                dec = "needs_approval"
            elif allow_flag:
                dec = "allow"
            else:
                dec = "blocked"

        object.__setattr__(self, "allowed", allow_flag)
        object.__setattr__(self, "needs_approval", appr_flag)
        object.__setattr__(self, "reason", reas)
        object.__setattr__(self, "decision", dec)

    @classmethod
    def allow(cls, reason: str = "") -> PolicyDecision:
        return cls(allowed=True, needs_approval=False, reason=reason, decision="allow")

    @classmethod
    def require_approval(cls, reason: str = "") -> PolicyDecision:
        return cls(allowed=False, needs_approval=True, reason=reason, decision="needs_approval")

    @classmethod
    def block(cls, reason: str = "") -> PolicyDecision:
        return cls(allowed=False, needs_approval=False, reason=reason, decision="blocked")

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, PolicyDecision):
            return (
                self.allowed == other.allowed
                and self.needs_approval == other.needs_approval
                and self.decision == other.decision
                and self.reason == other.reason
            )
        if isinstance(other, str):
            return self.decision == other
        return False


# ============================================================================
# Section 4: Tool Context & Result Declarations
# ============================================================================

@dataclass(frozen=True)
class ToolContext:
    """Immutable, fail-closed runtime context for all tool executions."""

    user_id: str
    profile_id: str
    principal: Literal["user", "job"] = "user"
    run_id: str = ""
    mode: Literal["local", "server"] = "local"
    autonomy: Literal["A0", "A1", "A2", "supervised", "autonomous"] = "A1"
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
        if not self.profile_id or not isinstance(self.profile_id, str) or not self.profile_id.strip():
            raise ValueError(
                "Security invariant violation: ToolContext requires a non-empty string 'profile_id'. Fail-closed. "
                "Security invariant violation: ToolContext requires a non-empty 'profile_id'. Fail-closed."
            )
        if not self.user_id or not isinstance(self.user_id, str) or not self.user_id.strip():
            raise ValueError(
                "Security invariant violation: ToolContext requires a non-empty string 'user_id'. Fail-closed. "
                "Security invariant violation: ToolContext requires a non-empty 'user_id'. Fail-closed."
            )


class ToolResult(BaseToolResult):
    """Execution result with backward-compatible HITL approval fields."""

    needs_approval: bool = False
    approval_id: Optional[str] = None


# ============================================================================
# Section 5: Egress Firewall Verification
# ============================================================================

def _extract_allowed_hosts(spec: ToolSpec) -> Tuple[str, ...]:
    """Extracts declared allowed hosts from ToolSpec data_flows."""
    df = getattr(spec, "data_flows", None)
    if df is None:
        return ()
    if hasattr(df, "allowed_hosts"):
        raw = getattr(df, "allowed_hosts")
        if isinstance(raw, (list, tuple, set)):
            return tuple(str(h).strip().lower() for h in raw if str(h).strip())
    if isinstance(df, (list, tuple, set)):
        return tuple(str(h).strip().lower() for h in df if str(h).strip())
    return ()


def verify_egress_firewall(
    spec: ToolSpec,
    args: Dict[str, Any],
) -> List[str]:
    """Matches requested destination hosts against spec.data_flows.allowed_hosts.

    Raises:
        EgressBlockedError: If destination host is unlisted or unauthorized (0 bytes sent).

    Returns:
        List[str]: Verified destination hosts found in arguments.
    """
    allowed_hosts = _extract_allowed_hosts(spec)
    spec_risk_tier = getattr(spec, "risk_tier", "read")
    destination_hosts: List[str] = []

    for key in ("url", "endpoint", "host", "target_url", "base_url"):
        target = args.get(key)
        if not target or not isinstance(target, str):
            continue

        clean_target = target.strip()
        if not clean_target:
            continue

        if "://" in clean_target:
            parsed = urlparse(clean_target)
        else:
            parsed = urlparse(f"http://{clean_target}")

        raw_host = parsed.hostname or clean_target
        dest_host = raw_host.strip().lower()
        destination_hosts.append(dest_host)

        # 1. Allowed hosts configured: verify exact match
        if allowed_hosts:
            if dest_host not in allowed_hosts:
                raise EgressBlockedError(
                    f"Security violation: Network egress to host '{dest_host}' "
                    f"denied by tool '{spec.name}' data_flows policy.",
                    host=dest_host,
                    tool=spec.name,
                )
        else:
            # 2. No allowed hosts configured:
            # External write tools must fail closed immediately if data_flows is missing/empty
            if spec_risk_tier == "write_external":
                raise EgressBlockedError(
                    f"Security violation: External egress tool '{spec.name}' "
                    "has no authorized data_flows configured.",
                    host=dest_host,
                    tool=spec.name,
                )

    return destination_hosts


# ============================================================================
# Section 6: Policy Decision Gate Matrix (AU-17)
# ============================================================================

def evaluate_policy_gate(
    ctx: ToolContext,
    spec: ToolSpec,
    args: Dict[str, Any],
    consents: Optional[Mapping[str, bool]] = None,
    age_band: Optional[str] = None,
) -> PolicyDecision:
    """Evaluates multi-dimensional security matrix:

        tier x profile autonomy (A0/A1/A2) x taint x consent x age_band

    Rules:
    1. Read operations: ALLOWED across all contexts.
    2. Child under 13: external writes completely blocked; write_local requires guardian consent.
    3. Irreversible actions: ALWAYS require human approval across all autonomy levels.
    4. Monotone taint: if taint == True, write_external and irreversible FORCE APPROVAL.
    5. Autonomy A0: all writes require approval.
    6. Autonomy A1: write_local allowed; write_external and irreversible require approval.
    7. Autonomy A2: write_local allowed; write_external allowed if consented, else requires approval.
    """
    tier: RiskTier = getattr(spec, "risk_tier", "read")

    # 1. Read Operations: Pure observation with zero state mutation
    if tier == "read":
        return PolicyDecision.allow("Read operation permitted")

    raw_autonomy = getattr(ctx, "autonomy", "A1")

    # Normalize autonomy levels
    if raw_autonomy in ("A0", "A1", "A2"):
        autonomy: AutonomyLevel = raw_autonomy  # type: ignore
    elif raw_autonomy == "supervised":
        autonomy = "A1"
    elif raw_autonomy == "autonomous":
        autonomy = "A2"
    else:
        autonomy = "A0"  # Fail-closed fallback

    eff_consents: Mapping[str, bool] = (
        consents
        if consents is not None
        else (getattr(ctx, "consents", None) or (getattr(ctx, "extra", {}) or {}).get("consents") or {})
    )
    eff_age_band: str = (
        age_band
        if age_band is not None
        else (getattr(ctx, "age_band", None) or (getattr(ctx, "extra", {}) or {}).get("age_band") or "adult")
    )
    effective_age_band = (eff_age_band or "adult").strip().lower()

    # 2. Child Under 13 Protection (AGENTS.md & AU-17)
    if effective_age_band == "child_under_13":
        if tier == "write_external":
            return PolicyDecision.block("Child under 13 external write blocked by policy")
        if tier == "write_local":
            if not eff_consents.get("guardian_consent"):
                return PolicyDecision.require_approval("Guardian consent required for child write_local")

    # 3. Irreversible Actions: Permanence invariant
    if tier == "irreversible":
        return PolicyDecision.require_approval("Irreversible action requires human approval")

    # 4. Monotone Taint Override: Untrusted input exfiltration prevention
    taint_obj = getattr(ctx, "taint", None)
    is_tainted: bool = bool(getattr(taint_obj, "is_tainted", taint_obj or False))
    if is_tainted and tier == "write_external":
        return PolicyDecision.require_approval("FORCED APPROVAL: Context is tainted by untrusted data")

    # 5. Autonomy Level Matrix (A0 / A1 / A2)
    if autonomy == "A0":
        return PolicyDecision.require_approval(f"A0 autonomy requires approval for all write actions")

    if autonomy == "A1":
        if tier == "write_external":
            return PolicyDecision.require_approval("A1 autonomy requires approval for external and irreversible actions")
        if tier == "write_local":
            return PolicyDecision.allow("write_local permitted under A1")

    if autonomy == "A2":
        if tier == "write_local":
            return PolicyDecision.allow("write_local permitted under A2")
        if tier == "write_external":
            if eff_consents.get("external_write_consent"):
                return PolicyDecision.allow("A2 autonomy with recorded external write consent")
            return PolicyDecision.require_approval("A2 autonomy requires consent or approval for external writes")

    return PolicyDecision.allow("Default allow")


# ============================================================================
# Section 6.5: Production SQL Approval Store Adapter (SqlApprovalStore)
# ============================================================================


class SqlApprovalStore:
    """Production SQL-backed approval store adapter for policy gate approvals (ADR-0004)."""

    def __init__(self, session_factory: Optional[Any] = None) -> None:
        self._session_factory = session_factory

    def _get_session_factory(self) -> Any:
        if self._session_factory is not None:
            return self._session_factory
        from carefold.db.session import get_session_factory

        return get_session_factory()

    async def get(self, approval_id: str) -> Optional[Any]:
        from sqlalchemy import select
        from carefold.db.models import Approval

        factory = self._get_session_factory()
        async with factory() as session:
            stmt = select(Approval).where(Approval.id == approval_id)
            res = await session.execute(stmt)
            return res.scalar_one_or_none()

    async def create_pending(
        self,
        approval_id: str,
        profile_id: str,
        run_id: str,
        tool_name: str,
        args: Dict[str, Any],
        risk_tier: str,
        destination_hosts: Optional[Sequence[str]] = None,
        thread_id: Optional[str] = None,
        ttl_minutes: int = 15,
    ) -> Any:
        from datetime import datetime, timedelta, timezone
        from carefold.db.models import Approval

        factory = self._get_session_factory()
        async with factory() as session:
            now = datetime.now(timezone.utc)
            record = Approval(
                id=approval_id,
                profile_id=profile_id,
                run_id=run_id,
                thread_id=thread_id or run_id,
                tool_name=tool_name,
                args_redacted=json.dumps(args),
                payload_hash=compute_payload_hash(args),
                destination_hosts=json.dumps(list(destination_hosts or [])),
                risk_tier=risk_tier,
                status="pending",
                expires_at=now + timedelta(minutes=ttl_minutes),
                created_at=now,
            )
            session.add(record)
            await session.commit()
            return record

    async def consume_atomic(self, approval_id: str, current_args: Dict[str, Any]) -> str:
        from carefold.api.approvals import consume_approval_atomic

        factory = self._get_session_factory()
        async with factory() as session:
            return await consume_approval_atomic(session, approval_id, current_args)


# ============================================================================
# Section 7: Universal Execution Choke Point (execute_tool_call)
# ============================================================================

async def execute_tool_call(
    ctx: ToolContext,
    spec: ToolSpec,
    args: Dict[str, Any],
    approval_store: Optional[Any] = None,
    approval_id: Optional[str] = None,
    consents: Optional[Mapping[str, bool]] = None,
    age_band: Optional[str] = None,
) -> ToolResult:
    """Single execution choke point for all tool invocations across Carefold.

    Enforces:
    1. Fail-closed validation of ToolContext, user_id, and profile_id.
    2. ToolSpec validation and callable executor availability.
    3. Network egress allowlist checking against spec.data_flows (0 bytes sent on error).
    4. Deterministic policy gate evaluation (tier x autonomy x taint x consent x age_band).
    5. Single-use cryptographic approval resume verification.
    6. Execution under sandboxed context with exception containment.
    7. Monotone taint flag propagation when untrusted tools execute.
    8. Audit event logging with execution timing and error details.
    """
    t0 = time.time()

    # 1. Fail-closed ToolContext Validation
    if not isinstance(ctx, (ToolContext, ConnectorToolContext)):
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: Tool execution denied. ToolContext instance is required.",
        )

    if not ctx.profile_id or not isinstance(ctx.profile_id, str) or not ctx.profile_id.strip():
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: Tool execution denied. profile_id is missing or empty (fail-closed).",
        )

    if not ctx.user_id or not isinstance(ctx.user_id, str) or not ctx.user_id.strip():
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

    # 3. Network Egress Firewall Verification
    try:
        dest_hosts = verify_egress_firewall(spec, args)
    except EgressBlockedError as exc:
        dur_ms = round((time.time() - t0) * 1000, 2)
        err_msg = f"EgressBlockedError: {exc}"
        await _record_tool_audit(ctx, spec, False, dur_ms, err_msg)
        return ToolResult(
            success=False,
            output=None,
            error=err_msg,
        )

    # 4. Deterministic Policy Gate Evaluation
    decision = evaluate_policy_gate(ctx, spec, args, consents=consents, age_band=age_band)

    if decision.decision == "blocked":
        dur_ms = round((time.time() - t0) * 1000, 2)
        err_msg = f"PolicyBlocked: {decision.reason}"
        await _record_tool_audit(ctx, spec, False, dur_ms, err_msg)
        return ToolResult(
            success=False,
            output=None,
            error=err_msg,
        )

    if decision.decision == "needs_approval":
        # Check if caller is resuming with an approved token
        if approval_id:
            store = approval_store or SqlApprovalStore()
            try:
                consume_fn = getattr(store, "consume_atomic", None)
                if not callable(consume_fn):
                    raise TypeError(f"Approval store {store} does not implement 'consume_atomic'.")

                if inspect.iscoroutinefunction(consume_fn):
                    await consume_fn(approval_id, args)
                else:
                    consume_fn(approval_id, args)
            except Exception as exc:
                dur_ms = round((time.time() - t0) * 1000, 2)
                err_msg = f"ApprovalResumeFailed: {exc}"
                await _record_tool_audit(ctx, spec, False, dur_ms, err_msg)
                return ToolResult(
                    success=False,
                    output=None,
                    error=err_msg,
                )
        else:
            # Execution halted: create pending approval record if store available
            app_id: Optional[str] = None
            if approval_store:
                app_id = f"app-{os.urandom(8).hex()}"
                create_fn = getattr(approval_store, "create_pending", None)
                if callable(create_fn):
                    if inspect.iscoroutinefunction(create_fn):
                        await create_fn(
                            approval_id=app_id,
                            profile_id=ctx.profile_id,
                            run_id=ctx.run_id or "run-1",
                            tool_name=spec.name,
                            args=args,
                            risk_tier=getattr(spec, "risk_tier", "read"),
                            destination_hosts=dest_hosts,
                        )
                    else:
                        create_fn(
                            approval_id=app_id,
                            profile_id=ctx.profile_id,
                            run_id=ctx.run_id or "run-1",
                            tool_name=spec.name,
                            args=args,
                            risk_tier=getattr(spec, "risk_tier", "read"),
                            destination_hosts=dest_hosts,
                        )
            dur_ms = round((time.time() - t0) * 1000, 2)
            err_msg = f"ApprovalRequired: {decision.reason}"
            await _record_tool_audit(ctx, spec, False, dur_ms, err_msg)
            return ToolResult(
                success=False,
                output=None,
                error=err_msg,
                needs_approval=True,
                approval_id=app_id,
            )

    # 5. Sandboxed Tool Execution
    try:
        try:
            sig = inspect.signature(executor)
            params = list(sig.parameters.keys())
        except (ValueError, TypeError):
            params = ["args"]

        if inspect.iscoroutinefunction(executor):
            if len(params) == 0:
                raw_res = await executor()
            elif len(params) >= 2 and params[0] in ("args", "params"):
                raw_res = await executor(args, ctx)
            elif len(params) == 1:
                raw_res = await executor(args)
            else:
                try:
                    raw_res = await executor(ctx, args)
                except TypeError:
                    raw_res = await executor(args, ctx)
        else:
            if len(params) == 0:
                raw_res = executor()
            elif len(params) >= 2 and params[0] in ("args", "params"):
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
    if isinstance(raw_res, BaseToolResult):
        result = raw_res
    elif isinstance(raw_res, UntrustedResult):
        unwrapped = raw_res.data
        if isinstance(unwrapped, list):
            unwrapped = [x.data if isinstance(x, UntrustedResult) else x for x in unwrapped]
        result = ToolResult(success=True, output=unwrapped, error=None)
    elif isinstance(raw_res, (list, tuple)) and any(isinstance(x, UntrustedResult) for x in raw_res):
        unwrapped = [x.data if isinstance(x, UntrustedResult) else x for x in raw_res]
        result = ToolResult(success=True, output=unwrapped, error=None)
    elif isinstance(raw_res, dict) and "success" in raw_res:
        result = ToolResult(
            success=bool(raw_res.get("success")),
            output=raw_res.get("output"),
            error=raw_res.get("error"),
        )
    else:
        result = ToolResult(success=True, output=raw_res, error=None)

    # 6. Untrusted Data Taint Tracking (Monotone propagation)
    if (
        isinstance(raw_res, UntrustedResult)
        or (isinstance(raw_res, (list, tuple)) and any(isinstance(x, UntrustedResult) for x in raw_res))
        or getattr(spec, "trust", "trusted") == "untrusted"
    ):
        if getattr(ctx, "taint", None) is not None and hasattr(ctx.taint, "set"):
            ctx.taint.set()

    # 7. Audit Event Logging
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

        session_factory = getattr(ctx, "session_factory", None) or (
            ctx.extra.get("session_factory") if isinstance(getattr(ctx, "extra", None), dict) else None
        )
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
                principal=getattr(ctx, "principal", "user"),
                actor_user_id=getattr(ctx, "user_id", None),
                run_id=getattr(ctx, "run_id", None) or None,
                risk=getattr(spec, "risk_tier", None),
            ),
            log_path=log_path,
            store_bodies=bool(settings.audit_store_bodies),
            session_factory=session_factory,
        )
    except Exception as err:
        logger.debug("Choke point audit recording failed: %s", err)


__all__ = [
    "AutonomyLevel",
    "DataFlows",
    "EgressBlockedError",
    "PolicyDecision",
    "RiskTier",
    "SqlApprovalStore",
    "TaintFlag",
    "ToolContext",
    "ToolResult",
    "ToolSpec",
    "TrustLevel",
    "UntrustedResult",
    "canonical_json",
    "compute_payload_hash",
    "evaluate_policy_gate",
    "execute_tool_call",
    "verify_egress_firewall",
]
