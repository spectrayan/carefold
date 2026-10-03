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

"""System Agents Discovery and Registry Isolation Test Suite.

Tests and documents:
1. Directory Traversal & System Agent Discovery:
   - load_all_agents() discovers internal agents in _system/ and marks them hidden=True.
   - load_all_agents() discovers user-facing agents in root agents/ and marks them hidden=False.
   - load_all_agents() strictly skips _template/ and never surfaces it.
2. AgentRegistry Traversal & On-Demand Resolution:
   - AgentRegistry.reload() discovers internal agents from _system/ and tags them hidden=True.
   - AgentRegistry.reload() excludes _template/.
   - AgentRegistry.get("orchestrator") resolves the AgentManifest with hidden=True.
   - AgentRegistry.get("_template") strictly returns None.
   - AgentRegistry.get("_system") and dot/underscore queries strictly return None.
3. Adversarial Traversal Stress Testing:
   - Synthetic workspaces with dot prefixes (.git, .hidden_dir) and underscore prefixes
     (_backup, __pycache__, _draft, _template) at root and within _system/.
   - Plain files placed directly in agents/ and agents/_system/.
   - Late-added system agents verified via dynamic on-demand resolution.
4. Delegation Tools Fallback & Registry Consistency:
   - ListAgentsTool catalog formatting excludes orchestrator and _template, while exposing
     delegatable specialists (including document-extractor).
5. API Layer Security & Isolation:
   - GET /api/agents excludes system agents and _template by default.
   - GET /api/agents?include_hidden=true includes system agents with hidden=True, never _template.
   - GET /api/agents/<agent_id> rejects _template, _system, and dot-prefixed queries with 404.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Set
import pytest
from fastapi.testclient import TestClient

from carefold.agents.registry import AgentRegistry
from carefold.constants.agents import AGENT_ORCHESTRATOR
from carefold.constants.paths import AGENT_MANIFEST_FILENAME, SYSTEM_AGENTS_DIR, TEMPLATE_DIR
from carefold.loaders.agent_loader import load_all_agents
from carefold.tools.delegation_tools import ListAgentsTool


EXPECTED_SYSTEM_AGENTS: Set[str] = {
    "orchestrator",
    "document-extractor",
    "skill-generator",
    "suggestion-generator",
}

EXPECTED_PUBLIC_AGENTS: Set[str] = {
    "benefits-guide",
    "habit-companion",
    "visit-steward",
}


# ============================================================================
# 1. Base Loader Tests: _system Discovery and _template Exclusion
# ============================================================================


def test_load_all_agents_discovers_system_agents_as_hidden(temp_workspace: Path):
    """Verify load_all_agents discovers agents in _system/ and marks them hidden=True."""
    agents_dir = temp_workspace / "agents"
    skills_dir = temp_workspace / "skills"

    summaries = load_all_agents(agents_dir, skills_dir)
    summary_map = {s.id: s for s in summaries}

    # Verify all expected system agents exist and are marked hidden
    for sys_id in EXPECTED_SYSTEM_AGENTS:
        assert sys_id in summary_map, f"System agent '{sys_id}' missing from load_all_agents()"
        assert summary_map[sys_id].hidden is True, f"System agent '{sys_id}' should have hidden=True"

    # Verify all expected public agents exist and are NOT hidden
    for pub_id in EXPECTED_PUBLIC_AGENTS:
        assert pub_id in summary_map, f"Public agent '{pub_id}' missing from load_all_agents()"
        assert summary_map[pub_id].hidden is False, f"Public agent '{pub_id}' should have hidden=False"


def test_load_all_agents_strictly_excludes_template(temp_workspace: Path):
    """Verify load_all_agents strictly excludes _template/ from summaries."""
    agents_dir = temp_workspace / "agents"
    assert (agents_dir / TEMPLATE_DIR).is_dir(), "_template directory must exist on disk for this test"

    summaries = load_all_agents(agents_dir, temp_workspace / "skills")
    discovered_ids = {s.id for s in summaries}

    assert "_template" not in discovered_ids, "_template must NEVER be loaded into summaries"
    assert TEMPLATE_DIR not in discovered_ids


# ============================================================================
# 2. AgentRegistry Tests: Discovery, get(), and reload()
# ============================================================================


def test_agent_registry_reload_discovers_system_and_skips_template(temp_workspace: Path):
    """Verify AgentRegistry.reload() loads system agents, tags hidden=True, and skips _template."""
    agents_dir = temp_workspace / "agents"
    skills_dir = temp_workspace / "skills"

    registry = AgentRegistry(agents_dir, skills_dir)
    registered_ids = set(registry.list_agent_ids())

    # Verify system agents are registered
    for sys_id in EXPECTED_SYSTEM_AGENTS:
        assert sys_id in registered_ids, f"System agent '{sys_id}' missing from registry"
        manifest = registry.get(sys_id)
        assert manifest is not None
        assert manifest.hidden is True, f"Manifest for '{sys_id}' should have hidden=True"

    # Verify public agents are registered and not hidden
    for pub_id in EXPECTED_PUBLIC_AGENTS:
        assert pub_id in registered_ids, f"Public agent '{pub_id}' missing from registry"
        manifest = registry.get(pub_id)
        assert manifest is not None
        assert manifest.hidden is False, f"Manifest for '{pub_id}' should have hidden=False"

    # Verify _template is completely absent
    assert "_template" not in registered_ids
    assert TEMPLATE_DIR not in registered_ids
    assert registry.get("_template") is None
    assert registry.get(TEMPLATE_DIR) is None


def test_agent_registry_get_orchestrator(temp_workspace: Path):
    """Verify AgentRegistry.get('orchestrator') returns valid manifest with hidden=True."""
    agents_dir = temp_workspace / "agents"
    skills_dir = temp_workspace / "skills"

    registry = AgentRegistry(agents_dir, skills_dir)
    manifest = registry.get("orchestrator")

    assert manifest is not None
    assert manifest.id == "orchestrator"
    assert manifest.hidden is True
    assert manifest.can_delegate is True
    assert registry.has_agent("orchestrator") is True
    assert registry["orchestrator"].id == "orchestrator"


def test_agent_registry_get_template_returns_none(temp_workspace: Path):
    """Verify AgentRegistry.get('_template') strictly returns None and raises KeyError on [] access."""
    agents_dir = temp_workspace / "agents"
    skills_dir = temp_workspace / "skills"

    registry = AgentRegistry(agents_dir, skills_dir)

    assert registry.get("_template") is None
    assert registry.get("_system") is None
    assert registry.get(".git") is None
    assert registry.get("") is None
    assert registry.has_agent("_template") is False

    with pytest.raises(KeyError):
        _ = registry["_template"]


# ============================================================================
# 3. Adversarial Traversal Stress Testing: Synthetic Edge Cases
# ============================================================================


def _create_minimal_agent(agent_dir: Path, agent_id: str, title: str, can_delegate: bool = False):
    """Helper to generate a syntactically valid agent directory with agent.yaml."""
    agent_dir.mkdir(parents=True, exist_ok=True)
    manifest_yaml = f"""id: "{agent_id}"
