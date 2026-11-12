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

"""Re-export shim delegating to yarvelle_core.engine.job_runner."""

from __future__ import annotations

import yarvelle_core.engine.job_runner as _yc_job_runner
from yarvelle_core.engine.job_runner import (
    AwaitableTuple,
    CLOCK_JUMP_THRESHOLD_SECONDS,
    DEFAULT_BATCH_SIZE,
    DEFAULT_LEASE_DURATION,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_POLL_INTERVAL,
    REMINDER_OVERDUE_THRESHOLD_SECONDS,
    calculate_next_occurrence,
    execute_tool_call,
    handle_delete_doc_job,
    sweep_overdue_reminders,
)
from carefold.clinical.host_bridges import CarefoldJobRunner as JobRunner
from carefold.clinical.host_bridges import create_extract_text_handler_compat as create_extract_text_handler
from carefold.clinical.host_bridges import handle_extract_text_job_compat as handle_extract_text_job
from carefold.clinical.host_bridges import handle_index_doc_job_compat as handle_index_doc_job


def __getattr__(name: str):
    return getattr(_yc_job_runner, name)
