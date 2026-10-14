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

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(i18n_router)
api_router.include_router(vitals_router)
api_router.include_router(appointments_router)
api_router.include_router(reminders_router)
api_router.include_router(activity_router)
api_router.include_router(preventive_router)
api_router.include_router(imports_router)
api_router.include_router(school_forms_router)
api_router.include_router(connections_router)
api_router.include_router(routines_router)
api_router.include_router(email_drafts_router)
api_router.include_router(companion_router)
api_router.include_router(handover_router)
api_router.include_router(coordinated_router)

api_router.include_router(agents_router)
api_router.include_router(skills_router)
api_router.include_router(audit_router)
api_router.include_router(approvals_router, prefix="/approvals", tags=["approvals"])
api_router.include_router(
    approvals_router,
    prefix="/profiles/{profile_id}/approvals",
    tags=["approvals"],
    include_in_schema=False,
)
api_router.include_router(chat_router)
api_router.include_router(models_router)
api_router.include_router(attachments_router)
api_router.include_router(notes_router)
api_router.include_router(prep_pack_router)
api_router.include_router(profiles_router, prefix="/profiles", tags=["profiles"])
api_router.include_router(search_router)
api_router.include_router(search_router, prefix="/profiles", tags=["search"], include_in_schema=False)
api_router.include_router(memory_router, prefix="/memory", tags=["memory"])
api_router.include_router(memory_router, prefix="/memories", tags=["memory"], include_in_schema=False)
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(admin_router, prefix="/admin", tags=["admin"])

__all__ = ["api_router"]
