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


"""Response synthesizer that keeps Carefold's canonical disclaimer footer.

yarvelle-core's synthesizer appends a generic product disclaimer and labels
persisted turns with the core product name. This subclass reuses core's
synthesis unchanged and swaps those strings for Carefold's wording in the
returned output, messages, and the turn it persists to the memory store.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage
from langgraph.store.base import BaseStore

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


def rebrand_text(text: str) -> str:
    """Replace core's disclaimer footer and turn label with Carefold's."""
    return text.replace(CORE_CANONICAL_DISCLAIMER, CAREFOLD_CANONICAL_DISCLAIMER).replace(
        _CORE_TURN_LABEL, _CAREFOLD_TURN_LABEL
    )


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
    """Core response synthesizer with Carefold's canonical disclaimer."""

    @staticmethod
    def _without_footer(text: str) -> str:
        body = ResponseSynthesizerNode._without_footer(text)
        if body.endswith(CAREFOLD_CANONICAL_DISCLAIMER):
            body = body[: -len(CAREFOLD_CANONICAL_DISCLAIMER)].rstrip()
        return body

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
    "rebrand_text",
]
