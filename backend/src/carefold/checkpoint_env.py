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


"""``CAREFOLD_CHECKPOINT_*`` aliases for yarvelle-core checkpoint settings.

Core's ``Settings`` binds checkpoint encryption switches under the
``YARVELLE_CORE_`` prefix. Carefold installs configure them as
``CAREFOLD_CHECKPOINT_ENCRYPTION``, ``CAREFOLD_CHECKPOINT_PLAINTEXT_READS``
and ``CAREFOLD_CHECKPOINT_KEY_VERSION``. When a Carefold-prefixed value is
set and valid it takes precedence: it is mirrored into the ``YARVELLE_CORE_``
variable (so later ``Settings`` instances and CLI subprocesses agree) and
applied to the live settings object. Blank or invalid values are ignored.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, MutableMapping, Optional

logger = logging.getLogger(__name__)

APP_PREFIX = "CAREFOLD_"
CORE_PREFIX = "YARVELLE_CORE_"

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def _parse_bool(raw: str) -> Optional[bool]:
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    return None


def _parse_key_version(raw: str) -> Optional[int]:
    value = raw.strip()
    if not value.isdigit():
        return None
    version = int(value)
    return version if version >= 1 else None


# setting attribute -> (env suffix, parser)
CHECKPOINT_ALIASES: Dict[str, tuple] = {
    "checkpoint_encryption": ("CHECKPOINT_ENCRYPTION", _parse_bool),
    "checkpoint_plaintext_reads": ("CHECKPOINT_PLAINTEXT_READS", _parse_bool),
    "checkpoint_key_version": ("CHECKPOINT_KEY_VERSION", _parse_key_version),
}


def apply_checkpoint_env_aliases(
    environ: Optional[MutableMapping[str, str]] = None,
    settings_obj: Optional[Any] = None,
) -> Dict[str, Any]:
    """Apply ``CAREFOLD_CHECKPOINT_*`` values; returns the settings that were applied."""
    env = os.environ if environ is None else environ
    applied: Dict[str, Any] = {}
    for attr, (suffix, parse) in CHECKPOINT_ALIASES.items():
        app_name = f"{APP_PREFIX}{suffix}"
        raw = env.get(app_name)
        if raw is None or not raw.strip():
            continue
        value = parse(raw)
        if value is None:
            logger.warning("Ignoring invalid %s value %r", app_name, raw)
            continue
        env[f"{CORE_PREFIX}{suffix}"] = raw.strip()
        if settings_obj is not None:
            setattr(settings_obj, attr, value)
        applied[attr] = value
    return applied


__all__ = ["CHECKPOINT_ALIASES", "apply_checkpoint_env_aliases"]
