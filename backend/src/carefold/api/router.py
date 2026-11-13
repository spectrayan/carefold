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

"""Master API Router assembling core and Carefold pack contributions via mount_router_contributions."""

from __future__ import annotations

from typing import List, Optional, Sequence
from fastapi import APIRouter, Depends, Request

from yarvelle_core.api.errors import ProblemDetailsRoute
from yarvelle_core.api.router import (
    PackRouterContractError,
    build_contribution_dependencies,
    mount_router_contributions,
)
from yarvelle_core.pack.spec import RouterContribution
from carefold.errors import YarvelleError

from carefold.api.activity import router as activity_router
from carefold.api.admin import router as admin_router
from carefold.api.agents import router as agents_router
from carefold.api.approvals import router as approvals_router
from carefold.api.attachments import router as attachments_router
from carefold.api.audit import router as audit_router
from carefold.api.auth import router as auth_router
from carefold.api.chat import router as chat_router
from carefold.api.connections import router as connections_router
from carefold.api.email_drafts import core_email_drafts_router as email_drafts_router
from carefold.api.health import router as health_router
from carefold.api.i18n import router as i18n_router
from carefold.api.memory import router as memory_router
from carefold.api.models import router as models_router
from carefold.api.notes import router as notes_router
from carefold.api.profiles import router as profiles_router
from carefold.api.reminders import router as reminders_router
from carefold.api.routines import router as routines_router
from carefold.api.search import router as search_router
from carefold.api.skills import router as skills_router
from carefold.routers import get_health_router_contributions


def get_default_router_contributions() -> List[RouterContribution]:
    """Returns ordered core + Carefold health pack router contributions."""
    health_by_router_id = {id(c.router): c for c in get_health_router_contributions()}
    from carefold.routers import (
        appointments_router,
        companion_router,
        coordinated_router,
        fhir_r4_router,
        handover_router,
        imports_router,
        prep_pack_router,
        preventive_router,
        school_forms_router,
        vitals_router,
    )

    return [
        RouterContribution(health_router, pack_id="core"),
        RouterContribution(i18n_router, pack_id="core"),
        health_by_router_id[id(vitals_router)],
        health_by_router_id[id(appointments_router)],
        RouterContribution(reminders_router, pack_id="core"),
        RouterContribution(activity_router, pack_id="core"),
        health_by_router_id[id(preventive_router)],
        health_by_router_id[id(imports_router)],
        health_by_router_id[id(school_forms_router)],
        RouterContribution(connections_router, pack_id="core"),
        RouterContribution(routines_router, pack_id="core"),
        RouterContribution(email_drafts_router, pack_id="core"),
        health_by_router_id[id(companion_router)],
        health_by_router_id[id(handover_router)],
        health_by_router_id[id(coordinated_router)],
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
        health_by_router_id[id(prep_pack_router)],
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
        health_by_router_id[id(fhir_r4_router)],
    ]


_AGENT_HTTP_PRINCIPALS = frozenset({"agent", "db-operator", "mcp_agent", "autonomous_agent"})
_HTTP_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def enforce_user_intended_http_mutation(request: Request) -> None:
    """Blocks agent principals from invoking HTTP mutation routes directly (#344).

    HTTP POST/PUT/PATCH/DELETE endpoints are reserved for explicit user-intended
    updates. Agent-originated database reads and writes must execute through
    McpDatabaseToolbox / db-operator.
    """
    if request.method.upper() not in _HTTP_MUTATION_METHODS:
        return
    raw_principal = (
        request.headers.get("x-carefold-principal")
        or request.headers.get("x-yarvelle-principal")
        or getattr(request.state, "principal", None)
        or ""
    )
    if str(raw_principal).strip().lower() in _AGENT_HTTP_PRINCIPALS:
        raise YarvelleError(
            "YRV-300-013",
            detail=(
                "HTTP mutation endpoints are reserved for explicit user-intended updates; "
                "agent database writes must execute through McpDatabaseToolbox / db-operator."
            ),
        )


def create_api_router(
    contributions: Optional[Sequence[RouterContribution]] = None,
) -> APIRouter:
    """Builds and returns the composite APIRouter enforcing require_pack_scope via mount_router_contributions."""
    router = APIRouter(
        route_class=ProblemDetailsRoute,
        dependencies=[Depends(enforce_user_intended_http_mutation)],
    )
    items = contributions if contributions is not None else get_default_router_contributions()
    return mount_router_contributions(router, items)


api_router: APIRouter = create_api_router()

__all__ = [
    "PackRouterContractError",
    "RouterContribution",
    "api_router",
    "build_contribution_dependencies",
    "create_api_router",
    "enforce_user_intended_http_mutation",
    "get_default_router_contributions",
    "mount_router_contributions",
]
