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

"""Carefold web search adapter layering clinical MRN query redaction on yarvelle_core."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from yarvelle_core.tools.web_search import *  # noqa: F401, F403
import yarvelle_core.tools.web_search as _target_module

_MRN_QUERY_RE = re.compile(
    r"(?i)\b(?:mrn|medical\s*record(?:\s*(?:number|no\.?|id))?)\b[:\s#-]*[A-Z0-9][A-Z0-9-]{2,}\b"
)
_MRN_LABEL_RE = re.compile(r"(?i)\b(?:mrn|medical\s*record)\b[:\s#-]*")


def _strip_clinical_identifiers(raw_query: str) -> tuple[str, List[str]]:
    """Strips clinical MRN tokens before delegating to yarvelle_core PII query sanitization."""
    redacted: List[str] = []

    def _repl(match: re.Match[str]) -> str:
        val = match.group(0).strip()
        if val:
            redacted.append(val)
        return " "

    cleaned = _MRN_QUERY_RE.sub(_repl, raw_query)
    cleaned = _MRN_LABEL_RE.sub(_repl, cleaned)
    return cleaned, redacted


def sanitize_search_query(
    query: str,
    profile_names: Optional[Sequence[str]] = None,
    profile_dob: Optional[str] = None,
) -> Dict[str, Any]:
    """Strips clinical MRN + core PII identifiers from an outbound web search query."""
    raw_query = "" if query is None else str(query)
    pre_cleaned, mrn_redacted = _strip_clinical_identifiers(raw_query)
    res = _target_module.sanitize_search_query(
        pre_cleaned,
        profile_names=profile_names,
        profile_dob=profile_dob,
    )
    return {
        "original_query": raw_query,
        "sanitized_query": res["sanitized_query"],
        "redacted_items": mrn_redacted + list(res.get("redacted_items", [])),
        "is_safe": res["is_safe"],
    }


async def execute_web_search(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Executes sandboxed web search with clinical MRN + core PII sanitization."""
    if not isinstance(args, dict):
        return await _target_module.execute_web_search(args, ctx=ctx)
    raw_query = str(args.get("query") or "")
    pre_cleaned, mrn_redacted = _strip_clinical_identifiers(raw_query)
    patched_args = {**args, "query": pre_cleaned}
    orig_fetch = getattr(_target_module, "_fetch_search_results", None)
    local_fetch = globals().get("_fetch_search_results", orig_fetch)
    if local_fetch is not orig_fetch and callable(local_fetch) and not bool(args.get("preview_only", False)):
        preview = await _target_module.execute_web_search({**patched_args, "preview_only": True}, ctx=ctx)
        max_res = max(1, min(int(args.get("max_results", 5)), 20)) if str(args.get("max_results", 5)).isdigit() else 5
        raw_hits = await local_fetch(
            provider=preview["provider"],
            target_url=f"https://{preview['target_host']}/",
            sanitized_query=preview["sanitized_query"],
            max_results=max_res,
        )
        cleaned_hits = _target_module._normalize_search_hits(raw_hits, max_results=max_res)
        _target_module._mark_context_tainted(ctx)
        res: Dict[str, Any] = {
            "query": raw_query,
            "sanitized_query": preview["sanitized_query"],
            "redacted_items": preview["redacted_items"],
            "provider": preview["provider"],
            "target_host": preview["target_host"],
            "results": cleaned_hits,
            "trust": "untrusted",
        }
    else:
        res = await _target_module.execute_web_search(patched_args, ctx=ctx)
    if isinstance(res, dict):
        res = {
            **res,
            "original_query": raw_query,
            "redacted_items": mrn_redacted + list(res.get("redacted_items", [])),
        }
    return res


def __getattr__(name: str) -> Any:
    return getattr(_target_module, name)


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(dir(_target_module)))
