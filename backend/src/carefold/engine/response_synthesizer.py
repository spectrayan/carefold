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


"""Response synthesizer and disclaimer deduplication utilities for Carefold.

yarvelle-core's synthesizer appends a generic product disclaimer and labels
persisted turns with the core product name. This module rebrands core wording
to Carefold's pack navigation wording, preserves leading Markdown formatting
when stripping robotic reference preambles, and strips constituent specialist
disclaimers so degraded multi-agent listings never leave a disclaimer in the
middle between specialist sections.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage
from langgraph.store.base import BaseStore

from yarvelle_core.resources.loader import get_resource_loader
from yarvelle_core.workflows.nodes.response_synthesizer_node import (
    CANONICAL_DISCLAIMER as CORE_CANONICAL_DISCLAIMER,
    ResponseSynthesizerNode,
)

CAREFOLD_CANONICAL_DISCLAIMER = (
    "DISCLAIMER: Carefold is an educational and administrative navigation companion, "
    "not a licensed healthcare provider. "
    "Do not alter prescription medications or therapy plans without consulting your physician."
)

_CORE_TURN_LABEL = "\nYarvelle Core: "
_CAREFOLD_TURN_LABEL = "\nCarefold: "

_REFERENCE_PREAMBLE_RE = re.compile(
    r"^(?:(?:\*|_){0,2}(?:(?:Based on|According to|From) (?:the )?(?:provided )?"
    r"reference (?:document|guide|material|checklist|information|docs?)(?: provided)?)"
    r"[,:]?(?:\*|_){0,2}[,:]?\s*)",
    re.IGNORECASE,
)

# Constituent specialist/guardrail disclaimer patterns (single-paragraph blocks).
_CONSTITUENT_DISCLAIMER_PATTERNS = (
    re.compile(r"\n*\s*(?:\*|_){1,2}Disclaimer:[^\n]*?(?:\*|_){1,2}(?=\s*(?:\n\n|\Z))", re.IGNORECASE),
    re.compile(r"(?:^|\n+)\s*(?:\*|_){0,2}DISCLAIMER:.*?(?=\n\n|\Z)", re.IGNORECASE | re.DOTALL),
    re.compile(
        r"(?:^|\n+)\s*NOTE:\s*I am not a (?:doctor|licensed physician|clinician|healthcare provider).*?(?=\n\n|\Z)",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?:^|\n+)\s*Please consult your (?:doctor|physician|clinician) before.*?(?=\n\n|\Z)",
        re.IGNORECASE | re.DOTALL,
    ),
)

_INLINE_DISCLAIMER_BLOCK_RE = re.compile(
    r"(?:\*|_){1,2}Disclaimer:[^\n]+?(?:\*|_){1,2}"
    r"|(?:^|\n)[ \t]*(?:\*|_){0,2}DISCLAIMER:[^\n]+(?:\n(?![ \t]*\n)[^\n]+)*",
    re.IGNORECASE,
)


def _carefold_guardrail_header() -> str:
    try:
        from carefold.resources.loader import get_resource_loader as get_carefold_loader

        header = get_carefold_loader().get_disclaimer_header_text()
        if header and "yarvelle" not in header.lower():
            return header
    except Exception:
        pass
    return ""


def _core_guardrail_header() -> str:
    try:
        return get_resource_loader().get_disclaimer_header_text() or ""
    except Exception:
        return ""


def strip_safe_reference_preamble(text: str) -> str:
    """Strips robotic 'Based on the provided reference document...' preambles without eating leading ``**``."""
    if not text:
        return text
    trimmed = text.lstrip()
    match = _REFERENCE_PREAMBLE_RE.match(trimmed)
    if not match:
        return text
    cleaned = trimmed[match.end() :].lstrip("*_ \t")
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:] if len(cleaned) > 1 else cleaned.upper()
    return cleaned


def rebrand_text(text: str) -> str:
    """Replaces core's disclaimer footers and turn labels with Carefold's."""
    if not text:
        return text
    out = text.replace(CORE_CANONICAL_DISCLAIMER, CAREFOLD_CANONICAL_DISCLAIMER).replace(
        _CORE_TURN_LABEL, _CAREFOLD_TURN_LABEL
    )
    core_hdr = _core_guardrail_header()
    if core_hdr and core_hdr in out:
        out = out.replace(core_hdr, _carefold_guardrail_header())
    return out


def strip_constituent_disclaimers(text: str) -> str:
    """Removes constituent specialist and guardrail disclaimers from text."""
    if not text:
        return ""
    cleaned = rebrand_text(strip_safe_reference_preamble(text)).strip()
    for canonical in (CORE_CANONICAL_DISCLAIMER, CAREFOLD_CANONICAL_DISCLAIMER):
        if canonical in cleaned:
            cleaned = cleaned.replace(canonical, "").strip()
    for pat in _CONSTITUENT_DISCLAIMER_PATTERNS:
        cleaned = pat.sub("", cleaned).strip()
    cleaned = re.sub(
        r"(?m)^\s*(?:\*|_){0,2}Disclaimer\s*:.*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned


def deduplicate_middle_disclaimers(text: str) -> str:
    """Removes in-the-middle disclaimers while preserving a single trailing disclaimer if one existed."""
    if not text:
        return text
    rebranded = rebrand_text(text)
    matches = list(_INLINE_DISCLAIMER_BLOCK_RE.finditer(rebranded))
    if not matches:
        return rebranded

    last_end = matches[-1].end()
    trailing_tail = rebranded[last_end:].strip()
    # Clean only when there are >=2 disclaimers OR a disclaimer sits in the middle before more prose.
    if len(matches) == 1 and not trailing_tail:
        return rebranded

    last_block = matches[-1].group(0).strip()
    body = strip_constituent_disclaimers(rebranded)
    if not body:
        return last_block
    footer = last_block if "yarvelle" not in last_block.lower() else f"*Disclaimer: {_carefold_guardrail_header()}*"
    return f"{body}\n\n{footer}"


def _rebrand(value: Any) -> Any:
    if isinstance(value, str):
        return rebrand_text(value)
    if isinstance(value, AIMessage):
        if isinstance(value.content, str):
            return value.model_copy(update={"content": rebrand_text(value.content)})
        return value
    if isinstance(value, dict):
        return {k: _rebrand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_rebrand(v) for v in value]
    return value


class _RebrandingStore:
    """Store proxy that rebrands persisted turn payloads; delegates everything else."""

    def __init__(self, inner: BaseStore) -> None:
        self._inner = inner

    async def aput(self, namespace: Any, key: str, value: Dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        return await self._inner.aput(namespace, key, _rebrand(value), *args, **kwargs)

    def put(self, namespace: Any, key: str, value: Dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        return self._inner.put(namespace, key, _rebrand(value), *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class CarefoldResponseSynthesizerNode(ResponseSynthesizerNode):
    """Core response synthesizer with Carefold's canonical disclaimer and constituent-footer stripping."""

    @staticmethod
    def _without_footer(text: str) -> str:
        body = ResponseSynthesizerNode._without_footer(text)
        return strip_constituent_disclaimers(body)

    async def execute(
        self, state: Dict[str, Any], *, store: Optional[BaseStore] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        wrapped = _RebrandingStore(store) if store is not None else None
        result = await super().execute(state, store=wrapped, **kwargs)
        if isinstance(state.get("output"), str):
            state["output"] = rebrand_text(state["output"])
        return _rebrand(result)

    process = execute


__all__ = [
    "CAREFOLD_CANONICAL_DISCLAIMER",
    "CarefoldResponseSynthesizerNode",
    "deduplicate_middle_disclaimers",
    "rebrand_text",
    "strip_constituent_disclaimers",
    "strip_safe_reference_preamble",
]
