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

"""Package re-export shim delegating to yarvelle_core.vault while binding carefold.vault.kek."""

from __future__ import annotations

from typing import Any
from yarvelle_core.vault import *  # noqa: F401, F403
import yarvelle_core.vault as _target_module
from carefold.vault import kek  # noqa: F401
from carefold.vault.kek import DEFAULT_ARGON2_SALT, derive_argon2id_kek, get_kek, resolve_kek  # noqa: F401


def __getattr__(name: str) -> Any:
    return getattr(_target_module, name)


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(dir(_target_module)))
