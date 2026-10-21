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

"""Sandboxed tool execution node with policy gating and LangGraph interrupt (AU-18).

Enforces:
1. Tool authorization against active agent/skill manifests.
2. Policy gate evaluation (tier x autonomy x taint x consent x age_band).
3. Creation of pending Approval records with canonical payload hashes.
4. LangGraph interrupt(...) pausing for human review.
5. Resumption with single-use atomic token consumption.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse
import uuid

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from yarvelle_core.audit.redaction import redact_tool_args
from yarvelle_core.engine.untrusted_content import wrap_tool_output

from carefold.config import settings
from carefold.constants.api import SSE_EVENT_APPROVAL_REQUIRED
from carefold.db.session import get_session_factory
from carefold.db.models import Approval
from carefold.logging import get_logger
from carefold.tools.registry import CLOSED_TOOL_DEFINITIONS, TOOL_EXECUTORS
from carefold.workflows.nodes.base import BaseNode

logger = get_logger("carefold.workflows.nodes.tool_node")


class ToolNode(BaseNode):
    """Executes tools adhering to the sandboxed permission boundary with HITL interruption."""

    def __init__(
        self,
        allowed_tools: Optional[Sequence[str]] = None,
        tools: Optional[Sequence[Any]] = None,
        name: str = "tools",
        tool_context: Optional[Any] = None,
        approval_store: Optional[Any] = None,
    ) -> None:
        super().__init__(name=name)
        self.allowed_tools = set(allowed_tools) if allowed_tools is not None else None
        self.tools = tools or []
        self.tool_context = tool_context
        self.approval_store = approval_store

    async def execute(
        self,
        state: Dict[str, Any],
        *,
        config: Optional[RunnableConfig] = None,
    ) -> Dict[str, Any]:
        """Executes tool calls through execute_tool_call with LangGraph interrupt support."""
        from carefold.loaders.agent_loader import find_agent_dir, load_agent
        from carefold.engine.tool_exec import (
            EgressBlockedError,
            SqlApprovalStore,
            ToolContext,
            ToolSpec,
            compute_payload_hash,
            evaluate_policy_gate,
            execute_tool_call,
            verify_egress_firewall,
        )
        from carefold.engine.tool_registry import create_default_registry
        default_tool_registry = create_default_registry()

        # Determine allowed tools boundary
        if self.allowed_tools is not None:
            allowed = self.allowed_tools
        elif state.get("effective_tools") is not None:
            allowed = set(state["effective_tools"])
        elif state.get("allowed_tools") is not None:
            allowed = set(state["allowed_tools"])
        else:
            allowed = set(CLOSED_TOOL_DEFINITIONS.keys())

        # Extract tool calls
        tool_calls = list(state.get("tool_calls", []))
        if not tool_calls:
            messages = state.get("messages", [])
            last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
            if last_ai:
                tool_calls = getattr(last_ai, "tool_calls", []) or []

        if not tool_calls:
            return {
                "messages": [],
                "tool_messages": [],
                "tool_traces": list(state.get("tool_traces", [])),
                "tool_output": "",
                "next_step": "tool_validator",
            }

        ws_root = Path(state.get("workspace_root") or settings.workspace_root)
        skills_dir = Path(state.get("skills_dir") or (ws_root / "skills"))
        agent_id = str(state.get("current_agent") or state.get("agent_id") or "carefold-agent")

        agent_obj = None
        skills_list = []
        try:
            agent_dir = find_agent_dir(ws_root / "agents", str(agent_id)) or (ws_root / "agents" / "visit-steward").resolve()
            agent_obj, _, skills_list = load_agent(agent_dir, skills_dir)
        except Exception:
            agent_obj = type("Agent", (), {"id": agent_id, "skills": []})()

        configurable = (config or {}).get("configurable", {})
        raw_ctx = (
            configurable.get("tool_context")
            or getattr(self, "tool_context", None)
            or state.get("tool_context")
        )

        # Check if any tool call is allowed and requires execution
        has_allowed_calls = any(c.get("name") in allowed for c in tool_calls)

        ctx: Optional[ToolContext] = None
        if has_allowed_calls:
            if isinstance(raw_ctx, ToolContext):
                if not raw_ctx.profile_id or not str(raw_ctx.profile_id).strip():
                    raise ValueError(
                        "Security invariant violation: ToolContext requires a non-empty 'profile_id'. Fail-closed."
                    )
                ctx = raw_ctx
            else:
                has_pid_key = "profile_id" in configurable or "profile_id" in state
                p_val = configurable.get("profile_id") if "profile_id" in configurable else state.get("profile_id")
                u_val = configurable.get("user_id") if "user_id" in configurable else state.get("user_id")

                if has_pid_key:
                    if p_val is None or not str(p_val).strip():
                        raise ValueError(
                            "Security invariant violation: ToolContext requires a non-empty 'profile_id'. Fail-closed."
                        )
                    p_id = str(p_val).strip()
                else:
                    p_id = "default_profile"

                u_id = str(u_val or "default_user").strip()
                if not u_id:
                    raise ValueError(
                        "Security invariant violation: ToolContext requires a non-empty 'profile_id'. Fail-closed."
                    )

                autonomy = str(configurable.get("autonomy") or state.get("autonomy") or "A1")
                run_id = str(configurable.get("run_id") or configurable.get("thread_id") or state.get("thread_id") or "run-1")

                ctx = ToolContext(
                    user_id=u_id,
                    profile_id=p_id,
                    run_id=run_id,
                    autonomy=autonomy,  # type: ignore
                    workspace_root=ws_root,
                    skills_dir=skills_dir,
                    agent=agent_obj,
                    effective_tools=tuple(allowed),
                    skills=tuple(skills_list),
                )

        thread_id = str(configurable.get("thread_id") or state.get("thread_id") or (ctx.run_id if ctx else "thread-1"))
        app_store = configurable.get("approval_store") or self.approval_store or SqlApprovalStore()

        tool_messages: List[ToolMessage] = []
        tool_traces: List[Dict[str, Any]] = list(state.get("tool_traces", []))
        last_tool_output: Any = ""

        for call in tool_calls:
            call_id = call.get("id") or f"call_{len(tool_messages)}"
            name = call.get("name", "")
            raw_args = call.get("args")
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except Exception:
                    args = {}
            else:
                args = dict(raw_args) if isinstance(raw_args, dict) else {}

            is_allowed = name in allowed
            if not is_allowed:
                error_msg = f"Tool '{name}' execution denied: undeclared tool for agent '{agent_id}'. Tool '{name}' is not permitted or undeclared for agent '{agent_id}'."
                tool_traces.append({
                    "tool": name,
                    "allowed": False,
                    "status": "denied",
                    "error": error_msg,
                    "duration_ms": 0.0,
                })
                tool_messages.append(
                    ToolMessage(
                        content=json.dumps({"error": error_msg, "success": False}),
                        tool_call_id=call_id,
                        status="error",
                        name=name,
                    )
                )
                last_tool_output = {"error": error_msg}
                continue

            # Resolve ToolSpec
            spec = None
            if self.tools:
                spec = next((t for t in self.tools if getattr(t, "name", None) == name), None)
            if spec is None and default_tool_registry:
                spec = default_tool_registry.get(name)
            if spec is None:
                executor = TOOL_EXECUTORS.get(name) or (lambda args=None, **kw: {"status": "success", "tool": name})
                tool_def = CLOSED_TOOL_DEFINITIONS.get(name, {})
                host = None
                for k in ("url", "endpoint", "target_url"):
                    val = args.get(k)
                    if val and isinstance(val, str):
                        parsed = urlparse(val if "://" in val else f"http://{val}")
                        if parsed.hostname:
                            host = parsed.hostname
                            break
                risk_tier = tool_def.get("risk_tier") or ("write_external" if host else "read")
                data_flows = tool_def.get("data_flows") or ((host,) if host else ())
                spec = ToolSpec(
                    name=name,
                    description=tool_def.get("description", ""),
                    parameters=tool_def.get("parameters", {}),
                    executor=executor,
                    risk_tier=risk_tier,
                    data_flows=data_flows,
                )

            # Check network egress firewall
            try:
                dest_hosts = verify_egress_firewall(spec, args)
            except EgressBlockedError as egress_err:
                error_msg = f"EgressBlockedError: {egress_err}"
                tool_traces.append({
                    "tool": name,
                    "allowed": False,
                    "status": "denied",
                    "error": error_msg,
                    "duration_ms": 0.0,
                })
                tool_messages.append(
                    ToolMessage(
                        content=json.dumps({"error": error_msg, "success": False}),
                        tool_call_id=call_id,
                        status="error",
                        name=name,
                    )
                )
                last_tool_output = {"error": error_msg}
                continue

            # Evaluate policy gate
            decision = evaluate_policy_gate(ctx, spec, args)

            if decision.decision == "needs_approval":
                raw_app_id = f"app_{thread_id}_{call_id}"
                if len(raw_app_id) <= 36:
                    approval_id = raw_app_id
                else:
                    approval_id = f"app_{hashlib.sha256(raw_app_id.encode('utf-8')).hexdigest()[:30]}"
                payload_hash = compute_payload_hash(args)

                # Check if approval already created / decided (idempotent lookup)
                is_resuming = False
                existing_record = None

                if app_store and hasattr(app_store, "get"):
                    if inspect.iscoroutinefunction(app_store.get):
                        existing_record = await app_store.get(approval_id)
                    else:
                        existing_record = app_store.get(approval_id)
                elif app_store and hasattr(app_store, "_records"):
                    existing_record = app_store._records.get(approval_id)

                if existing_record and getattr(existing_record, "status", None) in ("approved", "rejected", "consumed"):
                    is_resuming = True

                # Step 1: Pre-interrupt preparation
                if not is_resuming:
                    if app_store and hasattr(app_store, "create_pending"):
                        try:
                            if inspect.iscoroutinefunction(app_store.create_pending):
                                await app_store.create_pending(
                                    approval_id=approval_id,
                                    profile_id=ctx.profile_id,
                                    run_id=ctx.run_id,
                                    tool_name=spec.name,
                                    args=args,
                                    risk_tier=spec.risk_tier,
                                    destination_hosts=dest_hosts,
                                    thread_id=thread_id,
                                )
                            else:
                                app_store.create_pending(
                                    approval_id=approval_id,
                                    profile_id=ctx.profile_id,
                                    run_id=ctx.run_id,
                                    tool_name=spec.name,
                                    args=args,
                                    risk_tier=spec.risk_tier,
                                    destination_hosts=dest_hosts,
                                )
                        except Exception as store_exc:
                            logger.error(
                                "failed_to_persist_pending_approval",
                                approval_id=approval_id,
                                tool_name=spec.name,
                                profile_id=ctx.profile_id,
                                error=str(store_exc),
                                exc_info=True,
                            )
                            raise RuntimeError(
                                f"Failed to record pending approval '{approval_id}': {store_exc}"
                            ) from store_exc
                    else:
                        # Database fallback
                        try:
                            factory = get_session_factory()
                            async with factory() as session:
                                from datetime import datetime, timedelta, timezone

                                now = datetime.now(timezone.utc)
                                app_record = Approval(
                                    id=approval_id,
                                    profile_id=ctx.profile_id,
                                    run_id=ctx.run_id,
                                    thread_id=thread_id,
                                    tool_name=spec.name,
                                    args_redacted=json.dumps(redact_tool_args(args)),
                                    payload_hash=payload_hash,
                                    destination_hosts=json.dumps(dest_hosts),
                                    risk_tier=spec.risk_tier,
                                    status="pending",
                                    expires_at=now + timedelta(minutes=15),
                                    created_at=now,
                                )
                                session.add(app_record)
                                await session.commit()
                        except Exception as store_exc:
                            logger.error(
                                "failed_to_persist_pending_approval",
                                approval_id=approval_id,
                                tool_name=spec.name,
                                profile_id=ctx.profile_id,
                                error=str(store_exc),
                                exc_info=True,
                            )
                            raise RuntimeError(
                                f"Failed to record pending approval '{approval_id}': {store_exc}"
                            ) from store_exc

                    # Emit SSE approval_required event
                    approval_payload = {
                        "type": SSE_EVENT_APPROVAL_REQUIRED,
                        "approval_id": approval_id,
                        "tool_name": spec.name,
                        "args_redacted": redact_tool_args(args),
                        "payload_hash": payload_hash,
                        "risk_tier": spec.risk_tier,
                        "destination_hosts": dest_hosts,
                        "reason": decision.reason,
                    }
                    await adispatch_custom_event(SSE_EVENT_APPROVAL_REQUIRED, approval_payload)
                else:
                    approval_payload = {"approval_id": approval_id}

                # Step 2: Trigger LangGraph interrupt (pauses execution here)
                resume_data = interrupt(approval_payload)

                # Step 3: Resumed execution handling
                decision_status = (
                    resume_data.get("decision", "approved")
                    if isinstance(resume_data, dict)
                    else "approved"
                )
                effective_args = (
                    resume_data.get("edited_args")
                    if isinstance(resume_data, dict) and resume_data.get("edited_args")
                    else args
                )
                resuming_approval_id = (
                    resume_data.get("approval_id")
                    if isinstance(resume_data, dict) and resume_data.get("approval_id")
                    else approval_id
                )

                if decision_status == "approved":
                    t0 = time.time()
                    res = await execute_tool_call(
                        ctx, spec, effective_args, approval_store=app_store, approval_id=resuming_approval_id
                    )
                    dur_ms = round((time.time() - t0) * 1000, 2)
                    output_val = res.output if res.success else {"error": res.error}
                    status = "success" if res.success else "error"
                else:
                    dur_ms = 0.0
                    output_val = {"error": "Tool execution was rejected by user.", "rejected": True}
                    status = "error"
                    res = None

                tool_traces.append({
                    "tool": name,
                    "allowed": True,
                    "success": (res.success if res else False),
                    "duration_ms": dur_ms,
                    "output": output_val,
                    "audit_logged": True,
                })
                tool_messages.append(
                    ToolMessage(
                        content=wrap_tool_output(name, output_val, trust=getattr(spec, "trust", None)),
                        tool_call_id=call_id,
                        status=status,
                        name=name,
                    )
                )
                last_tool_output = output_val

            else:
                # Normal execution without interruption
                t0 = time.time()
                res = await execute_tool_call(ctx, spec, args, approval_store=app_store)
                dur_ms = round((time.time() - t0) * 1000, 2)

                tool_traces.append({
                    "tool": name,
                    "allowed": True,
                    "success": res.success,
                    "duration_ms": dur_ms,
                    "output": res.output if res.success else {"error": res.error},
                    "audit_logged": True,
                })
                output_val = res.output if res.success else {"error": res.error}
                tool_messages.append(
                    ToolMessage(
                        content=wrap_tool_output(name, output_val, trust=getattr(spec, "trust", None)),
                        tool_call_id=call_id,
                        status="success" if res.success else "error",
                        name=name,
                    )
                )
                last_tool_output = output_val

        return {
            "messages": tool_messages,
            "tool_messages": tool_messages,
            "tool_traces": tool_traces,
            "tool_output": last_tool_output,
            "next_step": "tool_validator",
        }


__all__ = ["ToolNode"]
