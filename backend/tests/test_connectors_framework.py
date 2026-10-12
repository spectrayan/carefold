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

"""Integration and regression test suite for Milestone 6 Core Connector Framework.

Validates:
- AU-50: Connector protocol compliance, stream specs, normalisation, manifest parsing.
- AU-51: ScopedHttp host allowlist enforcement, egress blocking, anti-SSRF protection.
- AU-52: Connection and Credential ORM models, state transitions, synonyms, optimistic concurrency.
- R7: Universal tool execution choke point (execute_tool_call) enforcement and fail-closed security.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from carefold.db.base import Base
from carefold.db.models import Connection, ConnectionState, Credential, Profile, User
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.engine.tool_exec import (
    ToolContext as EngineToolContext,
    ToolSpec as EngineToolSpec,
    execute_tool_call,
)
from connectors.base import (
    Connector,
    NormalisedRecord,
    Page,
    StreamSpec,
    ToolContext,
    ToolSpec,
)
from connectors.errors import EgressBlockedError, ManifestValidationError
from connectors.http import ScopedHttp
from connectors.manifest import (
    AuthConfig,
    ConnectorManifest,
    DataFlowSpec,
    PolicyConfig,
    TermsConfig,
    TrustConfig,
)


# ==============================================================================
# Fixtures and Sample Connector Implementation
# ==============================================================================

class SampleClinicalConnector:
    """Production-grade sample connector implementing the Connector Protocol."""

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="sample-portal-connector",
            version="1.0.0",
            name="Sample Hospital Health System",
            description="Integration with Sample Hospital patient portal FHIR API",
            data_flows=DataFlowSpec(
                allowed_hosts=["api.samplehospital.org", "auth.samplehospital.org"],
                allowed_schemes=["https"],
            ),
            auth=AuthConfig(
                type="oauth2",
                token_url="https://auth.samplehospital.org/oauth/token",
                authorization_url="https://auth.samplehospital.org/oauth/authorize",
                scopes=["patient/*.read", "Observation.read"],
            ),
            trust=TrustConfig(
                publisher="Spectrayan Health Team",
                verified=True,
                sandbox_level="strict",
            ),
            policy=PolicyConfig(
                rate_limit_rpm=60,
                timeout_seconds=30.0,
            ),
            terms=TermsConfig(
                license="Apache-2.0",
            ),
        )

    def streams(self) -> list[StreamSpec]:
        return [
            StreamSpec(
                name="observations",
                description="Clinical lab results and vital sign observations",
                read_mode="incremental",
                primary_key=["id"],
                cursor_field="effectiveDateTime",
            )
        ]

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="get_lab_results",
                description="Fetch authenticated lab results for a patient",
                parameters={
                    "type": "object",
                    "properties": {
                        "patient_id": {"type": "string"},
                        "category": {"type": "string"},
                    },
                    "required": ["patient_id"],
                },
                risk_class="read_only",
                handler=self.get_lab_results,
            )
        ]

    async def get_lab_results(self, args: dict, ctx: Any = None) -> dict:
        return {
            "patient_id": args.get("patient_id"),
            "category": args.get("category", "laboratory"),
            "count": 2,
            "observations": [
                {"code": "HbA1c", "value": "5.6", "unit": "%"},
                {"code": "Total Cholesterol", "value": "185", "unit": "mg/dL"},
            ],
        }

    async def fetch(
        self,
        ctx: ToolContext,
        stream: str,
        cursor: str | None,
        http: ScopedHttp,
    ) -> Page:
        records = [
            {"id": "obs-1", "code": "HbA1c", "effectiveDateTime": "2026-04-10T10:00:00Z"},
            {"id": "obs-2", "code": "Cholesterol", "effectiveDateTime": "2026-04-11T11:00:00Z"},
        ]
        return Page(stream=stream, records=records, next_cursor="2026-04-11T11:00:00Z", has_more=False)

    def map(self, page: Page) -> list[NormalisedRecord]:
        results: list[NormalisedRecord] = []
        for raw in page.records:
            raw_hash = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
            results.append(
                NormalisedRecord(
                    id=raw["id"],
                    stream=page.stream,
                    profile_id="prf-default",
                    source="sample-portal-connector",
                    record_type="observation",
                    timestamp=datetime.fromisoformat(raw["effectiveDateTime"]),
                    data=raw,
                    raw_hash=raw_hash,
                )
            )
        return results


@pytest.fixture
async def db_session(tmp_path: Path):
    """Provides an isolated async database session initialized via init_db() Alembic migrations."""
    db_file = tmp_path / "connectors_framework_test.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)

    factory = get_session_factory(engine)
    async with factory() as session:
        # Seed User and Profile
        user = User(
            id=str(uuid.uuid4()),
            email="test-steward@carefold.org",
            username="steward1",
            hashed_password="argon2id$v=19$m=65536,t=3,p=4$dummyhash",
            full_name="Steward One",
            role="steward",
        )
        profile = Profile(
            id=str(uuid.uuid4()),
            user_id=user.id,
            name="Jane Doe",
            relationship="self",
            role="self",
        )
        session.add_all([user, profile])
        await session.commit()
        yield session

    await engine.dispose()


# ==============================================================================
# 1. AU-50: Connector Protocol Compliance & Schema Tests
# ==============================================================================

def test_connector_protocol_compliance():
    """Verifies that SampleClinicalConnector satisfies the runtime-checkable Connector Protocol."""
    connector = SampleClinicalConnector()
    assert isinstance(connector, Connector)

    manifest = connector.manifest
    assert isinstance(manifest, ConnectorManifest)
    assert manifest.id == "sample-portal-connector"
    assert "api.samplehospital.org" in manifest.data_flows.allowed_hosts

    streams = connector.streams()
    assert len(streams) == 1
    assert isinstance(streams[0], StreamSpec)
    assert streams[0].name == "observations"

    tools = connector.tools()
    assert len(tools) == 1
    assert isinstance(tools[0], ToolSpec)
    assert tools[0].name == "get_lab_results"


@pytest.mark.asyncio
async def test_connector_streaming_and_normalisation():
    """Tests fetch and map execution on the sample connector."""
    connector = SampleClinicalConnector()
    ctx = ToolContext(user_id="usr-1", profile_id="prf-1")
    async with ScopedHttp(allowed_hosts=["api.samplehospital.org"]) as http:
        page = await connector.fetch(ctx=ctx, stream="observations", cursor=None, http=http)

    assert len(page.records) == 2
    assert page.has_more is False
    assert page.next_cursor == "2026-04-11T11:00:00Z"

    records = connector.map(page)
    assert len(records) == 2
    assert isinstance(records[0], NormalisedRecord)
    assert records[0].id == "obs-1"
    assert records[0].stream == "observations"
    assert records[0].record_type == "observation"


def test_tool_context_fail_closed_validation():
    """Asserts that connector ToolContext strictly fails closed when user_id or profile_id is missing."""
    with pytest.raises(ValueError, match="profile_id"):
        ToolContext(user_id="user-1", profile_id="")

    with pytest.raises(ValueError, match="profile_id"):
        ToolContext(user_id="user-1", profile_id="   ")

    with pytest.raises(ValueError, match="user_id"):
        ToolContext(user_id="", profile_id="profile-1")

    # Valid instantiation
    ctx = ToolContext(user_id="user-1", profile_id="profile-1", autonomy="supervised")
    assert ctx.user_id == "user-1"
    assert ctx.profile_id == "profile-1"
    assert ctx.autonomy == "supervised"


# ==============================================================================
# 2. AU-50: Manifest Validation & Schema Integrity Tests
# ==============================================================================

def test_manifest_validation_valid_and_invalid():
    """Tests manifest parsing from dictionary and rejects invalid schemas."""
    valid_dict = {
        "id": "portal-conn",
        "name": "Portal Connector",
        "version": "1.0.0",
        "description": "Integration connector",
        "data_flows": {
            "allowed_hosts": ["portal.health.org"],
            "allowed_schemes": ["https"],
        },
        "auth": {"type": "api_key"},
        "trust": {"publisher": "Health Org"},
        "policy": {"rate_limit_rpm": 60},
        "terms": {"license": "Apache-2.0"},
    }

    manifest = ConnectorManifest.from_dict(valid_dict)
    assert manifest.id == "portal-conn"
    assert manifest.auth.type == "api_key"

    # Missing mandatory id
    invalid_dict = dict(valid_dict)
    del invalid_dict["id"]
    with pytest.raises((ManifestValidationError, ValidationError)):
        ConnectorManifest.from_dict(invalid_dict)

    # Invalid auth type
    invalid_auth = dict(valid_dict)
    invalid_auth["auth"] = {"type": "unsupported_scheme"}
    with pytest.raises((ManifestValidationError, ValidationError)):
        ConnectorManifest.from_dict(invalid_auth)

    # Missing trust publisher
    invalid_trust = dict(valid_dict)
    invalid_trust["trust"] = {"verified": False}
    with pytest.raises((ManifestValidationError, ValidationError)):
        ConnectorManifest.from_dict(invalid_trust)


# ==============================================================================
# 3. AU-51: ScopedHttp Egress & SSRF Protection Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_scoped_http_allowlist_enforcement():
    """Verifies that ScopedHttp permits allowed hosts and strictly blocks unlisted hosts."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok", "host": request.url.host})

    transport = httpx.MockTransport(mock_handler)
    allowed_hosts = ["api.samplehospital.org"]

    async with ScopedHttp(allowed_hosts=allowed_hosts, transport=transport) as client:
        # Permitted host
        resp = await client.get("https://api.samplehospital.org/v1/ping")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Blocked host (not in allowlist)
        with pytest.raises(EgressBlockedError) as exc_info:
            await client.get("https://unauthorized-domain.com/v1/ping")
        assert "unauthorized-domain.com" in str(exc_info.value)
        assert exc_info.value.host == "unauthorized-domain.com"


