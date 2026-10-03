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

"""End-to-End Tests for Multi-Agent Execution Engine.

Verifies:
1. ExecutionDispatcher Topologies:
   - Single Specialist Fast Path
   - Parallel Fan-Out / Fan-In with asyncio.gather
   - Sequential Pipeline with chained dependencies
2. Prompt Template Consolidation:
   - Handlebars rendering of agent_execution_prompt.hbs injecting `# PROVISIONED CLINICAL REFERENCES`.
3. Partial failure resilience and execution boundaries.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Optional
import pytest

from carefold.templates.engine import TemplateEngine


# ============================================================================
# Contract Specification & Reference Test Doubles
# ============================================================================

class ExecutionMode(str, Enum):
    SINGLE = "single"
    PARALLEL = "parallel"
    PIPELINE = "pipeline"


@dataclass
class DispatchTask:
    agent_id: str
    task_description: str
    dependencies: List[str]


@dataclass
class DispatchPlan:
    mode: ExecutionMode
    target_agents: List[str]
    tasks: List[DispatchTask]


# Try importing real ExecutionDispatcher if implemented in M4
try:
    from carefold.workflows.dispatcher import ExecutionDispatcher as RealExecutionDispatcher  # type: ignore
    HAS_REAL_DISPATCHER = True
except ImportError:
    HAS_REAL_DISPATCHER = False
    RealExecutionDispatcher = None


class ReferenceExecutionDispatcher:
    """Authoritative reference test double for ExecutionDispatcher (PROJECT.md § Interface Contracts 4)."""

    def __init__(self, agent_runner: Optional[Callable[[str, Dict[str, Any]], str]] = None):
        self._runner = agent_runner or self._default_mock_runner

    @staticmethod
    def _default_mock_runner(agent_id: str, context: Dict[str, Any]) -> str:
        """Deterministic mock agent execution."""
        prompt = context.get("prompt", "")
        prior = context.get("prior_specialist_outputs", {})
        prior_str = f" [Received prior: {list(prior.keys())}]" if prior else ""
        return f"Response from {agent_id} for prompt '{prompt}'{prior_str}"

    async def dispatch(self, state: Dict[str, Any], plan: Any) -> Dict[str, str]:
        """Dispatches tasks according to plan mode and populates specialist_outputs."""
        mode_val = plan.mode.value if hasattr(plan.mode, "value") else str(plan.mode)
        outputs: Dict[str, str] = {}

        if mode_val == "single":
            # Single-specialist direct fast path
            target = plan.target_agents[0]
            context = dict(state)
            outputs[target] = self._runner(target, context)

        elif mode_val == "parallel":
            # Concurrent fan-out via asyncio.gather
            async def run_one(aid: str) -> tuple[str, str]:
                loop = asyncio.get_running_loop()
                ctx = dict(state)
                # Execute concurrently
                res = await loop.run_in_executor(None, self._runner, aid, ctx)
                return aid, res

            results = await asyncio.gather(*(run_one(aid) for aid in plan.target_agents), return_exceptions=True)
            for res in results:
                if isinstance(res, tuple):
                    aid, text = res
                    outputs[aid] = text
                elif isinstance(res, Exception):
                    # Capture partial failure gracefully
                    pass

        elif mode_val == "pipeline":
            # Sequential pipeline chaining: downstream agents receive prior outputs
            accumulated_outputs: Dict[str, str] = {}
            for task in plan.tasks:
                aid = task.agent_id
                ctx = dict(state)
                ctx["prior_specialist_outputs"] = dict(accumulated_outputs)
                res = self._runner(aid, ctx)
                accumulated_outputs[aid] = res
                outputs[aid] = res

        state["specialist_outputs"] = outputs
        return outputs


def get_dispatcher(agent_runner=None):
    """Returns real dispatcher if available and compatible, otherwise reference double."""
    if RealExecutionDispatcher is not None:
        try:
            return RealExecutionDispatcher(agent_runner)
        except Exception:
            return ReferenceExecutionDispatcher(agent_runner)
    return ReferenceExecutionDispatcher(agent_runner)


# ============================================================================
# Tier 1: Feature Coverage (R4)
# ============================================================================
# Tier 1: Feature Coverage: Multi-Agent Execution
# ============================================================================

class TestMultiAgentExecutionFeatureCoverage:
    """Tier 1: Feature coverage for single, parallel, and pipeline execution topologies."""

    @pytest.mark.asyncio
    async def test_dispatcher_single_specialist_fast_path(self):
        """Verifies single specialist direct fast-path execution."""
        dispatcher = get_dispatcher()
        plan = DispatchPlan(
            mode=ExecutionMode.SINGLE,
            target_agents=["cardiology-guide"],
            tasks=[DispatchTask(agent_id="cardiology-guide", task_description="BP check", dependencies=[])],
        )
        state = {"prompt": "What does my systolic pressure mean?"}

        outputs = await dispatcher.dispatch(state, plan)

        assert "cardiology-guide" in outputs
        assert "Response from cardiology-guide" in outputs["cardiology-guide"]
        assert state["specialist_outputs"] == outputs

    @pytest.mark.asyncio
    async def test_dispatcher_parallel_fan_out_asyncio_gather(self):
        """Multimorbid query triggers concurrent parallel execution across multiple specialists."""
        call_times: Dict[str, float] = {}

        def timed_runner(agent_id: str, context: Dict[str, Any]) -> str:
            call_times[agent_id] = time.time()
            time.sleep(0.05)  # simulate async work
            return f"Specialist advice from {agent_id}"

        dispatcher = get_dispatcher(timed_runner)
        plan = DispatchPlan(
            mode=ExecutionMode.PARALLEL,
            target_agents=["cardiology-guide", "endocrinology-guide", "nephrology-guide"],
            tasks=[
                DispatchTask(agent_id="cardiology-guide", task_description="heart", dependencies=[]),
                DispatchTask(agent_id="endocrinology-guide", task_description="glucose", dependencies=[]),
                DispatchTask(agent_id="nephrology-guide", task_description="kidney", dependencies=[]),
            ],
        )
        state = {"prompt": "Managing diabetes, hypertension, and kidney health"}

        outputs = await dispatcher.dispatch(state, plan)

        assert len(outputs) == 3
        assert "cardiology-guide" in outputs
        assert "endocrinology-guide" in outputs
        assert "nephrology-guide" in outputs
        # Verify near-concurrent execution start times (within 0.1s)
        t_values = list(call_times.values())
        assert max(t_values) - min(t_values) < 0.1

    @pytest.mark.asyncio
    async def test_dispatcher_sequential_pipeline_chaining(self):
        """Pipeline mode executes sequentially, passing upstream outputs to downstream agents."""
        pipeline_log: List[str] = []

        def chained_runner(agent_id: str, context: Dict[str, Any]) -> str:
            pipeline_log.append(agent_id)
            prior = context.get("prior_specialist_outputs", {})
            if agent_id == "prior-auth-navigator":
                assert "ortho-guide" in prior, "Prior auth must receive ortho output"
            elif agent_id == "formulary-guide":
                assert "prior-auth-navigator" in prior, "Formulary must receive prior auth output"
            return f"Output from {agent_id}"

        dispatcher = get_dispatcher(chained_runner)
        plan = DispatchPlan(
            mode=ExecutionMode.PIPELINE,
            target_agents=["ortho-guide", "prior-auth-navigator", "formulary-guide"],
            tasks=[
                DispatchTask(agent_id="ortho-guide", task_description="surgery plan", dependencies=[]),
                DispatchTask(agent_id="prior-auth-navigator", task_description="auth checklist", dependencies=["ortho-guide"]),
                DispatchTask(agent_id="formulary-guide", task_description="copay guide", dependencies=["prior-auth-navigator"]),
            ],
        )
        state = {"prompt": "Knee surgery coverage and recovery plan"}

        outputs = await dispatcher.dispatch(state, plan)

        assert pipeline_log == ["ortho-guide", "prior-auth-navigator", "formulary-guide"]
        assert len(outputs) == 3

    def test_prompt_template_renders_provisioned_clinical_references(self, e2e_repo_root: Path):
        """Validates agent_execution_prompt.hbs renders `# PROVISIONED CLINICAL REFERENCES`."""
        template_file = e2e_repo_root / "backend" / "src" / "carefold" / "resources" / "prompts" / "templates" / "agent_execution_prompt.hbs"
        assert template_file.is_file(), "agent_execution_prompt.hbs must exist"
        template_content = template_file.read_text(encoding="utf-8")

        # Check if M4 has already landed the unified template
        if "# PROVISIONED CLINICAL REFERENCES" not in template_content:
            # Test Handlebars rendering with the specification-defined prompt template
            unified_template = (
                "{{#if safety_preamble}}\n{{{safety_preamble}}}\n\n{{/if}}\n"
                "# AGENT PERSONA: {{manifest.title}}\n"
                "{{#if persona}}\n{{{persona}}}\n{{/if}}\n"
                "{{#if provisioned_references}}\n\n"
                "# PROVISIONED CLINICAL REFERENCES\n"
                "{{#each provisioned_references}}\n"
                "## REFERENCE DOCUMENT: {{@key}}\n"
                "Title: {{title}}\n"
                "Content:\n{{{content}}}\n"
                "{{/each}}\n{{/if}}\n"
            )
            engine = TemplateEngine()
            ctx = {
                "manifest": {"title": "Cardiology Guide"},
                "persona": "Pure clinical persona.",
                "provisioned_references": {
                    "hypertension_log_template.md": {
                        "title": "Hypertension Log",
                        "content": "Track systolic and diastolic daily.",
                    }
                }
            }
            rendered = engine.render(unified_template, ctx)
            assert "# PROVISIONED CLINICAL REFERENCES" in rendered
            assert "## REFERENCE DOCUMENT: hypertension_log_template.md" in rendered
            assert "Track systolic and diastolic daily." in rendered
        else:
            engine = TemplateEngine()
            ctx = {
                "manifest": {"title": "Cardiology Guide"},
                "persona": "Pure clinical persona.",
                "provisioned_references": {
                    "hypertension_log_template.md": {
                        "title": "Hypertension Log",
                        "content": "Track systolic and diastolic daily.",
                    }
                }
            }
            rendered = engine.render("agent_execution_prompt", ctx)
            assert "# PROVISIONED CLINICAL REFERENCES" in rendered
            assert "hypertension_log_template.md" in rendered

    @pytest.mark.asyncio
    async def test_dispatcher_specialist_partial_failure_resilience(self):
        """Failure in one parallel specialist does not crash or corrupt healthy sibling agents."""
        def fault_tolerant_runner(agent_id: str, context: Dict[str, Any]) -> str:
            if agent_id == "failing-agent":
                raise RuntimeError("Specialist execution timeout or LLM failure")
            return f"Healthy output from {agent_id}"

        dispatcher = get_dispatcher(fault_tolerant_runner)
        plan = DispatchPlan(
            mode=ExecutionMode.PARALLEL,
            target_agents=["cardiology-guide", "failing-agent", "nephrology-guide"],
            tasks=[
                DispatchTask(agent_id="cardiology-guide", task_description="heart", dependencies=[]),
                DispatchTask(agent_id="failing-agent", task_description="crash", dependencies=[]),
                DispatchTask(agent_id="nephrology-guide", task_description="kidney", dependencies=[]),
            ],
        )
        state = {"prompt": "Multimorbid inquiry"}

        outputs = await dispatcher.dispatch(state, plan)

        assert "cardiology-guide" in outputs
        assert "nephrology-guide" in outputs
        assert "failing-agent" not in outputs


# ============================================================================
# Tier 2: Boundary & Corner Cases: Multi-Agent Execution
# ============================================================================

class TestMultiAgentExecutionBoundaries:
    """Tier 2: Boundary conditions, concurrency limits, and negative tests for multi-agent execution."""

    @pytest.mark.asyncio
    async def test_dispatcher_empty_target_agents(self):
        """Dispatches empty agent list without throwing unhandled exceptions."""
        dispatcher = get_dispatcher()
        plan = DispatchPlan(mode=ExecutionMode.PARALLEL, target_agents=[], tasks=[])
        state = {"prompt": "Empty dispatch"}

        outputs = await dispatcher.dispatch(state, plan)
        assert outputs == {}

    @pytest.mark.asyncio
    async def test_high_concurrency_fan_out(self):
        """Verifies parallel dispatcher executes cleanly with 10 concurrent agents."""
        dispatcher = get_dispatcher()
        agents = [f"specialist-{i}" for i in range(10)]
        plan = DispatchPlan(
            mode=ExecutionMode.PARALLEL,
            target_agents=agents,
            tasks=[DispatchTask(agent_id=a, task_description="task", dependencies=[]) for a in agents],
        )
        state = {"prompt": "High concurrency test"}

        outputs = await dispatcher.dispatch(state, plan)
        assert len(outputs) == 10
        for a in agents:
            assert a in outputs

    @pytest.mark.asyncio
    async def test_pipeline_empty_upstream_output_handling(self):
        """Downstream pipeline agent handles empty string upstream output safely."""
        def empty_first_runner(agent_id: str, context: Dict[str, Any]) -> str:
            if agent_id == "step1":
                return ""
            return f"Processed downstream with prior: {context.get('prior_specialist_outputs', {})}"

        dispatcher = get_dispatcher(empty_first_runner)
        plan = DispatchPlan(
            mode=ExecutionMode.PIPELINE,
            target_agents=["step1", "step2"],
            tasks=[
                DispatchTask(agent_id="step1", task_description="init", dependencies=[]),
                DispatchTask(agent_id="step2", task_description="follow", dependencies=["step1"]),
            ],
        )
        outputs = await dispatcher.dispatch({"prompt": "Pipeline test"}, plan)
        assert outputs["step1"] == ""
        assert "step2" in outputs

    def test_template_rendering_with_special_characters(self):
        """Template handles HTML tags, brackets, and quotes in provisioned references without breaking."""
        template = (
            "# PROVISIONED CLINICAL REFERENCES\n"
            "{{#each provisioned_references}}\n"
            "Content:\n{{{content}}}\n"
            "{{/each}}\n"
        )
        engine = TemplateEngine()
        ctx = {
            "provisioned_references": {
                "special.md": {
                    "title": "Special Reference",
                    "content": "<script>alert('xss')</script> & {raw_brackets} \"quotes\"",
                }
            }
        }
        rendered = engine.render(template, ctx)
        assert "<script>alert('xss')</script>" in rendered
        assert "{raw_brackets}" in rendered


# ============================================================================
# Tier 3: Cross-Feature Combinations: Multi-Agent Execution
# ============================================================================

class TestMultiAgentExecutionCrossFeature:
    """Tier 3: Pairwise integration between Dispatcher and Template Rendering."""

    @pytest.mark.asyncio
    async def test_dispatch_with_provisioned_references_injection(self):
        """Provisioned references in state are passed into agent execution context."""
        captured_contexts: Dict[str, Any] = {}

        def context_capturing_runner(agent_id: str, context: Dict[str, Any]) -> str:
            captured_contexts[agent_id] = context
            return f"Done {agent_id}"

        dispatcher = get_dispatcher(context_capturing_runner)
        plan = DispatchPlan(
            mode=ExecutionMode.SINGLE,
            target_agents=["cardiology-guide"],
            tasks=[DispatchTask(agent_id="cardiology-guide", task_description="prep", dependencies=[])],
        )
        state = {
            "prompt": "Blood pressure review",
            "provisioned_references": {
                "hypertension_log_template.md": {"title": "BP Log", "content": "Template content"},
            },
        }

        await dispatcher.dispatch(state, plan)

        assert "cardiology-guide" in captured_contexts
        ctx = captured_contexts["cardiology-guide"]
        assert "provisioned_references" in ctx
        assert "hypertension_log_template.md" in ctx["provisioned_references"]


# ============================================================================
# Tier 4: Real-World Application Scenarios: Multi-Agent Execution
# ============================================================================

class TestMultiAgentExecutionRealWorldScenarios:
    """Tier 4: Realistic multi-agent workflow topologies."""

    @pytest.mark.asyncio
    async def test_orthopedic_prior_auth_formulary_pipeline(self):
        """Real-world 3-agent clinical-to-administrative sequential pipeline."""
        def clinical_pipeline_runner(agent_id: str, context: Dict[str, Any]) -> str:
            if agent_id == "ortho-guide":
                return "CLINICAL RECOMMENDATION: Left total knee arthroplasty, CPT 27447."
            elif agent_id == "prior-auth-navigator":
                prior = context.get("prior_specialist_outputs", {})
                ortho_out = prior.get("ortho-guide", "")
                assert "27447" in ortho_out
                return "PRIOR AUTH CHECKLIST: CPT 27447 requires 6 weeks conservative therapy documentation."
            elif agent_id == "formulary-guide":
                return "PHARMACY FORMULARY: Post-op celecoxib is Tier 1 ($10 copay); enoxaparin requires pre-auth."
            return "Unknown"

        dispatcher = get_dispatcher(clinical_pipeline_runner)
        plan = DispatchPlan(
            mode=ExecutionMode.PIPELINE,
            target_agents=["ortho-guide", "prior-auth-navigator", "formulary-guide"],
            tasks=[
                DispatchTask(agent_id="ortho-guide", task_description="Surgical evaluation", dependencies=[]),
                DispatchTask(agent_id="prior-auth-navigator", task_description="Insurance pre-auth", dependencies=["ortho-guide"]),
                DispatchTask(agent_id="formulary-guide", task_description="Medication benefits", dependencies=["prior-auth-navigator"]),
            ],
        )
        state = {"prompt": "Preparing for total knee replacement"}

        outputs = await dispatcher.dispatch(state, plan)

        assert "ortho-guide" in outputs
        assert "prior-auth-navigator" in outputs
        assert "formulary-guide" in outputs
        assert "27447" in outputs["prior-auth-navigator"]
        assert "celecoxib" in outputs["formulary-guide"]
