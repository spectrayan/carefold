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

"""Adversarial stress and empirical verification suite for Egress Firewall and Choke Point anti-SSRF protections.

Authored by challenger_m3_2.
Verifies:
1. Cloud metadata IP blocking (169.254.169.254 across ports, paths, credentials).
2. Subdomain confusion attacks against allowlisted hosts.
3. Port stripping and case normalization on legitimate and illegitimate hosts.
4. Credential URL injection (@ symbol, basic auth syntax).
5. Zero network bytes sent invariant: executor is never invoked on blocked egress.
6. External write tools (write_external) with empty data_flows fail closed immediately across all parameter keys.
7. Smuggled destination parameters across multiple argument keys.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict
import pytest

from carefold.engine.tool_exec import (
    EgressBlockedError,
    ToolContext,
    ToolSpec,
    execute_tool_call,
    verify_egress_firewall,
)
from carefold.engine.tool_registry import DataFlows


# ============================================================================
# 1. Cloud Metadata IP Anti-SSRF Protections (169.254.169.254)
# ============================================================================

class TestCloudMetadataAntiSSRF:
    """Verifies that cloud metadata IPs (169.254.169.254) are strictly blocked across all vectors."""

    @pytest.mark.parametrize(
        "metadata_target",
        [
            "http://169.254.169.254",
            "http://169.254.169.254/",
            "http://169.254.169.254/latest/meta-data/",
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
            "http://169.254.169.254/latest/user-data",
            "http://169.254.169.254:80/latest/meta-data/",
            "http://169.254.169.254:443/latest/meta-data/",
            "http://169.254.169.254:8080/computeMetadata/v1/",
            "https://169.254.169.254/latest/meta-data/",
            "169.254.169.254",
            "169.254.169.254:80",
            "http://admin:secret@169.254.169.254/latest/meta-data/",
            "http://169.254.169.254.nip.io/latest/meta-data/",
        ],
    )
    def test_verify_egress_firewall_blocks_metadata_ip(self, metadata_target: str):
        """verify_egress_firewall raises EgressBlockedError on any cloud metadata target."""
        spec = ToolSpec(
            name="cloud_connector",
            risk_tier="write_external",
            data_flows=("api.approved-service.com",),
            executor=lambda a: {"ok": True},
        )
        with pytest.raises(EgressBlockedError) as exc_info:
            verify_egress_firewall(spec, {"url": metadata_target})
        assert "Security violation: Network egress to host" in str(exc_info.value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "metadata_target",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://169.254.169.254:80/latest/user-data",
            "http://token:hunter2@169.254.169.254/",
        ],
    )
    async def test_execute_tool_call_blocks_metadata_ip_with_zero_bytes(self, metadata_target: str):
        """execute_tool_call catches EgressBlockedError and never invokes the executor."""
        called = False

        async def mock_executor(args, ctx=None):
            nonlocal called
            called = True
            return {"network_bytes_sent": 1024}

        spec = ToolSpec(
            name="metadata_prober",
            risk_tier="write_external",
            data_flows=("api.approved-service.com",),
            executor=mock_executor,
        )
        ctx = ToolContext(user_id="u1", profile_id="p1")

        result = await execute_tool_call(ctx, spec, {"url": metadata_target})

        assert result.success is False
        assert called is False, "Executor must NEVER be invoked on blocked egress (0 network bytes sent)"
        assert "EgressBlockedError" in (result.error or "")
        assert "169.254.169.254" in (result.error or "")


# ============================================================================
# 2. Subdomain Confusion & Suffix Spoofing Protections
# ============================================================================

class TestSubdomainConfusionProtections:
    """Verifies that subdomain confusion and domain spoofing attacks are strictly blocked."""

    @pytest.mark.parametrize(
        "spoofed_target",
        [
            "https://api.hospital.org.evil-attacker.com/leak",
            "https://api.hospital.org.attacker.io",
            "https://evil-api.hospital.org/leak",
            "https://notapi.hospital.org/leak",
            "https://hospital.org/leak",  # Parent domain not in allowed_hosts
            "https://sub.api.hospital.org/leak",  # Subdomain not in allowed_hosts
            "https://fake-api.hospital.org:8443/v1",
            "https://api.hospital.org.phishing.net",
        ],
    )
    def test_verify_egress_firewall_blocks_subdomain_confusion(self, spoofed_target: str):
        """verify_egress_firewall strictly blocks subdomain confusion and domain suffix spoofing."""
        spec = ToolSpec(
            name="ehr_sync",
            risk_tier="write_external",
            data_flows=("api.hospital.org",),
            executor=lambda a: {"ok": True},
        )
        with pytest.raises(EgressBlockedError) as exc_info:
            verify_egress_firewall(spec, {"url": spoofed_target})
        assert "Security violation: Network egress to host" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_subdomain_confusion_zero_bytes_sent(self):
        """Confirms executor is never invoked when subdomain confusion attack is detected."""
        executed = False

        async def mock_executor(args, ctx=None):
            nonlocal executed
            executed = True
            return {"leaked": True}

        spec = ToolSpec(
            name="ehr_sync",
            risk_tier="write_external",
            data_flows=("api.hospital.org",),
            executor=mock_executor,
        )
        ctx = ToolContext(user_id="u1", profile_id="p1")

        res = await execute_tool_call(
            ctx, spec, {"endpoint": "https://api.hospital.org.attacker.com/steal"}
        )
        assert res.success is False
        assert executed is False
        assert "EgressBlockedError" in (res.error or "")


# ============================================================================
# 3. Port Stripping & Case Normalization
# ============================================================================

class TestPortStrippingAndCaseNormalization:
    """Verifies that port stripping correctly extracts hostname and normalizes case."""

    @pytest.mark.parametrize(
        "target, expected_host",
        [
            ("https://api.hospital.org:443/v1/patient", "api.hospital.org"),
            ("https://api.hospital.org:8443/v1/patient", "api.hospital.org"),
            ("https://api.hospital.org:80/v1/patient", "api.hospital.org"),
            ("https://api.hospital.org:9000/v1/patient", "api.hospital.org"),
            ("api.hospital.org:8443", "api.hospital.org"),
            ("https://API.HOSPITAL.ORG:8443/v1/patient", "api.hospital.org"),
            ("https://Api.Hospital.Org/v1/patient", "api.hospital.org"),
            ("API.HOSPITAL.ORG", "api.hospital.org"),
        ],
    )
    def test_allowed_host_with_ports_and_cases_succeeds(self, target: str, expected_host: str):
        """Allowlisted host with various ports and cases passes egress firewall."""
        spec = ToolSpec(
            name="ehr_reader",
            risk_tier="read",
            data_flows=("api.hospital.org",),
            executor=lambda a: {"status": "ok"},
        )
        hosts = verify_egress_firewall(spec, {"url": target})
        assert hosts == [expected_host]

    @pytest.mark.parametrize(
        "unauthorized_target",
        [
            ("https://evil.attacker.com:8443/leak"),
            ("https://evil.attacker.com:443/leak"),
            ("https://evil.attacker.com:80/leak"),
            ("evil.attacker.com:9999"),
            ("https://EVIL.ATTACKER.COM:8080"),
        ],
    )
    def test_unauthorized_host_with_ports_is_blocked(self, unauthorized_target: str):
        """Unauthorized hosts with port numbers are blocked with port stripped from host in error."""
        spec = ToolSpec(
            name="ehr_reader",
            risk_tier="read",
            data_flows=("api.hospital.org",),
            executor=lambda a: {"status": "ok"},
        )
        with pytest.raises(EgressBlockedError) as exc_info:
            verify_egress_firewall(spec, {"url": unauthorized_target})
        assert "evil.attacker.com" in str(exc_info.value)
        assert ":8443" not in exc_info.value.host  # Port must be stripped from host attribute


# ============================================================================
# 4. Credential URL Injection Protections (@ symbol & userinfo)
# ============================================================================

class TestCredentialURLInjectionProtections:
    """Verifies that credential URL injections (@ symbol) cannot bypass egress allowlist."""

    @pytest.mark.parametrize(
        "credential_attack",
        [
            "https://api.hospital.org@evil-domain.com/leak",
            "https://api.hospital.org:secret@evil-domain.com/leak",
            "https://api.hospital.org:token@attacker.org:8443/data",
            "https://user:password@attacker.com/v1",
            "http://admin:admin@169.254.169.254/latest/meta-data/",
        ],
    )
    def test_credential_url_injection_to_unauthorized_host_blocked(self, credential_attack: str):
        """Attempts to use @ to trick url parsing into allowing evil hosts are blocked."""
        spec = ToolSpec(
            name="secure_client",
            risk_tier="write_external",
            data_flows=("api.hospital.org",),
            executor=lambda a: {"ok": True},
        )
        with pytest.raises(EgressBlockedError):
            verify_egress_firewall(spec, {"url": credential_attack})

    def test_credential_url_on_allowed_host_extracts_correct_hostname(self):
        """Valid basic-auth credentials targeting allowed host extract allowed host cleanly."""
        spec = ToolSpec(
            name="secure_client",
            risk_tier="write_external",
            data_flows=("api.hospital.org",),
            executor=lambda a: {"ok": True},
        )
        hosts = verify_egress_firewall(
            spec, {"url": "https://service_account:token123@api.hospital.org:8443/v1/sync"}
        )
        assert hosts == ["api.hospital.org"]


# ============================================================================
# 5. Empty DataFlows Fail-Closed Protections
# ============================================================================

class TestEmptyDataFlowsFailClosed:
    """Verifies that write_external tools with missing or empty data_flows fail closed immediately."""

    @pytest.mark.parametrize("empty_flows", [(), [], None, DataFlows(allowed_hosts=())])
    @pytest.mark.parametrize("key", ["url", "endpoint", "host", "target_url", "base_url"])
    def test_write_external_with_empty_data_flows_fails_closed(self, empty_flows: Any, key: str):
        """write_external tool with empty data_flows raises EgressBlockedError across all target keys."""
        spec = ToolSpec(
            name="unconfigured_sender",
            risk_tier="write_external",
            data_flows=empty_flows,
            executor=lambda a: {"ok": True},
        )
        with pytest.raises(EgressBlockedError) as exc_info:
            verify_egress_firewall(spec, {key: "https://api.external-service.com/push"})
        assert "has no authorized data_flows configured" in str(exc_info.value)
        assert exc_info.value.host == "api.external-service.com"
        assert exc_info.value.tool == "unconfigured_sender"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", ["url", "endpoint", "host", "target_url", "base_url"])
    async def test_execute_tool_call_fails_closed_empty_data_flows_zero_bytes(self, key: str):
        """execute_tool_call returns error and never invokes executor when data_flows is empty."""
        invoked = False

        async def mock_sender(args, ctx=None):
            nonlocal invoked
            invoked = True
            return {"sent": True}

        spec = ToolSpec(
            name="unconfigured_sender",
            risk_tier="write_external",
            data_flows=(),
            executor=mock_sender,
        )
        ctx = ToolContext(user_id="u1", profile_id="p1")

        result = await execute_tool_call(ctx, spec, {key: "https://api.stripe.com/v1/charges"})
        assert result.success is False
        assert invoked is False, "Executor must NOT be called for unconfigured write_external tool"
        assert "EgressBlockedError" in (result.error or "")
        assert "no authorized data_flows configured" in (result.error or "")


# ============================================================================
# 6. Smuggled Parameter Injections & Multiple Keys
# ============================================================================

class TestParameterSmugglingAdversarial:
    """Verifies that malicious parameters smuggled alongside legitimate ones are intercepted."""

    @pytest.mark.asyncio
    async def test_smuggled_malicious_parameter_intercepted_and_blocked(self):
        """When legitimate URL is in 'url' but malicious URL is smuggled in 'endpoint', egress fails."""
        called = False

        async def mock_executor(args, ctx=None):
            nonlocal called
            called = True
            return {"ok": True}

        spec = ToolSpec(
            name="sync_tool",
            risk_tier="write_external",
            data_flows=("api.hospital.org",),
            executor=mock_executor,
        )
        ctx = ToolContext(user_id="u1", profile_id="p1")

        smuggled_args = {
            "url": "https://api.hospital.org/v1/data",
            "endpoint": "https://169.254.169.254/latest/meta-data/",
        }

        result = await execute_tool_call(ctx, spec, smuggled_args)
        assert result.success is False
        assert called is False
        assert "EgressBlockedError" in (result.error or "")
        assert "169.254.169.254" in (result.error or "")

    @pytest.mark.asyncio
    async def test_all_five_destination_keys_are_scanned(self):
        """All five keys (url, endpoint, host, target_url, base_url) are verified by the firewall."""
        spec = ToolSpec(
            name="multi_key_tool",
            risk_tier="write_external",
            data_flows=("api.hospital.org",),
            executor=lambda a: {"ok": True},
        )
        ctx = ToolContext(user_id="u1", profile_id="p1")

        for key in ("url", "endpoint", "host", "target_url", "base_url"):
            res = await execute_tool_call(ctx, spec, {key: "http://169.254.169.254"})
            assert res.success is False
            assert "169.254.169.254" in (res.error or "")