title: "{title}"
version: "1.0.0"
risk_class: "wellness"
domain: "wellness"
category: "wellness.general"
description: "Synthetic test agent {title}"
can_delegate: {str(can_delegate).lower()}
persona:
  role: "Assistant for {title}"
tools: []
skills: []
"""
    (agent_dir / AGENT_MANIFEST_FILENAME).write_text(manifest_yaml, encoding="utf-8")


def test_synthetic_directory_traversal_filtering(tmp_path: Path):
    """Adversarial stress test: synthetic workspace with complex dot and underscore directory structures.

    Structure:
    agents/
      .git/
      .hidden_agent/ (with valid agent.yaml)
      _backup_agent/ (with valid agent.yaml)
      __pycache__/
      _draft/ (with valid agent.yaml)
      valid_public_1/ (valid)
      valid_public_2/ (valid)
      orphan_file.txt
      agent.yaml (stray file at root)
      _system/
        sys_agent_1/ (valid)
        sys_agent_2/ (valid)
        .internal_secret/ (with valid agent.yaml)
        _nested_temp/ (with valid agent.yaml)
        _template/ (with valid agent.yaml inside _system)
        __pycache__/
        stray_system_file.json
    """
    agents_dir = tmp_path / "agents"
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    # 1. Valid public agents
    _create_minimal_agent(agents_dir / "valid-public-1", "valid-public-1", "Public 1")
    _create_minimal_agent(agents_dir / "valid-public-2", "valid-public-2", "Public 2")

    # 2. Adversarial root entries (should be skipped)
    (agents_dir / ".git").mkdir(parents=True)
    _create_minimal_agent(agents_dir / ".hidden-agent", ".hidden-agent", "Hidden Dot Agent")
    _create_minimal_agent(agents_dir / "_backup-agent", "_backup-agent", "Backup Underscore Agent")
    (agents_dir / "__pycache__").mkdir(parents=True)
    _create_minimal_agent(agents_dir / "_draft", "_draft", "Draft Underscore Agent")
    _create_minimal_agent(agents_dir / "_template", "_template", "Template Agent")

    # Stray files at root
    (agents_dir / "orphan_file.txt").write_text("not a dir", encoding="utf-8")
    (agents_dir / "agent.yaml").write_text("id: stray", encoding="utf-8")

    # 3. System agents directory
    system_dir = agents_dir / SYSTEM_AGENTS_DIR
    _create_minimal_agent(system_dir / "sys-agent-1", "sys-agent-1", "System 1")
    _create_minimal_agent(system_dir / "sys-agent-2", "sys-agent-2", "System 2")

    # 4. Adversarial entries inside _system (should be skipped)
    (system_dir / ".git").mkdir(parents=True)
    _create_minimal_agent(system_dir / ".internal-secret", ".internal-secret", "Secret Dot System Agent")
    _create_minimal_agent(system_dir / "_nested-temp", "_nested-temp", "Nested Underscore System Agent")
    _create_minimal_agent(system_dir / "_template", "_template", "Nested Template inside System")
    (system_dir / "__pycache__").mkdir(parents=True)
    (system_dir / "stray_system_file.json").write_text("{}", encoding="utf-8")

    # --- Empirical Test A: load_all_agents() ---
    summaries = load_all_agents(agents_dir, skills_dir)
    discovered_ids = {s.id for s in summaries}

    expected_ids = {"valid-public-1", "valid-public-2", "sys-agent-1", "sys-agent-2"}
    assert discovered_ids == expected_ids, (
        f"load_all_agents() discovered {discovered_ids}, but expected strictly {expected_ids}"
    )

    summary_map = {s.id: s for s in summaries}
    assert summary_map["valid-public-1"].hidden is False
    assert summary_map["valid-public-2"].hidden is False
    assert summary_map["sys-agent-1"].hidden is True
    assert summary_map["sys-agent-2"].hidden is True

    # --- Empirical Test B: AgentRegistry.reload() ---
    registry = AgentRegistry(agents_dir, skills_dir)
    assert set(registry.list_agent_ids()) == expected_ids

    # Verify get() rejects all dot and underscore agents
    assert registry.get(".hidden-agent") is None
    assert registry.get("_backup-agent") is None
    assert registry.get("_draft") is None
    assert registry.get("_template") is None
    assert registry.get(".internal-secret") is None
    assert registry.get("_nested-temp") is None
    assert registry.get("_system") is None

    # Verify get() resolves valid agents
    m_pub = registry.get("valid-public-1")
    assert m_pub is not None and m_pub.hidden is False
    m_sys = registry.get("sys-agent-1")
    assert m_sys is not None and m_sys.hidden is True


def test_direct_system_directory_pointer(temp_workspace: Path):
    """Stress test: pointed directly at agents/_system instead of agents."""
    system_dir = temp_workspace / "agents" / SYSTEM_AGENTS_DIR
    skills_dir = temp_workspace / "skills"

    # load_all_agents when agents_dir is explicitly agents/_system
    summaries = load_all_agents(system_dir, skills_dir)
    discovered_ids = {s.id for s in summaries}

    assert EXPECTED_SYSTEM_AGENTS.issubset(discovered_ids)
    for s in summaries:
        assert s.hidden is True, f"All agents loaded directly from _system must have hidden=True, got {s.id}"

    # AgentRegistry when agents_dir is explicitly agents/_system
    registry = AgentRegistry(system_dir, skills_dir)
    for sys_id in EXPECTED_SYSTEM_AGENTS:
        manifest = registry.get(sys_id)
        assert manifest is not None
        assert manifest.hidden is True


def test_on_demand_resolution_of_late_added_system_agent(tmp_path: Path):
    """Verify registry on-demand fallback correctly resolves a system agent added after initialization."""
    agents_dir = tmp_path / "agents"
    system_dir = agents_dir / SYSTEM_AGENTS_DIR
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    _create_minimal_agent(agents_dir / "initial-public", "initial-public", "Initial Public")
    _create_minimal_agent(system_dir / "initial-sys", "initial-sys", "Initial Sys")

    registry = AgentRegistry(agents_dir, skills_dir)
    assert registry.list_agent_ids() == ["initial-public", "initial-sys"]

    # Now add a new system agent without calling reload()
    _create_minimal_agent(system_dir / "late-sys-agent", "late-sys-agent", "Late Sys Agent")

    # get() should resolve it on-demand from _system/ and set hidden=True
    late_manifest = registry.get("late-sys-agent")
    assert late_manifest is not None
    assert late_manifest.id == "late-sys-agent"
    assert late_manifest.hidden is True

    # Now add an adversarial underscore agent in _system
    _create_minimal_agent(system_dir / "_adversarial-late", "_adversarial-late", "Adversarial")
    assert registry.get("_adversarial-late") is None


# ============================================================================
# 4. Delegation Tools Fallback & Registry Hardening
# ============================================================================


def test_delegation_tool_fallback_and_system_agents(temp_workspace: Path):
    """Verify ListAgentsTool fallback format excludes orchestrator and _template, includes specialists."""
    # 1. Unregistered fallback execution
    tool_fallback = ListAgentsTool(registry=None)
    output_fallback = tool_fallback._run()

    # Orchestrator is excluded from specialist catalog
    assert AGENT_ORCHESTRATOR not in output_fallback
    assert "_template" not in output_fallback
    # document-extractor is a specialist in _system, should be present in delegatable catalog
    assert "document-extractor" in output_fallback

    # 2. Registered execution
    registry = AgentRegistry(temp_workspace / "agents", temp_workspace / "skills")
    tool_registered = ListAgentsTool(registry=registry)
    output_registered = tool_registered._run()

    assert AGENT_ORCHESTRATOR not in output_registered
    assert "_template" not in output_registered
    assert "document-extractor" in output_registered


# ============================================================================
# 5. API Layer Integration: Filtering, Details, and Edge Case Protection
# ============================================================================


def test_api_agents_list_hides_system_and_excludes_template(client: TestClient):
    """Verify GET /api/agents hides system agents by default and completely excludes _template."""
    # Default query: include_hidden=false
    res = client.get("/api/agents")
    assert res.status_code == 200
    data = res.json()
    ids = {a["id"] for a in data}

    assert "_template" not in ids
    for sys_id in EXPECTED_SYSTEM_AGENTS:
        assert sys_id not in ids, f"System agent '{sys_id}' leaked in default GET /api/agents"
    for pub_id in EXPECTED_PUBLIC_AGENTS:
        assert pub_id in ids, f"Public agent '{pub_id}' missing from GET /api/agents"

    # Query with include_hidden=true
    res_hidden = client.get("/api/agents?include_hidden=true")
    assert res_hidden.status_code == 200
    data_hidden = res_hidden.json()
    ids_hidden = {a["id"] for a in data_hidden}

    assert "_template" not in ids_hidden, "_template leaked when include_hidden=true"
    for sys_id in EXPECTED_SYSTEM_AGENTS:
        assert sys_id in ids_hidden
        item = next(a for a in data_hidden if a["id"] == sys_id)
        assert item["hidden"] is True
    for pub_id in EXPECTED_PUBLIC_AGENTS:
        assert pub_id in ids_hidden
        item = next(a for a in data_hidden if a["id"] == pub_id)
        assert item["hidden"] is False


def test_api_agents_detail_resolution_and_security(client: TestClient):
    """Verify GET /api/agents/{agent_id} resolves system agents and blocks dot/underscore traversal."""
    # Resolves orchestrator in _system/ with hidden=True
    res_orch = client.get("/api/agents/orchestrator")
    assert res_orch.status_code == 200
    data_orch = res_orch.json()
    assert data_orch["id"] == "orchestrator"
    assert data_orch["hidden"] is True

    # Resolves document-extractor in _system/ with hidden=True
    res_doc = client.get("/api/agents/document-extractor")
    assert res_doc.status_code == 200
    data_doc = res_doc.json()
    assert data_doc["id"] == "document-extractor"
    assert data_doc["hidden"] is True

    # Rejects _template with 404
    res_tmpl = client.get("/api/agents/_template")
    assert res_tmpl.status_code == 404

    # Rejects _system directory with 404
    res_sys = client.get("/api/agents/_system")
    assert res_sys.status_code == 404

    # Rejects dot prefixes
    res_dot = client.get("/api/agents/.git")
    assert res_dot.status_code == 404
