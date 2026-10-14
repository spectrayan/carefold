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

"""Compatibility shim for carefold.tools.attach_read.

Re-exports execute_attach_read and attach_read_tool.
"""

from __future__ import annotations

from carefold.tools.attach_read import (
    ALLOWED_ATTACHMENT_EXTENSIONS,
    ALLOWED_TEXT_EXTS,
    MAX_FILE_SIZE,
    attach_read_tool,
    execute_attach_read,
    extract_text_from_pdf_bytes,
)

__all__ = [
    "ALLOWED_ATTACHMENT_EXTENSIONS",
    "ALLOWED_TEXT_EXTS",
    "MAX_FILE_SIZE",
    "attach_read_tool",
    "execute_attach_read",
    "extract_text_from_pdf_bytes",
]
