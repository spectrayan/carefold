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

"""Template compilation and rendering package for Carefold."""

from carefold.templates.engine import (
    TemplateEngine,
    get_template_engine,
    render_template,
)
from carefold.templates.helpers import BUILTIN_HELPERS

__all__ = [
    "TemplateEngine",
    "get_template_engine",
    "render_template",
    "BUILTIN_HELPERS",
]
