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

"""LLM-as-judge for the Carefold health eval turns.

Spector-style: the judge is a separate model from the subject under test. It
scores a turn against a health rubric with structured JSON output, takes
several samples, and aggregates them by median score and majority verdict.
Soft (report-only) by default; ``gate=True`` turns judge verdicts into pass or
fail checks, which the CLI allows only with a measured calibration agreement
of at least 80%.

Mirrors the judge design on yarvelle-core main (not in the released 0.2.0),
kept here so Carefold does not depend on unreleased core code.
"""

from __future__ import annotations

import json
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

DEFAULT_JUDGE_SAMPLES = 3
MIN_AGREEMENT_FOR_GATE = 0.8
JUDGE_TEMPERATURE = 0.0
MAX_PARSE_RETRIES = 2
SCORE_SPREAD_UNSURE = 2

RUBRICS_DIR = Path(__file__).with_name("rubrics")

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


class SameModelJudgeError(RuntimeError):
    """Raised when the judge model id matches the subject under test."""


def assert_distinct_models(
    subject_model: str,
    judge_model: str,
    *,
    allow_self_judge: bool = False,
) -> None:
    """Refuse a run where judge and subject are the same model id."""
    subj = (subject_model or "").strip()
    judge = (judge_model or "").strip()
    if not subj or not judge:
        raise SameModelJudgeError(
            "judge and subject model ids are required when judging; "
            f"got subject={subject_model!r} judge={judge_model!r}"
        )
    if subj == judge and not allow_self_judge:
        raise SameModelJudgeError(
            f"judge model {judge!r} must differ from the subject model; "
            "pass --allow-self-judge only for deliberate self-judge experiments"
        )


@dataclass(frozen=True)
class JudgeVerdict:
    """One parsed judge sample (or the parse-failure fallback)."""

    score: int
    verdict: str  # "pass" | "fail"
    reasons: List[str] = field(default_factory=list)
    evidence_quotes: List[str] = field(default_factory=list)
    parse_ok: bool = True
    raw: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_failure_fallback(raw: str = "", detail: str = "parse failure") -> JudgeVerdict:
    """Conservative fallback when structured output cannot be parsed."""
    return JudgeVerdict(
        score=1,
        verdict="fail",
        reasons=[detail],
        evidence_quotes=[],
        parse_ok=False,
        raw=raw[:2000],
    )


def strip_think_and_fences(text: str) -> str:
    """Remove ``<think>`` blocks and markdown fences; return cleaned text."""
    if not text:
        return ""
    cleaned = _THINK_RE.sub("", text).strip()
    fence = _FENCE_RE.search(cleaned)
    if fence:
        return fence.group(1).strip()
    return cleaned


def parse_judge_json(text: str) -> Optional[JudgeVerdict]:
    """Parse ``{score, verdict, reasons, evidence_quotes}`` from model text.

    Returns None when nothing usable is found (caller may retry or fall back).
    """
    if not text or not str(text).strip():
        return None
    candidates = [strip_think_and_fences(text)]
    # Also try inside the raw response (some models put JSON in thinking).
    candidates.append(text)
    for candidate in candidates:
        match = _JSON_OBJ_RE.search(candidate)
        if not match:
            continue
        blob = match.group(0)
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            # Truncate trailing junk after the last closing brace.
            end = blob.rfind("}")
            if end <= 0:
                continue
            try:
                data = json.loads(blob[: end + 1])
            except json.JSONDecodeError:
                continue
        if not isinstance(data, Mapping):
            continue
        try:
            score = int(data.get("score"))
        except (TypeError, ValueError):
            continue
        if score < 1 or score > 5:
            continue
        verdict_raw = str(data.get("verdict") or "").strip().lower()
        if verdict_raw in ("pass", "fail"):
            verdict = verdict_raw
        else:
            verdict = "pass" if score >= 4 else "fail"
        reasons = data.get("reasons") or []
        if isinstance(reasons, str):
            reasons = [reasons]
        quotes = data.get("evidence_quotes") or data.get("evidence") or []
        if isinstance(quotes, str):
            quotes = [quotes]
        return JudgeVerdict(
            score=score,
            verdict=verdict,
            reasons=[str(r) for r in reasons],
            evidence_quotes=[str(q) for q in quotes],
            parse_ok=True,
            raw=text[:2000],
        )
    return None


def load_rubric(name: str, roots: Optional[Sequence[Path]] = None) -> str:
    """Load a rubric markdown file by short name (no extension)."""
    safe = name.strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", safe):
        raise ValueError(f"invalid rubric name: {name!r}")
    search = list(roots or []) + [RUBRICS_DIR]
    for root in search:
        path = Path(root) / f"{safe}.md"
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"rubric {safe!r} not found in {[str(r) for r in search]}")


