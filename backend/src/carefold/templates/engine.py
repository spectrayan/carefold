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

"""Re-export shim delegating to yarvelle_core.templates.engine."""

from __future__ import annotations

from yarvelle_core.templates.engine import *  # noqa: F401, F403
import yarvelle_core.templates.engine as _yc_templates
from carefold.clinical.host_bridges import CarefoldTemplateEngine as TemplateEngine
from carefold.clinical.host_bridges import get_carefold_template_engine as get_template_engine
from carefold.clinical.host_bridges import render_carefold_template as render_template


def __getattr__(name: str):
    return getattr(_yc_templates, name)
