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

"""Declarative dossier extraction heuristics backed by ``resources/dossier_heuristics.yaml``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Dict, List

import yaml

_HEURISTICS_YAML_PATH = (
    Path(__file__).resolve().parent.parent / "resources" / "dossier_heuristics.yaml"
)


@lru_cache(maxsize=1)
def load_dossier_heuristics() -> Dict[str, Any]:
    """Loads and caches Carefold's declarative dossier extraction regex rules."""
    raw = yaml.safe_load(_HEURISTICS_YAML_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Invalid dossier_heuristics.yaml payload: expected mapping.")
    return raw


def _normalize_dollar_amount(value: str, *, digits_only_check: bool = False) -> str:
    if not value:
        return ""
    if value.startswith("$"):
        return value
    if digits_only_check and not value.isdigit():
        return value
    return f"${value}"


def extract_clinical_visit_heuristic(text: str, dossier_cls: Any) -> Any:
    """Extracts a ``ClinicalVisitDossier`` from clinical visit prose using YAML rules."""
    cfg = load_dossier_heuristics()["clinical_visit"]
    patterns: Dict[str, str] = cfg["patterns"]
    delimiter = str(cfg.get("list_delimiter", ","))

    m_reason = re.search(patterns["reason_for_visit"], text, re.IGNORECASE)
    reason = m_reason.group(1).strip() if m_reason else ""

    m_time = re.search(patterns["follow_up_timeline"], text, re.IGNORECASE)
    timeline = m_time.group(1) if m_time else ""

    instructions: List[str] = []
    m_inst = re.search(patterns["physician_instructions"], text, re.IGNORECASE)
    if m_inst:
        raw_inst = [s.strip() for s in m_inst.group(1).split(delimiter) if s.strip()]
        if raw_inst:
            instructions = raw_inst

    questions: List[str] = []
    m_q = re.search(patterns["questions_to_ask"], text, re.IGNORECASE)
    if m_q:
        raw_q = [s.strip() for s in m_q.group(1).split(delimiter) if s.strip()]
        if raw_q:
            questions = raw_q

    return dossier_cls(
        reason_for_visit=reason,
        physician_instructions=instructions,
        follow_up_timeline=timeline,
        questions_to_ask=questions,
    )


def extract_insurance_benefits_heuristic(text: str, dossier_cls: Any) -> Any:
    """Extracts an ``InsuranceBenefitsDossier`` from benefits summary prose using YAML rules."""
    cfg = load_dossier_heuristics()["insurance_benefits"]
    patterns: Dict[str, str] = cfg["patterns"]

    m_ded = re.search(patterns["deductible"], text, re.IGNORECASE)
    deductible = _normalize_dollar_amount(
        m_ded.group(1) if m_ded else "",
        digits_only_check=True,
    )

    copays: Dict[str, str] = {}
    for key, pattern in cfg.get("copays", {}).items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            copays[str(key)] = _normalize_dollar_amount(match.group(1))

    if not copays:
        fallback = cfg.get("fallback_copay") or {}
        fb_pattern = fallback.get("pattern")
        fb_key = str(fallback.get("key", "office_visit"))
        if fb_pattern:
            m_gen = re.search(fb_pattern, text, re.IGNORECASE)
            if m_gen:
                copays[fb_key] = _normalize_dollar_amount(m_gen.group(1))

    m_coin = re.search(patterns["coinsurance"], text, re.IGNORECASE)
    coinsurance = m_coin.group(1) if m_coin else ""

    m_oop = re.search(patterns["out_of_pocket_maximum"], text, re.IGNORECASE)
    oop = m_oop.group(1) if m_oop else ""

    m_rules = re.search(patterns["in_out_network_rules"], text, re.IGNORECASE)
    rules = m_rules.group(1).strip() if m_rules else ""

    prior_auth: List[str] = []
    for entry in cfg.get("prior_authorization_flags", []):
        flags = re.IGNORECASE if entry.get("ignore_case") else 0
        if re.search(entry["pattern"], text, flags):
            prior_auth.append(str(entry["label"]))

    return dossier_cls(
        deductible=deductible,
        copays=copays,
        coinsurance=coinsurance,
        out_of_pocket_maximum=oop,
        in_out_network_rules=rules,
        prior_authorization_flags=prior_auth,
    )


def register_carefold_dossier_heuristics() -> None:
    """Registers Carefold's declarative dossier heuristic extractors with ``yarvelle_core``."""
    from yarvelle_core.workflows.subgraphs.extraction.tool import register_heuristic_extractor

    cfg = load_dossier_heuristics()
    for alias in cfg["clinical_visit"].get("aliases", []):
        register_heuristic_extractor(str(alias), extract_clinical_visit_heuristic)
    for alias in cfg["insurance_benefits"].get("aliases", []):
        register_heuristic_extractor(str(alias), extract_insurance_benefits_heuristic)


__all__ = [
    "extract_clinical_visit_heuristic",
    "extract_insurance_benefits_heuristic",
    "load_dossier_heuristics",
    "register_carefold_dossier_heuristics",
]