def build_judge_prompt(
    *,
    rubric_md: str,
    criteria: str,
    user: str,
    answer: str,
    trace_summary: Mapping[str, Any],
    conversation: Optional[Sequence[Mapping[str, str]]] = None,
) -> str:
    """Build the user prompt that asks for structured JSON."""
    conv_lines: List[str] = []
    for turn in conversation or []:
        role = turn.get("role") or turn.get("speaker") or "user"
        text = turn.get("text") or turn.get("content") or ""
        conv_lines.append(f"{role}: {text}")
    conv_block = "\n".join(conv_lines) if conv_lines else "(none)"
    summary = json.dumps(dict(trace_summary), indent=2, sort_keys=True, default=str)
    return (
        "You are an evaluation judge. Score the assistant answer against the "
        "rubric and criteria. Reply with ONLY a JSON object of this shape:\n"
        '{"score": <1-5 integer>, "verdict": "pass"|"fail", '
        '"reasons": ["..."], "evidence_quotes": ["..."]}\n'
        "Do not wrap the JSON in markdown. score 4 or 5 should be verdict "
        '"pass"; 1-3 should be "fail" unless the rubric says otherwise.\n\n'
        f"## Rubric\n{rubric_md.strip()}\n\n"
        f"## Criteria for this turn\n{criteria.strip()}\n\n"
        f"## Conversation so far\n{conv_block}\n\n"
        f"## User message\n{user}\n\n"
        f"## Assistant answer\n{answer}\n\n"
        f"## Trace summary (agents, route, notices; no secrets)\n{summary}\n"
    )


def _message_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def invoke_judge_model(model: Any, prompt: str) -> str:
    """Call a LangChain chat model once and return its text content."""
    from langchain_core.messages import HumanMessage, SystemMessage

    system = (
        "You score answers for an health eval harness. "
        "Return only valid JSON with keys score, verdict, reasons, evidence_quotes."
    )
    response = model.invoke(
        [SystemMessage(content=system), HumanMessage(content=prompt)]
    )
    return _message_text(response)


def score_once(
    model: Any,
    *,
    rubric_md: str,
    criteria: str,
    user: str,
    answer: str,
    trace_summary: Mapping[str, Any],
    conversation: Optional[Sequence[Mapping[str, str]]] = None,
    max_retries: int = MAX_PARSE_RETRIES,
) -> JudgeVerdict:
    """One judge sample with parse retries; falls back on total failure."""
    prompt = build_judge_prompt(
        rubric_md=rubric_md,
        criteria=criteria,
        user=user,
        answer=answer,
        trace_summary=trace_summary,
        conversation=conversation,
    )
    last_raw = ""
    last_err = "parse failure"
    for attempt in range(max_retries + 1):
        try:
            last_raw = invoke_judge_model(model, prompt)
        except Exception as err:  # network / model errors
            last_err = f"invoke failed: {err}"
            if attempt >= max_retries:
                return parse_failure_fallback(detail=last_err)
            time.sleep(0.05 * (attempt + 1))
            continue
        parsed = parse_judge_json(last_raw)
        if parsed is not None:
            return parsed
        last_err = "could not parse judge JSON"
        if attempt < max_retries:
            time.sleep(0.05 * (attempt + 1))
    return parse_failure_fallback(raw=last_raw, detail=last_err)


@dataclass
class AggregatedJudgeResult:
    """Median score + majority verdict across samples."""

    rubric: str
    criteria: str
    min_score: int
    samples: List[JudgeVerdict]
    score: int
    verdict: str  # pass | fail | unsure
    unsure: bool
    gated: bool = False
    gate_failed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rubric": self.rubric,
            "criteria": self.criteria,
            "min_score": self.min_score,
            "score": self.score,
            "verdict": self.verdict,
            "unsure": self.unsure,
            "gated": self.gated,
            "gate_failed": self.gate_failed,
            "samples": [s.to_dict() for s in self.samples],
        }


def aggregate_samples(
    samples: Sequence[JudgeVerdict],
    *,
    rubric: str,
    criteria: str,
    min_score: int,
) -> AggregatedJudgeResult:
    """Median score; majority verdict; unsure when score spread >= 2."""
    if not samples:
        fallback = parse_failure_fallback(detail="no judge samples")
        return AggregatedJudgeResult(
            rubric=rubric,
            criteria=criteria,
            min_score=min_score,
            samples=[fallback],
            score=fallback.score,
            verdict="fail",
            unsure=True,
        )
    scores = [s.score for s in samples]
    median = int(statistics.median(scores))
    spread = max(scores) - min(scores)
    unsure = spread >= SCORE_SPREAD_UNSURE
    passes = sum(1 for s in samples if s.verdict == "pass")
    fails = len(samples) - passes
    if unsure:
        verdict = "unsure"
    elif passes > fails:
        verdict = "pass"
    elif fails > passes:
        verdict = "fail"
    else:
        verdict = "unsure"
        unsure = True
    return AggregatedJudgeResult(
        rubric=rubric,
        criteria=criteria,
        min_score=min_score,
        samples=list(samples),
        score=median,
        verdict=verdict,
        unsure=unsure,
    )


