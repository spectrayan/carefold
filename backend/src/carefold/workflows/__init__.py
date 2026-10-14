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

"""Carefold Workflows Package.

Houses class-based LangGraph nodes, multi-agent subgraphs, and the unified
AgentState schema following SOLID principles.
"""

from __future__ import annotations

from carefold.workflows.dispatcher import ExecutionDispatcher
from carefold.workflows.nodes.base import BaseNode
from carefold.workflows.state import (
    AgentState,
    create_initial_state,
    extract_text_content,
    get_last_message,
    get_last_user_message,
    get_last_user_prompt_text,
)

__all__ = [
    "AgentState",
    "BaseNode",
    "ExecutionDispatcher",
    "create_initial_state",
    "extract_text_content",
    "get_last_message",
    "get_last_user_message",
    "get_last_user_prompt_text",
]
