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
from carefold.api.health import router as health_router
from carefold.api.imports import router as imports_router
from carefold.api.memory import router as memory_router
from carefold.api.models import router as models_router
from carefold.api.notes import router as notes_router
from carefold.api.prep_pack import router as prep_pack_router
from carefold.api.preventive import router as preventive_router
from carefold.api.profiles import router as profiles_router
from carefold.api.reminders import router as reminders_router
from carefold.api.school_forms import router as school_forms_router
from carefold.api.search import router as search_router
from carefold.api.skills import router as skills_router
from carefold.api.vitals import router as vitals_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(vitals_router)
api_router.include_router(appointments_router)
api_router.include_router(reminders_router)
api_router.include_router(activity_router)
api_router.include_router(preventive_router)
api_router.include_router(imports_router)
api_router.include_router(school_forms_router)

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