@pytest.mark.asyncio
async def test_scoped_http_anti_ssrf_and_scheme_blocking():
    """Verifies that ScopedHttp blocks cloud metadata, link-local IPs, and prohibited schemes."""
    dangerous_allowlist = ["169.254.169.254", "169.254.170.2", "169.254.1.1"]

    async with ScopedHttp(allowed_hosts=dangerous_allowlist) as client:
        # AWS metadata service blocked
        with pytest.raises(EgressBlockedError) as exc_aws:
            await client.get("http://169.254.169.254/latest/meta-data")
        assert "metadata" in str(exc_aws.value).lower()

        # ECS metadata service blocked
        with pytest.raises(EgressBlockedError) as exc_ecs:
            await client.get("http://169.254.170.2/v2/credentials")
        assert "metadata" in str(exc_ecs.value).lower()

        # Link-local IPv4 blocked
        with pytest.raises(EgressBlockedError) as exc_ll:
            await client.get("http://169.254.1.1/internal")
        assert "link-local" in str(exc_ll.value).lower()

        # Scheme enforcement: non-HTTP schemes blocked
        with pytest.raises(EgressBlockedError) as exc_ftp:
            await client.get("ftp://api.samplehospital.org/files")
        assert "prohibited" in str(exc_ftp.value).lower()


