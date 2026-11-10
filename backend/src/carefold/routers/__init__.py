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

"""Carefold health API routers and router contribution definitions."""

from __future__ import annotations

from typing import List

from yarvelle_core.pack.spec import RouterContribution

from carefold.routers.appointments import router as appointments_router
from carefold.routers.companion import router as companion_router
from carefold.routers.coordinated import router as coordinated_router
from carefold.routers.fhir_r4 import router as fhir_r4_router
from carefold.routers.handover import router as handover_router
from carefold.routers.imports import router as imports_router
from carefold.routers.prep_pack import router as prep_pack_router
from carefold.routers.preventive import router as preventive_router
from carefold.routers.school_forms import router as school_forms_router
from carefold.routers.vitals import router as vitals_router


def get_health_router_contributions() -> List[RouterContribution]:
    """Returns the 9 health router contributions."""
    return [
        RouterContribution(vitals_router, pack_id="health", scope="health.clinical", level="read"),
        RouterContribution(appointments_router, pack_id="health", scope="health.clinical", level="read"),
        RouterContribution(preventive_router, pack_id="health", scope="health.clinical", level="read"),
        RouterContribution(imports_router, pack_id="health", scope="health.clinical", level="write"),
        RouterContribution(school_forms_router, pack_id="health", scope="health.clinical", level="read"),
        RouterContribution(companion_router, pack_id="health", scope="health.clinical", level="read"),
        RouterContribution(handover_router, pack_id="health", scope="health.clinical", level="read"),
        RouterContribution(coordinated_router, pack_id="health", scope="health.clinical", level="read"),
        RouterContribution(prep_pack_router, pack_id="health", scope="health.clinical", level="read"),
    ]


__all__ = [
    "appointments_router",
    "companion_router",
    "coordinated_router",
    "fhir_r4_router",
    "handover_router",
    "imports_router",
    "prep_pack_router",
    "preventive_router",
    "school_forms_router",
    "vitals_router",
    "get_health_router_contributions",
]
