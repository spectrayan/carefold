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

"""Egress restriction and SSRF containment tests for ScopedHttp client."""

from __future__ import annotations

import httpx
import pytest

from connectors.errors import EgressBlockedError
from connectors.http import ScopedHttp


@pytest.fixture
def mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok", "url": str(request.url)})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_scoped_http_allowlisted_host_succeeds(mock_transport: httpx.MockTransport):
    """Verify requests to explicitly declared hosts succeed cleanly."""
    client = httpx.AsyncClient(transport=mock_transport)
    scoped = ScopedHttp(
        allowed_hosts=["fhir.epic.com", "api.labcorp.com"],
        client=client,
    )

    # 1. GET to allowlisted host
    res = await scoped.get("https://fhir.epic.com/api/Patient/123")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # 2. POST to another allowlisted host
    res_post = await scoped.post("https://api.labcorp.com/orders", json={"order_id": 42})
    assert res_post.status_code == 200


@pytest.mark.asyncio
async def test_scoped_http_blocks_unauthorized_host(mock_transport: httpx.MockTransport):
    """Verify requests to unlisted outbound hosts raise EgressBlockedError with zero network bytes sent."""
    client = httpx.AsyncClient(transport=mock_transport)
    scoped = ScopedHttp(allowed_hosts=["fhir.epic.com"], client=client)

    with pytest.raises(EgressBlockedError) as exc_info:
        await scoped.get("https://unauthorized-leak.com/exfiltrate")
    assert "blocked by manifest policy" in str(exc_info.value)
    assert exc_info.value.host == "unauthorized-leak.com"


@pytest.mark.asyncio
async def test_scoped_http_blocks_cloud_metadata(mock_transport: httpx.MockTransport):
    """Verify attempt to target cloud metadata IPs raises EgressBlockedError even if tricked into allowlist."""
    client = httpx.AsyncClient(transport=mock_transport)
    # Even if an adversary tried to place the metadata IP in allowed_hosts:
    scoped = ScopedHttp(
        allowed_hosts=["169.254.169.254", "169.254.170.2", "fhir.epic.com"],
        client=client,
    )

    # AWS/GCP instance metadata
    with pytest.raises(EgressBlockedError) as exc_aws:
        await scoped.get("http://169.254.169.254/latest/meta-data/")
    assert "metadata" in str(exc_aws.value).lower()

    # AWS ECS task metadata
    with pytest.raises(EgressBlockedError) as exc_ecs:
        await scoped.get("http://169.254.170.2/v2/metadata")
    assert "metadata" in str(exc_ecs.value).lower()


@pytest.mark.asyncio
async def test_scoped_http_blocks_link_local_ips(mock_transport: httpx.MockTransport):
    """Verify link-local IPv4 and IPv6 addresses are blocked unconditionally."""
    client = httpx.AsyncClient(transport=mock_transport)
    scoped = ScopedHttp(allowed_hosts=["169.254.1.20", "fe80::1"], client=client)

    with pytest.raises(EgressBlockedError) as exc_v4:
        await scoped.get("http://169.254.1.20/api")
    assert "link-local" in str(exc_v4.value).lower()

    with pytest.raises(EgressBlockedError) as exc_v6:
        await scoped.get("http://[fe80::1]/api")
    assert "link-local" in str(exc_v6.value).lower() or "scheme" in str(exc_v6.value).lower() or "metadata" in str(exc_v6.value).lower()


@pytest.mark.asyncio
async def test_scoped_http_blocks_prohibited_schemes(mock_transport: httpx.MockTransport):
    """Verify non-HTTP(S) schemes are blocked immediately."""
    client = httpx.AsyncClient(transport=mock_transport)
    scoped = ScopedHttp(allowed_hosts=["fhir.epic.com"], client=client)

    prohibited = [
        "file:///etc/passwd",
        "ftp://fhir.epic.com/files",
        "gopher://fhir.epic.com/1",
        "ldap://fhir.epic.com/ou=people",
    ]
    for url in prohibited:
        with pytest.raises(EgressBlockedError) as exc:
            await scoped.get(url)
        assert "scheme" in str(exc.value).lower() or "prohibited" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_scoped_http_async_context_manager(mock_transport: httpx.MockTransport):
    """Verify ScopedHttp operates cleanly as an async context manager."""
    client = httpx.AsyncClient(transport=mock_transport)
    async with ScopedHttp(allowed_hosts=["fhir.epic.com"], client=client) as http:
        res = await http.get("https://fhir.epic.com/health")
        assert res.status_code == 200
