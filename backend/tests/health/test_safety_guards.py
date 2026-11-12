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

"""Carefold safety.guards configuration, buffered release, and Granite Guardian shadow check."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

import carefold
from carefold.engine.runtime import create_execution_service
from carefold.safety.policy import CarefoldHealthSafetyPolicy
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE
from tests.test_refusal_ask_your_doctor import MUST_PASS, MUST_REFUSE
from yarvelle_core.engine.guards import GuardedSafetyPolicy, build_guarded_policy
from yarvelle_core.engine.guards.env import resolve_endpoint, resolve_mode
from yarvelle_core.engine.safety_policy import acheck_input, acheck_output
from yarvelle_core.pack.spec import PackManifest

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_YAML = REPO_ROOT / "backend" / "src" / "carefold" / "pack.yaml"


def _validate_pack_manifest_compat(data: Dict[str, Any]) -> PackManifest:
    payload = dict(data)
    if "error_prefix" not in PackManifest.model_fields:
        payload.pop("error_prefix", None)
        if isinstance(payload.get("scopes"), list):
            payload["scopes"] = [
                {**s, "sensitivity": "phi"} if isinstance(s, dict) and s.get("sensitivity") == "restricted" else s
                for s in payload["scopes"]
            ]
    return PackManifest.model_validate(payload)


def test_pack_yaml_and_python_twin_declare_buffered_granite_guardian() -> None:
    data = yaml.safe_load(PACK_YAML.read_text(encoding="utf-8"))
    manifest = _validate_pack_manifest_compat(data)
    pack = carefold.get_pack()

    for source in (manifest.safety, pack.safety):
        assert source is not None
        assert source.guards is not None
        assert source.guards.release == "buffered"
        assert len(source.guards.checks) == 1
        check = source.guards.checks[0]
        assert check.id == "granite-guardian"
        assert check.type == "model"
        assert check.preset == "granite_guardian"
        assert check.effective_stages() == ["output"]
        assert check.mode == "shadow"
        assert check.when_unconfigured == "allow"
        # Carefold ships no guard model; endpoint comes from env vars only.
        assert check.model.provider is None
        assert check.model.model is None
        assert check.model.base_url is None


def test_execution_service_uses_guarded_policy_and_buffered_release() -> None:
    service = create_execution_service(workspace_root=REPO_ROOT)
    assert isinstance(service.safety_policy, GuardedSafetyPolicy)
    assert isinstance(service.safety_policy.base, CarefoldHealthSafetyPolicy)
    assert isinstance(service.safety_policy, CarefoldHealthSafetyPolicy)
    assert service.output_release == "buffered"
    assert service._buffer_answer is True


def test_env_vars_configure_granite_guardian_with_carefold_or_yarvelle_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_spec = carefold.get_pack().safety.guards.checks[0]

    monkeypatch.setenv("CAREFOLD_SAFETY_GUARD_GRANITE_GUARDIAN_PROVIDER", "ollama")
    monkeypatch.setenv("CAREFOLD_SAFETY_GUARD_GRANITE_GUARDIAN_MODEL", "granite3-guardian:2b")
    monkeypatch.setenv("CAREFOLD_SAFETY_GUARD_GRANITE_GUARDIAN_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("CAREFOLD_SAFETY_GUARD_GRANITE_GUARDIAN_MODE", "enforce")

    ep = resolve_endpoint(check_spec)
    assert ep.provider == "ollama"
    assert ep.model == "granite3-guardian:2b"
    assert ep.base_url == "http://127.0.0.1:11434"
    assert resolve_mode(check_spec) == "enforce"

    # YARVELLE_ fallback works when CAREFOLD_ is unset.
    for suffix in ("PROVIDER", "MODEL", "BASE_URL", "MODE"):
        monkeypatch.delenv(f"CAREFOLD_SAFETY_GUARD_GRANITE_GUARDIAN_{suffix}", raising=False)
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_GRANITE_GUARDIAN_PROVIDER", "ollama")
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_GRANITE_GUARDIAN_MODEL", "granite3-guardian:2b")
    ep_fallback = resolve_endpoint(check_spec)
    assert ep_fallback.provider == "ollama"
    assert ep_fallback.model == "granite3-guardian:2b"


@pytest.mark.asyncio
async def test_guarded_policy_preserves_all_308_refusal_and_pass_verdicts() -> None:
    calls = 0

    class _SpyModel(GenericFakeChatModel):
        async def _agenerate(self, *args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return await super()._agenerate(*args, **kwargs)

    pack = carefold.get_pack()
    spy = _SpyModel(messages=iter([AIMessage(content="No")] * 200))
    policy = build_guarded_policy(
        CarefoldHealthSafetyPolicy(),
        pack=pack,
        chat_models={"granite-guardian": spy},
        include_env=False,
    )

    for text, category in MUST_REFUSE:
        in_v = await acheck_input(policy, text)
        out_v = await acheck_output(policy, text)
        assert in_v.refused and in_v.is_hard
        assert out_v.refused and out_v.is_hard
        assert in_v.reason == f"forbidden_intent:{category}"
        assert out_v.reason == f"forbidden_intent:{category}"
    # Policy refuses first: the guard model is never called on policy refusals.
    assert calls == 0

    for text in MUST_PASS:
        out_v = await acheck_output(policy, text)
        assert not out_v.refused, (text, out_v.reason)
    assert calls == len(MUST_PASS)


@pytest.mark.asyncio
async def test_granite_guardian_shadow_audits_without_blocking_and_enforce_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: List[Any] = []
    pack = carefold.get_pack()
    fake = GenericFakeChatModel(messages=iter([AIMessage(content="Yes"), AIMessage(content="Yes")]))

    shadow_policy = build_guarded_policy(
        CarefoldHealthSafetyPolicy(),
        pack=pack,
        chat_models={"granite-guardian": fake},
        audit_hooks=[records.append],
        include_env=False,
    )
    verdict = await acheck_output(shadow_policy, "Ask your doctor about a generic alternative.")
    assert verdict.refused is False
    assert len(records) == 1
    assert records[0].results[0].check_id == "granite-guardian"
    assert records[0].results[0].decision == "block"
    assert records[0].results[0].mode == "shadow"

    monkeypatch.setenv("CAREFOLD_SAFETY_GUARD_GRANITE_GUARDIAN_MODE", "enforce")
    enforce_policy = build_guarded_policy(
        CarefoldHealthSafetyPolicy(),
        pack=pack,
        chat_models={"granite-guardian": fake},
        audit_hooks=[records.append],
        include_env=False,
    )
    enforced = await acheck_output(enforce_policy, "Ask your doctor about a generic alternative.")
    assert enforced.refused is True
    assert enforced.is_hard is True
    assert enforced.reason == "guard:granite-guardian:blocked"
    assert enforced.safe_response == SAFE_REFUSAL_TEMPLATE


@pytest.mark.asyncio
async def test_buffered_service_never_streams_refused_output_tokens(tmp_path: Path) -> None:
    from tests.fixtures.fake_model import FakeListChatModel

    unsafe = "Take 20 mg of lisinopril twice a day."
    service = create_execution_service(
        model=FakeListChatModel(responses=[unsafe] * 6),
        workspace_root=REPO_ROOT,
        db_path=tmp_path / "checkpoints.db",
    )
    events: List[Dict[str, Any]] = [
        ev
        async for ev in service.execute_turn(
            thread_id="buffered-refusal-check",
            prompt="How should I prepare for my visit?",
            agent_id="appointment-prep-coordinator",
        )
    ]
    assert [e for e in events if e.get("type") == "token"] == []
    assert [e for e in events if e.get("type") == "suggestions"] == []
    assert all(unsafe not in str(e) for e in events)
    done = [e for e in events if e.get("type") == "done"][-1]
    assert done["refused"] is True
    assert done["fullText"] == SAFE_REFUSAL_TEMPLATE
