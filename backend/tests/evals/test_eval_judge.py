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

"""The Carefold eval judge parses, aggregates and attaches scores offline."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import List

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.orchestration import judge as J  # noqa: E402
from evals.orchestration.runner import build_pack, load_health_scenarios, run_health_scenarios  # noqa: E402


@pytest.fixture(autouse=True)
def _offline_fake_runs_allowed_on_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    """Core's scenario loader refuses CI. These tests only load files and run the
    scripted fake model offline, so CI variables are cleared for them (the same
    pattern core's own tests use). Live runs stay CI-refused in the CLI."""
    from yarvelle_core.testing.orch_eval.guard import CI_ENV_VARS

    for name in CI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


class _ScriptedJudge:
    """Stands in for a judge chat model; returns canned replies in order."""

    def __init__(self, replies: List[str]) -> None:
        self.replies = list(replies)
        self.prompts: List[str] = []

    def invoke(self, messages):  # noqa: ANN001
        self.prompts.append(str(messages[-1].content))
        reply = self.replies.pop(0) if self.replies else "not json"
        return type("Msg", (), {"content": reply})()


def test_parse_strips_think_blocks_and_fences() -> None:
    raw = '<think>hmm</think>\n```json\n{"score": 5, "verdict": "pass", "reasons": "clear"}\n```'
    verdict = J.parse_judge_json(raw)
    assert verdict is not None and verdict.score == 5 and verdict.verdict == "pass"
    assert verdict.reasons == ["clear"]


@pytest.mark.parametrize("raw", ["", "no json here", '{"score": 9}', '{"verdict": "pass"}'])
def test_unparseable_or_out_of_range_replies_are_rejected(raw: str) -> None:
    assert J.parse_judge_json(raw) is None


def test_verdict_defaults_from_score() -> None:
    assert J.parse_judge_json('{"score": 3}').verdict == "fail"
    assert J.parse_judge_json('{"score": 4}').verdict == "pass"


def test_score_once_retries_then_falls_back_to_a_conservative_fail() -> None:
    model = _ScriptedJudge(["junk", "junk", "junk"])
    verdict = J.score_once(model, rubric_md="r", criteria="c", user="u", answer="a", trace_summary={})
    assert (verdict.score, verdict.verdict, verdict.parse_ok) == (1, "fail", False)
    assert len(model.prompts) == 3


def test_aggregate_uses_the_median_and_flags_spread_as_unsure() -> None:
    v = lambda s: J.JudgeVerdict(score=s, verdict="pass" if s >= 4 else "fail")  # noqa: E731
    agg = J.aggregate_samples([v(4), v(5), v(4)], rubric="r", criteria="c", min_score=4)
    assert (agg.score, agg.verdict, agg.unsure) == (4, "pass", False)
    agg = J.aggregate_samples([v(1), v(5), v(4)], rubric="r", criteria="c", min_score=4)
    assert agg.verdict == "unsure" and agg.unsure


def test_judge_must_differ_from_the_subject() -> None:
    with pytest.raises(J.SameModelJudgeError):
        J.assert_distinct_models("llama3.1:8b", "llama3.1:8b")
    J.assert_distinct_models("glm-4.7-flash", "llama3.1:8b")


def test_every_health_rubric_used_by_a_scenario_exists() -> None:
    used = {t.judge.rubric for _p, s in load_health_scenarios() for t in s.turns if t.judge}
    assert used
    for name in used:
        text = J.load_rubric(name)
        assert "| 5 |" in text and "| 1 |" in text, name


def test_prompt_carries_rubric_conversation_and_trace_but_no_secrets() -> None:
    prompt = J.build_judge_prompt(
        rubric_md="RUBRIC", criteria="CRIT", user="U2", answer="A2",
        trace_summary={"route": "main_agent", "agents": ["benefits-coordinator"]},
        conversation=[{"role": "user", "text": "U1"}, {"role": "assistant", "text": "A1"}],
    )
    for part in ("RUBRIC", "CRIT", "user: U1", "assistant: A1", "U2", "A2", "benefits-coordinator"):
        assert part in prompt


@pytest.mark.asyncio
async def test_judging_fake_results_is_soft_by_default(tmp_path: Path) -> None:
    from yarvelle_core.testing.orch_eval.fake import FakeBackend

    loaded = [(p, s) for p, s in load_health_scenarios() if s.id == "partial-failure-honesty"]
    (result,) = await run_health_scenarios(loaded, build_pack(tmp_path, persona_markers=True), FakeBackend)
    model = _ScriptedJudge(['{"score": 2, "verdict": "fail", "reasons": ["vague"]}', '{"score": 5, "verdict": "pass"}'])
    records = J.judge_results([result], dict((s.id, s) for _p, s in loaded), model, samples=1)
    assert [(r.turn, r.result.score, r.result.verdict) for r in records] == [(1, 2, "fail"), (2, 5, "pass")]
    assert "user: Can you help me get ready" in model.prompts[1]  # turn 2 sees turn 1
    assert result.passed  # soft: a low judge score is reported, not a failure
    check = next(c for c in result.turns[0].checks if c.name.startswith("judge:"))
    assert check.status == "skip" and "score 2/5" in check.detail

    gated = J.judge_results([result], dict((s.id, s) for _p, s in loaded),
                            _ScriptedJudge(['{"score": 2}', '{"score": 5}']), samples=1, gate=True)
    assert not result.passed and len(gated) == 2
