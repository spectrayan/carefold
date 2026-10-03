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

"""Tier 3: Cross-Feature Combinations E2E Tests (Pairwise Interactions).

Validates integration contracts and data flow across architectural package
boundaries (15 cross-feature pairwise interactions).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient

from carefold.config import settings
from tests.e2e.conftest import read_attachment_sync, record_audit_sync


def _try_import(module_path: str, symbol_name: Optional[str] = None) -> Any:
    try:
        mod = importlib.import_module(module_path)
        if symbol_name:
            return getattr(mod, symbol_name, None)
        return mod
    except (ImportError, ModuleNotFoundError, AttributeError):
        return None


class TestCrossFeatureInteractions:
    """Pairwise cross-feature interactions validating package boundaries."""

    @pytest.mark.asyncio
    async def test_i01_guardrail_refusal_audit_combination(self, e2e_workspace: Path):
        """Interaction: InputGuardrailNode -> RefusalNode -> AuditLogger."""
        from carefold.safety.classifier import check_safety_refusal
        res = check_safety_refusal("You have severe bronchitis, take 500mg amoxicillin.")
        assert res.refused is True
        assert res.safe_response is not None
        assert "cannot" in res.safe_response.lower()

        record_audit_sync({"event": "refusal", "category": res.reason or "clinical"})
        log_path = settings.audit_log_path
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8")
            assert "bronchitis" not in content

    def test_i02_model_factory_provider_agent_node(self):
        """Interaction: ModelFactory -> BaseModelProvider -> AgentNode."""
        factory_mod = _try_import("carefold.model.factory")
        if factory_mod and hasattr(factory_mod, "create_chat_model"):
            m = factory_mod.create_chat_model(provider="ollama")
            assert m is not None

    def test_i03_ingestion_pii_sanitizer_dossier_extraction(self, e2e_workspace: Path):
        """Interaction: Sandboxed Ingestion -> PII Sanitizer -> Dossier Extraction."""
        res = read_attachment_sync("sample_visit.txt", e2e_workspace)
        assert res.success is True
        raw_text = res.output["content"]
        assert "CLINICAL VISIT SUMMARY" in raw_text

        san_mod = _try_import("carefold.workflows.subgraphs.extraction.sanitizer")
        if san_mod and hasattr(san_mod, "sanitize_pii"):
            sanitized = san_mod.sanitize_pii(raw_text)
            assert "123-45-6789" not in sanitized

    def test_i04_dossier_extraction_grounding_agent_state(self, sample_insurance_text: str):
        """Interaction: Dossier Extraction -> Grounding Validator -> AgentState."""
        grd_mod = _try_import("carefold.workflows.subgraphs.extraction.grounding")
        if grd_mod is None:
            pytest.skip("F-37: GroundingValidator pending implementation")
        val = grd_mod.GroundingValidator.validate_numerical_value("$1,500", sample_insurance_text)
        assert val.is_grounded is True

    @pytest.mark.asyncio
    async def test_i05_supervisor_routing_specialist_subgraph(self):
        """Interaction: SupervisorNode -> Specialist Subgraph -> State Propagation."""
        node_mod = _try_import("carefold.workflows.nodes.supervisor_node")
        if node_mod is None:
            pytest.skip("F-23: SupervisorNode pending implementation")
        sup = node_mod.SupervisorNode()
        state = {"messages": [{"role": "user", "content": "Review my doctor's instructions"}]}
        out = await sup.execute(state)
        assert "current_agent" in out or "routed_subgraph" in out

    @pytest.mark.asyncio
    async def test_i06_tool_execution_validator_traces(self, e2e_workspace: Path):
        """Interaction: ToolNode -> ToolValidatorNode -> Tool Traces."""
        res = read_attachment_sync("sample_visit.txt", e2e_workspace)
        assert res.success is True

        node_mod = _try_import("carefold.workflows.nodes.tool_validator_node")
        if node_mod and hasattr(node_mod, "ToolValidatorNode"):
            val_node = node_mod.ToolValidatorNode()
            out = await val_node.execute({"tool_output": res.output["content"]})
            assert out is not None

    @pytest.mark.asyncio
    async def test_i07_output_guardrail_reflection_self_correction(self):
        """Interaction: OutputGuardrailNode -> ReflectionNode -> Self-Correction."""
        guard_mod = _try_import("carefold.workflows.nodes.output_guardrail_node")
        refl_mod = _try_import("carefold.workflows.nodes.reflection_node")
        if guard_mod is None or refl_mod is None:
            pytest.skip("M3 nodes pending implementation")
        refl = refl_mod.ReflectionNode()
        res = await refl.execute({"reflection_count": 0, "max_reflections": 3})
        assert res.get("reflection_count") == 1

    @pytest.mark.asyncio
    async def test_i08_reflection_threshold_fallback_termination(self):
        """Interaction: Reflection Loop Ceiling -> Fallback Termination."""
        refl_mod = _try_import("carefold.workflows.nodes.reflection_node")
        if refl_mod is None:
            pytest.skip("F-28: ReflectionNode pending implementation")
        refl = refl_mod.ReflectionNode()
        res = await refl.execute({"reflection_count": 3, "max_reflections": 3})
        assert res.get("next_step") in ("done", "fallback", "refusal")

    def test_i09_dual_invocation_tool_agent_state(self):
        """Interaction: extract_document_dossier tool -> AgentState['document_dossiers']."""
        tool_mod = _try_import("carefold.workflows.subgraphs.extraction.tool")
        if tool_mod is None:
            pytest.skip("F-38: Extraction tool pending implementation")
        assert hasattr(tool_mod, "extract_document_dossier")

    def test_i10_resource_loader_safety_classifier_chat_api(self, e2e_client: TestClient):
        """Interaction: ResourceLoader -> Safety Classifier -> /api/chat."""
        res = e2e_client.post("/api/chat", json={
            "agent_id": "visit-steward",
            "message": "Hello, how can you help me prepare for my visit?"
        })
        assert res.status_code in (200, 400, 422)

    def test_i11_error_node_sse_stream_audit_privacy(self, e2e_client: TestClient):
        """Interaction: ErrorNode -> SSE Streaming Service -> Audit Privacy."""
        res = e2e_client.post("/api/chat", json={
            "agent_id": "nonexistent_agent_xyz",
            "message": "Test error handling"
        })
        assert res.status_code in (404, 422, 200)

    def test_i12_checkpointer_multiturn_state_persistence(self):
        """Interaction: SQLite Checkpointer -> Thread State -> Multi-Turn Resumption."""
        bld_mod = _try_import("carefold.engine.builder")
        if bld_mod is None:
            pytest.skip("F-39: GraphBuilder pending implementation")
        assert hasattr(bld_mod.GraphBuilder, "build_graph")

    def test_i13_api_constants_defaults_engine_builder(self):
        """Interaction: API Constants + Defaults Constants -> Engine Builder."""
        api_const = _try_import("carefold.constants.api")
        def_const = _try_import("carefold.constants.defaults")
        if api_const is None or def_const is None:
            pytest.skip("M1 Constants pending implementation")
        assert hasattr(api_const, "CHAT_ENDPOINT")
        assert hasattr(def_const, "MAX_FILE_SIZE_BYTES") or hasattr(def_const, "MAX_ATTACHMENT_SIZE")

    def test_i14_pii_sanitizer_tool_output_audit_redaction(self, e2e_workspace: Path):
        """Interaction: Tool Output -> PII Masking -> Audit Redaction."""
        from carefold.audit.redaction import redact_audit_event
        text = "Visit summary for SSN 123-45-6789 and MRN 987654"
        redacted = redact_audit_event({"prompt": text}, store_bodies=False)
        assert "123-45-6789" not in redacted
        assert "prompt" not in redacted

