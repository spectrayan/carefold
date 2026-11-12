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

"""OAuth broker shim re-exporting yarvelle_core.connectors.oauth and Carefold SMART on FHIR helpers."""

from __future__ import annotations

from yarvelle_core.connectors.oauth import *  # noqa: F401, F403
from carefold.connectors.smart_fhir import (  # noqa: F401
    SMART_V1_CLINICAL_SCOPES,
    SMART_V2_CLINICAL_SCOPES,
    SmartConfiguration,
    build_smart_authorization_url,
    discover_smart_configuration,
    redact_smart_auth_secrets,
)

import yarvelle_core.connectors.oauth as _yc_mod

def __getattr__(name: str):
    return getattr(_yc_mod, name)
