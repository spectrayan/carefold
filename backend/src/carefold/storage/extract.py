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

"""Re-export shim delegating to yarvelle_core.storage.extract."""

from __future__ import annotations

from yarvelle_core.storage.extract import *  # noqa: F401, F403
from yarvelle_core.storage.extract import Image, _OCR_AVAILABLE, _PYPDF_AVAILABLE, pypdf, pytesseract
import yarvelle_core.storage.extract as _yc_extract
from carefold.clinical.host_bridges import (
    extract_cas_attachment_compat as extract_cas_attachment,
    extract_cas_document_compat as extract_cas_document,
    extract_document_text_compat as extract_document_text,
)


def __getattr__(name: str):
    return getattr(_yc_extract, name)
