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

"""Settings subsystem providing hexagonal SettingsPort and SQL adapter."""

from carefold.settings.adapters.sql_adapter import SqlSettingsAdapter
from carefold.settings.factory import (
    create_settings_port,
    get_settings_port,
    reset_settings_port,
    reset_settings_ports,
    set_settings_port,
)
from carefold.settings.ports import SECRET_MASK, SettingsPort

__all__ = [
    "SECRET_MASK",
    "SettingsPort",
    "SqlSettingsAdapter",
    "create_settings_port",
    "get_settings_port",
    "reset_settings_port",
    "reset_settings_ports",
    "set_settings_port",
]
