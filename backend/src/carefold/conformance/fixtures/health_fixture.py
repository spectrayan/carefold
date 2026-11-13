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

"""First-party health pack fixture for cross-scope conformance testing (Step C2e)."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Tuple
from fastapi import APIRouter, Depends
from yarvelle_core.api.errors import ProblemDetailsRoute

from carefold.db.models import Note
from carefold.engine.tool_registry import DataFlows, ToolSpec
from carefold.errors import YarvelleError
from carefold.schemas.tool import ToolResult
from carefold.scope.context import require_scope


async def _execute_record_vitals(args: Dict[str, Any] = None, ctx: Any = None) -> ToolResult:
    return ToolResult(
        success=True,
        output={"status": "recorded", "vital": "bp_120_80"},
    )


HEALTH_CONFORMANCE_TOOL = ToolSpec(
    name="mock_health_record_vitals",
    description="Record patient clinical vitals for conformance testing",
    risk_tier="write_local",
    data_flows=DataFlows(),
    scopes={"health.clinical"},
    executor=_execute_record_vitals,
)


def _check_health_scope() -> None:
    try:
        require_scope("health.clinical", level="read")
    except Exception as exc:
        raise YarvelleError(
            "YRV-300-008",
            detail=f"Scope grant 'health.clinical:read' required: {exc}",
            cause=exc,
            context={'scope': "health.clinical", 'level': "read"},
        ) from exc


health_conformance_router = APIRouter(
    prefix="/test-health",
    tags=["test_health"],
    route_class=ProblemDetailsRoute,
)


@health_conformance_router.get("/vitals", dependencies=[Depends(_check_health_scope)])
async def list_mock_vitals():
    return {"status": "ok", "vitals": [{"type": "blood_pressure", "value": "120/80"}]}


class HealthPackFixture:
    """Fixture simulating the first-party Carefold Health domain pack."""

    pack_id: str = "health"
    domain: str = "health"
    owned_scopes: List[str] = ["health.clinical", "health.paperwork"]
    declared_reads: List[str] = ["health.*"]

    def create_orm_record(
        self, session: Any, profile_id: str, scope: str = "health.clinical"
    ) -> Note:
        return Note(
            id=f"note-{profile_id[:8]}",
            profile_id=profile_id,
            slug=f"slug-{profile_id[:8]}",
            scope=scope,
            title="Clinical Visit Summary",
            content="Prescribed Metformin 500mg daily with breakfast. Patient reports stable vitals.",
        )

    def create_cas_file(
        self, cas_root: Any, profile_id: str, scope: str = "health.clinical"
    ) -> Tuple[str, bytes]:
        content = b"CLINICAL LAB RESULTS: A1C 6.4%, BP 120/80 mmHg, Glucose 98 mg/dL"
        sha = hashlib.sha256(content).hexdigest()
        return sha, content

    def create_search_document(
        self, profile_id: str, scope: str = "health.clinical"
    ) -> Tuple[str, str]:
        return "doc-health-001", "Prescribed Metformin 500mg daily. Follow-up appointment in 3 months."

    def create_memory_entry(
        self, profile_id: str, scope: str = "health.clinical"
    ) -> Tuple[str, str]:
        return f"scope:{scope}/profile:{profile_id}/working", "Patient reports mild fatigue after morning exercise"

    def create_vault_secret(
        self, profile_id: str, scope: str = "health.clinical"
    ) -> bytes:
        return b"HEALTH_PORTAL_OAUTH_REFRESH_TOKEN_332211"

    def get_test_tool(self) -> ToolSpec:
        return HEALTH_CONFORMANCE_TOOL

    def get_test_router(self) -> APIRouter:
        return health_conformance_router

    def get_exportable_dossier(
        self, profile_id: str, scope: str = "health.clinical"
    ) -> Dict[str, Any]:
        return {
            "domain": "health",
            "scope": scope,
            "profile_id": profile_id,
            "vitals": {"blood_pressure": "120/80", "heart_rate": 72},
            "medications": ["Metformin 500mg"],
        }


__all__ = [
    "HEALTH_CONFORMANCE_TOOL",
    "health_conformance_router",
    "HealthPackFixture",
]
