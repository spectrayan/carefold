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

"""Master API Router mounting all Carefold endpoints."""

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Union
from fastapi import APIRouter

from carefold.api.activity import router as activity_router
from carefold.api.admin import router as admin_router
from carefold.api.agents import router as agents_router
from carefold.api.appointments import router as appointments_router
from carefold.api.approvals import router as approvals_router
from carefold.api.attachments import router as attachments_router
from carefold.api.audit import router as audit_router
from carefold.api.auth import router as auth_router
from carefold.api.chat import router as chat_router
from carefold.api.companion import router as companion_router
from carefold.api.connections import router as connections_router
from carefold.api.coordinated import router as coordinated_router
from carefold.api.email_drafts import router as email_drafts_router
from carefold.api.fhir_r4 import router as fhir_r4_router
from carefold.api.handover import router as handover_router
from carefold.api.health import router as health_router
from carefold.api.i18n import router as i18n_router
from carefold.api.imports import router as imports_router
from carefold.api.memory import router as memory_router
from carefold.api.models import router as models_router
from carefold.api.notes import router as notes_router
from carefold.api.prep_pack import router as prep_pack_router
from carefold.api.preventive import router as preventive_router
from carefold.api.profiles import router as profiles_router
from carefold.api.reminders import router as reminders_router
from carefold.api.routines import router as routines_router
from carefold.api.school_forms import router as school_forms_router
from carefold.api.search import router as search_router
from carefold.api.skills import router as skills_router
from carefold.api.vitals import router as vitals_router


@dataclass
class RouterContribution:
    """Metadata describing an API router contribution from core or a domain pack."""

    router: APIRouter
    prefix: str = ""
    tags: Optional[List[Union[str, Any]]] = None
    dependencies: Optional[Sequence[Any]] = None
    include_in_schema: bool = True
    pack_id: Optional[str] = None
    scope: Optional[str] = None
    level: Optional[str] = None


def get_default_router_contributions() -> List[RouterContribution]:
    """Returns the ordered list of 32 router contributions matching baseline openapi.json."""
    return [
        RouterContribution(health_router, pack_id="core"),
        RouterContribution(i18n_router, pack_id="core"),
        RouterContribution(vitals_router, pack_id="health", scope="health.clinical", level="read"),
        RouterContribution(appointments_router, pack_id="health", scope="health.clinical", level="read"),
        RouterContribution(reminders_router, pack_id="core"),
        RouterContribution(activity_router, pack_id="core"),
        RouterContribution(preventive_router, pack_id="health", scope="health.clinical", level="read"),
        RouterContribution(imports_router, pack_id="health", scope="health.clinical", level="write"),
        RouterContribution(school_forms_router, pack_id="health", scope="health.clinical", level="read"),
        RouterContribution(connections_router, pack_id="core"),
        RouterContribution(routines_router, pack_id="core"),
        RouterContribution(email_drafts_router, pack_id="core"),
        RouterContribution(companion_router, pack_id="health", scope="health.clinical", level="read"),
        RouterContribution(handover_router, pack_id="health", scope="health.clinical", level="read"),
        RouterContribution(coordinated_router, pack_id="health", scope="health.clinical", level="read"),
        RouterContribution(agents_router, pack_id="core"),
        RouterContribution(skills_router, pack_id="core"),
        RouterContribution(audit_router, pack_id="core"),
        RouterContribution(approvals_router, prefix="/approvals", tags=["approvals"], pack_id="core"),
        RouterContribution(
            approvals_router,
            prefix="/profiles/{profile_id}/approvals",
            tags=["approvals"],
            include_in_schema=False,
            pack_id="core",
        ),
        RouterContribution(chat_router, pack_id="core"),
        RouterContribution(models_router, pack_id="core"),
        RouterContribution(attachments_router, pack_id="core"),
        RouterContribution(notes_router, pack_id="core"),
        RouterContribution(prep_pack_router, pack_id="health", scope="health.clinical", level="read"),
        RouterContribution(profiles_router, prefix="/profiles", tags=["profiles"], pack_id="core"),
        RouterContribution(search_router, pack_id="core"),
        RouterContribution(
            search_router, prefix="/profiles", tags=["search"], include_in_schema=False, pack_id="core"
        ),
        RouterContribution(memory_router, prefix="/memory", tags=["memory"], pack_id="core"),
        RouterContribution(
            memory_router, prefix="/memories", tags=["memory"], include_in_schema=False, pack_id="core"
        ),
        RouterContribution(auth_router, prefix="/auth", tags=["auth"], pack_id="core"),
        RouterContribution(admin_router, prefix="/admin", tags=["admin"], pack_id="core"),
        RouterContribution(fhir_r4_router, pack_id="health", scope="health.clinical", level="read"),
    ]


def create_api_router(
    contributions: Optional[Sequence[RouterContribution]] = None,
) -> APIRouter:
    """Builds and returns the composite APIRouter from an ordered list of RouterContributions."""
    router = APIRouter()
    items = contributions if contributions is not None else get_default_router_contributions()
    for contrib in items:
        kwargs: dict[str, Any] = {}
        if contrib.prefix:
            kwargs["prefix"] = contrib.prefix
        if contrib.tags:
            kwargs["tags"] = contrib.tags
        if contrib.dependencies:
            kwargs["dependencies"] = contrib.dependencies
        if not contrib.include_in_schema:
            kwargs["include_in_schema"] = False
        router.include_router(contrib.router, **kwargs)
    return router


api_router: APIRouter = create_api_router()

__all__ = ["api_router", "create_api_router", "RouterContribution", "get_default_router_contributions"]

