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

"""Carefold Safe Refusal Template externalized via ResourceLoader.

Sources safe refusal templates and disclaimer headers from disclaimers.yaml.
Zero hardcoded disclaimer texts or string literals embedded in Python code.
"""

from __future__ import annotations

from typing import Any
from carefold.resources.loader import get_resource_loader


def get_safe_refusal_template() -> str:
    """Retrieve the standard safe refusal template from disclaimers resource."""
    return get_resource_loader().get_safe_refusal_template()


def get_disclaimer_header_text() -> str:
    """Retrieve the standard disclaimer header text from disclaimers resource."""
    return get_resource_loader().get_disclaimer_header_text()


# Module-level backward-compatible variables populated at import time
_loader = get_resource_loader()
SAFE_REFUSAL_TEMPLATE: str = _loader.get_safe_refusal_template()
DISCLAIMER_HEADER_TEXT: str = _loader.get_disclaimer_header_text()

__all__ = [
    "SAFE_REFUSAL_TEMPLATE",
    "DISCLAIMER_HEADER_TEXT",
    "get_safe_refusal_template",
    "get_disclaimer_header_text",
]


def __getattr__(name: str) -> Any:
    """Dynamic attribute lookup for live resource updates or hot reloading."""
    if name == "SAFE_REFUSAL_TEMPLATE":
        return get_safe_refusal_template()
    if name == "DISCLAIMER_HEADER_TEXT":
        return get_disclaimer_header_text()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
