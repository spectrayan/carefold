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

"""Re-export shim delegating email draft routes to yarvelle_core.api.email_drafts."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter
from yarvelle_core.api.errors import ProblemDetailsRoute
import yarvelle_core.api.email_drafts as _target_module
from carefold.routers.imports import router as _imports_router
from carefold.routers.school_forms import router as _school_forms_router

core_email_drafts_router = APIRouter(tags=["email-and-school"], route_class=ProblemDetailsRoute)
router = APIRouter(tags=["email-and-school"], route_class=ProblemDetailsRoute)
for _r in _target_module.router.routes:
    if "/email-drafts" in getattr(_r, "path", ""):
        core_email_drafts_router.routes.append(_r)
        router.routes.append(_r)
for _r in [*_imports_router.routes, *_school_forms_router.routes]:
    if "/gmail/" in getattr(_r, "path", "") or "/school-ics" in getattr(_r, "path", ""):
        router.routes.append(_r)


def __getattr__(name: str) -> Any:
    return getattr(_target_module, name)
