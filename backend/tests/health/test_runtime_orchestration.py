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

"""Production runtime uses core orchestration; red flags refuse first, attachments route first."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import carefold.schemas.manifest  # registers clinical AgentDomain
from carefold.engine.runtime import CarefoldAgentExecutionService, create_execution_service
from carefold.safety.policy import CarefoldHealthSafetyPolicy
from yarvelle_core.engine.orchestration.routing import select_fixed_route
from yarvelle_core.workflows.nodes.input_guardrail_node import InputGuardrailNode
from yarvelle_core.workflows.nodes.orchestrator_node import OrchestratorNode


REPO_ROOT = Path(__file__).resolve().parents[3]
AGENTS_ROOT = REPO_ROOT / "agents"


class _CountingChatModel(BaseChatModel):
    """Records invocations so fixed-route turns can assert no model router call."""

    call_bucket: Dict[str, int] = {"n": 0}

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Fresh mutable counter per instance (avoid shared ClassVar state).
        object.__setattr__(self, "call_bucket", {"n": 0})

    @property
    def calls(self) -> int:
        return int(self.call_bucket.get("n", 0))

    @property
    def _llm_type(self) -> str:
        return "counting-chat"

    def _generate(
        self,
        messages: List[Any],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.call_bucket["n"] = self.calls + 1
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="model-should-not-route"))]
        )

    async def _agenerate(
        self,
        messages: List[Any],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def test_no_legacy_runtime_feature_flag() -> None:
    """Production path must not gate on a legacy runtime / planner flag."""
    banned = (
        "USE_CORE_RUNTIME",
        "LEGACY_RUNTIME",
        "planner: legacy",
        "CAREFold_LEGACY_ENGINE",
        "CAREFOLD_LEGACY_RUNTIME",
    )
    for key in banned:
        assert os.environ.get(key) in (None, "")
    svc = create_execution_service()
    assert isinstance(svc, CarefoldAgentExecutionService)
    assert svc.orchestration is not None
    assert svc.routes_turns is True


def test_health_policy_raises_red_flag_for_emergency_text() -> None:
    policy = CarefoldHealthSafetyPolicy()
    flags = policy.check_flags(
        "I have crushing chest pain radiating to my left arm and a cold sweat"
    )
    assert flags == ["red_flag"]
    assert policy.check_flags("How do I prepare for a routine checkup?") == []


@pytest.mark.asyncio
async def test_routing_guardrail_refuses_emergency_with_red_flag() -> None:
    """Live emergencies hard-refuse with the vetted referral; red_flag is still raised for audit."""
    node = InputGuardrailNode(safety_policy=CarefoldHealthSafetyPolicy())
    state = {
        "messages": [
            HumanMessage(
                content="I have crushing chest pain radiating to my jaw and cold sweat"
            )
        ]
    }
    out = await node.execute(state)
    assert out.get("refused") is True
    assert out.get("next_step") == "refusal"
    assert "red_flag" in (out.get("guardrail_flags") or [])
    assert out.get("emergency_red_flags") is not None
    assert out.get("refusal_message")


def test_red_flag_has_no_fixed_route_to_triage_auditor() -> None:
    """A red flag never routes to triage-auditor, whose audit text is internal."""
    from carefold import get_pack

    orch = get_pack().orchestration
    assert orch is not None
    state = {"guardrail_flags": ["red_flag"], "messages": []}
    assert select_fixed_route(orch, state) is None


def test_document_attachment_fixed_route() -> None:
    from carefold import get_pack

    orch = get_pack().orchestration
    state = {
        "attachments": [{"mime_type": "application/pdf", "name": "eob.pdf"}],
        "guardrail_flags": [],
        "messages": [],
    }
    decision = select_fixed_route(orch, state)
    assert decision is not None
    assert decision.agent_id == "document-extractor"
    assert decision.route_id == "document-intake"


def test_carefold_checkpoint_env_aliases_apply_to_settings() -> None:
    from types import SimpleNamespace

    from carefold.checkpoint_env import apply_checkpoint_env_aliases

    env = {
        "CAREFOLD_CHECKPOINT_ENCRYPTION": "true",
        "CAREFOLD_CHECKPOINT_PLAINTEXT_READS": " off ",
        "CAREFOLD_CHECKPOINT_KEY_VERSION": "2",
        "YARVELLE_CORE_CHECKPOINT_KEY_VERSION": "1",
    }
    target = SimpleNamespace(
        checkpoint_encryption=False,
        checkpoint_plaintext_reads=True,
        checkpoint_key_version=1,
    )
    applied = apply_checkpoint_env_aliases(env, target)

    assert applied == {
        "checkpoint_encryption": True,
        "checkpoint_plaintext_reads": False,
        "checkpoint_key_version": 2,
    }
    assert target.checkpoint_encryption is True
    assert target.checkpoint_plaintext_reads is False
    assert target.checkpoint_key_version == 2
    # Carefold-prefixed values win and are mirrored for core Settings / CLI.
    assert env["YARVELLE_CORE_CHECKPOINT_ENCRYPTION"] == "true"
    assert env["YARVELLE_CORE_CHECKPOINT_PLAINTEXT_READS"] == "off"
    assert env["YARVELLE_CORE_CHECKPOINT_KEY_VERSION"] == "2"


@pytest.mark.parametrize(
    "name,value",
    [
        ("CAREFOLD_CHECKPOINT_ENCRYPTION", "maybe"),
        ("CAREFOLD_CHECKPOINT_PLAINTEXT_READS", ""),
        ("CAREFOLD_CHECKPOINT_KEY_VERSION", "0"),
        ("CAREFOLD_CHECKPOINT_KEY_VERSION", "two"),
    ],
)
def test_carefold_checkpoint_env_aliases_ignore_blank_or_invalid(name: str, value: str) -> None:
    from types import SimpleNamespace

    from carefold.checkpoint_env import apply_checkpoint_env_aliases

    env = {name: value}
    target = SimpleNamespace(
        checkpoint_encryption=False,
        checkpoint_plaintext_reads=True,
        checkpoint_key_version=1,
    )
    assert apply_checkpoint_env_aliases(env, target) == {}
    assert (target.checkpoint_encryption, target.checkpoint_plaintext_reads) == (False, True)
    assert target.checkpoint_key_version == 1
    assert not any(k.startswith("YARVELLE_CORE_") for k in env)


def test_carefold_checkpoint_env_aliases_reach_core_settings_at_import() -> None:
    """Importing carefold in a fresh interpreter applies the aliases to core settings."""
    import subprocess
    import sys

    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CAREFOLD_CHECKPOINT_", "YARVELLE_CORE_CHECKPOINT_"))
    }
    env.update(
        {
            "CAREFOLD_CHECKPOINT_ENCRYPTION": "true",
            "CAREFOLD_CHECKPOINT_PLAINTEXT_READS": "false",
            "CAREFOLD_CHECKPOINT_KEY_VERSION": "3",
            "PYTHONPATH": str(REPO_ROOT / "backend" / "src"),
        }
    )
    code = (
        "import carefold\n"
        "from yarvelle_core.config import settings as s\n"
        "from yarvelle_core.vault.checkpoints import checkpoint_encryption_enabled\n"
        "print(s.checkpoint_encryption, s.checkpoint_plaintext_reads,"
        " s.checkpoint_key_version, checkpoint_encryption_enabled())\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    assert out.stdout.strip().splitlines()[-1] == "True False 3 True"


@pytest.mark.asyncio
async def test_db_created_agent_explicit_route(temp_workspace: Path) -> None:
    """Explicit / DB-selected agent ids still route without silent substitution."""
    from carefold import get_pack
    from carefold.agents.registry import AgentRegistry
    from carefold.loaders.agent_loader import load_agent

    orch = get_pack().orchestration
    agents_dir = temp_workspace / "agents"
    custom = agents_dir / "custom-db-agent"
    custom.mkdir(parents=True)
    (custom / "agent.yaml").write_text(
        "id: custom-db-agent\n"
        "title: Custom DB Agent\n"
        "version: 0.1.0\n"
        "domain: clinical\n"
        "category: health.custom\n"
        "hidden: false\n"
        "can_delegate: false\n"
        "description: DB-created specialist\n"
        "tools: []\n"
        "skills: []\n",
        encoding="utf-8",
    )
    (custom / "persona.md").write_text("You are a custom DB agent.\n", encoding="utf-8")
    registry = AgentRegistry(agents_dir, temp_workspace / "skills")
    assert registry.get("custom-db-agent") is not None

    model = _CountingChatModel()
    node = OrchestratorNode(
        model=model,
        registry=registry,
        orchestration=orch,
        default_agent=orch.default_agent,
    )
    state = {
        "messages": [HumanMessage(content="Help with my custom request")],
        "explicit_agent": "custom-db-agent",
        "guardrail_flags": [],
    }
    result = await node.execute(state)
    assert result.get("current_agent") == "custom-db-agent"
    assert model.calls == 0


@pytest.mark.asyncio
async def test_existing_thread_resume_state_keeps_orchestration_defaults() -> None:
    """Service keeps pack orchestration for resumed threads (no legacy flag)."""
    svc = create_execution_service()
    assert svc.orchestration is not None
    assert svc.orchestration.default_agent == "appointment-prep-coordinator"
    assert [r.route_id for r in svc.orchestration.fixed_routes] == ["document-intake"]
    assert svc.routes_turns is True


@pytest.mark.asyncio
async def test_synthesizer_uses_carefold_disclaimer_and_turn_label() -> None:
    """Synthesized output and the persisted turn carry Carefold's disclaimer, not core's."""
    from langgraph.store.memory import InMemoryStore

    from carefold.engine.response_synthesizer import (
        CAREFOLD_CANONICAL_DISCLAIMER,
        CarefoldResponseSynthesizerNode,
    )
    from yarvelle_core.workflows.nodes.response_synthesizer_node import (
        CANONICAL_DISCLAIMER as CORE_DISCLAIMER,
    )

    store = InMemoryStore()
    node = CarefoldResponseSynthesizerNode()
    state = {
        "thread_id": "th_synth_brand",
        "prompt": "Help me prepare for my cardiology visit",
        "messages": [HumanMessage(content="Help me prepare for my cardiology visit")],
        "specialist_outputs": {
            "heart-care-coordinator": "Bring your blood pressure log.",
            "kidney-care-coordinator": "Bring recent lab results.",
        },
    }
    result = await node.execute(state, store=store)

    output = str(result["output"])
    assert output.rstrip().endswith(CAREFOLD_CANONICAL_DISCLAIMER)
    assert CORE_DISCLAIMER not in output
    assert "Yarvelle" not in output
    for message in result.get("messages", []):
        assert "Yarvelle" not in str(message.content)
        assert CAREFOLD_CANONICAL_DISCLAIMER in str(message.content)

    records = await store.asearch(("memories", "th_synth_brand"))
    assert len(records) == 1
    persisted = records[0].value
    assert "Yarvelle" not in str(persisted)
    assert "\nCarefold: " in persisted["text"]
    assert CAREFOLD_CANONICAL_DISCLAIMER in persisted["agent_response"]


def test_production_graph_wires_carefold_nodes() -> None:
    """The routed production graph uses Carefold's refusal and synthesizer nodes."""
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from carefold.engine.refusal_node import CarefoldRefusalNode
    from carefold.engine.response_synthesizer import CarefoldResponseSynthesizerNode

    captured: Dict[str, Any] = {}
    svc = create_execution_service(workspace_root=REPO_ROOT)

    import yarvelle_core.engine.builder as core_builder

    original = core_builder.GraphBuilder.with_node

    def _spy(self: Any, name: str, node: Any) -> Any:
        captured[name] = node
        return original(self, name, node)

    core_builder.GraphBuilder.with_node = _spy  # type: ignore[method-assign]
    try:
        graph = svc._build_orchestrated_graph(FakeListChatModel(responses=["ok"]), None, None)
    finally:
        core_builder.GraphBuilder.with_node = original  # type: ignore[method-assign]

    assert isinstance(captured.get("refusal"), CarefoldRefusalNode)
    assert isinstance(captured.get("response_synthesizer"), CarefoldResponseSynthesizerNode)
    assert "input_guardrail" not in captured  # core guardrail reads policy check_flags
    nodes = set(graph.get_graph().nodes)
    assert {"input_guardrail", "supervisor", "refusal", "response_synthesizer"} <= nodes


@pytest.mark.asyncio
async def test_checkpoint_writes_queue_across_connections(tmp_path: Path) -> None:
    """Concurrent turns' checkpoint writes on one file wait on a shared in-process lock."""
    import asyncio

    from carefold.engine.runtime import _checkpoint_write_lock, serialized_sqlite_saver

    db_path = tmp_path / "chats" / "checkpoints.db"
    async with serialized_sqlite_saver(db_path) as first, serialized_sqlite_saver(db_path) as second:
        lock = _checkpoint_write_lock(db_path)
        assert lock is _checkpoint_write_lock(tmp_path / "chats" / ".." / "chats" / "checkpoints.db")
        async with lock:
            pending = [
                asyncio.create_task(first.adelete_thread("thread-a")),
                asyncio.create_task(second.adelete_thread("thread-b")),
            ]
            await asyncio.sleep(0.05)
            assert not any(task.done() for task in pending)
        await asyncio.gather(*pending)
        # Reads are not queued behind the write lock.
        async with lock:
            assert await asyncio.wait_for(
                first.aget_tuple({"configurable": {"thread_id": "thread-a"}}), timeout=5
            ) is None