# ==============================================================================
# 4. AU-52: Connection and Credential ORM Persistence & Synonyms
# ==============================================================================

@pytest.mark.asyncio
async def test_connection_and_credential_orm_persistence(db_session: AsyncSession):
    """Verifies CRUD lifecycle, synonyms, and relationships on Connection and Credential models."""
    user = (await db_session.execute(select(User))).scalar_one()
    profile = (await db_session.execute(select(Profile))).scalar_one()

    # Create Connection using state="pending_auth" synonym
    conn_id = str(uuid.uuid4())
    conn = Connection(
        id=conn_id,
        user_id=user.id,
        profile_id=profile.id,
        connector_id="sample-portal-connector",
        state="pending_auth",
        label="Sample Hospital EHR",
        config_json='{"fhir_version": "R4"}',
    )
    db_session.add(conn)
    await db_session.commit()

    # Verify synonym reads
    retrieved_conn = (await db_session.execute(select(Connection).where(Connection.id == conn_id))).scalar_one()
    assert retrieved_conn.state == "pending_auth"
    assert retrieved_conn.status == "pending_auth"
    assert retrieved_conn.label == "Sample Hospital EHR"

    # Transition to active
    retrieved_conn.state = "active"
    retrieved_conn.status_message = "Handshake authenticated"
    await db_session.commit()

    await db_session.refresh(retrieved_conn)
    assert retrieved_conn.state == "active"
    assert retrieved_conn.status == "active"

    # Create Credential with AAD binding and encrypted_data synonym
    cred_id = str(uuid.uuid4())
    aad_binding = f"carefold:p:{profile.id}:c:{conn.id}"
    cred = Credential(
        id=cred_id,
        connection_id=conn.id,
        user_id=user.id,
        profile_id=profile.id,
        encrypted_data="ciphertext_aes_gcm_token_payload",
        token_version=1,
        aad_binding=aad_binding,
        expires_at=datetime.now(timezone.utc),
    )
    db_session.add(cred)
    await db_session.commit()

    # Verify synonym reads on Credential
    retrieved_cred = (
        await db_session.execute(
            select(Credential).options(selectinload(Credential.connection)).where(Credential.id == cred_id)
        )
    ).scalar_one()
    assert retrieved_cred.encrypted_data == "ciphertext_aes_gcm_token_payload"
    assert retrieved_cred.encrypted_blob == "ciphertext_aes_gcm_token_payload"
    assert retrieved_cred.token_version == 1
    assert retrieved_cred.aad_binding == aad_binding

    # Verify relationship navigation
    assert retrieved_cred.connection.id == conn.id
    retrieved_conn_with_creds = (
        await db_session.execute(
            select(Connection).options(selectinload(Connection.credentials)).where(Connection.id == conn_id)
        )
    ).scalar_one()
    assert len(retrieved_conn_with_creds.credentials) == 1
    assert retrieved_conn_with_creds.credentials[0].id == cred.id


