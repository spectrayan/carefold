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

"""Handlebars template helper functions for Carefold prompt and report templating with pydantic-handlebars."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional


def helper_join(*args: Any, **kwargs: Any) -> str:
    """Joins an iterable of items with a delimiter."""
    if not args:
        return ""
    items = args[0]
    delimiter = args[1] if len(args) > 1 else ", "
    if items is None:
        return ""
    if isinstance(items, str):
        return items
    return delimiter.join(str(x) for x in items if x is not None)


def helper_default(*args: Any, **kwargs: Any) -> Any:
    """Returns value if truthy, otherwise default_value."""
    if not args:
        return ""
    val = args[0]
    fallback = args[1] if len(args) > 1 else ""
    return val if val else fallback


def helper_eq(*args: Any, **kwargs: Any) -> bool:
    """Equality check."""
    if len(args) < 2:
        return False
    return str(args[0]) == str(args[1])


def helper_neq(*args: Any, **kwargs: Any) -> bool:
    """Inequality check."""
    if len(args) < 2:
        return True
    return str(args[0]) != str(args[1])


def helper_upper(*args: Any, **kwargs: Any) -> str:
    """Converts string to uppercase."""
    if not args:
        return ""
    return str(args[0] or "").upper()


def helper_lower(*args: Any, **kwargs: Any) -> str:
    """Converts string to lowercase."""
    if not args:
        return ""
    return str(args[0] or "").lower()


def helper_first_line(*args: Any, **kwargs: Any) -> str:
    """Returns the first non-empty line from text."""
    if not args or not args[0]:
        return ""
    for line in str(args[0]).splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return ""


BUILTIN_HELPERS: Dict[str, Callable] = {
    "join": helper_join,
    "default": helper_default,
    "eq": helper_eq,
    "neq": helper_neq,
    "upper": helper_upper,
    "lower": helper_lower,
    "first_line": helper_first_line,
}

__all__ = ["BUILTIN_HELPERS"]
