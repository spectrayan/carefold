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

"""Adversarial stress testing suite for Connector Protocol, Manifest Validation,
and Universal Tool Execution Choke Point (AU-50 / AU-51 / AU-52 / R7).

Written by Challenger 1 (m6_18_chal1).
Covers:
1. Custom and malformed connector classes failing runtime protocol checks.
2. Manifest validation under invalid YAML/dict inputs, missing required fields,
   illegal schemes/ports in DataFlowSpec, and invalid token_rotation in AuthConfig.
3. Fail-closed ToolContext validation, tool result wrapping, metadata extraction,
   and 50-call concurrent dispatch with zero cross-call state leakage or taint contamination.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import random
from typing import Any, Dict, List, Optional
import uuid

import pytest
from pydantic import ValidationError

from carefold.engine.tool_exec import (
    TaintFlag,
    ToolContext as EngineToolContext,
    ToolSpec as EngineToolSpec,
    execute_tool_call,
)
from carefold.schemas.tool import ToolResult
from connectors.base import (
    Connector,
    NormalisedRecord,
    Page,
    StreamSpec,
    ToolContext as ConnectorToolContext,
    ToolSpec as ConnectorToolSpec,
)
from connectors.errors import (
    ConnectorError,
    EgressBlockedError,
    ManifestValidationError,
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


# ==============================================================================
# 1. Custom and Malformed Connector Classes (Protocol Checks)
# ==============================================================================

class FullyConformingConnector:
    """Structurally conforms to Connector protocol without explicit inheritance."""

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="conforming-test",
            version="1.0.0",
            name="Conforming Test",
            description="Fully conforming connector",
            data_flows=DataFlowSpec(allowed_hosts=["api.example.com"]),
            auth=AuthConfig(type="api_key"),
            trust=TrustConfig(publisher="Tester"),
        )

    def streams(self) -> List[StreamSpec]:
        return [StreamSpec(name="records")]

    async def fetch(
        self,
        ctx: ConnectorToolContext,
        stream: str,
        cursor: Optional[str],
        http: ScopedHttp,
    ) -> Page:
        return Page(stream=stream, records=[])

    def map(self, page: Page) -> List[NormalisedRecord]:
        return []

    def tools(self) -> List[ConnectorToolSpec]:
        return []


class EmptyConnector:
    """Empty class lacking all protocol members."""
    pass


class MissingManifestConnector:
    """Missing manifest property."""

    def streams(self) -> List[StreamSpec]:
        return []

    async def fetch(
        self,
        ctx: ConnectorToolContext,
        stream: str,
        cursor: Optional[str],
        http: ScopedHttp,
    ) -> Page:
        return Page(stream=stream, records=[])

    def map(self, page: Page) -> List[NormalisedRecord]:
        return []

    def tools(self) -> List[ConnectorToolSpec]:
        return []


class MissingStreamsConnector:
    """Missing streams() method."""

    @property
    def manifest(self) -> Any:
        return None

    async def fetch(
        self,
        ctx: ConnectorToolContext,
        stream: str,
        cursor: Optional[str],
        http: ScopedHttp,
    ) -> Page:
        return Page(stream=stream, records=[])

    def map(self, page: Page) -> List[NormalisedRecord]:
        return []

    def tools(self) -> List[ConnectorToolSpec]:
        return []


class MissingFetchConnector:
    """Missing async fetch() method."""

    @property
    def manifest(self) -> Any:
        return None

    def streams(self) -> List[StreamSpec]:
        return []

    def map(self, page: Page) -> List[NormalisedRecord]:
        return []

    def tools(self) -> List[ConnectorToolSpec]:
        return []


class MissingMapConnector:
    """Missing map() method."""

    @property
    def manifest(self) -> Any:
        return None

    def streams(self) -> List[StreamSpec]:
        return []

    async def fetch(
        self,
        ctx: ConnectorToolContext,
        stream: str,
        cursor: Optional[str],
        http: ScopedHttp,
    ) -> Page:
        return Page(stream=stream, records=[])

    def tools(self) -> List[ConnectorToolSpec]:
        return []


class MissingToolsConnector:
    """Missing tools() method."""

    @property
    def manifest(self) -> Any:
        return None

    def streams(self) -> List[StreamSpec]:
        return []

    async def fetch(
        self,
        ctx: ConnectorToolContext,
        stream: str,
        cursor: Optional[str],
        http: ScopedHttp,
    ) -> Page:
        return Page(stream=stream, records=[])

    def map(self, page: Page) -> List[NormalisedRecord]:
        return []


class NonCallableMethodsConnector:
    """Has attributes with expected names, but they are non-callable scalars."""

    manifest: str = "not-a-property"
    streams: str = "not-callable"
    fetch: int = 42
    map: bool = False
    tools: list = []  # List instance is not a callable


def test_conforming_connector_structural_typing():
    """Verify that a fully conforming class passes runtime Protocol verification."""
    connector = FullyConformingConnector()
    assert isinstance(connector, Connector)


@pytest.mark.parametrize(
    "malformed_cls",
    [
        EmptyConnector,
        MissingManifestConnector,
        MissingStreamsConnector,
        MissingFetchConnector,
        MissingMapConnector,
        MissingToolsConnector,
    ],
)
def test_malformed_connectors_missing_methods_fail_protocol_check(malformed_cls):
    """Verify that any class missing protocol methods/properties fails runtime isinstance check."""
    instance = malformed_cls()
    assert not isinstance(instance, Connector), (
        f"Malformed class {malformed_cls.__name__} unexpectedly satisfied Connector Protocol"
    )


def test_malformed_connector_non_callable_fails_runtime_invocation():
    """Verify that while PEP 544 runtime_checkable performs attribute existence checks,
    malformed non-callable attributes immediately fail runtime invocation."""
    instance = NonCallableMethodsConnector()
    # At runtime, invoking non-callable attributes fails runtime checks
    with pytest.raises(TypeError):
        instance.streams()

    with pytest.raises(TypeError):
        instance.tools()


# ==============================================================================
# 2. Manifest Validation & Schema Integrity
# ==============================================================================

@pytest.fixture
def minimal_valid_manifest_dict() -> Dict[str, Any]:
    return {
        "id": "valid-connector",
        "version": "1.0.0",
        "name": "Valid Connector",
        "description": "Minimal valid manifest",
        "data_flows": {
            "allowed_hosts": ["api.health.org"],
            "allowed_schemes": ["https"],
            "allowed_ports": [443],
        },
        "auth": {
            "type": "oauth2",
            "token_rotation": True,
        },
        "trust": {
            "publisher": "Valid Health Org",
        },
    }


def test_manifest_validation_unparseable_yaml():
    """Malformed or syntactically invalid YAML must raise ManifestValidationError."""
    corrupted_yaml = """
    id: broken-yaml
    name: [unclosed sequence
    description: bad
    """
    with pytest.raises(ManifestValidationError, match="YAML parsing error|Invalid"):
        ConnectorManifest.from_yaml(corrupted_yaml)


@pytest.mark.parametrize(
    "invalid_yaml_content",
    [
        "just a plain scalar string",
        "- list item 1\n- list item 2",
        "12345",
        "",
        "   \n\t  \n",
    ],
)
def test_manifest_validation_non_dict_yaml(invalid_yaml_content):
    """YAML that deserializes to anything other than a dictionary must raise ManifestValidationError."""
    with pytest.raises(ManifestValidationError):
        ConnectorManifest.from_yaml(invalid_yaml_content)


@pytest.mark.parametrize("invalid_dict_input", ["not a dict", [1, 2, 3], None, 999])
def test_manifest_validation_non_dict_from_dict(invalid_dict_input):
    """from_dict with non-dict input must raise ManifestValidationError."""
    with pytest.raises((ManifestValidationError, ValidationError)):
        ConnectorManifest.from_dict(invalid_dict_input)


@pytest.mark.parametrize(
    "missing_field",
    [
        "id",
        "version",
        "name",
        "description",
        "data_flows",
        "auth",
        "trust",
    ],
)
def test_manifest_validation_missing_required_root_fields(
    minimal_valid_manifest_dict, missing_field
):
    """Omitting any mandatory root-level manifest field must raise ManifestValidationError."""
    payload = dict(minimal_valid_manifest_dict)
    del payload[missing_field]
    with pytest.raises((ManifestValidationError, ValidationError)):
        ConnectorManifest.from_dict(payload)


@pytest.mark.parametrize(
    "illegal_scheme",
    [
        ["ftp"],
        ["file"],
        ["gopher"],
        ["javascript"],
        ["ws"],
        ["https", "ftp"],
    ],
)
def test_manifest_validation_illegal_data_flow_schemes(
    minimal_valid_manifest_dict, illegal_scheme
):
    """DataFlowSpec must reject prohibited URL schemes."""
    payload = dict(minimal_valid_manifest_dict)
    payload["data_flows"]["allowed_schemes"] = illegal_scheme
    with pytest.raises((ManifestValidationError, ValidationError)):
        ConnectorManifest.from_dict(payload)


@pytest.mark.parametrize(
    "illegal_ports",
    [
        ["not_a_port"],
        [None],
        ["https"],
        {"port": 443},
    ],
)
def test_manifest_validation_illegal_data_flow_ports(
    minimal_valid_manifest_dict, illegal_ports
):
    """DataFlowSpec must reject non-integer port values."""
    payload = dict(minimal_valid_manifest_dict)
    payload["data_flows"]["allowed_ports"] = illegal_ports
    with pytest.raises((ManifestValidationError, ValidationError)):
        ConnectorManifest.from_dict(payload)


@pytest.mark.parametrize(
    "invalid_token_rotation",
    [
        {"rotate": True},
        [True, False],
        None,
    ],
)
def test_manifest_validation_invalid_token_rotation(
    minimal_valid_manifest_dict, invalid_token_rotation
):
    """AuthConfig must validate token_rotation boolean types."""
    payload = dict(minimal_valid_manifest_dict)
    payload["auth"]["token_rotation"] = invalid_token_rotation
    with pytest.raises((ManifestValidationError, ValidationError)):
        ConnectorManifest.from_dict(payload)


@pytest.mark.parametrize(
    "invalid_auth_type",
    [
        "bearer_token",
        "magic_link",
        "saml2",
        "anonymous",
        "custom_scheme",
    ],
)
def test_manifest_validation_invalid_auth_type(
    minimal_valid_manifest_dict, invalid_auth_type
):
    """AuthConfig must reject unsupported authentication mechanism types."""
    payload = dict(minimal_valid_manifest_dict)
    payload["auth"]["type"] = invalid_auth_type
    with pytest.raises((ManifestValidationError, ValidationError)):
        ConnectorManifest.from_dict(payload)


def test_manifest_validation_full_yaml_round_trip():
    """Verify that a comprehensive manifest YAML parses and retains defaults."""
    full_yaml = """
    id: fhir-epic-sandbox
    version: 2.1.0
    name: Epic Sandbox Connector
    description: FHIR R4 clinical records connector
    data_flows:
      allowed_hosts:
        - fhir.epic.com
        - oauth.epic.com
      allowed_schemes:
        - https
      allowed_ports:
        - 443
        - 8443
      egress_direction: egress_only
      pii_types_transferred:
        - name
        - mrn
        - dob
    auth:
      type: oauth2
      authorization_url: https://oauth.epic.com/authorize
      token_url: https://oauth.epic.com/token
      scopes:
        - patient/*.read
      token_rotation: true
    tools:
      - name: get_vitals
        description: Read patient vital observations
        risk_class: read_only
    trust:
      publisher: Epic Systems Integration
      verified: true
      sandbox_level: strict
    policy:
      rate_limit_rpm: 120
      timeout_seconds: 45.0
    terms:
      license: Apache-2.0
      privacy_policy_url: https://epic.com/privacy
    """
    manifest = ConnectorManifest.from_yaml(full_yaml)
    assert manifest.id == "fhir-epic-sandbox"
    assert manifest.version == "2.1.0"
    assert len(manifest.data_flows.allowed_hosts) == 2
    assert 8443 in manifest.data_flows.allowed_ports
    assert manifest.auth.token_rotation is True
    assert len(manifest.tools) == 1
    assert manifest.tools[0].name == "get_vitals"
    assert manifest.policy.rate_limit_rpm == 120
    assert manifest.policy.timeout_seconds == 45.0
    assert manifest.terms.privacy_policy_url == "https://epic.com/privacy"


# ==============================================================================
# 3. Tool Execution via execute_tool_call Choke Point
# ==============================================================================

@pytest.mark.parametrize("empty_val", ["", "   ", "\t\n", None])
def test_tool_context_fail_closed_on_empty_profile_or_user(empty_val):
    """Direct ToolContext construction must raise ValueError when profile_id or user_id is empty."""
    with pytest.raises((ValueError, TypeError)):
        EngineToolContext(user_id="user-123", profile_id=empty_val)  # type: ignore

    with pytest.raises((ValueError, TypeError)):
        EngineToolContext(user_id=empty_val, profile_id="profile-123")  # type: ignore


@pytest.mark.asyncio
async def test_execute_tool_call_fail_closed_on_invalid_context():
    """execute_tool_call must deny execution if ToolContext is malformed or not an instance."""
    spec = EngineToolSpec(
        name="test_tool",
        executor=lambda args: {"status": "ok"},
    )

    # 1. Non-ToolContext input
    res_none = await execute_tool_call(ctx=None, spec=spec, args={})  # type: ignore
    assert res_none.success is False
    assert "ToolContext instance is required" in res_none.error

    # 2. Arbitrary object input
    res_obj = await execute_tool_call(ctx=object(), spec=spec, args={})  # type: ignore
    assert res_obj.success is False
    assert "ToolContext instance is required" in res_obj.error

    # 3. Context with profile_id bypassed/cleared via object.__setattr__
    ctx = EngineToolContext(user_id="user-1", profile_id="profile-1")
    object.__setattr__(ctx, "profile_id", "")
    res_profile_empty = await execute_tool_call(ctx=ctx, spec=spec, args={})
    assert res_profile_empty.success is False
    assert "profile_id is missing or empty (fail-closed)" in res_profile_empty.error

    # 4. Context with user_id bypassed/cleared via object.__setattr__
    ctx2 = EngineToolContext(user_id="user-1", profile_id="profile-1")
    object.__setattr__(ctx2, "user_id", "")
    res_user_empty = await execute_tool_call(ctx=ctx2, spec=spec, args={})
    assert res_user_empty.success is False
    assert "user_id is missing or empty (fail-closed)" in res_user_empty.error


@pytest.mark.asyncio
async def test_execute_tool_call_fail_closed_on_invalid_spec():
    """execute_tool_call must deny execution if ToolSpec is invalid or executor is not callable."""
    ctx = EngineToolContext(user_id="user-1", profile_id="profile-1")

    # Non-ToolSpec instance
    res_no_spec = await execute_tool_call(ctx=ctx, spec=None, args={})  # type: ignore
    assert res_no_spec.success is False
    assert "ToolSpec instance is required" in res_no_spec.error

    # ToolSpec with non-callable executor
    spec_bad_executor = EngineToolSpec(name="bad_tool", executor="not_callable")  # type: ignore
    res_bad_exec = await execute_tool_call(ctx=ctx, spec=spec_bad_executor, args={})
    assert res_bad_exec.success is False
    assert "no valid executor" in res_bad_exec.error


@pytest.mark.asyncio
async def test_tool_result_wrapping_and_metadata_extraction():
    """Choke point must correctly wrap dicts, ToolResults, primitives, and catch exceptions."""
    ctx = EngineToolContext(user_id="user-1", profile_id="profile-1")

    # 1. Plain dictionary output
    spec_dict = EngineToolSpec(
        name="dict_tool",
        executor=lambda args: {"data": [1, 2, 3]},
    )
    res_dict = await execute_tool_call(ctx=ctx, spec=spec_dict, args={})
    assert isinstance(res_dict, ToolResult)
    assert res_dict.success is True
    assert res_dict.output == {"data": [1, 2, 3]}
    assert res_dict.error is None

    # 2. Dictionary containing explicit success=False
    spec_fail_dict = EngineToolSpec(
        name="fail_dict_tool",
        executor=lambda args: {"success": False, "error": "Operation rejected", "output": None},
    )
    res_fail_dict = await execute_tool_call(ctx=ctx, spec=spec_fail_dict, args={})
    assert isinstance(res_fail_dict, ToolResult)
    assert res_fail_dict.success is False
    assert res_fail_dict.error == "Operation rejected"

    # 3. Direct ToolResult return
    native_result = ToolResult(success=True, output="pre-wrapped", error=None)
    spec_native = EngineToolSpec(
        name="native_tool",
        executor=lambda args: native_result,
    )
    res_native = await execute_tool_call(ctx=ctx, spec=spec_native, args={})
    assert res_native is native_result

    # 4. Scalar primitive output
    spec_scalar = EngineToolSpec(
        name="scalar_tool",
        executor=lambda args: 42,
    )
    res_scalar = await execute_tool_call(ctx=ctx, spec=spec_scalar, args={})
    assert res_scalar.success is True
    assert res_scalar.output == 42

    # 5. Exception containment
    def crashing_executor(args):
        raise RuntimeError("Fatal downstream API crash")

    spec_crash = EngineToolSpec(name="crash_tool", executor=crashing_executor)
    res_crash = await execute_tool_call(ctx=ctx, spec=spec_crash, args={})
    assert res_crash.success is False
    assert "Tool 'crash_tool' execution failed: Fatal downstream API crash" in res_crash.error


@pytest.mark.asyncio
async def test_tool_signatures_and_context_delivery():
    """Verify that execute_tool_call delivers args and ctx across varied callable signatures."""
    ctx = EngineToolContext(user_id="user-alpha", profile_id="profile-omega")

    # Signature A: async def (args, ctx)
    async def async_args_ctx(args: dict, c: Any):
        return {"u": c.user_id, "p": c.profile_id, "a": args.get("k")}

    # Signature B: async def (ctx, args)
    async def async_ctx_args(c: Any, args: dict):
        return {"u": c.user_id, "p": c.profile_id, "a": args.get("k")}

    # Signature C: sync def (args)
    def sync_args_only(args: dict):
        return {"a": args.get("k")}

    for name, fn in [
        ("sig_a", async_args_ctx),
        ("sig_b", async_ctx_args),
        ("sig_c", sync_args_only),
    ]:
        spec = EngineToolSpec(name=name, executor=fn)
        res = await execute_tool_call(ctx=ctx, spec=spec, args={"k": "value-xyz"})
        assert res.success is True
        assert res.output["a"] == "value-xyz"
        if "u" in res.output:
            assert res.output["u"] == "user-alpha"
            assert res.output["p"] == "profile-omega"


@pytest.mark.asyncio
async def test_choke_point_network_egress_blocking():
    """Choke point must proactively block unauthorized external hosts before executing."""
    ctx = EngineToolContext(user_id="user-1", profile_id="profile-1")

    called = False

    def monitored_executor(args):
        nonlocal called
        called = True
        return {"ok": True}

    spec = EngineToolSpec(
        name="egress_tool",
        executor=monitored_executor,
        data_flows=("api.allowed-ehr.com",),
    )

    # 1. Unauthorized egress target
    res_blocked = await execute_tool_call(
        ctx=ctx,
        spec=spec,
        args={"url": "https://data-exfiltration.net/upload"},
    )
    assert res_blocked.success is False
    assert "denied by tool 'egress_tool' data_flows policy" in res_blocked.error
    assert called is False, "Executor was invoked despite egress policy violation!"

    # 2. Authorized egress target
    res_allowed = await execute_tool_call(
        ctx=ctx,
        spec=spec,
        args={"url": "https://api.allowed-ehr.com/patients"},
    )
    assert res_allowed.success is True
    assert called is True


# ==============================================================================
# 4. High-Volume Concurrent Dispatching (50 Parallel Calls)
# ==============================================================================

@pytest.mark.asyncio
async def test_high_volume_concurrent_dispatching_zero_state_leakage():
    """Simulate 50 parallel tool calls through execute_tool_call verifying:
    1. Zero race conditions or crosstalk across calls.
    2. Exact return correlation between input args, ToolContext, and output.
    3. Untrusted taint isolation: untrusted tool calls do not contaminate parallel trusted calls.
    """
    total_calls = 50

    async def concurrent_worker(args: dict, ctx: EngineToolContext) -> dict:
        # Realistic randomized async I/O interleaving
        await asyncio.sleep(random.uniform(0.005, 0.020))
        return {
            "echo_call_id": args["call_id"],
            "echo_user_id": ctx.user_id,
            "echo_profile_id": ctx.profile_id,
            "echo_secret": args["secret_token"],
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

    trusted_spec = EngineToolSpec(
        name="parallel_trusted_tool",
        risk_tier="read",
        trust="trusted",
        executor=concurrent_worker,
    )

    untrusted_spec = EngineToolSpec(
        name="parallel_untrusted_tool",
        risk_tier="read",
        trust="untrusted",
        executor=concurrent_worker,
    )

    async def single_dispatch(call_index: int):
        uid = f"user_{call_index}_{uuid.uuid4().hex[:6]}"
        pid = f"profile_{call_index}_{uuid.uuid4().hex[:6]}"
        secret = f"secret_token_{call_index}_{uuid.uuid4()}"
        is_untrusted = (call_index % 2 == 0)

        taint_flag = TaintFlag(initial=False)
        ctx = EngineToolContext(
            user_id=uid,
            profile_id=pid,
            run_id=f"run-{call_index}",
            taint=taint_flag,
        )
        spec = untrusted_spec if is_untrusted else trusted_spec

        result = await execute_tool_call(
            ctx=ctx,
            spec=spec,
            args={"call_id": call_index, "secret_token": secret},
        )

        return {
            "index": call_index,
            "uid": uid,
            "pid": pid,
            "secret": secret,
            "is_untrusted": is_untrusted,
            "taint_state": taint_flag.is_tainted,
            "result": result,
        }

    # Dispatch 50 calls simultaneously
    tasks = [single_dispatch(i) for i in range(total_calls)]
    dispatched_results = await asyncio.gather(*tasks)

    assert len(dispatched_results) == total_calls

    seen_outputs = set()

    for item in dispatched_results:
        idx = item["index"]
        expected_uid = item["uid"]
        expected_pid = item["pid"]
        expected_secret = item["secret"]
        is_untrusted = item["is_untrusted"]
        taint_state = item["taint_state"]
        result: ToolResult = item["result"]

        # 1. Success check
        assert result.success is True, f"Call {idx} failed: {result.error}"
        out = result.output
        assert isinstance(out, dict)

        # 2. Exact correlation check (zero state leakage)
        assert out["echo_call_id"] == idx, f"Call ID mismatch in call {idx}: got {out['echo_call_id']}"
        assert out["echo_user_id"] == expected_uid, f"User ID crosstalk in call {idx}: got {out['echo_user_id']}"
        assert out["echo_profile_id"] == expected_pid, f"Profile ID crosstalk in call {idx}: got {out['echo_profile_id']}"
        assert out["echo_secret"] == expected_secret, f"Secret leakage in call {idx}: got {out['echo_secret']}"

        # 3. Taint isolation check
        if is_untrusted:
            assert taint_state is True, f"Untrusted call {idx} failed to mark taint"
        else:
            assert taint_state is False, (
                f"Trusted call {idx} was contaminated by parallel untrusted executions!"
            )

        # 4. Distinctness guarantee
        output_signature = (out["echo_call_id"], out["echo_user_id"], out["echo_secret"])
        assert output_signature not in seen_outputs, f"Duplicate output signature detected for call {idx}"
        seen_outputs.add(output_signature)

    assert len(seen_outputs) == total_calls
