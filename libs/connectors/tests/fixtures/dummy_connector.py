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

"""Sample clinical connector fixture for unit and integration testing."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from connectors.base import (
    Connector,
    NormalisedRecord,
    Page,
    StreamSpec,
    ToolContext,
    ToolSpec,
)
from connectors.http import ScopedHttp
from connectors.manifest import (
    AuthConfig,
    ConnectorManifest,
    DataFlowSpec,
    PolicyConfig,
    TermsConfig,
    ToolDeclaration,
    TrustConfig,
)


class DummyClinicalConnector:
    """Fixture implementing the Connector protocol for clinical vitals and labs."""

    def __init__(self, allowed_host: str = "fhir.example-health.org") -> None:
        self.allowed_host = allowed_host
        self._manifest = ConnectorManifest(
            id="dummy-clinical",
            version="1.0.0",
            name="Dummy Clinical EHR Connector",
            description="Mock EHR connector for testing protocol compliance and tool execution.",
            data_flows=DataFlowSpec(
                allowed_hosts=[allowed_host],
                allowed_schemes=["https"],
                allowed_ports=[443],
                egress_direction="egress_only",
                pii_types_transferred=["medical_record_number", "vitals"],
            ),
            auth=AuthConfig(
                type="oauth2",
                scopes=["patient/Observation.read", "patient/Patient.read"],
                authorization_url=f"https://{allowed_host}/oauth2/authorize",
                token_url=f"https://{allowed_host}/oauth2/token",
                token_rotation=True,
            ),
            tools=[
                ToolDeclaration(
                    name="get_patient_vitals",
                    description="Retrieves latest blood pressure and heart rate observations.",
                    risk_class="read_only",
                ),
            ],
            trust=TrustConfig(
                publisher="Spectrayan Testing Lab",
                verified=True,
                sandbox_level="strict",
            ),
            policy=PolicyConfig(
                rate_limit_rpm=120,
                timeout_seconds=15.0,
                retry_max_attempts=2,
            ),
            terms=TermsConfig(
                license="Apache-2.0",
                privacy_policy_url=f"https://{allowed_host}/privacy",
            ),
        )

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def streams(self) -> List[StreamSpec]:
        return [
            StreamSpec(
                name="observations",
                description="Clinical lab results and vital signs",
                read_mode="incremental",
                primary_key=["id"],
                cursor_field="updated_at",
            ),
            StreamSpec(
                name="medications",
                description="Active medication prescriptions",
                read_mode="full_refresh",
                primary_key=["id"],
            ),
        ]

    async def fetch(
        self,
        ctx: ToolContext,
        stream: str,
        cursor: Optional[str],
        http: ScopedHttp,
    ) -> Page:
        # Calls the external endpoint via ScopedHttp
        target_url = f"https://{self.allowed_host}/api/{stream}"
        response = await http.get(target_url, params={"cursor": cursor} if cursor else None)
        data = response.json() if hasattr(response, "json") else {"records": []}
        records = data.get("records", [])
        next_cur = data.get("next_cursor")
        return Page(
            stream=stream,
            records=records,
            next_cursor=next_cur,
            has_more=bool(next_cur),
            metadata={"status": response.status_code if hasattr(response, "status_code") else 200},
        )

    def map(self, page: Page) -> List[NormalisedRecord]:
        results: List[NormalisedRecord] = []
        for r in page.records:
            rec_id = str(r.get("id", "rec-0"))
            raw_serialized = json.dumps(r, sort_keys=True).encode("utf-8")
            raw_hash = hashlib.sha256(raw_serialized).hexdigest()
            results.append(
                NormalisedRecord(
                    id=rec_id,
                    stream=page.stream,
                    profile_id=r.get("profile_id", "default-profile"),
                    source=self.manifest.id,
                    record_type="observation" if page.stream == "observations" else "medication",
                    timestamp=None,
                    data=r,
                    raw_hash=raw_hash,
                )
            )
        return results

    def tools(self) -> List[ToolSpec]:
        async def _get_patient_vitals_handler(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
            # Enforce fail-closed profile_id scoping
            if not ctx.profile_id:
                raise ValueError("ToolContext profile_id is required.")
            vitals_type = args.get("vital_type", "all")
            return {
                "profile_id": ctx.profile_id,
                "vital_type": vitals_type,
                "blood_pressure": "120/80 mmHg",
                "heart_rate": 72,
                "recorded_at": "2026-10-12T00:00:00Z",
            }

        return [
            ToolSpec(
                name="get_patient_vitals",
                description="Retrieves latest blood pressure and heart rate observations.",
                parameters={
                    "type": "object",
                    "properties": {
                        "vital_type": {"type": "string", "enum": ["bp", "hr", "all"]},
                    },
                },
                risk_class="read_only",
                handler=_get_patient_vitals_handler,
            ),
        ]


__all__ = ["DummyClinicalConnector"]
