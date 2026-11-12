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

"""Markdown frontmatter parser delegating YAML parsing to yarvelle_core with Carefold intended-use verifier."""

from __future__ import annotations

from typing import Optional, Tuple
from yarvelle_core.loaders.frontmatter import ParsedFrontmatter, parse_frontmatter  # noqa: F401
from carefold.resources.loader import get_resource_loader

MANDATORY_INTENDED_USE_LINES = get_resource_loader().get_mandatory_intended_use_lines()


def check_mandatory_intended_use(content: str) -> Tuple[bool, Optional[str]]:
    normalized = content.lower()
    for line in MANDATORY_INTENDED_USE_LINES:
        if line == "Not a clinician and not emergency care":
            if not ("not a clinician" in normalized and ("not emergency care" in normalized or "not emergency" in normalized)):
                return False, line
        elif line == "If this is an emergency, contact local emergency services":
            if not any(p in normalized for p in ("contact local emergency services", "contact emergency services", "call 911", "emergency services")):
                return False, line
        elif line == "Do not change medication without the prescribing clinician":
            if not any(p in normalized for p in ("do not change medication", "prescribing clinician", "without your doctor", "without consulting")):
                return False, line
    return True, None
