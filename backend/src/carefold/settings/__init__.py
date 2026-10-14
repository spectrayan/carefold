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
