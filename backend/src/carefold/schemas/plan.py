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

"""Execution plan schemas for dynamic multi-agent orchestration (R3).

Defines typed schemas for planning execution topologies:
- ExecutionMode: Supported orchestration topologies (single, parallel, pipeline).
- AgentTask: Discrete task assignment with dependencies and required documents.
- ExecutionPlan: Complete orchestration plan coordinating specialist agents.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field, model_validator



class ExecutionMode(str, Enum):
    """Execution topology mode for multi-agent dispatch."""

    SINGLE = "single"
    PARALLEL = "parallel"
    PIPELINE = "pipeline"


class AgentTask(BaseModel):
    """Discrete specialist agent task assignment."""

    agent_id: str = Field(
        ...,
        description="Target specialist agent ID responsible for executing this task.",
    )
    instructions: str = Field(
        default="",
        description="Focused clinical or navigation instructions for the agent.",
    )
    task_description: str = Field(
        default="",
        description="Human-readable description of the delegated task.",
    )
    priority: int = Field(
        default=1,
        description="Execution priority level (1 = highest).",
    )
    depends_on: List[str] = Field(
        default_factory=list,
        description="List of agent IDs or task IDs that must complete before this task.",
    )
    dependencies: List[str] = Field(
        default_factory=list,
        description="Alias for depends_on indicating prerequisite agent dependencies.",
    )
    required_docs: List[str] = Field(
        default_factory=list,
        description="Specific reference doc filenames required for task execution.",
    )

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _sync_input_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Sync instructions and task_description
            if "task_description" in data and not data.get("instructions"):
                data["instructions"] = data["task_description"]
            elif "instructions" in data and not data.get("task_description"):
                data["task_description"] = data["instructions"]

            # Sync depends_on and dependencies
            if "dependencies" in data and not data.get("depends_on"):
                data["depends_on"] = data["dependencies"]
            elif "depends_on" in data and not data.get("dependencies"):
                data["dependencies"] = data["depends_on"]
        return data

    @model_validator(mode="after")
    def _sync_model_aliases(self) -> AgentTask:
        if self.task_description and not self.instructions:
            self.instructions = self.task_description
        elif self.instructions and not self.task_description:
            self.task_description = self.instructions

        if self.dependencies and not self.depends_on:
            self.depends_on = list(self.dependencies)
        elif self.depends_on and not self.dependencies:
            self.dependencies = list(self.depends_on)
        return self


class ExecutionPlan(BaseModel):
    """Typed execution plan produced by Orchestrator for multi-agent coordination."""

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the execution plan.",
    )
    intent: Optional[str] = Field(
        default=None,
        description="Optional high-level user intent (e.g. visit_prep, log_vitals, remind_me).",
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Input parameters associated with the template intent.",
    )
    steps: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Step-by-step pipeline execution breakdown.",
    )
    status: str = Field(
        default="compiled",
        description="Lifecycle status of the plan (e.g. draft, compiled, executed).",
    )
    mode: ExecutionMode = Field(
        default=ExecutionMode.SINGLE,
        description="Topological execution mode: single, parallel, or pipeline.",
    )
    target_agents: List[str] = Field(
        default_factory=list,
        description="List of target specialist agent IDs in execution order.",
    )
    tasks: List[AgentTask] = Field(
        default_factory=list,
        description="Ordered list of discrete agent tasks to execute.",
    )
    reasoning: str = Field(
        default="",
        description="Rationale explaining topology selection and agent delegation.",
    )

    def __getitem__(self, item: str) -> Any:
        """Enables dictionary-style subscripting for plan['intent'], plan['steps'], etc."""
        if hasattr(self, item):
            val = getattr(self, item)
            if isinstance(val, Enum):
                return val.value
            return val
        raise KeyError(item)

    def __contains__(self, item: str) -> bool:
        """Enables 'intent in plan' checks."""
        return hasattr(self, item) or item in self.__dict__

    def get(self, item: str, default: Any = None) -> Any:
        """Enables dict-like .get(key, default) access."""
        if hasattr(self, item):
            val = getattr(self, item)
            if isinstance(val, Enum):
                return val.value
            return val
        return default

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the ExecutionPlan into a JSON-compatible dictionary."""
        d = self.model_dump()
        if isinstance(d.get("mode"), Enum):
            d["mode"] = d["mode"].value
        return d


__all__ = [
    "AgentTask",
    "ExecutionMode",
    "ExecutionPlan",
]

