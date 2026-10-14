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

"""OS background service packaging descriptors for macOS, Linux, and Windows (AU-81)."""

from __future__ import annotations

from carefold.packaging.service import (
    generate_linux_systemd_unit,
    generate_macos_launchd_plist,
    generate_windows_task_xml,
    list_os_service_descriptors,
)

__all__ = [
    "generate_linux_systemd_unit",
    "generate_macos_launchd_plist",
    "generate_windows_task_xml",
    "list_os_service_descriptors",
]
