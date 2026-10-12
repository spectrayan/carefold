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

"""Protocol and runtime data model compliance tests for connectors."""

from __future__ import annotations

import httpx
import pytest

from connectors.base import (
    Connector,
    NormalisedRecord,
    Page,
    StreamSpec,
    ToolContext,
    ToolSpec,
)
from connectors.http import ScopedHttp
from connectors.manifest import ConnectorManifest
from .fixtures.dummy_connector import DummyClinicalConnector


def test_connector_protocol_runtime_checkable():
    """Verify DummyClinicalConnector satisfies the @runtime_checkable Connector protocol."""
    conn = DummyClinicalConnector()
    assert isinstance(conn, Connector)


def test_connector_manifest_properties():
    """Verify manifest property returns a valid ConnectorManifest."""
    conn = DummyClinicalConnector()
    manifest = conn.manifest
    assert isinstance(manifest, ConnectorManifest)
    assert manifest.id == "dummy-clinical"
    assert manifest.data_flows.allowed_hosts == ["fhir.example-health.org"]
    assert manifest.auth.type == "oauth2"


def test_connector_streams_spec():
    """Verify streams() returns well-formed StreamSpec instances."""
    conn = DummyClinicalConnector()
    streams = conn.streams()
    assert len(streams) == 2
    stream_names = {s.name for s in streams}
    assert stream_names == {"observations", "medications"}
    assert all(isinstance(s, StreamSpec) for s in streams)


@pytest.mark.asyncio
async def test_connector_fetch_and_map():
    """Verify fetch() retrieves Page and map() transforms it into NormalisedRecords."""
    conn = DummyClinicalConnector(allowed_host="fhir.example-health.org")
    ctx = ToolContext(user_id="usr-123", profile_id="prof-456")

    # Mock transport for ScopedHttp
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "records": [
                    {"id": "obs-1", "profile_id": "prof-456", "code": "BP", "value": "120/80"},
                    {"id": "obs-2", "profile_id": "prof-456", "code": "HR", "value": "72"},
                ],
                "next_cursor": "cur-next-99",
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    scoped_http = ScopedHttp(allowed_hosts=["fhir.example-health.org"], client=mock_client)

    page = await conn.fetch(ctx, stream="observations", cursor=None, http=scoped_http)
    assert isinstance(page, Page)
    assert len(page.records) == 2
    assert page.next_cursor == "cur-next-99"
    assert page.has_more is True

    records = conn.map(page)
    assert len(records) == 2
    assert all(isinstance(r, NormalisedRecord) for r in records)
    assert records[0].stream == "observations"
    assert records[0].profile_id == "prof-456"
    assert records[0].raw_hash != ""


def test_connector_tools_spec():
    """Verify tools() exposes callable tool specifications."""
    conn = DummyClinicalConnector()
    tools = conn.tools()
    assert len(tools) >= 1
    tool = tools[0]
    assert isinstance(tool, ToolSpec)
    assert tool.name == "get_patient_vitals"
    assert callable(tool.handler)


def test_tool_context_fail_closed_validation():
    """Verify ToolContext enforces non-empty profile_id and user_id fail-closed invariants."""
    # Valid
    ctx = ToolContext(user_id="user-1", profile_id="profile-1")
    assert ctx.user_id == "user-1"
    assert ctx.profile_id == "profile-1"

    # Missing/empty profile_id raises ValueError
    with pytest.raises(ValueError) as exc_p:
        ToolContext(user_id="user-1", profile_id="")
    assert "fail-closed" in str(exc_p.value).lower()

    # Missing/empty user_id raises ValueError
    with pytest.raises(ValueError) as exc_u:
        ToolContext(user_id="   ", profile_id="profile-1")
    assert "fail-closed" in str(exc_u.value).lower()
