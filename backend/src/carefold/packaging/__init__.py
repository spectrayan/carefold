# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
