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

from carefold.api.agents import router as agents_router
from carefold.api.attachments import router as attachments_router
from carefold.api.audit import router as audit_router
from carefold.api.chat import router as chat_router
from carefold.api.health import router as health_router
from carefold.api.memory import router as memory_router
from carefold.api.models import router as models_router
from carefold.api.notes import router as notes_router
from carefold.api.skills import router as skills_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(agents_router)
api_router.include_router(skills_router)
api_router.include_router(audit_router)
api_router.include_router(chat_router)
api_router.include_router(models_router)
api_router.include_router(attachments_router)
api_router.include_router(notes_router)
api_router.include_router(memory_router, prefix="/memory", tags=["memory"])

__all__ = ["api_router"]