@pytest.mark.asyncio
async def test_credential_optimistic_concurrency_locking(db_session: AsyncSession):
    """Verifies that token_version provides optimistic concurrency control during rotation."""
    user = (await db_session.execute(select(User))).scalar_one()
    profile = (await db_session.execute(select(Profile))).scalar_one()

    conn = Connection(
        user_id=user.id,
        profile_id=profile.id,
        connector_id="sample-portal-connector",
        status=ConnectionState.ACTIVE.value,
    )
    db_session.add(conn)
    await db_session.commit()

    cred = Credential(
        connection_id=conn.id,
        user_id=user.id,
        profile_id=profile.id,
        encrypted_blob="token_v1",
        token_version=1,
    )
    db_session.add(cred)
    await db_session.commit()

    expected_version = 1

    # Worker A succeeds in rotating token: updates where token_version == 1
    stmt_a = (
        update(Credential)
        .where(Credential.id == cred.id, Credential.token_version == expected_version)
        .values(
            encrypted_blob="token_v2_by_worker_a",
            token_version=expected_version + 1,
            rotated_at=datetime.now(timezone.utc),
        )
    )
    res_a = await db_session.execute(stmt_a)
    await db_session.commit()
    assert res_a.rowcount == 1  # Successfully rotated

    # Worker B tries to rotate using the stale version (expected_version = 1)
    stmt_b = (
        update(Credential)
        .where(Credential.id == cred.id, Credential.token_version == expected_version)
        .values(
            encrypted_blob="token_v2_by_worker_b",
            token_version=expected_version + 1,
            rotated_at=datetime.now(timezone.utc),
        )
    )
    res_b = await db_session.execute(stmt_b)
    await db_session.commit()
    # Stale version update affected 0 rows (optimistic locking conflict prevented overwrite)
    assert res_b.rowcount == 0

    # Credential in database retains Worker A's update
    await db_session.refresh(cred)
    assert cred.token_version == 2
    assert cred.encrypted_blob == "token_v2_by_worker_a"


# ==============================================================================
# 5. R7: Universal Choke Point Execution (execute_tool_call) Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_connector_tool_execution_via_choke_point():
    """Asserts that connector tools execute strictly through execute_tool_call with security checks."""
    connector = SampleClinicalConnector()
    tool_spec = connector.tools()[0]
    # Set data_flows on connector tool spec for egress policy verification
    object.__setattr__(tool_spec, "data_flows", ("api.samplehospital.org",))

    # Connector native ToolContext passed directly to choke point
    valid_ctx = ToolContext(
        user_id="usr-steward-100",
        profile_id="prf-patient-200",
        autonomy="supervised",
    )

    # 1. Valid execution directly through choke point
    result = await execute_tool_call(
        ctx=valid_ctx,
        spec=tool_spec,
        args={"patient_id": "PT-5555", "category": "laboratory"},
    )
    assert result.success is True
    assert result.output["patient_id"] == "PT-5555"
    assert result.output["count"] == 2
    assert len(result.output["observations"]) == 2

    # 2. Fail-closed: missing profile_id raises ValueError on ToolContext creation
    with pytest.raises(ValueError, match="profile_id"):
        ToolContext(user_id="usr-100", profile_id="")

    # 3. Fail-closed: missing user_id raises ValueError on ToolContext creation
    with pytest.raises(ValueError, match="profile_id|user_id"):
        ToolContext(user_id="", profile_id="prf-200")

    # 4. Egress policy enforcement through choke point:
    # If a tool attempts external egress to an unauthorized host, choke point denies execution
    egress_denied_result = await execute_tool_call(
        ctx=valid_ctx,
        spec=tool_spec,
        args={"patient_id": "PT-5555", "url": "https://unauthorized-leak.net/api"},
    )
    assert egress_denied_result.success is False
    assert "denied by tool 'get_lab_results' data_flows policy" in egress_denied_result.error
