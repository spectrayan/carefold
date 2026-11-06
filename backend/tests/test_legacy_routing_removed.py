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

"""Regression guard: retired Carefold routing/dispatch modules stay retired.

Chat routing runs through ``yarvelle_core``'s orchestrated ``GraphBuilder``
(configured by ``carefold.engine.runtime``). The forked Carefold builder,
orchestrator, supervisor and dispatcher were removed; these offline checks
make sure they are not silently reintroduced or imported again.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

CAREFOLD_SRC = Path(__file__).resolve().parents[1] / "src" / "carefold"

RETIRED_MODULES = (
    "carefold.engine.builder",
    "carefold.workflows.dispatcher",
    "carefold.workflows.nodes.orchestrator_node",
    "carefold.workflows.nodes.supervisor_node",
    "carefold.workflows.nodes.supervisor",
    "carefold.workflows.subgraphs.supervisor",
)

RETIRED_EXPORTS = {
    "carefold.engine": ("GraphBuilder", "create_agent_graph"),
    "carefold.engine.graph": ("create_agent_graph",),
    "carefold.workflows": ("ExecutionDispatcher",),
    "carefold.workflows.nodes": (
        "OrchestratorDecision",
        "OrchestratorNode",
        "SupervisorNode",
    ),
    "carefold.workflows.subgraphs": (
        "build_supervisor_subgraph",
        "create_supervisor_router_node",
        "create_supervisor_subgraph",
        "route_specialist_return",
        "route_supervisor",
    ),
}


@pytest.mark.parametrize("module_name", RETIRED_MODULES)
def test_retired_module_is_not_importable(module_name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)


@pytest.mark.parametrize("module_name", RETIRED_MODULES)
def test_retired_module_file_is_absent(module_name: str) -> None:
    rel = Path(*module_name.split(".")[1:]).with_suffix(".py")
    assert not (CAREFOLD_SRC / rel).exists(), f"{rel} was reintroduced"


@pytest.mark.parametrize(("package", "names"), sorted(RETIRED_EXPORTS.items()))
def test_package_no_longer_exports_legacy_names(package: str, names: tuple[str, ...]) -> None:
    module = importlib.import_module(package)
    exported = set(getattr(module, "__all__", ()))
    for name in names:
        assert name not in exported, f"{package}.__all__ still exports {name}"
        assert not hasattr(module, name), f"{package} still defines {name}"


def _imported_modules(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.lineno, node.module))
            found.extend(
                (node.lineno, f"{node.module}.{alias.name}") for alias in node.names
            )
    return found


def test_no_source_module_imports_retired_paths() -> None:
    offenders: list[str] = []
    for path in sorted(CAREFOLD_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, name in _imported_modules(tree):
            if any(name == mod or name.startswith(mod + ".") for mod in RETIRED_MODULES):
                offenders.append(f"{path.relative_to(CAREFOLD_SRC)}:{lineno} -> {name}")
    assert not offenders, "retired routing modules imported:\n" + "\n".join(offenders)


def test_runtime_factory_builds_core_orchestrated_service() -> None:
    from yarvelle_core.engine.service import AgentExecutionService as CoreService

    from carefold.engine import AgentExecutionService
    from carefold.engine.runtime import (
        CarefoldAgentExecutionService,
        create_execution_service,
    )
    from carefold.safety.policy import CarefoldHealthSafetyPolicy

    assert AgentExecutionService is CarefoldAgentExecutionService
    service = create_execution_service()
    assert isinstance(service, CoreService)
    assert isinstance(service.safety_policy, CarefoldHealthSafetyPolicy)
    assert service.orchestration is not None
    assert service.default_agent_id == service.orchestration.default_agent


def test_runtime_builds_core_graph_offline() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from carefold.engine.runtime import create_execution_service
    from tests.fixtures.fake_model import FakeListChatModel

    service = create_execution_service()
    graph = service._build_orchestrated_graph(
        FakeListChatModel(responses=["ok"]), MemorySaver(), None
    )
    nodes = set(graph.get_graph().nodes)
    assert {"supervisor", "refusal", "response_synthesizer"} <= nodes
    assert "dispatcher" not in nodes
