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

"""Carefold engine package.

Streamlined execution engine exposing GraphBuilder, AgentExecutionService,
prompt assembly, and runtime execution facade.
"""

from __future__ import annotations

from carefold.engine.agent_factory import (
    create_carefold_agent,
    load_all_subagents,
    load_subagent_from_yaml,
)
from carefold.engine.builder import GraphBuilder, create_agent_graph
from carefold.engine.prompt_builder import build_system_prompt
from carefold.engine.runner import ExecutionContext, execute_agent_run
from carefold.engine.service import AgentExecutionService

__all__ = [
    "AgentExecutionService",
    "ExecutionContext",
    "GraphBuilder",
    "build_system_prompt",
    "create_agent_graph",
    "create_carefold_agent",
    "execute_agent_run",
    "load_all_subagents",
    "load_subagent_from_yaml",
]