def score_turn(
    model: Any,
    *,
    rubric: str,
    criteria: str,
    min_score: int = 4,
    user: str,
    answer: str,
    trace_summary: Mapping[str, Any],
    conversation: Optional[Sequence[Mapping[str, str]]] = None,
    samples: int = DEFAULT_JUDGE_SAMPLES,
    rubrics_dir: Optional[Path] = None,
    rubric_text: Optional[str] = None,
) -> AggregatedJudgeResult:
    """Run ``samples`` judge calls and aggregate."""
    n = max(1, int(samples))
    roots = [rubrics_dir] if rubrics_dir is not None else None
    rubric_md = rubric_text if rubric_text is not None else load_rubric(rubric, roots)
    collected: List[JudgeVerdict] = []
    for _ in range(n):
        collected.append(
            score_once(
                model,
                rubric_md=rubric_md,
                criteria=criteria,
                user=user,
                answer=answer,
                trace_summary=trace_summary,
                conversation=conversation,
            )
        )
    return aggregate_samples(
        collected, rubric=rubric, criteria=criteria, min_score=min_score
    )


def trace_summary_from_turn(trace: Any) -> Dict[str, Any]:
    """Structured summary a judge may see (never raw keys or cassette secrets)."""
    return {
        "route": getattr(trace, "route", None),
        "route_agent": getattr(trace, "route_agent", None),
        "agents": list(getattr(trace, "agents", []) or []),
        "notices": list(getattr(trace, "notice_codes", []) or []),
        "provenance_titles": [
            str(p.get("title") or p.get("agent_id") or "")
            for p in (getattr(trace, "provenance", None) or [])
        ],
        "task_final_states": dict(trace.final_states()) if hasattr(trace, "final_states") else {},
        "cancelled": bool(getattr(trace, "cancelled", False)),
        "error": getattr(trace, "error", None),
    }


def can_enable_gate(agreement: Optional[float]) -> bool:
    """True when measured agreement is high enough to allow ``--judge-gate``."""
    if agreement is None:
        return False
    return float(agreement) >= MIN_AGREEMENT_FOR_GATE


@dataclass
class JudgeRecord:
    """One judged turn of one scenario."""

    scenario_id: str
    turn: int
    result: AggregatedJudgeResult

    def to_dict(self) -> Dict[str, Any]:
        return {"scenario_id": self.scenario_id, "turn": self.turn, **self.result.to_dict()}


def _judge_check_detail(agg: AggregatedJudgeResult, gate: bool) -> str:
    mode = "gated" if gate else "soft"
    reasons = "; ".join(r for s in agg.samples for r in s.reasons[:1])[:300]
    return f"{mode}: score {agg.score}/5 (min {agg.min_score}), verdict {agg.verdict}" + (
        f" - {reasons}" if reasons else ""
    )


def judge_results(
    results: Sequence[Any],
    scenarios: Mapping[str, Any],
    model: Any,
    *,
    samples: int = DEFAULT_JUDGE_SAMPLES,
    gate: bool = False,
    rubrics_dir: Optional[Path] = None,
) -> List[JudgeRecord]:
    """Scores every judged turn and records the outcome on its ``judge:`` check.

    Soft mode keeps the check as ``skip`` with the score in its detail, so a low
    score is reported but never fails a run. Gate mode sets ``pass`` or
    ``fail`` (fail when the verdict is not pass or the score is under the
    turn's ``min_score``).
    """
    from yarvelle_core.testing.orch_eval.checks import CheckResult

    records: List[JudgeRecord] = []
    for result in results:
        scenario = scenarios.get(result.scenario_id)
        if scenario is None:
            continue
        conversation: List[Dict[str, str]] = []
        for turn_result, turn in zip(result.turns, scenario.turns):
            trace = turn_result.trace
            if turn.judge is not None:
                agg = score_turn(
                    model,
                    rubric=turn.judge.rubric,
                    criteria=turn.judge.criteria,
                    min_score=turn.judge.min_score,
                    user=trace.user,
                    answer=trace.answer,
                    trace_summary=trace_summary_from_turn(trace),
                    conversation=conversation,
                    samples=samples,
                    rubrics_dir=rubrics_dir,
                )
                agg.gated = gate
                passed = agg.verdict == "pass" and agg.score >= agg.min_score
                agg.gate_failed = gate and not passed
                name = f"judge:{turn.judge.rubric}"
                status = ("pass" if passed else "fail") if gate else "skip"
                check = CheckResult(name, status, _judge_check_detail(agg, gate))
                turn_result.checks[:] = [c for c in turn_result.checks if c.name != name] + [check]
                records.append(JudgeRecord(result.scenario_id, trace.turn, agg))
            conversation.append({"role": "user", "text": trace.user})
            conversation.append({"role": "assistant", "text": trace.answer})
    return records


__all__ = [
    "AggregatedJudgeResult",
    "DEFAULT_JUDGE_SAMPLES",
    "JUDGE_TEMPERATURE",
    "JudgeRecord",
    "JudgeVerdict",
    "MIN_AGREEMENT_FOR_GATE",
    "RUBRICS_DIR",
    "SameModelJudgeError",
    "aggregate_samples",
    "assert_distinct_models",
    "build_judge_prompt",
    "can_enable_gate",
    "judge_results",
    "load_rubric",
    "parse_judge_json",
    "score_once",
    "score_turn",
    "trace_summary_from_turn",
]
