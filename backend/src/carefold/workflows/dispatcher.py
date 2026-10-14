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

"""Execution dispatcher for single, parallel, and pipeline agent orchestration (R4).

Coordinates multi-agent execution topologies defined by ExecutionPlan:
- Single: Direct fast-path execution of a single specialist agent.
- Parallel: Concurrent fan-out / fan-in execution via asyncio.gather across multiple specialists.
- Pipeline: Chained sequential execution where downstream specialists ingest upstream outputs.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from langchain_core.language_models.chat_models import BaseChatModel

from carefold.agents.registry import AgentRegistry, get_agent_registry
from carefold.workflows.nodes.agent_execution_node import AgentExecutionNode
from carefold.workflows.nodes.base import BaseNode
from carefold.workflows.state import extract_text_content, get_last_user_message

logger = logging.getLogger(__name__)


class ExecutionDispatcher(BaseNode):
    """Multi-topology execution dispatcher coordinating specialist agent execution."""

    def __init__(
        self,
        agent_runner: Optional[Callable[..., Any]] = None,
        model: Optional[BaseChatModel] = None,
        registry: Optional[AgentRegistry] = None,
        tool_registry: Optional[Any] = None,
        default_tools: Optional[Sequence[Any]] = None,
        name: str = "execution_dispatcher",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, **kwargs)
        self._runner = agent_runner
        self.model = model
        self._registry = registry
        self.tool_registry = tool_registry
        self.default_tools = list(default_tools) if default_tools is not None else None

    @property
    def registry(self) -> AgentRegistry:
        """Lazily resolves AgentRegistry from workspace root if not explicitly injected."""
        if self._registry is None:
            self._registry = get_agent_registry()
        return self._registry

    async def _execute_agent(self, agent_id: str, context: Dict[str, Any]) -> str:
        """Executes a single specialist agent with given context."""
        if self._runner is not None:
            if inspect.iscoroutinefunction(self._runner):
                return await self._runner(agent_id, context)
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._runner, agent_id, context)

        # If model is configured or present in context, invoke real AgentExecutionNode
        model = self.model or context.get("model")
        if model is not None:
            agent_state = dict(context)
            agent_state["current_agent"] = agent_id
            agent_state["agent_id"] = agent_id
            node = AgentExecutionNode(
                model=model,
                registry=self.registry,
                tool_registry=self.tool_registry,
                default_tools=self.default_tools,
            )
            res = await node.execute(agent_state)

            # Tool execution loop for multi-agent dispatched executions
            tool_calls = res.get("tool_calls")
            iteration = 0
            max_iterations = 3
            while tool_calls and iteration < max_iterations:
                iteration += 1
                from carefold.constants.api import SSE_EVENT_TOOL_END, SSE_EVENT_TOOL_START
                from carefold.workflows.nodes.tool_node import ToolNode
                try:
                    from langchain_core.callbacks.manager import adispatch_custom_event
                except ImportError:
                    adispatch_custom_event = None

                for c in tool_calls:
                    if adispatch_custom_event is not None:
                        try:
                            await adispatch_custom_event(
                                SSE_EVENT_TOOL_START,
                                {"type": SSE_EVENT_TOOL_START, "tool": c.get("name"), "params": c.get("args")},
                            )
                        except Exception:
                            pass

                tool_node = ToolNode(
                    allowed_tools=res.get("effective_tools") or self.default_tools,
                    tools=self.default_tools,
                )
                tool_state = dict(agent_state)
                tool_state["messages"] = list(agent_state.get("messages", [])) + list(res.get("messages", []))
                tool_state["tool_calls"] = tool_calls
                tool_state["current_agent"] = agent_id
                prior_traces_count = len(tool_state.get("tool_traces", []))
                tool_res = await tool_node.execute(tool_state)
                new_traces = tool_res.get("tool_traces", [])[prior_traces_count:]

                for trace in new_traces:
                    if adispatch_custom_event is not None:
                        try:
                            await adispatch_custom_event(
                                SSE_EVENT_TOOL_END,
                                {
                                    "type": SSE_EVENT_TOOL_END,
                                    "tool": trace.get("tool"),
                                    "duration_ms": trace.get("duration_ms", 0.0),
                                    "status": "success" if trace.get("allowed") and trace.get("success") else "error",
                                    "allowed": trace.get("allowed", True),
                                    "result": trace.get("output", {}),
                                },
                            )
                        except Exception:
                            pass

                agent_state["messages"] = list(tool_state["messages"]) + list(tool_res.get("messages", []))
                agent_state["tool_traces"] = list(tool_res.get("tool_traces", []))
                if isinstance(context, dict):
                    context["tool_traces"] = list(context.get("tool_traces", [])) + list(new_traces)
                res = await node.execute(agent_state)
                tool_calls = res.get("tool_calls")

            return str(res.get("output", ""))

        # Deterministic default runner when no model and no custom runner are configured
        prompt = context.get("prompt", "")
        if not prompt and context.get("messages"):
            prompt = extract_text_content(get_last_user_message(context))
        prior = context.get("prior_specialist_outputs", {})
        prior_str = f" [Received prior: {list(prior.keys())}]" if prior else ""
        return f"Response from {agent_id} for prompt '{prompt}'{prior_str}"

    def _topological_sort_tasks(self, tasks: List[Any], target_agents: List[str]) -> List[Any]:
        """Sorts tasks topologically by dependencies while preserving stable ordering."""
        if not tasks:
            return list(target_agents)

        task_map: Dict[str, Any] = {}
        deps_map: Dict[str, List[str]] = {}
        for task in tasks:
            aid = getattr(task, "agent_id", None) or (task.get("agent_id") if isinstance(task, dict) else str(task))
            task_map[aid] = task
            deps = getattr(task, "dependencies", None) or getattr(task, "depends_on", None)
            if deps is None and isinstance(task, dict):
                deps = task.get("dependencies") or task.get("depends_on")
            deps_map[aid] = list(deps or [])

        # If no dependencies specified across any tasks, preserve original list
        if not any(deps_map.values()):
            return list(tasks)

        sorted_tasks: List[Any] = []
        visited = set()
        visiting = set()

        def visit(aid: str) -> None:
            if aid in visiting:
                return
            if aid not in visited:
                visiting.add(aid)
                for dep in deps_map.get(aid, []):
                    if dep in task_map:
                        visit(dep)
                visiting.remove(aid)
                visited.add(aid)
                if aid in task_map:
                    sorted_tasks.append(task_map[aid])

        for aid in task_map:
            if aid not in visited:
                visit(aid)

        return sorted_tasks

    async def dispatch(self, state: Dict[str, Any], plan: Optional[Any] = None) -> Dict[str, str]:
        """Dispatches tasks according to plan mode and populates specialist_outputs."""
        if plan is None:
            plan = state.get("execution_plan")

        if plan is None:
            mode_val = "single"
            target_agent = str(state.get("current_agent") or state.get("agent_id") or "visit-steward")
            target_agents = [target_agent] if target_agent else []
            tasks = []
        else:
            if hasattr(plan, "mode"):
                mode_attr = plan.mode
                mode_val = mode_attr.value if hasattr(mode_attr, "value") else str(mode_attr).lower()
            elif isinstance(plan, dict):
                mode_attr = plan.get("mode", "single")
                mode_val = mode_attr.value if hasattr(mode_attr, "value") else str(mode_attr).lower()
            else:
                mode_val = "single"

            if hasattr(plan, "target_agents") and plan.target_agents:
                target_agents = list(plan.target_agents)
            elif isinstance(plan, dict) and plan.get("target_agents"):
                target_agents = list(plan["target_agents"])
            else:
                target_agents = []

            if hasattr(plan, "tasks") and plan.tasks:
                tasks = list(plan.tasks)
            elif isinstance(plan, dict) and plan.get("tasks"):
                tasks = list(plan["tasks"])
            else:
                tasks = []

            if not target_agents and tasks:
                for t in tasks:
                    aid = getattr(t, "agent_id", None) or (t.get("agent_id") if isinstance(t, dict) else str(t))
                    if aid and aid not in target_agents:
                        target_agents.append(aid)

            if not target_agents and not tasks and mode_val == "single":
                target_agent = str(state.get("current_agent") or state.get("agent_id") or "")
                if target_agent:
                    target_agents = [target_agent]

        outputs: Dict[str, str] = {}

        if not target_agents and not tasks:
            state["specialist_outputs"] = outputs
            return outputs

        if mode_val == "single":
            target = target_agents[0]
            context = dict(state)
            context["current_agent"] = target
            context["agent_id"] = target
            if tasks:
                t0 = tasks[0]
                instr = getattr(t0, "instructions", None) or getattr(t0, "task_description", None) or (t0.get("instructions") if isinstance(t0, dict) else None) or (t0.get("task_description") if isinstance(t0, dict) else None)
                if instr:
                    context["orchestrator_instructions"] = instr
            outputs[target] = await self._execute_agent(target, context)

        elif mode_val == "parallel":
            async def run_one(aid: str) -> tuple[str, str]:
                ctx = dict(state)
                ctx["current_agent"] = aid
                ctx["agent_id"] = aid
                # Find matching task instructions if available
                for t in tasks:
                    t_aid = getattr(t, "agent_id", None) or (t.get("agent_id") if isinstance(t, dict) else str(t))
                    if t_aid == aid:
                        instr = getattr(t, "instructions", None) or getattr(t, "task_description", None) or (t.get("instructions") if isinstance(t, dict) else None) or (t.get("task_description") if isinstance(t, dict) else None)
                        if instr:
                            ctx["orchestrator_instructions"] = instr
                        break
                res = await self._execute_agent(aid, ctx)
                return aid, res

            results = await asyncio.gather(*(run_one(aid) for aid in target_agents), return_exceptions=True)
            for res in results:
                if isinstance(res, tuple):
                    aid, text = res
                    outputs[aid] = text
                elif isinstance(res, Exception):
                    self.logger.warning("Parallel specialist '%s' execution failed: %s", aid if 'aid' in locals() else "unknown", res)

        elif mode_val == "pipeline":
            accumulated_outputs: Dict[str, str] = {}
            execution_items = self._topological_sort_tasks(tasks, target_agents)
            for item in execution_items:
                aid = getattr(item, "agent_id", None) or (item.get("agent_id") if isinstance(item, dict) else str(item))
                ctx = dict(state)
                ctx["current_agent"] = aid
                ctx["agent_id"] = aid
                ctx["prior_specialist_outputs"] = dict(accumulated_outputs)

                if accumulated_outputs:
                    prior_summary = "\n\n".join(
                        f"### Prior Output from {prev_id}:\n{prev_out}"
                        for prev_id, prev_out in accumulated_outputs.items()
                    )
                    existing_instr = ctx.get("orchestrator_instructions", "")
                    if existing_instr:
                        ctx["orchestrator_instructions"] = f"{existing_instr}\n\n# PRIOR SPECIALIST OUTPUTS\n{prior_summary}"
                    else:
                        ctx["orchestrator_instructions"] = f"# PRIOR SPECIALIST OUTPUTS\n{prior_summary}"
                    ctx["prior_specialist_context"] = prior_summary

                task_instr = getattr(item, "instructions", None) or getattr(item, "task_description", None) or (item.get("instructions") if isinstance(item, dict) else None) or (item.get("task_description") if isinstance(item, dict) else None)
                if task_instr:
                    current_instr = ctx.get("orchestrator_instructions", "")
                    if current_instr:
                        ctx["orchestrator_instructions"] = f"{current_instr}\n\nTask: {task_instr}"
                    else:
                        ctx["orchestrator_instructions"] = f"Task: {task_instr}"

                res = await self._execute_agent(aid, ctx)
                accumulated_outputs[aid] = res
                outputs[aid] = res

        state["specialist_outputs"] = outputs
        return outputs

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """LangGraph node execution interface."""
        plan = state.get("execution_plan")
        outputs = await self.dispatch(state, plan)
        next_step = "response_synthesizer" if len(outputs) > 1 else "output_guardrail"
        result: Dict[str, Any] = {
            "specialist_outputs": outputs,
            "next_step": next_step,
        }
        if len(outputs) == 1:
            result["output"] = next(iter(outputs.values()))
        return result


__all__ = ["ExecutionDispatcher"]
